import json
import uuid
from datetime import datetime, timezone
from redis import Redis
from asyncpg import Pool
from gameClasses import User
from database import SESSION_EXPIRE_SECONDS
from models import CreateWorldRequest, World_info

class GameDBService:
    def __init__(self, db_pool: Pool, redis_client: Redis):
        self.db_pool = db_pool
        self.redis_client = redis_client

    async def createWorld(self, world_info: CreateWorldRequest, user: User) -> bool:
        """Создать мир в базе данных"""
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO worlds (world_name, world_seed, world_creator_id) VALUES ($1, $2, $3)",
                world_info.world_name, world_info.world_seed, user.id, 
            )
            return True
    
    # Сначала проверяем наличие мира в базе данных
    async def createServer(self, world_info: World_info, user User) -> bool:
        """Открыть сервер для текущего мира"""
        async with self.db_pool.acquire() as conn:
            await conn.