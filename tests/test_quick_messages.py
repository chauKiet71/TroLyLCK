from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from memory_bot.bot import MemoryBot
from memory_bot.database import Database


class FakeMessage:
    def __init__(self, text: str = "") -> None:
        self.text = text
        self.from_user = SimpleNamespace(id=123)
        self.answers: list[tuple[str, dict[str, object]]] = []

    async def answer(self, text: str, **kwargs: object) -> None:
        self.answers.append((text, kwargs))


class FakeCallback:
    def __init__(self, data: str, message: FakeMessage | None = None) -> None:
        self.data = data
        self.from_user = SimpleNamespace(id=123)
        self.message = message
        self.answers: list[tuple[str | None, dict[str, object]]] = []

    async def answer(self, text: str | None = None, **kwargs: object) -> None:
        self.answers.append((text, kwargs))


class FakeState:
    def __init__(self) -> None:
        self.current: str | None = None
        self.data: dict[str, object] = {}

    async def set_state(self, state: object) -> None:
        self.current = getattr(state, "state", str(state))

    async def update_data(self, **kwargs: object) -> None:
        self.data.update(kwargs)

    async def get_data(self) -> dict[str, object]:
        return self.data.copy()

    async def get_state(self) -> str | None:
        return self.current

    async def clear(self) -> None:
        self.current = None
        self.data.clear()


def build_bot() -> MemoryBot:
    bot = object.__new__(MemoryBot)
    bot.settings = SimpleNamespace(allowed_telegram_user_ids=frozenset())
    bot.database = SimpleNamespace()
    return bot


@pytest.mark.asyncio
async def test_quickadd_flow_saves_after_name_then_content() -> None:
    bot = build_bot()
    bot.database.quick_message_name_exists = AsyncMock(return_value=False)
    bot.database.create_quick_message = AsyncMock(
        return_value={"id": uuid4(), "name": "Chào khách", "content": "Xin chào anh/chị"}
    )
    state = FakeState()

    await bot.quickadd_command(FakeMessage("/quickadd"), state)
    assert state.current == "QuickMessageForm:name"

    name_message = FakeMessage("  Chào khách  ")
    await bot.quick_name_step(name_message, state)
    assert state.current == "QuickMessageForm:content"

    content_message = FakeMessage("Xin chào anh/chị")
    await bot.quick_content_step(content_message, state)

    assert state.current is None
    assert "Đã lưu tin nhắn nhanh “Chào khách”" in content_message.answers[0][0]
    bot.database.create_quick_message.assert_awaited_once_with(
        123, "Chào khách", "Xin chào anh/chị"
    )


@pytest.mark.asyncio
async def test_duplicate_quick_name_stays_at_name_step() -> None:
    bot = build_bot()
    bot.database.quick_message_name_exists = AsyncMock(return_value=True)
    state = FakeState()
    await state.set_state(SimpleNamespace(state="QuickMessageForm:name"))
    message = FakeMessage("Chào khách")

    await bot.quick_name_step(message, state)

    assert state.current == "QuickMessageForm:name"
    assert "đã tồn tại" in message.answers[0][0]


def test_quick_fields_enforce_telegram_limits() -> None:
    with pytest.raises(ValueError, match="Tên"):
        MemoryBot._validated_quick_name("   ")
    with pytest.raises(ValueError, match="64"):
        MemoryBot._validated_quick_name("x" * 65)
    with pytest.raises(ValueError, match="Nội dung"):
        MemoryBot._validated_quick_content("   ")
    with pytest.raises(ValueError, match="4.096"):
        MemoryBot._validated_quick_content("x" * 4097)


@pytest.mark.asyncio
async def test_quick_command_lists_owned_templates_as_buttons() -> None:
    template_id = uuid4()
    bot = build_bot()
    bot.database.list_quick_messages = AsyncMock(
        return_value=[{"id": template_id, "name": "Chào khách", "content": "Xin chào"}]
    )
    message = FakeMessage("/quick")

    await bot.quick_command(message)

    keyboard = message.answers[0][1]["reply_markup"]
    assert keyboard.inline_keyboard[0][0].text == "Chào khách"
    assert keyboard.inline_keyboard[0][0].callback_data == f"quick:send:{template_id}"


@pytest.mark.asyncio
async def test_quick_button_sends_owned_template_content() -> None:
    template_id = uuid4()
    bot = build_bot()
    bot.database.get_quick_message = AsyncMock(
        return_value={"id": template_id, "name": "Chào khách", "content": "Xin chào anh/chị"}
    )
    message = FakeMessage()
    callback = FakeCallback(f"quick:send:{template_id}", message)

    await bot.quick_send(callback)

    assert message.answers[0][0] == "Xin chào anh/chị"


@pytest.mark.asyncio
async def test_cancel_clears_active_quickadd_flow() -> None:
    bot = build_bot()
    state = FakeState()
    await state.set_state(SimpleNamespace(state="QuickMessageForm:content"))
    message = FakeMessage("/cancel")

    await bot.cancel_command(message, state)

    assert state.current is None
    assert message.answers[0][0] == "Đã hủy thao tác hiện tại."


@pytest.mark.asyncio
async def test_quick_message_database_reads_are_scoped_to_user() -> None:
    template_id = uuid4()
    database = object.__new__(Database)
    database._fetchall = AsyncMock(
        return_value=[{"id": template_id, "name": "Chào khách", "content": "Xin chào"}]
    )

    found = await database.get_quick_message(123, template_id)

    assert found is not None
    assert found["content"] == "Xin chào"
    assert database._fetchall.await_args.args[1] == (123, template_id)


@pytest.mark.asyncio
async def test_quick_message_database_writes_are_scoped_to_user() -> None:
    template_id = uuid4()
    database = object.__new__(Database)
    database._fetchall = AsyncMock(
        return_value=[{"id": template_id, "name": "Chào khách", "content": "Xin chào"}]
    )

    created = await database.create_quick_message(123, "Chào khách", "Xin chào")

    assert created is not None
    assert created["id"] == template_id
    assert database._fetchall.await_args.args[1] == (123, "Chào khách", "Xin chào")


@pytest.mark.asyncio
async def test_duplicate_quick_name_check_is_case_insensitive() -> None:
    database = object.__new__(Database)
    database._fetchall = AsyncMock(return_value=[{"exists": True}])

    exists = await database.quick_message_name_exists(123, "CHÀO KHÁCH")

    assert exists is True
    assert database._fetchall.await_args.args[1] == (123, "CHÀO KHÁCH")


@pytest.mark.asyncio
async def test_quick_message_list_is_scoped_to_user() -> None:
    database = object.__new__(Database)
    database._fetchall = AsyncMock(return_value=[])

    assert await database.list_quick_messages(123) == []
    assert database._fetchall.await_args.args[1] == (123,)
