import asyncio
import time
from typing import Dict, List, Optional
from gameClasses import GameServer, World, PlayerState
import socketio

class GameServerManager:
    """Управляет игровым циклом конкретного сервера"""
    
    def __init__(self, server: GameServer, sio: socketio.AsyncServer):
        self.server = server
        self.sio = sio
        self.running = True
        self.tick_count = 0
        self.last_tick_time = time.time()
    
    async def game_loop(self):
        """Основной игровой цикл"""
        try:
            while self.running:
                # Обновляем мир
                await self.update_world()
                
                # Рассылаем обновления игрокам
                await self.broadcast_world_update()
                
                # Инкрементируем тик
                self.tick_count += 1
                
                # Ждем следующего тика (20 тиков/сек = 50мс)
                await asyncio.sleep(1/20)
        except asyncio.CancelledError:
            print(f"Game loop for server {self.server.server_code} cancelled")
        except Exception as e:
            print(f"Error in game loop for server {self.server.server_code}: {e}")
            self.running = False
    
    async def update_world(self):
        """Обновляет состояние мира"""
        # Здесь будет ваша игровая логика
        # Например: обработка скриптов, физика, события и т.д.
        
        # Пример: обновление времени в мире
        self.server.world.tick += 1
        
        # Пример: обработка действий игроков
        # for player in self.players.values():
        #     if player.current_script:
        #         await self.execute_player_script(player)
    
    async def broadcast_world_update(self):
        """Рассылает обновление состояния всем игрокам сервера"""
        # Формируем данные для отправки
        world_data = {
            "tick": self.server.world.tick,
            "blocks": self.server.world.get_changed_blocks_since_last_update(),
            "players": [player.to_dict() for player in self.players.values()]
        }
        
        # Рассылаем всем игрокам в комнате сервера
        await self.sio.emit(
            "world_update",
            world_data,
            room=self.server.server_code
        )
    
    async def add_player(self, sid: str, player_state: PlayerState):
        """Добавляет игрока на сервер"""
        self.server.players[sid] = player_state
        
        # Отправляем текущее состояние мира новому игроку
        await self.sio.emit(
            "world_state",
            self.server.world.to_dict(),
            to=sid
        )
        
        # Уведомляем других игроков о новом игроке
        await self.sio.emit(
            "player_joined",
            {"player_id": sid, "username": player_state.username},
            room=self.server.server_code,
            skip_sid=sid
        )
    
    async def remove_player(self, sid: str):
        """Удаляет игрока с сервера"""
        if sid in self.players:
            player_state = self.players.pop(sid)
            
            # Уведомляем других игроков
            await self.sio.emit(
                "player_left",
                {"player_id": sid},
                room=self.server.server_code
            )
    
    async def handle_player_action(self, sid: str, action_data: dict):
        """Обрабатывает действие игрока"""
        if sid not in self.players:
            return
        
        action_type = action_data.get("action")
        
        if action_type == "move":
            await self.handle_player_move(sid, action_data)
        elif action_type == "rotate":
            await self.handle_player_rotate(sid, action_data)
        elif action_type == "interact":
            await self.handle_player_interact(sid, action_data)
        # ... другие действия
    
    async def handle_player_move(self, sid: str, action_data: dict):
        """Обрабатывает движение игрока"""
        player = self.players[sid]
        direction = action_data.get("direction")
        
        # Проверяем, можно ли двигаться в этом направлении
        new_position = self.calculate_new_position(player.position, direction)
        
        if self.server.world.can_move_to(new_position):
            player.position = new_position
            await self.broadcast_player_update(sid, player)
    
    async def handle_player_rotate(self, sid: str, action_data: dict):
        """Обрабатывает поворот игрока"""
        player = self.players[sid]
        rotation = action_data.get("rotation")
        
        player.rotation = rotation
        await self.broadcast_player_update(sid, player)
    
    async def handle_player_interact(self, sid: str, action_data: dict):
        """Обрабатывает взаимодействие игрока с миром"""
        player = self.players[sid]
        block_position = action_data.get("position")
        action = action_data.get("action")  # "break" или "place"
        
        if action == "break":
            self.server.world.break_block(block_position)
        elif action == "place":
            block_type = action_data.get("block_type")
            self.server.world.place_block(block_position, block_type)
        
        # Рассылаем обновление блоков
        await self.broadcast_world_update()
    
    async def broadcast_player_update(self, sid: str, player: PlayerState):
        """Рассылает обновление состояния игрока"""
        player_data = player.to_dict()
        player_data["player_id"] = sid
        
        await self.sio.emit(
            "player_update",
            player_data,
            room=self.server.server_code
        )
    
    def calculate_new_position(self, position: tuple, direction: str) -> tuple:
        """Вычисляет новую позицию на основе направления"""
        x, y, z = position
        
        if direction == "forward":
            if self.players[position].rotation == "N":
                z += 1
            elif self.players[position].rotation == "S":
                z -= 1
            elif self.players[position].rotation == "W":
                x -= 1
            elif self.players[position].rotation == "E":
                x += 1
        elif direction == "backward":
            # Обратное движение
            pass
        # ... другие направления
        
        return (x, y, z)
    
    async def stop(self):
        """Останавливает игровой цикл"""
        self.running = False
        
        # Уведомляем всех игроков о завершении сервера
        await self.sio.emit(
            "server_stopped",
            {"message": "Server is shutting down"},
            room=self.server.server_code
        )
        
        print(f"Server {self.server.server_code} stopped")
    
    def get_player_count(self) -> int:
        """Возвращает количество игроков на сервере"""
        return len(self.players)
    
    def is_empty(self) -> bool:
        """Проверяет, пуст ли сервер"""
        return len(self.players) == 0
    
    def get_server_info(self) -> dict:
        """Возвращает информацию о сервере"""
        return {
            "server_code": self.server.server_code,
            "server_id": self.server.server_id,
            "world_id": self.server.world_id,
            "player_count": self.get_player_count(),
            "tick": self.server.world.tick,
            "status": "active" if self.running else "stopped"
        }