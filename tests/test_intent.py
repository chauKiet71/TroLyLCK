from datetime import UTC, datetime
from uuid import uuid4

from memory_bot.services.ai import AIService
from memory_bot.types import SearchResult


def service() -> AIService:
    return AIService(None, "unused", "unused")


def test_question_is_search() -> None:
    assert service()._heuristic_intent("Hình như có file báo cáo rồi đúng không?") == "search"


def test_statement_is_saved() -> None:
    assert service()._heuristic_intent("Doanh thu tháng 8 là 500 triệu") == "save"


def test_day_la_is_explicit_save_case_insensitive() -> None:
    assert service().explicit_intent("Đây là Repo tôi cần lưu") == "save"
    assert service().explicit_intent("đây   là báo cáo tháng 8") == "save"


def test_k_ko_khong_are_explicit_search_words() -> None:
    assert service().explicit_intent("Có báo cáo k") == "search"
    assert service().explicit_intent("Có báo cáo KO?") == "search"
    assert service().explicit_intent("Có báo cáo không?") == "search"


def test_day_la_has_priority_over_search_words() -> None:
    assert service().explicit_intent("Đây là tài liệu, đúng không?") == "save"


def test_letter_k_inside_another_word_is_not_search() -> None:
    assert service().explicit_intent("Thông tin trong kho lưu trữ") is None


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
