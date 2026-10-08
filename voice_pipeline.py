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

def detect_language(text: str) -> str:
    for ch in text:
        if '\u0C80' <= ch <= '\u0CFF':
            return 'kn'
        if '\u0900' <= ch <= '\u097F':
            return 'hi'
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
            "origin": "APMC Amargol",
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

        normalized_data = normalize_pcm(pcm_data)
        audio = sr.AudioData(normalized_data, 8000, 2)
        transcription = ""

        # Try Google Multi-lingual Speech API with Indic priority
        for lang_code in ["kn-IN", "hi-IN", "en-IN"]:
            try:
                text = self.recognizer.recognize_google(audio, language=lang_code)
                if text and len(text.strip()) > 1:
                    transcription = text.strip()
                    self.language = detect_language(transcription)
                    return transcription
            except (sr.UnknownValueError, sr.RequestError):
                continue

        return transcription

    def extract_entities(self, text: str):
        lower = text.lower()

        # Origin identification
        if any(w in text for w in ["ಹುಬ್ಬಳ್ಳಿ", "ಅಮರಗೋಳ", "ಧಾರವಾಡ"]) or any(w in lower for w in ["hubballi", "hubli", "amargol"]):
            self.extracted_data["origin"] = "APMC Amargol"

        # Destination extraction
        if "ಬೆಂಗಳೂರ" in text or "ಬೆಂಗಳೂರು" in text or "bangalore" in lower or "bengaluru" in lower:
            self.extracted_data["destination"] = "Bengaluru"
        elif "ಬೆಳಗಾವಿ" in text or "belgaum" in lower or "belagavi" in lower:
            self.extracted_data["destination"] = "Belagavi"
        elif "ದಾವಣಗೆರೆ" in text or "davanagere" in lower or "davangere" in lower:
            self.extracted_data["destination"] = "Davanagere"
        elif "ಪುಣೆ" in text or "pune" in lower or "poona" in lower:
            self.extracted_data["destination"] = "Pune"
        elif "ಬಾಗಲಕೋಟ" in text or "ಬಾಗಲಕೋಟೆ" in text or "bagalkot" in lower:
            self.extracted_data["destination"] = "Bagalkot"
        elif "ಗೋವಾ" in text or "goa" in lower:
            self.extracted_data["destination"] = "Goa"
        elif "ಹಾವೇರಿ" in text or "haveri" in lower:
            self.extracted_data["destination"] = "Haveri"

        # Vehicle Type extraction
        if any(w in text for w in ["ಹತ್ತು ಚಕ್ರ", "10 ಚಕ್ರ"]) or "10 wheeler" in lower:
            self.extracted_data["vehicle_type"] = "10-Wheeler"
            if not self.extracted_data["capacity"]:
                self.extracted_data["capacity"] = 16.0
        elif any(w in text for w in ["ಆರು ಚಕ್ರ", "6 ಚಕ್ರ"]) or "6 wheeler" in lower:
            self.extracted_data["vehicle_type"] = "6-Wheeler"
            if not self.extracted_data["capacity"]:
                self.extracted_data["capacity"] = 9.0
        elif "ಐಷರ್" in text or "eicher" in lower or "4 tonne" in lower or "4 ಟನ್" in text:
            self.extracted_data["vehicle_type"] = "Eicher 14ft"
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

        tonne_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:ಟನ್|ton|tonne|tonnes|t)?', text, re.IGNORECASE)
        if tonne_match and not self.extracted_data.get("capacity"):
            try:
                val = float(tonne_match.group(1))
                if 1.0 <= val <= 50.0:
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
        elif not self.extracted_data.get("name") and self.state == "NAME_RATE_COLLECTION":
            words = [w for w in re.split(r'[\s,]+', text) if w and not re.search(r'\d', w)]
            ignore = ["truck", "lorry", "gaadi", "load", "driver", "vyapari", "raita", "malu", "agri",
                      "rate", "rupaye", "rs", "beku", "kodtini", "yes", "no", "sari", "houdu", "ha",
                      "theek", "bhejna", "chahiye", "tonne", "ton"]
            valid_words = [w for w in words if w.lower() not in ignore and len(w) >= 2]
            if valid_words:
                self.extracted_data["name"] = valid_words[0].capitalize()

        # Price / Budget extraction (e.g. "8000 rate", "5000 ಬಾಡಿಗೆ", "Rs 18000")
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
            # Standalone 3-6 digit number check
            standalone_num = re.search(r'\b(\d{3,6})\b', text)
            if standalone_num:
                val = float(standalone_num.group(1))
                if 500 <= val <= 200000 and val != self.extracted_data.get("capacity"):
                    self.extracted_data["price"] = val

    def is_affirmative(self, text: str) -> bool:
        lower = text.lower()
        affirmative_words = [
            "ಹೌದು", "ಸರಿ", "ಒಪ್ಪುತ್ತೇನೆ", "ಆಯ್ತು", "ಮಾಡಿ", "ಖಂಡಿತ", "ಹಾ", "ಹೌದ್ರಿ", "ಆಯ್ತ್ರಿ",
            "हाँ", "हा", "पक्का", "ठीक", "कर दो", "चलेगा", "मंजूर",
            "yes", "ok", "okay", "agree", "confirm", "done", "sure", "fine"
        ]
        return any(w in lower or w in text for w in affirmative_words)

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

        # Check if caller is confirming or rejecting an offered deal
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
            else:
                self.state = "COMPLETED"
                if lang == "kn":
                    return "ಸರಿ ರೀ. ನಿಮಗೆ ಬೇಕಾದಾಗ ಮತ್ತೆ ಕರೆ ಮಾಡಿ. ಶುಭ ದಿನ!"
                else:
                    return "Understood. Call back anytime when you are ready. Have a good day!"

        self.extract_entities(user_text)
        dest = self.extracted_data.get("destination")
        cap = self.extracted_data.get("capacity")

        # 1. Route destination check
        if not dest:
            self.state = "ROUTE_SELECTION"
            if lang == "kn":
                return "ಸರಿ ರೀ. ಹುಬ್ಬಳ್ಳಿಯಿಂದ ಯಾವ ಊರಿಗೆ ಹೋಗಬೇಕು ಅಥವಾ ಎಲ್ಲಿಗೆ ಲೋಡ್ ಕಳಿಸಬೇಕು ಅಂತ ಹೇಳಿ."
            elif lang == "hi":
                return "जी ठीक है। हुबली से किस शहर जाना है या कहाँ लोड भेजना है?"
            else:
                return "Understood. Which destination city are you heading to or sending goods to?"

        # 2. Capacity / tonnage check
        if not cap:
            self.state = "CAPACITY_CONFIRMATION"
            target = dest or "ಬೆಂಗಳೂರು"
            if self.role == "SHIPPER":
                if lang == "kn":
                    return f"ಖಂಡಿತ ರೀ! {target} ಮಾರ್ಗಕ್ಕೆ ರಿಟರ್ನ್ ಗಾಡಿಗಳು ಲಭ್ಯವಿವೆ. ನಿಮ್ಮ ಬಳಿ ಎಷ್ಟು ಟನ್ ಮತ್ತು ಯಾವ ಮಾಲು ಇದೆ ರೀ?"
                elif lang == "hi":
                    return f"नमस्ते जी! {target} के लिए रिटर्न गाड़ियां उपलब्ध हैं। आपके पास कितना टन और क्या माल है?"
                else:
                    return f"Return trucks available for {target}. How many tonnes and what produce do you have to send?"
            else:
                if lang == "kn":
                    return f"ಖಂಡಿತ ರೀ! ಹುಬ್ಬಳ್ಳಿಯಿಂದ {target}ಗೆ ಹೋಗಲು ಲೋಡ್ ರೆಡಿ ಇದೆ. ನಿಮ್ಮ ಗಾಡಿ ಎಷ್ಟು ಚಕ್ರದ್ರಿ? ಸಾಮರ್ಥ್ಯ ಎಷ್ಟು ಟನ್ ಐತಿ?"
                elif lang == "hi":
                    return f"नमस्ते भाईसाहब! हुबली से {target} के लिए लोड तुरंत मिल जाएगा। आपकी गाड़ी कितने चक्के और कितने टन की है?"
                else:
                    return f"Sure! Ready loads available from Hubballi to {target}. What is your truck type and capacity in tonnes?"

        # 3. Name & Expected Price/Rate check
        has_name = bool(self.extracted_data.get("name"))
        has_price = bool(self.extracted_data.get("price"))

        if self.state != "NAME_RATE_COLLECTION" and not (has_name and has_price):
            self.state = "NAME_RATE_COLLECTION"
            if not has_name and not has_price:
                if lang == "kn":
                    return "ಸರಿ ರೀ. ನಿಮ್ಮ ಹೆಸರು ಮತ್ತು ನೀವು ನಿರೀಕ್ಷಿಸುವ ಬಾಡಿಗೆ ದರ ಎಷ್ಟು ಅಂತ ಹೇಳ್ತೀರಾ?"
                elif lang == "hi":
                    return "जी ठीक है। आपका नाम और आपका अपेक्षित किराया कितना है, बता सकते हैं?"
                else:
                    return "Understood. Could you please share your name and your expected freight rate?"
            elif not has_name:
                if lang == "kn":
                    return "ಸರಿ ರೀ. ನಿಮ್ಮ ಹೆಸರು ಏನು ಅಂತ ಹೇಳ್ತೀರಾ?"
                elif lang == "hi":
                    return "जी ठीक है। आपका शुभ नाम क्या है?"
                else:
                    return "Understood. May I know your name please?"
            else:
                if lang == "kn":
                    return "ಸರಿ ರೀ. ನೀವು ನಿರೀಕ್ಷಿಸುವ ಬಾಡಿಗೆ ದರ ಎಷ್ಟು ಅಂತ ಹೇಳ್ತೀರಾ?"
                elif lang == "hi":
                    return "जी ठीक है। आपका अपेक्षित किराया कितना है?"
                else:
                    return "Understood. What is your expected freight rate?"

        # 4. Destination, Capacity, and Name/Price collected -> Registration & Marketplace matching
        if self.role == "SHIPPER":
            tonnes = float(cap)
            cargo = self.extracted_data.get("cargo_type", "Agri Produce")
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

            match = matching_engine.find_best_truck_for_load(destination=dest, weight=tonnes)
            if match:
                record = matching_engine.create_match_record(
                    truck_id=match["truck_id"],
                    load_id=self.current_load_id,
                    route_score=match["route_score"],
                    capacity_score=match["capacity_score"],
                    overall_score=match["overall_score"],
                    agreed_price=match["agreed_price"]
                )
                self.current_match = {**match, **record}
                self.state = "DEAL_OFFER"

                price = int(match["agreed_price"])
                truck_type = match["truck_type"]
                loc = match["current_location"]

                if lang == "kn":
                    return f"ಖಂಡಿತ ರೀ {shipper_name}! ನಿಮ್ಮ {int(tonnes)} ಟನ್ {cargo} ಕಳಿಸಲು {dest} ಮಾರ್ಗದ {truck_type} ({loc}) ತಕ್ಷಣ ಲಭ್ಯವಿದೆ. ಬಾಡಿಗೆ ರೂ. {price}. ಈ ಗಾಡಿ ಪಕ್ಕಾ ಮಾಡಲಾ ರೀ?"
                elif lang == "hi":
                    return f"बिल्कुल जी! आपका {int(tonnes)} टन {cargo} भेजने के लिए {dest} के लिए {truck_type} ({loc}) उपलब्ध है। किराया {price} रुपये है। क्या यह गाड़ी बुक करें?"
                else:
                    return f"Sure! For your {int(tonnes)}-tonne {cargo} to {dest}, a {truck_type} at {loc} is available for Rs. {price}. Confirm booking?"
            else:
                self.state = "DEAL_OFFER"
                if lang == "kn":
                    return f"ಸರಿ ರೀ {shipper_name}. ಅಮರಗೋಳದಿಂದ {dest}ಗೆ ನಿಮ್ಮ {int(tonnes)} ಟನ್ {cargo} ಲೋಡ್ ದಾಖಲಾಗಿದೆ. ಸೂಕ್ತ ರಿಟರ್ನ್ ಗಾಡಿ ಸಿಕ್ಕ ತಕ್ಷಣ ತಿಳಿಸುತ್ತೇವೆ."
                else:
                    return f"Recorded your {int(tonnes)}-tonne {cargo} load for {dest}. We will notify you as soon as a return truck is available."

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

            match = matching_engine.find_best_load_for_truck(destination=dest, capacity=tonnes)
            if match:
                record = matching_engine.create_match_record(
                    truck_id=self.current_truck_id,
                    load_id=match["load_id"],
                    route_score=match["route_score"],
                    capacity_score=match["capacity_score"],
                    overall_score=match["overall_score"],
                    agreed_price=match["agreed_price"]
                )
                self.current_match = {**match, **record}
                self.state = "DEAL_OFFER"

                cargo = match["cargo_type"]
                weight = match["weight_tonnes"]
                pickup = match["pickup_location"]
                price = int(match["agreed_price"])

                if lang == "kn":
                    return f"ಖಂಡಿತ ರೀ {driver_name}! ನಿಮ್ಮ {int(tonnes)} ಟನ್ ಗಾಡಿಗೆ {pickup}ಯಿಂದ {weight} ಟನ್ {cargo} ಲೋಡ್ ತಕ್ಷಣ ಸಿಕ್ಕಿದೆ. ಬಾಡಿಗೆ ರೂ. {price}. ಈ ಲೋಡ್ ಒಪ್ಕೋತೀರಾ ರೀ?"
                elif lang == "hi":
                    return f"बिल्कुल भाईसाहब! आपके {int(tonnes)} टन ट्रक के लिए {pickup} से {weight} टन {cargo} का लोड तुरंत उपलब्ध है। किराया {price} रुपये है। क्या आप यह लोड लेना चाहते हैं?"
                else:
                    return f"Sure! For your {int(tonnes)}-tonne truck, {weight} tonnes of {cargo} is ready at {pickup} for Rs. {price}. Do you confirm?"
            else:
                self.state = "DEAL_OFFER"
                if lang == "kn":
                    return f"ಸರಿ ರೀ {driver_name}. ಅಮರಗೋಳದಿಂದ {dest}ಗೆ ನಿಮ್ಮ {int(tonnes)} ಟನ್ ಗಾಡಿ ನೋಂದಾಯಿಸಲಾಗಿದೆ. ಹೊಸ ಲೋಡ್ ಸಿಕ್ಕ ತಕ್ಷಣ ತಿಳಿಸುತ್ತೇವೆ."
                else:
                    return f"Recorded your {int(tonnes)}-tonne truck for {dest}. We will notify you once a load is available."

    async def text_to_speech_pcm(self, text: str) -> bytes:
        voice = "kn-IN-GaganNeural"
        if self.language == "hi":
            voice = "hi-IN-MadhurNeural"
        elif self.language == "en":
            voice = "en-IN-PrabhatNeural"

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
