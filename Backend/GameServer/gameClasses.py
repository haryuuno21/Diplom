from dataclasses import dataclass, field
from time import time
from typing import Literal
import uuid


Coordinates = tuple[int, int, int]
Direction = Literal["north", "east", "south", "west"]
PlayerMode = Literal["manual", "automatic"]

BLOCK_AIR = "воздух"
BLOCK_SOIL = "почва"
BLOCK_ACID = "кислотная поверхность"
BLOCK_SAND = "песок"
BLOCK_WATER = "вода"
BLOCK_TREE = "дерево"
BLOCK_LEAVES = "листва"

MAX_PLAYER_HEALTH = 10000

DIRECTION_TO_RUSSIAN: dict[Direction, str] = {
    "north": "север",
    "east": "восток",
    "south": "юг",
    "west": "запад",
}

RUSSIAN_TO_DIRECTION = {value: key for key, value in DIRECTION_TO_RUSSIAN.items()}

MODE_TO_RUSSIAN: dict[PlayerMode, str] = {
    "manual": "ручной",
    "automatic": "автоматический",
}


def position_to_key(position: Coordinates) -> str:
    x, y, z = position
    return f"{x}:{y}:{z}"


def key_to_position(value: str) -> Coordinates:
    x, y, z = value.split(":")
    return int(x), int(y), int(z)


@dataclass
class PlayerState:
    user_id: int
    username: str
    position: Coordinates
    direction: Direction = "north"
    health: int = MAX_PLAYER_HEALTH
    mode: PlayerMode = "manual"
    going_circles: bool = False

    def to_public_dict(self, sid: str) -> dict:
        return {
            "player_id": sid,
            "user_id": self.user_id,
            "username": self.username,
            "coordinates": list(self.position),
            "direction": DIRECTION_TO_RUSSIAN[self.direction],
            "direction_key": self.direction,
            "health": self.health,
            "mode": MODE_TO_RUSSIAN[self.mode],
            "mode_key": self.mode,
        }

    def to_snapshot_dict(self, *, server_code: str) -> dict:
        return {
            "server_code": server_code,
            "user_id": self.user_id,
            "username": self.username,
            "coordinates": list(self.position),
            "direction_key": self.direction,
            "health": self.health,
            "mode_key": self.mode,
            "going_circles": self.going_circles,
        }


@dataclass
class WorldState:
    seed: str
    width: int = 128
    height: int = 128
    depth: int = 128
    water_level: int = 32
    spawn_point: Coordinates = (64, 64, 64)
    overrides: dict[str, str] = field(default_factory=dict)
    tick: int = 0

    def to_dict(self) -> dict:
        return {
            "seed": self.seed,
            "width": self.width,
            "height": self.height,
            "depth": self.depth,
            "water_level": self.water_level,
            "spawn_point": list(self.spawn_point),
            "overrides": self.overrides,
            "tick": self.tick,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WorldState":
        if not data:
            return cls(seed="")
        return cls(
            seed=data.get("seed", ""),
            width=int(data.get("width", 128)),
            height=int(data.get("height", 128)),
            depth=int(data.get("depth", 128)),
            water_level=int(data.get("water_level", 32)),
            spawn_point=tuple(data.get("spawn_point", (64, 64, 64))),
            overrides={str(key): str(value) for key, value in data.get("overrides", {}).items()},
            tick=int(data.get("tick", 0)),
        )


@dataclass
class World:
    world_id: int
    world_name: str
    world_seed: str
    world_creator_id: int
    world_created_at: float
    last_modified: float
    world_state: WorldState

    def to_dict(self) -> dict:
        return {
            "world_id": self.world_id,
            "world_name": self.world_name,
            "world_seed": self.world_seed,
            "world_creator_id": self.world_creator_id,
            "world_created_at": self.world_created_at,
            "last_modified": self.last_modified,
            "world_state": self.world_state.to_dict(),
        }


@dataclass
class GameServer:
    world: World
    host_id: int
    max_players: int
    server_code: str
    server_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: float = field(default_factory=time)
    status: str = "waiting"
    players: dict[str, PlayerState] = field(default_factory=dict)

    @property
    def world_id(self) -> int:
        return self.world.world_id

    @property
    def world_name(self) -> str:
        return self.world.world_name

    @property
    def player_count(self) -> int:
        return len(self.players)
