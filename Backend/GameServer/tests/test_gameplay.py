import asyncio
import time
import unittest

from basicRuntime import BasicScriptRuntime
from gameClasses import GameServer, World
from gameServerManager import GameServerManager
from serverControlService import ServerControlService
from worldGenerator import WorldGenerator


class GameplayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        world_state = WorldGenerator().generate_world("test-seed")
        world = World(
            world_id=1,
            world_name="Test World",
            world_seed="test-seed",
            world_creator_id=1,
            world_created_at=0.0,
            last_modified=0.0,
            world_state=world_state,
        )
        self.manager = GameServerManager(
            GameServer(world=world, host_id=1, max_players=4, server_code="ABC123")
        )
        self.manager.start()

        class User:
            id = 1
            username = "tester"

        self.user = User()
        await self.manager.add_player("sid1", self.user)

        class UserTwo:
            id = 2
            username = "tester_two"

        self.user_two = UserTwo()
        await self.manager.add_player("sid2", self.user_two)

    async def asyncTearDown(self):
        await self.manager.stop()

    async def test_tick_payload_contains_self_and_players(self):
        payload = self.manager.build_tick_payload("sid1")
        self.assertIn("self", payload)
        self.assertIn("players", payload)
        self.assertEqual(payload["players"][0]["username"], "tester")
        self.assertEqual(len(payload["players"]), 2)

    async def test_legacy_depth_script_executes(self):
        state, _, result = await self.manager.execute_script(
            "sid1",
            'WHILE(DEPTH("front") = 0)\n    MOVE("forward")\nEND WHILE',
        )
        self.assertTrue(result["success"], result["error"])
        self.assertIn("coordinates", state)

    async def test_endless_script_is_stopped(self):
        self.manager.script_runtime.max_loop_iterations = 20
        _, _, result = await self.manager.execute_script(
            "sid1",
            'WHILE(1=1)\n    MOVE("forward")\n    MOVE("backward")\nEND WHILE',
        )
        self.assertFalse(result["success"])
        self.assertIn("loop iteration limit", result["error"].lower())

    async def test_chat_message_is_saved(self):
        message = await self.manager.add_chat_message("sid1", {"message": "hello"})
        self.assertEqual(message["message"], "hello")
        payload = self.manager.build_world_payload("sid1")
        self.assertEqual(payload["chat_history"][-1]["message"], "hello")

    async def test_script_draft_is_in_player_snapshot_and_world_payload(self):
        self.manager.set_player_script_draft(
            "sid1",
            {
                "script_name": "restore.bas",
                "script_content": 'MOVE("forward")',
            },
        )

        snapshot = self.manager.build_player_snapshot("sid1")
        payload = self.manager.build_world_payload("sid1")

        self.assertEqual(snapshot["script_name"], "restore.bas")
        self.assertEqual(snapshot["script_content"], 'MOVE("forward")')
        self.assertEqual(payload["script_draft"]["script_name"], "restore.bas")
        self.assertEqual(payload["script_draft"]["script_content"], 'MOVE("forward")')

    async def test_loaded_chat_history_is_in_world_payload(self):
        self.manager.load_chat_history(
            [
                {
                    "player_id": "old-sid",
                    "user_id": 1,
                    "username": "tester",
                    "message": "from database",
                    "script_name": None,
                    "script_content": None,
                    "timestamp": 123,
                }
            ]
        )

        payload = self.manager.build_world_payload("sid1")
        self.assertEqual(payload["chat_history"][-1]["message"], "from database")

    async def test_service_persists_chat_message(self):
        class FakeDBService:
            def __init__(self):
                self.saved_messages = []

            async def store_chat_message(self, world_id, server_code, message):
                self.saved_messages.append((world_id, server_code, message))

        fake_db = FakeDBService()
        service = ServerControlService(fake_db)
        service.managers[self.manager.server.server_code] = self.manager

        message = await service.add_chat_message(
            self.manager.server.server_code,
            "sid1",
            {"message": "persist me"},
        )

        self.assertEqual(message["message"], "persist me")
        self.assertEqual(fake_db.saved_messages[-1][0], self.manager.server.world_id)
        self.assertEqual(fake_db.saved_messages[-1][1], self.manager.server.server_code)
        self.assertEqual(fake_db.saved_messages[-1][2]["message"], "persist me")

    async def test_service_persists_script_draft(self):
        class FakeDBService:
            def __init__(self):
                self.saved_snapshots = []

            async def store_player_state(self, world_id, user_id, snapshot, *, persist_to_postgres=False):
                self.saved_snapshots.append((world_id, user_id, snapshot, persist_to_postgres))

            async def upsert_server_record(self, server):
                return None

            async def store_active_server(self, server_info):
                return None

        fake_db = FakeDBService()
        service = ServerControlService(fake_db)
        service.managers[self.manager.server.server_code] = self.manager

        draft = await service.save_player_script_state(
            self.manager.server.server_code,
            "sid1",
            {
                "script_name": "restore.bas",
                "script_content": 'MOVE("forward")',
            },
        )

        self.assertEqual(draft["script_name"], "restore.bas")
        self.assertTrue(fake_db.saved_snapshots[-1][3])
        self.assertEqual(fake_db.saved_snapshots[-1][2]["script_name"], "restore.bas")
        self.assertEqual(fake_db.saved_snapshots[-1][2]["script_content"], 'MOVE("forward")')

    async def test_player_snapshot_restores_state(self):
        await self.manager.turn_player("sid1", "right")
        await self.manager.move_player("sid1", "forward")

        snapshot = self.manager.build_player_snapshot("sid1")

        restored_world = World(
            world_id=2,
            world_name="Restored World",
            world_seed="restored-seed",
            world_creator_id=1,
            world_created_at=0.0,
            last_modified=0.0,
            world_state=WorldGenerator().generate_world("restored-seed"),
        )
        restored_manager = GameServerManager(
            GameServer(world=restored_world, host_id=1, max_players=4, server_code="ZZZ999")
        )
        restored_manager.start()

        try:
            restored_player = await restored_manager.add_player(
                "sid-restored",
                self.user,
                restored_state=snapshot,
            )

            self.assertEqual(restored_player.position, tuple(snapshot["coordinates"]))
            self.assertEqual(restored_player.direction, snapshot["direction_key"])
            self.assertEqual(restored_player.health, snapshot["health"])
        finally:
            await restored_manager.stop()

    async def test_disconnect_persists_player_snapshot(self):
        class FakeDBService:
            def __init__(self):
                self.saved_snapshots = []

            async def get_world_for_user(self, world_id, user_id):
                return self.world

            async def get_player_state(self, world_id, user_id):
                return None

            async def store_player_state(self, world_id, user_id, snapshot, *, persist_to_postgres=False):
                self.saved_snapshots.append((world_id, user_id, snapshot, persist_to_postgres))

            async def upsert_server_record(self, server):
                return None

            async def store_active_server(self, server_info):
                return None

            async def delete_active_server(self, server_code):
                return None

            async def update_server_status(self, server_code, status, player_count):
                return None

            async def save_world_state(self, world_id, world_state):
                return None

        fake_db = FakeDBService()
        fake_db.world = self.manager.server.world
        service = ServerControlService(fake_db)
        service.managers[self.manager.server.server_code] = self.manager

        await self.manager.move_player("sid1", "forward")
        expected_snapshot = self.manager.build_player_snapshot("sid1")
        await service.remove_player(self.manager.server.server_code, "sid1")

        persisted = fake_db.saved_snapshots[-1]
        self.assertEqual(persisted[0], self.manager.server.world.world_id)
        self.assertEqual(persisted[1], self.user.id)
        self.assertTrue(persisted[3])
        self.assertEqual(persisted[2]["coordinates"], expected_snapshot["coordinates"])
        self.assertEqual(len(self.manager.server.players), 1)

    async def test_server_stays_alive_for_idle_timeout(self):
        class FakeDBService:
            def __init__(self):
                self.saved_snapshots = []
                self.updated_servers = []
                self.deleted_servers = []
                self.saved_worlds = []

            async def get_world_for_user(self, world_id, user_id):
                return self.world

            async def get_player_state(self, world_id, user_id):
                return None

            async def store_player_state(self, world_id, user_id, snapshot, *, persist_to_postgres=False):
                self.saved_snapshots.append((world_id, user_id, snapshot, persist_to_postgres))

            async def upsert_server_record(self, server):
                return None

            async def store_active_server(self, server_info):
                return None

            async def delete_active_server(self, server_code):
                self.deleted_servers.append(server_code)

            async def update_server_status(self, server_code, status, player_count):
                self.updated_servers.append((server_code, status, player_count))

            async def save_world_state(self, world_id, world_state):
                self.saved_worlds.append((world_id, world_state.tick))

        fake_db = FakeDBService()
        fake_db.world = self.manager.server.world
        service = ServerControlService(fake_db, idle_shutdown_seconds=0.05)
        service.managers[self.manager.server.server_code] = self.manager

        await service.remove_player(self.manager.server.server_code, "sid1")
        await service.remove_player(self.manager.server.server_code, "sid2")

        self.assertIn(self.manager.server.server_code, service.managers)
        await asyncio.sleep(0.08)

        self.assertNotIn(self.manager.server.server_code, service.managers)
        self.assertIn(self.manager.server.server_code, fake_db.deleted_servers)
        self.assertTrue(fake_db.saved_worlds)

    async def test_script_does_not_block_other_player_or_ticks(self):
        self.manager.script_action_tick_cost = 2
        start_tick = self.manager.server.world.world_state.tick

        script_task = asyncio.create_task(
            self.manager.execute_script(
                "sid1",
                'FOR I = 1 TO 4\n    TURN("right")\nNEXT',
            )
        )

        await asyncio.sleep(0.03)
        other_state_before = self.manager.build_state_payload("sid2")
        other_state_after, _ = await self.manager.turn_player("sid2", "right")

        await asyncio.sleep(0.12)
        middle_tick = self.manager.server.world.world_state.tick
        self.assertGreater(middle_tick, start_tick)
        self.assertNotEqual(other_state_before["direction_key"], other_state_after["direction_key"])

        _, _, result = await script_task
        self.assertTrue(result["success"], result["error"])

    async def test_players_can_run_scripts_in_parallel(self):
        self.manager.script_action_tick_cost = 2
        started_at = time.monotonic()

        first_task = asyncio.create_task(
            self.manager.execute_script(
                "sid1",
                'FOR I = 1 TO 2\n    TURN("right")\nNEXT',
            )
        )
        second_task = asyncio.create_task(
            self.manager.execute_script(
                "sid2",
                'FOR I = 1 TO 2\n    TURN("left")\nNEXT',
            )
        )

        first_result, second_result = await asyncio.gather(first_task, second_task)
        elapsed = time.monotonic() - started_at

        self.assertTrue(first_result[2]["success"], first_result[2]["error"])
        self.assertTrue(second_result[2]["success"], second_result[2]["error"])
        self.assertLess(elapsed, 0.35)

    async def test_script_can_be_stopped(self):
        self.manager.script_action_tick_cost = 2

        script_task = asyncio.create_task(
            self.manager.execute_script(
                "sid1",
                'WHILE(1=1)\n    TURN("right")\nEND WHILE',
            )
        )

        await asyncio.sleep(0.08)
        stop_result = await self.manager.stop_script("sid1")
        self.assertIsNotNone(stop_result)

        state, _public_state, result = await script_task
        self.assertFalse(result["success"])
        self.assertIn("stopped by user", result["error"].lower())
        self.assertEqual(state["mode_key"], "manual")


class BasicRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_basic_runtime_handles_assignment_and_loop(self):
        runtime = BasicScriptRuntime(max_loop_iterations=10)
        counter = {"value": 0}

        async def move(direction):
            counter["value"] += 1
            return direction

        async def depth(position):
            return 0 if counter["value"] < 2 else 1

        async def noop(*args, **kwargs):
            return None

        result = await runtime.execute(
            'X = 1\nWHILE(DEPTH("front") = 0)\n    MOVE("forward")\n    X = X + 1\nEND WHILE',
            {
                "MOVE": move,
                "TURN": noop,
                "HEAL": noop,
                "GET_ROBOT_COORDINATES": noop,
                "GET_ROBOT_LOCATION": noop,
                "GET_BLOCK": noop,
                "DEPTH": depth,
                "ADDTREE": noop,
            },
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(counter["value"], 2)


if __name__ == "__main__":
    unittest.main()
