from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from memory_bot.bot import MemoryBot


class FakeStatus:
    def __init__(self, owner: "FakeMessage") -> None:
        self.owner = owner

    async def edit_text(self, text: str, **_kwargs: object) -> None:
        self.owner.edits.append(text)


class FakeMessage:
    def __init__(self, text: str) -> None:
        self.text = text
        self.from_user = SimpleNamespace(id=123)
        self.chat = SimpleNamespace(id=456)
        self.message_id = 789
        self.answers: list[str] = []
        self.edits: list[str] = []

    async def answer(self, text: str, **_kwargs: object) -> FakeStatus:
        self.answers.append(text)
        return FakeStatus(self)


def build_bot() -> MemoryBot:
    bot = object.__new__(MemoryBot)
    bot.settings = SimpleNamespace(
        allowed_telegram_user_ids=frozenset(),
        search_result_limit=5,
    )
    bot.database = SimpleNamespace(create_memory=AsyncMock())
    bot.memories = SimpleNamespace(search=AsyncMock(), index_text=AsyncMock())
    bot.ai = SimpleNamespace(
        answer=AsyncMock(),
        answer_general=AsyncMock(),
    )
    return bot


async def test_prefixed_text_saves_only_content_after_prefix() -> None:
    bot = build_bot()
    memory_id = uuid4()
    bot.database.create_memory = AsyncMock(return_value={"id": memory_id})
    message = FakeMessage("đây là   Kho prompt GPT-Image-2")

    await bot.handle_text(message)

    saved = bot.database.create_memory.await_args.args[0]
    assert saved.text_content == "Kho prompt GPT-Image-2"
    bot.memories.index_text.assert_awaited_once_with(memory_id, "Kho prompt GPT-Image-2")
    assert message.answers == ["Đã ghi nhớ thông tin này, ông chủ!"]


async def test_ordinary_text_searches_memory_and_answers_without_saving() -> None:
    bot = build_bot()
    bot.memories.search = AsyncMock(return_value=[])
    bot.ai.answer_general = AsyncMock(return_value="Paris là thủ đô của Pháp.")
    message = FakeMessage("Thủ đô Pháp là gì?")

    await bot.handle_text(message)

    bot.database.create_memory.assert_not_awaited()
    bot.memories.search.assert_awaited_once_with(123, "Thủ đô Pháp là gì?", 5)
    bot.ai.answer_general.assert_awaited_once_with("Thủ đô Pháp là gì?", [])
    assert message.answers == ["Tôi đang suy nghĩ…"]
    assert message.edits == ["Paris là thủ đô của Pháp."]


async def test_empty_explicit_save_is_rejected() -> None:
    bot = build_bot()
    message = FakeMessage("đây là   ")

    await bot.handle_text(message)

    bot.database.create_memory.assert_not_awaited()
    assert "nội dung phía sau" in message.answers[0]


async def test_find_answer_remains_memory_only() -> None:
    bot = build_bot()
    bot.memories.search = AsyncMock(return_value=[])
    bot.ai.answer = AsyncMock(return_value="Không tìm thấy trong bộ nhớ.")
    message = FakeMessage("/find thủ đô Pháp")

    await bot._answer_search(message, "thủ đô Pháp")

    bot.ai.answer.assert_awaited_once_with("thủ đô Pháp", [])
    bot.ai.answer_general.assert_not_awaited()
    assert message.edits == ["Không tìm thấy trong bộ nhớ."]
