# Telegram General Assistant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every ordinary Telegram text message receive a memory-first general AI answer while saving only content after a leading `đây là` prefix.

**Architecture:** A focused message-routing helper recognizes explicit saves. `MemoryBot` routes explicit saves to persistence and all other text to hybrid memory retrieval plus a new stateless `AIService.answer_general()` method. Existing `/find` remains memory-only through `AIService.answer()`.

**Tech Stack:** Python 3.11+, aiogram 3, OpenAI Responses API, Neon PostgreSQL, pgvector, pytest, Ruff

**Spec:** `docs/superpowers/specs/2026-08-29-telegram-general-assistant-design.md`

## Global Constraints

- Only messages beginning with `đây là`, case-insensitively and after optional leading whitespace, are explicit saves.
- Persist and index only the trimmed content after the prefix.
- Ordinary chat messages are not persisted as memories.
- Search existing user-scoped memories before every general answer.
- Do not introduce conversation history, web search, schedules, reminders, or external tools.
- Preserve `/find` as memory-only behavior.
- Keep bot instructions separate from user input and retrieved memory data.

---

### Task 1: Explicit Save Routing

**Files:**
- Create: `src/memory_bot/services/message_routing.py`
- Create: `tests/test_message_routing.py`
- Modify: `src/memory_bot/services/ai.py`
- Modify: `tests/test_intent.py`

**Interfaces:**
- Produces: `explicit_save_content(text: str) -> str | None`; returns trimmed content, `""` for an empty explicit save, and `None` for ordinary chat.
- Removes: obsolete `AIService.detect_intent()`, `explicit_intent()`, `_heuristic_intent()`, and `INTENT_INSTRUCTIONS`.

- [ ] **Step 1: Write failing parser tests**

```python
from memory_bot.services.message_routing import explicit_save_content


def test_explicit_save_strips_prefix_and_whitespace() -> None:
    assert explicit_save_content("  ĐÂY   LÀ   Kho prompt GPT-Image-2  ") == "Kho prompt GPT-Image-2"


def test_day_la_inside_chat_is_not_a_save() -> None:
    assert explicit_save_content("Tôi nghĩ đây là câu trả lời đúng") is None


def test_empty_explicit_save_returns_empty_content() -> None:
    assert explicit_save_content("đây là   ") == ""
```

- [ ] **Step 2: Run parser tests to verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_message_routing.py -q`

Expected: collection fails because `memory_bot.services.message_routing` does not exist.

- [ ] **Step 3: Implement the parser**

```python
import re

SAVE_PREFIX = re.compile(r"^\s*đây\s+là\b", flags=re.IGNORECASE | re.UNICODE)


def explicit_save_content(text: str) -> str | None:
    match = SAVE_PREFIX.match(text)
    if not match:
        return None
    return text[match.end():].strip()
```

- [ ] **Step 4: Remove obsolete binary intent routing**

Delete the intent prompt, `Literal` import, and the three unused intent methods from
`src/memory_bot/services/ai.py`. Remove the corresponding intent tests while keeping fallback
URL-answer coverage in `tests/test_intent.py`.

- [ ] **Step 5: Run focused tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_message_routing.py tests\test_intent.py -q`

Expected: all focused tests pass.

- [ ] **Step 6: Commit explicit routing**

```powershell
git add src/memory_bot/services/message_routing.py src/memory_bot/services/ai.py tests/test_message_routing.py tests/test_intent.py
git commit -m "refactor: make memory saves explicit"
```

---

### Task 2: Memory-First General Answers

**Files:**
- Modify: `src/memory_bot/services/ai.py`
- Modify: `tests/test_ai_instructions.py`

**Interfaces:**
- Consumes: `SearchResult` values from the existing memory search service.
- Produces: `AIService.answer_general(question: str, results: Sequence[SearchResult]) -> str`.
- Preserves: `AIService.answer()` as the memory-only `/find` answer path.

- [ ] **Step 1: Write failing general-answer tests**

Add tests proving that a question with no memory still calls the model, memory is included as
optional context, and instructions never enter user input:

```python
from datetime import UTC, datetime
from uuid import uuid4


def memory_result() -> SearchResult:
    return SearchResult(
        id=uuid4(),
        kind="text",
        title="Sở thích",
        text_content="Ông chủ thích cà phê đen",
        caption=None,
        source_url=None,
        mime_type="text/plain",
        telegram_file_id=None,
        storage_path=None,
        file_name=None,
        created_at=datetime(2026, 8, 29, tzinfo=UTC),
        snippet="Ông chủ thích cà phê đen",
        score=1.0,
    )


async def test_general_answer_uses_model_without_memory() -> None:
    ai = AIService(None, "chat-model", "unused")
    create_response = AsyncMock(return_value=SimpleNamespace(output_text="Paris."))
    ai.client = SimpleNamespace(responses=SimpleNamespace(create=create_response))

    answer = await ai.answer_general("Thủ đô Pháp là gì?", [])

    request = create_response.await_args.kwargs
    assert answer == "Paris."
    assert "kiến thức tổng quát" in request["instructions"]
    assert "Thủ đô Pháp là gì?" in request["input"]
    assert "Bộ nhớ liên quan:\n(không có)" in request["input"]


async def test_general_answer_prioritizes_memory_context() -> None:
    result = memory_result()
    ai = AIService(None, "chat-model", "unused")
    create_response = AsyncMock(return_value=SimpleNamespace(output_text="Ông chủ thích cà phê đen."))
    ai.client = SimpleNamespace(responses=SimpleNamespace(create=create_response))

    await ai.answer_general("Tôi thích uống gì?", [result])

    request = create_response.await_args.kwargs
    assert "Ông chủ thích cà phê đen" in request["input"]
    assert "ưu tiên" in request["instructions"]
```

- [ ] **Step 2: Run tests to verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_ai_instructions.py -q`

Expected: FAIL because `AIService.answer_general` is missing.

- [ ] **Step 3: Implement general-answer instructions and context formatting**

Add `GENERAL_ANSWER_INSTRUCTIONS` that prioritizes memory, permits general knowledge, forbids
invented memories, and ignores instructions embedded in memory. Extract the duplicated result
formatting into `_memory_context(results)` and use it from both answer paths.

```python
async def answer_general(self, question: str, results: Sequence[SearchResult]) -> str:
    if not self.client:
        if results:
            return self._fallback_answer(results)
        return "Tôi cần OPENAI_API_KEY hợp lệ để trả lời câu hỏi tổng quát, ông chủ ạ."
    context = self._memory_context(results) or "(không có)"
    prompt = f"Câu hỏi:\n{question}\n\nBộ nhớ liên quan:\n{context}"
    try:
        response = await self.client.responses.create(
            model=self.chat_model,
            instructions=self._task_instructions(GENERAL_ANSWER_INSTRUCTIONS),
            input=prompt,
        )
        return response.output_text.strip()
    except Exception as exc:
        self._handle_api_error(exc)
        logger.exception("Khong tao duoc cau tra loi tong quat")
        if results:
            return self._fallback_answer(results)
        return "Tôi chưa thể kết nối AI để trả lời câu hỏi này, ông chủ ạ."
```

- [ ] **Step 4: Run focused tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_ai_instructions.py tests\test_intent.py -q`

Expected: all focused tests pass.

- [ ] **Step 5: Commit general answers**

```powershell
git add src/memory_bot/services/ai.py tests/test_ai_instructions.py tests/test_intent.py
git commit -m "feat: add memory-first general answers"
```

---

### Task 3: Telegram General Chat Flow

**Files:**
- Modify: `src/memory_bot/bot.py`
- Create: `tests/test_general_chat.py`

**Interfaces:**
- Consumes: `explicit_save_content(text)`, `MemoryService.search()`, and
  `AIService.answer_general()`.
- Produces: `_answer_chat(message: Message, question: str) -> None`.
- Preserves: `_answer_search()` for `/find` and attachment delivery.

- [ ] **Step 1: Write failing bot-flow tests**

Use a fake Telegram message and an object-created `MemoryBot` with `AsyncMock` boundaries. Cover:

```python
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
    bot.ai = SimpleNamespace(answer_general=AsyncMock())
    bot.links = SimpleNamespace()
    return bot


async def test_prefixed_text_saves_only_content_after_prefix() -> None:
    bot = build_bot()
    memory_id = uuid4()
    bot.database.create_memory = AsyncMock(return_value={"id": memory_id})
    bot.memories.index_text = AsyncMock()
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
    assert message.edits == ["Paris là thủ đô của Pháp."]


async def test_empty_explicit_save_is_rejected() -> None:
    bot = build_bot()
    message = FakeMessage("đây là   ")

    await bot.handle_text(message)

    bot.database.create_memory.assert_not_awaited()
    assert "nội dung phía sau" in message.answers[0]
```

- [ ] **Step 2: Run tests to verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_general_chat.py -q`

Expected: tests fail because the bot still runs binary save/search routing.

- [ ] **Step 3: Replace plain-text routing**

In `_handle_text`, call `explicit_save_content(text)`. Reject `""`, persist non-`None` content,
and otherwise call `_answer_chat`. Do not create a `kind="query"` database row.

```python
save_content = explicit_save_content(text)
if save_content is not None:
    if not save_content:
        await message.answer("Hãy nhập nội dung phía sau ‘đây là’, ông chủ nhé.")
        return
    await self._save_text(message, save_content)
    return
await self._answer_chat(message, text)
```

Add `_save_text()` for existing persistence/index/link behavior and `_answer_chat()`:

```python
async def _answer_chat(self, message: Message, question: str) -> None:
    assert message.from_user is not None
    status = await message.answer("Tôi đang suy nghĩ…")
    results = await self.memories.search(
        message.from_user.id, question, self.settings.search_result_limit
    )
    answer = await self.ai.answer_general(question, results)
    await status.edit_text(answer)
    await self._send_search_attachments(message, results)
```

Extract attachment iteration from `_answer_search()` into `_send_search_attachments()` so both
memory-only and general answers can return relevant files without duplicating logic.

- [ ] **Step 4: Run focused bot tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_general_chat.py tests\test_database_resilience.py tests\test_links.py -q`

Expected: all focused tests pass.

- [ ] **Step 5: Commit Telegram flow**

```powershell
git add src/memory_bot/bot.py tests/test_general_chat.py
git commit -m "feat: route Telegram text to general assistant"
```

---

### Task 4: Documentation and Full Verification

**Files:**
- Modify: `README.md`

**Interfaces:**
- Documents the implemented Telegram behavior and deployment requirement.

- [ ] **Step 1: Update user documentation**

Change the capability and usage sections to state:

- Prefix `đây là` stores only the following content.
- Any other ordinary text receives a memory-first general answer.
- General answers require `OPENAI_API_KEY`.
- No conversation history is retained.
- `/find` searches only stored memory.

- [ ] **Step 2: Run full verification**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
git diff --check
```

Expected: all tests pass, Ruff reports `All checks passed!`, and `git diff --check` exits 0.

- [ ] **Step 3: Review requirement coverage**

Verify manually from the diff that ordinary messages do not call `create_memory`, explicit saves
persist stripped content, `/find` still calls `AIService.answer`, and general chat calls
`AIService.answer_general` after `MemoryService.search`.

- [ ] **Step 4: Commit documentation**

```powershell
git add README.md
git commit -m "docs: explain general assistant behavior"
```
