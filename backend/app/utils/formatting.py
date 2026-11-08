"""Indian formatting and timezone helpers."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

_today_override: date | None = None  # used by tests


def today_ist() -> date:
    if _today_override is not None:
        return _today_override
    return datetime.now(IST).date()


def now_ist() -> datetime:
    return datetime.now(IST)


def set_today_override(d: date | None) -> None:
    global _today_override
    _today_override = d


def inr(amount: int | float | None, symbol: str = "₹") -> str:
    """Format with Indian digit grouping: 150000 -> ₹1,50,000."""
    if amount is None:
        amount = 0
    neg = amount < 0
    n = int(round(abs(amount)))
    s = str(n)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups) + "," + tail
    return f"{'-' if neg else ''}{symbol}{s}"


def fmt_date(d: date | datetime | None) -> str:
    """DD-MMM-YYYY e.g. 05-Nov-2026."""
    if d is None:
        return ""
    if isinstance(d, datetime):
        d = d.astimezone(IST).date() if d.tzinfo else d.date()
    return d.strftime("%d-%b-%Y")


def fmt_short(d: date) -> str:
    """e.g. 5 Nov."""
    return f"{d.day} {d.strftime('%b')}"


def month_label(month: str) -> str:
    """'2026-11' -> 'Nov 2026'."""
    y, m = month.split("-")
    return date(int(y), int(m), 1).strftime("%b %Y")
