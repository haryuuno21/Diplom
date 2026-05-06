import json
from datetime import datetime, timezone
from typing import Optional

from asyncpg import Pool
from asyncpg.exceptions import UniqueViolationError
from redis.asyncio import Redis

from apiModels import GameServerResponse, SessionUser, WorldInfo, WorldListResponse
from database import SERVER_EXPIRE_SECONDS
from gameClasses import GameServer, World, WorldState


def _to_epoch(value: datetime) -> float:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def _coerce_json(value) -> dict:
    if value is None:
        return {}
    if isinstance(value, str):
        return json.loads(value)
    return value


class GameDBService:
    def __init__(self, db_pool: Pool, redis_client: Redis):
        self.db_pool = db_pool
        self.redis_client = redis_client

    async def create_user(self, username: str, password_hash: str) -> Optional[SessionUser]:
        async with self.db_pool.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    """
                    INSERT INTO users (username, password_hash)
                    VALUES ($1, $2)
                    RETURNING id, username
                    """,
                    username,
                    password_hash,
                )
            except UniqueViolationError:
                return None
        return SessionUser(id=row["id"], username=row["username"])

    async def get_user_credentials(self, username: str):
        async with self.db_pool.acquire() as conn:
            return await conn.fetchrow(
                """
                SELECT id, username, password_hash
                FROM users
                WHERE username = $1
                """,
                username,
            )

    async def update_user(
        self,
        user_id: int,
        *,
        username: str | None = None,
        password_hash: str | None = None,
    ) -> Optional[SessionUser]:
        if username is None and password_hash is None:
            raise ValueError("Nothing to update")

        fields = []
        values: list[object] = []
        index = 1

        if username is not None:
            fields.append(f"username = ${index}")
            values.append(username)
            index += 1

        if password_hash is not None:
            fields.append(f"password_hash = ${index}")
            values.append(password_hash)
            index += 1

        values.append(user_id)
        query = f"""
            UPDATE users
            SET {", ".join(fields)}
            WHERE id = ${index}
            RETURNING id, username
        """

        async with self.db_pool.acquire() as conn:
            try:
                row = await conn.fetchrow(query, *values)
            except UniqueViolationError as exc:
                raise ValueError("Username is already taken") from exc

        if not row:
            return None
        return SessionUser(id=row["id"], username=row["username"])

    async def create_world(
        self,
        world_name: str,
        world_seed: str,
        user: SessionUser,
        world_state: WorldState,
    ) -> WorldInfo:
        async with self.db_pool.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    """
                    INSERT INTO worlds (world_name, world_seed, world_creator_id, world_state)
                    VALUES ($1, $2, $3, $4::jsonb)
                    RETURNING world_id, world_name, world_seed, created_at, last_modified
                    """,
                    world_name,
                    world_seed,
                    user.id,
                    json.dumps(world_state.to_dict()),
                )
            except UniqueViolationError as exc:
                raise ValueError("World with this name already exists") from exc

        return WorldInfo(
            world_id=row["world_id"],
            world_name=row["world_name"],
            world_seed=row["world_seed"],
            world_created_at=_to_epoch(row["created_at"]),
            world_last_modified=_to_epoch(row["last_modified"]),
        )

    async def get_worlds(self, user: SessionUser) -> WorldListResponse:
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT world_id, world_name, world_seed, created_at, last_modified
                FROM worlds
                WHERE world_creator_id = $1
                ORDER BY created_at DESC
                """,
                user.id,
            )

        return WorldListResponse(
            worlds=[
                WorldInfo(
                    world_id=row["world_id"],
                    world_name=row["world_name"],
                    world_seed=row["world_seed"],
                    world_created_at=_to_epoch(row["created_at"]),
                    world_last_modified=_to_epoch(row["last_modified"]),
                )
                for row in rows
            ]
        )

    async def get_world_for_user(self, world_id: int, user_id: int) -> Optional[World]:
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT world_id, world_name, world_seed, world_creator_id, world_state,
                       created_at, last_modified
                FROM worlds
                WHERE world_id = $1 AND world_creator_id = $2
                """,
                world_id,
                user_id,
            )
        return self._row_to_world(row) if row else None

    async def load_world(self, world_id: int) -> Optional[World]:
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT world_id, world_name, world_seed, world_creator_id, world_state,
                       created_at, last_modified
                FROM worlds
                WHERE world_id = $1
                """,
                world_id,
            )
        return self._row_to_world(row) if row else None

    async def delete_world(self, world_id: int, user_id: int) -> bool:
        async with self.db_pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM worlds
                WHERE world_id = $1 AND world_creator_id = $2
                """,
                world_id,
                user_id,
            )
        return result.endswith("1")

    async def save_world_state(self, world_id: int, world_state: WorldState) -> None:
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE worlds
                SET world_state = $1::jsonb,
                    last_modified = NOW()
                WHERE world_id = $2
                """,
                json.dumps(world_state.to_dict()),
                world_id,
            )

    async def upsert_server_record(self, server: GameServer) -> None:
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO game_servers (
                    server_id, server_code, world_id, host_id, status, player_count, max_players
                )
                VALUES ($1::uuid, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (server_code) DO UPDATE
                SET status = EXCLUDED.status,
                    player_count = EXCLUDED.player_count,
                    max_players = EXCLUDED.max_players,
                    last_heartbeat = NOW()
                """,
                server.server_id,
                server.server_code,
                server.world_id,
                server.host_id,
                server.status,
                server.player_count,
                server.max_players,
            )

    async def update_server_status(
        self,
        server_code: str,
        status: str,
        player_count: int,
    ) -> None:
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE game_servers
                SET status = $1,
                    player_count = $2,
                    last_heartbeat = NOW()
                WHERE server_code = $3
                """,
                status,
                player_count,
                server_code,
            )

    async def store_active_server(self, server_info: GameServerResponse) -> None:
        await self.redis_client.setex(
            f"server:{server_info.server_code}",
            SERVER_EXPIRE_SECONDS,
            json.dumps(server_info.model_dump()),
        )

    async def get_active_server(self, server_code: str) -> Optional[GameServerResponse]:
        payload = await self.redis_client.get(f"server:{server_code}")
        if not payload:
            return None
        return GameServerResponse(**json.loads(payload))

    async def delete_active_server(self, server_code: str) -> None:
        await self.redis_client.delete(f"server:{server_code}")

    def _row_to_world(self, row) -> World:
        state_payload = _coerce_json(row["world_state"])
        return World(
            world_id=row["world_id"],
            world_name=row["world_name"],
            world_seed=row["world_seed"],
            world_creator_id=row["world_creator_id"],
            world_created_at=_to_epoch(row["created_at"]),
            last_modified=_to_epoch(row["last_modified"]),
            world_state=WorldState.from_dict(state_payload),
        )
