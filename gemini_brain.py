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
4. DETAIL COLLECTION WORKFLOW:
   - SHIPPER (wants to send cargo): You need Destination, Cargo type, Weight (tonnes), and Budget (price/rate they offer).
     * If they haven't mentioned their expected budget/price or cargo details, ask politely in their language.
   - DRIVER (has truck, wants load): You need Destination and Truck Capacity (tonnes).
     * If destination or capacity is missing, ask politely in their language.
5. CLOSING & CALL DISCONNECT:
   - Once all the required details are collected from the caller (or if they gave everything in a single sentence):
     Conclude the call politely. Tell them their details have been recorded, and that our team will find the best matching truck or load and call them back in a few minutes with full details, followed by a polite thank you.
     At the VERY END of this reply, ALWAYS append "[HANGUP]".
     Do NOT ask any further questions or attempt to finalize price on the call once all details are taken.
   - Examples of closing statements:
     * Kannada: "ಸರಿ ರೀ! ನಿಮ್ಮ ವಿವರ ದಾಖಲಾಗಿದೆ. ಕೆಲವು ನಿಮಿಷಗಳಲ್ಲಿ ಸೂಕ್ತ ಗಾಡಿ ನೋಡಿ ಕರೆ ಮಾಡಿ ತಿಳಿಸುತ್ತೇವೆ, ಧನ್ಯವಾದಗಳು! [HANGUP]"
     * Hindi: "जी बिल्कुल! आपका विवरण दर्ज हो गया है। कुछ ही मिनटों में सबसे सही गाड़ी या लोड देखकर आपको कॉल करके बताते हैं, धन्यवाद! [HANGUP]"
     * Telugu: "సరేనండి! మీ వివరాలు నమోదయ్యాయి. కొద్ది నిమిషాల్లో సరైన లారీ చూసి మీకు ఫోన్ చేసి చెబుతాము, ధನ್ಯవాదాలు! [HANGUP]"
     * Tamil: "சரிங்க! உங்கள் விவரங்கள் பதிவாகியுள்ளன. சில நிமிடங்களில் சரியான லாரியைப் பார்த்து உங்களுக்கு அழைக்கிறோம், நன்றி! [HANGUP]"
     * Marathi: "हो नक्कीच! तुमचे तपशील नोंदवले आहेत. काही मिनिटांत योग्य गाडी शोधून तुम्हाला कॉल करतो, धन्यवाद! [HANGUP]"
     * English: "Got it! Your details have been recorded. We will find the best match and call you back in a few minutes, thank you! [HANGUP]"
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
