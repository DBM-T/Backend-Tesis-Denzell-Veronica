from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.services.alertas_service import refresh_alerts_and_dashboard


scheduler = AsyncIOScheduler(timezone="UTC")


def start_scheduler() -> None:
    if scheduler.running:
        return
    scheduler.add_job(
        refresh_alerts_and_dashboard,
        trigger="interval",
        minutes=30,
        id="refresh_alerts_and_dashboard",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.start()


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
