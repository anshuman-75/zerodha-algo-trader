"""
auto_investor_v3.py — Main Runner for Auto-Investor v3
- Runs 4x daily: 9:15 AM (scan), 9:45 AM, 11:00 AM, 1:00 PM, 3:00 PM IST
- Survives SSH disconnection (run via systemd)
- Token refresh via Telegram (no manual SSH needed)
- Equity analysis + F&O options trading
- Dynamic watchlist from NSE scanner
- Full Telegram reporting
"""

import time
import datetime
import pytz
import json
import traceback

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from kiteconnect import KiteConnect

import config
import logger as log
from token_manager import ensure_valid_token, send_telegram
from market_scanner import build_dynamic_watchlist, format_market_data_for_claude
from claude_investor import analyse_and_decide as get_claude_decision
from options_trader import run_options_analysis
from daily_orders import (
    record_order, already_bought_today,
    get_fno_trades_today, record_fno_trade
)
import zerodha as z

# ─────────────────────────────────────────────────────────────
#  CONSTANTS
# ─────────────────────────────────────────────────────────────
IST = pytz.timezone("Asia/Kolkata")

# Daily state — reset at midnight
_daily_state = {
    "fno_trades_today":    0,
    "equity_spent_today":  0.0,
    "scan_result":         None,
    "kite":                None,
    "date":                None,
}


# ─────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────

def get_kite():
    """Returns authenticated kite, refreshing token if needed."""
    global _daily_state

    kite = KiteConnect(api_key=config.ZERODHA_API_KEY)
    kite = ensure_valid_token(kite, timeout_minutes=10)

    if kite is None:
        send_telegram(
            "❌ <b>Bot startup failed</b>\n\n"
            "Could not authenticate with Zerodha.\n"
            "Please restart manually:\n"
            "<code>screen -r investor_v3</code>\n"
            "<code>python3.11 auto_investor_v3.py</code>"
        )
        return None

    _daily_state["kite"] = kite
    return kite


def reset_daily_state():
    """Resets daily counters at midnight."""
    global _daily_state
    today = datetime.date.today().isoformat()
    if _daily_state["date"] != today:
        _daily_state["fno_trades_today"]   = 0
        _daily_state["equity_spent_today"] = 0.0
        _daily_state["scan_result"]        = None
        _daily_state["date"]               = today
        print(f"[Main] Daily state reset for {today}")


def is_market_day():
    """Returns True if today is a weekday (Mon-Fri)."""
    return datetime.datetime.now(IST).weekday() < 5


def now_ist():
    return datetime.datetime.now(IST).strftime("%d %b %Y, %I:%M %p IST")


# ─────────────────────────────────────────────────────────────
#  SCHEDULED JOBS
# ─────────────────────────────────────────────────────────────

def job_premarket_scan():
    """9:15 AM — Pre-market scanner."""
    reset_daily_state()
    if not is_market_day():
        print("[Scan] Weekend — skipping.")
        return

    print(f"\n{'='*55}")
    print(f"  PRE-MARKET SCAN  |  {now_ist()}")
    print(f"{'='*55}")

    try:
        scan_result = build_dynamic_watchlist(base_watchlist=config.WATCHLIST)
        _daily_state["scan_result"] = scan_result

        summary = scan_result.get("scan_summary", "Scan complete.")
        log.info(f"[Scan] {summary}")

        send_telegram(
            f"📡 <b>Pre-Market Scan Complete</b>\n\n"
            f"{summary}\n\n"
            f"🕐 {now_ist()}"
        )

    except Exception as e:
        err = traceback.format_exc()
        print(f"[Scan] Error: {e}\n{err}")
        send_telegram(f"⚠️ Pre-market scan failed:\n<code>{e}</code>")


def job_analysis(label="Analysis"):
    """Core analysis job — runs at 9:45 AM, 11:00 AM, 1:00 PM, 3:00 PM."""
    reset_daily_state()
    if not is_market_day():
        print(f"[{label}] Weekend — skipping.")
        return

    print(f"\n{'='*55}")
    print(f"  {label.upper()}  |  {now_ist()}")
    print(f"{'='*55}")

    # Step 1: Auth
    kite = get_kite()
    if not kite:
        return

    # Step 2: Portfolio
    try:
        portfolio      = z.get_portfolio(kite)
        portfolio_text = z.get_portfolio_summary(portfolio)
        cash           = portfolio["cash"]
        print(f"[{label}] Cash available: ₹{cash:,.2f}")
    except Exception as e:
        print(f"[{label}] Portfolio fetch failed: {e}")
        send_telegram(f"⚠️ Portfolio fetch failed:\n<code>{e}</code>")
        return

    # Step 3: Market data
    scan = _daily_state.get("scan_result")
    if scan:
        equity_watchlist = scan["equity_watchlist"]
        fno_watchlist    = scan["fno_watchlist"]
        market_data      = scan["market_data"]
        market_block     = format_market_data_for_claude(market_data)
    else:
        print(f"[{label}] No scan result, using base watchlist")
        equity_watchlist = config.WATCHLIST
        fno_watchlist    = config.FNO_WATCHLIST
        market_data      = {}
        market_block     = ""

    # Step 4: SIP investments (9:45 AM only)
    sip_report = ""
    if label == "Morning Analysis":
        sip_report = run_sip_investments(kite, portfolio, cash)

    # Step 5: Equity analysis
    equity_report = run_equity_analysis(
        kite, label, portfolio_text, equity_watchlist, market_block, cash
    )

    # Step 6: Options analysis
    options_report = run_options_trading(
        kite, label, fno_watchlist, market_data, portfolio_text
    )

    # Step 7: Telegram report
    send_analysis_report(
        label, portfolio_text, sip_report, equity_report, options_report, market_data
    )


def run_sip_investments(kite, portfolio, cash):
    """Runs scheduled SIP investments for today if applicable."""
    today_name = datetime.datetime.now(IST).strftime("%A")
    sip_lines  = []

    for sip in config.SCHEDULED_INVESTMENTS:
        if sip["day"] != today_name:
            continue

        symbol = sip["symbol"]
        amount = sip["amount_inr"]

        if cash < amount + config.MIN_CASH_RESERVE:
            msg = f"⚠️ SIP {symbol}: Skipped — insufficient cash (₹{cash:,.0f})"
            print(f"[SIP] {msg}")
            sip_lines.append(msg)
            continue

        try:
            quotes = z.get_quote(kite, [symbol])
            ltp    = quotes.get(symbol, {}).get("ltp", 0)
            if ltp <= 0:
                sip_lines.append(f"⚠️ SIP {symbol}: Skipped — could not get price")
                continue

            qty      = max(1, int(amount // ltp))
            order_id = z.place_market_order(kite, symbol, qty, "BUY")

            actual_cost = round(qty * ltp, 2)
            _daily_state["equity_spent_today"] += actual_cost
            record_order(symbol, "BUY", qty, ltp, order_id, "SIP investment")

            msg = f"✅ SIP {symbol}: Bought {qty} shares @ ~₹{ltp:,.2f} (₹{actual_cost:,.0f})"
            print(f"[SIP] {msg}")
            sip_lines.append(msg)
            log.info(f"[SIP] {msg} | Order ID: {order_id}")

        except Exception as e:
            msg = f"❌ SIP {symbol}: Failed — {e}"
            print(f"[SIP] {msg}")
            sip_lines.append(msg)
            log.info(f"[SIP] ERROR: {msg}")

    return "\n".join(sip_lines) if sip_lines else "No SIP due today."


def run_equity_analysis(kite, label, portfolio_text, watchlist, market_block, cash):
    """Runs Claude equity analysis and places orders."""
    lines = []
    try:
        quotes = z.get_quote(kite, watchlist)
        if not quotes:
            return "⚠️ Could not fetch watchlist quotes."

        decision = get_claude_decision(
            portfolio_summary=portfolio_text,
            quotes=quotes,
            market_context=market_block,
            cash=cash,
        )

        actions = decision.get("actions", [])
        if not actions:
            return f"🤖 Claude: No equity trades — {decision.get('reasoning', 'no strong signals')}"

        for action in actions:
            sym    = action.get("symbol", "")
            side   = action.get("action", "").upper()
            qty    = action.get("quantity", 0)
            reason = action.get("reason", "")

            if side not in ("BUY", "SELL") or qty <= 0:
                continue

            # Skip if already bought today
            if side == "BUY" and already_bought_today(sym):
                lines.append(f"⏭️ {sym}: Skipped — already bought today")
                continue

            quotes_sym = quotes.get(sym, {})
            ltp        = quotes_sym.get("ltp", 0)
            cost       = ltp * qty

            if side == "BUY":
                if cost > config.MAX_ORDER_VALUE:
                    lines.append(f"⚠️ {sym}: Skipped — order value ₹{cost:,.0f} > limit")
                    continue
                daily_total = _daily_state["equity_spent_today"] + cost
                if daily_total > config.MAX_DAILY_SPEND:
                    lines.append(f"⚠️ {sym}: Skipped — daily spend limit reached")
                    continue
                if cash - cost < config.MIN_CASH_RESERVE:
                    lines.append(f"⚠️ {sym}: Skipped — would breach cash reserve")
                    continue

            order_id = z.place_market_order(kite, sym, qty, side)

            if side == "BUY":
                _daily_state["equity_spent_today"] += cost
                record_order(sym, "BUY", qty, ltp, order_id, reason)

            msg = f"{'✅' if side == 'BUY' else '🔴'} {side} {sym}: {qty} shares @ ~₹{ltp:,.2f} | {reason}"
            lines.append(msg)
            log.info(f"[Equity] {msg} | Order: {order_id}")

        summary = decision.get("reasoning", "")
        if summary:
            lines.insert(0, f"🤖 <i>{summary}</i>")

    except Exception as e:
        err = traceback.format_exc()
        print(f"[Equity] Error: {e}\n{err}")
        lines.append(f"❌ Equity analysis error: {e}")

    return "\n".join(lines) if lines else "No equity trades this run."


def run_options_trading(kite, label, fno_watchlist, market_data, portfolio_text):
    """Runs options analysis and places trade if signal is strong."""
    try:
        result = run_options_analysis(
            kite=kite,
            fno_watchlist=fno_watchlist,
            market_data=market_data,
            portfolio_summary=portfolio_text,
            trades_today=get_fno_trades_today(),
        )

        action = result.get("action", "SKIP")
        reason = result.get("reasoning", result.get("reason", ""))

        if action == "BUY" and result.get("order_placed"):
            _daily_state["fno_trades_today"] += 1
            sym  = result.get("tradingsymbol", "")
            cost = result.get("estimated_cost", 0)
            conf = result.get("confidence", "")
            record_fno_trade(
                result.get("symbol", ""),
                sym,
                cost,
                result.get("order_id", "")
            )
            return (
                f"⚡ <b>Options Trade Placed!</b>\n"
                f"  Symbol    : {sym}\n"
                f"  Type      : {result.get('type')} | Strike: {result.get('strike')}\n"
                f"  Lots      : {result.get('lots')} | Cost: ₹{cost:,.0f}\n"
                f"  Confidence: {conf}\n"
                f"  Reason    : {reason}"
            )
        elif action == "BUY" and not result.get("order_placed"):
            return f"⚡ Options: Claude wanted to BUY but order failed.\n{reason}"
        else:
            skip_reason = result.get("reason", "")
            if skip_reason == "daily_limit":
                return "⚡ Options: Daily trade limit reached."
            elif skip_reason == "high_vix":
                vix = market_data.get("india_vix", "?")
                return f"⚡ Options: Skipped — VIX too high ({vix})"
            else:
                return f"⚡ Options: No trade — {reason[:100] if reason else 'no strong signal'}"

    except Exception as e:
        print(f"[Options] Error: {e}")
        return f"⚡ Options error: {e}"


def send_analysis_report(label, portfolio_text, sip_report,
                          equity_report, options_report, market_data):
    """Sends a formatted analysis report to Telegram."""
    vix   = market_data.get("india_vix", "N/A")
    pcr   = market_data.get("pcr", "N/A")
    fii   = market_data.get("fii_net_cr", "N/A")
    pcr_s = market_data.get("pcr_sentiment", "")

    msg = (
        f"📊 <b>{label} Report</b>\n"
        f"🕐 {now_ist()}\n"
        f"{'─'*35}\n"
        f"🔴 VIX: {vix}  |  📈 PCR: {pcr} ({pcr_s})  |  🏦 FII: ₹{fii}Cr\n"
        f"{'─'*35}\n"
        f"\n<b>💰 SIP</b>\n{sip_report}\n"
        f"\n<b>📈 Equity</b>\n{equity_report}\n"
        f"\n<b>⚡ F&O Options</b>\n{options_report}\n"
        f"{'─'*35}\n"
        f"<b>Portfolio Snapshot</b>\n<code>{portfolio_text[:800]}</code>"
    )

    send_telegram(msg)
    log.info(f"[{label}] Report sent to Telegram.")


# ─────────────────────────────────────────────────────────────
#  SCHEDULER SETUP
# ─────────────────────────────────────────────────────────────

def setup_scheduler():
    scheduler = BlockingScheduler(timezone=IST)

    scheduler.add_job(
        job_premarket_scan,
        CronTrigger(hour=9, minute=15, day_of_week="mon-fri", timezone=IST),
        id="premarket_scan",
        name="Pre-Market Scan",
        misfire_grace_time=300,
    )
    scheduler.add_job(
        lambda: job_analysis("Morning Analysis"),
        CronTrigger(hour=9, minute=45, day_of_week="mon-fri", timezone=IST),
        id="morning_analysis",
        name="Morning Analysis",
        misfire_grace_time=300,
    )
    scheduler.add_job(
        lambda: job_analysis("Mid-Morning Check"),
        CronTrigger(hour=11, minute=0, day_of_week="mon-fri", timezone=IST),
        id="midmorning",
        name="Mid-Morning Check",
        misfire_grace_time=300,
    )
    scheduler.add_job(
        lambda: job_analysis("Afternoon Check"),
        CronTrigger(hour=13, minute=0, day_of_week="mon-fri", timezone=IST),
        id="afternoon",
        name="Afternoon Check",
        misfire_grace_time=300,
    )
    scheduler.add_job(
        lambda: job_analysis("Pre-Close Check"),
        CronTrigger(hour=15, minute=0, day_of_week="mon-fri", timezone=IST),
        id="preclose",
        name="Pre-Close Check",
        misfire_grace_time=300,
    )

    return scheduler


# ─────────────────────────────────────────────────────────────
#  STARTUP
# ─────────────────────────────────────────────────────────────

def startup():
    """Runs once when the bot starts."""
    reset_daily_state()

    print("\n" + "="*55)
    print("  AUTO-INVESTOR v3  |  Starting up...")
    print("="*55)
    print(f"  Time     : {now_ist()}")
    print(f"  Watchlist: {len(config.WATCHLIST)} base stocks")
    print(f"  Schedule : 9:15 | 9:45 | 11:00 | 13:00 | 15:00 IST")
    print("="*55 + "\n")

    kite = get_kite()
    if not kite:
        print("[Startup] Could not authenticate. Bot will retry at next scheduled run.")
        send_telegram(
            "🚀 <b>Auto-Investor v3 Started</b>\n\n"
            "⚠️ Token invalid — please complete Telegram login to activate.\n"
            f"🕐 {now_ist()}"
        )
        return

    _daily_state["kite"] = kite

    send_telegram(
        f"🚀 <b>Auto-Investor v3 Online!</b>\n\n"
        f"✅ Zerodha authenticated\n"
        f"📅 Schedule: 9:15 | 9:45 | 11:00 | 13:00 | 15:00 IST\n"
        f"💰 Budget: ₹{config.MAX_ORDER_VALUE:,}/order | ₹{config.MAX_DAILY_SPEND:,}/day\n"
        f"⚡ F&O: ₹1,500 max | Buy only | 1 trade/day\n"
        f"🕐 Started: {now_ist()}"
    )

    print("[Startup] Bot is live. Scheduler starting...")


# ─────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    startup()

    scheduler = setup_scheduler()

    print("\n[Scheduler] Jobs scheduled:")
    for job in scheduler.get_jobs():
        print(f"  • {job.name}")

    print("\n[Scheduler] Running. Press Ctrl+C to stop.\n")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("\n[Scheduler] Stopped by user.")
        send_telegram("⛔ Auto-Investor v3 stopped manually.")
