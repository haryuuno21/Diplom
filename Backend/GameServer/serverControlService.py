import asyncio
import random

from apiModels import GameServerResponse, SessionUser
from database import SERVER_IDLE_SHUTDOWN_SECONDS
from gameClasses import GameServer
from gameDBService import GameDBService
from gameServerManager import GameServerManager


class ServerControlService:
    def __init__(
        self,
        game_db_service: GameDBService,
        *,
        idle_shutdown_seconds: int = SERVER_IDLE_SHUTDOWN_SECONDS,
    ):
        self.managers: dict[str, GameServerManager] = {}
        self._idle_shutdown_tasks: dict[str, asyncio.Task] = {}
        self.game_db_service = game_db_service
        self.idle_shutdown_seconds = max(0, int(idle_shutdown_seconds))

    async def create_server(self, world_id: int, user: SessionUser) -> GameServerResponse:
        existing = self._find_existing_server(world_id, user.id)
        if existing:
            await self._cancel_idle_shutdown(existing.server.server_code)
            return await self._store_and_build_response(existing)

        world = await self.game_db_service.get_world_for_user(world_id, user.id)
        if not world:
            raise ValueError("World not found or access denied")

        server = GameServer(
            world=world,
            host_id=user.id,
            max_players=4,
            server_code=self.generate_server_code(),
        )
        manager = GameServerManager(
            server,
            manual_action_tick_cost=1,
            script_action_tick_cost=4,
            tick_interval_seconds=0.05,
        )
        manager.load_chat_history(await self.game_db_service.get_chat_history(world.world_id))
        manager.start()
        self.managers[server.server_code] = manager

        return await self._store_and_build_response(manager)

    async def get_server_info(self, server_code: str) -> GameServerResponse | None:
        manager = self.managers.get(server_code)
        if manager:
            return await self._store_and_build_response(manager)
        return await self.game_db_service.get_active_server(server_code)

    async def add_player(self, server_code: str, sid: str, user: SessionUser) -> dict:
        manager = self._require_manager(server_code)
        await self._cancel_idle_shutdown(server_code)
        restored_state = await self.game_db_service.get_player_state(manager.server.world.world_id, user.id)
        await manager.add_player(sid, user, restored_state=restored_state)
        await self._persist_player_snapshot(manager, sid)
        await self._store_and_build_response(manager)
        return manager.build_world_payload(sid)

    async def remove_player(self, server_code: str, sid: str) -> bool:
        manager = self.managers.get(server_code)
        if not manager:
            return False

        should_stop, snapshot = await manager.remove_player(sid)
        if snapshot is not None:
            await self._persist_snapshot(manager, snapshot, persist_to_postgres=True)
        if should_stop:
            await self._schedule_idle_shutdown(server_code)
            await self._store_and_build_response(manager)
            return True

        await self._store_and_build_response(manager)
        return False

    async def move_player(self, server_code: str, sid: str, direction: str) -> tuple[dict, dict]:
        manager = self._require_manager(server_code)
        state, public_state = await manager.move_player(sid, direction)
        await self._persist_player_snapshot(manager, sid)
        await self._store_and_build_response(manager)
        return state, public_state

    async def turn_player(self, server_code: str, sid: str, direction: str) -> tuple[dict, dict]:
        manager = self._require_manager(server_code)
        state, public_state = await manager.turn_player(sid, direction)
        await self._persist_player_snapshot(manager, sid)
        await self._store_and_build_response(manager)
        return state, public_state

    async def heal_player(self, server_code: str, sid: str) -> tuple[dict, dict]:
        manager = self._require_manager(server_code)
        state, public_state = await manager.heal_player(sid)
        await self._persist_player_snapshot(manager, sid)
        await self._store_and_build_response(manager)
        return state, public_state

    async def restart_player(self, server_code: str, sid: str) -> tuple[dict, dict]:
        manager = self._require_manager(server_code)
        state, public_state = await manager.restart_player(sid)
        await self._persist_player_snapshot(manager, sid)
        await self._store_and_build_response(manager)
        return state, public_state

    async def execute_script(
        self,
        server_code: str,
        sid: str,
        script_text: str,
        *,
        on_state_change=None,
    ) -> tuple[dict, dict, dict]:
        manager = self._require_manager(server_code)
        state, public_state, script_result = await manager.execute_script(
            sid,
            script_text,
            on_state_change=on_state_change,
        )
        await self._persist_player_snapshot(manager, sid)
        await self._store_and_build_response(manager)
        return state, public_state, script_result

    async def save_player_script_state(self, server_code: str, sid: str, payload: dict | str) -> dict | None:
        manager = self._require_manager(server_code)
        draft = manager.set_player_script_draft(sid, payload)
        await self._persist_player_snapshot(manager, sid, persist_to_postgres=True)
        return draft

    async def stop_script(self, server_code: str, sid: str) -> tuple[dict, dict] | None:
        manager = self._require_manager(server_code)
        result = await manager.stop_script(sid)
        if result is not None:
            await self._persist_player_snapshot(manager, sid)
            await self._store_and_build_response(manager)
        return result

    async def update_player_state(self, server_code: str, sid: str, payload: dict) -> dict | None:
        manager = self.managers.get(server_code)
        if not manager:
            return None

        updated = await manager.update_player_state(
            sid,
            position=payload.get("position"),
            rotation=payload.get("rotation"),
            health=payload.get("health"),
        )
        if updated is not None:
            await self._persist_player_snapshot(manager, sid)
            await self._store_and_build_response(manager)
        return updated

    def build_player_state(self, server_code: str, sid: str) -> dict:
        manager = self._require_manager(server_code)
        return manager.build_state_payload(sid)

    def build_tick_payload(self, server_code: str, sid: str) -> dict:
        manager = self._require_manager(server_code)
        return manager.build_tick_payload(sid)

    def list_player_ids(self, server_code: str) -> list[str]:
        manager = self._require_manager(server_code)
        return manager.list_player_ids()

    def build_world_payload(self, server_code: str, sid: str | None = None) -> dict:
        manager = self._require_manager(server_code)
        return manager.build_world_payload(sid)

    async def add_chat_message(self, server_code: str, sid: str, payload: dict | str) -> dict:
        manager = self._require_manager(server_code)
        message = await manager.add_chat_message(sid, payload)
        await self.game_db_service.store_chat_message(
            manager.server.world_id,
            manager.server.server_code,
            message,
        )
        return message

    async def stop_world_servers(self, world_id: int) -> None:
        for server_code, manager in list(self.managers.items()):
            if manager.server.world_id == world_id:
                await self.stop_server(server_code)

    async def stop_server(self, server_code: str) -> None:
        await self._cancel_idle_shutdown(server_code)
        await self._finalize_server_stop(server_code)

    async def _finalize_server_stop(self, server_code: str) -> None:
        manager = self.managers.pop(server_code, None)
        if not manager:
            await self.game_db_service.delete_active_server(server_code)
            return

        await self._persist_all_player_snapshots(manager, persist_to_postgres=True)
        await self.game_db_service.save_world_state(
            manager.server.world_id,
            manager.server.world.world_state,
        )
        manager.server.status = "stopped"
        await self.game_db_service.update_server_status(server_code, "stopped", 0)
        await self.game_db_service.delete_active_server(server_code)
        await manager.stop()

    async def persist_server_state(self, server_code: str) -> None:
        manager = self.managers.get(server_code)
        if not manager:
            return
        await self._persist_all_player_snapshots(manager, persist_to_postgres=True)
        await self.game_db_service.save_world_state(
            manager.server.world_id,
            manager.server.world.world_state,
        )

    async def shutdown(self) -> None:
        for server_code in list(self._idle_shutdown_tasks.keys()):
            await self._cancel_idle_shutdown(server_code)
        for server_code in list(self.managers.keys()):
            await self.stop_server(server_code)

    def generate_server_code(self) -> str:
        chars = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
        for _ in range(1000):
            code = "".join(random.choices(chars, k=6))
            if code not in self.managers:
                return code
        raise RuntimeError("Could not generate a unique server code")

    def _find_existing_server(self, world_id: int, host_id: int) -> GameServerManager | None:
        for manager in self.managers.values():
            if manager.server.world_id == world_id and manager.server.host_id == host_id:
                return manager
        return None

    def _require_manager(self, server_code: str) -> GameServerManager:
        manager = self.managers.get(server_code)
        if not manager:
            raise ValueError("Server is not active")
        return manager

    async def _persist_player_snapshot(
        self,
        manager: GameServerManager,
        sid: str,
        *,
        persist_to_postgres: bool = False,
    ) -> None:
        if sid not in manager.server.players:
            return
        snapshot = manager.build_player_snapshot(sid)
        await self._persist_snapshot(
            manager,
            snapshot,
            persist_to_postgres=persist_to_postgres,
        )

    async def _persist_all_player_snapshots(
        self,
        manager: GameServerManager,
        *,
        persist_to_postgres: bool = False,
    ) -> None:
        for sid in list(manager.list_player_ids()):
            await self._persist_player_snapshot(
                manager,
                sid,
                persist_to_postgres=persist_to_postgres,
            )

    async def _persist_snapshot(
        self,
        manager: GameServerManager,
        snapshot: dict,
        *,
        persist_to_postgres: bool = False,
    ) -> None:
        await self.game_db_service.store_player_state(
            manager.server.world.world_id,
            int(snapshot["user_id"]),
            snapshot,
            persist_to_postgres=persist_to_postgres,
        )

    async def _schedule_idle_shutdown(self, server_code: str) -> None:
        await self._cancel_idle_shutdown(server_code)

        async def _worker() -> None:
            try:
                await asyncio.sleep(self.idle_shutdown_seconds)
                manager = self.managers.get(server_code)
                if not manager or manager.server.players:
                    return
                await self._finalize_server_stop(server_code)
            except asyncio.CancelledError:
                return
            finally:
                self._idle_shutdown_tasks.pop(server_code, None)

        self._idle_shutdown_tasks[server_code] = asyncio.create_task(_worker())

    async def _cancel_idle_shutdown(self, server_code: str) -> None:
        task = self._idle_shutdown_tasks.pop(server_code, None)
        if not task:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _store_and_build_response(self, manager: GameServerManager) -> GameServerResponse:
        response = GameServerResponse(
            server_id=manager.server.server_id,
            server_code=manager.server.server_code,
            world_id=manager.server.world_id,
            world_name=manager.server.world_name,
            host_id=manager.server.host_id,
            status=manager.server.status,
            created_at=manager.server.created_at,
            player_count=manager.server.player_count,
            max_players=manager.server.max_players,
        )
        await self.game_db_service.upsert_server_record(manager.server)
        await self.game_db_service.store_active_server(response)
        return response
