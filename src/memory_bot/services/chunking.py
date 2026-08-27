from __future__ import annotations


def chunk_text(text: str, max_chars: int = 3500, overlap_chars: int = 350) -> list[str]:
    """Split text on paragraph boundaries while retaining a small overlap."""
    normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if not normalized:
        return []
    if len(normalized) <= max_chars:
        return [normalized]

    paragraphs = normalized.split("\n")
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            start = 0
            while start < len(paragraph):
                end = min(start + max_chars, len(paragraph))
                chunks.append(paragraph[start:end])
                if end == len(paragraph):
                    break
                start = max(end - overlap_chars, start + 1)
            continue

        candidate = f"{current}\n{paragraph}" if current else paragraph
        if len(candidate) <= max_chars:
            current = candidate
            continue

        chunks.append(current)
        overlap = current[-overlap_chars:] if overlap_chars else ""
        current = f"{overlap}\n{paragraph}" if overlap else paragraph

    if current:
        chunks.append(current)
    return chunks
