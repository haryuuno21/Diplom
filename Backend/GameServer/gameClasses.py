from dataclasses import dataclass
from typing import Literal, Tuple, List
import uuid
from time import time

Coordinates = Tuple[int, int, int]
Direction = Literal["N", "W", "S", "E"]

@dataclass
class Player:
    user: User
    position: Coordinates = (0, 0, 0)
    rotation: Direction = "N"
    health: int = 100

@dataclass
class Block:
    position: Coordinates = (0, 0, 0)
    id: int = 0

@dataclass
class World:
    pass

class Connection:
    connection_id: str
    user_id: str


class GameServer:
    server_id: str
    server_code: str  # Уникальный код для подключения (например: "ABC123")
    host_id: str    # id создателя сервера
    connections: List[Connection]  # Список id всех подключений
    world: World
    created_at: float
    max_players: int

    def __init__(self, world: World, host_id: str, max_players: int):
        self.server_id = str(uuid.uuid4())
        self.server_code = self._generate_code()
        self.host_id = host_id
        self.world_state = world
        self.created_at = time()
        self.max_players = max_players
    
    def _generate_code(self) -> str:
        """Генерирует короткий уникальный код (6 символов)"""
        import random
        import string
        while True:
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            # Проверяем уникальность (в реальности через Redis или БД)
            if code not in active_servers:
                return code
    
    def add_player(self, id: str):
        if id not in self.players:
            self.players.append(id)
    
    def remove_player(self, id: str):
        if id in self.players:
            self.players.remove(id)
        return len(self.players) == 0  # True если сервер пустой