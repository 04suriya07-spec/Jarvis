"""FastAPI authentication helpers."""

from __future__ import annotations

from fastapi import Header, HTTPException, Request, WebSocket

from core.config import get_config

cfg = get_config()


def auth_required() -> bool:
    return bool(cfg.javris_auth_enabled and cfg.javris_api_token)


def _valid_authorization(value: str | None) -> bool:
    if not auth_required():
        return True
    if not value or not value.lower().startswith("bearer "):
        return False
    return value.split(" ", 1)[1].strip() == cfg.javris_api_token


async def require_api_auth(authorization: str | None = Header(default=None)) -> None:
    if not _valid_authorization(authorization):
        raise HTTPException(status_code=401, detail="Missing or invalid API token")


def websocket_authorized(websocket: WebSocket) -> bool:
    if not auth_required():
        return True
    auth = websocket.headers.get("authorization")
    if _valid_authorization(auth):
        return True
    token = websocket.query_params.get("token", "")
    return bool(token and token == cfg.javris_api_token)


def client_is_local(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in {"127.0.0.1", "::1", "localhost"}
