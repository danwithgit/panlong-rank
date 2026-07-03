from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import Settings, get_settings
from app.models import BoardDetailResponse, DashboardResponse, Timeframe
from app.services.calendar import get_trading_status
from app.services.provider import MarketDataProvider, get_provider
from app.services.rankings import (
    build_board_rankings,
    build_leader_rankings,
    build_stock_rankings,
    find_board,
    timeframe_label,
)

app = FastAPI(title="Panlong Rank", version="0.1.0")
app.mount("/static", StaticFiles(directory="app/static"), name="static")


def market_provider(settings: Settings = Depends(get_settings)) -> MarketDataProvider:
    return get_provider(settings)


@app.get("/")
def index_page():
    return FileResponse("app/static/index.html")


@app.get("/api/health")
def health(settings: Settings = Depends(get_settings)):
    return {"status": "ok", "app": settings.app_name, "provider": settings.data_provider}


@app.get("/api/index")
def index_quote(
    settings: Settings = Depends(get_settings),
    provider: MarketDataProvider = Depends(market_provider),
):
    status = get_trading_status(settings)
    return provider.snapshot(status).index


@app.get("/api/dashboard", response_model=DashboardResponse)
def dashboard(
    timeframe: Timeframe = Timeframe.realtime,
    limit: int = Query(default=10, ge=1, le=50),
    settings: Settings = Depends(get_settings),
    provider: MarketDataProvider = Depends(market_provider),
):
    snapshot = provider.snapshot(get_trading_status(settings))
    return DashboardResponse(
        timeframe=timeframe,
        timeframe_label=timeframe_label(timeframe),
        index=snapshot.index,
        trading_status=snapshot.trading_status,
        board_rankings=build_board_rankings(snapshot, timeframe, limit),
        leader_rankings=build_leader_rankings(snapshot, timeframe, limit),
    )


@app.get("/api/rankings")
def rankings(
    timeframe: Timeframe = Timeframe.realtime,
    limit: int = Query(default=10, ge=1, le=50),
    settings: Settings = Depends(get_settings),
    provider: MarketDataProvider = Depends(market_provider),
):
    snapshot = provider.snapshot(get_trading_status(settings))
    return {
        "timeframe": timeframe,
        "timeframe_label": timeframe_label(timeframe),
        "board_rankings": build_board_rankings(snapshot, timeframe, limit),
        "leader_rankings": build_leader_rankings(snapshot, timeframe, limit),
        "stock_rankings": build_stock_rankings(snapshot, timeframe, limit),
    }


@app.get("/api/boards/{board_code}", response_model=BoardDetailResponse)
def board_detail(
    board_code: str,
    timeframe: Timeframe = Timeframe.realtime,
    limit: int = Query(default=10, ge=1, le=50),
    settings: Settings = Depends(get_settings),
    provider: MarketDataProvider = Depends(market_provider),
):
    snapshot = provider.snapshot(get_trading_status(settings))
    board = find_board(snapshot, board_code)
    if board is None:
        raise HTTPException(status_code=404, detail="Board not found")
    return BoardDetailResponse(
        timeframe=timeframe,
        timeframe_label=timeframe_label(timeframe),
        board=board,
        stock_rankings=build_stock_rankings(snapshot, timeframe, limit, board_code=board_code),
    )


@app.get("/api/leaders")
def leaders(
    timeframe: Timeframe = Timeframe.realtime,
    limit: int = Query(default=10, ge=1, le=50),
    settings: Settings = Depends(get_settings),
    provider: MarketDataProvider = Depends(market_provider),
):
    snapshot = provider.snapshot(get_trading_status(settings))
    return {
        "timeframe": timeframe,
        "timeframe_label": timeframe_label(timeframe),
        "leader_rankings": build_leader_rankings(snapshot, timeframe, limit),
    }
