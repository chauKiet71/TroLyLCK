from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

from memory_bot.database import Database
from memory_bot.services.ai import AIService
from memory_bot.services.chunking import chunk_text
from memory_bot.services.extractor import DocumentExtractor
from memory_bot.types import SearchResult

logger = logging.getLogger(__name__)


def filter_relevant_results(
    results: Sequence[SearchResult],
    *,
    relative_to_best: float = 0.75,
    absolute_minimum: float = 0.45,
) -> list[SearchResult]:
    """Drop weak partial matches when a clearly stronger result exists."""
    if not results:
        return []
    ordered = sorted(results, key=lambda item: item.score, reverse=True)
    threshold = max(absolute_minimum, ordered[0].score * relative_to_best)
    return [item for item in ordered if item.score >= threshold]


class MemoryService:
    def __init__(self, database: Database, ai: AIService) -> None:
        self.database = database
        self.ai = ai
        self.extractor = DocumentExtractor()

    async def index_text(self, memory_id: UUID, text: str) -> None:
        chunks = chunk_text(text)
        if not chunks:
            return
        embeddings = await self.ai.embed(chunks)
        await self.database.replace_chunks(memory_id, chunks, embeddings)

    async def index_file(
        self,
        memory_id: UUID,
        path: Path,
        mime_type: str | None,
        caption: str | None,
    ) -> str:
        if mime_type and mime_type.startswith("image/"):
            text = await self.ai.describe_image(path, caption)
            if text:
                await self.database.update_memory_content(
                    memory_id, text_content=text, metadata_patch={"image_analyzed": True}
                )
                await self.index_text(memory_id, text)
            return text

        try:
            extracted = await asyncio.to_thread(self.extractor.extract, path, mime_type)
        except Exception as exc:
            logger.exception("Khong trich xuat duoc file %s", path)
            await self.database.update_memory_content(
                memory_id, metadata_patch={"extract_error": type(exc).__name__}
            )
            return ""

        combined = "\n".join(part for part in (caption, extracted.text) if part)
        if extracted.text or extracted.title:
            await self.database.update_memory_content(
                memory_id,
                text_content=combined or None,
                title=extracted.title,
                metadata_patch={"text_extracted": bool(extracted.text)},
            )
        if combined:
            await self.index_text(memory_id, combined)
        return combined

    async def search(self, telegram_user_id: int, query: str, limit: int) -> list[SearchResult]:
        lexical_task = asyncio.create_task(
            self.database.lexical_search(telegram_user_id, query, limit)
        )
        query_embeddings = await self.ai.embed([query])
        semantic: Sequence[SearchResult] = []
        if query_embeddings and query_embeddings[0]:
            semantic = await self.database.semantic_search(
                telegram_user_id, query_embeddings[0], limit
            )
        lexical = await lexical_task

        combined: dict[UUID, SearchResult] = {}
        for result in semantic:
            combined[result.id] = result
        for result in lexical:
            if result.id in combined:
                combined[result.id].score += 0.2 + result.score
            else:
                result.score += 0.1
                combined[result.id] = result
        ranked = filter_relevant_results(list(combined.values()))
        return ranked[:limit]
