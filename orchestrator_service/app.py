from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Dict, Any
from hospital_chatbot_orchestrator import HospitalChatbot
from voice_call_scheduler import voice_scheduler

app = FastAPI(title="Hospital Orchestrator API")

# Initialize chatbot once per process
_chatbot = HospitalChatbot()

class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    voice_call: bool = False

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.on_event("startup")
async def _start_scheduler():
    try:
        await voice_scheduler.start()
    except Exception as e:
        # Don't crash app on scheduler failure; report in health logs
        print(f"[orchestrator] Warning: failed to start voice scheduler: {e}")

@app.on_event("shutdown")
async def _stop_scheduler():
    try:
        await voice_scheduler.stop()
    except Exception:
        pass

@app.post("/chat")
async def chat(req: ChatRequest):
    text = req.message if not req.voice_call else f"[VOICE_CALL] {req.message}"
    result = _chatbot.chat(text, conversation_id=req.conversation_id)
    return result
