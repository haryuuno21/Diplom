import json
import uuid
from datetime import datetime, timedelta
from redis import Redis
from asyncpg import Pool
from database import SESSION_EXPIRE_SECONDS
from models import User

class AuthService:
    def __init__(self, db_pool: Pool, redis_client: Redis):
        self.db_pool = db_pool
        self.redis_client = redis_client
    
    async def create_user(self, username: str, password: str) -> bool:
        """Создать нового пользователя"""
        # Проверка существования пользователя
        async with self.db_pool.acquire() as conn:
            existing_user = await conn.fetchrow(
                "SELECT id FROM users WHERE username = $1",
                username
            )
            if existing_user:
                return False
            
            # Создание пользователя
            hashed_password = User.hash_password(password)
            await conn.execute(
                "INSERT INTO users (username, hashed_password) VALUES ($1, $2)",
                username, hashed_password
            )
            return True
    
    async def authenticate_user(self, username: str, password: str):
        """Аутентифицировать пользователя"""
        async with self.db_pool.acquire() as conn:
            user_row = await conn.fetchrow(
                "SELECT id, username, hashed_password FROM users WHERE username = $1",
                username
            )
            if not user_row:
                return None
            
            user = User(user_row['id'], user_row['username'], user_row['hashed_password'])
            if user.verify_password(password):
                return user
            return None
    
    async def create_session(self, user_id: int, username: str) -> str:
        """Создать сессию и вернуть session_id"""
        session_id = str(uuid.uuid4())
        session_data = {
            "user_id": user_id,
            "username": username,
            "created_at": datetime.utcnow().isoformat()
        }
        
        await self.redis_client.setex(
            f"session:{session_id}",
            SESSION_EXPIRE_SECONDS,
            json.dumps(session_data)
        )
        return session_id
    
    async def get_session(self, session_id: str):
        """Получить данные сессии"""
        session_data = await self.redis_client.get(f"session:{session_id}")
        if session_data:
            return json.loads(session_data)
        return None
    
    async def delete_session(self, session_id: str):
        """Удалить сессию"""
        await self.redis_client.delete(f"session:{session_id}")