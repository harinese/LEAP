# -*- coding: utf-8 -*-
import io
import os
import wave
import json
import base64
import logging
import asyncio
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("gnani_client")

GNANI_BASE_URL = os.getenv("GNANI_BASE_URL", "https://api.vachana.ai").rstrip("/")
GNANI_API_KEY = os.getenv("GNANI_API_KEY", "")

# Voice mappings for Gnani Timbre models
GNANI_VOICES = {
    "kn-IN": "Lakshmi",
    "kn": "Lakshmi",
    "hi-IN": "Shubham",
    "hi": "Shubham",
    "en-IN": "Nalini",
    "en": "Nalini"
}

def pcm_to_wav_bytes(pcm_bytes: bytes, sample_rate: int = 8000, num_channels: int = 1, sample_width: int = 2) -> bytes:
    """Wraps raw 16-bit PCM bytes into standard WAV container in memory."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(num_channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()

def wav_to_pcm_bytes(wav_bytes: bytes, target_sample_rate: int = 8000) -> bytes:
    """Extracts raw 16-bit mono 8000Hz PCM from WAV bytes."""
    import miniaudio
    try:
        decoded = miniaudio.decode(
            wav_bytes,
            nchannels=1,
            sample_rate=target_sample_rate,
            output_format=miniaudio.SampleFormat.SIGNED16
        )
        return decoded.samples.tobytes()
    except Exception as e:
        logger.error(f"Error decoding WAV to PCM: {e}")
        return b""

async def transcribe_gnani(pcm_bytes: bytes, language_code: str = "kn-IN") -> str:
    """
    Calls Gnani Prisma STT REST API (v3.0) with in-memory WAV audio.
    Endpoint: POST https://api.vachana.ai/stt/v3
    """
    api_key = os.getenv("GNANI_API_KEY") or GNANI_API_KEY
    if not api_key:
        logger.warning("GNANI_API_KEY not configured. Falling back.")
        return ""

    if len(pcm_bytes) < 3200:
        return ""

    wav_payload = pcm_to_wav_bytes(pcm_bytes, sample_rate=8000, num_channels=1, sample_width=2)
    url = f"{GNANI_BASE_URL}/stt/v3"
    headers = {
        "X-API-Key-ID": api_key
    }
    files = {
        "audio_file": ("audio.wav", wav_payload, "audio/wav")
    }
    data = {
        "model": "prisma-v3.0",
        "language_code": language_code
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, headers=headers, files=files, data=data)
            if resp.status_code == 200:
                result = resp.json()
                transcript = result.get("transcript") or result.get("text") or ""
                if not transcript and isinstance(result.get("data"), dict):
                    transcript = result["data"].get("transcript") or result["data"].get("text") or ""
                logger.info(f"Gnani STT Result: {transcript}")
                return transcript.strip()
            else:
                logger.error(f"Gnani STT Error {resp.status_code}: {resp.text}")
                return ""
    except Exception as e:
        logger.error(f"Gnani STT Exception: {e}")
        return ""

async def synthesize_gnani(text: str, language_code: str = "kn-IN", voice: Optional[str] = None) -> bytes:
    """
    Calls Gnani Timbre TTS REST API to synthesize Indic speech.
    Endpoint: POST https://api.vachana.ai/api/v1/tts/inference
    Returns: raw 8000Hz 16-bit mono PCM bytes ready for Exotel streaming.
    """
    api_key = os.getenv("GNANI_API_KEY") or GNANI_API_KEY
    if not api_key:
        logger.warning("GNANI_API_KEY not configured. Falling back.")
        return b""

    selected_voice = voice or GNANI_VOICES.get(language_code, "Lakshmi")
    url = f"{GNANI_BASE_URL}/api/v1/tts/inference"
    headers = {
        "Content-Type": "application/json",
        "X-API-Key-ID": api_key
    }
    payload = {
        "text": text,
        "voice": selected_voice,
        "model": "timbre-v2.5",
        "language": language_code,
        "speed": 1.0,
        "audio_config": {
            "encoding": "linear_pcm",
            "container": "wav",
            "num_channels": 1,
            "sample_rate": 8000,
            "sample_width": 2
        }
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                content_type = resp.headers.get("content-type", "")
                if "audio" in content_type or resp.content[:4] == b"RIFF":
                    return wav_to_pcm_bytes(resp.content, target_sample_rate=8000)
                else:
                    try:
                        res_json = resp.json()
                        b64_data = res_json.get("audio_content") or res_json.get("audio") or ""
                        if b64_data:
                            raw_wav = base64.b64decode(b64_data)
                            return wav_to_pcm_bytes(raw_wav, target_sample_rate=8000)
                    except Exception:
                        pass
                    return wav_to_pcm_bytes(resp.content, target_sample_rate=8000)
            else:
                logger.error(f"Gnani TTS Error {resp.status_code}: {resp.text}")
                return b""
    except Exception as e:
        logger.error(f"Gnani TTS Exception: {e}")
        return b""
