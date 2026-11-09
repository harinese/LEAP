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
import gemini_brain

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

KANNADA_GREETING_TEXT = "ನಮಸ್ಕಾರ ರೀ! ರಾಷ್ಟ್ರೀಯ ಸರಕು ಸಾರಿಗೆ ಸೇತು. ನಿಮ್ಮ ಗಾಡಿ ಅಥವಾ ಲೋಡ್ ಯಾವ ಊರಿನಿಂದ ಯಾವ ಊರಿಗೆ ಬೇಕು?"
CACHED_KANNADA_GREETING_PCM: bytes = b""

async def get_or_create_cached_greeting() -> bytes:
    global CACHED_KANNADA_GREETING_PCM
    if CACHED_KANNADA_GREETING_PCM:
        return CACHED_KANNADA_GREETING_PCM
    try:
        vp = VoicePipeline("warmup", "warmup")
        vp.language = "kn"
        pcm = await vp.text_to_speech_pcm(KANNADA_GREETING_TEXT)
        if pcm:
            CACHED_KANNADA_GREETING_PCM = pcm
            logger.info(f"Pre-cached Kannada greeting audio ({len(pcm)} bytes) ready in RAM!")
        return pcm
    except Exception as e:
        logger.error(f"Error warming up greeting: {e}")
        return b""

@app.on_event("startup")
async def startup_warmup():
    asyncio.create_task(get_or_create_cached_greeting())


def get_db_context_summary():
    try:
        conn = db_manager.get_connection()
        c = conn.cursor()
        c.execute("SELECT id, cargo_type, weight_tonnes, pickup_location, destination, max_budget FROM loads WHERE status = 'PENDING' LIMIT 6")
        loads = [dict(r) for r in c.fetchall()]
        c.execute("SELECT id, truck_type, capacity_tonnes, current_location, destination, min_price FROM trucks WHERE status = 'AVAILABLE' LIMIT 6")
        trucks = [dict(r) for r in c.fetchall()]
        conn.close()
        loads_str = "\n".join([f"Load #{l['id']}: {l['weight_tonnes']}T {l['cargo_type']} to {l['destination']} (Budget: Rs {int(l['max_budget']) if l['max_budget'] else 'Negotiable'})" for l in loads]) or "No active loads"
        trucks_str = "\n".join([f"Truck #{t['id']}: {t['capacity_tonnes']}T {t['truck_type']} at {t['current_location']} to {t['destination']}" for t in trucks]) or "No active trucks"
        return {
            "available_loads_summary": loads_str,
            "available_trucks_summary": trucks_str
        }
    except Exception as e:
        logger.error(f"Error fetching DB context summary: {e}")
        return {"available_loads_summary": "Error", "available_trucks_summary": "Error"}


CHUNK_SIZE = 640  # 40ms of 8000Hz 16-bit mono PCM (320 samples * 2 bytes)
BASE_SILENCE_THRESHOLD = 320
SILENCE_DURATION_FRAMES = 13    # ~520ms silence for spontaneous, human-like turn turnaround

async def send_audio_to_exotel(websocket: WebSocket, stream_sid: str, pcm_data: bytes, cancel_event: asyncio.Event, ws_lock: asyncio.Lock):
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
        async with ws_lock:
            await websocket.send_text(json.dumps(msg))
        offset += len(chunk)
        await asyncio.sleep(0.038)

@app.get("/")
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "National Freight Exchange Voicebot (Powered by Gnani.ai)",
        "stt_model": "Gnani Prisma STT (v3.0)",
        "tts_model": "Gnani Timbre TTS (v2.5)",
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
    active_speech_frames = 0
    is_responding = False
    is_playing_audio = False
    cancel_speech_event = asyncio.Event()
    ws_lock = asyncio.Lock()

    async def play_audio_task(pcm: bytes):
        nonlocal is_playing_audio
        is_playing_audio = True
        try:
            await send_audio_to_exotel(websocket, stream_sid, pcm, cancel_speech_event, ws_lock)
        except (WebSocketDisconnect, Exception) as e:
            logger.info(f"Audio playback completed or stream closed: {e}")
        finally:
            is_playing_audio = False

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
                gemini_conv = gemini_brain.GeminiConversation(call_sid, caller_phone)
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
                    greeting_text = KANNADA_GREETING_TEXT

                db_manager.save_utterance(call_sid, "agent", greeting_text)
                # Instant zero-delay playback from RAM cache
                greeting_pcm = await get_or_create_cached_greeting()
                if not greeting_pcm:
                    greeting_pcm = await pipeline.text_to_speech_pcm(greeting_text)
                cancel_speech_event.clear()
                asyncio.create_task(play_audio_task(greeting_pcm))

            elif event == "media":
                media_obj = data.get("media", {})
                payload_b64 = media_obj.get("payload", "")
                if not payload_b64:
                    continue

                try:
                    chunk = base64.b64decode(payload_b64)
                except Exception:
                    continue

                # While bot is speaking, ignore incoming line noise so agent speaks cleanly to caller
                if is_playing_audio:
                    continue

                rms = calculate_rms(chunk)

                # Calibrate ambient noise floor dynamically
                if len(noise_samples) < 15:
                    noise_samples.append(rms)
                    if len(noise_samples) == 15:
                        avg_noise = sum(noise_samples) / 15
                        adaptive_threshold = max(BASE_SILENCE_THRESHOLD, avg_noise * 1.2)
                        logger.info(f"Calibrated noise threshold: {adaptive_threshold:.1f} RMS")

                if is_responding:
                    continue

                if rms > adaptive_threshold:
                    speech_detected = True
                    active_speech_frames += 1
                    silence_frames = 0
                    audio_buffer.extend(chunk)
                else:
                    if speech_detected:
                        silence_frames += 1
                        audio_buffer.extend(chunk)

                        # End of turn detected (caller finished speaking)
                        if silence_frames >= SILENCE_DURATION_FRAMES:
                            # Verify if caller actually voiced speech (at least 6 frames = 240ms of active speech)
                            if active_speech_frames < 6 or len(audio_buffer) < 16000:
                                # Minor throat clear, mic click, or breath (< 240ms of voice).
                                # Discard silently without interrupting caller!
                                audio_buffer.clear()
                                speech_detected = False
                                silence_frames = 0
                                active_speech_frames = 0
                                continue

                            is_responding = True
                            user_pcm = bytes(audio_buffer)
                            audio_buffer.clear()
                            speech_detected = False
                            silence_frames = 0
                            active_speech_frames = 0

                            if pipeline:
                                logger.info(f"Processing speech ({len(user_pcm)} bytes)...")
                                recognized_text = await pipeline.transcribe(user_pcm)

                                if not recognized_text:
                                    logger.warning("Empty transcription, asking for repeat in caller language.")
                                    if pipeline.language == "kn":
                                        agent_reply = "ಕ್ಷಮಿಸಿ ರೀ, ಇನ್ನೊಮ್ಮೆ ಸ್ಪಷ್ಟವಾಗಿ ಹೇಳ್ತೀರಾ?"
                                    elif pipeline.language == "hi":
                                        agent_reply = "माफ कीजिए, आवाज साफ नहीं आई। किस शहर के लिए लोड चाहिए, दोबारा बोलेंगे?"
                                    else:
                                        agent_reply = "Sorry, I could not hear clearly. Which city are you looking for a load to?"
                                    reply_pcm = await pipeline.text_to_speech_pcm(agent_reply)
                                    cancel_speech_event.clear()
                                    asyncio.create_task(play_audio_task(reply_pcm))
                                else:
                                    logger.info(f"Caller Said: {recognized_text}")
                                    db_manager.save_utterance(call_sid, "caller", recognized_text)
                                    pipeline.extract_entities(recognized_text)

                                    call_should_hangup = False
                                    full_reply_text = ""
                                    streamed_chunks = 0

                                    # Stream Gemini token clauses directly to pipelined TTS playback
                                    if gemini_conv and gemini_conv.is_available():
                                        db_ctx = get_db_context_summary()
                                        db_ctx["caller_role"] = pipeline.role
                                        cancel_speech_event.clear()

                                        async for chunk in gemini_conv.generate_reply_stream(recognized_text, db_ctx):
                                            chunk_clean = chunk.strip()
                                            if not chunk_clean:
                                                continue

                                            streamed_chunks += 1
                                            if "[HANGUP]" in chunk_clean:
                                                call_should_hangup = True
                                                chunk_clean = chunk_clean.replace("[HANGUP]", "").strip()
                                            elif "[hangup]" in chunk_clean.lower():
                                                call_should_hangup = True
                                                chunk_clean = re.sub(r'\[hangup\]', '', chunk_clean, flags=re.IGNORECASE).strip()

                                            full_reply_text += " " + chunk_clean
                                            pipeline.language = gemini_conv.detected_language

                                            if chunk_clean:
                                                chunk_pcm = await pipeline.text_to_speech_pcm(chunk_clean)
                                                if chunk_pcm:
                                                    await play_audio_task(chunk_pcm)

                                    # Fallback to deterministic state engine if Gemini did not stream
                                    if streamed_chunks == 0:
                                        agent_reply = pipeline.process_turn(recognized_text)
                                        if "[HANGUP]" in agent_reply:
                                            call_should_hangup = True
                                            agent_reply = agent_reply.replace("[HANGUP]", "").strip()
                                        elif "[hangup]" in agent_reply.lower():
                                            call_should_hangup = True
                                            agent_reply = re.sub(r'\[hangup\]', '', agent_reply, flags=re.IGNORECASE).strip()

                                        full_reply_text = agent_reply
                                        reply_pcm = await pipeline.text_to_speech_pcm(agent_reply)
                                        cancel_speech_event.clear()
                                        await play_audio_task(reply_pcm)

                                    clean_full = full_reply_text.strip()
                                    logger.info(f"Full Agent Reply: {clean_full}")
                                    db_manager.save_utterance(call_sid, "agent", clean_full)

                                    # Persist load/truck in DB if concluding call
                                    if call_should_hangup:
                                        try:
                                            dest = pipeline.extracted_data.get("destination") or "ಬೆಂಗಳೂರು"
                                            tonnes = float(pipeline.extracted_data.get("capacity") or 4.0)
                                            if pipeline.role == "SHIPPER":
                                                if not pipeline.current_load_id:
                                                    cargo = pipeline.extracted_data.get("cargo_type") or "General Goods"
                                                    shipper_name = pipeline.extracted_data.get("name") or "ವ್ಯಾಪಾರಿ"
                                                    max_budget = float(pipeline.extracted_data.get("price") or 0.0)
                                                    pipeline.current_load_id = db_manager.register_load(
                                                        phone=caller_phone or "+919448011999",
                                                        destination=dest,
                                                        weight=tonnes,
                                                        cargo=cargo,
                                                        shipper_name=shipper_name,
                                                        max_budget=max_budget,
                                                        call_sid=call_sid
                                                    )
                                                    logger.info(f"Persisted load #{pipeline.current_load_id} for {caller_phone}")
                                            else:
                                                if not pipeline.current_truck_id:
                                                    driver_name = pipeline.extracted_data.get("name") or "ಚಾಲಕ"
                                                    min_price = float(pipeline.extracted_data.get("price") or 0.0)
                                                    pipeline.current_truck_id = db_manager.register_truck(
                                                        phone=caller_phone or "+919845012399",
                                                        destination=dest,
                                                        capacity=tonnes,
                                                        truck_type=pipeline.extracted_data.get("vehicle_type", "Truck"),
                                                        driver_name=driver_name,
                                                        min_price=min_price,
                                                        call_sid=call_sid
                                                    )
                                                    logger.info(f"Persisted truck #{pipeline.current_truck_id} for {caller_phone}")
                                        except Exception as db_err:
                                            logger.error(f"Error persisting on hangup: {db_err}")

                                        logger.info(f"Call {call_sid}: Concluding call. Playing goodbye audio and terminating...")
                                        await asyncio.sleep(0.8) # Allow telephony buffer to finish draining to PSTN
                                        logger.info(f"Terminating WebSocket connection for {call_sid}")
                                        try:
                                            await websocket.close()
                                        except Exception:
                                            pass
                                        if call_sid:
                                            db_manager.log_call_end(call_sid)
                                        break

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
