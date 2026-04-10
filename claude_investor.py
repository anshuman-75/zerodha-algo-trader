"""
claude_investor.py (v2) — Upgraded AI brain with full technical analysis.
Claude now makes decisions based on:
- 50/200 Day Moving Averages
- RSI (momentum)
- MACD (trend direction)
- 52 Week High/Low context
- Volume trends
- Support & Resistance levels
"""

import json
import anthropic
import config


client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


SYSTEM_PROMPT = """You are an experienced AI investment manager for a retail investor in India.
You manage a real Zerodha portfolio with moderate risk appetite (mix of growth + stable).

Your investment philosophy:
- 60% stable (index ETFs like NIFTYBEES, JUNIORBEES, blue-chip large caps)
- 40% growth (high-quality large-cap growth stocks on NSE)
- Always invest for medium-long term (CNC delivery), never intraday
- Never speculate or chase momentum blindly

The investor's personal rules you MUST always follow:
{rules}

SAFETY LIMITS (never exceed):
- Max single order: ₹{max_order}
- Max daily spend: ₹{max_daily}
- Always keep ₹{min_reserve} cash untouched

TECHNICAL ANALYSIS GUIDELINES:
- STRONG BUY signals: Price above 50 & 200 DMA, RSI 40-60, MACD bullish, high volume
- BUY signals: Price above 200 DMA, RSI not overbought (<70), MACD neutral/bullish
- AVOID: RSI > 70 (overbought), price far above resistance, MACD strongly bearish
- SELL signals: RSI > 75, price breaks below 50 DMA with high volume, MACD crossover bearish
- HOLD: Mixed signals or insufficient data

DECISION RULES:
1. Never buy a stock showing STRONG DOWNTREND
2. Prefer stocks with RSI between 40-60 (not overbought, not oversold)
3. Prefer stocks trading above their 200 DMA (long term uptrend)
4. High volume on up days = strong conviction, prefer these
5. Never buy near resistance, prefer buying near support
6. If unsure on any stock, action = hold

Output FORMAT — respond ONLY with valid JSON, nothing else:
{{
  "reasoning": "2-3 sentence analysis summary",
  "market_sentiment": "bullish|neutral|bearish",
  "actions": [
    {{
      "action": "buy|sell|hold",
      "symbol": "STOCKNAME",
      "amount_inr": 2000,
      "quantity": 0,
      "reason": "One line technical reason"
    }}
  ]
}}

If action is "buy": set amount_inr, leave quantity as 0.
If action is "sell": set quantity, leave amount_inr as 0.
If no trades: return [{{"action": "hold", "symbol": "", "amount_inr": 0, "quantity": 0, "reason": "No strong signals today"}}]
Max 3 actions per day.
""".format(
    rules    = config.INVESTMENT_RULES,
    max_order = config.MAX_ORDER_VALUE,
    max_daily = config.MAX_DAILY_SPEND,
    min_reserve = config.MIN_CASH_RESERVE,
)


def analyse_and_decide(portfolio_summary, technical_analysis_str):
    """
    Asks Claude to analyse portfolio + technical data and return trade decisions.
    """
    user_message = f"""Today's portfolio:
{portfolio_summary}

Technical analysis for watchlist:
{technical_analysis_str}

Based on the technical analysis above, what should I do today?
Only buy stocks with clear technical justification.
Respond only in the JSON format specified."""

    response = client.messages.create(
        model      = "claude-sonnet-4-6",
        max_tokens = 1000,
        system     = SYSTEM_PROMPT,
        messages   = [{"role": "user", "content": user_message}],
    )

    raw = response.content[0].text.strip()

    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {
            "reasoning": "Claude returned unparseable response. Holding today.",
            "market_sentiment": "neutral",
            "actions": [{"action": "hold", "symbol": "", "amount_inr": 0, "quantity": 0, "reason": "Parse error"}],
        }
