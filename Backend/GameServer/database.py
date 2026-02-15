import os
from asyncpg import create_pool
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
REDIS_URL = os.getenv("REDIS_URL")
SESSION_EXPIRE_SECONDS = int(os.getenv("SESSION_EXPIRE_SECONDS", 3600))

# Pool для PostgreSQL
async def init_db():
    return await create_pool(DATABASE_URL, min_size=5, max_size=20)

# Redis клиент
from redis import from_url

async def init_redis():
    return from_url(
        REDIS_URL,
        decode_responses=True,
        encoding="utf-8"
    )