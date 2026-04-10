"""
zerodha.py — Handles Zerodha login, portfolio data, and order placement.
"""

import json
import datetime
from kiteconnect import KiteConnect
import config


def get_kite():
    """Returns an authenticated KiteConnect instance."""
    kite = KiteConnect(api_key=config.ZERODHA_API_KEY)
    if config.ZERODHA_ACCESS_TOKEN:
        kite.set_access_token(config.ZERODHA_ACCESS_TOKEN)
    return kite


def login(kite):
    """Interactive browser-based Zerodha login."""
    print("\n" + "="*55)
    print("  ZERODHA LOGIN")
    print("="*55)
    print(f"\n1. Open this URL in your browser:\n\n   {kite.login_url()}\n")
    print("2. Log in and copy the 'request_token' from the redirect URL.\n")
    request_token = input("Paste request_token here: ").strip()
    data = kite.generate_session(request_token, api_secret=config.ZERODHA_API_SECRET)
    kite.set_access_token(data["access_token"])
    config.ZERODHA_ACCESS_TOKEN = data["access_token"]

    # Save access token permanently to config file
    with open('config.py', 'r') as f:
        content = f.read()
    import re
    content = re.sub(
        r'ZERODHA_ACCESS_TOKEN = ".*?"',
        f'ZERODHA_ACCESS_TOKEN = "{data["access_token"]}"',
        content
    )
    with open('config.py', 'w') as f:
        f.write(content)

    print("✅ Logged in successfully!\n")
    return kite


def get_portfolio(kite):
    """Returns holdings, positions, and available cash."""
    holdings  = kite.holdings()
    margins   = kite.margins()["equity"]
    available = margins.get("available", {})
    cash = available.get("cash", 0) + available.get("intraday_payin", 0)
    positions = kite.positions().get("net", [])
    return {
        "holdings":  holdings,
        "positions": positions,
        "cash":      cash,
    }


def get_portfolio_summary(portfolio):
    """Returns a plain-English string summary of the portfolio."""
    lines = [f"Available cash: ₹{portfolio['cash']:,.2f}"]

    if portfolio["holdings"]:
        lines.append(f"\nHoldings ({len(portfolio['holdings'])} stocks):")
        total_invested = 0
        total_current  = 0
        for h in portfolio["holdings"]:
            invested = h["average_price"] * h["quantity"]
            current  = h["last_price"]   * h["quantity"]
            pnl      = h["pnl"]
            pct      = ((current - invested) / invested * 100) if invested else 0
            sign     = "+" if pnl >= 0 else ""
            total_invested += invested
            total_current  += current
            lines.append(
                f"  • {h['tradingsymbol']:15s} | Qty: {h['quantity']:5d} "
                f"| Avg: ₹{h['average_price']:8.2f} | LTP: ₹{h['last_price']:8.2f} "
                f"| P&L: {sign}₹{pnl:,.2f} ({sign}{pct:.1f}%)"
            )
        overall_pnl = total_current - total_invested
        overall_pct = (overall_pnl / total_invested * 100) if total_invested else 0
        sign = "+" if overall_pnl >= 0 else ""
        lines.append(
            f"\nTotal invested: ₹{total_invested:,.2f} | "
            f"Current value: ₹{total_current:,.2f} | "
            f"Overall P&L: {sign}₹{overall_pnl:,.2f} ({sign}{overall_pct:.1f}%)"
        )
    else:
        lines.append("\nNo holdings yet.")

    return "\n".join(lines)


def get_quote(kite, symbols):
    """Returns latest quotes for a list of NSE symbols."""
    instruments = [f"NSE:{s}" for s in symbols]
    try:
        quotes = kite.quote(instruments)
        result = {}
        for sym in symbols:
            key = f"NSE:{sym}"
            if key in quotes:
                q = quotes[key]
                result[sym] = {
                    "ltp":    q["last_price"],
                    "open":   q["ohlc"]["open"],
                    "high":   q["ohlc"]["high"],
                    "low":    q["ohlc"]["low"],
                    "close":  q["ohlc"]["close"],
                    "volume": q["volume"],
                    "change": q.get("net_change", 0),
                }
        return result
    except Exception as e:
        return {}


def place_market_order(kite, symbol, quantity, transaction_type):
    return kite.place_order(
        variety          = kite.VARIETY_REGULAR,
        exchange         = kite.EXCHANGE_NSE,
        tradingsymbol    = symbol.upper(),
        transaction_type = transaction_type.upper(),
        quantity         = int(quantity),
        order_type       = kite.ORDER_TYPE_MARKET,
        product          = kite.PRODUCT_CNC,
        market_protection = -1,  # ← add this line
    )

def is_market_open():
    """Returns True if current IST time is within market hours on a weekday."""
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
    if now.weekday() >= 5:  # Saturday/Sunday
        return False
    market_open  = now.replace(hour=9,  minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close

