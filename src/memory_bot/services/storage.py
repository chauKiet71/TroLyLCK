from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

from aiogram import Bot


def safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^\w. -]+", "_", Path(name).name, flags=re.UNICODE).strip(" .")
    return cleaned[:160] or "file"


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    async def download_telegram_file(
        self,
        bot: Bot,
        file_id: str,
        telegram_user_id: int,
        original_name: str,
    ) -> Path:
        user_dir = (self.root / str(telegram_user_id)).resolve()
        user_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid4().hex}_{safe_filename(original_name)}"
        destination = (user_dir / filename).resolve()
        if self.root not in destination.parents:
            raise ValueError("Duong dan luu file khong an toan")
        telegram_file = await bot.get_file(file_id)
        if not telegram_file.file_path:
            raise ValueError("Telegram khong tra ve file_path")
        await bot.download_file(telegram_file.file_path, destination=destination)
        return destination

    def delete_file(self, stored_path: str | Path) -> bool:
        path = Path(stored_path).resolve()
        if self.root not in path.parents:
            raise ValueError("Duong dan xoa file khong an toan")
        if not path.is_file():
            return False
        path.unlink()
        return True
