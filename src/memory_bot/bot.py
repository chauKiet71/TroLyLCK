from __future__ import annotations

import logging
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from psycopg import OperationalError

from memory_bot.config import Settings
from memory_bot.database import Database
from memory_bot.services.ai import AIService
from memory_bot.services.links import LinkReader, extract_urls
from memory_bot.services.memory import MemoryService
from memory_bot.services.storage import LocalStorage
from memory_bot.types import MemoryCreate, SearchResult

logger = logging.getLogger(__name__)


class QuickMessageForm(StatesGroup):
    name = State()
    content = State()


@dataclass(slots=True)
class MediaInfo:
    kind: str
    file_id: str
    file_unique_id: str
    file_name: str
    mime_type: str | None
    file_size: int | None


class MemoryBot:
    def __init__(
        self,
        settings: Settings,
        database: Database,
        ai: AIService,
        memory_service: MemoryService,
        storage: LocalStorage,
    ) -> None:
        self.settings = settings
        self.database = database
        self.ai = ai
        self.memories = memory_service
        self.storage = storage
        self.links = LinkReader(settings.max_download_bytes)
        self.router = Router(name="memory_bot")
        self._register_handlers()

    def _register_handlers(self) -> None:
        self.router.message.register(self.start, CommandStart())
        self.router.message.register(self.help, Command("help"))
        self.router.message.register(self.show_id, Command("id"))
        self.router.message.register(self.find_command, Command("find"))
        self.router.message.register(self.recent_command, Command("recent"))
        self.router.message.register(self.forget_command, Command("forget"))
        self.router.message.register(self.quickadd_command, Command("quickadd"))
        self.router.message.register(self.quick_command, Command("quick"))
        self.router.message.register(self.cancel_command, Command("cancel"))
        self.router.callback_query.register(self.forget_pick, F.data.startswith("forget:pick:"))
        self.router.callback_query.register(
            self.forget_confirm, F.data.startswith("forget:confirm:")
        )
        self.router.callback_query.register(self.forget_cancel, F.data == "forget:cancel")
        self.router.callback_query.register(self.quick_send, F.data.startswith("quick:send:"))
        self.router.message.register(
            self.quick_name_step, StateFilter(QuickMessageForm.name), F.text
        )
        self.router.message.register(
            self.quick_content_step, StateFilter(QuickMessageForm.content), F.text
        )
        self.router.message.register(self.handle_text, F.text)
        self.router.message.register(
            self.handle_media,
            F.photo
            | F.document
            | F.audio
            | F.video
            | F.voice
            | F.animation
            | F.video_note
            | F.sticker,
        )

    def _is_allowed(self, message: Message) -> bool:
        if not message.from_user:
            return False
        allowed = self.settings.allowed_telegram_user_ids
        return not allowed or message.from_user.id in allowed

    async def _guard(self, message: Message) -> bool:
        if self._is_allowed(message):
            return True
        await message.answer("Bot này là trợ lý riêng và tài khoản của bạn chưa được cấp quyền.")
        return False

    async def start(self, message: Message) -> None:
        if not await self._guard(message):
            return
        await message.answer(
            "Tôi là trợ lý bộ nhớ của bạn. Hãy gửi tin nhắn, ảnh, file hoặc đường link; "
            "tôi sẽ lưu và lập chỉ mục để tìm lại sau.\n\n"
            "Bạn có thể hỏi tự nhiên, ví dụ: “Gửi lại báo cáo tài chính tháng 8”.\n"
            "Lệnh nhanh:\n"
            "/find <nội dung> — tìm trực tiếp\n"
            "/recent — xem 10 mục gần nhất\n"
            "/forget <nội dung> — tìm và xóa an toàn\n"
            "/quickadd — tạo tin nhắn nhanh\n"
            "/quick — mở danh sách tin nhắn nhanh\n"
            "/cancel — hủy thao tác đang thực hiện\n"
            "/id — xem Telegram user ID\n"
            "/help — hướng dẫn"
        )

    async def help(self, message: Message) -> None:
        await self.start(message)

    async def show_id(self, message: Message) -> None:
        if not message.from_user:
            return
        await message.answer(f"Telegram user ID của bạn: {message.from_user.id}")

    async def find_command(self, message: Message) -> None:
        if not await self._guard(message):
            return
        query = (message.text or "").partition(" ")[2].strip()
        if not query:
            await message.answer("Cách dùng: /find báo cáo tài chính tháng 8")
            return
        await self._answer_search(message, query)

    async def recent_command(self, message: Message) -> None:
        if not await self._guard(message) or not message.from_user:
            return
        results = await self.database.recent(message.from_user.id, limit=10)
        if not results:
            await message.answer("Bộ nhớ hiện chưa có dữ liệu.")
            return
        lines = ["10 mục được lưu gần nhất:"]
        for index, result in enumerate(results, start=1):
            label = self._result_label(result)
            lines.append(f"{index}. {label} — {result.created_at:%d/%m/%Y %H:%M}")
        await message.answer("\n".join(lines))

    async def quickadd_command(self, message: Message, state: FSMContext) -> None:
        if not await self._guard(message):
            return
        await state.clear()
        await state.set_state(QuickMessageForm.name)
        await message.answer("Hãy nhập tên cho tin nhắn nhanh (tối đa 64 ký tự).")

    async def quick_name_step(self, message: Message, state: FSMContext) -> None:
        if not await self._guard(message) or not message.from_user:
            return
        try:
            name = self._validated_quick_name(message.text or "")
        except ValueError as exc:
            await message.answer(str(exc))
            return
        if await self.database.quick_message_name_exists(message.from_user.id, name):
            await message.answer("Tên này đã tồn tại. Hãy nhập một tên khác.")
            return
        await state.update_data(quick_name=name)
        await state.set_state(QuickMessageForm.content)
        await message.answer(f"Hãy nhập nội dung cho “{name}” (tối đa 4.096 ký tự).")

    async def quick_content_step(self, message: Message, state: FSMContext) -> None:
        if not await self._guard(message) or not message.from_user:
            return
        try:
            content = self._validated_quick_content(message.text or "")
        except ValueError as exc:
            await message.answer(str(exc))
            return
        data = await state.get_data()
        name = data.get("quick_name")
        if not isinstance(name, str):
            await state.clear()
            await message.answer("Phiên tạo tin nhắn đã hết hạn. Hãy dùng /quickadd để thử lại.")
            return
        created = await self.database.create_quick_message(
            message.from_user.id, name, content
        )
        await state.clear()
        if not created:
            await message.answer("Tên này vừa được sử dụng. Hãy dùng /quickadd với tên khác.")
            return
        await message.answer(f"Đã lưu tin nhắn nhanh “{name}”. Dùng /quick để gửi.")

    async def quick_command(self, message: Message) -> None:
        if not await self._guard(message) or not message.from_user:
            return
        templates = await self.database.list_quick_messages(message.from_user.id)
        if not templates:
            await message.answer("Bạn chưa có tin nhắn nhanh. Dùng /quickadd để tạo.")
            return
        buttons = [
            [
                InlineKeyboardButton(
                    text=template["name"], callback_data=f"quick:send:{template['id']}"
                )
            ]
            for template in templates
        ]
        await message.answer(
            "Chọn tin nhắn muốn gửi:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )

    async def quick_send(self, callback: CallbackQuery) -> None:
        if not await self._guard_callback(callback) or not callback.data:
            return
        template_id = self._quick_callback_uuid(callback.data)
        if not template_id:
            await callback.answer("Yêu cầu không hợp lệ.", show_alert=True)
            return
        template = await self.database.get_quick_message(callback.from_user.id, template_id)
        if not template:
            await callback.answer("Tin nhắn này không còn tồn tại.", show_alert=True)
            return
        await callback.answer()
        if callback.message is not None:
            await callback.message.answer(template["content"])

    async def cancel_command(self, message: Message, state: FSMContext) -> None:
        if not await self._guard(message):
            return
        if not await state.get_state():
            await message.answer("Hiện không có thao tác nào cần hủy.")
            return
        await state.clear()
        await message.answer("Đã hủy thao tác hiện tại.")

    @staticmethod
    def _validated_quick_name(value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("Tên tin nhắn không được để trống.")
        if len(name) > 64:
            raise ValueError("Tên tin nhắn không được dài quá 64 ký tự.")
        return name

    @staticmethod
    def _validated_quick_content(value: str) -> str:
        content = value.strip()
        if not content:
            raise ValueError("Nội dung tin nhắn không được để trống.")
        if len(content) > 4096:
            raise ValueError("Nội dung tin nhắn không được dài quá 4.096 ký tự.")
        return content

    @staticmethod
    def _quick_callback_uuid(data: str) -> UUID | None:
        prefix = "quick:send:"
        if not data.startswith(prefix):
            return None
        try:
            return UUID(data.removeprefix(prefix))
        except ValueError:
            return None

    async def forget_command(self, message: Message) -> None:
        if not await self._guard(message) or not message.from_user:
            return
        query = (message.text or "").partition(" ")[2].strip()
        if not query:
            await message.answer("Cách dùng: /forget nội dung hoặc tên file cần xóa")
            return
        results = await self.memories.search(message.from_user.id, query, limit=5)
        if not results:
            await message.answer("Tôi không tìm thấy mục phù hợp để xóa.")
            return

        lines = ["Chọn đúng mục bạn muốn xóa:"]
        buttons: list[list[InlineKeyboardButton]] = []
        for index, result in enumerate(results, start=1):
            lines.append(
                f"{index}. {self._result_label(result)} — "
                f"{result.created_at:%d/%m/%Y %H:%M}"
            )
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"Chọn mục {index}", callback_data=f"forget:pick:{result.id}"
                    )
                ]
            )
        buttons.append([InlineKeyboardButton(text="Hủy", callback_data="forget:cancel")])
        await message.answer(
            "\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )

    async def forget_pick(self, callback: CallbackQuery) -> None:
        if not await self._guard_callback(callback) or not callback.data:
            return
        memory_id = self._forget_callback_uuid(callback.data, "pick")
        if not memory_id:
            await callback.answer("Yêu cầu không hợp lệ.", show_alert=True)
            return
        result = await self.database.get_memory(callback.from_user.id, memory_id)
        if not result:
            await callback.answer("Mục này không còn tồn tại.", show_alert=True)
            return

        await callback.answer()
        if callback.message is not None:
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Xóa vĩnh viễn",
                            callback_data=f"forget:confirm:{memory_id}",
                        ),
                        InlineKeyboardButton(text="Hủy", callback_data="forget:cancel"),
                    ]
                ]
            )
            await callback.message.edit_text(
                f"Xác nhận xóa “{self._result_label(result)}”?\n"
                "Nội dung và chỉ mục tìm kiếm liên quan sẽ bị xóa.",
                reply_markup=keyboard,
            )

    async def forget_confirm(self, callback: CallbackQuery) -> None:
        if not await self._guard_callback(callback) or not callback.data:
            return
        memory_id = self._forget_callback_uuid(callback.data, "confirm")
        if not memory_id:
            await callback.answer("Yêu cầu không hợp lệ.", show_alert=True)
            return
        result = await self.database.get_memory(callback.from_user.id, memory_id)
        if not result:
            await callback.answer("Mục này không còn tồn tại.", show_alert=True)
            return

        stored_paths = await self.database.delete_memory_tree(callback.from_user.id, memory_id)
        for stored_path in stored_paths:
            try:
                self.storage.delete_file(stored_path)
            except (OSError, ValueError):
                logger.warning("Khong xoa duoc ban sao local %s", stored_path, exc_info=True)
        await callback.answer("Đã xóa.")
        if callback.message is not None:
            await callback.message.edit_text(f"Đã xóa “{self._result_label(result)}” khỏi bộ nhớ.")

    async def forget_cancel(self, callback: CallbackQuery) -> None:
        if not await self._guard_callback(callback):
            return
        await callback.answer("Đã hủy.")
        if callback.message is not None:
            await callback.message.edit_text("Đã hủy thao tác xóa.")

    async def _guard_callback(self, callback: CallbackQuery) -> bool:
        allowed = self.settings.allowed_telegram_user_ids
        if not allowed or callback.from_user.id in allowed:
            return True
        await callback.answer("Tài khoản của bạn chưa được cấp quyền.", show_alert=True)
        return False

    @staticmethod
    def _forget_callback_uuid(data: str, action: str) -> UUID | None:
        prefix = f"forget:{action}:"
        if not data.startswith(prefix):
            return None
        try:
            return UUID(data.removeprefix(prefix))
        except ValueError:
            return None

    async def handle_text(self, message: Message) -> None:
        if not await self._guard(message) or not message.from_user or not message.text:
            return
        try:
            await self._handle_text(message)
        except OperationalError:
            logger.exception("Ket noi database bi gian doan khi xu ly tin nhan van ban")
            await message.answer(
                "Kết nối bộ nhớ vừa bị gián đoạn nên tôi chưa thể xác nhận đã lưu, ông chủ ạ. "
                "Vui lòng thử lại sau ít phút."
            )

    async def _handle_text(self, message: Message) -> None:
        assert message.from_user is not None
        assert message.text is not None
        text = message.text.strip()
        urls = extract_urls(text)
        explicit_intent = self.ai.explicit_intent(text)
        if explicit_intent:
            intent = explicit_intent
        else:
            intent = "save" if urls else await self.ai.detect_intent(text)

        if intent == "search":
            await self.database.create_memory(
                MemoryCreate(
                    telegram_user_id=message.from_user.id,
                    telegram_chat_id=message.chat.id,
                    telegram_message_id=message.message_id,
                    kind="query",
                    text_content=text,
                    searchable=False,
                )
            )
            await self._answer_search(message, text)
            return

        memory = await self.database.create_memory(
            MemoryCreate(
                telegram_user_id=message.from_user.id,
                telegram_chat_id=message.chat.id,
                telegram_message_id=message.message_id,
                kind="text",
                text_content=text,
                metadata={"url_count": len(urls)},
            )
        )
        await self.memories.index_text(memory["id"], text)

        link_success = 0
        for url in urls:
            if await self._ingest_link(message, memory["id"], url):
                link_success += 1
        if urls:
            await message.answer(
                f"Đã lưu tin nhắn và đọc được {link_success}/{len(urls)} đường link."
            )
        else:
            await message.answer("Đã ghi nhớ thông tin này.")

    async def _ingest_link(self, message: Message, parent_id: Any, url: str) -> bool:
        assert message.from_user is not None
        try:
            content = await self.links.read(url)
            link_memory = await self.database.create_memory(
                MemoryCreate(
                    telegram_user_id=message.from_user.id,
                    telegram_chat_id=message.chat.id,
                    telegram_message_id=message.message_id,
                    parent_id=parent_id,
                    kind="link",
                    title=content.title,
                    text_content=content.text or url,
                    source_url=content.url,
                    mime_type=content.content_type,
                    metadata={"fetched": True},
                )
            )
            await self.memories.index_text(
                link_memory["id"],
                "\n".join(part for part in (content.title, content.text, content.url) if part),
            )
            return True
        except Exception as exc:
            logger.warning("Khong doc duoc URL %s: %s", url, exc)
            link_memory = await self.database.create_memory(
                MemoryCreate(
                    telegram_user_id=message.from_user.id,
                    telegram_chat_id=message.chat.id,
                    telegram_message_id=message.message_id,
                    parent_id=parent_id,
                    kind="link",
                    text_content=url,
                    source_url=url,
                    metadata={"fetched": False, "error": type(exc).__name__},
                )
            )
            await self.memories.index_text(link_memory["id"], url)
            return False

    async def handle_media(self, message: Message, bot: Bot) -> None:
        if not await self._guard(message) or not message.from_user:
            return
        media = self._media_info(message)
        if not media:
            await message.answer("Tôi chưa hỗ trợ loại nội dung này.")
            return
        if media.file_size and media.file_size > self.settings.max_download_bytes:
            await message.answer(
                f"File lớn hơn giới hạn {self.settings.max_download_mb} MB "
                "nên chưa thể lưu bản sao."
            )
            return

        status = await message.answer("Đã nhận. Tôi đang lưu và đọc nội dung…")
        path: Path | None = None
        try:
            path = await self.storage.download_telegram_file(
                bot, media.file_id, message.from_user.id, media.file_name
            )
            memory = await self.database.create_memory(
                MemoryCreate(
                    telegram_user_id=message.from_user.id,
                    telegram_chat_id=message.chat.id,
                    telegram_message_id=message.message_id,
                    kind=media.kind,
                    text_content=message.caption,
                    caption=message.caption,
                    mime_type=media.mime_type,
                    telegram_file_id=media.file_id,
                    telegram_file_unique_id=media.file_unique_id,
                    storage_path=str(path),
                    file_name=media.file_name,
                    file_size=media.file_size,
                )
            )
            extracted = await self.memories.index_file(
                memory["id"], path, media.mime_type, message.caption
            )
            detail = " và đã lập chỉ mục nội dung" if extracted else ""
            await status.edit_text(f"Đã ghi nhớ {media.file_name}{detail}.")
        except Exception:
            logger.exception("Loi khi luu media")
            await status.edit_text(
                "Có lỗi khi xử lý nội dung này. File chưa được ghi nhớ hoàn chỉnh; hãy thử lại."
            )

    async def _answer_search(self, message: Message, query: str) -> None:
        if not message.from_user:
            return
        status = await message.answer("Tôi đang tìm trong bộ nhớ…")
        results = await self.memories.search(
            message.from_user.id, query, self.settings.search_result_limit
        )
        answer = await self.ai.answer(query, results)
        await status.edit_text(answer)

        sent: set[str] = set()
        for result in results[:3]:
            if not result.telegram_file_id or result.telegram_file_id in sent:
                continue
            sent.add(result.telegram_file_id)
            await self._send_attachment(message, result)

    async def _send_attachment(self, message: Message, result: SearchResult) -> None:
        caption = f"Tìm thấy: {self._result_label(result)}"
        file_value: str | FSInputFile = result.telegram_file_id or ""
        try:
            await self._dispatch_attachment(message, result.kind, file_value, caption)
            return
        except Exception:
            logger.warning("Khong gui duoc bang Telegram file_id; thu ban sao local", exc_info=True)

        if result.storage_path and Path(result.storage_path).is_file():
            try:
                await self._dispatch_attachment(
                    message, result.kind, FSInputFile(result.storage_path), caption
                )
            except Exception:
                logger.exception("Khong gui duoc ban sao local %s", result.storage_path)

    @staticmethod
    async def _dispatch_attachment(
        message: Message, kind: str, file_value: str | FSInputFile, caption: str
    ) -> None:
        if kind == "photo":
            await message.answer_photo(file_value, caption=caption)
        elif kind == "video":
            await message.answer_video(file_value, caption=caption)
        elif kind == "audio":
            await message.answer_audio(file_value, caption=caption)
        elif kind == "voice":
            await message.answer_voice(file_value, caption=caption)
        elif kind == "animation":
            await message.answer_animation(file_value, caption=caption)
        elif kind == "video_note":
            await message.answer_video_note(file_value)
        elif kind == "sticker":
            await message.answer_sticker(file_value)
        else:
            await message.answer_document(file_value, caption=caption)

    @staticmethod
    def _result_label(result: SearchResult) -> str:
        return (
            result.file_name
            or result.title
            or result.source_url
            or result.snippet.replace("\n", " ")[:90]
            or result.kind
        )

    @staticmethod
    def _media_info(message: Message) -> MediaInfo | None:
        if message.photo:
            item = message.photo[-1]
            return MediaInfo(
                "photo",
                item.file_id,
                item.file_unique_id,
                f"photo_{message.message_id}.jpg",
                "image/jpeg",
                item.file_size,
            )
        candidates = (
            ("document", message.document, "document.bin"),
            ("audio", message.audio, "audio.mp3"),
            ("video", message.video, "video.mp4"),
            ("voice", message.voice, "voice.ogg"),
            ("animation", message.animation, "animation.mp4"),
            ("video_note", message.video_note, "video_note.mp4"),
            ("sticker", message.sticker, "sticker.webp"),
        )
        for kind, item, fallback_name in candidates:
            if not item:
                continue
            name = getattr(item, "file_name", None) or f"{message.message_id}_{fallback_name}"
            mime_type = getattr(item, "mime_type", None) or mimetypes.guess_type(name)[0]
            return MediaInfo(
                kind=kind,
                file_id=item.file_id,
                file_unique_id=item.file_unique_id,
                file_name=name,
                mime_type=mime_type,
                file_size=getattr(item, "file_size", None),
            )
        return None
