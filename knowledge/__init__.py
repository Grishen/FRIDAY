"""Local RAG (retrieval) over text files in knowledge_docs/."""

from .rag_store import answer_from_knowledge, sync_knowledge_folder
from .voice_triggers import extract_kb_question, wants_knowledge_lookup

__all__ = [
    "answer_from_knowledge",
    "sync_knowledge_folder",
    "wants_knowledge_lookup",
    "extract_kb_question",
]
