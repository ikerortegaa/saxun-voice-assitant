"""Modelos de sesión y estado conversacional."""
from enum import Enum
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class ConversationState(str, Enum):
    GREETING = "greeting"
    INTENT_CAPTURE = "intent_capture"
    DISAMBIGUATION = "disambiguation"
    RAG_PROCESSING = "rag_processing"
    RESPONSE = "response"
    CONFIRMATION = "confirmation"
    MULTI_STEP = "multi_step"
    NO_EVIDENCE = "no_evidence"
    HANDOFF_PENDING = "handoff_pending"
    HANDOFF_ACTIVE = "handoff_active"
    CLOSING = "closing"
    ENDED = "ended"


class ConversationTurn(BaseModel):
    turn_number: int
    role: str  # "user" | "assistant"
    content: str
    content_redacted: Optional[str] = None
    confidence: Optional[float] = None
    action: Optional[str] = None
    citations: list[dict] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Session(BaseModel):
    session_id: str
    call_sid: str
    stream_sid: str = ""
    caller_hash: str
    language: str = "es"
    state: ConversationState = ConversationState.GREETING
    turns: list[ConversationTurn] = Field(default_factory=list)
    turn_count: int = 0
    handoff_triggered: bool = False
    failed_asr_count: int = 0           # reintentos ASR consecutivos fallidos
    unresolved_turns: int = 0           # turnos sin resolución del mismo tema
    tts_active: bool = False
    started_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict = Field(default_factory=dict)

    def add_turn(self, role: str, content: str, **kwargs) -> ConversationTurn:
        self.turn_count += 1
        turn = ConversationTurn(
            turn_number=self.turn_count,
            role=role,
            content=content,
            **kwargs,
        )
        self.turns.append(turn)
        return turn

    def get_history_for_llm(self, max_turns: int = 10) -> list[dict]:
        """Devuelve el historial en formato OpenAI messages (sin PII)."""
        recent = self.turns[-max_turns * 2:]
        return [
            {
                "role": t.role if t.role == "user" else "assistant",
                "content": t.content_redacted or t.content,
            }
            for t in recent
        ]
