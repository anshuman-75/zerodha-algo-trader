# AutoInvestor v3

An automated trading bot for the Indian stock market — built on Zerodha Kite API, powered by Claude AI, and managed via Telegram.

> **Status:** Live as of April 10, 2026 | Server: OneProvider France | Ubuntu 20.04

---

## What it does

AutoInvestor v3 runs fully autonomously during market hours. It scans the NSE market at key intervals, uses Claude AI to analyse signals and decide trades, places equity and F&O orders through Zerodha, and sends you a Telegram report after every run — all without any manual intervention.

**Scheduled runs:** 9:15 AM · 9:45 AM · 11:00 AM · 1:00 PM · 3:00 PM IST (Mon–Fri)

---

## Features

- **Pre-market scan** — NSE top actives, gainers, losers, VIX, PCR, FII/DII data at 9:15 AM
- **AI-driven decisions** — Claude analyses signals and picks BUY/SELL with confidence scores
- **F&O trading** — Options chain analysis, CE/PE selection, within a strict Rs. 1,500 test budget
- **Automated SIP** — Weekly NIFTYBEES (Rs. 500) and JUNIORBEES (Rs. 250) investments
- **Profit booking** — Auto-sells 50% of a position when it gains 8%
- **Stop-loss** — Auto-exits if any position loses more than 8%
- **Telegram control** — Login flow, token refresh, and reports all via Telegram
- **systemd service** — Survives SSH drops, auto-restarts on crash, starts on reboot

---

## Project structure

```
investor_v3/
├── auto_investor_v3.py     # Main runner — APScheduler, calls all modules
├── market_scanner.py       # Pre-market scan — VIX, PCR, FII/DII, watchlist builder
├── options_trader.py       # F&O brain — options chain, CE/PE selection, order placement
├── fno_tracker.py          # Tracks F&O trades — enforces 1 trade per 2 weeks limit
├── token_manager.py        # Telegram-based Zerodha token refresh
├── config.py               # All settings (API keys, limits, watchlists) — not in repo
├── config.example.py       # Template config — copy this and fill in your values
└── investor.service        # systemd service file
```

---

## Configuration

Copy the example config and fill in your credentials:

```bash
cp config.example.py config.py
nano config.py
```

Key settings:

| Setting | Default | Description |
|---|---|---|
| `MAX_ORDER_VALUE` | Rs. 5,000 | Max per single equity order |
| `MAX_DAILY_SPEND` | Rs. 5,000 | Max equity spend per day |
| `MIN_CASH_RESERVE` | Rs. 1,000 | Always kept untouched |
| `MAX_FNO_ORDER_VALUE` | Rs. 1,500 | Max per options trade |
| `MAX_FNO_TRADES_BIWEEKLY` | 1 | Max F&O trades per 2 weeks |
| `MAX_VIX_FOR_FNO` | 25 | Skip options if VIX above this |
| `PROFIT_BOOKING_PCT` | 8% | Sell 50% when position gains this |
| `STOP_LOSS_PCT` | 8% | Exit if position loses this |

---

## Setup

### Prerequisites

- Python 3.11+
- A [Zerodha](https://zerodha.com) account with Kite API access
- An [Anthropic](https://anthropic.com) API key (for Claude)
- A Telegram bot token

### Install dependencies

```bash
cd ~/investor_v3
pip3.11 install -r requirements.txt
```

### Enable the systemd service

```bash
sudo cp investor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable investor
sudo systemctl start investor
```

### Zerodha token setup

On first run (or after the daily 6 AM token expiry), send `/login` to your Telegram bot. It will send you a login link — open it in an **incognito window**, complete the login, paste the `request_token` back to the bot within 2 minutes.

---

## Daily management

```bash
# Check if bot is running
sudo systemctl status investor

# Follow live logs
journalctl -u investor -f

# Attach to screen session
screen -r investor_v3   # Ctrl+A then D to detach

# Restart bot
sudo systemctl restart investor

# Check F&O trade history
python3.11 fno_tracker.py

# View logs
cat ~/investor_v3/investor_log.txt
```

---

## Watchlist

- **Equity:** 22 stocks (large-cap NSE)
- **F&O:** 15 stocks (options-eligible)

Dynamic additions from the morning scan (NSE top actives, unusual movers).

---

## Safety limits

The bot is designed to be conservative by default:

- Never spends below the `MIN_CASH_RESERVE` threshold
- F&O trades capped at 1 per day and 1 per 2 weeks
- F&O only trades on HIGH confidence signals
- F&O skipped entirely if VIX > 25
- All orders go through a final Claude review before placement

---

## Known quirks

| Issue | Fix |
|---|---|
| `request_token` expires fast | Paste it within 2 minutes |
| Zerodha login fails | Always use incognito window |
| Token expires at 6 AM | Telegram login flow handles this automatically |
| pip `--break-system-packages` error | Use `pip3.11 install` without that flag on this server |

---

## Disclaimer

This bot places real trades with real money. Use it at your own risk. Past performance of any algorithm is not a guarantee of future results. Always monitor your positions and maintain a sufficient cash buffer.

---

*Built by Anshuman · April 2026*
