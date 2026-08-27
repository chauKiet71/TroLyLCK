from __future__ import annotations

import logging

import psycopg

logger = logging.getLogger(__name__)


# ADD COLUMN IF NOT EXISTS is intentional: startup is also the lightweight migration runner.
SCHEMA_STATEMENTS = (
    "CREATE EXTENSION IF NOT EXISTS vector",
    """
    CREATE TABLE IF NOT EXISTS memories (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        telegram_user_id BIGINT NOT NULL,
        telegram_chat_id BIGINT NOT NULL,
        telegram_message_id BIGINT NOT NULL,
        parent_id UUID REFERENCES memories(id) ON DELETE SET NULL,
        kind TEXT NOT NULL,
        title TEXT,
        text_content TEXT,
        caption TEXT,
        source_url TEXT,
        mime_type TEXT,
        telegram_file_id TEXT,
        telegram_file_unique_id TEXT,
        storage_path TEXT,
        file_name TEXT,
        file_size BIGINT,
        searchable BOOLEAN NOT NULL DEFAULT TRUE,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "ALTER TABLE memories ADD COLUMN IF NOT EXISTS telegram_user_id BIGINT",
    "ALTER TABLE memories ADD COLUMN IF NOT EXISTS telegram_chat_id BIGINT",
    "ALTER TABLE memories ADD COLUMN IF NOT EXISTS telegram_message_id BIGINT",
    "ALTER TABLE memories ADD COLUMN IF NOT EXISTS kind TEXT",
    """
    ALTER TABLE memories ADD COLUMN IF NOT EXISTS parent_id UUID
    REFERENCES memories(id) ON DELETE SET NULL
    """,
    "ALTER TABLE memories ADD COLUMN IF NOT EXISTS title TEXT",
    "ALTER TABLE memories ADD COLUMN IF NOT EXISTS text_content TEXT",
    "ALTER TABLE memories ADD COLUMN IF NOT EXISTS caption TEXT",
    "ALTER TABLE memories ADD COLUMN IF NOT EXISTS source_url TEXT",
    "ALTER TABLE memories ADD COLUMN IF NOT EXISTS mime_type TEXT",
    "ALTER TABLE memories ADD COLUMN IF NOT EXISTS telegram_file_id TEXT",
    "ALTER TABLE memories ADD COLUMN IF NOT EXISTS telegram_file_unique_id TEXT",
    "ALTER TABLE memories ADD COLUMN IF NOT EXISTS storage_path TEXT",
    "ALTER TABLE memories ADD COLUMN IF NOT EXISTS file_name TEXT",
    "ALTER TABLE memories ADD COLUMN IF NOT EXISTS file_size BIGINT",
    "ALTER TABLE memories ADD COLUMN IF NOT EXISTS searchable BOOLEAN NOT NULL DEFAULT TRUE",
    "ALTER TABLE memories ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE memories ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now()",
    "ALTER TABLE memories ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()",
    """
    CREATE TABLE IF NOT EXISTS memory_chunks (
        id BIGSERIAL PRIMARY KEY,
        memory_id UUID NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
        chunk_index INTEGER NOT NULL,
        content TEXT NOT NULL,
        embedding VECTOR(1536),
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE(memory_id, chunk_index)
    )
    """,
    """
    ALTER TABLE memory_chunks ADD COLUMN IF NOT EXISTS memory_id UUID
    REFERENCES memories(id) ON DELETE CASCADE
    """,
    "ALTER TABLE memory_chunks ADD COLUMN IF NOT EXISTS chunk_index INTEGER",
    "ALTER TABLE memory_chunks ADD COLUMN IF NOT EXISTS content TEXT",
    "ALTER TABLE memory_chunks ADD COLUMN IF NOT EXISTS embedding VECTOR(1536)",
    """
    ALTER TABLE memory_chunks ADD COLUMN IF NOT EXISTS metadata
    JSONB NOT NULL DEFAULT '{}'::jsonb
    """,
    """
    ALTER TABLE memory_chunks ADD COLUMN IF NOT EXISTS created_at
    TIMESTAMPTZ NOT NULL DEFAULT now()
    """,
    """
    CREATE INDEX IF NOT EXISTS memories_user_created_idx
    ON memories (telegram_user_id, created_at DESC)
    """,
    "CREATE INDEX IF NOT EXISTS memories_parent_idx ON memories (parent_id)",
    """
    CREATE INDEX IF NOT EXISTS memories_file_unique_idx
    ON memories (telegram_user_id, telegram_file_unique_id)
    """,
    "CREATE INDEX IF NOT EXISTS memory_chunks_memory_idx ON memory_chunks (memory_id)",
    """
    CREATE INDEX IF NOT EXISTS memory_chunks_embedding_hnsw
    ON memory_chunks USING hnsw (embedding vector_cosine_ops)
    """,
)


async def ensure_schema(database_url: str) -> None:
    """Create/upgrade every required extension, table, column and index."""
    logger.info("Dang kiem tra schema Neon PostgreSQL")
    connection = await psycopg.AsyncConnection.connect(database_url, autocommit=True)
    async with connection:
        for statement in SCHEMA_STATEMENTS:
            await connection.execute(statement)
    logger.info("Schema da san sang")
