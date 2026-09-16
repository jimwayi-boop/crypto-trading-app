import os
import pandas as pd
from strategy import MomentumBreakoutStrategy
from bullish_client import BullishClient

API_KEY = os.environ.get("BULLISH_API_KEY", "")
SECRET_KEY = os.environ.get("BULLISH_SECRET_KEY", "")
ACCOUNT_ID = os.environ.get("BULLISH_ACCOUNT_ID", "")

client = BullishClient(API_KEY, SECRET_KEY, ACCOUNT_ID)


def execute_live_trade(symbol="BTCUSDC", timeframe="1h"):
    ohlcv = client.fetch_ohlcv(symbol, timeframe, limit=100)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)

    # 如果是 4h，本地合成
    if timeframe == '4h':
        df = df.resample('4h').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }).dropna()

    strategy = MomentumBreakoutStrategy()
    df = strategy.generate_signals(df)
    latest_sig = df['signal'].iloc[-1]
    price = df['close'].iloc[-1]

    balance = client.fetch_balance()

    # 正确解析 Bullish 原生交易对格式（例如 BTCUSDC）
    if symbol.endswith("USDC"):
        base_currency = symbol[:-4]
        quote_currency = "USDC"
    elif symbol.endswith("USDT"):
        base_currency = symbol[:-4]
        quote_currency = "USDT"
    else:
        raise ValueError(f"无法识别的交易对格式: {symbol}")

    if latest_sig == 1:
        quote_balance = balance.get(quote_currency, {}).get('free', 0)
        if quote_balance > 10:
            amount = (quote_balance * 0.5) / price
            try:
                order = client.market_buy(symbol, amount)
                print(f"✅ 买入成功：{amount:.6f} {base_currency} @ ${price:.2f}")
            except Exception as e:
                print(f"❌ 买入失败：{e}")
        else:
            print(f"⏸ 买入信号，但 {quote_currency} 余额不足（{quote_balance}）")

    elif latest_sig == -1:
        coin_balance = balance.get(base_currency, {}).get('free', 0)
        if coin_balance > 0:
            try:
                order = client.market_sell(symbol, coin_balance)
                print(f"✅ 卖出成功：{coin_balance:.6f} {base_currency} @ ${price:.2f}")
            except Exception as e:
                print(f"❌ 卖出失败：{e}")
        else:
            print(f"⏸ 卖出信号，但 {base_currency} 余额为 0")

    else:
        print(f"⏸ 无交易信号，当前价格 ${price:.2f}")


if __name__ == "__main__":
    execute_live_trade()
