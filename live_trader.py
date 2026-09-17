import os
import smtplib
from email.mime.text import MIMEText
from datetime import datetime
import pandas as pd
from strategy_news import NewsSentimentStrategy
from bullish_client import BullishClient

# ============ 配置区 ============
API_KEY = os.environ.get("BULLISH_API_KEY", "")
SECRET_KEY = os.environ.get("BULLISH_SECRET_KEY", "")
ACCOUNT_ID = os.environ.get("BULLISH_ACCOUNT_ID", "")

GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", GMAIL_USER)

client = BullishClient(API_KEY, SECRET_KEY, ACCOUNT_ID)


def send_email(subject, body):
    """发送邮件通知。失败时不抛出异常，只打印警告。"""
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        print("⚠️ Gmail 未配置，跳过邮件通知")
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


def execute_live_trade(symbol="BTCUSDC", timeframe="1h"):
    # 1. 获取K线
    ohlcv = client.fetch_ohlcv(symbol, timeframe, limit=100)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)

    if timeframe == '4h':
        df = df.resample('4h').agg({
            'open': 'first', 'high': 'max', 'low': 'min',
            'close': 'last', 'volume': 'sum'
        }).dropna()

    # 2. 使用新闻情绪策略生成信号
    strategy = NewsSentimentStrategy(
        fast_ema=20,
        slow_ema=50,
        lookback=20,
        sentiment_threshold=0.3,
        news_lookback_hours=2
    )
    df, sentiment_score, reason = strategy.generate_signals(df, symbol)
    latest_sig = df['signal'].iloc[-1]
    price = df['close'].iloc[-1]

    # 3. 获取余额
    balance = client.fetch_balance()

    if symbol.endswith("USDC"):
        base_currency = symbol[:-4]
        quote_currency = "USDC"
    elif symbol.endswith("USDT"):
        base_currency = symbol[:-4]
        quote_currency = "USDT"
    else:
        raise ValueError(f"无法识别的交易对格式: {symbol}")

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    # 4. 执行交易
    if latest_sig == 1:
        quote_balance = balance.get(quote_currency, {}).get('free', 0)
        if quote_balance > 10:
            amount = (quote_balance * 0.5) / price
            try:
                client.market_buy(symbol, amount)
                msg = (f"✅ 买入成功\n\n"
                       f"时间: {now}\n"
                       f"交易对: {symbol}\n"
                       f"数量: {amount:.6f} {base_currency}\n"
                       f"价格: ${price:.2f}\n"
                       f"金额: ${amount * price:.2f}\n"
                       f"情绪分: {sentiment_score:+.3f}\n"
                       f"信号原因: {reason}")
                print(msg)
                send_email(f"[Crypto Bot] 买入 {base_currency}", msg)
            except Exception as e:
                msg = (f"❌ 买入失败\n\n"
                       f"时间: {now}\n"
                       f"交易对: {symbol}\n"
                       f"价格: ${price:.2f}\n"
                       f"情绪分: {sentiment_score:+.3f}\n"
                       f"原因: {e}")
                print(msg)
                send_email(f"[Crypto Bot] 买入失败 {base_currency}", msg)
        else:
            print(f"⏸ 买入信号，但 {quote_currency} 余额不足（{quote_balance}）")

    elif latest_sig == -1:
        coin_balance = balance.get(base_currency, {}).get('free', 0)
        if coin_balance > 0:
            try:
                client.market_sell(symbol, coin_balance)
                msg = (f"✅ 卖出成功\n\n"
                       f"时间: {now}\n"
                       f"交易对: {symbol}\n"
                       f"数量: {coin_balance:.6f} {base_currency}\n"
                       f"价格: ${price:.2f}\n"
                       f"金额: ${coin_balance * price:.2f}\n"
                       f"情绪分: {sentiment_score:+.3f}\n"
                       f"信号原因: {reason}")
                print(msg)
                send_email(f"[Crypto Bot] 卖出 {base_currency}", msg)
            except Exception as e:
                msg = (f"❌ 卖出失败\n\n"
                       f"时间: {now}\n"
                       f"交易对: {symbol}\n"
                       f"价格: ${price:.2f}\n"
                       f"情绪分: {sentiment_score:+.3f}\n"
                       f"原因: {e}")
                print(msg)
                send_email(f"[Crypto Bot] 卖出失败 {base_currency}", msg)
        else:
            print(f"⏸ 卖出信号，但 {base_currency} 余额为 0")

    else:
        print(f"⏸ 无交易信号，当前价格 ${price:.2f} | 情绪分: {sentiment_score:+.3f}")


if __name__ == "__main__":
    try:
        execute_live_trade()
    except Exception as e:
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        msg = f"❌ 脚本执行异常\n\n时间: {now}\n错误: {e}"
        print(msg)
        send_email("[Crypto Bot] 运行异常", msg)
        raise