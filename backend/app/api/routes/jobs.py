import hmac
from datetime import date

from fastapi import APIRouter, Header

from app.api.deps import DB
from app.core.config import get_settings
from app.core.errors import Unauthorized
from app.services.jobs import run_daily
from app.utils.formatting import today_ist

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("/run-daily")
def run_daily_jobs(db: DB, x_cron_secret: str = Header(default=""), on: date | None = None):
    secret = get_settings().cron_secret
    if not secret or not hmac.compare_digest(x_cron_secret.encode(), secret.encode()):
        raise Unauthorized("Invalid cron secret")
    # ``on`` lets you replay a specific date in development; ignored in production.
    today = on if (on and not get_settings().is_production) else today_ist()
    return run_daily(db, today)
