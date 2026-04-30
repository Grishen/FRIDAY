"""Chunk plain text for embedding (fixed windows with overlap)."""


def split_text_into_chunks(
    text: str,
    *,
    max_chars: int = 900,
    overlap: int = 80,
) -> list[str]:
    cleaned = text.replace("\r\n", "\n").strip()
    if not cleaned:
        return []
    step = max(1, max_chars - overlap)
    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        end = min(start + max_chars, len(cleaned))
        piece = cleaned[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(cleaned):
            break
        start += step
    return chunks
