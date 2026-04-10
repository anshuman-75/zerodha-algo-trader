"""
config.py — Auto-Investor v3 Configuration
Fill in your credentials. All rules and limits are set here.
"""

# ─────────────────────────────────────────────────────────────
#  CREDENTIALS
# ─────────────────────────────────────────────────────────────
ZERODHA_API_KEY      = ""
ZERODHA_API_SECRET   = ""
ZERODHA_ACCESS_TOKEN = ""    # Leave blank — auto-filled on login

ANTHROPIC_API_KEY    = ""    # Your Anthropic API key

TELEGRAM_BOT_TOKEN   = ""    # From @BotFather
TELEGRAM_CHAT_ID     = ""    # Your Telegram chat ID

# ─────────────────────────────────────────────────────────────
#  SAFETY LIMITS — Equity
# ─────────────────────────────────────────────────────────────

# Max money Claude can invest in a SINGLE equity order (₹)
MAX_ORDER_VALUE = 1000

# Max money Claude can invest in a SINGLE DAY across all equity orders (₹)
MAX_DAILY_SPEND = 1000

# Minimum cash balance to always keep untouched (₹)
MIN_CASH_RESERVE = 1000

# ─────────────────────────────────────────────────────────────
#  SAFETY LIMITS — F&O Options
# ─────────────────────────────────────────────────────────────

# Max budget per single options trade (₹)
MAX_FNO_ORDER_VALUE = 1500

# Max number of options trades per day (hard limit)
MAX_FNO_TRADES_DAY = 1

# Max number of options trades per 2 weeks (14 days)
# Set to 1 → only 1 F&O trade allowed every 2 weeks
MAX_FNO_TRADES_BIWEEKLY = 1

# Skip options trading if VIX is above this level
# (high VIX = expensive premiums = bad time to buy options)
MAX_VIX_FOR_FNO = 25

# Only trade options if Claude confidence is HIGH
# Set to False to also allow MEDIUM confidence trades
FNO_HIGH_CONFIDENCE_ONLY = True

# ─────────────────────────────────────────────────────────────
#  SCHEDULER SETTINGS
# ─────────────────────────────────────────────────────────────

# All times are IST (Asia/Kolkata)
SCHEDULE = [
    {"hour": 9,  "minute": 15, "label": "Pre-Market Scan"},      # scanner only
    {"hour": 9,  "minute": 45, "label": "Morning Analysis"},      # SIP + equity + F&O
    {"hour": 11, "minute": 0,  "label": "Mid-Morning Check"},     # equity + F&O
    {"hour": 13, "minute": 0,  "label": "Afternoon Check"},       # equity + F&O
    {"hour": 15, "minute": 0,  "label": "Pre-Close Check"},       # equity + F&O
]

# ─────────────────────────────────────────────────────────────
#  YOUR INVESTMENT RULES  (Claude will always follow these)
# ─────────────────────────────────────────────────────────────
INVESTMENT_RULES = """
EQUITY RULES:
1. ALWAYS keep a minimum cash reserve of ₹1,000 untouched.
2. Never invest more than ₹5,000 in a single order.
3. Prefer index ETFs (NIFTYBEES, JUNIORBEES) for stable allocation.
4. For growth stocks, only pick large-cap NSE-listed companies.
5. Never buy penny stocks or stocks below ₹50.
6. Never invest more than 20% of portfolio in a single stock.
7. Rebalance toward safer assets if overall portfolio P&L drops below -10%.
8. Do NOT trade on days with major news events or high volatility (VIX > 20).
9. Prefer buying during morning dips (9:30–10:30 AM IST).
10. Never sell a holding that is less than 30 days old unless P&L drops below -8%.

F&O OPTIONS RULES:
11. ONLY buy options (CE or PE) — never sell/write options.
12. Maximum ₹1,500 per options trade. Never exceed this.
13. Only trade options when signal confidence is HIGH.
14. Skip options if India VIX is above 25.
15. Maximum 1 options trade per 2 weeks.
16. Prefer Nifty/BankNifty index options over stock options (more liquid).
17. Only buy options with high Open Interest (liquid strikes).
18. Never buy options expiring same day (too risky).
19. Prefer options expiring at least 3-7 days away.
20. If no strong directional signal exists → SKIP, do not force a trade.
"""

# ─────────────────────────────────────────────────────────────
#  SCHEDULED SIP INVESTMENTS
# ─────────────────────────────────────────────────────────────
# These run regardless of Claude's analysis (rules-based)
SCHEDULED_INVESTMENTS = [
    {"symbol": "NIFTYBEES",  "amount_inr": 500, "day": "Monday"},
    {"symbol": "JUNIORBEES", "amount_inr": 250, "day": "Wednesday"},
]

# ─────────────────────────────────────────────────────────────
#  EQUITY WATCHLIST
# ─────────────────────────────────────────────────────────────
# Stocks Claude will analyse for equity buying/selling
WATCHLIST = [
    # Original watchlist
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
    "WIPRO", "AXISBANK", "LT", "COFORGE", "BAJFINANCE", "TITAN",
    "NIFTYBEES", "JUNIORBEES",

    # New additions — v3
    "SBIN", "TATAMOTORS", "MARUTI", "SUNPHARMA",
    "TATASTEEL", "HINDALCO", "ONGC", "POWERGRID", "KOTAKBANK",
]

# ─────────────────────────────────────────────────────────────
#  F&O WATCHLIST  (liquid stocks only — options must exist)
# ─────────────────────────────────────────────────────────────
# These are the most liquid F&O stocks on NSE
# Options on these have tight spreads and high OI
FNO_WATCHLIST = [
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "AXISBANK",
    "BAJFINANCE", "INFY", "WIPRO", "LT", "SBIN",
    "TATAMOTORS", "KOTAKBANK", "SUNPHARMA", "TATASTEEL", "ADANIENT",
]

# Index options — always analysed for F&O
# (Nifty and BankNifty are most liquid in all of NSE)
FNO_INDICES = ["NIFTY", "BANKNIFTY"]

# ─────────────────────────────────────────────────────────────
#  PROFIT BOOKING RULE  (v3 new feature)
# ─────────────────────────────────────────────────────────────

# If any holding gains more than this % → sell 50% automatically
PROFIT_BOOKING_PCT = 8.0     # 8% gain = sell half

# If any holding loses more than this % → sell to cut losses
STOP_LOSS_PCT = 8.0          # 8% loss = exit position

# ─────────────────────────────────────────────────────────────
#  LOG FILE
# ─────────────────────────────────────────────────────────────
LOG_FILE = "investor_log.txt"
