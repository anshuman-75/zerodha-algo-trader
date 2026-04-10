"""
telegram_reporter.py — Sends daily investment reports to Telegram.

Sends a beautiful report every morning after Claude's analysis showing:
- Portfolio summary
- Market sentiment
- Claude's reasoning
- Orders placed
- Daily P&L
"""

import requests
import datetime
import config


def send_message(text):
    """Sends a message to Telegram."""
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id":    config.TELEGRAM_CHAT_ID,
        "text":       text,
        "parse_mode": "HTML",
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.ok
    except Exception as e:
        print(f"Telegram error: {e}")
        return False


def send_daily_report(portfolio, decision, orders_placed, daily_spent):
    """
    Sends a full daily report to Telegram after Claude's analysis.
    """
    now = datetime.datetime.now().strftime("%d %b %Y, %I:%M %p IST")

    # Sentiment emoji
    sentiment = decision.get("market_sentiment", "neutral").lower()
    if sentiment == "bullish":
        sentiment_emoji = "🟢 BULLISH"
    elif sentiment == "bearish":
        sentiment_emoji = "🔴 BEARISH"
    else:
        sentiment_emoji = "🟡 NEUTRAL"

    # Portfolio stats
    cash      = portfolio.get("cash", 0)
    holdings  = portfolio.get("holdings", [])
    total_pnl = sum(h.get("pnl", 0) for h in holdings)
    pnl_emoji = "📈" if total_pnl >= 0 else "📉"
    pnl_sign  = "+" if total_pnl >= 0 else ""

    # Build orders section
    actions = decision.get("actions", [])
    orders_text = ""
    for a in actions:
        if a["action"] == "buy":
            orders_text += f"\n  🛒 BUY {a['symbol']} — {a['reason']}"
        elif a["action"] == "sell":
            orders_text += f"\n  💰 SELL {a['symbol']} — {a['reason']}"
        elif a["action"] == "hold":
            orders_text += f"\n  ⏸ HOLD — {a['reason']}"

    # Build holdings section
    holdings_text = ""
    if holdings:
        for h in holdings[:5]:  # show max 5
            pnl   = h.get("pnl", 0)
            sign  = "+" if pnl >= 0 else ""
            emoji = "📈" if pnl >= 0 else "📉"
            holdings_text += f"\n  {emoji} {h['tradingsymbol']}: {sign}₹{pnl:,.0f}"
        if len(holdings) > 5:
            holdings_text += f"\n  ... and {len(holdings)-5} more"
    else:
        holdings_text = "\n  No holdings yet"

    message = f"""🤖 <b>Claude Investor — Daily Report</b>
📅 {now}

━━━━━━━━━━━━━━━━━━━━━
📊 <b>MARKET SENTIMENT</b>
{sentiment_emoji}

🧠 <b>CLAUDE'S REASONING</b>
{decision.get('reasoning', 'No reasoning provided')}

━━━━━━━━━━━━━━━━━━━━━
⚡ <b>TODAY'S ACTIONS</b>{orders_text}

💸 <b>Amount Invested Today:</b> ₹{daily_spent:,.0f}
📦 <b>Orders Placed:</b> {orders_placed}

━━━━━━━━━━━━━━━━━━━━━
💼 <b>PORTFOLIO</b>
💵 Cash Available: ₹{cash:,.0f}
{pnl_emoji} Overall P&L: {pnl_sign}₹{total_pnl:,.0f}

<b>Holdings:</b>{holdings_text}

━━━━━━━━━━━━━━━━━━━━━
<i>Next run: Tomorrow 9:45 AM IST</i>"""

    return send_message(message)


def send_order_alert(action, symbol, quantity, order_id, reason):
    """Sends instant alert when an order is placed."""
    emoji = "🛒" if action.upper() == "BUY" else "💰"
    message = f"""{emoji} <b>Order Placed</b>

<b>Action:</b> {action.upper()}
<b>Stock:</b> {symbol}
<b>Quantity:</b> {quantity} shares
<b>Order ID:</b> {order_id}
<b>Reason:</b> {reason}

<i>Check Kite app for execution status</i>"""
    return send_message(message)


def send_error_alert(error_msg):
    """Sends alert if something goes wrong."""
    message = f"""⚠️ <b>Investor Bot Error</b>

{error_msg}

<i>Please check the server logs</i>"""
    return send_message(message)


def send_startup_message():
    """Sends a message when the bot starts up."""
    message = f"""🚀 <b>Claude Investor Bot Started</b>

✅ Connected to Zerodha
✅ Technical analysis ready
✅ Scheduler running

<b>Next analysis:</b> 9:45 AM IST on market days
<i>You'll receive a report after each daily run</i>"""
    return send_message(message)
