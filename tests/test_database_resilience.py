from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from psycopg import OperationalError

from memory_bot.bot import MemoryBot
from memory_bot.database import Database
from memory_bot.services.ai import AIService


def test_database_pool_checks_connections_before_checkout(monkeypatch) -> None:
    captured_options: dict[str, object] = {}
    connection_check = AsyncMock()

    class CapturingPool:
        check_connection = connection_check

        def __init__(self, **options: object) -> None:
            captured_options.update(options)

    monkeypatch.setattr("memory_bot.database.AsyncConnectionPool", CapturingPool)

    Database("postgresql://user:password@localhost/database")

    assert captured_options["check"] is connection_check


class FakeMessage:
    def __init__(self, text: str) -> None:
        self.text = text
        self.from_user = SimpleNamespace(id=123)
        self.chat = SimpleNamespace(id=456)
        self.message_id = 789
        self.answers: list[str] = []

    async def answer(self, text: str, **_kwargs: object) -> None:
        self.answers.append(text)


@pytest.mark.asyncio
async def test_text_save_reports_database_disconnect_instead_of_going_silent() -> None:
    bot = object.__new__(MemoryBot)
    bot.settings = SimpleNamespace(allowed_telegram_user_ids=frozenset())
    bot.ai = AIService(None, "unused", "unused")
    bot.database = SimpleNamespace(
        create_memory=AsyncMock(
            side_effect=OperationalError(
                "consuming input failed: SSL connection has been closed unexpectedly"
            )
        )
    )
    bot.memories = SimpleNamespace()
    message = FakeMessage("đây là kho prompt GPT-Image-2, không có cấu trúc")

    escaped_error = None
    try:
        await bot.handle_text(message)
    except OperationalError as exc:
        escaped_error = exc

    assert escaped_error is None
    assert message.answers == [
        "Kết nối bộ nhớ vừa bị gián đoạn nên tôi chưa thể xác nhận đã lưu, ông chủ ạ. "
        "Vui lòng thử lại sau ít phút."
    ]
