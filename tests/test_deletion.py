from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from memory_bot.bot import MemoryBot
from memory_bot.database import Database
from memory_bot.services.storage import LocalStorage
from memory_bot.types import SearchResult


class FakeMessage:
    def __init__(self, text: str = "") -> None:
        self.text = text
        self.from_user = SimpleNamespace(id=123)
        self.chat = SimpleNamespace(id=456)
        self.message_id = 789
        self.answers: list[tuple[str, dict[str, object]]] = []
        self.edits: list[tuple[str, dict[str, object]]] = []

    async def answer(self, text: str, **kwargs: object) -> None:
        self.answers.append((text, kwargs))

    async def edit_text(self, text: str, **kwargs: object) -> None:
        self.edits.append((text, kwargs))


class FakeCallback:
    def __init__(self, data: str, message: FakeMessage | None = None) -> None:
        self.data = data
        self.from_user = SimpleNamespace(id=123)
        self.message = message
        self.answers: list[tuple[str | None, dict[str, object]]] = []

    async def answer(self, text: str | None = None, **kwargs: object) -> None:
        self.answers.append((text, kwargs))


def search_result() -> SearchResult:
    return SearchResult(
        id=uuid4(),
        kind="document",
        title=None,
        text_content="Báo cáo tháng 8",
        caption=None,
        source_url=None,
        mime_type="application/pdf",
        telegram_file_id="telegram-file",
        storage_path=None,
        file_name="bao-cao.pdf",
        created_at=datetime(2026, 8, 27, tzinfo=UTC),
        snippet="Báo cáo tháng 8",
        score=1.0,
    )


def build_bot(tmp_path: Path) -> MemoryBot:
    bot = object.__new__(MemoryBot)
    bot.settings = SimpleNamespace(allowed_telegram_user_ids=frozenset())
    bot.database = SimpleNamespace()
    bot.memories = SimpleNamespace()
    bot.storage = LocalStorage(tmp_path / "files")
    return bot


def test_delete_file_removes_file_inside_storage(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path / "files")
    stored = storage.root / "123" / "report.txt"
    stored.parent.mkdir()
    stored.write_text("content", encoding="utf-8")

    assert storage.delete_file(stored) is True
    assert not stored.exists()


def test_delete_file_rejects_path_outside_storage(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path / "files")
    outside = tmp_path / "private.txt"
    outside.write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="khong an toan"):
        storage.delete_file(outside)

    assert outside.exists()


@pytest.mark.asyncio
async def test_delete_memory_tree_scopes_root_and_children_to_same_user() -> None:
    memory_id = uuid4()
    database = object.__new__(Database)
    database._fetchall = AsyncMock(return_value=[{"storage_path": "stored/report.pdf"}])

    paths = await database.delete_memory_tree(123, memory_id)

    assert paths == ["stored/report.pdf"]
    params = database._fetchall.await_args.args[1]
    assert params == (memory_id, 123, 123)


@pytest.mark.asyncio
async def test_get_memory_requires_matching_user() -> None:
    result = search_result()
    database = object.__new__(Database)
    database._fetchall = AsyncMock(
        return_value=[
            {
                "id": result.id,
                "kind": result.kind,
                "title": result.title,
                "text_content": result.text_content,
                "caption": result.caption,
                "source_url": result.source_url,
                "mime_type": result.mime_type,
                "telegram_file_id": result.telegram_file_id,
                "storage_path": result.storage_path,
                "file_name": result.file_name,
                "created_at": result.created_at,
                "snippet": result.snippet,
                "score": 0.0,
            }
        ]
    )

    found = await database.get_memory(123, result.id)

    assert found is not None
    assert found.id == result.id
    params = database._fetchall.await_args.args[1]
    assert params == (123, result.id)


def test_forget_callback_requires_expected_action_and_valid_uuid() -> None:
    memory_id = uuid4()

    assert MemoryBot._forget_callback_uuid(f"forget:confirm:{memory_id}", "confirm") == memory_id
    assert MemoryBot._forget_callback_uuid(f"forget:pick:{memory_id}", "confirm") is None
    assert MemoryBot._forget_callback_uuid("forget:confirm:not-a-uuid", "confirm") is None


@pytest.mark.asyncio
async def test_forget_command_lists_search_results_as_buttons(tmp_path: Path) -> None:
    result = search_result()
    bot = build_bot(tmp_path)
    bot.memories.search = AsyncMock(return_value=[result])
    message = FakeMessage("/forget báo cáo tháng 8")

    await bot.forget_command(message)

    answer, options = message.answers[0]
    assert "bao-cao.pdf" in answer
    keyboard = options["reply_markup"]
    assert keyboard.inline_keyboard[0][0].callback_data == f"forget:pick:{result.id}"


@pytest.mark.asyncio
async def test_forget_pick_asks_for_final_confirmation(tmp_path: Path) -> None:
    result = search_result()
    bot = build_bot(tmp_path)
    bot.database.get_memory = AsyncMock(return_value=result)
    message = FakeMessage()
    callback = FakeCallback(f"forget:pick:{result.id}", message)

    await bot.forget_pick(callback)

    edited, options = message.edits[0]
    assert "Xác nhận xóa" in edited
    keyboard = options["reply_markup"]
    assert keyboard.inline_keyboard[0][0].callback_data == f"forget:confirm:{result.id}"


@pytest.mark.asyncio
async def test_forget_confirm_deletes_database_record_and_local_file(tmp_path: Path) -> None:
    result = search_result()
    bot = build_bot(tmp_path)
    stored = bot.storage.root / "123" / "bao-cao.pdf"
    stored.parent.mkdir()
    stored.write_text("content", encoding="utf-8")
    bot.database.get_memory = AsyncMock(return_value=result)
    bot.database.delete_memory_tree = AsyncMock(return_value=[str(stored)])
    message = FakeMessage()
    callback = FakeCallback(f"forget:confirm:{result.id}", message)

    await bot.forget_confirm(callback)

    assert not stored.exists()
    assert "Đã xóa" in message.edits[0][0]


@pytest.mark.asyncio
async def test_forget_cancel_keeps_data_and_closes_confirmation(tmp_path: Path) -> None:
    bot = build_bot(tmp_path)
    message = FakeMessage()
    callback = FakeCallback("forget:cancel", message)

    await bot.forget_cancel(callback)

    assert message.edits[0][0] == "Đã hủy thao tác xóa."
