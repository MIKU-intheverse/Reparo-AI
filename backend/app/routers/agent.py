from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agent.engine import chat
from app.core.deps import get_current_user
from app.database import get_db
from app.models import User

router = APIRouter(prefix="/api/agent", tags=["agent"])


class ChatMessage(BaseModel):
    message: str
    history: list[dict] = []


@router.post("/chat")
def agent_chat(payload: ChatMessage, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    result = chat(payload.message, payload.history, user, db)
    return {"reply": result["reply"], "tool_trace": result["trace"], "environment": user.environment}
