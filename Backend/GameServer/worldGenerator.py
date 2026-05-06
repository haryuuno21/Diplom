import random
import secrets

from gameClasses import WorldState
from worldRuntime import WorldRuntime


class WorldGenerator:
    def generate_world(self, seed: str) -> WorldState:
        rng = random.Random(seed)
        water_level = 24 + rng.randint(0, 8)
        world_state = WorldState(seed=seed, water_level=water_level)
        runtime = WorldRuntime(world_state)
        world_state.spawn_point = runtime.find_spawn_point()
        return world_state

    def generate_seed(self) -> str:
        return secrets.token_hex(8)
