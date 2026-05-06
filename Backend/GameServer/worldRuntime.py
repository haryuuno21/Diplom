from __future__ import annotations

import hashlib
import math
import random

from gameClasses import (
    BLOCK_ACID,
    BLOCK_AIR,
    BLOCK_LEAVES,
    BLOCK_SAND,
    BLOCK_SOIL,
    BLOCK_TREE,
    BLOCK_WATER,
    Coordinates,
    Direction,
    PlayerState,
    WorldState,
    position_to_key,
)


TURN_LEFT: dict[Direction, Direction] = {
    "north": "west",
    "west": "south",
    "south": "east",
    "east": "north",
}

TURN_RIGHT: dict[Direction, Direction] = {
    "north": "east",
    "east": "south",
    "south": "west",
    "west": "north",
}

RELATIVE_TO_DIRECTION: dict[Direction, dict[str, tuple[int, int]]] = {
    "north": {
        "forward": (0, 1),
        "backward": (0, -1),
        "left": (-1, 0),
        "right": (1, 0),
    },
    "south": {
        "forward": (0, -1),
        "backward": (0, 1),
        "left": (1, 0),
        "right": (-1, 0),
    },
    "east": {
        "forward": (1, 0),
        "backward": (-1, 0),
        "left": (0, 1),
        "right": (0, -1),
    },
    "west": {
        "forward": (-1, 0),
        "backward": (1, 0),
        "left": (0, -1),
        "right": (0, 1),
    },
}

LOOKUP_ALIASES = {
    "front": "forward",
    "back": "backward",
}


class WorldRuntime:
    def __init__(self, world_state: WorldState):
        self.world_state = world_state
        if not world_state.seed:
            world_state.seed = "default"
        self._spawn_rng = random.Random(f"{world_state.seed}:spawn")

    def find_spawn_point(self) -> Coordinates:
        for _ in range(512):
            x = self._spawn_rng.randint(8, self.world_state.width - 9)
            z = self._spawn_rng.randint(8, self.world_state.depth - 9)
            y = self.get_surface_height(x, z) + 1
            location = self.get_block((x, y - 1, z))
            if location not in (BLOCK_WATER, BLOCK_ACID) and 1 < y < self.world_state.height - 2:
                return (x, y, z)
        return (self.world_state.width // 2, self.get_surface_height(self.world_state.width // 2, self.world_state.depth // 2) + 1, self.world_state.depth // 2)

    def in_bounds(self, position: Coordinates) -> bool:
        x, y, z = position
        return (
            0 <= x < self.world_state.width
            and 0 <= y < self.world_state.height
            and 0 <= z < self.world_state.depth
        )

    def get_block(self, position: Coordinates) -> str:
        if not self.in_bounds(position):
            return BLOCK_AIR

        override = self.world_state.overrides.get(position_to_key(position))
        if override is not None:
            return override

        x, y, z = position
        surface_height = self.get_surface_height(x, z)

        if y > surface_height:
            if surface_height < self.world_state.water_level and y <= self.world_state.water_level:
                return BLOCK_WATER
            return BLOCK_AIR

        if y == surface_height:
            return self.get_surface_block(x, z, surface_height)

        return BLOCK_SOIL

    def set_block(self, position: Coordinates, block_type: str) -> None:
        if self.in_bounds(position):
            self.world_state.overrides[position_to_key(position)] = block_type

    def get_surface_height(self, x: int, z: int) -> int:
        low = self._value_noise_2d(x, z, 24)
        high = self._value_noise_2d(x, z, 8)
        height = 18 + int(low * 30 + high * 14)
        return max(4, min(self.world_state.height - 4, height))

    def get_surface_block(self, x: int, z: int, height: int | None = None) -> str:
        if height is None:
            height = self.get_surface_height(x, z)
        if height <= self.world_state.water_level - 2:
            return BLOCK_SAND

        biome = self._value_noise_2d(x, z, 16, channel="biome")
        if biome < 0.16:
            return BLOCK_ACID
        if biome < 0.34:
            return BLOCK_SAND
        return BLOCK_SOIL

    def get_current_location(self, player: PlayerState) -> str:
        x, y, z = player.position
        return self.get_block((x, y - 1, z))

    def get_temperature(self, player: PlayerState) -> float:
        base = {
            BLOCK_AIR: 20.0,
            BLOCK_SOIL: 15.0,
            BLOCK_WATER: 10.0,
            BLOCK_ACID: 100.0,
            BLOCK_SAND: 24.0,
            BLOCK_TREE: 14.0,
            BLOCK_LEAVES: 13.0,
        }.get(self.get_current_location(player), 20.0)
        jitter = self._hash_float(
            "temp",
            player.position[0],
            player.position[1],
            player.position[2],
            self.world_state.tick // 20,
        )
        return base + (jitter * 5.0 - 2.5)

    def apply_environment_damage(self, player: PlayerState) -> None:
        location = self.get_current_location(player)
        if location == BLOCK_ACID:
            player.health -= 100
        elif location == BLOCK_WATER:
            player.health -= 10
        player.health = max(0, player.health)

    def move_player(self, player: PlayerState, direction: str) -> bool:
        if direction not in ("forward", "backward", "left", "right"):
            raise ValueError("Unsupported move direction")

        dx, dz = RELATIVE_TO_DIRECTION[player.direction][direction]
        x, y, z = player.position
        next_position = (x + dx, y, z + dz)

        if not self.in_bounds(next_position):
            return False

        future_x, future_y, future_z = next_position

        if self.get_block((future_x, future_y, future_z)) != BLOCK_AIR:
            stepped_up = (future_x, future_y + 1, future_z)
            if not self.in_bounds(stepped_up) or self.get_block(stepped_up) != BLOCK_AIR:
                return False
            future_y += 1

        while future_y > 1 and self.get_block((future_x, future_y - 1, future_z)) == BLOCK_AIR:
            future_y -= 1

        if future_y <= 0:
            return False

        fall_distance = y - future_y
        if fall_distance > 3:
            player.health -= fall_distance * 100

        player.position = (future_x, future_y, future_z)
        player.health = max(0, player.health)
        self.apply_environment_damage(player)
        return True

    def turn_player(self, player: PlayerState, direction: str) -> None:
        if direction == "left":
            player.direction = TURN_LEFT[player.direction]
        elif direction == "right":
            player.direction = TURN_RIGHT[player.direction]
        else:
            raise ValueError("Unsupported turn direction")

    def heal_player(self, player: PlayerState, amount: int = 10) -> None:
        player.health = min(10000, player.health + amount)

    def get_block_in_direction(self, player: PlayerState, position_name: str, eyelevel: bool) -> str:
        position_name = LOOKUP_ALIASES.get(position_name, position_name)
        if position_name == "under":
            x, y, z = player.position
            return self.get_block((x, y - 1, z))

        offsets = RELATIVE_TO_DIRECTION[player.direction]
        if position_name not in offsets:
            raise ValueError("Unsupported position lookup")

        dx, dz = offsets[position_name]
        x, y, z = player.position
        probe_y = y if eyelevel else y - 1
        return self.get_block((x + dx, probe_y, z + dz))

    def depth(self, player: PlayerState, position_name: str) -> int:
        position_name = LOOKUP_ALIASES.get(position_name, position_name)
        offsets = RELATIVE_TO_DIRECTION[player.direction]
        if position_name not in offsets:
            raise ValueError("Unsupported depth direction")

        dx, dz = offsets[position_name]
        x, y, z = player.position
        target_x = x + dx
        target_z = z + dz
        probe_y = y - 1

        if not self.in_bounds((target_x, max(probe_y, 0), target_z)):
            return 10000

        if self.get_block((target_x, probe_y, target_z)) == BLOCK_AIR:
            final_y = probe_y - 1
            while final_y >= 0 and self.get_block((target_x, final_y, target_z)) == BLOCK_AIR:
                final_y -= 1
            if final_y < 0:
                return 10000
            return probe_y - final_y - 1

        final_y = probe_y + 1
        while final_y < self.world_state.height and self.get_block((target_x, final_y, target_z)) != BLOCK_AIR:
            final_y += 1
        if final_y >= self.world_state.height:
            return -10000
        return probe_y - final_y + 1

    def add_tree(self, x: int, y: int, z: int) -> str:
        blocks = {
            (x, y, z): BLOCK_TREE,
            (x, y + 1, z): BLOCK_TREE,
            (x, y + 2, z): BLOCK_TREE,
            (x + 1, y + 2, z): BLOCK_LEAVES,
            (x - 1, y + 2, z): BLOCK_LEAVES,
            (x, y + 2, z - 1): BLOCK_LEAVES,
            (x, y + 2, z + 1): BLOCK_LEAVES,
            (x, y + 3, z): BLOCK_LEAVES,
        }
        for position, block_type in blocks.items():
            self.set_block(position, block_type)
        return "success"

    def get_near_locations(self, player: PlayerState, radius: int = 5) -> list[dict]:
        x, y, z = player.position
        result: list[dict] = []
        for px in range(x - radius, x + radius + 1):
            for py in range(y - radius, y + radius + 1):
                for pz in range(z - radius, z + radius + 1):
                    position = (px, py, pz)
                    if not self.in_bounds(position):
                        continue
                    block_type = self.get_block(position)
                    if block_type == BLOCK_AIR:
                        continue
                    result.append(
                        {
                            "coordinates": [px, py, pz],
                            "location": block_type,
                        }
                    )
        return result

    def _value_noise_2d(self, x: int, z: int, scale: int, *, channel: str = "terrain") -> float:
        scaled_x = x / scale
        scaled_z = z / scale
        x0 = math.floor(scaled_x)
        z0 = math.floor(scaled_z)
        x1 = x0 + 1
        z1 = z0 + 1
        sx = scaled_x - x0
        sz = scaled_z - z0

        n00 = self._hash_float(channel, x0, z0)
        n10 = self._hash_float(channel, x1, z0)
        n01 = self._hash_float(channel, x0, z1)
        n11 = self._hash_float(channel, x1, z1)

        ix0 = self._lerp(n00, n10, self._smoothstep(sx))
        ix1 = self._lerp(n01, n11, self._smoothstep(sx))
        return self._lerp(ix0, ix1, self._smoothstep(sz))

    def _hash_float(self, channel: str, *parts: int) -> float:
        payload = ":".join([self.world_state.seed, channel, *[str(part) for part in parts]])
        digest = hashlib.sha256(payload.encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") / float(2**64 - 1)

    @staticmethod
    def _lerp(a: float, b: float, factor: float) -> float:
        return a + (b - a) * factor

    @staticmethod
    def _smoothstep(value: float) -> float:
        return value * value * (3 - 2 * value)
