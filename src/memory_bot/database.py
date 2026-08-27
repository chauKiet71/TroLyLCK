from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from memory_bot.services.search_text import meaningful_search_terms
from memory_bot.types import MemoryCreate, SearchResult


def _vector_literal(values: Sequence[float]) -> str:
    return "[" + ",".join(f"{value:.9g}" for value in values) + "]"


class Database:
    def __init__(self, database_url: str) -> None:
        self.pool = AsyncConnectionPool(
            conninfo=database_url,
            min_size=1,
            max_size=6,
            open=False,
            kwargs={"row_factory": dict_row},
        )

    async def open(self) -> None:
        await self.pool.open()
        await self.pool.wait()

    async def close(self) -> None:
        await self.pool.close()

    async def create_memory(self, memory: MemoryCreate) -> dict[str, Any]:
        query = """
            INSERT INTO memories (
                telegram_user_id, telegram_chat_id, telegram_message_id, parent_id,
                kind, title, text_content, caption, source_url, mime_type,
                telegram_file_id, telegram_file_unique_id, storage_path, file_name,
                file_size, searchable, metadata
            ) VALUES (
                %(telegram_user_id)s, %(telegram_chat_id)s, %(telegram_message_id)s,
                %(parent_id)s, %(kind)s, %(title)s, %(text_content)s, %(caption)s,
                %(source_url)s, %(mime_type)s, %(telegram_file_id)s,
                %(telegram_file_unique_id)s, %(storage_path)s, %(file_name)s,
                %(file_size)s, %(searchable)s, %(metadata)s
            ) RETURNING *
        """
        params = {
            "telegram_user_id": memory.telegram_user_id,
            "telegram_chat_id": memory.telegram_chat_id,
            "telegram_message_id": memory.telegram_message_id,
            "parent_id": memory.parent_id,
            "kind": memory.kind,
            "title": memory.title,
            "text_content": memory.text_content,
            "caption": memory.caption,
            "source_url": memory.source_url,
            "mime_type": memory.mime_type,
            "telegram_file_id": memory.telegram_file_id,
            "telegram_file_unique_id": memory.telegram_file_unique_id,
            "storage_path": memory.storage_path,
            "file_name": memory.file_name,
            "file_size": memory.file_size,
            "searchable": memory.searchable,
            "metadata": Jsonb(memory.metadata),
        }
        async with self.pool.connection() as connection:
            cursor = await connection.execute(query, params)
            row = await cursor.fetchone()
        assert row is not None
        return row

    async def update_memory_content(
        self,
        memory_id: UUID,
        *,
        text_content: str | None = None,
        title: str | None = None,
        metadata_patch: dict[str, Any] | None = None,
    ) -> None:
        await self._execute(
            """
            UPDATE memories
            SET text_content = COALESCE(%s, text_content),
                title = COALESCE(%s, title),
                metadata = metadata || %s,
                updated_at = now()
            WHERE id = %s
            """,
            (text_content, title, Jsonb(metadata_patch or {}), memory_id),
        )

    async def replace_chunks(
        self,
        memory_id: UUID,
        chunks: Sequence[str],
        embeddings: Sequence[Sequence[float] | None],
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("So chunk va embedding khong khop")
        async with self.pool.connection() as connection:
            async with connection.transaction():
                await connection.execute(
                    "DELETE FROM memory_chunks WHERE memory_id = %s", (memory_id,)
                )
                for index, (content, embedding) in enumerate(zip(chunks, embeddings, strict=True)):
                    vector = _vector_literal(embedding) if embedding else None
                    await connection.execute(
                        """
                        INSERT INTO memory_chunks (memory_id, chunk_index, content, embedding)
                        VALUES (%s, %s, %s, %s::vector)
                        """,
                        (memory_id, index, content, vector),
                    )

    async def semantic_search(
        self,
        telegram_user_id: int,
        embedding: Sequence[float],
        limit: int,
    ) -> list[SearchResult]:
        query = """
            SELECT m.*, c.content AS snippet,
                   1 - (c.embedding <=> %s::vector) AS score
            FROM memory_chunks c
            JOIN memories m ON m.id = c.memory_id
            WHERE m.telegram_user_id = %s
              AND m.searchable = TRUE
              AND c.embedding IS NOT NULL
            ORDER BY c.embedding <=> %s::vector
            LIMIT %s
        """
        vector = _vector_literal(embedding)
        rows = await self._fetchall(query, (vector, telegram_user_id, vector, limit * 3))
        return self._deduplicate_results(rows, limit)

    async def lexical_search(
        self,
        telegram_user_id: int,
        search_text: str,
        limit: int,
    ) -> list[SearchResult]:
        terms = meaningful_search_terms(search_text)
        if not terms:
            return []
        query = """
            WITH terms AS (
                SELECT unnest(%s::text[]) AS term
            ), ranked AS (
                SELECT m.*,
                       COALESCE(match_chunk.content, m.text_content, m.caption, m.title, '')
                           AS snippet,
                       GREATEST((
                           SELECT count(*)
                           FROM terms t
                           WHERE concat_ws(' ', m.title, m.text_content, m.caption,
                                           m.file_name, m.source_url)
                               ILIKE '%%' || t.term || '%%'
                       ), COALESCE(match_chunk.hits, 0)) AS hits
                FROM memories m
                LEFT JOIN LATERAL (
                    SELECT c.content, count(*) AS hits
                    FROM memory_chunks c
                    CROSS JOIN terms t
                    WHERE c.memory_id = m.id
                      AND c.content ILIKE '%%' || t.term || '%%'
                    GROUP BY c.id, c.content
                    ORDER BY hits DESC
                    LIMIT 1
                ) match_chunk ON TRUE
                WHERE m.telegram_user_id = %s
                  AND m.searchable = TRUE
            )
            SELECT ranked.*,
                   hits::double precision / %s AS score
            FROM ranked
            WHERE hits >= GREATEST(1, CEIL(%s * 0.50))
            ORDER BY hits DESC, created_at DESC
            LIMIT %s
        """
        rows = await self._fetchall(
            query,
            (terms, telegram_user_id, len(terms), len(terms), limit),
        )
        return self._deduplicate_results(rows, limit)

    async def recent(self, telegram_user_id: int, limit: int = 10) -> list[SearchResult]:
        rows = await self._fetchall(
            """
            SELECT m.*, COALESCE(m.text_content, m.caption, m.title, '') AS snippet, 0.0 AS score
            FROM memories m
            WHERE telegram_user_id = %s AND searchable = TRUE
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (telegram_user_id, limit),
        )
        return [self._to_result(row) for row in rows]

    async def get_memory(
        self, telegram_user_id: int, memory_id: UUID
    ) -> SearchResult | None:
        rows = await self._fetchall(
            """
            SELECT m.*, COALESCE(m.text_content, m.caption, m.title, '') AS snippet,
                   0.0 AS score
            FROM memories m
            WHERE telegram_user_id = %s AND id = %s AND searchable = TRUE
            """,
            (telegram_user_id, memory_id),
        )
        return self._to_result(rows[0]) if rows else None

    async def delete_memory_tree(self, telegram_user_id: int, memory_id: UUID) -> list[str]:
        rows = await self._fetchall(
            """
            WITH RECURSIVE targets AS (
                SELECT id
                FROM memories
                WHERE id = %s AND telegram_user_id = %s
                UNION ALL
                SELECT child.id
                FROM memories child
                JOIN targets parent ON child.parent_id = parent.id
                WHERE child.telegram_user_id = %s
            ), deleted AS (
                DELETE FROM memories memory
                USING targets
                WHERE memory.id = targets.id
                RETURNING memory.storage_path
            )
            SELECT storage_path FROM deleted WHERE storage_path IS NOT NULL
            """,
            (memory_id, telegram_user_id, telegram_user_id),
        )
        return [row["storage_path"] for row in rows]

    async def _execute(self, query: str, params: Sequence[Any]) -> None:
        async with self.pool.connection() as connection:
            await connection.execute(query, params)

    async def _fetchall(self, query: str, params: Sequence[Any]) -> list[dict[str, Any]]:
        async with self.pool.connection() as connection:
            cursor = await connection.execute(query, params)
            return list(await cursor.fetchall())

    @classmethod
    def _deduplicate_results(cls, rows: Sequence[dict[str, Any]], limit: int) -> list[SearchResult]:
        found: list[SearchResult] = []
        seen: set[UUID] = set()
        for row in rows:
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            found.append(cls._to_result(row))
            if len(found) == limit:
                break
        return found

    @staticmethod
    def _to_result(row: dict[str, Any]) -> SearchResult:
        return SearchResult(
            id=row["id"],
            kind=row["kind"],
            title=row.get("title"),
            text_content=row.get("text_content"),
            caption=row.get("caption"),
            source_url=row.get("source_url"),
            mime_type=row.get("mime_type"),
            telegram_file_id=row.get("telegram_file_id"),
            storage_path=row.get("storage_path"),
            file_name=row.get("file_name"),
            created_at=row["created_at"],
            snippet=(row.get("snippet") or "")[:3000],
            score=float(row.get("score") or 0),
        )
