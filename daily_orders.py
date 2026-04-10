"""
daily_orders.py — AutoInvestor v3
Tracks orders placed within the current trading day.
Prevents Claude from double-buying the same stock across multiple daily runs.
File: ~/investor_v3/daily_orders.json  (auto-created, auto-reset each new day)
"""

import json
import os
from datetime import date

ORDERS_FILE = os.path.join(os.path.dirname(__file__), "daily_orders.json")


def _load():
    """Load today's orders file. Returns empty structure if missing or stale."""
    today = str(date.today())
    if os.path.exists(ORDERS_FILE):
        try:
            with open(ORDERS_FILE, "r") as f:
                data = json.load(f)
            if data.get("date") == today:
                return data
        except Exception:
            pass
    return {"date": today, "orders": [], "symbols_bought": [], "total_spent": 0, "fno_trades": []}


def _save(data):
    with open(ORDERS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def record_order(symbol, action, quantity, price, order_id, reason=""):
    """Call this immediately after every successful order placement."""
    data = _load()
    entry = {
        "symbol": symbol,
        "action": action,
        "quantity": quantity,
        "price": price,
        "value": round(quantity * price, 2),
        "order_id": order_id,
        "reason": reason,
    }
    data["orders"].append(entry)
    if action == "BUY" and symbol not in data["symbols_bought"]:
        data["symbols_bought"].append(symbol)
    if action == "BUY":
        data["total_spent"] += entry["value"]
    _save(data)


def get_todays_summary():
    """Returns a dict with today's orders for injection into Claude's prompt."""
    data = _load()
    return {
        "orders_placed_today": data["orders"],
        "symbols_bought_today": data["symbols_bought"],
        "total_spent_today": round(data["total_spent"], 2),
    }


def already_bought_today(symbol):
    """Quick check — returns True if this symbol was already bought today."""
    data = _load()
    return symbol in data["symbols_bought"]


def get_symbols_bought_today():
    return _load().get("symbols_bought", [])


def get_total_spent_today():
    return _load().get("total_spent", 0)


def record_fno_trade(symbol, tradingsymbol, cost, order_id):
    """Record an F&O trade placed today."""
    data = _load()
    data.setdefault("fno_trades", [])
    data["fno_trades"].append({
        "symbol": symbol,
        "tradingsymbol": tradingsymbol,
        "cost": cost,
        "order_id": order_id,
    })
    _save(data)


def get_fno_trades_today():
    """Returns number of F&O trades placed today."""
    return len(_load().get("fno_trades", []))


if __name__ == "__main__":
    summary = get_todays_summary()
    print(f"Date: {_load()['date']}")
    print(f"Symbols bought today: {summary['symbols_bought_today']}")
    print(f"Total spent today: ₹{summary['total_spent_today']}")
    print(f"F&O trades today: {get_fno_trades_today()}")
    print(f"Orders:")
    for o in summary["orders_placed_today"]:
        print(f"  {o['action']} {o['symbol']} x{o['quantity']} @ ₹{o['price']} = ₹{o['value']} | ID: {o['order_id']}")
