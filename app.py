import httpx
from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config import BASE, Config
from live import handle_live

PERSONA = Config.system_prompt()

app = FastAPI()


class Turn(BaseModel):
    role: str  # "user" or "model"
    text: str = Field(max_length=Config.MAX_TEXT_LENGTH)


class ChatIn(BaseModel):
    history: list[Turn] = Field(max_length=Config.MAX_HISTORY_TURNS * 2)


@app.post("/api/chat")
async def chat(body: ChatIn):
    if not Config.GEMINI_API_KEY:
        raise HTTPException(500, Config.ERROR_MESSAGES["no_key"])
    payload = {
        "systemInstruction": {"parts": [{"text": PERSONA}]},
        "contents": [
            {"role": "user" if t.role == "user" else "model", "parts": [{"text": t.text}]}
            for t in body.history
        ],
        "generationConfig": {"temperature": Config.DEFAULT_TEMPERATURE,
                             "maxOutputTokens": Config.MAX_OUTPUT_TOKENS,
                             "thinkingConfig": {"thinkingBudget": 0}},
    }
    async with httpx.AsyncClient(timeout=Config.REQUEST_TIMEOUT) as client:
        r = await client.post(
            Config.GEMINI_URL, json=payload, headers={"x-goog-api-key": Config.GEMINI_API_KEY}
        )
    if r.status_code != 200:
        raise HTTPException(502, Config.ERROR_MESSAGES["upstream"])
    try:
        parts = r.json()["candidates"][0]["content"]["parts"]
        return {"reply": "".join(p.get("text", "") for p in parts).strip()}
    except (KeyError, IndexError):
        raise HTTPException(502, Config.ERROR_MESSAGES["empty"])


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await handle_live(ws)


@app.api_route("/", methods=["GET", "HEAD"])
async def index():
    return FileResponse(BASE / "static" / "index.html")


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
