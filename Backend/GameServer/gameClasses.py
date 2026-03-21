from dataclasses import asdict, dataclass
from typing import Literal, Tuple, List
import uuid
from time import time

from apiModels import User

Coordinates = Tuple[int, int, int]
Direction = Literal["N", "W", "S", "E"]

@dataclass
class PlayerState:
    user_id: int
    position: Coordinates = (0, 0, 0)
    rotation: Direction = "N"
    health: int = 100

@dataclass
class Block:
    position: Coordinates = (0, 0, 0)
    id: int = 0

@dataclass
class WorldState:
    blocks: list[Block]
    players: list[PlayerState]

    def toJson(self):
        return asdict(self)

@dataclass
class World:
    world_id: int
    world_name: str
    world_seed: str
    world_creator_id: int
    world_created_at: float
    world_state: WorldState

class GameServer:
    server_id: str
    server_code: str  # Уникальный код для подключения (например: "ABC123")
    host_id: int
    world: World
    created_at: float
    max_players: int
    players: list[User]

    def __init__(self, world: World, host_id: int, max_players: int, server_code: str):
        self.server_id = str(uuid.uuid4())
        self.server_code = server_code
        self.host_id = host_id
        self.world_state = world
        self.created_at = time()
        self.max_players = max_players
    
    def add_player(self, user: User):
        if user not in self.players:
            self.players.append(user)
    
    def remove_player(self, user: User):
        if user in self.players:
            self.players.remove(user)
        return len(self.players) == 0  # True если сервер пустой