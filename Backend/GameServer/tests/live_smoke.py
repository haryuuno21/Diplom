import json
import os
import subprocess
import time
import uuid
from pathlib import Path

import requests
import socketio


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
HOST = os.getenv("SMOKE_HOST", "127.0.0.1")
PORT = int(os.getenv("SMOKE_PORT", "3011"))
BASE_URL = f"http://{HOST}:{PORT}"


def _wait_for_http(session: requests.Session, url: str, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            response = session.get(url, timeout=1)
            if response.ok:
                return response.json()
        except requests.RequestException:
            pass
        time.sleep(0.25)
    raise RuntimeError(f"Backend did not become ready at {url}")


def _wait_for_event(events: list[tuple[str, dict | None]], event_name: str, predicate=None, timeout: float = 10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for name, payload in list(events):
            if name == event_name and (predicate is None or predicate(payload)):
                return payload
        time.sleep(0.05)
    recent = [(name, type(payload).__name__) for name, payload in events[-10:]]
    raise TimeoutError(f"Timed out waiting for {event_name}; recent={recent}")


def _make_client(base_url: str, server_code: str, session: requests.Session, sink: list[tuple[str, dict | None]]):
    client = socketio.Client(logger=False, engineio_logger=False, reconnection=False)

    def push(name: str):
        def _handler(data=None):
            sink.append((name, data))

        return _handler

    for event_name in [
        "connect",
        "disconnect",
        "allInfo",
        "world_state",
        "tick_state",
        "world_tick",
        "state",
        "script_result",
        "chat_message",
        "player_joined",
        "player_left",
    ]:
        client.on(event_name, push(event_name))

    cookie_header = "; ".join(f"{key}={value}" for key, value in session.cookies.get_dict().items())
    client.connect(
        f"{base_url}?server_code={server_code}",
        headers={"Cookie": cookie_header},
        transports=["websocket"],
        wait_timeout=10,
    )
    return client


def main() -> None:
    out_log = ROOT / "uvicorn.out.log"
    err_log = ROOT / "uvicorn.err.log"
    for path in (out_log, err_log):
        path.write_text("", encoding="utf-8")

    with out_log.open("w", encoding="utf-8") as out, err_log.open("w", encoding="utf-8") as err:
        proc = subprocess.Popen(
            [str(PYTHON), "-m", "uvicorn", "server:app", "--host", HOST, "--port", str(PORT)],
            cwd=ROOT,
            stdout=out,
            stderr=err,
        )

    http = requests.Session()
    host_client = None
    guest_client = None
    host_session = None
    guest_session = None
    world_id = None

    try:
        health = _wait_for_http(http, f"{BASE_URL}/api/health")
        run_id = uuid.uuid4().hex[:8]

        users = []
        for prefix in ("host", "guest"):
            session = requests.Session()
            username = f"{prefix}_{run_id}"
            response = session.post(
                f"{BASE_URL}/api/auth/register",
                json={"username": username, "password": "secret123"},
                timeout=10,
            )
            response.raise_for_status()
            users.append({"session": session, "username": username, "user": response.json()["user"]})

        host_session = users[0]["session"]
        guest_session = users[1]["session"]

        world_response = host_session.post(
            f"{BASE_URL}/api/worlds",
            json={"world_name": f"World_{run_id}", "world_seed": f"seed-{run_id}"},
            timeout=10,
        )
        world_response.raise_for_status()
        world = world_response.json()
        world_id = world["world_id"]

        server_response = host_session.post(
            f"{BASE_URL}/api/servers",
            json={"world_id": world_id},
            timeout=10,
        )
        server_response.raise_for_status()
        server_info = server_response.json()
        server_code = server_info["server_code"]

        guest_server_info = guest_session.get(f"{BASE_URL}/api/servers/{server_code}", timeout=10)
        guest_server_info.raise_for_status()

        host_events: list[tuple[str, dict | None]] = []
        guest_events: list[tuple[str, dict | None]] = []
        host_client = _make_client(BASE_URL, server_code, host_session, host_events)
        guest_client = _make_client(BASE_URL, server_code, guest_session, guest_events)

        host_all_info = _wait_for_event(host_events, "allInfo")
        _wait_for_event(guest_events, "allInfo")
        host_tick = _wait_for_event(
            host_events,
            "tick_state",
            lambda payload: payload and len(payload.get("players", [])) == 2,
        )
        _wait_for_event(
            guest_events,
            "tick_state",
            lambda payload: payload and len(payload.get("players", [])) == 2,
        )
        player_joined = _wait_for_event(
            host_events,
            "player_joined",
            lambda payload: payload and payload.get("username") == users[1]["username"],
        )

        before_direction = host_all_info["direction"]
        host_client.emit("turn", "right")
        turned_state = _wait_for_event(
            host_events,
            "state",
            lambda payload: payload and payload.get("direction") != before_direction,
        )

        host_client.emit("exec", 'WHILE(DEPTH("front") = 0)\n    MOVE("forward")\nEND WHILE')
        script_result = _wait_for_event(host_events, "script_result")

        chat_ack = host_client.call("chat_message", {"message": "hello from host"}, timeout=10)
        guest_chat = _wait_for_event(
            guest_events,
            "chat_message",
            lambda payload: payload and payload.get("message") == "hello from host",
        )

        guest_client.disconnect()
        guest_client = None
        player_left = _wait_for_event(
            host_events,
            "player_left",
            lambda payload: payload and payload.get("username") == users[1]["username"],
        )

        summary = {
            "health": health,
            "world_id": world_id,
            "server_code": server_code,
            "players_on_tick": len(host_tick["players"]),
            "player_joined_username": player_joined["username"],
            "turn_changed_direction": before_direction != turned_state["direction"],
            "script_status": script_result["status"],
            "chat_ack_username": chat_ack["username"],
            "chat_message": guest_chat["message"],
            "player_left_username": player_left["username"],
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        if guest_client is not None:
            guest_client.disconnect()
        if host_client is not None:
            host_client.disconnect()
        if world_id is not None and host_session is not None:
            try:
                host_session.delete(f"{BASE_URL}/api/worlds/{world_id}", timeout=10)
            except requests.RequestException:
                pass
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)


if __name__ == "__main__":
    main()
