"""
options_trader.py — F&O Options Buying Module for Auto-Investor v3
- Fetches options chain from Kite for Nifty, BankNifty, and watchlist stocks
- Sends data to Claude for CE/PE decision
- Places BUY order only, within Rs.1500 limit
- Max 1 options trade per day
- Never sells options (buying only = limited risk)
"""

import datetime
import json
import anthropic
import config
from market_scanner import format_market_data_for_claude

# ─────────────────────────────────────────────────────────────
#  CONSTANTS
# ─────────────────────────────────────────────────────────────
MAX_FNO_BUDGET       = 1500   # Max Rs per options trade
MAX_FNO_TRADES_DAY   = 1      # Only 1 options trade per day
MIN_PREMIUM          = 5      # Skip options below Rs.5 (illiquid)
MAX_PREMIUM          = 200    # Skip options above Rs.200 (too expensive for budget)

# Index instruments as they appear in Kite
INDEX_INSTRUMENTS = {
    "NIFTY":     "NSE:NIFTY 50",
    "BANKNIFTY": "NSE:NIFTY BANK",
}

# Kite exchange for F&O
FNO_EXCHANGE = "NFO"


# ─────────────────────────────────────────────────────────────
#  INSTRUMENT LOADER
# ─────────────────────────────────────────────────────────────

def get_fno_instruments(kite):
    """
    Downloads full NFO instrument list from Kite.
    Returns a list of dicts with symbol, expiry, strike, type etc.
    Cached in memory for the session.
    """
    try:
        instruments = kite.instruments("NFO")
        return instruments
    except Exception as e:
        print(f"[Options] Failed to fetch instruments: {e}")
        return []


def filter_instruments(instruments, symbol, expiry_date=None):
    """
    Filters NFO instruments for a given symbol (e.g. NIFTY, BANKNIFTY, AXISBANK).
    Returns only the nearest weekly/monthly expiry options if expiry_date not specified.
    """
    symbol_upper = symbol.upper()

    # Get all options for this symbol
    filtered = [
        i for i in instruments
        if i["name"] == symbol_upper
        and i["instrument_type"] in ("CE", "PE")
        and i["expiry"] is not None
    ]

    if not filtered:
        return []

    # Find nearest expiry
    today = datetime.date.today()
    future_expiries = sorted(set(
        i["expiry"] for i in filtered
        if isinstance(i["expiry"], datetime.date) and i["expiry"] >= today
    ))

    if not future_expiries:
        return []

    nearest_expiry = expiry_date or future_expiries[0]

    return [i for i in filtered if i["expiry"] == nearest_expiry]


def get_atm_options(kite, instruments, symbol, spot_price, num_strikes=5):
    """
    Returns ATM and near-ATM CE/PE options for a symbol.
    Fetches live quotes and returns options with premium within budget.

    num_strikes: how many strikes above/below ATM to include
    """
    expiry_instruments = filter_instruments(instruments, symbol)
    if not expiry_instruments:
        print(f"[Options] No instruments found for {symbol}")
        return []

    # Find ATM strike (nearest to spot price)
    strikes = sorted(set(i["strike"] for i in expiry_instruments))
    if not strikes:
        return []

    atm_strike = min(strikes, key=lambda s: abs(s - spot_price))
    atm_index  = strikes.index(atm_strike)

    # Get a window of strikes around ATM
    start = max(0, atm_index - num_strikes)
    end   = min(len(strikes), atm_index + num_strikes + 1)
    selected_strikes = strikes[start:end]

    # Filter instruments to selected strikes
    candidates = [
        i for i in expiry_instruments
        if i["strike"] in selected_strikes
    ]

    if not candidates:
        return []

    # Fetch live quotes for all candidates
    trading_symbols = [f"NFO:{i['tradingsymbol']}" for i in candidates]

    try:
        quotes = kite.quote(trading_symbols)
    except Exception as e:
        print(f"[Options] Quote fetch failed for {symbol}: {e}")
        return []

    results = []
    for inst in candidates:
        key = f"NFO:{inst['tradingsymbol']}"
        if key not in quotes:
            continue

        q = quotes[key]
        ltp = q.get("last_price", 0)

        if ltp < MIN_PREMIUM or ltp > MAX_PREMIUM:
            continue

        lot_size  = inst.get("lot_size", 1)
        one_lot_cost = ltp * lot_size

        if one_lot_cost > MAX_FNO_BUDGET:
            continue

        results.append({
            "tradingsymbol": inst["tradingsymbol"],
            "symbol":        symbol,
            "expiry":        str(inst["expiry"]),
            "strike":        inst["strike"],
            "type":          inst["instrument_type"],   # CE or PE
            "ltp":           ltp,
            "lot_size":      lot_size,
            "one_lot_cost":  round(one_lot_cost, 2),
            "lots_possible": int(MAX_FNO_BUDGET // one_lot_cost),
            "oi":            q.get("oi", 0),
            "volume":        q.get("volume", 0),
            "iv":            q.get("oi_day_high", 0),   # proxy if Greeks not available
            "bid":           q.get("depth", {}).get("buy", [{}])[0].get("price", 0),
            "ask":           q.get("depth", {}).get("sell", [{}])[0].get("price", 0),
        })

    # Sort by OI descending (most liquid first)
    results.sort(key=lambda x: x["oi"], reverse=True)
    return results


# ─────────────────────────────────────────────────────────────
#  CLAUDE DECISION
# ─────────────────────────────────────────────────────────────

def ask_claude_for_options_trade(options_data, market_data, portfolio_summary, technical_summary=""):
    """
    Sends options chain data + market signals to Claude.
    Claude decides: which option to buy (or SKIP if no strong signal).
    Returns a structured decision dict.
    """
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    # Format options data for prompt
    options_text = ""
    for sym, opts in options_data.items():
        if not opts:
            continue
        options_text += f"\n── {sym} Options (nearest expiry) ──\n"
        for o in opts[:10]:   # max 10 per symbol to save tokens
            options_text += (
                f"  {o['type']:2s} | Strike: {o['strike']:8.0f} | "
                f"LTP: Rs.{o['ltp']:6.2f} | Lot: {o['lot_size']} | "
                f"1-lot cost: Rs.{o['one_lot_cost']:7.2f} | "
                f"OI: {o['oi']:,} | Vol: {o['volume']:,} | "
                f"Symbol: {o['tradingsymbol']}\n"
            )

    market_block = format_market_data_for_claude(market_data)

    prompt = f"""You are an expert options trader managing a small retail portfolio in India.
Your job is to decide whether to place ONE options BUY trade today.

STRICT RULES:
- Budget: Rs.{MAX_FNO_BUDGET} maximum for this trade
- ONLY buying options (CE or PE) — never selling/writing
- Only trade if you see a STRONG, HIGH-CONFIDENCE signal
- If signal is weak or unclear → respond with SKIP
- Prefer high OI options (more liquid, tighter spread)
- Max 1 trade per day
- Expiry must be current week or next week only

{market_block}

PORTFOLIO SUMMARY:
{portfolio_summary}

{f"TECHNICAL ANALYSIS SUMMARY:{technical_summary}" if technical_summary else ""}

AVAILABLE OPTIONS (within Rs.{MAX_FNO_BUDGET} budget per lot):
{options_text if options_text else "No options available within budget."}

DECISION REQUIRED:
Analyse all the above data and respond in this EXACT JSON format only (no extra text):

{{
  "action": "BUY" or "SKIP",
  "tradingsymbol": "NFO_TRADING_SYMBOL or null",
  "symbol": "underlying symbol or null",
  "type": "CE or PE or null",
  "strike": strike_price_or_null,
  "expiry": "YYYY-MM-DD or null",
  "lots": number_of_lots_or_null,
  "estimated_cost": total_cost_in_rupees_or_null,
  "confidence": "HIGH / MEDIUM / LOW",
  "reasoning": "2-3 sentence explanation of why this trade makes sense OR why skipping"
}}

Only respond with the JSON. No preamble, no markdown, no extra text.
"""

    try:
        message = client.messages.create(
            model      = "claude-sonnet-4-20250514",
            max_tokens = 500,
            messages   = [{"role": "user", "content": prompt}]
        )

        raw = message.content[0].text.strip()

        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        decision = json.loads(raw)
        return decision

    except json.JSONDecodeError as e:
        print(f"[Options] Claude returned invalid JSON: {e}")
        return {"action": "SKIP", "reasoning": "Claude response parse error", "confidence": "LOW"}
    except Exception as e:
        print(f"[Options] Claude API error: {e}")
        return {"action": "SKIP", "reasoning": f"API error: {e}", "confidence": "LOW"}


# ─────────────────────────────────────────────────────────────
#  ORDER PLACEMENT
# ─────────────────────────────────────────────────────────────

def place_options_order(kite, decision):
    """
    Places a BUY order for the option chosen by Claude.
    Returns order_id on success, None on failure.
    """
    if decision.get("action") != "BUY":
        return None

    tradingsymbol = decision.get("tradingsymbol")
    lots          = decision.get("lots", 1)

    if not tradingsymbol or not lots:
        print("[Options] Invalid decision — missing tradingsymbol or lots")
        return None

    # Fetch lot size from decision or default to 1
    quantity = int(lots)  # Kite takes quantity in lots for F&O

    try:
        order_id = kite.place_order(
            variety          = kite.VARIETY_REGULAR,
            exchange         = FNO_EXCHANGE,
            tradingsymbol    = tradingsymbol,
            transaction_type = kite.TRANSACTION_TYPE_BUY,
            quantity         = quantity,
            order_type       = kite.ORDER_TYPE_MARKET,
            product          = kite.PRODUCT_NRML,
        )
        print(f"[Options] ✅ Order placed! ID: {order_id} | {tradingsymbol} x{quantity} lots")
        return order_id

    except Exception as e:
        print(f"[Options] ❌ Order failed: {e}")
        return None


# ─────────────────────────────────────────────────────────────
#  MAIN FUNCTION
# ─────────────────────────────────────────────────────────────

def run_options_analysis(kite, fno_watchlist, market_data, portfolio_summary,
                          technical_summary="", trades_today=0):
    """
    Full options trading flow:
    1. Check if we already hit daily trade limit
    2. Fetch instruments + spot prices
    3. Build options chain for each symbol
    4. Ask Claude for decision
    5. Place order if action = BUY
    6. Return result dict

    trades_today: number of F&O trades already placed today
    """
    print("\n[Options] ⚡ Starting options analysis...")

    # ── Guard: daily limit ────────────────────────────────────
    if trades_today >= MAX_FNO_TRADES_DAY:
        msg = f"[Options] Daily limit reached ({MAX_FNO_TRADES_DAY} trade/day). Skipping."
        print(msg)
        return {"action": "SKIP", "reason": "daily_limit", "message": msg}

    # ── Guard: VIX check ──────────────────────────────────────
    vix = market_data.get("india_vix")
    if vix and vix > 25:
        msg = f"[Options] VIX too high ({vix}) — options premiums expensive. Skipping."
        print(msg)
        return {"action": "SKIP", "reason": "high_vix", "message": msg}

    # ── Step 1: Load instruments ──────────────────────────────
    print("[Options] Loading NFO instrument list...")
    instruments = get_fno_instruments(kite)
    if not instruments:
        return {"action": "SKIP", "reason": "no_instruments"}

    # ── Step 2: Get spot prices for indices + watchlist ───────
    # Indices
    index_quotes = {}
    try:
        raw = kite.quote(["NSE:NIFTY 50", "NSE:NIFTY BANK"])
        index_quotes["NIFTY"]     = raw.get("NSE:NIFTY 50",   {}).get("last_price", 0)
        index_quotes["BANKNIFTY"] = raw.get("NSE:NIFTY BANK", {}).get("last_price", 0)
    except Exception as e:
        print(f"[Options] Index quote failed: {e}")

    # Stocks from F&O watchlist
    stock_quotes = {}
    try:
        keys = [f"NSE:{s}" for s in fno_watchlist]
        raw  = kite.quote(keys)
        for sym in fno_watchlist:
            price = raw.get(f"NSE:{sym}", {}).get("last_price", 0)
            if price > 0:
                stock_quotes[sym] = price
    except Exception as e:
        print(f"[Options] Stock quote failed: {e}")

    # ── Step 3: Build options chain ───────────────────────────
    options_data = {}

    # Indices first
    for idx, spot in index_quotes.items():
        if spot > 0:
            print(f"[Options] Fetching {idx} options (spot: {spot})...")
            opts = get_atm_options(kite, instruments, idx, spot, num_strikes=5)
            if opts:
                options_data[idx] = opts

    # Top 5 liquid stocks from watchlist (limit to save time)
    for sym in fno_watchlist[:5]:
        spot = stock_quotes.get(sym, 0)
        if spot > 0:
            print(f"[Options] Fetching {sym} options (spot: {spot})...")
            opts = get_atm_options(kite, instruments, sym, spot, num_strikes=3)
            if opts:
                options_data[sym] = opts

    if not options_data:
        msg = "[Options] No options data available within budget. Skipping."
        print(msg)
        return {"action": "SKIP", "reason": "no_options_in_budget", "message": msg}

    # ── Step 4: Ask Claude ────────────────────────────────────
    print("[Options] 🤖 Asking Claude for options decision...")
    decision = ask_claude_for_options_trade(
        options_data      = options_data,
        market_data       = market_data,
        portfolio_summary = portfolio_summary,
        technical_summary = technical_summary,
    )

    print(f"[Options] Claude decision: {decision.get('action')} | "
          f"Confidence: {decision.get('confidence')} | "
          f"{decision.get('reasoning', '')[:80]}...")

    # ── Step 5: Place order if BUY ────────────────────────────
    order_id = None
    if decision.get("action") == "BUY" and decision.get("confidence") in ("HIGH", "MEDIUM"):
        order_id = place_options_order(kite, decision)
        decision["order_id"] = order_id
        decision["order_placed"] = order_id is not None
    else:
        print(f"[Options] No trade placed. Reason: {decision.get('reasoning', 'N/A')}")
        decision["order_placed"] = False

    return decision


# ─────────────────────────────────────────────────────────────
#  STANDALONE TEST (dry run, no real orders)
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("options_trader.py loaded OK.")
    print(f"Max budget per trade : Rs.{MAX_FNO_BUDGET}")
    print(f"Max trades per day   : {MAX_FNO_TRADES_DAY}")
    print("Run via auto_investor_v3.py for live trading.")
