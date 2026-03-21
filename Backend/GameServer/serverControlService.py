###
# Данный класс будет хранить все созданные сервера
# Словарь Server code - Server
# ###

import asyncio
import random

from gameServerManager import GameServerManager
from apiModels import User
from gameDBService import GameDBService
from gameClasses import GameServer


class ServerControlService:
    def __init__(self, game_db_service: GameDBService):
        self.managers: dict[str, GameServerManager]
        self.game_db_service = game_db_service

    async def createServer(self, world_id: int, user: User) -> str:
        """
        Создает новый игровой сервер
        
        Args:
            world_id: ID мира для создания сервера
            user: Пользователь, создающий сервер
            
        Returns:
            Код сервера для подключения игроков
        """
        server_code = self.generateServerCode()
        world = await self.game_db_service.load_world(world_id)
        server = GameServer(
            server_code=server_code,
            host_id=user.id,
            world=world,
            max_players=4,
        )
        manager = GameServerManager(server, self.game_db_service)
        self.managers[server_code] = manager
        asyncio.create_task(manager.game_loop())

        return server_code

    def generateServerCode(self):
        """
        Генерирует уникальный 6-символьный код сервера
        
        Returns:
            Уникальный код сервера
        """
        chars = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
        
        # Попытки генерации (защита от бесконечного цикла)
        max_attempts = 1000
        
        for _ in range(max_attempts):
            code = ''.join(random.choices(chars, k=6))
            
            # Проверяем уникальность
            if code not in self.managers:
                return code
        
        raise RuntimeError("Could not generate unique server code after multiple attempts")
    
    async def stopServer(self, server_code: str):
        """
        Останавливает сервер и удаляет его из управления
        
        Args:
            server_code: Код сервера для остановки
        """
        if server_code in self.servers:
            # Останавливаем игровой цикл
            if server_code in self.managers:
                await self.managers[server_code].stop()
                del self.managers[server_code]
            
            print(f"Server {server_code} stopped and removed")
