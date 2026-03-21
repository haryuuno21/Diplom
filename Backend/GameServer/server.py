import socketio
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uvicorn
import json

from serverControlService import ServerControlService
from gameDBService import GameDBService
from worldGenerator import WorldGenerator
from worldService import WorldService
from apiModels import CreateServerRequest, CreateWorldRequest, User, WorldListResponse

from database import init_db, init_redis

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db_pool = await init_db()
    app.state.redis_client = await init_redis()
    
    world_gen = WorldGenerator()
    game_db_service = GameDBService(app.state.db_pool, app.state.redis_client)
    world_service = WorldService(game_db_service, world_gen)
    server_control_service = ServerControlService(game_db_service)
    
    app.state.world_service = world_service
    app.state.game_db_service = game_db_service
    app.state.server_control_service = server_control_service
    
    yield
    
    await app.state.db_pool.close()
    await app.state.redis_client.aclose()

app = FastAPI(lifespan=lifespan)

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

### Создание игрового мира
# Пользователь вводит название мира и сид
# Пользователь должен быть авторизован (session_id в куках)
###
@app.post("/api/worlds")
async def create_world(create_world_body: CreateWorldRequest, request: Request):
    """Создание игрового мира"""
    user = app.state.game_db_service.getUserFromSession(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    try:
        world_id = await app.state.world_service.createWorld(create_world_body, user)
        
        return {
            "world_id": world_id,
            "name": create_world_body.world_name,
            "message": "World created successfully"
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create world"
        )
    
@app.get("/api/worlds")
async def list_worlds(request: Request) -> WorldListResponse:
    user = app.state.game_db_service.getUserFromSession(request)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    return await app.state.game_db_service.getWorlds(user)

@app.post("/api/server")
async def create_server(create_server_body: CreateServerRequest, request: Request):
    """Создать сервер для мира"""
    user = app.state.game_db_service.getUserFromSession(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    world_exists = await app.state.game_db_service.checkWorldExists(
        create_server_body.world_id, 
        user.id
    )
    if not world_exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="World not found or you don't have permission"
        )
    server_code = await app.state.server_control_service.createServer(create_server_body.world_id, user)
    return server_code

@sio.event
async def connect(sid, environ):
    """Обработка подключения игрока к игровому серверу"""
    # Извлекаем server_code из query параметров
    query_string = environ.get('QUERY_STRING', '')
    server_code = None
    for param in query_string.split('&'):
        if param.startswith('server_code='):
            server_code = param.split('=', 1)[1]
            break
    
    if not server_code:
        return False
    

    
    server_data = json.loads(server_data_json)
    
    # Получаем сессию пользователя из кук
    session_id = extract_session_id(environ)
    if not session_id:
        return False
    
    user_data = await app.state.redis_client.get(f"session:{session_id}")
    if not user:
        return False
    
    user = json.loads(user_data)
    
    # Добавляем игрока в комнату сервера (автоматически создаёт комнату при первом вызове)
    sio.enter_room(sid, server_code)
    
    # Обновляем список игроков в сервере
    server_data['players'].append(sid)
    server_data['status'] = 'active' if len(server_data['players']) > 0 else 'waiting'
    await app.state.redis_client.setex(
        f"server:{server_code}",
        86400,
        json.dumps(server_data)
    )
    
    # Сохраняем данные сессии
    await sio.save_session(sid, {
        "user_id": user['user_id'],
        "username": user['username'],
        "server_code": server_code,
        "server_id": server_data['server_id']
    })
    
    # Отправляем текущее состояние мира
    world_state_json = await app.state.redis_client.get(f"world:{server_code}")
    if world_state_json:
        await sio.emit("world_state", json.loads(world_state_json), to=sid)
    
    # Уведомляем других игроков
    await sio.emit(
        "player_joined",
        {"player_id": sid, "username": user['username']},
        room=server_code,
        skip_sid=sid  # Не отправляем самому себе
    )
    
    return True

@sio.event
async def disconnect(sid):
    """Обработка отключения игрока"""
    session = await sio.get_session(sid)
    if not session or 'server_code' not in session:
        return
    
    server_code = session['server_code']
    
    # Удаляем игрока из сервера
    server_data_json = await app.state.redis_client.get(f"server:{server_code}")
    if server_data:
        server_data = json.loads(server_data_json)
        if sid in server_data['players']:
            server_data['players'].remove(sid)
            await app.state.redis_client.setex(
                f"server:{server_code}",
                86400,
                json.dumps(server_data)
            )
        
        # Уведомляем других игроков
        await sio.emit(
            "player_left",
            {"player_id": sid},
            room=server_code,
            skip_sid=sid
        )
        
        # Если сервер пустой, запускаем таймер удаления (5 минут)
        if len(server_data['players']) == 0:
            await schedule_server_cleanup(server_code, delay=300)



if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=3010)