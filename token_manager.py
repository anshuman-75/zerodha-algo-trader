"""
token_manager.py — Zerodha Token Manager for Auto-Investor v3
Solves the daily 6 AM token expiry problem without manual SSH.

Flow:
1. Bot detects token is expired or missing
2. Sends Telegram message to Anshuman with login URL
3. Anshuman clicks link, logs in, copies request_token from URL
4. Anshuman sends the request_token to the Telegram bot
5. token_manager catches it, generates new access_token
6. Saves to config.py and resumes the bot automatically

No SSH needed. Everything via Telegram on your phone.
"""

import re
import time
import datetime
import requests
import config
from kiteconnect import KiteConnect


# ─────────────────────────────────────────────────────────────
#  TELEGRAM HELPERS
# ─────────────────────────────────────────────────────────────

def send_telegram(message, parse_mode="HTML"):
    """Sends a message to Anshuman's Telegram."""
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={
            "chat_id":    config.TELEGRAM_CHAT_ID,
            "text":       message,
            "parse_mode": parse_mode,
        }, timeout=10)
        return resp.json().get("ok", False)
    except Exception as e:
        print(f"[Token] Telegram send failed: {e}")
        return False


def get_latest_telegram_message(after_timestamp=None):
    """
    Polls Telegram for the latest message from Anshuman.
    Returns the message text if it's newer than after_timestamp.
    """
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates"
    try:
        resp = requests.get(url, params={"limit": 10, "timeout": 5}, timeout=15)
        data = resp.json()

        if not data.get("ok"):
            return None

        updates = data.get("result", [])
        if not updates:
            return None

        # Get most recent message from our chat
        for update in reversed(updates):
            msg = update.get("message", {})
            chat_id  = str(msg.get("chat", {}).get("id", ""))
            msg_date = msg.get("date", 0)
            text     = msg.get("text", "").strip()

            # Only accept messages from Anshuman's chat
            if chat_id != str(config.TELEGRAM_CHAT_ID):
                continue

            # Only accept messages newer than when we sent the login prompt
            if after_timestamp and msg_date <= after_timestamp:
                continue

            if text:
                return text

        return None

    except Exception as e:
        print(f"[Token] Telegram poll failed: {e}")
        return None


# ─────────────────────────────────────────────────────────────
#  TOKEN VALIDATION
# ─────────────────────────────────────────────────────────────

def is_token_valid(kite):
    """
    Checks if the current access token is valid by making a
    lightweight API call (fetch profile).
    Returns True if valid, False if expired/invalid.
    """
    if not config.ZERODHA_ACCESS_TOKEN:
        return False
    try:
        kite.set_access_token(config.ZERODHA_ACCESS_TOKEN)
        kite.profile()   # lightweight call — just fetches account info
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────
#  TOKEN SAVE
# ─────────────────────────────────────────────────────────────

def save_access_token(new_token):
    """
    Saves the new access token to config.py on disk.
    Also updates config module in memory so bot uses it immediately.
    """
    try:
        with open("config.py", "r") as f:
            content = f.read()

        content = re.sub(
            r'ZERODHA_ACCESS_TOKEN\s*=\s*".*?"',
            f'ZERODHA_ACCESS_TOKEN = "{new_token}"',
            content
        )

        with open("config.py", "w") as f:
            f.write(content)

        # Update in-memory config immediately
        config.ZERODHA_ACCESS_TOKEN = new_token
        print(f"[Token] ✅ Access token saved to config.py")
        return True

    except Exception as e:
        print(f"[Token] ❌ Failed to save token: {e}")
        return False


# ─────────────────────────────────────────────────────────────
#  MAIN: TELEGRAM-BASED LOGIN FLOW
# ─────────────────────────────────────────────────────────────

def refresh_token_via_telegram(kite, timeout_minutes=10):
    """
    Full Telegram-based token refresh flow.

    1. Generates Zerodha login URL
    2. Sends it to Anshuman on Telegram
    3. Waits for Anshuman to paste request_token back
    4. Exchanges it for access_token
    5. Saves to config.py
    6. Returns authenticated kite instance

    timeout_minutes: how long to wait for response before giving up
    """
    print("\n[Token] 🔑 Access token expired. Starting Telegram login flow...")

    login_url = kite.login_url()
    now_unix  = int(time.time())

    # ── Send login instructions to Telegram ──────────────────
    message = (
        "🔐 <b>Zerodha Login Required</b>\n\n"
        "Your access token has expired. Follow these steps:\n\n"
        "1️⃣ Open this link in <b>Incognito browser</b>:\n"
        f"<code>{login_url}</code>\n\n"
        "2️⃣ Log in with your Zerodha credentials\n\n"
        "3️⃣ After login, you'll be redirected to a URL like:\n"
        "<code>http://127.0.0.1/?request_token=XXXXXX&action=login&status=success</code>\n\n"
        "4️⃣ Copy ONLY the <code>request_token</code> value (the part after <code>request_token=</code>)\n\n"
        "5️⃣ Reply to THIS message with just the token\n\n"
        f"⏳ Waiting {timeout_minutes} minutes for your response..."
    )

    sent = send_telegram(message)
    if not sent:
        print("[Token] ❌ Failed to send Telegram message. Falling back to terminal input.")
        return _fallback_terminal_login(kite)

    print(f"[Token] 📱 Login instructions sent to Telegram. Waiting up to {timeout_minutes} mins...")

    # ── Poll for response ─────────────────────────────────────
    deadline    = time.time() + (timeout_minutes * 60)
    poll_interval = 5   # check every 5 seconds
    reminder_sent = False

    while time.time() < deadline:
        time.sleep(poll_interval)

        text = get_latest_telegram_message(after_timestamp=now_unix)

        if not text:
            # Send a reminder halfway through
            elapsed = time.time() - now_unix
            if elapsed > (timeout_minutes * 30) and not reminder_sent:
                remaining = int((deadline - time.time()) / 60)
                send_telegram(
                    f"⏳ Still waiting for your request_token...\n"
                    f"You have {remaining} minute(s) left.\n\n"
                    f"Just reply with the token value from the redirect URL."
                )
                reminder_sent = True
            continue

        # Extract request_token from message
        # Accept both raw token and full URL pasted by user
        request_token = _extract_request_token(text)

        if not request_token:
            send_telegram(
                "❓ Couldn't find a valid request_token in your message.\n\n"
                "Please send ONLY the token value, for example:\n"
                "<code>AbCdEfGhIjKlMnOpQrStUvWx12345678</code>"
            )
            continue

        # ── Exchange for access token ─────────────────────────
        print(f"[Token] Got request_token: {request_token[:10]}... Exchanging...")
        try:
            session_data = kite.generate_session(
                request_token,
                api_secret=config.ZERODHA_API_SECRET
            )
            access_token = session_data["access_token"]
            kite.set_access_token(access_token)
            save_access_token(access_token)

            # Confirm on Telegram
            now_str = datetime.datetime.now().strftime("%d %b %Y, %I:%M %p")
            send_telegram(
                f"✅ <b>Login Successful!</b>\n\n"
                f"🕐 Time: {now_str}\n"
                f"🤖 Auto-Investor v3 is resuming...\n\n"
                f"You'll receive the daily analysis report shortly."
            )

            print("[Token] ✅ Token refreshed successfully via Telegram!")
            return kite

        except Exception as e:
            err_msg = str(e)
            print(f"[Token] ❌ Token exchange failed: {err_msg}")
            send_telegram(
                f"❌ <b>Login Failed</b>\n\n"
                f"Error: <code>{err_msg}</code>\n\n"
                "Please try again — reply with a fresh request_token.\n"
                "(Tokens expire quickly, generate a new one)"
            )
            # Reset timestamp to accept new message
            now_unix = int(time.time())
            continue

    # ── Timeout ───────────────────────────────────────────────
    print(f"[Token] ⏰ Timeout after {timeout_minutes} mins. No token received.")
    send_telegram(
        f"⏰ <b>Login Timeout</b>\n\n"
        f"No response received in {timeout_minutes} minutes.\n"
        "The bot will skip today's analysis.\n\n"
        "To restart manually:\n"
        "<code>screen -r investor</code>\n"
        "<code>python3.11 auto_investor_v3.py</code>"
    )
    return None


def _extract_request_token(text):
    """
    Extracts request_token from either:
    - Raw token string: "AbCdEfGhIjKlMnOpQrStUvWx12345678"
    - Full URL: "http://127.0.0.1/?request_token=AbCd...&action=login"
    """
    # Try extracting from URL first
    url_match = re.search(r"request_token=([A-Za-z0-9]+)", text)
    if url_match:
        return url_match.group(1)

    # Otherwise treat the whole message as the token
    # Zerodha request tokens are alphanumeric, ~32 chars
    cleaned = text.strip().replace(" ", "").replace("\n", "")
    if re.match(r"^[A-Za-z0-9]{20,64}$", cleaned):
        return cleaned

    return None


def _fallback_terminal_login(kite):
    """
    Fallback: original terminal-based login if Telegram fails.
    Same as the original zerodha.py login() function.
    """
    print("\n[Token] Falling back to terminal login...")
    print(f"\n1. Open this URL in Incognito:\n\n   {kite.login_url()}\n")
    request_token = input("Paste request_token here: ").strip()

    try:
        data = kite.generate_session(request_token, api_secret=config.ZERODHA_API_SECRET)
        kite.set_access_token(data["access_token"])
        save_access_token(data["access_token"])
        print("[Token] ✅ Logged in via terminal fallback.")
        return kite
    except Exception as e:
        print(f"[Token] ❌ Terminal login failed: {e}")
        return None


# ─────────────────────────────────────────────────────────────
#  ENTRY POINT — used by auto_investor_v3.py
# ─────────────────────────────────────────────────────────────

def ensure_valid_token(kite, timeout_minutes=10):
    """
    Call this at bot startup and before each analysis run.

    - If token is valid → returns kite immediately (no action)
    - If token is expired → triggers Telegram login flow
    - Returns authenticated kite instance, or None if login fails
    """
    if is_token_valid(kite):
        print("[Token] ✅ Access token is valid.")
        return kite

    print("[Token] ⚠️  Access token invalid or expired.")
    return refresh_token_via_telegram(kite, timeout_minutes=timeout_minutes)


# ─────────────────────────────────────────────────────────────
#  STANDALONE TEST
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Testing token_manager.py...")
    print(f"Telegram Bot : {config.TELEGRAM_BOT_TOKEN[:10]}...")
    print(f"Chat ID      : {config.TELEGRAM_CHAT_ID}")

    # Test sending a message
    ok = send_telegram("🧪 token_manager.py test message — ignore this.")
    print(f"Telegram send test: {'✅ OK' if ok else '❌ Failed'}")

    # Test token validation
    kite = KiteConnect(api_key=config.ZERODHA_API_KEY)
    valid = is_token_valid(kite)
    print(f"Current token valid: {'✅ Yes' if valid else '❌ No (needs refresh)'}")
