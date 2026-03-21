import json
import uuid
from datetime import datetime, timezone

from fastapi import Request
from gameClasses import WorldState
from redis import Redis
from asyncpg import Pool
from database import SESSION_EXPIRE_SECONDS
from apiModels import CreateWorldRequest, User, WorldInfo, WorldListResponse

class GameDBService:
    def __init__(self, db_pool: Pool, redis_client: Redis):
        self.db_pool = db_pool
        self.redis_client = redis_client

    async def createWorld(self, world_info: CreateWorldRequest, user: User, world_state: WorldState) -> int:
        """Создать мир в базе данных и вернуть его ID"""
        async with self.db_pool.acquire() as conn:
            world_id = await conn.fetchval(
                "INSERT INTO worlds (world_name, world_seed, world_creator_id) VALUES ($1, $2, $3) RETURNING world_id",
                world_info.world_name, 
                world_info.world_seed, 
                user.user_id
            )
            await conn.execute(
                "UPDATE worlds SET world_state = $1, last_modified = NOW() WHERE world_id = $2",
                world_state.toJson(),
                world_id
            )
        return world_id
    
    async def getWorlds(self, user: User) -> WorldListResponse:
        async with self.db_pool.acquire() as conn:
            records = await conn.fetch(
            """
                SELECT world_id, world_name, 
                      EXTRACT(EPOCH FROM created_at) AS world_created_at,
                      EXTRACT(EPOCH FROM last_modified) AS world_last_modified
                FROM worlds 
                WHERE world_creator_id = $1
                ORDER BY created_at DESC
            """,
            user.id
          )
        
            worlds = [
                WorldInfo(
                    world_id=record['world_id'],
                    world_name=record['world_name'],
                    world_created_at=record['world_created_at'],
                    world_last_modified=record['world_last_modified']
                )
             for record in records
            ]
        
        return WorldListResponse(worlds=worlds)
    
    def getUserFromSession(self, request: Request) -> User:
        session_id = request.cookies.get("session_id")
        if not session_id:
            return None

        user_data = self.redis_client.get(f"session:{session_id}")
        if not user_data:
            return None
    
        user_dict = json.loads(user_data)
        return User(id=user_dict["user_id"], user_name=user_dict["user_name"])