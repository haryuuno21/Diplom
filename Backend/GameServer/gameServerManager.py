from __future__ import annotations

import asyncio
from dataclasses import dataclass
import time
from typing import Awaitable, Callable

from apiModels import SessionUser
from basicRuntime import BasicRuntimeError, BasicScriptRuntime, BasicScriptCancelledError
from gameClasses import (
    DIRECTION_TO_RUSSIAN,
    MODE_TO_RUSSIAN,
    MAX_PLAYER_HEALTH,
    GameServer,
    PlayerState,
)
from worldRuntime import WorldRuntime


StateChangeCallback = Callable[[dict, dict], Awaitable[None]]


@dataclass
class ScheduledPlayerAction:
    sid: str
    execute_at_tick: int
    future: asyncio.Future
    operation: Callable[[PlayerState], object | None]


class GameServerManager:
    def __init__(
        self,
        server: GameServer,
        *,
        manual_action_tick_cost: int = 1,
        script_action_tick_cost: int = 0,
        tick_interval_seconds: float = 0.05,
    ):
        self.server = server
        self.runtime = WorldRuntime(server.world.world_state)
        self.script_runtime = BasicScriptRuntime()
        self.chat_history: list[dict] = []
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._running = False
        self.manual_action_tick_cost = max(1, int(manual_action_tick_cost))
        self.script_action_tick_cost = max(0, int(script_action_tick_cost))
        self.tick_interval_seconds = float(tick_interval_seconds)
        self._active_script_players: set[str] = set()
        self._pending_actions: list[ScheduledPlayerAction] = []
        self._script_cancel_events: dict[str, asyncio.Event] = {}

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._game_loop())

    async def _game_loop(self) -> None:
        try:
            while self._running:
                completed_actions: list[tuple[asyncio.Future, tuple | None, Exception | None]] = []
                async with self._lock:
                    self.server.world.world_state.tick += 1

                    ready_actions = [
                        action
                        for action in self._pending_actions
                        if action.execute_at_tick <= self.server.world.world_state.tick
                    ]
                    self._pending_actions = [
                        action
                        for action in self._pending_actions
                        if action.execute_at_tick > self.server.world.world_state.tick
                    ]

                    for action in ready_actions:
                        if action.future.cancelled():
                            continue

                        player = self.server.players.get(action.sid)
                        if not player:
                            completed_actions.append(
                                (
                                    action.future,
                                    None,
                                    BasicRuntimeError("Script interrupted because player disconnected"),
                                )
                            )
                            continue

                        try:
                            operation_result = action.operation(player)
                            completed_actions.append(
                                (
                                    action.future,
                                    (
                                        self._build_state_payload(action.sid),
                                        player.to_public_dict(action.sid),
                                        operation_result,
                                    ),
                                    None,
                                )
                            )
                        except Exception as exc:
                            completed_actions.append((action.future, None, exc))

                    if self.server.world.world_state.tick % 20 == 0:
                        for player in self.server.players.values():
                            self.runtime.apply_environment_damage(player)

                for future, payload, error in completed_actions:
                    if future.done():
                        continue
                    if error is not None:
                        future.set_exception(error)
                    else:
                        future.set_result(payload)
                await asyncio.sleep(self.tick_interval_seconds)
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        self._running = False
        pending = self._pending_actions
        self._pending_actions = []
        self._script_cancel_events.clear()
        for action in pending:
            if not action.future.done():
                action.future.set_exception(BasicRuntimeError("Server stopped before action execution"))
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def add_player(
        self,
        sid: str,
        user: SessionUser,
        *,
        restored_state: dict | None = None,
    ) -> PlayerState:
        async with self._lock:
            if sid in self.server.players:
                return self.server.players[sid]
            for existing_sid, existing_player in list(self.server.players.items()):
                if existing_player.user_id == user.id:
                    self.server.players.pop(existing_sid, None)
                    self.server.players[sid] = existing_player
                    if existing_sid in self._active_script_players:
                        self._active_script_players.discard(existing_sid)
                        self._active_script_players.add(sid)
                    if existing_sid in self._script_cancel_events:
                        self._script_cancel_events[sid] = self._script_cancel_events.pop(existing_sid)
                    for action in self._pending_actions:
                        if action.sid == existing_sid:
                            action.sid = sid
                    return existing_player
            if len(self.server.players) >= self.server.max_players:
                raise ValueError("Server is full")

            spawn_point = self.server.world.world_state.spawn_point
            if restored_state:
                player = self._player_from_snapshot(user, restored_state, spawn_point)
            else:
                player = PlayerState(
                    user_id=user.id,
                    username=user.username,
                    position=spawn_point,
                )
            self.server.players[sid] = player
            self.server.status = "active"
            return player

    async def remove_player(self, sid: str) -> tuple[bool, dict | None]:
        interrupted_actions: list[ScheduledPlayerAction] = []
        snapshot: dict | None = None
        async with self._lock:
            self._active_script_players.discard(sid)
            self._script_cancel_events.pop(sid, None)
            remaining_actions: list[ScheduledPlayerAction] = []
            for action in self._pending_actions:
                if action.sid == sid:
                    interrupted_actions.append(action)
                else:
                    remaining_actions.append(action)
            self._pending_actions = remaining_actions
            player = self.server.players.pop(sid, None)
            if player:
                snapshot = self._player_snapshot(sid, player)
            self.server.status = "active" if self.server.players else "waiting"

        for action in interrupted_actions:
            if not action.future.done():
                action.future.set_exception(BasicRuntimeError("Script interrupted because player disconnected"))

        return not self.server.players, snapshot

    async def move_player(self, sid: str, direction: str) -> tuple[dict, dict]:
        state, public_state, _ = await self._schedule_player_action(
            sid,
            self.manual_action_tick_cost,
            lambda player: self.runtime.move_player(player, direction),
        )
        return state, public_state

    async def turn_player(self, sid: str, direction: str) -> tuple[dict, dict]:
        state, public_state, _ = await self._schedule_player_action(
            sid,
            self.manual_action_tick_cost,
            lambda player: self.runtime.turn_player(player, direction),
        )
        return state, public_state

    async def heal_player(self, sid: str) -> tuple[dict, dict]:
        state, public_state, _ = await self._schedule_player_action(
            sid,
            self.manual_action_tick_cost,
            lambda player: self.runtime.heal_player(player),
        )
        return state, public_state

    async def restart_player(self, sid: str) -> tuple[dict, dict]:
        def _restart(player: PlayerState) -> None:
            player.position = self.server.world.world_state.spawn_point
            player.direction = "north"
            player.health = MAX_PLAYER_HEALTH
            player.mode = "manual"
            player.going_circles = False

        state, public_state, _ = await self._schedule_player_action(
            sid,
            self.manual_action_tick_cost,
            _restart,
        )
        return state, public_state

    async def execute_script(
        self,
        sid: str,
        script_text: str,
        *,
        on_state_change: StateChangeCallback | None = None,
    ) -> tuple[dict, dict, dict]:
        async with self._lock:
            if sid in self._active_script_players:
                raise ValueError("A script is already running for this player")

            player = self._require_player(sid)
            self._active_script_players.add(sid)
            cancel_event = asyncio.Event()
            self._script_cancel_events[sid] = cancel_event
            player.mode = "automatic"
            player.going_circles = False

        async def move(direction: str):
            state, public_state, _ = await self._schedule_player_action(
                sid,
                self.script_action_tick_cost,
                lambda current_player: self.runtime.move_player(current_player, direction),
            )
            await self._emit_state_change_if_needed(sid, state, public_state, on_state_change)
            return "ok"

        async def turn(direction: str):
            state, public_state, _ = await self._schedule_player_action(
                sid,
                self.script_action_tick_cost,
                lambda current_player: self.runtime.turn_player(current_player, direction),
            )
            await self._emit_state_change_if_needed(sid, state, public_state, on_state_change)
            return "ok"

        async def heal():
            state, public_state, current_health = await self._schedule_player_action(
                sid,
                self.script_action_tick_cost,
                lambda current_player: self.runtime.heal_player(current_player) or current_player.health,
            )
            await self._emit_state_change_if_needed(sid, state, public_state, on_state_change)
            return current_health if current_health is not None else state.get("health")

        async def get_robot_coordinates():
            async with self._lock:
                current_player = self._require_script_player(sid)
                return list(current_player.position)

        async def get_robot_location():
            async with self._lock:
                current_player = self._require_script_player(sid)
                return self.runtime.get_current_location(current_player)

        async def get_block(position_name: str, eyelevel: bool):
            async with self._lock:
                current_player = self._require_script_player(sid)
                return self.runtime.get_block_in_direction(current_player, position_name.lower(), bool(eyelevel))

        async def depth(position_name: str):
            async with self._lock:
                current_player = self._require_script_player(sid)
                return self.runtime.depth(current_player, position_name.lower())

        async def addtree(x: int, y: int, z: int):
            state, public_state, result = await self._schedule_player_action(
                sid,
                self.script_action_tick_cost,
                lambda _current_player: self.runtime.add_tree(int(x), int(y), int(z)),
            )
            await self._emit_state_change_if_needed(sid, state, public_state, on_state_change)
            return result

        callbacks = {
            "MOVE": move,
            "TURN": turn,
            "HEAL": heal,
            "GET_ROBOT_COORDINATES": get_robot_coordinates,
            "GET_ROBOT_LOCATION": get_robot_location,
            "GET_BLOCK": get_block,
            "DEPTH": depth,
            "ADDTREE": addtree,
        }

        result = await self.script_runtime.execute(
            script_text,
            callbacks,
            cancel_requested=cancel_event.is_set,
        )

        async with self._lock:
            self._active_script_players.discard(sid)
            self._script_cancel_events.pop(sid, None)
            current_player = self.server.players.get(sid)
            if current_player:
                current_player.mode = "manual"
                if not result.success and result.error and "loop iteration limit" in result.error.lower():
                    current_player.going_circles = True
                state = self._build_state_payload(sid)
                public_state = current_player.to_public_dict(sid)
            else:
                state = {}
                public_state = {}

        script_result = {
            "success": result.success,
            "logs": result.logs,
            "error": result.error,
        }
        return state, public_state, script_result

    async def stop_script(self, sid: str) -> tuple[dict, dict] | None:
        interrupted_actions: list[ScheduledPlayerAction] = []
        async with self._lock:
            if sid not in self._active_script_players:
                return None

            cancel_event = self._script_cancel_events.get(sid)
            if cancel_event:
                cancel_event.set()

            remaining_actions: list[ScheduledPlayerAction] = []
            for action in self._pending_actions:
                if action.sid == sid:
                    interrupted_actions.append(action)
                else:
                    remaining_actions.append(action)
            self._pending_actions = remaining_actions

            player = self.server.players.get(sid)
            if not player:
                return None
            player.mode = "manual"
            state = self._build_state_payload(sid)
            public_state = player.to_public_dict(sid)

        for action in interrupted_actions:
            if not action.future.done():
                action.future.set_exception(BasicScriptCancelledError("Скрипт остановлен игроком"))

        return state, public_state

    async def _schedule_player_action(
        self,
        sid: str,
        tick_cost: int,
        operation: Callable[[PlayerState], object | None],
    ) -> tuple[dict, dict, object | None]:
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()

        async with self._lock:
            self._require_player(sid)
            execute_at_tick = self.server.world.world_state.tick + max(1, int(tick_cost))
            self._pending_actions.append(
                ScheduledPlayerAction(
                    sid=sid,
                    execute_at_tick=execute_at_tick,
                    future=future,
                    operation=operation,
                )
            )

        state, public_state, operation_result = await future
        return state, public_state, operation_result

    def _require_script_player(self, sid: str) -> PlayerState:
        player = self.server.players.get(sid)
        if not player:
            raise BasicRuntimeError("Script interrupted because player disconnected")
        return player

    async def update_player_state(
        self,
        sid: str,
        *,
        position=None,
        rotation=None,
        health=None,
    ) -> dict | None:
        async with self._lock:
            player = self.server.players.get(sid)
            if not player:
                return None
            if position is not None:
                player.position = tuple(position)
            if rotation is not None:
                normalized = str(rotation).lower()
                if normalized in DIRECTION_TO_RUSSIAN:
                    player.direction = normalized
            if health is not None:
                player.health = int(health)
            return player.to_public_dict(sid)

    def build_player_snapshot(self, sid: str) -> dict:
        player = self._require_player(sid)
        return self._player_snapshot(sid, player)

    def build_state_payload(self, sid: str) -> dict:
        return self._build_state_payload(sid)

    def build_world_payload(self, sid: str | None = None) -> dict:
        payload = {
            "server_code": self.server.server_code,
            "server_id": self.server.server_id,
            "world": self.server.world.to_dict(),
            "players": [
                player.to_public_dict(player_sid)
                for player_sid, player in self.server.players.items()
            ],
            "chat_history": self.chat_history[-50:],
        }
        if sid is not None and sid in self.server.players:
            payload["self"] = self._build_state_payload(sid)
        return payload

    def build_tick_payload(self, sid: str) -> dict:
        return {
            "tick": self.server.world.world_state.tick,
            "server_code": self.server.server_code,
            "self": self._build_state_payload(sid),
            "players": [
                player.to_public_dict(player_sid)
                for player_sid, player in self.server.players.items()
            ],
        }

    def list_player_ids(self) -> list[str]:
        return list(self.server.players.keys())

    async def add_chat_message(self, sid: str, payload: dict | str) -> dict:
        async with self._lock:
            player = self._require_player(sid)
            if isinstance(payload, str):
                payload = {"message": payload}

            message = {
                "player_id": sid,
                "user_id": player.user_id,
                "username": player.username,
                "message": str(payload.get("message", "")).strip(),
                "script_name": payload.get("script_name"),
                "script_content": payload.get("script_content"),
                "timestamp": int(time.time() * 1000),
            }
            self.chat_history.append(message)
            self.chat_history = self.chat_history[-50:]
            return message

    def _build_state_payload(self, sid: str) -> dict:
        player = self._require_player(sid)
        location = self.runtime.get_current_location(player)
        return {
            "coordinates": list(player.position),
            "mode": MODE_TO_RUSSIAN[player.mode],
            "mode_key": player.mode,
            "direction": DIRECTION_TO_RUSSIAN[player.direction],
            "direction_key": player.direction,
            "health": player.health,
            "temperature": self.runtime.get_temperature(player),
            "location": location,
            "nearLocations": self.runtime.get_near_locations(player),
            "timestamp": int(time.time() * 1000),
            "going_circles": player.going_circles,
            "username": player.username,
        }

    async def _emit_state_change_if_needed(
        self,
        sid: str,
        state: dict,
        public_state: dict,
        callback: StateChangeCallback | None,
    ) -> None:
        if callback is None:
            return
        await callback(state, public_state)

    def _require_player(self, sid: str) -> PlayerState:
        player = self.server.players.get(sid)
        if not player:
            raise ValueError("Player is not connected to this server")
        return player

    def _player_snapshot(self, sid: str, player: PlayerState) -> dict:
        return {
            **player.to_snapshot_dict(server_code=self.server.server_code),
            "player_id": sid,
            "world_id": self.server.world.world_id,
            "world_name": self.server.world.world_name,
        }

    def _player_from_snapshot(
        self,
        user: SessionUser,
        snapshot: dict,
        spawn_point,
    ) -> PlayerState:
        coordinates = snapshot.get("coordinates") or spawn_point
        if not isinstance(coordinates, (list, tuple)) or len(coordinates) != 3:
            coordinates = spawn_point
        direction = str(snapshot.get("direction_key", "north")).lower()
        if direction not in DIRECTION_TO_RUSSIAN:
            direction = "north"
        return PlayerState(
            user_id=user.id,
            username=str(snapshot.get("username") or user.username),
            position=tuple(int(value) for value in coordinates),
            direction=direction,
            health=int(snapshot.get("health", 10000)),
            mode="manual",
            going_circles=bool(snapshot.get("going_circles", False)),
        )
