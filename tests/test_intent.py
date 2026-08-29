from datetime import UTC, datetime
from uuid import uuid4

from memory_bot.services.ai import AIService
from memory_bot.types import SearchResult


def service() -> AIService:
    return AIService(None, "unused", "unused")


def test_fallback_answer_includes_clickable_url() -> None:
    result = SearchResult(
        id=uuid4(),
        kind="link",
        title="MediaCrawler",
        text_content="Repository tại https://github.com/NanmiCoder/MediaCrawler",
        caption=None,
        source_url="https://github.com/NanmiCoder/MediaCrawler",
        mime_type="text/html",
        telegram_file_id=None,
        storage_path=None,
        file_name=None,
        created_at=datetime(2026, 8, 27, tzinfo=UTC),
        snippet="MediaCrawler",
        score=1.0,
    )

    answer = service()._fallback_answer([result])

    assert "Link: https://github.com/NanmiCoder/MediaCrawler" in answer
    assert answer.count("https://github.com/NanmiCoder/MediaCrawler") == 1
