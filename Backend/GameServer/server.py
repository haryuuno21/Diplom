# game_server.py
import socketio
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import json
import time
import random
import string

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

# Хранилище данных (в реальности можно использовать Redis)
active_servers = {}  # {server_code: server_data}
user_sessions = {}   # {session_id: user_data}

# === HTTP ENDPOINTS (управление серверами) ===

@app.post("/api/servers")
async def create_server(request: Request):
    """Создание нового игрового сервера"""
    # Получаем session_id из cookie
    session_id = request.cookies.get("session_id")
    if not session_id or session_id not in user_sessions:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    user_data = user_sessions[session_id]
    
    # Генерируем уникальный код сервера
    server_code = generate_server_code()
    
    # Создаем сервер
    server_data = {
        "server_code": server_code,
        "host_user_id": user_data["user_id"],
        "host_username": user_data["username"],
        "players": [],  # SID игроков
        "world_state": {"blocks": {}, "tick": 0},
        "created_at": time.time(),
        "status": "waiting"  # ожидает подключений
    }
    
    active_servers[server_code] = server_data
    
    return {"server_code": server_code, "message": "Server created successfully"}

@app.get("/api/servers")
async def list_servers(request: Request):
    """Список доступных серверов"""
    session_id = request.cookies.get("session_id")
    if not session_id or session_id not in user_sessions:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    servers_list = [
        {
            "server_code": code,
            "host_username": data["host_username"],
            "player_count": len(data["players"]),
            "status": data["status"]
        }
        for code, data in active_servers.items()
    ]
    
    return {"servers": servers_list}

# === SOCKET.IO EVENTS (игровая логика) ===

@sio.event
async def connect(sid, environ):
    """Проверка при WebSocket подключении"""
    # Получаем session_id из cookie
    cookies = environ.get('HTTP_COOKIE', '')
    session_id = extract_session_id_from_cookies(cookies)
    
    if not session_id or session_id not in user_sessions:
        return False
    
    # Получаем server_code из query параметров
    query_string = environ.get('QUERY_STRING', '')
    server_code = extract_server_code_from_query(query_string)
    
    if not server_code or server_code not in active_servers:
        return False
    
    # Добавляем игрока на сервер
    server = active_servers[server_code]
    server["players"].append(sid)
    server["status"] = "active"
    
    # Сохраняем данные сессии
    await sio.save_session(sid, {
        "user_id": user_sessions[session_id]["user_id"],
        "username": user_sessions[session_id]["username"],
        "server_code": server_code
    })
    
    print(f"Player {user_sessions[session_id]['username']} connected to server {server_code}")
    return True

@sio.event
async def disconnect(sid):
    """Обработка отключения игрока"""
    session = await sio.get_session(sid)
    if session and "server_code" in session:
        server_code = session["server_code"]
        if server_code in active_servers:
            server = active_servers[server_code]
            if sid in server["players"]:
                server["players"].remove(sid)
                print(f"Player disconnected from server {server_code}")
                
                # Удаляем пустой сервер
                if len(server["players"]) == 0:
                    del active_servers[server_code]
                    print(f"Server {server_code} deleted")

@sio.event
async def game_action(sid, data):
    """Обработка игровых действий"""
    session = await sio.get_session(sid)
    if not session:
        return
    
    server_code = session["server_code"]
    server = active_servers.get(server_code)
    if not server:
        return
    
    # Обновляем состояние мира
    action = data.get("action")
    # ... ваша игровая логика ...
    
    # Рассылаем обновление всем игрокам на сервере
    for player_sid in server["players"]:
        await sio.emit("world_update", server["world_state"], to=player_sid)

# === Вспомогательные функции ===

def generate_server_code():
    """Генерирует уникальный код сервера"""
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if code not in active_servers:
            return code

def generate_session_id():
    """Генерирует ID сессии"""
    return ''.join(random.choices(string.ascii_letters + string.digits, k=32))

def extract_session_id_from_cookies(cookies_str):
    """Извлекает session_id из cookie строки"""
    if not cookies_str:
        return None
    for cookie in cookies_str.split(';'):
        parts = cookie.strip().split('=', 1)
        if len(parts) == 2 and parts[0] == 'session_id':
            return parts[1]
    return None

def extract_server_code_from_query(query_string):
    """Извлекает server_code из query строки"""
    if not query_string:
        return None
    for param in query_string.split('&'):
        if param.startswith('server_code='):
            return param.split('=', 1)[1]
    return None

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=3010)