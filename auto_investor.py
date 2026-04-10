"""
auto_investor.py (v2.1) — With Telegram daily reports.
"""

import time
import datetime
import math
import schedule

import config
import zerodha
import claude_investor
import logger
from technical_analysis import analyse_watchlist
from telegram_reporter import (
    send_daily_report,
    send_order_alert,
    send_error_alert,
    send_startup_message,
)


# ── Daily spend tracker ────────────────────────────────────────────────────────
daily_spent  = 0
daily_orders = 0
daily_actions = []


def reset_daily_tracker():
    global daily_spent, daily_orders, daily_actions
    daily_spent   = 0
    daily_orders  = 0
    daily_actions = []


# ── Safety checks ──────────────────────────────────────────────────────────────

def safety_check(cash, amount):
    global daily_spent
    if not zerodha.is_market_open():
        return False, "Market is closed"
    if cash - amount < config.MIN_CASH_RESERVE:
        return False, f"Would breach minimum cash reserve of ₹{config.MIN_CASH_RESERVE}"
    if amount > config.MAX_ORDER_VALUE:
        return False, f"Order ₹{amount} exceeds max order limit ₹{config.MAX_ORDER_VALUE}"
    if daily_spent + amount > config.MAX_DAILY_SPEND:
        return False, f"Would exceed daily spend limit ₹{config.MAX_DAILY_SPEND}"
    return True, "OK"


# ── Execute a single trade ─────────────────────────────────────────────────────

def execute_action(kite, action, portfolio):
    global daily_spent, daily_orders

    symbol   = action.get("symbol", "").upper()
    act      = action.get("action", "hold")
    amount   = action.get("amount_inr", 0)
    quantity = action.get("quantity", 0)
    reason   = action.get("reason", "")
    cash     = portfolio["cash"]

    if act == "hold" or not symbol:
        return

    if act == "buy":
        quotes = zerodha.get_quote(kite, [symbol])
        if symbol not in quotes:
            logger.log_order_skipped(symbol, "Could not fetch live price")
            return

        ltp  = quotes[symbol]["ltp"]
        qty  = math.floor(amount / ltp)

        if qty < 1:
            logger.log_order_skipped(symbol, f"Amount ₹{amount} too small at ₹{ltp:.2f}")
            return

        actual_cost = qty * ltp
        ok, skip_reason = safety_check(cash, actual_cost)
        if not ok:
            logger.log_order_skipped(symbol, skip_reason)
            return

        try:
            order_id = zerodha.place_market_order(kite, symbol, qty, "BUY")
            daily_spent  += actual_cost
            daily_orders += 1
            logger.log_order("buy", symbol, qty, order_id)
            send_order_alert("BUY", symbol, qty, order_id, reason)
        except Exception as e:
            logger.error(f"Order failed for {symbol}: {e}")
            send_error_alert(f"Order failed for {symbol}: {e}")

    elif act == "sell":
        if quantity < 1:
            logger.log_order_skipped(symbol, "Quantity is 0")
            return
        holding = next((h for h in portfolio["holdings"] if h["tradingsymbol"] == symbol), None)
        if not holding or holding["quantity"] < quantity:
            logger.log_order_skipped(symbol, "Not enough shares to sell")
            return
        try:
            order_id = zerodha.place_market_order(kite, symbol, quantity, "SELL")
            daily_orders += 1
            logger.log_order("sell", symbol, quantity, order_id)
            send_order_alert("SELL", symbol, quantity, order_id, reason)
        except Exception as e:
            logger.error(f"Sell order failed for {symbol}: {e}")
            send_error_alert(f"Sell failed for {symbol}: {e}")


# ── Scheduled investments ──────────────────────────────────────────────────────

def run_scheduled_investments(kite, portfolio):
    global daily_spent, daily_orders

    today = datetime.datetime.now().strftime("%A")
    cash  = portfolio["cash"]

    for rule in config.SCHEDULED_INVESTMENTS:
        if rule["day"] != today:
            continue

        symbol = rule["symbol"]
        amount = rule["amount_inr"]
        quotes = zerodha.get_quote(kite, [symbol])

        if symbol not in quotes:
            logger.log_order_skipped(symbol, "Price unavailable")
            continue

        ltp = quotes[symbol]["ltp"]
        qty = math.floor(amount / ltp)

        if qty < 1:
            logger.log_order_skipped(symbol, f"Amount ₹{amount} too small at ₹{ltp:.2f}")
            continue

        actual_cost = qty * ltp
        ok, reason  = safety_check(cash, actual_cost)
        if not ok:
            logger.log_order_skipped(symbol, f"Scheduled blocked: {reason}")
            continue

        try:
            order_id = zerodha.place_market_order(kite, symbol, qty, "BUY")
            daily_spent  += actual_cost
            daily_orders += 1
            cash         -= actual_cost
            logger.log_scheduled(symbol, qty, order_id)
            send_order_alert("BUY", symbol, qty, order_id, "Scheduled SIP investment")
        except Exception as e:
            logger.error(f"Scheduled order failed: {e}")
            send_error_alert(f"Scheduled order failed for {symbol}: {e}")


# ── Main daily job ─────────────────────────────────────────────────────────────

def daily_investment_job(kite):
    global daily_spent, daily_orders

    reset_daily_tracker()
    logger.info("=" * 55)
    logger.info("Daily investment run starting (v2.1 with Telegram)...")

    if not zerodha.is_market_open():
        logger.info("Market is closed today. Skipping.")
        return

    # 1. Fetch portfolio
    try:
        portfolio = zerodha.get_portfolio(kite)
    except Exception as e:
        logger.error(f"Could not fetch portfolio: {e}")
        send_error_alert(f"Could not fetch portfolio: {e}")
        return

    summary = zerodha.get_portfolio_summary(portfolio)
    logger.info(f"Portfolio:\n{summary}")

    # 2. Scheduled investments
    logger.info("Running scheduled investments...")
    run_scheduled_investments(kite, portfolio)

    try:
        portfolio = zerodha.get_portfolio(kite)
    except Exception:
        pass

    # 3. Technical analysis
    logger.info("Running technical analysis on watchlist...")
    try:
        ta_results, ta_string = analyse_watchlist(kite, config.WATCHLIST)
        logger.info(f"TA complete for {len(ta_results)} symbols")
    except Exception as e:
        logger.error(f"Technical analysis failed: {e}")
        ta_string = "Technical analysis unavailable."

    # 4. Ask Claude
    logger.info("Asking Claude AI for investment decisions...")
    try:
        decision = claude_investor.analyse_and_decide(summary, ta_string)
    except Exception as e:
        logger.error(f"Claude analysis failed: {e}")
        send_error_alert(f"Claude analysis failed: {e}")
        return

    logger.log_decision(decision)

    # 5. Execute decisions
    for action in decision.get("actions", []):
        execute_action(kite, action, portfolio)
        portfolio["cash"] -= daily_spent

    # 6. Log summary
    logger.log_daily_summary(daily_spent, daily_orders)

    # 7. Send Telegram report
    try:
        portfolio = zerodha.get_portfolio(kite)
    except Exception:
        pass

    send_daily_report(portfolio, decision, daily_orders, daily_spent)
    logger.info("Telegram report sent successfully!")


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    print("\n" + "="*55)
    print("  Claude AI Auto-Investor v2.1 — With Telegram Reports")
    print("="*55)
    print(f"\n  Risk profile    : Moderate")
    print(f"  Max order       : ₹{config.MAX_ORDER_VALUE:,}")
    print(f"  Max daily spend : ₹{config.MAX_DAILY_SPEND:,}")
    print(f"  Cash reserve    : ₹{config.MIN_CASH_RESERVE:,}")
    print(f"  Daily run time  : {config.ANALYSIS_HOUR:02d}:{config.ANALYSIS_MINUTE:02d} IST")
    print(f"  Notifications   : Telegram")
    print()

    kite = zerodha.get_kite()
    zerodha.login(kite)

    # Send startup message
    send_startup_message()

    run_time = f"{config.ANALYSIS_HOUR:02d}:{config.ANALYSIS_MINUTE:02d}"
    schedule.every().monday.at(run_time).do(daily_investment_job, kite)
    schedule.every().tuesday.at(run_time).do(daily_investment_job, kite)
    schedule.every().wednesday.at(run_time).do(daily_investment_job, kite)
    schedule.every().thursday.at(run_time).do(daily_investment_job, kite)
    schedule.every().friday.at(run_time).do(daily_investment_job, kite)

    logger.info(f"Scheduler started. Running every market day at {run_time} IST.")
    logger.info("Press Ctrl+C to stop.\n")

    run_now = input("Run analysis RIGHT NOW for testing? (yes/no): ").strip().lower()
    if run_now == "yes":
        daily_investment_job(kite)

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
