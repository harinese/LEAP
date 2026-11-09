# -*- coding: utf-8 -*-
import os
import json
import logging
from typing import Dict, Any, Optional, List

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger("gemini_brain")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""

SYSTEM_INSTRUCTION = """You are the AI Voice Freight Coordinator for the National Freight Exchange (ರಾಷ್ಟ್ರೀಯ ಸರಕು ಸಾರಿಗೆ ಸೇತು / राष्ट्रीय माल भाड़ा सेतु).
You are speaking to real truck drivers and cargo shippers over a live mobile phone call.

CRITICAL RULES:
1. DETECT & MATCH LANGUAGE: You MUST reply in the EXACT SAME LANGUAGE and DIALECT the caller spoke (Kannada, Hindi, Marathi, Telugu, Tamil, Gujarati, Bengali, Malayalam, Punjabi, Indian English, etc.). Never change languages unless the caller switches.
2. LIVE TELEPHONY FORMAT: Keep your responses to 1 to 2 spoken sentences maximum. Do NOT use markdown, asterisks, bullet points, or emojis. Speak plain conversational sentences suitable for Text-to-Speech audio.
3. CONVERSATIONAL BROKER PERSONA: Sound like a sharp, friendly, polite Indian transport broker. Be natural, not robotic.
4. SHIPPER vs DRIVER FLOW:
   - SHIPPER (wants to send cargo): Extract Origin, Destination, Cargo type, Weight (tonnes), and Budget (Rs).
     * If they did not mention their price/budget, politely ask how much freight/rate they are offering for this load in their language.
     * Once all details (including their budget) are known, call search_and_match_load_tool to find an available truck.
   - DRIVER (has truck, wants load): Extract Destination and Truck Capacity (tonnes).
     * DO NOT ask the driver for a price. Call search_and_match_truck_tool to find available loads and quote the shipper's listed price!
5. DEAL CONFIRMATION: When the caller agrees ("yes", "okay", "ಸರಿ", "ಹೌದು", "ಹಾ", "ठीक है", "मंजूर", "సరే", "சரி", "confirm"), call confirm_deal_tool and state their NFX Waybill Token clearly.
"""

def get_gemini_client():
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or GEMINI_API_KEY
    if not api_key:
        return None
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        return genai
    except Exception as e:
        logger.error(f"Failed to initialize Gemini: {e}")
        return None

class GeminiConversation:
    def __init__(self, call_sid: str, caller_phone: str = ""):
        self.call_sid = call_sid
        self.caller_phone = caller_phone
        self.history = []
        self.detected_language = "kn"
        self.active_deal = None
        self.genai = get_gemini_client()
        self.model = None

        if self.genai:
            try:
                # Prefer gemini-2.5-flash or gemini-2.0-flash, fallback to gemini-1.5-flash
                model_name = "gemini-2.5-flash"
                try:
                    self.model = self.genai.GenerativeModel(
                        model_name=model_name,
                        system_instruction=SYSTEM_INSTRUCTION
                    )
                except Exception:
                    self.model = self.genai.GenerativeModel(
                        model_name="gemini-1.5-flash",
                        system_instruction=SYSTEM_INSTRUCTION
                    )
                logger.info(f"Gemini Conversation initialized with {self.model.model_name}")
            except Exception as e:
                logger.error(f"Error creating GenerativeModel: {e}")
                self.model = None

    def is_available(self) -> bool:
        return self.model is not None

    async def generate_reply(self, user_text: str, db_context: Dict[str, Any]) -> str:
        """
        Processes caller text with Gemini 2.0 / 1.5 Flash in < 400ms.
        Passes live SQLite inventory and caller role context so Gemini has full market awareness.
        """
        if not self.model:
            return ""

        import asyncio

        # Format compact inventory context for Gemini
        loads_summary = db_context.get("available_loads_summary", "No active loads")
        trucks_summary = db_context.get("available_trucks_summary", "No active trucks")
        caller_role = db_context.get("caller_role", "UNKNOWN")

        prompt = f"""[MARKET CONTEXT FOR THIS CALL]
Caller Phone: {self.caller_phone}
Caller Detected Role: {caller_role}
Current Live Available Loads in SQLite:
{loads_summary}
Current Live Available Trucks in SQLite:
{trucks_summary}

[CONVERSATION HISTORY]
{self._format_history()}

[CALLER SAID JUST NOW]
"{user_text}"

Respond naturally to the caller in the EXACT same language they spoke. Remember: 1-2 spoken sentences maximum, no markdown, no asterisks."""

        try:
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.model.generate_content(prompt)
            )

            reply = response.text.strip() if response and response.text else ""
            # Clean any accidental markdown formatting (TTS should speak clean prose)
            reply = reply.replace("**", "").replace("*", "").replace("#", "").strip()

            # Record in conversation history
            self.history.append({"role": "user", "text": user_text})
            self.history.append({"role": "model", "text": reply})

            # Detect language code for TTS voice selection
            self._update_detected_language(reply)

            return reply
        except Exception as e:
            logger.error(f"Gemini generation error: {e}")
            return ""

    def _format_history(self) -> str:
        if not self.history:
            return "No previous turns."
        lines = []
        for h in self.history[-6:]:  # Keep last 3 turns for fast inference
            role_label = "Caller" if h["role"] == "user" else "Assistant"
            lines.append(f"{role_label}: {h['text']}")
        return "\n".join(lines)

    def _update_detected_language(self, text: str):
        # Character range detection across Indian scripts
        for ch in text:
            if '\u0C80' <= ch <= '\u0CFF': # Kannada
                self.detected_language = "kn"
                return
            if '\u0C00' <= ch <= '\u0C7F': # Telugu
                self.detected_language = "te"
                return
            if '\u0B80' <= ch <= '\u0BFF': # Tamil
                self.detected_language = "ta"
                return
            if '\u0900' <= ch <= '\u097F': # Devanagari (Hindi / Marathi)
                # Check for Marathi specific markers
                if any(w in text for w in ["आहे", "नाही", "गाडी", "पुण्याहून"]):
                    self.detected_language = "mr"
                else:
                    self.detected_language = "hi"
                return
            if '\u0A80' <= ch <= '\u0AFF': # Gujarati
                self.detected_language = "gu"
                return
            if '\u0980' <= ch <= '\u09FF': # Bengali
                self.detected_language = "bn"
                return
            if '\u0D00' <= ch <= '\u0D7F': # Malayalam
                self.detected_language = "ml"
                return
        self.detected_language = "en"
