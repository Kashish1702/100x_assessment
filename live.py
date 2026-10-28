"""WebSocket proxy: browser <-> this server <-> Gemini Live.

Browser -> server messages (JSON):
  {"type": "config", "voice": "Puck"}      optional, first message
  {"type": "audio", "data": "<b64 PCM16 16kHz mono>"}
  {"type": "text", "data": "question"}
Server -> browser messages:
  ready | audio(b64 PCM16 24kHz) | transcript(role,text) | turn_complete | interruption | error
"""
import asyncio
import base64
import json
import logging

import websockets
from fastapi import WebSocket, WebSocketDisconnect

from config import Config

log = logging.getLogger("live")


def setup_message(voice: str) -> dict:
    return {
        "setup": {
            "model": f"models/{Config.GEMINI_LIVE_MODEL}",
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "temperature": Config.DEFAULT_TEMPERATURE,
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
            },
            "systemInstruction": {"parts": [{"text": Config.system_prompt()}]},
            "inputAudioTranscription": {},
            "outputAudioTranscription": {},
        }
    }


async def handle_live(ws: WebSocket):
    await ws.accept()
    if not Config.GEMINI_API_KEY:
        await ws.send_json({"type": "error", "message": Config.ERROR_MESSAGES["no_key"]})
        await ws.close()
        return

    voice = Config.DEFAULT_VOICE
    pending = None  # first message may be config; anything else is replayed after setup
    try:
        first = json.loads(await asyncio.wait_for(ws.receive_text(), timeout=10))
        if first.get("type") == "config":
            if first.get("voice") in Config.VOICES:
                voice = first["voice"]
        else:
            pending = first
    except (asyncio.TimeoutError, ValueError):
        pass
    except WebSocketDisconnect:
        return

    url = f"{Config.GEMINI_LIVE_WS_URL}?key={Config.GEMINI_API_KEY}"
    try:
        async with websockets.connect(url, max_size=None) as upstream:
            await upstream.send(json.dumps(setup_message(voice)))
            first_reply = json.loads(await asyncio.wait_for(upstream.recv(), timeout=15))
            if "setupComplete" not in first_reply:
                raise RuntimeError(f"unexpected setup reply: {str(first_reply)[:200]}")
            await ws.send_json({"type": "ready", "voice": voice})

            async def client_to_gemini():
                msg = pending
                while True:
                    if msg is None:
                        msg = json.loads(await ws.receive_text())
                    kind = msg.get("type")
                    if kind == "audio":
                        await upstream.send(json.dumps({"realtimeInput": {"audio": {
                            "data": msg["data"],
                            "mimeType": f"audio/pcm;rate={Config.AUDIO_SAMPLE_RATE}"}}}))
                    elif kind == "text" and str(msg.get("data", "")).strip():
                        text = str(msg["data"])[: Config.MAX_TEXT_LENGTH]
                        await upstream.send(json.dumps({"realtimeInput": {"text": text}}))
                    msg = None

            async def gemini_to_client():
                async for raw in upstream:
                    data = json.loads(raw)
                    sc = data.get("serverContent")
                    if not sc:
                        continue
                    if sc.get("interrupted"):
                        await ws.send_json({"type": "interruption"})
                    for part in sc.get("modelTurn", {}).get("parts", []):
                        inline = part.get("inlineData")
                        if inline and inline.get("data"):
                            await ws.send_json({"type": "audio", "data": inline["data"]})
                    for key, role in (("inputTranscription", "user"), ("outputTranscription", "bot")):
                        text = sc.get(key, {}).get("text")
                        if text:
                            await ws.send_json({"type": "transcript", "role": role, "text": text})
                    if sc.get("turnComplete"):
                        await ws.send_json({"type": "turn_complete"})

            tasks = [asyncio.create_task(client_to_gemini()), asyncio.create_task(gemini_to_client())]
            done, rest = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in rest:
                t.cancel()
            for t in done:
                exc = t.exception()
                if exc and not isinstance(exc, (WebSocketDisconnect, websockets.ConnectionClosed)):
                    raise exc
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001 - report any upstream failure to the user
        log.exception("live session failed: %r", e)
        try:
            await ws.send_json({"type": "error", "message": Config.ERROR_MESSAGES["upstream"]})
            await ws.close()
        except Exception:  # noqa: BLE001
            pass
