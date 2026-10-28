# Voice Bot

A realtime voice bot that answers interview questions as me, built with FastAPI and Gemini Live.

## Run the server

Requires Python 3.10+ and a free Gemini API key from https://aistudio.google.com.

```bash
# 1. Install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Add your API key
cp .env.example .env
# edit .env and set GEMINI_API_KEY=your_key

# 3. Start the server
uvicorn app:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000 in Chrome, Edge or Safari and tap the mic.
