"""
market_scanner.py — Pre-market scanner for Auto-Investor v3
Runs at 9:15 AM IST to build a dynamic watchlist before main analysis.
Fetches: NSE top actives, gainers, losers, India VIX, PCR, FII/DII data.
"""

import requests
import datetime
import json
import config

# ─────────────────────────────────────────────────────────────
#  STATIC F&O ELIGIBLE LIQUID STOCKS (always included)
# ─────────────────────────────────────────────────────────────
FNO_LIQUID_STOCKS = [
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "AXISBANK",
    "BAJFINANCE", "INFY", "WIPRO", "LT", "SBIN",
    "TATAMOTORS", "KOTAKBANK", "SUNPHARMA", "TATASTEEL", "ADANIENT",
]

# NSE headers — required to avoid 401 from NSE website
NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.nseindia.com/",
}


def _get_nse_session():
    """Creates a requests session with NSE cookies (required for API calls)."""
    session = requests.Session()
    session.headers.update(NSE_HEADERS)
    try:
        # Hit NSE homepage first to get cookies
        session.get("https://www.nseindia.com", timeout=10)
    except Exception:
        pass
    return session


def get_most_active(session, top_n=20):
    """Fetches top N most active stocks by volume from NSE."""
    try:
        url = "https://www.nseindia.com/api/live-analysis-volume-gainers"
        resp = session.get(url, timeout=10)
        data = resp.json()
        stocks = []
        for item in data.get("data", [])[:top_n]:
            sym = item.get("symbol", "").strip()
            if sym and _is_valid_equity(sym):
                stocks.append(sym)
        return stocks
    except Exception as e:
        print(f"[Scanner] Most active fetch failed: {e}")
        return []


def get_top_gainers(session, top_n=10):
    """Fetches top N gainers from NSE."""
    try:
        url = "https://www.nseindia.com/api/live-analysis-variations?index=gainers"
        resp = session.get(url, timeout=10)
        data = resp.json()
        stocks = []
        for item in data.get("NIFTY", {}).get("data", [])[:top_n]:
            sym = item.get("symbol", "").strip()
            if sym and _is_valid_equity(sym):
                stocks.append(sym)
        return stocks
    except Exception as e:
        print(f"[Scanner] Top gainers fetch failed: {e}")
        return []


def get_top_losers(session, top_n=10):
    """Fetches top N losers from NSE."""
    try:
        url = "https://www.nseindia.com/api/live-analysis-variations?index=losers"
        resp = session.get(url, timeout=10)
        data = resp.json()
        stocks = []
        for item in data.get("NIFTY", {}).get("data", [])[:top_n]:
            sym = item.get("symbol", "").strip()
            if sym and _is_valid_equity(sym):
                stocks.append(sym)
        return stocks
    except Exception as e:
        print(f"[Scanner] Top losers fetch failed: {e}")
        return []


def get_india_vix(session):
    """Fetches current India VIX value."""
    try:
        url = "https://www.nseindia.com/api/allIndices"
        resp = session.get(url, timeout=10)
        data = resp.json()
        for item in data.get("data", []):
            if item.get("index") == "INDIA VIX":
                vix = float(item.get("last", 0))
                change = float(item.get("percentChange", 0))
                return {"vix": vix, "change_pct": change}
        return {"vix": None, "change_pct": None}
    except Exception as e:
        print(f"[Scanner] VIX fetch failed: {e}")
        return {"vix": None, "change_pct": None}


def get_pcr(session):
    """
    Fetches Nifty Put-Call Ratio from NSE options chain.
    PCR > 1.2 = bullish sentiment, PCR < 0.8 = bearish sentiment.
    """
    try:
        url = "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"
        resp = session.get(url, timeout=15)
        data = resp.json()

        total_call_oi = 0
        total_put_oi  = 0
        records = data.get("records", {}).get("data", [])
        for record in records:
            ce = record.get("CE", {})
            pe = record.get("PE", {})
            total_call_oi += ce.get("openInterest", 0)
            total_put_oi  += pe.get("openInterest", 0)

        pcr = round(total_put_oi / total_call_oi, 3) if total_call_oi > 0 else None
        sentiment = "neutral"
        if pcr:
            if pcr > 1.2:
                sentiment = "bullish"
            elif pcr < 0.8:
                sentiment = "bearish"

        return {
            "pcr": pcr,
            "sentiment": sentiment,
            "total_call_oi": total_call_oi,
            "total_put_oi":  total_put_oi,
        }
    except Exception as e:
        print(f"[Scanner] PCR fetch failed: {e}")
        return {"pcr": None, "sentiment": "unknown"}


def get_fii_dii(session):
    """
    Fetches latest FII/DII buying/selling data from NSE.
    Returns net buy/sell figures for institutional flow analysis.
    """
    try:
        url = "https://www.nseindia.com/api/fiidiiTradeReact"
        resp = session.get(url, timeout=10)
        data = resp.json()

        # Get most recent entry
        entries = data if isinstance(data, list) else data.get("data", [])
        if not entries:
            return {"fii_net": None, "dii_net": None, "date": None}

        latest = entries[0]
        fii_net = float(latest.get("fiiNet", 0) or 0)
        dii_net = float(latest.get("diiNet", 0) or 0)
        date    = latest.get("date", "unknown")

        fii_flow = "buying" if fii_net > 0 else "selling"
        dii_flow = "buying" if dii_net > 0 else "selling"

        return {
            "fii_net":   fii_net,
            "dii_net":   dii_net,
            "fii_flow":  fii_flow,
            "dii_flow":  dii_flow,
            "date":      date,
        }
    except Exception as e:
        print(f"[Scanner] FII/DII fetch failed: {e}")
        return {"fii_net": None, "dii_net": None}


def _is_valid_equity(symbol):
    """
    Basic filter: skip ETFs, bonds, indices, and illiquid names.
    Only allow clean NSE equity symbols (letters only, 2-15 chars).
    """
    if not symbol or len(symbol) < 2 or len(symbol) > 15:
        return False
    if any(char.isdigit() for char in symbol):
        return False  # skip symbols with numbers (e.g. bonds)
    skip_keywords = ["NIFTY", "SENSEX", "LIQUID", "GILT", "GSEC", "BOND"]
    for kw in skip_keywords:
        if kw in symbol.upper():
            return False
    return True


def build_dynamic_watchlist(base_watchlist=None):
    """
    Main function — builds the combined watchlist for the day.

    Returns a dict with:
      - equity_watchlist: merged list of base + dynamic stocks (for equity analysis)
      - fno_watchlist:    liquid F&O stocks (for options trading)
      - market_data:      VIX, PCR, FII/DII (passed to Claude)
      - scan_summary:     plain-English string for logs/Telegram
    """
    print("\n[Scanner] 📡 Starting pre-market scan...")
    session = _get_nse_session()

    # ── 1. Fetch market-wide signals ──────────────────────────
    vix_data  = get_india_vix(session)
    pcr_data  = get_pcr(session)
    fii_data  = get_fii_dii(session)

    # ── 2. Fetch dynamic stock lists ──────────────────────────
    most_active = get_most_active(session, top_n=20)
    gainers     = get_top_gainers(session, top_n=10)
    losers      = get_top_losers(session, top_n=10)

    # ── 3. Merge all into one equity watchlist (deduplicated) ──
    base = list(base_watchlist or config.WATCHLIST)
    combined = list(dict.fromkeys(base + most_active + gainers + losers))

    # ── 4. F&O watchlist = liquid stocks always ────────────────
    fno_watchlist = FNO_LIQUID_STOCKS.copy()

    # ── 5. Build market data summary for Claude ───────────────
    vix_val  = vix_data.get("vix")
    pcr_val  = pcr_data.get("pcr")
    fii_net  = fii_data.get("fii_net")
    dii_net  = fii_data.get("dii_net")

    market_data = {
        "india_vix":     vix_val,
        "vix_change_pct": vix_data.get("change_pct"),
        "vix_signal":    _vix_signal(vix_val),
        "pcr":           pcr_val,
        "pcr_sentiment": pcr_data.get("sentiment", "unknown"),
        "fii_net_cr":    round(fii_net / 100, 2) if fii_net else None,  # convert to Cr
        "dii_net_cr":    round(dii_net / 100, 2) if dii_net else None,
        "fii_flow":      fii_data.get("fii_flow"),
        "dii_flow":      fii_data.get("dii_flow"),
        "fii_date":      fii_data.get("date"),
    }

    # ── 6. Plain-English summary ───────────────────────────────
    lines = ["📡 Pre-Market Scan Complete"]
    lines.append(f"🔴 India VIX : {vix_val or 'N/A'}  →  {_vix_signal(vix_val)}")
    lines.append(f"📊 Nifty PCR : {pcr_val or 'N/A'}  →  {pcr_data.get('sentiment', 'N/A')}")
    if fii_net is not None:
        lines.append(f"🏦 FII       : ₹{fii_net:+,.0f} Cr  ({fii_data.get('fii_flow', '?')})")
    if dii_net is not None:
        lines.append(f"🏦 DII       : ₹{dii_net:+,.0f} Cr  ({fii_data.get('dii_flow', '?')})")
    lines.append(f"📈 Dynamic stocks added : {len(most_active + gainers + losers)} raw → {len(combined)} total after dedup")
    lines.append(f"🎯 Equity watchlist     : {len(combined)} stocks")
    lines.append(f"⚡ F&O watchlist        : {len(fno_watchlist)} stocks")

    scan_summary = "\n".join(lines)
    print(scan_summary)

    return {
        "equity_watchlist": combined,
        "fno_watchlist":    fno_watchlist,
        "market_data":      market_data,
        "scan_summary":     scan_summary,
        "raw": {
            "most_active": most_active,
            "gainers":     gainers,
            "losers":      losers,
        }
    }


def _vix_signal(vix):
    """Converts VIX number to a plain-English signal for Claude."""
    if vix is None:
        return "unknown"
    if vix < 12:
        return "very low volatility — good for options buying (cheap premiums)"
    elif vix < 16:
        return "low volatility — normal market, proceed with analysis"
    elif vix < 20:
        return "moderate volatility — be selective, reduce position sizes"
    elif vix < 25:
        return "high volatility — caution, prefer ETFs over individual stocks"
    else:
        return "extreme volatility — AVOID options buying, premiums very expensive"


def format_market_data_for_claude(market_data):
    """
    Returns a clean string block to include in Claude's prompt.
    """
    vix     = market_data.get("india_vix", "N/A")
    vix_sig = market_data.get("vix_signal", "N/A")
    pcr     = market_data.get("pcr", "N/A")
    pcr_s   = market_data.get("pcr_sentiment", "N/A")
    fii     = market_data.get("fii_net_cr", "N/A")
    dii     = market_data.get("dii_net_cr", "N/A")
    fii_f   = market_data.get("fii_flow", "N/A")
    dii_f   = market_data.get("dii_flow", "N/A")

    return f"""
=== MARKET-WIDE SIGNALS ===
India VIX        : {vix}  →  {vix_sig}
Nifty PCR        : {pcr}  →  {pcr_s}
  (PCR > 1.2 = bulls in control | PCR < 0.8 = bears in control)
FII Net Flow     : ₹{fii} Cr  ({fii_f})
DII Net Flow     : ₹{dii} Cr  ({dii_f})
  (Positive = net buying, Negative = net selling)
===========================
"""


# ─────────────────────────────────────────────────────────────
#  STANDALONE TEST
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    result = build_dynamic_watchlist()
    print("\n── Market Data ──")
    print(json.dumps(result["market_data"], indent=2))
    print("\n── Equity Watchlist ──")
    print(result["equity_watchlist"])
    print("\n── F&O Watchlist ──")
    print(result["fno_watchlist"])
    print("\n── Claude Prompt Block ──")
    print(format_market_data_for_claude(result["market_data"]))
