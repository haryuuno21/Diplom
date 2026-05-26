import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
import time
from urllib.parse import parse_qs

import socketio
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from apiModels import (
    AuthResponse,
    CreateServerRequest,
    CreateWorldRequest,
    GameServerResponse,
    MessageResponse,
    SessionUser,
    UpdateProfileRequest,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
    WorldInfo,
    WorldListResponse,
)
from authService import AuthService
from database import init_db, init_redis, initialize_schema
from gameDBService import GameDBService
from serverControlService import ServerControlService
from worldGenerator import WorldGenerator
from worldService import WorldService


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_pool = await init_db()
    redis_client = await init_redis()
    await initialize_schema(db_pool)

    app.state.db_pool = db_pool
    app.state.redis_client = redis_client
    app.state.auth_service = AuthService(db_pool, redis_client)
    app.state.game_db_service = GameDBService(db_pool, redis_client)
    app.state.world_service = WorldService(app.state.game_db_service, WorldGenerator())
    app.state.server_control_service = ServerControlService(app.state.game_db_service)

    yield

    for server_code in list(broadcast_tasks.keys()):
        await _stop_broadcast_task(server_code)
    await app.state.server_control_service.shutdown()
    await db_pool.close()
    await redis_client.aclose()


fastapi_app = FastAPI(
    lifespan=lifespan,
    title="Diplom Multiplayer Backend",
    version="0.2.0",
)

broadcast_tasks: dict[str, asyncio.Task] = {}
active_socket_connections: dict[str, dict[str, str | int]] = {}
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "Frontend"

fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if FRONTEND_DIR.exists():
    fastapi_app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="frontend-assets")
    fastapi_app.mount("/css", StaticFiles(directory=FRONTEND_DIR / "css"), name="frontend-css")
    fastapi_app.mount("/js", StaticFiles(directory=FRONTEND_DIR / "js"), name="frontend-js")
    fastapi_app.mount("/vendor", StaticFiles(directory=FRONTEND_DIR / "vendor"), name="frontend-vendor")


def _user_response(user: SessionUser) -> UserResponse:
    return UserResponse(id=user.id, username=user.username)


async def _require_user(request: Request) -> SessionUser:
    user = await fastapi_app.state.auth_service.get_current_user(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return user


async def _emit_state_bundle(server_code: str, sid: str, state: dict, public_state: dict) -> None:
    await sio.emit("state", state, to=sid)
    await sio.emit("health", state["health"], to=sid)
    await sio.emit("temperature", state["temperature"], to=sid)
    await _emit_to_server_players(server_code, "player_update", public_state)


async def _emit_to_server_players(server_code: str, event_name: str, payload: dict, *, skip_sid: str | None = None) -> None:
    try:
        player_ids = fastapi_app.state.server_control_service.list_player_ids(server_code)
    except ValueError:
        return
    for player_id in player_ids:
        if skip_sid and player_id == skip_sid:
            continue
        await sio.emit(event_name, payload, to=player_id)


def _parse_script_payload(script_text):
    if isinstance(script_text, dict):
        script_name = str(script_text.get("script_name", "")).strip()
        script_body = str(script_text.get("script_content", ""))
        if script_name:
            extension = os.path.splitext(script_name)[1].lower()
            if extension not in (".bas", ".txt"):
                return None, None, f"Unsupported script extension: {extension}"
        return script_name or None, script_body, None
    return None, str(script_text), None


async def _broadcast_server_ticks(server_code: str) -> None:
    last_persist_at = time.monotonic()
    try:
        while True:
            try:
                player_ids = fastapi_app.state.server_control_service.list_player_ids(server_code)
            except ValueError:
                return

            if not player_ids:
                return

            room_snapshot = fastapi_app.state.server_control_service.build_world_payload(server_code)
            for player_id in player_ids:
                tick_payload = fastapi_app.state.server_control_service.build_tick_payload(server_code, player_id)
                await sio.emit("tick_state", tick_payload, to=player_id)
                await sio.emit("state", tick_payload["self"], to=player_id)

            await _emit_to_server_players(server_code, "world_tick", room_snapshot)

            if time.monotonic() - last_persist_at >= 5:
                await fastapi_app.state.server_control_service.persist_server_state(server_code)
                last_persist_at = time.monotonic()

            await asyncio.sleep(0.1)
    except asyncio.CancelledError:
        return


def _ensure_broadcast_task(server_code: str) -> None:
    task = broadcast_tasks.get(server_code)
    if task and not task.done():
        return
    broadcast_tasks[server_code] = asyncio.create_task(_broadcast_server_ticks(server_code))


async def _stop_broadcast_task(server_code: str) -> None:
    task = broadcast_tasks.pop(server_code, None)
    if not task:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@fastapi_app.post("/api/auth/register", response_model=AuthResponse)
@fastapi_app.post("/api/register", response_model=AuthResponse, include_in_schema=False)
async def register(payload: UserRegisterRequest, response: Response) -> AuthResponse:
    user = await fastapi_app.state.auth_service.register_user(payload.username, payload.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User already exists",
        )

    session_id = await fastapi_app.state.auth_service.create_session(user)
    fastapi_app.state.auth_service.set_session_cookie(response, session_id)
    return AuthResponse(message="User registered successfully", user=_user_response(user))


@fastapi_app.post("/api/auth/login", response_model=AuthResponse)
@fastapi_app.post("/api/login", response_model=AuthResponse, include_in_schema=False)
async def login(payload: UserLoginRequest, response: Response) -> AuthResponse:
    user = await fastapi_app.state.auth_service.authenticate_user(payload.username, payload.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    session_id = await fastapi_app.state.auth_service.create_session(user)
    fastapi_app.state.auth_service.set_session_cookie(response, session_id)
    return AuthResponse(message="Login successful", user=_user_response(user))


@fastapi_app.post("/api/auth/logout", response_model=MessageResponse)
@fastapi_app.post("/api/logout", response_model=MessageResponse, include_in_schema=False)
async def logout(request: Request, response: Response) -> MessageResponse:
    session_id = request.cookies.get("session_id")
    if session_id:
        await fastapi_app.state.auth_service.delete_session(session_id)
    fastapi_app.state.auth_service.clear_session_cookie(response)
    return MessageResponse(message="Logged out successfully")


@fastapi_app.get("/api/auth/me", response_model=UserResponse)
async def me(request: Request) -> UserResponse:
    user = await _require_user(request)
    return _user_response(user)


@fastapi_app.put("/api/profile", response_model=AuthResponse)
async def update_profile(payload: UpdateProfileRequest, request: Request, response: Response) -> AuthResponse:
    user = await _require_user(request)
    try:
        updated_user = await fastapi_app.state.auth_service.update_user(
            user,
            username=payload.username,
            password=payload.password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if not updated_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    session_id = await fastapi_app.state.auth_service.create_session(updated_user)
    fastapi_app.state.auth_service.set_session_cookie(response, session_id)
    return AuthResponse(message="Profile updated successfully", user=_user_response(updated_user))


@fastapi_app.post("/api/worlds", response_model=WorldInfo)
async def create_world(payload: CreateWorldRequest, request: Request) -> WorldInfo:
    user = await _require_user(request)
    try:
        return await fastapi_app.state.world_service.create_world(payload, user)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@fastapi_app.get("/api/worlds", response_model=WorldListResponse)
async def list_worlds(request: Request) -> WorldListResponse:
    user = await _require_user(request)
    return await fastapi_app.state.game_db_service.get_worlds(user)


@fastapi_app.delete("/api/worlds/{world_id}", response_model=MessageResponse)
async def delete_world(world_id: int, request: Request) -> MessageResponse:
    user = await _require_user(request)
    world = await fastapi_app.state.game_db_service.get_world_for_user(world_id, user.id)
    if not world:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="World not found")
    await fastapi_app.state.server_control_service.stop_world_servers(world_id)
    deleted = await fastapi_app.state.world_service.delete_world(world_id, user)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="World not found")
    return MessageResponse(message="World deleted successfully")


@fastapi_app.post("/api/servers", response_model=GameServerResponse)
@fastapi_app.post("/api/server", response_model=GameServerResponse, include_in_schema=False)
async def create_server(payload: CreateServerRequest, request: Request) -> GameServerResponse:
    user = await _require_user(request)
    try:
        return await fastapi_app.state.server_control_service.create_server(payload.world_id, user)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@fastapi_app.get("/api/servers/{server_code}", response_model=GameServerResponse)
async def get_server(server_code: str, request: Request) -> GameServerResponse:
    await _require_user(request)
    info = await fastapi_app.state.server_control_service.get_server_info(server_code)
    if not info:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")
    return info


@fastapi_app.get("/api/health", response_model=MessageResponse)
async def health_check() -> MessageResponse:
    return MessageResponse(message="ok")


if FRONTEND_DIR.exists():
    @fastapi_app.get("/", include_in_schema=False)
    async def frontend_root() -> RedirectResponse:
        return RedirectResponse(url="/login.html")


    @fastapi_app.get("/login.html", include_in_schema=False)
    async def login_page() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "login.html")


    @fastapi_app.get("/index.html", include_in_schema=False)
    async def lobby_page() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")


    @fastapi_app.get("/game.html", include_in_schema=False)
    async def game_page() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "game.html")


sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins=[])
app = socketio.ASGIApp(sio, other_asgi_app=fastapi_app, socketio_path="socket.io")


@sio.event
async def connect(sid, environ, auth):
    query = parse_qs(environ.get("QUERY_STRING", ""))
    server_code = query.get("server_code", [None])[0]
    if not server_code:
        return False

    session_id = fastapi_app.state.auth_service.extract_session_id_from_cookie_header(
        environ.get("HTTP_COOKIE")
    )
    if not session_id:
        return False

    user = await fastapi_app.state.auth_service.get_session(session_id)
    if not user:
        return False

    try:
        payload = await fastapi_app.state.server_control_service.add_player(server_code, sid, user)
    except ValueError:
        return False

    await sio.enter_room(sid, server_code)
    await sio.save_session(
        sid,
        {"server_code": server_code, "user_id": user.id, "username": user.username},
    )
    active_socket_connections[sid] = {
        "server_code": server_code,
        "user_id": user.id,
        "username": user.username,
    }
    if "self" in payload:
        await sio.emit("allInfo", payload["self"], to=sid)
        await sio.emit("state", payload["self"], to=sid)
    await sio.emit("world_state", payload, to=sid)
    _ensure_broadcast_task(server_code)
    await _emit_to_server_players(
        server_code,
        "player_joined",
        payload.get("self", {"player_id": sid, "username": user.username}),
        skip_sid=sid,
    )
    return True


@sio.event
async def disconnect(sid):
    fallback_session = active_socket_connections.pop(sid, None)
    try:
        session = await sio.get_session(sid)
    except KeyError:
        session = fallback_session or {}

    server_code = session.get("server_code")
    if not server_code:
        return

    await fastapi_app.state.server_control_service.remove_player(server_code, sid)
    await _emit_to_server_players(
        server_code,
        "player_left",
        {
            "player_id": sid,
            "user_id": session.get("user_id"),
            "username": session.get("username"),
        },
        skip_sid=sid,
    )


@sio.event
async def move(sid, direction):
    try:
        session = await sio.get_session(sid)
    except KeyError:
        return
    server_code = session.get("server_code")
    if not server_code:
        return

    try:
        state, public_state = await fastapi_app.state.server_control_service.move_player(
            server_code,
            sid,
            str(direction).lower(),
        )
    except ValueError as exc:
        await sio.emit("message", str(exc), to=sid)
        return

    await _emit_state_bundle(server_code, sid, state, public_state)


@sio.event
async def turn(sid, direction):
    try:
        session = await sio.get_session(sid)
    except KeyError:
        return
    server_code = session.get("server_code")
    if not server_code:
        return

    try:
        state, public_state = await fastapi_app.state.server_control_service.turn_player(
            server_code,
            sid,
            str(direction).lower(),
        )
    except ValueError as exc:
        await sio.emit("message", str(exc), to=sid)
        return

    await _emit_state_bundle(server_code, sid, state, public_state)


@sio.event
async def heal(sid):
    try:
        session = await sio.get_session(sid)
    except KeyError:
        return
    server_code = session.get("server_code")
    if not server_code:
        return

    state, public_state = await fastapi_app.state.server_control_service.heal_player(server_code, sid)
    await _emit_state_bundle(server_code, sid, state, public_state)


@sio.event
async def restart(sid):
    try:
        session = await sio.get_session(sid)
    except KeyError:
        return
    server_code = session.get("server_code")
    if not server_code:
        return

    state, public_state = await fastapi_app.state.server_control_service.restart_player(server_code, sid)
    await _emit_state_bundle(server_code, sid, state, public_state)


@sio.event
async def exec(sid, script_text):
    try:
        session = await sio.get_session(sid)
    except KeyError:
        return
    server_code = session.get("server_code")
    if not server_code:
        return

    async def on_state_change(state: dict, public_state: dict):
        await _emit_state_bundle(server_code, sid, state, public_state)

    script_name, script_source, script_error = _parse_script_payload(script_text)
    if script_error:
        await sio.emit("basic_error", script_error, to=sid)
        return
    if script_text is not None:
        await fastapi_app.state.server_control_service.save_player_script_state(
            server_code,
            sid,
            {"script_name": script_name, "script_content": script_source},
        )

    try:
        state, public_state, result = await fastapi_app.state.server_control_service.execute_script(
            server_code,
            sid,
            script_source,
            on_state_change=on_state_change,
        )
    except ValueError as exc:
        error_text = str(exc)
        await sio.emit("runtime_error", error_text, to=sid)
        await sio.emit(
            "script_result",
            {"status": "error", "logs": [], "error": error_text},
            to=sid,
        )
        return

    if state and public_state:
        await _emit_state_bundle(server_code, sid, state, public_state)

    for log_line in result["logs"]:
        await sio.emit("message", log_line, to=sid)

    if result["success"]:
        await sio.emit("script_result", {"status": "success", "logs": result["logs"]}, to=sid)
    else:
        error_text = result["error"] or "Unknown BASIC execution error"
        if "syntax" in error_text.lower():
            await sio.emit("basic_error", error_text, to=sid)
        else:
            await sio.emit("runtime_error", error_text, to=sid)
        await sio.emit(
            "script_result",
            {"status": "error", "logs": result["logs"], "error": error_text},
            to=sid,
        )


@sio.event
async def execute_script(sid, script_text):
    await exec(sid, script_text)


@sio.event
async def save_script_state(sid, script_text):
    try:
        session = await sio.get_session(sid)
    except KeyError:
        return
    server_code = session.get("server_code")
    if not server_code:
        return

    script_name, script_source, script_error = _parse_script_payload(script_text)
    if script_error:
        await sio.emit("basic_error", script_error, to=sid)
        return

    await fastapi_app.state.server_control_service.save_player_script_state(
        server_code,
        sid,
        {"script_name": script_name, "script_content": script_source},
    )


@sio.event
async def stop_script(sid):
    try:
        session = await sio.get_session(sid)
    except KeyError:
        return
    server_code = session.get("server_code")
    if not server_code:
        return

    result = await fastapi_app.state.server_control_service.stop_script(server_code, sid)
    if not result:
        await sio.emit(
            "script_result",
            {"status": "error", "logs": [], "error": "Нет запущенного скрипта для остановки"},
            to=sid,
        )
        return

    state, public_state = result
    await _emit_state_bundle(server_code, sid, state, public_state)
    await sio.emit(
        "script_result",
        {"status": "stopped", "logs": [], "error": "Скрипт остановлен игроком"},
        to=sid,
    )


async def _handle_chat_message(sid, payload):
    try:
        session = await sio.get_session(sid)
    except KeyError:
        return None

    server_code = session.get("server_code")
    if not server_code:
        return None

    message = await fastapi_app.state.server_control_service.add_chat_message(server_code, sid, payload)
    await _emit_to_server_players(server_code, "chat_message", message)
    return message


@sio.event
async def chat_message(sid, payload):
    return await _handle_chat_message(sid, payload)


@sio.event
async def chat(sid, payload):
    return await _handle_chat_message(sid, payload)


@sio.event
async def player_state(sid, data):
    try:
        session = await sio.get_session(sid)
    except KeyError:
        return

    server_code = session.get("server_code")
    if not server_code:
        return

    updated = await fastapi_app.state.server_control_service.update_player_state(server_code, sid, data)
    if updated is None:
        return

    await _emit_to_server_players(server_code, "player_state", updated, skip_sid=sid)


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=3010, reload=True)
