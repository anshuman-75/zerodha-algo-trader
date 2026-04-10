"""
technical_analysis.py — Fetches historical data from Kite and computes
technical indicators for Claude to make smarter decisions.

Indicators computed:
- 50 Day & 200 Day Moving Average (trend)
- RSI (momentum — overbought/oversold)
- MACD (trend direction)
- 52 Week High/Low (price context)
- Volume trend (buying/selling pressure)
- Support & Resistance levels
"""

import datetime
import pandas as pd
import numpy as np


# ── Fetch historical data from Kite ───────────────────────────────────────────

def get_historical_data(kite, symbol, days=250):
    """
    Fetches up to `days` days of daily OHLCV data for a symbol from Kite.
    Returns a pandas DataFrame or None if failed.
    """
    try:
        instrument = kite.ltp(f"NSE:{symbol}")
        instrument_token = instrument[f"NSE:{symbol}"]["instrument_token"]

        to_date   = datetime.date.today()
        from_date = to_date - datetime.timedelta(days=days + 50)  # buffer for weekends

        records = kite.historical_data(
            instrument_token = instrument_token,
            from_date        = from_date,
            to_date          = to_date,
            interval         = "day",
        )

        if not records:
            return None

        df = pd.DataFrame(records)
        df["date"]   = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        return df

    except Exception as e:
        return None


# ── Technical indicators ───────────────────────────────────────────────────────

def compute_sma(series, window):
    return series.rolling(window=window).mean().iloc[-1]


def compute_rsi(series, period=14):
    delta  = series.diff()
    gain   = delta.where(delta > 0, 0.0)
    loss   = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs  = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(rsi.iloc[-1], 2)


def compute_macd(series):
    ema12  = series.ewm(span=12, adjust=False).mean()
    ema26  = series.ewm(span=26, adjust=False).mean()
    macd   = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist   = macd - signal
    return round(macd.iloc[-1], 2), round(signal.iloc[-1], 2), round(hist.iloc[-1], 2)


def compute_52_week(series):
    last_252 = series.tail(252)
    return round(last_252.max(), 2), round(last_252.min(), 2)


def compute_volume_trend(volume_series):
    """Compares last 5 days average volume vs 20 days average."""
    avg_5  = volume_series.tail(5).mean()
    avg_20 = volume_series.tail(20).mean()
    ratio  = avg_5 / avg_20 if avg_20 > 0 else 1
    if ratio > 1.5:
        return "HIGH (strong interest)"
    elif ratio > 1.0:
        return "ABOVE AVERAGE"
    elif ratio > 0.7:
        return "NORMAL"
    else:
        return "LOW (weak interest)"


def compute_support_resistance(df):
    """Simple support/resistance using recent pivot points."""
    recent = df.tail(20)
    support    = round(recent["low"].min(), 2)
    resistance = round(recent["high"].max(), 2)
    return support, resistance


def compute_trend(df):
    """Determines trend based on price vs moving averages."""
    close  = df["close"]
    ltp    = close.iloc[-1]
    sma50  = compute_sma(close, 50)
    sma200 = compute_sma(close, 200)

    if ltp > sma50 > sma200:
        return "STRONG UPTREND"
    elif ltp > sma200:
        return "UPTREND"
    elif ltp < sma50 < sma200:
        return "STRONG DOWNTREND"
    elif ltp < sma200:
        return "DOWNTREND"
    else:
        return "SIDEWAYS"


# ── Main analysis function ─────────────────────────────────────────────────────

def analyse_symbol(kite, symbol):
    """
    Returns a dict of technical indicators for a symbol.
    Returns None if data unavailable.
    """
    df = get_historical_data(kite, symbol)
    if df is None or len(df) < 50:
        return None

    close  = df["close"]
    volume = df["volume"]
    ltp    = close.iloc[-1]

    sma50  = compute_sma(close, 50)
    sma200 = compute_sma(close, 200) if len(df) >= 200 else None
    rsi    = compute_rsi(close)
    macd, signal, hist = compute_macd(close)
    week52_high, week52_low = compute_52_week(close)
    vol_trend  = compute_volume_trend(volume)
    support, resistance = compute_support_resistance(df)
    trend = compute_trend(df)

    # Distance from 52 week high/low
    pct_from_high = round((ltp - week52_high) / week52_high * 100, 1)
    pct_from_low  = round((ltp - week52_low)  / week52_low  * 100, 1)

    # RSI interpretation
    if rsi > 70:
        rsi_signal = "OVERBOUGHT (avoid buying)"
    elif rsi < 30:
        rsi_signal = "OVERSOLD (potential buy)"
    elif 40 <= rsi <= 60:
        rsi_signal = "NEUTRAL"
    else:
        rsi_signal = "NORMAL"

    # MACD interpretation
    if hist > 0 and macd > signal:
        macd_signal = "BULLISH (momentum rising)"
    elif hist < 0 and macd < signal:
        macd_signal = "BEARISH (momentum falling)"
    else:
        macd_signal = "NEUTRAL"

    return {
        "symbol":       symbol,
        "ltp":          round(ltp, 2),
        "trend":        trend,
        "sma50":        round(sma50, 2),
        "sma200":       round(sma200, 2) if sma200 else "N/A",
        "above_sma50":  ltp > sma50,
        "above_sma200": ltp > sma200 if sma200 else None,
        "rsi":          rsi,
        "rsi_signal":   rsi_signal,
        "macd":         macd,
        "macd_signal":  macd_signal,
        "week52_high":  week52_high,
        "week52_low":   week52_low,
        "pct_from_high": pct_from_high,
        "pct_from_low":  pct_from_low,
        "volume_trend": vol_trend,
        "support":      support,
        "resistance":   resistance,
    }


def analyse_watchlist(kite, symbols):
    """
    Analyses all symbols in the watchlist.
    Returns a dict of {symbol: analysis} and a formatted string for Claude.
    """
    results = {}
    for symbol in symbols:
        analysis = analyse_symbol(kite, symbol)
        if analysis:
            results[symbol] = analysis

    return results, format_analysis_for_claude(results)


def format_analysis_for_claude(results):
    """Formats technical analysis into a readable string for Claude."""
    if not results:
        return "Technical analysis unavailable."

    lines = []
    for sym, a in results.items():
        lines.append(f"\n{'='*50}")
        lines.append(f"  {sym} | LTP: ₹{a['ltp']}")
        lines.append(f"{'='*50}")
        lines.append(f"  Trend          : {a['trend']}")
        lines.append(f"  50 DMA         : ₹{a['sma50']} ({'ABOVE' if a['above_sma50'] else 'BELOW'})")
        lines.append(f"  200 DMA        : ₹{a['sma200']} ({'ABOVE' if a['above_sma200'] else 'BELOW'} )" if a['above_sma200'] is not None else f"  200 DMA        : {a['sma200']}")
        lines.append(f"  RSI (14)       : {a['rsi']} → {a['rsi_signal']}")
        lines.append(f"  MACD           : {a['macd']} → {a['macd_signal']}")
        lines.append(f"  52W High       : ₹{a['week52_high']} ({a['pct_from_high']}% from high)")
        lines.append(f"  52W Low        : ₹{a['week52_low']} (+{a['pct_from_low']}% from low)")
        lines.append(f"  Volume         : {a['volume_trend']}")
        lines.append(f"  Support        : ₹{a['support']}")
        lines.append(f"  Resistance     : ₹{a['resistance']}")

    return "\n".join(lines)
