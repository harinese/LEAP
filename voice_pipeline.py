# -*- coding: utf-8 -*-
import io
import math
import re
import struct
import base64
import os
import asyncio
from typing import Tuple, Optional, Dict, Any, List

import edge_tts
import miniaudio
import speech_recognition as sr
import db_manager
import matching_engine
import gnani_client

KANNADA_NUMBERS = {
    "ಒಂದು": 1, "ಎರಡು": 2, "ಮೂರು": 3, "ನಾಲ್ಕು": 4, "ಐದು": 5,
    "ಆರು": 6, "ಏಳು": 7, "ಎಂಟು": 8, "ಒಂಬತ್ತು": 9, "ಹತ್ತು": 10,
    "ಹನ್ನೊಂದು": 11, "ಹನ್ನೆರಡು": 12, "ಹದಿಮೂರು": 13, "ಹದಿನಾಲ್ಕು": 14, "ಹದಿನೈದು": 15,
    "ಹದಿನಾರು": 16, "ಹದಿನೇಳು": 17, "ಹದಿನೆಂಟು": 18, "ಹತ್ತೊಂಬತ್ತು": 19, "ಇಪ್ಪತ್ತು": 20,
    "ಇಪ್ಪತ್ತೆರಡು": 22, "ಇಪ್ಪತ್ನಾಲ್ಕು": 24, "ಇಪ್ಪತ್ತೈದು": 25, "ಮೂವತ್ತು": 30
}

HINDI_NUMBERS = {
    "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पांच": 5,
    "छह": 6, "सात": 7, "आठ": 8, "नौ": 9, "दस": 10,
    "ग्यारह": 11, "बारह": 12, "तेरह": 13, "चौदह": 14, "पंद्रह": 15,
    "सोलह": 16, "सत्रह": 17, "अठारह": 18, "उन्नीस": 19, "बीस": 20,
    "पच्चीस": 25, "तीस": 30
}

DESTINATION_KEYWORDS = {
    "Bengaluru": ["ಬೆಂಗಳೂರ", "ಬೆಂಗಳೂರು", "bangalore", "bengaluru"],
    "Chitradurga": ["ಚಿತ್ರದುರ್ಗ", "chitradurga", "chithradurga"],
    "Davanagere": ["ದಾವಣಗೆರೆ", "davanagere", "davangere"],
    "Belagavi": ["ಬೆಳಗಾವಿ", "belgaum", "belagavi"],
    "Haveri": ["ಹಾವೇರಿ", "haveri"],
    "Gadag": ["ಗದಗ", "gadag"],
    "Ballari": ["ಬಳ್ಳಾರಿ", "ballari", "bellary"],
    "Shivamogga": ["ಶಿವಮೊಗ್ಗ", "shivamogga", "shimoga"],
    "Bagalkot": ["ಬಾಗಲಕೋಟ", "ಬಾಗಲಕೋಟೆ", "bagalkot", "bagalkote"],
    "Mangaluru": ["ಮಂಗಳೂರ", "ಮಂಗಳೂರು", "mangaluru", "mangalore"],
    "Mysuru": ["ಮೈಸೂರ", "ಮೈಸೂರು", "mysuru", "mysore"],
    "Tumakuru": ["ತುಮಕೂರ", "ತುಮಕೂರು", "tumakuru", "tumkur"],
    "Raichur": ["ರಾಯಚೂರ", "ರಾಯಚೂರು", "raichur"],
    "Koppal": ["ಕೊಪ್ಪಳ", "koppal"],
    "Vijayapura": ["ವಿಜಯಪುರ", "ಬಿಜಾಪುರ", "vijayapura", "bijapur"],
    "Kalaburagi": ["ಕಲಬುರಗಿ", "ಗುಲ್ಬರ್ಗ", "kalaburagi", "gulbarga"],
    "Hassan": ["ಹಾಸನ", "hassan"],
    "Udupi": ["ಉಡುಪಿ", "udupi"],
    "Karwar": ["ಕಾರವಾರ", "ಅಂಕೋಲಾ", "karwar"],
    "Hubballi": ["ಹುಬ್ಬಳ್ಳಿ", "ಧಾರವಾಡ", "hubballi", "hubli", "dharwad"],
    "Pune": ["ಪುಣೆ", "pune", "poona"],
    "Goa": ["ಗೋವಾ", "ಪಣಜಿ", "goa", "panaji"],
    "Mumbai": ["ಮುಂಬೈ", "ಮುಂಬಯಿ", "mumbai", "bombay"],
    "Hyderabad": ["ಹೈದರಾಬಾದ್", "hyderabad"],
    "Chennai": ["ಚೆನ್ನೈ", "ಮದ್ರಾಸ್", "chennai"],
    "Delhi": ["ದೆಹಲಿ", "ದಿಲ್ಲಿ", "delhi", "new delhi"],
    "Ahmedabad": ["ಅಹಮದಾಬಾದ್", "ahmedabad", "amdavad"],
    "Kolkata": ["ಕೋಲ್ಕತ್ತಾ", "ಕಲ್ಕತ್ತಾ", "kolkata", "calcutta"],
}

DEST_DISPLAY_KN = {
    "Bengaluru": "ಬೆಂಗಳೂರು",
    "Chitradurga": "ಚಿತ್ರದುರ್ಗ",
    "Davanagere": "ದಾವಣಗೆರೆ",
    "Belagavi": "ಬೆಳಗಾವಿ",
    "Haveri": "ಹಾವೇರಿ",
    "Gadag": "ಗದಗ",
    "Ballari": "ಬಳ್ಳಾರಿ",
    "Shivamogga": "ಶಿವಮೊಗ್ಗ",
    "Bagalkot": "ಬಾಗಲಕೋಟೆ",
    "Mangaluru": "ಮಂಗಳೂರು",
    "Mysuru": "ಮೈಸೂರು",
    "Tumakuru": "ತುಮಕೂರು",
    "Raichur": "ರಾಯಚೂರು",
    "Koppal": "ಕೊಪ್ಪಳ",
    "Vijayapura": "ವಿಜಯಪುರ",
    "Kalaburagi": "ಕಲಬುರಗಿ",
    "Hassan": "ಹಾಸನ",
    "Udupi": "ಉಡುಪಿ",
    "Karwar": "ಕಾರವಾರ",
    "Hubballi": "ಹುಬ್ಬಳ್ಳಿ",
    "Pune": "ಪುಣೆ",
    "Goa": "ಗೋವಾ",
    "Mumbai": "ಮುಂಬೈ",
    "Hyderabad": "ಹೈದರಾಬಾದ್",
    "Chennai": "ಚೆನ್ನೈ",
    "Delhi": "ದೆಹಲಿ",
    "Ahmedabad": "ಅಹಮದಾಬಾದ್",
    "Kolkata": "ಕೋಲ್ಕತ್ತಾ",
}

def get_destination_display(dest: str, lang: str = "kn") -> str:
    if not dest:
        return "ಬೆಂಗಳೂರು" if lang == "kn" else "Bengaluru"
    if lang == "kn":
        return DEST_DISPLAY_KN.get(dest, dest)
    return dest


def detect_language(text: str) -> str:
    for ch in text:
        if '\u0C00' <= ch <= '\u0C7F':
            return 'te'
        if '\u0C80' <= ch <= '\u0CFF':
            return 'kn'
        if '\u0B80' <= ch <= '\u0BFF':
            return 'ta'
        if '\u0900' <= ch <= '\u097F':
            if any(w in text for w in ["आहे", "नाही", "गाडी", "पुण्याहून"]):
                return 'mr'
            return 'hi'
        if '\u0A80' <= ch <= '\u0AFF':
            return 'gu'
        if '\u0980' <= ch <= '\u09FF':
            return 'bn'
        if '\u0D00' <= ch <= '\u0D7F':
            return 'ml'
    return 'en'

def calculate_rms(pcm_bytes: bytes) -> float:
    if not pcm_bytes:
        return 0.0
    count = len(pcm_bytes) // 2
    if count == 0:
        return 0.0
    shorts = struct.unpack(f"<{count}h", pcm_bytes)
    sum_squares = sum(s * s for s in shorts)
    return math.sqrt(sum_squares / count)

def normalize_pcm(pcm_bytes: bytes, target_peak: int = 24000) -> bytes:
    if not pcm_bytes:
        return pcm_bytes
    count = len(pcm_bytes) // 2
    shorts = list(struct.unpack(f"<{count}h", pcm_bytes))
    max_val = max(abs(s) for s in shorts) if shorts else 0
    if max_val == 0 or max_val >= target_peak:
        return pcm_bytes
    factor = min(3.5, target_peak / max_val)
    normalized = [min(32767, max(-32768, int(s * factor))) for s in shorts]
    return struct.pack(f"<{count}h", *normalized)

class VoicePipeline:
    def __init__(self, stream_sid: str, call_sid: str = "", caller_phone: str = ""):
        self.stream_sid = stream_sid
        self.call_sid = call_sid or stream_sid
        self.caller_phone = caller_phone
        self.language = "kn"
        self.state = "ROUTE_SELECTION"
        self.role = "UNKNOWN"
        self.current_truck_id: Optional[int] = None
        self.current_load_id: Optional[int] = None
        self.current_match: Optional[Dict[str, Any]] = None
        self.is_callback_flow = False
        self.extracted_data: Dict[str, Any] = {
            "origin": "Bengaluru",
            "destination": "",
            "capacity": None,
            "cargo_type": None,
            "vehicle_type": "Truck",
            "name": None,
            "price": None,
            "rate": None
        }
        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold = 260
        self.recognizer.dynamic_energy_threshold = True

        # Check if caller has an active pending match waiting for confirmation
        self.check_pending_callback_match()

    def check_pending_callback_match(self):
        if not self.caller_phone:
            return
        conn = db_manager.get_connection()
        cursor = conn.cursor()
        query = """
            SELECT m.*, 
                   t.phone as driver_phone, t.driver_name, t.truck_type, t.capacity_tonnes, t.current_location as truck_loc,
                   l.cargo_type, l.weight_tonnes, l.pickup_location, l.destination, l.shipper_name, l.phone as shipper_phone
            FROM matches m
            JOIN trucks t ON m.truck_id = t.id
            JOIN loads l ON m.load_id = l.id
            WHERE (t.phone = ? OR l.phone = ?) AND m.status = 'OFFERED'
            ORDER BY m.created_at DESC LIMIT 1
        """
        cursor.execute(query, (self.caller_phone, self.caller_phone))
        row = cursor.fetchone()
        conn.close()

        if row:
            self.current_match = dict(row)
            self.current_match["match_id"] = row["id"]
            self.current_match["booking_token"] = row["booking_token"]
            self.state = "CALLBACK_CONFIRMATION"
            self.is_callback_flow = True
            if row["shipper_phone"] == self.caller_phone:
                self.role = "SHIPPER"
            else:
                self.role = "DRIVER"

    async def transcribe(self, pcm_data: bytes) -> str:
        if len(pcm_data) < 3200:
            return ""

        # 1. Primary: Gnani Prisma STT (v3.0) with indic-auto multilingual detection
        try:
            gnani_text = await gnani_client.transcribe_gnani(pcm_data, language_code="indic-auto")
            if gnani_text and len(gnani_text.strip()) > 1:
                transcription = gnani_text.strip()
                self.language = detect_language(transcription)
                logger.info(f"Gnani STT Detected ({self.language}): {transcription}")
                return transcription
        except Exception as e:
            logger.debug(f"Gnani STT error: {e}")

        # 2. Resilient Concurrent Fallback: Google Speech Recognition across Indic languages
        normalized_data = normalize_pcm(pcm_data)
        audio = sr.AudioData(normalized_data, 8000, 2)

        lang_code_map = {
            "te": "te-IN",
            "kn": "kn-IN",
            "hi": "hi-IN",
            "ta": "ta-IN",
            "mr": "mr-IN",
            "en": "en-IN"
        }
        current_code = lang_code_map.get(self.language, "kn-IN")
        all_langs = ["te-IN", "kn-IN", "hi-IN", "ta-IN", "mr-IN", "en-IN"]
        ordered_langs = [current_code] + [l for l in all_langs if l != current_code]

        async def try_recognize(lang):
            try:
                t = await asyncio.to_thread(self.recognizer.recognize_google, audio, language=lang)
                if t and len(t.strip()) > 1:
                    return t.strip()
            except Exception:
                return ""
            return ""

        # Try prioritized language first
        transcription = await try_recognize(ordered_langs[0])
        if transcription:
            self.language = detect_language(transcription)
            return transcription

        # If empty, race remaining Indic languages concurrently!
        alternates = ordered_langs[1:]
        results = await asyncio.gather(*(try_recognize(l) for l in alternates))
        for res in results:
            if res:
                transcription = res
                self.language = detect_language(transcription)
                return transcription

        return ""

    def extract_entities(self, text: str):
        lower = text.lower()

        # Origin identification (National Corridors)
        ORIGIN_PATTERNS = {
            "Bengaluru": ["ಬೆಂಗಳೂರಿನಿಂದ", "ಬೆಂಗಳೂರಿಂದ", "from bangalore", "from bengaluru"],
            "Mumbai": ["ಮುಂಬೈನಿಂದ", "from mumbai", "from bombay"],
            "Pune": ["ಪುಣೆಯಿಂದ", "from pune"],
            "Delhi": ["ದೆಹಲಿಯಿಂದ", "ದಿಲ್ಲಿಯಿಂದ", "from delhi"],
            "Hyderabad": ["ಹೈದರಾಬಾದ್‌ನಿಂದ", "ಹೈದರಾಬಾದಿಂದ", "from hyderabad"],
            "Chennai": ["ಚೆನ್ನೈನಿಂದ", "from chennai"],
            "Hubballi": ["ಹುಬ್ಬಳ್ಳಿಯಿಂದ", "ಧಾರವಾಡದಿಂದ", "from hubballi", "from hubli", "ಅಮರಗೋಳದಿಂದ"],
            "Davanagere": ["ದಾವಣಗೆರೆಯಿಂದ", "from davanagere"],
            "Belagavi": ["ಬೆಳಗಾವಿಯಿಂದ", "from belagavi", "from belgaum"],
        }
        for city, patterns in ORIGIN_PATTERNS.items():
            if any(p in text or p in lower for p in patterns):
                self.extracted_data["origin"] = city
                break

        # Destination extraction
        found_dest = False
        for canonical, keywords in DESTINATION_KEYWORDS.items():
            if any(k in text or k in lower for k in keywords):
                self.extracted_data["destination"] = canonical
                found_dest = True
                break

        # Fallback when caller answers in ROUTE_SELECTION and city is not in predefined list
        if not found_dest and not self.extracted_data.get("destination") and self.state == "ROUTE_SELECTION":
            cleaned = text
            stopwords = [
                "ನಮಸ್ಕಾರ", "ರೀ", "ಹಲೋ", "ಸರ್", "ನಮಸ್ತೆ", "hello", "hi",
                "ಹೋಗಬೇಕು", "ಹೋಗ್ಬೇಕು", "ಹೋಗುವುದು", "ಹೋಗಿ", "ಕಳಿಸಬೇಕು", "ಕಳಿಸಬೇಕಾಗಿದೆ",
                "ಲೋಡ್", "ಗಾಡಿ", "ಲಾರಿ", "ಟ್ರಕ್", "ಇದೆ", "ಬೇಕು", "ಐತಿ",
                "jana hai", "bhejna", "hai", "chahiye", "to", "send", "going"
            ]
            for sw in stopwords:
                cleaned = re.sub(rf'\b{re.escape(sw)}\b', ' ', cleaned, flags=re.IGNORECASE)
                cleaned = cleaned.replace(sw, ' ')

            # Strip trailing Kannada case markers: -ಕ್ಕೆ, -ಗೆ, -ಅಲ್ಲಿಗೆ, -ಕಡೆಗೆ, -ಕಡೆ
            cleaned = re.sub(r'(?:ಕ್ಕೆ|ಗೆ|ಅಲ್ಲಿಗೆ|ಕಡೆಗೆ|ಕಡೆ)$', '', cleaned.strip()).strip()

            tokens = [w.strip() for w in re.split(r'[\s,]+', cleaned) if len(w.strip()) >= 2]
            if tokens:
                cand = tokens[0]
                if not re.search(r'\d', cand) and cand.lower() not in ["yes", "no", "ok", "sari", "houdu"]:
                    self.extracted_data["destination"] = cand.capitalize()

        # Vehicle Type extraction
        if any(w in text for w in ["ಹತ್ತು ಚಕ್ರ", "10 ಚಕ್ರ"]) or "10 wheeler" in lower:
            self.extracted_data["vehicle_type"] = "10-Wheeler"
            if not self.extracted_data["capacity"]:
                self.extracted_data["capacity"] = 16.0
        elif any(w in text for w in ["ಆರು ಚಕ್ರ", "6 ಚಕ್ರ"]) or "6 wheeler" in lower:
            self.extracted_data["vehicle_type"] = "6-Wheeler"
            if not self.extracted_data["capacity"]:
                self.extracted_data["capacity"] = 9.0
        elif "ಐಷರ್" in text or "eicher" in lower:
            self.extracted_data["vehicle_type"] = "Eicher 14ft"
            if not self.extracted_data["capacity"]:
                self.extracted_data["capacity"] = 4.0

        # Spoken numbers conversion
        for word, val in KANNADA_NUMBERS.items():
            if word in text:
                self.extracted_data["capacity"] = float(val)
                break
        for word, val in HINDI_NUMBERS.items():
            if word in text:
                self.extracted_data["capacity"] = float(val)
                break

        # Digit regex capacity extraction (e.g., "4 tonne", "4000 kg", "16 ton")
        kg_match = re.search(r'(\d{3,5})\s*(?:kg|ಕೆಜಿ)', text, re.IGNORECASE)
        if kg_match:
            try:
                self.extracted_data["capacity"] = float(kg_match.group(1)) / 1000.0
            except ValueError:
                pass

        tonne_explicit = re.search(r'(\d+(?:\.\d+)?)\s*(?:ಟನ್|ton|tonne|tonnes)', text, re.IGNORECASE)
        if tonne_explicit:
            try:
                val = float(tonne_explicit.group(1))
                if 0.5 <= val <= 60.0:
                    self.extracted_data["capacity"] = val
            except ValueError:
                pass

        # Cargo / Produce extraction
        if any(w in text for w in ["ಈರುಳ್ಳಿ", "ಉಳ್ಳಾಗಡ್ಡಿ"]) or "onion" in lower:
            self.extracted_data["cargo_type"] = "Onions"
        elif any(w in text for w in ["ಮೆಣಸಿನಕಾಯಿ", "ಬ್ಯಾಡಗಿ"]) or "chilli" in lower:
            self.extracted_data["cargo_type"] = "Dry Red Chilli"
        elif "ಟೊಮ್ಯಾಟೊ" in text or "tomato" in lower:
            self.extracted_data["cargo_type"] = "Tomato"
        elif "ಹತ್ತಿ" in text or "cotton" in lower:
            self.extracted_data["cargo_type"] = "Cotton"
        elif "ಜೋಳ" in text or "maize" in lower:
            self.extracted_data["cargo_type"] = "Maize"

        # Role detection
        shipper_keywords = [
            "ಲೋಡ್ ಇದೆ", "ಕಳಿಸಬೇಕು", "ಕಳಿಸಬೇಕಾಗಿದೆ", "ಮಾಲು ಇದೆ", "ಮಾಲು", "ರೈತ", "ವ್ಯಾಪಾರಿ", "ಮಂಡಿ",
            "load hai", "bhejna", "kisaan", "vyapari", "maal hai", "maal",
            "load available", "dispatch", "send cargo", "have load", "want to send", "goods"
        ]
        driver_keywords = [
            "ಲೋಡ್ ಬೇಕು", "ಗಾಡಿ ಇದೆ", "ಟ್ರಕ್ ಇದೆ", "ಲಾರಿ ಇದೆ", "ಖಾಲಿ ಇದೆ", "ಡ್ರೈವರ್", "ಚಕ್ರ", "ಲಾರಿ", "ಟ್ರಕ್", "ಗಾಡಿ",
            "load chahiye", "gaadi hai", "truck hai", "khali", "driver", "gaadi", "lorry",
            "need load", "truck available", "empty truck", "return load"
        ]

        if any(w in text or w in lower for w in shipper_keywords) or (self.extracted_data.get("cargo_type") and not any(w in text or w in lower for w in driver_keywords)):
            self.role = "SHIPPER"
        elif any(w in text or w in lower for w in driver_keywords):
            self.role = "DRIVER"

        # Name extraction (Kannada, Hindi, English)
        name_match = re.search(r'(?:ನನ್ನ ಹೆಸರು|ಹೆಸರು|ನಾನು|mera naam|naam|my name is|i am)\s+([a-zA-Z\u0C80-\u0CFF\u0900-\u097F]+)', text, re.IGNORECASE)
        if name_match:
            cand = name_match.group(1).strip()
            if cand.lower() not in ["truck", "lorry", "gaadi", "load", "driver", "vyapari", "raita", "malu", "agri"]:
                self.extracted_data["name"] = cand.capitalize()

        # Price / Budget extraction
        rate_explicit = re.search(r'(?:rate|price|ಬಾಡಿಗೆ|kiraya|ಕಿರಾ|rs|ರೂ)\s*(?:is|of|ide|beku|kodtini)?\s*(\d{3,6})', text, re.IGNORECASE)
        price_explicit = re.search(r'(\d{3,6})\s*(?:rate|price|rs|rupees|ರೂಪಾಯಿ|ರೂ|ಬಾಡಿಗೆ|rupaye|kiraya|ಕಿರಾ|ಕೊಡ್ತೀನಿ|ಬೇಕು)', text, re.IGNORECASE)
        if rate_explicit:
            try:
                self.extracted_data["price"] = float(rate_explicit.group(1))
            except ValueError:
                pass
        elif price_explicit:
            try:
                self.extracted_data["price"] = float(price_explicit.group(1))
            except ValueError:
                pass
        elif not self.extracted_data.get("price"):
            standalone_num = re.search(r'\b(\d{3,6})\b', text)
            if standalone_num:
                val = float(standalone_num.group(1))
                if 500 <= val <= 200000 and val != self.extracted_data.get("capacity"):
                    self.extracted_data["price"] = val

    def is_affirmative(self, text: str) -> bool:
        lower = text.lower()
        affirmative_words = [
            "ಹೌದು", "ಸರಿ", "ಒಪ್ಪುತ್ತೇನೆ", "ಆಯ್ತು", "ಮಾಡಿ", "ಖಂಡಿತ", "ಹಾ", "ಹೌದ್ರಿ", "ಆಯ್ತ್ರಿ", "ಪಕ್ಕಾ",
            "हाँ", "हा", "पक्का", "ठीक", "कर दो", "चलेगा", "मंजूर",
            "yes", "ok", "okay", "agree", "confirm", "done", "sure", "fine"
        ]
        return any(w in lower or w in text for w in affirmative_words)

    def is_negative(self, text: str) -> bool:
        lower = text.lower()
        negative_words = [
            "ಬೇಡ", "ಇಲ್ಲ", "ಕ್ಯಾನ್ಸಲ್", "ಬೇಡ್ರಿ", "ಇಲ್ಲ್ರಿ",
            "नहीं", "ना", "मत करो", "कैंसिल",
            "no", "nope", "cancel", "dont", "don't"
        ]
        return any(w in lower or w in text for w in negative_words)

    def process_turn(self, user_text: str) -> str:
        lang = self.language

        # 1. Flow for caller calling back to confirm SMS recommendation
        if self.state == "CALLBACK_CONFIRMATION" and self.current_match:
            if self.is_affirmative(user_text):
                self.state = "COMPLETED"
                token = self.current_match["booking_token"]
                matching_engine.confirm_match(
                    match_id=self.current_match["match_id"],
                    truck_id=self.current_match.get("truck_id"),
                    load_id=self.current_match.get("load_id")
                )

                if self.role == "SHIPPER":
                    driver = self.current_match.get("driver_name", "ಚಾಲಕ")
                    phone = self.current_match.get("driver_phone", "")
                    truck = self.current_match.get("truck_type", "ಗಾಡಿ")

                    if lang == "kn":
                        return f"ತುಂಬಾ ಒಳ್ಳೆಯದು ರೀ! ನಿಮ್ಮ ಡೀಲ್ ದೃಢಪಟ್ಟಿದೆ. ಗೇಟ್ ಪಾಸ್ ಟೋಕನ್ {token}. ಚಾಲಕ {driver} ({truck}), ಅವರ ಫೋನ್ {phone}. ಧನ್ಯವಾದಗಳು ರೀ!"
                    elif lang == "hi":
                        return f"बधाई हो जी! डील पक्की हो गई। आपका गेट पास टोकन {token} है। ड्राइवर {driver} ({truck}), उनका फोन {phone} है। धन्यवाद!"
                    else:
                        return f"Deal confirmed! Your gate pass token is {token}. Driver {driver} ({truck}), phone {phone}. Thank you!"
                else:
                    shipper = self.current_match.get("shipper_name", "ವ್ಯಾಪಾರಿ")
                    phone = self.current_match.get("shipper_phone", "")

                    if lang == "kn":
                        return f"ತುಂಬಾ ಒಳ್ಳೆಯದು ರೀ! ನಿಮ್ಮ ಡೀಲ್ ದೃಢಪಟ್ಟಿದೆ. ಗೇಟ್ ಪಾಸ್ ಟೋಕನ್ {token}. ವ್ಯಾಪಾರಿ {shipper}, ಅವರ ಫೋನ್ {phone}. ಧನ್ಯವಾದಗಳು ರೀ!"
                    elif lang == "hi":
                        return f"बधाई हो जी! डील पक्की हो गई। आपका गेट पास टोकन {token} है। व्यापारी {shipper}, उनका फोन {phone} है। धन्यवाद!"
                    else:
                        return f"Deal confirmed! Your gate pass token is {token}. Shipper {shipper}, phone {phone}. Thank you!"
            else:
                self.state = "ROUTE_SELECTION"
                if lang == "kn":
                    return "ಸರಿ ರೀ. ನಿಮಗೆ ಬೇರೆ ಊರಿಗೆ ಲೋಡ್ ಬೇಕಾ? ಎಲ್ಲಿಗೆ ಹೊರಡಬೇಕು ಅಂತ ಹೇಳಿ."
                else:
                    return "Understood. Which other destination are you looking for?"

        # 2. Check if caller is confirming or rejecting an offered deal
        if self.state == "DEAL_OFFER":
            if self.is_affirmative(user_text) and self.current_match:
                self.state = "COMPLETED"
                token = self.current_match["booking_token"]

                matching_engine.confirm_match(
                    match_id=self.current_match["match_id"],
                    truck_id=self.current_truck_id or self.current_match.get("truck_id"),
                    load_id=self.current_load_id or self.current_match.get("load_id")
                )

                if self.role == "SHIPPER":
                    driver = self.current_match.get("driver_name", "ಚಾಲಕ")
                    phone = self.current_match.get("driver_phone", "")
                    truck = self.current_match.get("truck_type", "ಗಾಡಿ")

                    if lang == "kn":
                        return f"ತುಂಬಾ ಒಳ್ಳೆಯದು ರೀ! ಡೀಲ್ ಪಕ್ಕಾ ಆಯ್ತು. ನಿಮ್ಮ ಗೇಟ್ ಪಾಸ್ ಟೋಕನ್ {token}. ಚಾಲಕ {driver} ({truck}), ಅವರ ಫೋನ್ {phone}. ಧನ್ಯವಾದಗಳು ರೀ!"
                    elif lang == "hi":
                        return f"बधाई हो जी! डील पक्की हो गई। गेट पास टोकन {token} है। ड्राइवर {driver} ({truck}), उनका फोन {phone} है। धन्यवाद!"
                    else:
                        return f"Deal confirmed! Gate pass token is {token}. Driver {driver} phone {phone}. Thank you!"
                else:
                    shipper = self.current_match.get("shipper_name", "ವ್ಯಾಪಾರಿ")
                    phone = self.current_match.get("shipper_phone", "")

                    if lang == "kn":
                        return f"ತುಂಬಾ ಒಳ್ಳೆಯದು ರೀ! ಡೀಲ್ ಪಕ್ಕಾ ಆಯ್ತು. ನಿಮ್ಮ ಗೇಟ್ ಪಾಸ್ ಟೋಕನ್ {token}. ವ್ಯಾಪಾರಿ {shipper}, ಅವರ ಫೋನ್ {phone}. ಧನ್ಯವಾದಗಳು ರೀ!"
                    elif lang == "hi":
                        return f"बधाई हो जी! आपकी डील पक्की हो गई। गेट पास टोकन {token} है। व्यापारी {shipper}, उनका फोन {phone} है। धन्यवाद!"
                    else:
                        return f"Deal confirmed! Gate pass token is {token}. Trader {shipper}, phone {phone}. Thank you!"
            elif self.is_negative(user_text):
                self.state = "ROUTE_SELECTION"
                self.extracted_data["destination"] = ""
                self.extracted_data["capacity"] = None
                self.current_match = None
                if lang == "kn":
                    return "ಸರಿ ರೀ. ನಿಮಗೆ ಬೇರೆ ಯಾವ ಊರಿಗೆ ಲೋಡ್ ಬೇಕು ಅಂತ ಹೇಳಿ."
                elif lang == "hi":
                    return "जी ठीक है। आपको किस दूसरे शहर के लिए लोड चाहिए?"
                else:
                    return "Understood. Which other destination are you looking for?"
            else:
                if lang == "kn":
                    return "ಡೀಲ್ ಪಕ್ಕಾ ಮಾಡಲು 'ಸರಿ' ಅಥವಾ 'ಹೌದು' ಎನ್ನಿ ರೀ. ಬೇರೆ ಊರಿಗೆ ಬೇಕಿದ್ದರೆ ಊರಿನ ಹೆಸರು ಹೇಳಿ."
                elif lang == "hi":
                    return "डील पक्की करने के लिए 'हाँ' या 'ठीक है' बोलिए, या दूसरे शहर का नाम बताएं।"
                else:
                    return "To confirm the deal please say 'yes' or 'confirm', or name another city."

        # 2.5 Handle PRICE_COLLECTION state: shipper is telling us their price
        if self.state == "PRICE_COLLECTION":
            self.extract_entities(user_text)
            price = self.extracted_data.get("price")
            if not price:
                if lang == "kn":
                    return "ಬಾಡಿಗೆ ಎಷ್ಟು ಕೊಡ್ತೀರಿ ಅಂತ ಹೇಳಿ ರೀ? ಉದಾಹರಣೆಗೆ 5000 ರೂಪಾಯಿ ಅಥವಾ 15000 ರೂಪಾಯಿ."
                elif lang == "hi":
                    return "किराया कितना देंगे बताइए? जैसे 5000 रुपये या 15000 रुपये।"
                else:
                    return "Please tell me the rate you are offering. For example, 5000 rupees or 15000 rupees."
            # Price collected, now proceed to section 5 matching
            self.state = "ROUTE_SELECTION"

        # 2.5 Handle PRICE_COLLECTION state: shipper is telling us their price
        if self.state == "PRICE_COLLECTION":
            self.extract_entities(user_text)
            price = self.extracted_data.get("price")
            if not price:
                if lang == "kn":
                    return "ಬಾಡಿಗೆ ಎಷ್ಟು ಕೊಡ್ತೀರಿ ಅಂತ ಹೇಳಿ ರೀ? ಉದಾಹರಣೆಗೆ 5000 ರೂಪಾಯಿ ಅಥವಾ 15000 ರೂಪಾಯಿ."
                elif lang == "hi":
                    return "किराया कितना देंगे बताइए? जैसे 5000 रुपये या 15000 रुपये।"
                else:
                    return "Please tell me the rate you are offering. For example, 5000 rupees or 15000 rupees."
            # Price collected, now proceed to section 5 matching
            self.state = "ROUTE_SELECTION"

        self.extract_entities(user_text)
        dest = self.extracted_data.get("destination")
        cap = self.extracted_data.get("capacity")

        # 3. Route destination check
        if not dest:
            self.state = "ROUTE_SELECTION"
            if lang == "kn":
                return "ಸರಿ ರೀ. ಯಾವ ಊರಿನಿಂದ ಯಾವ ಊರಿಗೆ ಹೋಗಬೇಕು ಅಥವಾ ಎಲ್ಲಿಗೆ ಲೋಡ್ ಕಳಿಸಬೇಕು ಅಂತ ಹೇಳಿ."
            elif lang == "hi":
                return "जी ठीक है। किस शहर से किस शहर जाना है या कहाँ लोड भेजना है?"
            else:
                return "Understood. Which city are you heading to or sending goods to?"

        # 4. Capacity / tonnage check
        if not cap:
            self.state = "CAPACITY_CONFIRMATION"
            target = get_destination_display(dest, lang)
            if self.role == "SHIPPER":
                if lang == "kn":
                    return f"ಖಂಡಿತ ರೀ! {target} ಮಾರ್ಗಕ್ಕೆ ಗಾಡಿಗಳು ಲಭ್ಯವಿವೆ. ನಿಮ್ಮ ಬಳಿ ಎಷ್ಟು ಟನ್ ಮತ್ತು ಯಾವ ಮಾಲು ಇದೆ ರೀ?"
                elif lang == "hi":
                    return f"नमस्ते जी! {target} के लिए गाड़ियां उपलब्ध हैं। आपके पास कितना टन और क्या माल है?"
                else:
                    return f"Trucks available for {target}. How many tonnes and what cargo do you have?"
            else:
                if lang == "kn":
                    return f"ಖಂಡಿತ ರೀ! {target}ಗೆ ಹೋಗಲು ಲೋಡ್ ರೆಡಿ ಇದೆ. ನಿಮ್ಮ ಗಾಡಿ ಸಾಮರ್ಥ್ಯ ಎಷ್ಟು ಟನ್ ಐತಿ ರೀ?"
                elif lang == "hi":
                    return f"नमस्ते भाईसाहब! {target} के लिए लोड तुरंत मिल जाएगा। आपकी गाड़ी कितने टन की है?"
                else:
                    return f"Sure! Ready loads available for {target}. What is your truck capacity in tonnes?"

        # 4.5 SHIPPER PRICE CHECK: If shipper has destination+capacity but no price, ask for it
        if self.role == "SHIPPER" and not self.extracted_data.get("price"):
            self.state = "PRICE_COLLECTION"
            target = get_destination_display(dest, lang)
            if lang == "kn":
                return f"ಸರಿ ರೀ! {target}ಗೆ {int(float(cap))} ಟನ್ ಲೋಡ್ ಇದೆ ಅಂತ ಗೊತ್ತಾಯ್ತು. ಬಾಡಿಗೆ ಎಷ್ಟು ಕೊಡ್ತೀರಿ ಅಂತ ಹೇಳಿ ರೀ?"
            elif lang == "hi":
                return f"ठीक है जी! {target} के लिए {int(float(cap))} टन लोड समझ गया। किराया कितना देंगे बताइए?"
            else:
                return f"Got it! {int(float(cap))} tonnes to {target}. What rate are you offering for this load?"

        # 5. Destination & Capacity known -> Instant Registration & Marketplace matching
        if self.role == "SHIPPER":
            tonnes = float(cap)
            cargo = self.extracted_data.get("cargo_type") or "General Goods"
            shipper_name = self.extracted_data.get("name") or "ವ್ಯಾಪಾರಿ"
            max_budget = float(self.extracted_data.get("price") or 0.0)

            self.current_load_id = db_manager.register_load(
                phone=self.caller_phone or "+919448011999",
                destination=dest,
                weight=tonnes,
                cargo=cargo,
                shipper_name=shipper_name,
                max_budget=max_budget,
                call_sid=self.call_sid
            )

            match = matching_engine.find_best_truck_for_load(destination=dest, weight=tonnes, max_budget=max_budget)
            if match:
                matching_engine.create_match_record(
                    truck_id=match["truck_id"],
                    load_id=self.current_load_id,
                    route_score=match["route_score"],
                    capacity_score=match["capacity_score"],
                    overall_score=match["overall_score"],
                    agreed_price=match["agreed_price"]
                )

            dest_display = get_destination_display(dest, lang)
            self.state = "CALL_CONCLUDED"
            if lang == "kn":
                return f"ಧನ್ಯವಾದಗಳು ರೀ {shipper_name}! ನಿಮ್ಮ {dest_display} ಮಾರ್ಗದ {int(tonnes)} ಟನ್ {cargo} ವಿವರ ದಾಖಲಾಗಿದೆ. ಕೆಲವು ನಿಮಿಷಗಳಲ್ಲಿ ಸೂಕ್ತ ಗಾಡಿ ಹುಡುಕಿ ಕರೆ ಮಾಡಿ ತಿಳಿಸುತ್ತೇವೆ. [HANGUP]"
            elif lang == "hi":
                return f"धन्यवाद जी! {dest} के लिए आपके {int(tonnes)} टन {cargo} का विवरण दर्ज हो गया है। कुछ ही मिनटों में सही गाड़ी देखकर आपको कॉल करेंगे। [HANGUP]"
            elif lang == "te":
                return f"ధన్యవాదాలు! {dest} కోసం మీ {int(tonnes)} టన్నుల {cargo} వివరాలు నమోదయ్యాయి. కొద్ది నిమిషాల్లో సరైన లారీ చూసి కాల్ చేస్తాము. [HANGUP]"
            elif lang == "ta":
                return f"நன்றி! {dest} செல்லும் உங்கள் {int(tonnes)} டன் {cargo} விவரங்கள் பதிவாகியுள்ளன. சில நிமிடங்களில் பொருத்தமான லாரியைப் பார்த்து அழைக்கிறோம். [HANGUP]"
            elif lang == "mr":
                return f"धन्यवाद! {dest} साठी तुमच्या {int(tonnes)} टन {cargo} ची नोंद झाली आहे. काही मिनिटांत योग्य गाडी शोधून तुम्हाला कॉल करतो. [HANGUP]"
            else:
                return f"Thank you! Your details for {int(tonnes)} tonnes of {cargo} to {dest} are recorded. We will find a matching truck and call you back in a few minutes. [HANGUP]"

        else: # DRIVER
            tonnes = float(cap)
            driver_name = self.extracted_data.get("name") or "ಚಾಲಕ"
            min_price = float(self.extracted_data.get("price") or 0.0)

            self.current_truck_id = db_manager.register_truck(
                phone=self.caller_phone or "+919845012399",
                destination=dest,
                capacity=tonnes,
                truck_type=self.extracted_data.get("vehicle_type", "Truck"),
                driver_name=driver_name,
                min_price=min_price,
                call_sid=self.call_sid
            )

            match = matching_engine.find_best_load_for_truck(destination=dest, capacity=tonnes, min_price=min_price)
            if match:
                matching_engine.create_match_record(
                    truck_id=self.current_truck_id,
                    load_id=match["load_id"],
                    route_score=match["route_score"],
                    capacity_score=match["capacity_score"],
                    overall_score=match["overall_score"],
                    agreed_price=match["agreed_price"]
                )

            dest_display = get_destination_display(dest, lang)
            self.state = "CALL_CONCLUDED"
            if lang == "kn":
                return f"ಧನ್ಯವಾದಗಳು ರೀ {driver_name}! ನಿಮ್ಮ {dest_display} ಮಾರ್ಗದ {int(tonnes)} ಟನ್ ಗಾಡಿ ವಿವರ ದಾಖಲಾಗಿದೆ. ಕೆಲವು ನಿಮಿಷಗಳಲ್ಲಿ ಸೂಕ್ತ ಲೋಡ್ ಹುಡುಕಿ ಕರೆ ಮಾಡಿ ತಿಳಿಸುತ್ತೇವೆ. [HANGUP]"
            elif lang == "hi":
                return f"धन्यवाद भाईसाहब! {dest} के लिए आपके {int(tonnes)} टन ट्रक का विवरण दर्ज हो गया है। कुछ ही मिनटों में सही लोड देखकर आपको कॉल करेंगे। [HANGUP]"
            elif lang == "te":
                return f"ధన్యవాదాలు! {dest} కోసం మీ {int(tonnes)} టన్నుల లారీ వివరాలు నమోదయ్యాయి. కొద్ది నిమిషాల్లో సరైన లోడ్ చూసి కాల్ చేస్తాము. [HANGUP]"
            elif lang == "ta":
                return f"நன்றி! {dest} செல்லும் உங்கள் {int(tonnes)} டன் லாரி விவரங்கள் பதிவாகியுள்ளன. சில நிமிடங்களில் சரியான லோடு பார்த்து அழைக்கிறோம். [HANGUP]"
            elif lang == "mr":
                return f"धन्यवाद! {dest} साठी तुमच्या {int(tonnes)} टन गाडीची नोंद झाली आहे. काही मिनिटांत योग्य लोड शोधून कॉल करतो. [HANGUP]"
            else:
                return f"Thank you! Your {int(tonnes)}-tonne truck for {dest} has been registered. We will find a matching load and call you back in a few minutes. [HANGUP]"

    async def text_to_speech_pcm(self, text: str) -> bytes:
        indic_codes = {
            "kn": "kn-IN",
            "hi": "hi-IN",
            "mr": "mr-IN",
            "te": "te-IN",
            "ta": "ta-IN",
            "gu": "gu-IN",
            "bn": "bn-IN",
            "ml": "ml-IN",
            "en": "en-IN"
        }
        lang_code = indic_codes.get(self.language, "kn-IN")

        # 1. Primary: Gnani Timbre Neural Indic TTS (Native 8000Hz PCM)
        try:
            gnani_pcm = await gnani_client.synthesize_gnani(text, language_code=lang_code)
            if gnani_pcm and len(gnani_pcm) > 0:
                return gnani_pcm
        except Exception:
            pass

        # 2. Resilient Fallback: Edge TTS
        voice_map = {
            "kn": "kn-IN-GaganNeural",
            "hi": "hi-IN-MadhurNeural",
            "mr": "mr-IN-AarohiNeural",
            "te": "te-IN-MohanNeural",
            "ta": "ta-IN-ValluvarNeural",
            "gu": "gu-IN-NiranjanNeural",
            "bn": "bn-IN-BashkarNeural",
            "ml": "ml-IN-MidhunNeural",
            "en": "en-IN-PrabhatNeural",
        }
        voice = voice_map.get(self.language, "kn-IN-GaganNeural")

        communicate = edge_tts.Communicate(text, voice, rate="+2%")
        mp3_buffer = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                mp3_buffer += chunk["data"]

        if not mp3_buffer:
            return b""

        decoded = miniaudio.decode(
            mp3_buffer,
            nchannels=1,
            sample_rate=8000,
            output_format=miniaudio.SampleFormat.SIGNED16
        )
        return decoded.samples.tobytes()
