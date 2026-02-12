from dataclasses import dataclass
import uuid
from typing import List
from time import time
from gameClasses import World

class Connection:
    connection_sid: str
    user_sid: str


class GameServer:
    server_sid: str
    server_code: str  # Уникальный код для подключения (например: "ABC123")
    host_sid: str    # SID создателя сервера
    connections: List[Connection]  # Список SID всех подключений
    world: World
    created_at: float
    max_players: int

    def __init__(self, world: World, host_sid: str, max_players: int):
        self.server_sid = str(uuid.uuid4())
        self.server_code = self._generate_code()
        self.host_sid = host_sid
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
    
    def add_player(self, sid: str):
        if sid not in self.players:
            self.players.append(sid)
    
    def remove_player(self, sid: str):
        if sid in self.players:
            self.players.remove(sid)
        return len(self.players) == 0  # True если сервер пустой