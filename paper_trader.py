"""
纸面交易脚本
使用真实市场价格 + 真实策略，但不实际下单
虚拟账户状态保存在 paper_state.json，并自动 commit 到仓库
"""

import os
import json
import smtplib
import subprocess
from email.mime.text import MIMEText
from datetime import datetime, timezone
import pandas as pd
import ccxt
from strategy_news import NewsSentimentStrategy

# ============ 配置 ============
SYMBOL = "BTCUSDC"
TIMEFRAME = "1h"
INITIAL_CAPITAL = 500.0
STATE_FILE = "paper_state.json"

GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", GMAIL_USER)


# ============ 状态管理 ============
def load_state():
    """读取虚拟账户状态，不存在则初始化"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "cash": INITIAL_CAPITAL,
        "position": 0.0,
        "entry_price": 0.0,
        "trades": [],
        "created": datetime.now(timezone.utc).isoformat(),
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }


def save_state(state):
    """保存状态到文件"""
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def commit_state():
    """把 paper_state.json 提交到 GitHub 仓库"""
    try:
        subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
        subprocess.run(
            ["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"],
            check=True,
        )
        subprocess.run(["git", "add", STATE_FILE], check=True)

        # 检查是否有变化
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            capture_output=True,
        )
        if result.returncode != 0:
            commit_msg = f"Update paper state {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
            subprocess.run(["git", "commit", "-m", commit_msg], check=True)
            subprocess.run(["git", "push"], check=True)
            print("📤 状态已提交到仓库")
        else:
            print("📤 状态无变化，跳过提交")
    except Exception as e:
        print(f"⚠️ Git 提交失败: {e}")


# ============ 邮件通知 ============
def send_email(subject, body):
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        print("⚠️ Gmail 未配置，跳过邮件")
        return
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = GMAIL_USER
        msg["To"] = NOTIFY_EMAIL
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.send_message(msg)
        print(f"📧 邮件已发送: {subject}")
    except Exception as e:
        print(f"⚠️ 邮件发送失败: {e}")


# ============ 主逻辑 ============
def execute_paper_trade():
    state = load_state()

    # 获取 K 线
    exchange = ccxt.bullish({"enableRateLimit": True})
    exchange.load_markets()
    ohlcv = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=100)
    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)

    # 生成信号
    strategy = NewsSentimentStrategy(
        fast_ema=20,
        slow_ema=50,
        lookback=20,
        sentiment_threshold=0.3,
        news_lookback_hours=72,
    )
    df, sentiment_score, reason = strategy.generate_signals(df, SYMBOL)
    latest_sig = df["signal"].iloc[-1]
    price = df["close"].iloc[-1]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # 当前组合净值
    portfolio_value = state["cash"] + state["position"] * price
    pnl_pct = (portfolio_value / INITIAL_CAPITAL - 1) * 100

    print(
        f"  💰 虚拟账户: 现金 ${state['cash']:.2f} | 持仓 {state['position']:.6f} BTC "
        f"| 总值 ${portfolio_value:.2f} ({pnl_pct:+.2f}%)"
    )

    # 执行虚拟交易
    if latest_sig == 1 and state["cash"] > 10:
        # 买入：用 50% 现金
        buy_amount = (state["cash"] * 0.5) / price
        cost = buy_amount * price
        state["cash"] -= cost
        state["position"] += buy_amount
        state["entry_price"] = price
        trade = {
            "type": "BUY",
            "time": now,
            "price": price,
            "amount": buy_amount,
            "cost": cost,
            "sentiment": sentiment_score,
            "reason": reason,
        }
        state["trades"].append(trade)

        body = (
            f"📝 纸面买入\n\n"
            f"时间: {now}\n"
            f"价格: ${price:.2f}\n"
            f"数量: {buy_amount:.6f} BTC\n"
            f"金额: ${cost:.2f}\n"
            f"情绪分: {sentiment_score:+.3f}\n"
            f"原因: {reason}\n\n"
            f"剩余现金: ${state['cash']:.2f}\n"
            f"持仓市值: ${state['position'] * price:.2f}\n"
            f"组合总值: ${portfolio_value:.2f} ({pnl_pct:+.2f}%)"
        )
        print(body)
        send_email("[Paper Trade] 买入 BTC", body)

    elif latest_sig == -1 and state["position"] > 0:
        # 卖出：全部卖出
        sell_amount = state["position"]
        proceeds = sell_amount * price
        realized_pnl = (price - state["entry_price"]) * sell_amount
        state["cash"] += proceeds
        state["position"] = 0
        trade = {
            "type": "SELL",
            "time": now,
            "price": price,
            "amount": sell_amount,
            "proceeds": proceeds,
            "realized_pnl": realized_pnl,
            "sentiment": sentiment_score,
            "reason": reason,
        }
        state["trades"].append(trade)

        body = (
            f"📝 纸面卖出\n\n"
            f"时间: {now}\n"
            f"价格: ${price:.2f}\n"
            f"数量: {sell_amount:.6f} BTC\n"
            f"金额: ${proceeds:.2f}\n"
            f"实现盈亏: ${realized_pnl:+.2f}\n"
            f"情绪分: {sentiment_score:+.3f}\n"
            f"原因: {reason}\n\n"
            f"剩余现金: ${state['cash']:.2f}\n"
            f"组合总值: ${portfolio_value:.2f} ({pnl_pct:+.2f}%)"
        )
        print(body)
        send_email("[Paper Trade] 卖出 BTC", body)

    else:
        print(f"  ⏸ 无交易信号，当前价格 ${price:.2f} | 情绪分: {sentiment_score:+.3f}")

    save_state(state)
    commit_state()


if __name__ == "__main__":
    try:
        execute_paper_trade()
    except Exception as e:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        msg = f"❌ 纸面交易脚本异常\n\n时间: {now}\n错误: {e}"
        print(msg)
        send_email("[Paper Trade] 运行异常", msg)
        raise