from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
import logging
import re
import time
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.tables import SectorSnapshot, StockSectorMap, StockUniverse
from app.services.provider import _call_with_timeout

CN_TZ = ZoneInfo("Asia/Shanghai")
logger = logging.getLogger(__name__)


def stock_universe_count(db: Session) -> int:
    return int(db.scalar(select(func.count(StockUniverse.id)).where(StockUniverse.active.is_(True))) or 0)


def load_stock_context(db: Session) -> tuple[dict[str, str], dict[str, list[tuple[str, str]]]]:
    universe = {
        row.stock_code: row.stock_name
        for row in db.scalars(select(StockUniverse).where(StockUniverse.active.is_(True)))
    }
    mappings: dict[str, list[tuple[str, str]]] = defaultdict(list)
    if not universe:
        return universe, mappings
    rows = db.scalars(
        select(StockSectorMap).where(
            StockSectorMap.stock_code.in_(universe),
            StockSectorMap.sector_code != "",
        )
    )
    for row in rows:
        mappings[row.stock_code].append((row.sector_code, row.sector_name))
    return universe, dict(mappings)


def refresh_stock_metadata(
    db: Session,
    settings: Settings,
    *,
    refresh_memberships: bool,
    ak=None,
) -> dict:
    if ak is None:
        import akshare as ak

    universe_rows = 0
    if _universe_needs_refresh(db, settings):
        universe_rows = refresh_stock_universe(db, settings, ak=ak)
    membership_rows = 0
    membership_sectors = 0
    if refresh_memberships:
        membership_rows, membership_sectors = refresh_sector_membership_batch(db, settings, ak=ak)
    return {
        "universe_rows": universe_rows,
        "active_stocks": stock_universe_count(db),
        "membership_rows": membership_rows,
        "membership_sectors": membership_sectors,
    }


def refresh_stock_universe(db: Session, settings: Settings, *, ak=None) -> int:
    if ak is None:
        import akshare as ak

    loaders = [
        ("SH", lambda: ak.stock_info_sh_name_code(), ("证券代码",), ("证券简称",)),
        ("SH", lambda: ak.stock_info_sh_name_code(symbol="科创板"), ("证券代码",), ("证券简称",)),
        ("SZ", lambda: ak.stock_info_sz_name_code(), ("A股代码", "证券代码"), ("A股简称", "证券简称")),
        ("BJ", lambda: ak.stock_info_bj_name_code(), ("证券代码",), ("证券简称",)),
    ]
    collected: dict[str, tuple[str, str]] = {}
    for market, loader, code_columns, name_columns in loaders:
        frame = _call_with_timeout(loader, settings.metadata_provider_call_timeout_seconds)
        rows = _universe_rows(frame, market, code_columns, name_columns)
        if not rows:
            raise RuntimeError(f"empty {market} stock universe")
        collected.update(rows)
    if len(collected) < settings.min_realtime_stock_count:
        raise RuntimeError(f"stock universe coverage too low: {len(collected)}")

    now = datetime.utcnow()
    trade_date = datetime.now(CN_TZ).date().isoformat()
    existing = {row.stock_code: row for row in db.scalars(select(StockUniverse))}
    db.execute(update(StockUniverse).values(active=False, updated_at=now))
    for code, (name, market) in collected.items():
        row = existing.get(code)
        if row is None:
            db.add(
                StockUniverse(
                    stock_code=code,
                    stock_name=name,
                    market=market,
                    active=True,
                    last_seen_date=trade_date,
                )
            )
            continue
        row.stock_name = name
        row.market = market
        row.active = True
        row.last_seen_date = trade_date
        row.updated_at = now
    db.flush()
    return len(collected)


def refresh_sector_membership_batch(db: Session, settings: Settings, *, ak=None) -> tuple[int, int]:
    if ak is None:
        import akshare as ak

    latest_time = db.scalar(select(func.max(SectorSnapshot.snapshot_time)))
    if latest_time is None:
        return 0, 0
    sectors = list(
        db.scalars(
            select(SectorSnapshot)
            .where(SectorSnapshot.snapshot_time == latest_time)
            .order_by(SectorSnapshot.sector_code)
        )
    )
    refreshed_at = dict(
        db.execute(
            select(StockSectorMap.sector_code, func.max(StockSectorMap.updated_at)).group_by(
                StockSectorMap.sector_code
            )
        )
    )
    cutoff = datetime.utcnow() - timedelta(hours=settings.metadata_max_age_hours)
    stale = [row for row in sectors if refreshed_at.get(row.sector_code, datetime.min) < cutoff]
    selected = stale[: settings.membership_refresh_batch_size]
    written = refreshed = 0
    for index, sector in enumerate(selected):
        try:
            frame = _call_with_timeout(
                lambda: ak.stock_sector_detail(sector=sector.sector_code),
                settings.provider_call_timeout_seconds,
            )
            members = _sector_members(frame)
            if not members:
                raise RuntimeError("empty sector membership")
            db.execute(delete(StockSectorMap).where(StockSectorMap.sector_code == sector.sector_code))
            for code, name in members.items():
                db.add(
                    StockSectorMap(
                        stock_code=code,
                        stock_name=name,
                        sector_code=sector.sector_code,
                        sector_name=sector.sector_name,
                        sector_type="industry",
                    )
                )
            db.flush()
            written += len(members)
            refreshed += 1
        except Exception as exc:
            logger.warning("sector membership refresh failed for %s: %s", sector.sector_code, exc)
        if index + 1 < len(selected):
            time.sleep(settings.membership_request_delay_seconds)
    return written, refreshed


def _universe_needs_refresh(db: Session, settings: Settings) -> bool:
    count = stock_universe_count(db)
    if count < settings.min_realtime_stock_count:
        return True
    latest = db.scalar(select(func.max(StockUniverse.updated_at)).where(StockUniverse.active.is_(True)))
    if latest is None:
        return True
    return latest < datetime.utcnow() - timedelta(hours=settings.metadata_max_age_hours)


def _universe_rows(frame, market: str, code_columns: tuple[str, ...], name_columns: tuple[str, ...]):
    code_column = next((column for column in code_columns if column in frame.columns), None)
    name_column = next((column for column in name_columns if column in frame.columns), None)
    if code_column is None or name_column is None:
        return {}
    result: dict[str, tuple[str, str]] = {}
    for _, row in frame.iterrows():
        code = _stock_code(row[code_column])
        name = str(row[name_column]).strip()
        if code and name:
            result[code] = (name, market)
    return result


def _sector_members(frame) -> dict[str, str]:
    code_column = next((column for column in ("code", "代码", "symbol") if column in frame.columns), None)
    name_column = next((column for column in ("name", "名称") if column in frame.columns), None)
    if code_column is None or name_column is None:
        return {}
    result: dict[str, str] = {}
    for _, row in frame.iterrows():
        code = _stock_code(row[code_column])
        name = str(row[name_column]).strip()
        if code and name:
            result[code] = name
    return result


def _stock_code(value) -> Optional[str]:
    match = re.search(r"(\d{6})", str(value))
    return match.group(1) if match else None
