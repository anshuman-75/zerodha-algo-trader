"""
fno_tracker.py — Tracks F&O trade count across days
Enforces the biweekly limit (MAX_FNO_TRADES_BIWEEKLY in config.py)

Uses a simple JSON file: fno_tracker.json
{
    "trades": [
        {"date": "2026-04-10", "symbol": "NIFTY24417CE", "cost": 1125}
    ]
}
"""

import json
import os
import datetime
import config

TRACKER_FILE = "fno_tracker.json"


# ─────────────────────────────────────────────────────────────
#  LOAD / SAVE
# ─────────────────────────────────────────────────────────────

def _load():
    if not os.path.exists(TRACKER_FILE):
        return {"trades": []}
    try:
        with open(TRACKER_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {"trades": []}


def _save(data):
    try:
        with open(TRACKER_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[FNO Tracker] Save failed: {e}")


# ─────────────────────────────────────────────────────────────
#  CORE FUNCTIONS
# ─────────────────────────────────────────────────────────────

def get_biweekly_trade_count():
    """
    Returns number of F&O trades placed in the last 14 days.
    """
    data   = _load()
    today  = datetime.date.today()
    cutoff = today - datetime.timedelta(days=14)

    recent = [
        t for t in data["trades"]
        if datetime.date.fromisoformat(t["date"]) > cutoff
    ]
    return len(recent)


def can_trade_fno():
    """
    Returns (True, message) if allowed to trade F&O today.
    Returns (False, reason) if biweekly limit reached.
    """
    count = get_biweekly_trade_count()
    limit = config.MAX_FNO_TRADES_BIWEEKLY

    if count >= limit:
        next_available = _next_available_date()
        return False, (
            f"Biweekly F&O limit reached ({count}/{limit} trades in last 14 days). "
            f"Next trade allowed after {next_available}."
        )

    remaining = limit - count
    return True, f"{remaining} F&O trade(s) remaining in this 2-week window."


def record_fno_trade(symbol, cost):
    """
    Records a completed F&O trade.
    Call this after a successful options order placement.
    """
    data = _load()
    data["trades"].append({
        "date":   datetime.date.today().isoformat(),
        "symbol": symbol,
        "cost":   cost,
    })
    _save(data)
    print(f"[FNO Tracker] Recorded trade: {symbol} @ ₹{cost}")


def get_trade_history(days=30):
    """Returns trade history for the last N days."""
    data   = _load()
    today  = datetime.date.today()
    cutoff = today - datetime.timedelta(days=days)

    return [
        t for t in data["trades"]
        if datetime.date.fromisoformat(t["date"]) > cutoff
    ]


def _next_available_date():
    """Returns the date when next F&O trade will be allowed."""
    data = _load()
    if not data["trades"]:
        return datetime.date.today().isoformat()

    # Find oldest trade in current 14-day window
    today  = datetime.date.today()
    cutoff = today - datetime.timedelta(days=14)

    recent_dates = sorted([
        datetime.date.fromisoformat(t["date"])
        for t in data["trades"]
        if datetime.date.fromisoformat(t["date"]) > cutoff
    ])

    if not recent_dates:
        return today.isoformat()

    # Next available = oldest trade date + 15 days
    oldest = recent_dates[0]
    return (oldest + datetime.timedelta(days=15)).isoformat()


def summary():
    """Returns a plain-English summary for Telegram reports."""
    count          = get_biweekly_trade_count()
    limit          = config.MAX_FNO_TRADES_BIWEEKLY
    allowed, msg   = can_trade_fno()
    history        = get_trade_history(days=14)

    lines = [f"⚡ F&O Tracker: {count}/{limit} trades in last 14 days"]
    if history:
        for t in history:
            lines.append(f"  • {t['date']} | {t['symbol']} | ₹{t['cost']:,}")
    if not allowed:
        lines.append(f"  🔒 {msg}")
    else:
        lines.append(f"  ✅ {msg}")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
#  STANDALONE TEST
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("F&O Tracker Status:")
    print(summary())
    allowed, msg = can_trade_fno()
    print(f"\nCan trade today: {'✅ Yes' if allowed else '❌ No'}")
    print(f"Reason: {msg}")
