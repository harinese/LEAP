# -*- coding: utf-8 -*-
"""
Test script to verify Gnani Prisma STT and Timbre TTS APIs.
Usage:
  1. Add your GNANI_API_KEY to .env or set $env:GNANI_API_KEY="your_key"
  2. Run: python test_gnani.py
"""
import os
import sys
import asyncio
import gnani_client

async def main():
    api_key = os.getenv("GNANI_API_KEY")
    if not api_key:
        print("[!] GNANI_API_KEY is not set in .env or environment!")
        print("    Please add GNANI_API_KEY=your_key to .env file.")
        return

    masked_key = api_key[:4] + "..." + api_key[-4:] if len(api_key) > 8 else "***"
    print(f"[*] Testing Gnani APIs with key: {masked_key}")

    # 1. Test TTS (Timbre)
    test_phrase = "ನಮಸ್ಕಾರ! ರಾಷ್ಟ್ರೀಯ ಸರಕು ಸಾರಿಗೆ ಸೇತುಗೆ ಸ್ವಾಗತ."
    print(f"\n[1] Testing Gnani Timbre TTS (Kannada)...")
    print(f"    Text: {test_phrase}")
    pcm_audio = await gnani_client.synthesize_gnani(test_phrase, language_code="kn-IN")
    if pcm_audio and len(pcm_audio) > 0:
        print(f"    [+] SUCCESS: Generated {len(pcm_audio)} bytes of 8000Hz PCM audio!")
    else:
        print("    [-] FAILED: Could not synthesize audio via Gnani TTS.")
        return

    # 2. Test STT (Prisma)
    print(f"\n[2] Testing Gnani Prisma STT (Round-trip with synthesized audio)...")
    transcript = await gnani_client.transcribe_gnani(pcm_audio, language_code="kn-IN")
    if transcript:
        print(f"    [+] SUCCESS! Transcribed text: {transcript}")
    else:
        print("    [-] FAILED: Could not transcribe audio via Gnani STT.")

if __name__ == "__main__":
    asyncio.run(main())
