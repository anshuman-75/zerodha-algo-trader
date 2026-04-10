"""
logger.py — Logs all decisions, orders, and errors to a file and console.
"""

import datetime
import config


def _timestamp():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")


def _write(tag, message):
    line = f"[{_timestamp()}] [{tag}] {message}"
    print(line)
    with open(config.LOG_FILE, "a") as f:
        f.write(line + "\n")


def info(msg):    _write("INFO ", msg)
def success(msg): _write("✅ OK", msg)
def warning(msg): _write("⚠️  WARN", msg)
def error(msg):   _write("❌ ERR", msg)


def log_decision(decision):
    info(f"Market sentiment: {decision.get('market_sentiment', '?').upper()}")
    info(f"Claude reasoning: {decision.get('reasoning', '')}")
    for a in decision.get("actions", []):
        if a["action"] == "hold":
            info(f"Action: HOLD — {a['reason']}")
        elif a["action"] == "buy":
            info(f"Action: BUY {a['symbol']} ₹{a['amount_inr']} — {a['reason']}")
        elif a["action"] == "sell":
            info(f"Action: SELL {a['quantity']} x {a['symbol']} — {a['reason']}")


def log_order(action, symbol, quantity, order_id):
    success(f"Order placed | {action.upper()} {quantity} x {symbol} | Order ID: {order_id}")


def log_order_skipped(symbol, reason):
    warning(f"Order skipped | {symbol} | Reason: {reason}")


def log_scheduled(symbol, quantity, order_id):
    success(f"Scheduled order | BUY {quantity} x {symbol} | Order ID: {order_id}")


def log_daily_summary(spent, orders):
    info(f"Daily summary: ₹{spent:,.2f} invested across {orders} order(s).")
    info("─" * 50)

