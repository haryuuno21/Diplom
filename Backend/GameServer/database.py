import os

from asyncpg import Pool, create_pool
from dotenv import load_dotenv
from redis.asyncio import Redis, from_url

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
REDIS_URL = os.getenv("REDIS_URL")
SESSION_EXPIRE_SECONDS = int(os.getenv("SESSION_EXPIRE_SECONDS", 3600))
SERVER_EXPIRE_SECONDS = int(os.getenv("SERVER_EXPIRE_SECONDS", 86400))

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS worlds (
    world_id SERIAL PRIMARY KEY,
    world_name VARCHAR(50) NOT NULL,
    world_seed VARCHAR(100) NOT NULL,
    world_creator_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    world_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_modified TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (world_creator_id, world_name)
);

CREATE INDEX IF NOT EXISTS idx_worlds_creator ON worlds(world_creator_id);

CREATE TABLE IF NOT EXISTS game_servers (
    server_id UUID PRIMARY KEY,
    server_code VARCHAR(6) NOT NULL UNIQUE,
    world_id INTEGER NOT NULL REFERENCES worlds(world_id) ON DELETE CASCADE,
    host_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status VARCHAR(16) NOT NULL,
    player_count INTEGER NOT NULL DEFAULT 0,
    max_players INTEGER NOT NULL DEFAULT 4,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_heartbeat TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


async def init_db() -> Pool:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured")
    return await create_pool(DATABASE_URL, min_size=1, max_size=10)


async def initialize_schema(pool: Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)


async def init_redis() -> Redis:
    if not REDIS_URL:
        raise RuntimeError("REDIS_URL is not configured")
    return from_url(REDIS_URL, decode_responses=True, encoding="utf-8")

