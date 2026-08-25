"""FastAPI dashboard API for the paper/demo runtime."""

from __future__ import annotations

import asyncio
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .demo_runtime import DemoRuntime
from .controls import ResumeDenied
from .env import load_local_env
from .market_data import MarketDataError


class ReasonRequest(BaseModel):
    reason: str = Field(default="Operator action", max_length=240)


class ResetRequest(BaseModel):
    owner_confirmed: bool = False


class DemoOrderRequest(BaseModel):
    instrument_id: str = Field(min_length=1, max_length=20)
    side: str = Field(pattern="^(BUY|SELL)$")
    notional: Decimal = Field(gt=Decimal("0"), max_digits=12, decimal_places=4)
    idempotency_key: str | None = Field(default=None, max_length=160)


class WatchlistRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)


def create_app(runtime: DemoRuntime | None = None) -> FastAPI:
    load_local_env()
    runtime = runtime or DemoRuntime(os.getenv("TRADEFORGE_DEMO_DB", "artifacts/tradeforge-demo.db"))
    app = FastAPI(title="TradeForge Dashboard API", version="0.2.0", docs_url="/api/docs", redoc_url=None)
    app.state.runtime = runtime
    origins = os.getenv("TRADEFORGE_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in origins if origin.strip()],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    def require_owner(
        request: Request,
        authorization: str | None = Header(default=None),
        x_tradeforge_owner_token: str | None = Header(default=None),
    ) -> None:
        """Fail closed for production deployments without a configured owner token."""
        configured = os.getenv("TRADEFORGE_DASHBOARD_TOKEN")
        production = os.getenv("TRADEFORGE_ENV", "demo").lower() == "production"
        if not production and not configured:
            return
        presented = x_tradeforge_owner_token or (authorization.removeprefix("Bearer ").strip() if authorization else None)
        if not configured or presented != configured:
            raise HTTPException(status_code=401, detail={"code": "OWNER_AUTHENTICATION_REQUIRED"})

    @app.get("/api/v1/dashboard")
    def dashboard(_: None = Depends(require_owner)):
        return runtime.dashboard()

    @app.get("/api/v1/health")
    def health(_: None = Depends(require_owner)):
        return {"status": runtime.dashboard()["system"], "services": runtime.dashboard()["health"]}

    @app.post("/api/v1/control/pause")
    def pause(request: ReasonRequest, _: None = Depends(require_owner)):
        return runtime.pause(request.reason)

    @app.post("/api/v1/control/resume")
    def resume(_: None = Depends(require_owner)):
        try:
            return runtime.resume()
        except ResumeDenied as exc:
            raise HTTPException(status_code=409, detail={"code": "RESUME_DENIED", "failures": list(exc.failures)}) from exc

    @app.post("/api/v1/control/stop-everything")
    def stop_everything(request: ReasonRequest, _: None = Depends(require_owner)):
        return runtime.stop_everything(request.reason)

    @app.post("/api/v1/auto/start")
    def start_auto(_: None = Depends(require_owner)):
        try:
            return runtime.start_auto()
        except ResumeDenied as exc:
            raise HTTPException(status_code=409, detail={"code": "AUTO_START_DENIED", "failures": list(exc.failures)}) from exc

    @app.post("/api/v1/auto/pause")
    def pause_auto(request: ReasonRequest, _: None = Depends(require_owner)):
        return runtime.pause_auto(request.reason)

    @app.post("/api/v1/session/close")
    def close_session(_: None = Depends(require_owner)):
        try:
            return runtime.end_session()
        except ResumeDenied as exc:
            raise HTTPException(status_code=409, detail={"code": "SESSION_CLOSE_DENIED", "failures": list(exc.failures)}) from exc

    @app.post("/api/v1/notifications/acknowledge")
    def acknowledge_notifications(_: None = Depends(require_owner)):
        return runtime.acknowledge_notifications()

    @app.post("/api/v1/control/reset-kill-switch")
    def reset_kill_switch(request: ResetRequest, _: None = Depends(require_owner)):
        try:
            return runtime.reset_kill_switch(request.owner_confirmed)
        except (PermissionError, ResumeDenied) as exc:
            failures = list(exc.failures) if isinstance(exc, ResumeDenied) else [str(exc)]
            raise HTTPException(status_code=409, detail={"code": "KILL_SWITCH_RESET_DENIED", "failures": failures}) from exc

    @app.post("/api/v1/control/system-check")
    def system_check(_: None = Depends(require_owner)):
        return runtime.system_check()

    @app.post("/api/v1/control/reconcile")
    def reconcile(_: None = Depends(require_owner)):
        return runtime.reconcile()

    @app.post("/api/v1/demo/scenarios/{scenario}")
    def simulate(scenario: str, _: None = Depends(require_owner)):
        try:
            return runtime.simulate(scenario)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail={"code": "UNKNOWN_SCENARIO", "message": str(exc)}) from exc

    @app.post("/api/v1/demo/orders")
    def place_demo_order(request: DemoOrderRequest, _: None = Depends(require_owner)):
        try:
            return runtime.place_order(request.instrument_id, request.side, request.notional, request.idempotency_key)
        except (ValueError, InvalidOperation) as exc:
            raise HTTPException(status_code=400, detail={"code": "ORDER_REQUEST_INVALID", "message": str(exc)}) from exc

    @app.get("/api/v1/universe/search")
    def search_universe(q: str = "", _: None = Depends(require_owner)):
        return runtime.search_universe(q)

    @app.post("/api/v1/universe/watchlist")
    def add_watchlist(request: WatchlistRequest, _: None = Depends(require_owner)):
        try:
            return runtime.add_to_watchlist(request.symbol)
        except (ValueError, MarketDataError) as exc:
            raise HTTPException(status_code=400, detail={"code": "WATCHLIST_ADD_FAILED", "message": str(exc)}) from exc

    @app.websocket("/api/v1/ws")
    async def stream(websocket: WebSocket):
        configured = os.getenv("TRADEFORGE_DASHBOARD_TOKEN")
        production = os.getenv("TRADEFORGE_ENV", "demo").lower() == "production"
        if production and (not configured or websocket.query_params.get("token") != configured):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        try:
            while True:
                await websocket.send_json(runtime.dashboard())
                await asyncio.sleep(1)
        except (WebSocketDisconnect, RuntimeError):
            return

    frontend_dist = Path(__file__).resolve().parents[2] / "web" / "dist"
    if frontend_dist.exists():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
    else:
        @app.get("/")
        def root():
            return {"service": "TradeForge", "dashboard": "not built", "api": "/api/v1/dashboard", "mode": "PAPER"}

    return app


app = create_app()
