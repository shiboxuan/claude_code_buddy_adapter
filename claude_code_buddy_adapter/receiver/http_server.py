"""HTTP receiver：4 endpoint，loopback 绑定，异常隔离。

对齐 protocol §3.1（127.0.0.1:8765、X-Buddy-Token 预留、helper exit 0）、
§3.2/§3.3（statusline/hook）、§3.4（/v1/state sanitized）、§3.5（replay）、§3.6（错误体）。
MVP 不返回 hook 控制决策；任何响应（含错误）都是结构化 JSON，不阻断 helper。
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .. import __version__ as ADAPTER_VERSION
from ..claude.normalizer import normalize, normalize_hook, normalize_statusline
from ..claude.textutil import repo_basename
from ..config import AdapterConfig


def _err(code: str, message: str = "", status: int = 400) -> JSONResponse:
    body: dict[str, Any] = {"ok": False, "error": code}
    if message:
        body["message"] = message
    return JSONResponse(status_code=status, content=body)


def _sanitize_session(s) -> dict:
    """§3.4 sanitized：只暴露 session_id/state/repo(basename)/updated_at_ms。"""
    return {
        "session_id": s.session_id,
        "state": s.state.value,
        "repo": repo_basename(s.repo_name) if s.repo_name else None,
        "updated_at_ms": s.updated_at_ms,
    }


async def _read_json(request: Request):
    """解析 JSON body；失败返回 JSONResponse（错误体）。"""
    try:
        data = await request.json()
    except Exception:
        return _err("json_parse_error", status=400)
    if not isinstance(data, dict):
        return _err("json_parse_error", "payload must be a JSON object", 400)
    return data


def create_app(
    store,
    composer,
    config: AdapterConfig,
    bridge=None,
    metrics=None,
    token: Optional[str] = None,
) -> FastAPI:
    app = FastAPI(title="claude-code-buddy-adapter", version=ADAPTER_VERSION)

    def _device_connected() -> bool:
        return bool(bridge is not None and bridge.is_device_connected)

    def _push(prev=None, updated=None) -> None:
        if bridge is None:
            return
        if prev is not None and updated is not None and prev.state != updated.state:
            bridge.handle_state_change(prev, updated)  # alert 边沿 + snapshot
        else:
            bridge.send_full_snapshot()

    # X-Buddy-Token：MVP 无鉴权（仅 loopback），仅当配置 token 时校验（预留位）
    @app.middleware("http")
    async def token_gate(request: Request, call_next):
        if token is not None and request.headers.get("X-Buddy-Token") != token:
            return _err("unauthorized", status=401)
        return await call_next(request)

    # ---- §3.2 POST /v1/claude/statusline ----
    @app.post("/v1/claude/statusline")
    async def statusline(request: Request):
        payload = await _read_json(request)
        if isinstance(payload, JSONResponse):
            return payload
        try:
            ev = normalize_statusline(payload)
            updated = store.apply_event(ev)
            _push(updated=updated)
        except Exception:
            return _err("internal_error", status=500)
        return {"ok": True}

    # ---- §3.3 POST /v1/claude/hook ----
    @app.post("/v1/claude/hook")
    async def hook(request: Request):
        payload = await _read_json(request)
        if isinstance(payload, JSONResponse):
            return payload
        try:
            ev = normalize_hook(payload)
            prev = store.get(ev.session_id) if ev.session_id else None
            updated = store.apply_event(ev)
            _push(prev=prev, updated=updated)
        except Exception:
            return _err("internal_error", status=500)
        return {"ok": True}

    # ---- §3.4 GET /v1/state ----
    @app.get("/v1/state")
    async def get_state():
        try:
            dc = _device_connected()
            focus = store.focus()
            return {
                "ok": True,
                "device_connected": dc,
                "global_state": store.global_state(dc),
                "focus_session_id": focus.session_id if focus else None,
                "sessions": [_sanitize_session(s) for s in store.active()],
                "counts": store.counts(),
                "adapter_version": ADAPTER_VERSION,
            }
        except Exception:
            return _err("internal_error", status=500)

    # ---- metrics（供 dump-state / 运维）----
    @app.get("/v1/metrics")
    async def get_metrics():
        try:
            return {"ok": True, "metrics": metrics.snapshot() if metrics is not None else {}}
        except Exception:
            return _err("internal_error", status=500)

    # ---- §3.5 POST /v1/debug/replay ----
    @app.post("/v1/debug/replay")
    async def replay(request: Request):
        body = await _read_json(request)
        if isinstance(body, JSONResponse):
            return body
        event = body.get("event") if isinstance(body, dict) else None
        if not isinstance(event, dict):
            return _err("missing_required_field", "event required", 400)
        source = event.get("source")
        if source not in ("statusline", "hook"):
            return _err("missing_required_field", "event.source must be statusline|hook", 400)
        raw = event.get("raw") if isinstance(event.get("raw"), dict) else {}
        if event.get("session_id"):
            raw = {**raw, "session_id": event["session_id"]}
        if event.get("hook_event_name"):
            raw = {**raw, "hook_event_name": event["hook_event_name"]}
        try:
            ev = normalize(raw, source, received_at_ms=event.get("received_at_ms"))
            updated = store.apply_event(ev)
            _push(updated=updated)
        except Exception:
            return _err("internal_error", status=500)
        return {"ok": True, "applied_state": updated.state.value}

    # ---- §3.6 错误响应 ----
    @app.exception_handler(StarletteHTTPException)
    async def http_exc_handler(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            return _err("unknown_message_type", "not found", 404)
        return _err("internal_error", str(exc.detail), exc.status_code)

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        return _err("internal_error", status=500)

    return app
