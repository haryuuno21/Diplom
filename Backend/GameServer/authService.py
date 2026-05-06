import base64
import hashlib
import json
import secrets
from http.cookies import SimpleCookie
from typing import Optional

from asyncpg import Pool
from fastapi import Request, Response
from redis.asyncio import Redis

from apiModels import SessionUser
from database import SESSION_EXPIRE_SECONDS
from gameDBService import GameDBService


class AuthService:
    def __init__(self, db_pool: Pool, redis_client: Redis):
        self.db_pool = db_pool
        self.redis_client = redis_client
        self.game_db_service = GameDBService(db_pool, redis_client)

    async def register_user(self, username: str, password: str) -> Optional[SessionUser]:
        password_hash = self.hash_password(password)
        return await self.game_db_service.create_user(username, password_hash)

    async def authenticate_user(self, username: str, password: str) -> Optional[SessionUser]:
        row = await self.game_db_service.get_user_credentials(username)
        if not row:
            return None
        if not self.verify_password(password, row["password_hash"]):
            return None
        return SessionUser(id=row["id"], username=row["username"])

    async def update_user(
        self,
        user: SessionUser,
        *,
        username: str | None = None,
        password: str | None = None,
    ) -> Optional[SessionUser]:
        password_hash = self.hash_password(password) if password else None
        return await self.game_db_service.update_user(
            user.id,
            username=username,
            password_hash=password_hash,
        )

    async def create_session(self, user: SessionUser) -> str:
        session_id = secrets.token_urlsafe(32)
        payload = json.dumps(user.model_dump())
        await self.redis_client.setex(
            f"session:{session_id}",
            SESSION_EXPIRE_SECONDS,
            payload,
        )
        return session_id

    async def get_session(self, session_id: str) -> Optional[SessionUser]:
        payload = await self.redis_client.get(f"session:{session_id}")
        if not payload:
            return None
        return SessionUser(**json.loads(payload))

    async def delete_session(self, session_id: str) -> None:
        await self.redis_client.delete(f"session:{session_id}")

    async def get_current_user(self, request: Request) -> Optional[SessionUser]:
        session_id = request.cookies.get("session_id")
        if not session_id:
            return None
        return await self.get_session(session_id)

    def set_session_cookie(self, response: Response, session_id: str) -> None:
        response.set_cookie(
            key="session_id",
            value=session_id,
            httponly=True,
            secure=False,
            samesite="lax",
            max_age=SESSION_EXPIRE_SECONDS,
        )

    def clear_session_cookie(self, response: Response) -> None:
        response.delete_cookie("session_id")

    @staticmethod
    def extract_session_id_from_cookie_header(cookie_header: str | None) -> Optional[str]:
        if not cookie_header:
            return None
        cookie = SimpleCookie()
        cookie.load(cookie_header)
        session = cookie.get("session_id")
        return session.value if session else None

    @staticmethod
    def hash_password(password: str) -> str:
        salt = secrets.token_bytes(16)
        digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
        return base64.b64encode(salt + digest).decode("ascii")

    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        raw = base64.b64decode(password_hash.encode("ascii"))
        salt, expected = raw[:16], raw[16:]
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
        return secrets.compare_digest(actual, expected)
