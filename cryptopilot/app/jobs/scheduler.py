"""Scheduler — APScheduler AsyncIOScheduler (Phase 5).

AsyncIOScheduler chạy CHUNG event loop với FastAPI → job có thể await CoinGecko/Gemini.
Đăng ký 3 job interval; lịch lấy từ settings (chỉnh trong .env không cần sửa code).

main.py gọi start_scheduler() trong lifespan startup, shutdown_scheduler() khi tắt.
max_instances=1 (mặc định APScheduler) → job chạy lâu hơn chu kỳ cũng không chạy chồng.
"""

import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import settings
from app.jobs.portfolio_snapshot import portfolio_snapshot
from app.jobs.price_check import price_check
from app.jobs.proactive_agent import proactive_agent
from app.jobs.refresh_coins import refresh_coins

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def start_scheduler() -> None:
    if not settings.ENABLE_SCHEDULER:
        logger.info("Scheduler tắt (ENABLE_SCHEDULER=false)")
        return
    if scheduler.running:
        return

    scheduler.add_job(
        price_check,
        "interval",
        minutes=settings.ALERT_CHECK_INTERVAL_MINUTES,
        id="price_check",
        replace_existing=True,
    )
    scheduler.add_job(
        proactive_agent,
        "interval",
        hours=settings.PROACTIVE_INTERVAL_HOURS,
        id="proactive_agent",
        replace_existing=True,
    )
    scheduler.add_job(
        refresh_coins,
        "interval",
        hours=settings.REFRESH_COINS_INTERVAL_HOURS,
        id="refresh_coins",
        replace_existing=True,
    )
    scheduler.add_job(
        portfolio_snapshot,
        "interval",
        hours=settings.PORTFOLIO_SNAPSHOT_INTERVAL_HOURS,
        id="portfolio_snapshot",
        replace_existing=True,
        # chạy ngay lúc đăng ký (không đợi hết chu kỳ 24h đầu) để có ít nhất 1 điểm
        # dữ liệu ngay sau khi deploy, tránh chart trống hoàn toàn
        next_run_time=datetime.now(),
    )
    scheduler.start()
    logger.info(
        "Scheduler chạy: price_check %dm, proactive %dh, refresh_coins %dh, "
        "portfolio_snapshot %dh",
        settings.ALERT_CHECK_INTERVAL_MINUTES,
        settings.PROACTIVE_INTERVAL_HOURS,
        settings.REFRESH_COINS_INTERVAL_HOURS,
        settings.PORTFOLIO_SNAPSHOT_INTERVAL_HOURS,
    )


def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler đã dừng")
