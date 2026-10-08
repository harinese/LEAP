import asyncio
import base64
import json
import logging
import os
from typing import Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

import db_manager
import matching_engine
from voice_pipeline import VoicePipeline, calculate_rms

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("agent_server")

app = FastAPI(title="SetuVoice Exotel AgentStream Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

db_manager.init_db()

CHUNK_SIZE = 640  # 40ms of 8000Hz 16-bit mono PCM (320 samples * 2 bytes)
BASE_SILENCE_THRESHOLD = 320
SILENCE_DURATION_FRAMES = 30    # ~640ms silence to allow natural pause between words

async def send_audio_to_exotel(websocket: WebSocket, stream_sid: str, pcm_data: bytes, cancel_event: asyncio.Event):
    offset = 0
    total = len(pcm_data)
    while offset < total:
        if cancel_event.is_set():
            logger.info("Outbound audio interrupted by caller barge-in.")
            break
        chunk = pcm_data[offset:offset + CHUNK_SIZE]
        if not chunk:
            break
        payload = base64.b64encode(chunk).decode("utf-8")
        msg = {
            "event": "media",
            "stream_sid": stream_sid,
            "media": {
                "payload": payload
            }
        }
        await websocket.send_text(json.dumps(msg))
        offset += len(chunk)
        await asyncio.sleep(0.038)

@app.get("/")
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "Exotel AgentStream Voicebot",
        "telephony_format": "PCM16 8000Hz Mono",
        "auth_model": "CLI-as-Identity (Zero Sign-up)",
        "features": ["One-Shot Slot Extraction", "Call-Back Deal Confirmation", "Async SMS Recommendations", "Barge-in"],
        "database": "SQLite (setu_agent.db) Ready"
    }

@app.get("/profiles")
@app.get("/api/profiles")
async def get_profiles():
    return db_manager.get_all_profiles()

@app.get("/trucks")
@app.get("/api/trucks")
async def get_trucks():
    return db_manager.get_all_trucks()

@app.get("/loads")
@app.get("/api/loads")
async def get_loads():
    return db_manager.get_all_loads()

@app.get("/matches")
@app.get("/api/matches")
async def get_matches():
    return db_manager.get_all_matches()

@app.get("/api/matches/stats")
async def get_marketplace_stats():
    conn = db_manager.get_connection()
    c = conn.cursor()
    c.execute("SELECT count(*) as count FROM trucks")
    total_trucks = c.fetchone()["count"]
    c.execute("SELECT count(*) as count FROM trucks WHERE status = 'AVAILABLE'")
    avail_trucks = c.fetchone()["count"]
    c.execute("SELECT count(*) as count FROM loads")
    total_loads = c.fetchone()["count"]
    c.execute("SELECT count(*) as count FROM loads WHERE status = 'PENDING'")
    pending_loads = c.fetchone()["count"]
    c.execute("SELECT count(*) as count FROM matches WHERE status = 'CONFIRMED'")
    confirmed = c.fetchone()["count"]
    conn.close()

    return {
        "trucks": {
            "totalTrucks": total_trucks,
            "availableTrucks": avail_trucks,
            "matchedTrucks": max(0, total_trucks - avail_trucks),
        },
        "loads": {
            "totalLoads": total_loads,
            "pendingLoads": pending_loads,
            "matchedLoads": max(0, total_loads - pending_loads),
        },
        "matches": {
            "confirmedCount": confirmed,
            "totalSavingsRupees": confirmed * 4200,
            "totalDriverEarningsRupees": confirmed * 14500,
            "totalDieselSavedLiters": confirmed * 110,
            "deadheadReductionPercent": 68.5,
        }
    }

@app.post("/loads")
@app.post("/api/loads")
async def create_load(request: Request):
    data = await request.json()
    load_id = db_manager.register_load(
        phone=data.get("phone", "+919448000000"),
        destination=data.get("destination", "Bengaluru"),
        weight=float(data.get("weight", 10.0)),
        cargo=data.get("cargo", "Agricultural Produce"),
        shipper_name=data.get("shipper_name", "Trader"),
        max_budget=float(data.get("max_budget", 0))
    )
    return {"status": "success", "load_id": load_id}

@app.websocket("/exotel/ws")
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("Exotel WebSocket connection established.")

    pipeline: Optional[VoicePipeline] = None
    stream_sid: str = ""
    call_sid: str = ""
    caller_phone: str = ""

    audio_buffer = bytearray()
    silence_frames = 0
    speech_detected = False
    is_responding = False
    is_playing_audio = False
    cancel_speech_event = asyncio.Event()

    adaptive_threshold = BASE_SILENCE_THRESHOLD
    noise_samples = []

    try:
        while True:
            raw_text = await websocket.receive_text()
            try:
                data = json.loads(raw_text)
            except json.JSONDecodeError:
                continue

            event = data.get("event")

            if event == "start":
                start_obj = data.get("start", {})
                stream_sid = data.get("stream_sid") or start_obj.get("stream_sid", f"stream_{id(websocket)}")
                call_sid = start_obj.get("call_sid", f"call_{stream_sid}")
                caller_phone = start_obj.get("from", "")

                logger.info(f"Incoming Call (CLI Auth): {caller_phone} | Session: {call_sid}")
                profile = db_manager.get_or_create_caller_profile(caller_phone)
                pipeline = VoicePipeline(stream_sid, call_sid, caller_phone)
                pipeline.language = profile.get("preferred_language", "kn")
                db_manager.log_call_start(call_sid, stream_sid, caller_phone)

                # Smart Greeting: Detect if caller is calling back to confirm an SMS recommendation
                if pipeline.is_callback_flow and pipeline.current_match:
                    dest = pipeline.current_match.get("destination", "ಬೆಂಗಳೂರು")
                    wt = pipeline.current_match.get("weight_tonnes", "2.5")
                    cargo = pipeline.current_match.get("cargo_type", "ಲೋಡ್")
                    rate = int(pipeline.current_match.get("agreed_price", 8000))
                    
                    greeting_text = (
                        f"ನಮಸ್ಕಾರ ರೀ! ನಿಮ್ಮ {dest} ಮಾರ್ಗದ {wt} ಟನ್ {cargo} ರಿಟರ್ನ್ ಲೋಡ್ ದೃಢೀಕರಿಸಲು ಕರೆ ಮಾಡಿದ್ದೀರಾ? "
                        f"ನಿಗದಿತ ಬಾಡಿಗೆ ರೂ. {rate}. ಡೀಲ್ ಪಕ್ಕಾ ಮಾಡಲು 'ಸರಿ' ಅಥವಾ 'ಹೌದು' ಎನ್ನಿ."
                    )
                else:
                    is_returning = profile.get("total_calls", 1) > 1
                    if is_returning:
                        greeting_text = "ನಮಸ್ಕಾರ ರೀ! ಎಪಿಎಂಸಿ ಅಮರಗೋಳಕ್ಕೆ ಮತ್ತೆ ಸ್ವಾಗತ. ಇಂದು ನಿಮ್ಮ ಗಾಡಿ ಯಾವ ಊರಿಗೆ ಹೊರಡಬೇಕು?"
                    else:
                        greeting_text = "ನಮಸ್ಕಾರ ರೀ! ಎಪಿಎಂಸಿ ಅಮರಗೋಳ ರಿಟರ್ನ್ ಲೋಡ್ ಕೇಂದ್ರ. ನಿಮ್ಮ ಗಾಡಿ ಯಾವ ಊರಿಗೆ ಹೊರಡಬೇಕು?"

                db_manager.save_utterance(call_sid, "agent", greeting_text)
                greeting_pcm = await pipeline.text_to_speech_pcm(greeting_text)
                cancel_speech_event.clear()
                is_playing_audio = True
                asyncio.create_task(send_audio_to_exotel(websocket, stream_sid, greeting_pcm, cancel_speech_event))
                await asyncio.sleep(len(greeting_pcm) / (8000 * 2) + 0.2)
                is_playing_audio = False

            elif event == "media":
                media_obj = data.get("media", {})
                payload_b64 = media_obj.get("payload", "")
                if not payload_b64:
                    continue

                try:
                    chunk = base64.b64decode(payload_b64)
                except Exception:
                    continue

                rms = calculate_rms(chunk)

                # Calibrate ambient noise floor dynamically
                if len(noise_samples) < 15:
                    noise_samples.append(rms)
                    if len(noise_samples) == 15:
                        avg_noise = sum(noise_samples) / 15
                        adaptive_threshold = max(BASE_SILENCE_THRESHOLD, avg_noise * 1.2)
                        logger.info(f"Calibrated noise threshold: {adaptive_threshold:.1f} RMS")

                # Barge-in: if bot is playing and caller speaks, stop audio immediately
                if is_playing_audio and rms > (adaptive_threshold * 1.3):
                    cancel_speech_event.set()
                    is_playing_audio = False
                    await websocket.send_text(json.dumps({
                        "event": "clear",
                        "stream_sid": stream_sid
                    }))
                    logger.info("Barge-in triggered: clearing Exotel audio buffer.")

                if is_responding:
                    continue

                if rms > adaptive_threshold:
                    speech_detected = True
                    silence_frames = 0
                    audio_buffer.extend(chunk)
                else:
                    if speech_detected:
                        silence_frames += 1
                        audio_buffer.extend(chunk)

                        # End of turn detected (caller finished speaking)
                        if silence_frames >= SILENCE_DURATION_FRAMES and len(audio_buffer) > 20000:
                            is_responding = True
                            user_pcm = bytes(audio_buffer)
                            audio_buffer.clear()
                            speech_detected = False
                            silence_frames = 0

                            if pipeline:
                                logger.info(f"Processing speech ({len(user_pcm)} bytes)...")
                                recognized_text = await pipeline.transcribe(user_pcm)

                                if not recognized_text:
                                    logger.warning("Empty transcription, asking for repeat in caller language.")
                                    if pipeline.language == "kn":
                                        agent_reply = "ಕ್ಷಮಿಸಿ ರೀ, ನಿಮ್ಮ ಮಾತು ಸ್ಪಷ್ಟವಾಗಿ ಕೇಳಿಸಲಿಲ್ಲ. ಯಾವ ಊರಿಗೆ ಲೋಡ್ ಬೇಕು ಅಂತ ಇನ್ನೊಮ್ಮೆ ಹೇಳ್ತೀರಾ?"
                                    elif pipeline.language == "hi":
                                        agent_reply = "माफ कीजिए, आवाज साफ नहीं आई। किस शहर के लिए लोड चाहिए, दोबारा बोलेंगे?"
                                    else:
                                        agent_reply = "Sorry, I could not hear clearly. Which city are you looking for a load to?"
                                else:
                                    logger.info(f"Caller Said: {recognized_text}")
                                    db_manager.save_utterance(call_sid, "caller", recognized_text)
                                    agent_reply = pipeline.process_turn(recognized_text)

                                logger.info(f"Agent Reply: {agent_reply}")
                                db_manager.save_utterance(call_sid, "agent", agent_reply)


                                reply_pcm = await pipeline.text_to_speech_pcm(agent_reply)
                                cancel_speech_event.clear()
                                is_playing_audio = True
                                await send_audio_to_exotel(websocket, stream_sid, reply_pcm, cancel_speech_event)
                                is_playing_audio = False

                            is_responding = False

            elif event == "stop":
                logger.info(f"Call Finished: {stream_sid}")
                if call_sid:
                    db_manager.log_call_end(call_sid)
                break

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {stream_sid}")
        if call_sid:
            db_manager.log_call_end(call_sid)
    except Exception as e:
        logger.error(f"Error in WebSocket handler: {e}")
        if call_sid:
            db_manager.log_call_end(call_sid)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    logger.info(f"Starting SetuVoice AgentStream server on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
