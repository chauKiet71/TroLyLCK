from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(slots=True)
class MemoryCreate:
    telegram_user_id: int
    telegram_chat_id: int
    telegram_message_id: int
    kind: str
    parent_id: UUID | None = None
    title: str | None = None
    text_content: str | None = None
    caption: str | None = None
    source_url: str | None = None
    mime_type: str | None = None
    telegram_file_id: str | None = None
    telegram_file_unique_id: str | None = None
    storage_path: str | None = None
    file_name: str | None = None
    file_size: int | None = None
    searchable: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SearchResult:
    id: UUID
    kind: str
    title: str | None
    text_content: str | None
    caption: str | None
    source_url: str | None
    mime_type: str | None
    telegram_file_id: str | None
    storage_path: str | None
    file_name: str | None
    created_at: datetime
    snippet: str
    score: float
