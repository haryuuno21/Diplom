# game_server.py
import socketio
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import json
import time
import random
import string

from models import CreateWorldRequest, World_info

# Создаем FastAPI приложение
app = FastAPI()

# Настраиваем CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Создаем Socket.IO сервер
sio = socketio.AsyncServer(
    cors_allowed_origins='*',
    async_mode='asgi'
)

# Объединяем FastAPI и Socket.IO
app.mount("/", socketio.ASGIApp(sio))

# === HTTP ENDPOINTS (управление серверами) ===

### Входные данные:
#       Сессия в куках
#       Название мира
#       Seed (опционально)
#   Действия:
#       Проверяем наличие сессии
#       Получаем пользователя
#       Генерируем мир на основе сида
#       Записываем в бд новый мир (Id, Seed, Name, creator, created_at, last_save -> save)
#       ###
@app.post("/api/worlds")
async def createWorld(create_world_body:CreateWorldRequest, request: Request):
    """Создание игрового мира"""
    user = getUserFromSession(request)
    if not user:
        raise Exception()
    
    
@app.get("/api/words")
async def getWorlds(request: Request):
    """Получить список игровых миров"""

@app.post("/api/server")
async def createServer(request: Request):
    """Создать сервер для мира"""

def getUserFromSession(request:Request):
    session_id = request.cookies.get("session_id")
    if not session_id or not redis.check_session(session_id):
        return None
    else:
        return redis.get_user_data(session_id)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=3010)