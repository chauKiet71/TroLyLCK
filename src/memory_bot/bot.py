from __future__ import annotations

import logging
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import FSInputFile, Message

from memory_bot.config import Settings
from memory_bot.database import Database
from memory_bot.services.ai import AIService
from memory_bot.services.links import LinkReader, extract_urls
from memory_bot.services.memory import MemoryService
from memory_bot.services.storage import LocalStorage
from memory_bot.types import MemoryCreate, SearchResult

logger = logging.getLogger(__name__)


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

    async def handle_text(self, message: Message) -> None:
        if not await self._guard(message) or not message.from_user or not message.text:
            return
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
