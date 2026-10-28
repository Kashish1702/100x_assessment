# Central configuration for the voice bot (mirrors the Config-class pattern of the reference project)
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE = Path(__file__).parent


class Config:
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    GEMINI_URL = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent"
    )

    # Gemini Live (realtime voice over WebSocket)
    GEMINI_LIVE_MODEL = os.getenv("GEMINI_LIVE_MODEL", "gemini-2.5-flash-native-audio-latest")
    GEMINI_LIVE_WS_URL = os.getenv(
        "GEMINI_LIVE_WS_URL",
        "wss://generativelanguage.googleapis.com/ws/"
        "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent",
    )
    VOICES = ["Puck", "Charon", "Kore", "Fenrir", "Aoede"]
    DEFAULT_VOICE = os.getenv("GEMINI_VOICE", "Puck")
    AUDIO_SAMPLE_RATE = 16000          # mic -> Gemini
    AUDIO_OUTPUT_SAMPLE_RATE = 24000   # Gemini -> speaker

    DEFAULT_TEMPERATURE = 0.8
    MAX_OUTPUT_TOKENS = 400
    MAX_HISTORY_TURNS = 12      # turns of context the browser sends
    MAX_TEXT_LENGTH = 2000
    REQUEST_TIMEOUT = 30        # seconds

    PERSONA_FILE = BASE / "persona.md"

    # Spoken-answer rules, always prepended to the persona knowledge base
    SYSTEM_RULES = """You are being interviewed by voice. Speak as the person described in the profile below.

Rules:
- Always answer in the first person, as this person. Never say you are an AI assistant.
- Keep answers spoken-style: 3-5 sentences, no bullet points, no markdown, no emojis, no links.
- When asked a question from the profile, answer from the provided facts but phrase it naturally. Do not repeat the text verbatim.
- Never invent employers, degrees, numbers or events that are not in the profile. If unsure, say so briefly and pivot to a related true fact.
- If asked whether you are an AI, say you are a voice version of this person built for the assessment.
- If the user writes in another language, reply in that language when possible.
- Stay on topic: career, skills, personality, motivation, work style. Politely steer back otherwise.
"""

    ERROR_MESSAGES = {
        "no_key": "Server is missing GEMINI_API_KEY",
        "upstream": "The AI service had a problem, please try again",
        "empty": "Empty response from the AI service",
    }

    @classmethod
    def system_prompt(cls) -> str:
        return cls.SYSTEM_RULES + "\n### Profile\n" + cls.PERSONA_FILE.read_text(encoding="utf-8")
