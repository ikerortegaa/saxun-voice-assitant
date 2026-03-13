"""Modelos del pipeline RAG."""
from enum import Enum
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field


class RAGAction(str, Enum):
    RESPOND = "respond"
    HANDOFF = "handoff"
    NO_EVIDENCE = "no_evidence"
    CLARIFY = "clarify"
    CONFIRM_STEPS = "confirm_steps"


class Chunk(BaseModel):
    chunk_id: str
    doc_id: str
    content: str
    section: str = ""
    language: str = "es"
    sensitivity: str = "public"
    status: str = "active"
    score: float = 0.0       # score de retrieval (RRF o reranker)
    metadata: dict = Field(default_factory=dict)


class Citation(BaseModel):
    chunk_id: str
    doc_id: str
    doc_title: str
    section: str = ""
    relevance_score: float


class RetrievalResult(BaseModel):
    chunks: list[Chunk]
    query: str
    method: str = "hybrid"   # hybrid | dense | sparse
    latency_ms: float = 0.0


class LLMResponse(BaseModel):
    response_text: str
    confidence: float = 0.0
    action: RAGAction = RAGAction.RESPOND
    citations: list[Citation] = Field(default_factory=list)
    evidence_found: bool = False
    language: str = "es"
    handoff_reason: Optional[str] = None
    needs_confirmation: bool = False
    raw_response: Optional[str] = None   # JSON raw del LLM para debugging


class DocumentRecord(BaseModel):
    doc_id: str
    file_path: str
    file_hash: str
    title: str = ""
    version: str = "1.0"
    status: str = "active"   # active | superseded | expired
    language: str = "es"
    sensitivity: str = "public"
    effective_date: Optional[datetime] = None
    expiry_date: Optional[datetime] = None
    chunk_count: int = 0
    ingested_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict = Field(default_factory=dict)
