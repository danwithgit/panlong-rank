from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.session import SessionLocal, get_db, init_db
from app.db.tables import JobLog
from app.models import BoardDetailResponse, DashboardResponse, Timeframe
from app.services.cache import get_cache
from app.services.calendar import get_trading_status
from app.services.collector import collect_market_snapshot
from app.services.periods import period_for, period_options
from app.services.ranking_service import (
    build_board_detail_from_db,
    build_dashboard_from_db,
    rank_query,
    snapshot_for_timeframe_with_settings,
)
from app.services.scheduler import start_scheduler, stop_scheduler
from app.services.snapshot_store import has_snapshots, latest_snapshot


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_db()
    if settings.collect_on_startup:
        db = SessionLocal()
        try:
            if not has_snapshots(db):
                collect_market_snapshot(db, settings, force=True)
        except Exception:
            pass
        finally:
            db.close()
    start_scheduler(settings)
    yield
    stop_scheduler()


app = FastAPI(title="Panlong Rank", version="0.2.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/")
def index_page():
    return FileResponse("app/static/index.html")


@app.get("/api/health")
def health(settings: Settings = Depends(get_settings), db: Session = Depends(get_db)):
    latest = latest_snapshot(db, get_trading_status(settings))
    return {
        "status": "ok",
        "app": settings.app_name,
        "provider": settings.data_provider,
        "database_url": _safe_database_url(settings.database_url),
        "has_snapshots": has_snapshots(db),
        "scheduler_enabled": settings.scheduler_enabled,
        "cache": "redis" if settings.redis_url else "memory",
        "latest_data_source": latest.data_source if latest else None,
    }


@app.post("/api/admin/collect")
def collect_now(
    force: bool = Query(default=False),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
):
    snapshot = collect_market_snapshot(db, settings, force=force)
    return {
        "status": "ok",
        "trade_date": snapshot.trading_status.trade_date,
        "updated_at": snapshot.index.updated_at,
        "boards": len(snapshot.boards),
        "stocks": len(snapshot.stocks),
    }


@app.get("/api/admin/job-logs")
def job_logs(limit: int = Query(default=20, ge=1, le=200), db: Session = Depends(get_db)):
    rows = db.scalars(select(JobLog).order_by(JobLog.started_at.desc(), JobLog.id.desc()).limit(limit)).all()
    return {
        "items": [
            {
                "id": row.id,
                "job_name": row.job_name,
                "status": row.status,
                "started_at": row.started_at,
                "finished_at": row.finished_at,
                "error_message": row.error_message,
                "rows_count": row.rows_count,
            }
            for row in rows
        ]
    }


@app.get("/api/periods")
def periods():
    return {"items": period_options()}


@app.get("/api/index/shanghai")
def shanghai_index(settings: Settings = Depends(get_settings), db: Session = Depends(get_db)):
    status = get_trading_status(settings)
    snapshot = snapshot_for_timeframe_with_settings(db, status, settings, Timeframe.realtime)
    if snapshot is None:
        raise HTTPException(status_code=503, detail="行情数据缺失，采集服务繁忙或上游数据源不可用")
    return {
        "index_code": snapshot.index.code,
        "index_name": snapshot.index.name,
        "current_price": snapshot.index.current,
        "change_value": snapshot.index.change,
        "change_percent": snapshot.index.change_percent,
        "volume": snapshot.index.volume,
        "turnover": snapshot.index.amount,
        "updated_at": snapshot.index.updated_at,
        "is_trading_day": snapshot.trading_status.is_trade_day,
        "is_realtime_data": snapshot.trading_status.is_trade_day,
        "data_source": snapshot.data_source,
        "is_sample_data": _is_sample_source(snapshot.data_source),
        "display_trade_date": snapshot.trading_status.trade_date if snapshot.trading_status.is_trade_day else snapshot.trading_status.last_trade_date,
        "trading_status": snapshot.trading_status,
    }


@app.get("/api/index")
def index_quote(settings: Settings = Depends(get_settings), db: Session = Depends(get_db)):
    status = get_trading_status(settings)
    snapshot = snapshot_for_timeframe_with_settings(db, status, settings, Timeframe.realtime)
    if snapshot is None:
        raise HTTPException(status_code=503, detail="行情数据缺失，采集服务繁忙或上游数据源不可用")
    return snapshot.index


@app.get("/api/dashboard", response_model=DashboardResponse)
def dashboard(
    timeframe: Timeframe = Timeframe.realtime,
    limit: int = Query(default=10, ge=1, le=50),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
):
    cache = get_cache(settings)
    status = get_trading_status(settings)
    latest = latest_snapshot(db, status)
    latest_stamp = latest.index.updated_at.isoformat() if latest else "-"
    cache_key = f"dashboard:{timeframe.value}:{limit}:{status.trade_date}:{status.last_trade_date}:{latest_stamp}"
    cached = cache.get_json(cache_key)
    if cached:
        return cached
    try:
        snapshot, board_rankings, leader_rankings = build_dashboard_from_db(db, status, settings, timeframe, limit)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"dashboard unavailable: {exc}") from exc
    response = DashboardResponse(
        timeframe=timeframe,
        timeframe_label=_timeframe_label(timeframe),
        index=snapshot.index,
        trading_status=snapshot.trading_status,
        data_source=snapshot.data_source,
        is_sample_data=_is_sample_source(snapshot.data_source),
        board_rankings=board_rankings,
        leader_rankings=leader_rankings,
    )
    payload = response.model_dump(mode="json")
    cache.set_json(cache_key, payload, settings.cache_ttl_seconds)
    return payload


@app.get("/api/rank/sectors")
def rank_sectors(
    period: str = "realtime",
    type: str = Query(default="turnover", pattern="^(turnover|volume|fund|change)$"),
    limit: int = Query(default=10, ge=1, le=50),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
):
    return _rank_response(db, settings, _parse_period(period), type, "sector", limit)


@app.get("/api/rank/stocks")
def rank_stocks(
    sector_code: str = Query(...),
    period: str = "realtime",
    type: str = Query(default="turnover", pattern="^(turnover|volume|fund|change)$"),
    limit: int = Query(default=10, ge=1, le=50),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
):
    return _rank_response(db, settings, _parse_period(period), type, "stock", limit, sector_code=sector_code)


@app.get("/api/rank/leaders")
def rank_leaders(
    period: str = "realtime",
    type: str = Query(default="fund", pattern="^(turnover|volume|fund|change)$"),
    limit: int = Query(default=10, ge=1, le=50),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
):
    return _rank_response(db, settings, _parse_period(period), type, "leader_stock", limit)


@app.get("/api/rankings")
def rankings(
    timeframe: Timeframe = Timeframe.realtime,
    limit: int = Query(default=10, ge=1, le=50),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
):
    status = get_trading_status(settings)
    snapshot, board_rankings, leader_rankings = build_dashboard_from_db(db, status, settings, timeframe, limit)
    stock_block = rank_query(db, status, settings, timeframe, "turnover", "stock", limit)
    return {
        "timeframe": timeframe,
        "timeframe_label": _timeframe_label(timeframe),
        "index": snapshot.index,
        "board_rankings": board_rankings,
        "leader_rankings": leader_rankings,
        "stock_rankings": [stock_block],
    }


@app.get("/api/boards/{board_code}", response_model=BoardDetailResponse)
def board_detail(
    board_code: str,
    timeframe: Timeframe = Timeframe.realtime,
    limit: int = Query(default=10, ge=1, le=50),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
):
    status = get_trading_status(settings)
    board, stock_rankings, snapshot = build_board_detail_from_db(db, status, settings, timeframe, limit, board_code)
    if board is None:
        raise HTTPException(status_code=404, detail="Board not found")
    return BoardDetailResponse(
        timeframe=timeframe,
        timeframe_label=_timeframe_label(timeframe),
        data_source=snapshot.data_source,
        is_sample_data=_is_sample_source(snapshot.data_source),
        board=board,
        stock_rankings=stock_rankings,
    )


@app.get("/api/leaders")
def leaders(
    timeframe: Timeframe = Timeframe.realtime,
    limit: int = Query(default=10, ge=1, le=50),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
):
    status = get_trading_status(settings)
    block = rank_query(db, status, settings, timeframe, "fund", "leader_stock", limit)
    return {
        "timeframe": timeframe,
        "timeframe_label": _timeframe_label(timeframe),
        "leader_rankings": [block],
    }


def _rank_response(
    db: Session,
    settings: Settings,
    period: Timeframe,
    rank_type: str,
    target_type: str,
    limit: int,
    sector_code: Optional[str] = None,
):
    status = get_trading_status(settings)
    cache = get_cache(settings)
    latest = latest_snapshot(db, status)
    latest_stamp = latest.index.updated_at.isoformat() if latest else "-"
    cache_key = (
        f"rank:{target_type}:{rank_type}:{period.value}:{sector_code or '-'}:"
        f"{limit}:{status.trade_date}:{status.last_trade_date}:{latest_stamp}"
    )
    cached = cache.get_json(cache_key)
    if cached:
        return cached
    try:
        block = rank_query(db, status, settings, period, rank_type, target_type, limit, sector_code=sector_code)
        snapshot = snapshot_for_timeframe_with_settings(db, status, settings, period)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"ranking unavailable: {exc}") from exc
    payload = {
        "period": period_for(period).period_type,
        "timeframe": period.value,
        "period_label": _timeframe_label(period),
        "type": rank_type,
        "target_type": target_type,
        "updated_at": snapshot.index.updated_at if snapshot else None,
        "data_source": snapshot.data_source if snapshot else None,
        "is_sample_data": _is_sample_source(snapshot.data_source) if snapshot else None,
        "items": block.items,
    }
    encoded = {
        **payload,
        "items": [item.model_dump(mode="json") for item in block.items],
    }
    cache.set_json(cache_key, encoded, settings.cache_ttl_seconds)
    return encoded


def _timeframe_label(timeframe: Timeframe) -> str:
    from app.models import TIMEFRAME_LABELS

    return TIMEFRAME_LABELS[timeframe]


def _safe_database_url(database_url: str) -> str:
    if "@" not in database_url:
        return database_url
    prefix, suffix = database_url.rsplit("@", 1)
    scheme = prefix.split(":", 1)[0]
    return f"{scheme}:***@{suffix}"


def _is_sample_source(data_source: str) -> bool:
    return data_source.startswith("sample") or "sample" in data_source


def _parse_period(period: str) -> Timeframe:
    aliases = {
        "realtime": Timeframe.realtime,
        "hourly": Timeframe.hour_0930_1030,
        "hour_0930_1030": Timeframe.hour_0930_1030,
        "hour_1030_1130": Timeframe.hour_1030_1130,
        "hour_1300_1400": Timeframe.hour_1300_1400,
        "hour_1400_1500": Timeframe.hour_1400_1500,
        "morning": Timeframe.morning,
        "afternoon": Timeframe.afternoon,
        "tail": Timeframe.closing,
        "closing": Timeframe.closing,
        "daily": Timeframe.daily,
        "last_trade_day": Timeframe.last_trade_day,
    }
    if period not in aliases:
        raise HTTPException(status_code=422, detail=f"Unsupported period: {period}")
    return aliases[period]
