from datetime import UTC, datetime
from uuid import uuid4

from memory_bot.services.memory import filter_relevant_results
from memory_bot.types import SearchResult


def result(score: float, title: str) -> SearchResult:
    return SearchResult(
        id=uuid4(),
        kind="text",
        title=title,
        text_content=title,
        caption=None,
        source_url=None,
        mime_type=None,
        telegram_file_id=None,
        storage_path=None,
        file_name=None,
        created_at=datetime(2026, 8, 27, tzinfo=UTC),
        snippet=title,
        score=score,
    )


def test_weak_partial_match_is_removed() -> None:
    chinese_initials = result(1.1, "Bảng thanh mẫu tiếng Trung")
    english_ipa = result(0.7, "Bảng IPA tiếng Anh")

    filtered = filter_relevant_results([english_ipa, chinese_initials])

    assert filtered == [chinese_initials]


def test_similarly_relevant_results_are_kept() -> None:
    august = result(1.1, "Báo cáo tháng 8")
    august_revised = result(0.9, "Báo cáo tháng 8 bản sửa")

    assert filter_relevant_results([august, august_revised]) == [august, august_revised]
