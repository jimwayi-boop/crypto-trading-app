import os
import pandas as pd
from strategy import MomentumBreakoutStrategy
from bullish_client import BullishClient

API_KEY = os.environ.get("BULLISH_API_KEY", "")
SECRET_KEY = os.environ.get("BULLISH_SECRET_KEY", "")
ACCOUNT_ID = os.environ.get("BULLISH_ACCOUNT_ID", "")

client = BullishClient(API_KEY, SECRET_KEY, ACCOUNT_ID)

def execute_live_trade(symbol="BTCUSDC", timeframe="4h"):
    ohlcv = client.fetch_ohlcv(symbol, timeframe, limit=200)
    df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)

    strategy = MomentumBreakoutStrategy()
    df = strategy.generate_signals(df)
    latest_sig = df['signal'].iloc[-1]
    price = df['close'].iloc[-1]

    balance = client.fetch_balance()
    base_currency = symbol.split('/')[0]
    quote_currency = symbol.split('/')[1]

    if latest_sig == 1:
        quote_balance = balance[quote_currency]['free']
        if quote_balance > 10:
            amount = (quote_balance * 0.5) / price
            try:
                order = client.market_buy(symbol, amount)
                print(f"✅ 买入成功：{amount:.6f} {base_currency} @ ${price:.2f}")
            except Exception as e:
                print(f"❌ 买入失败：{e}")

    elif latest_sig == -1:
        coin_balance = balance[base_currency]['free']
        if coin_balance > 0:
            try:
                order = client.market_sell(symbol, coin_balance)
                print(f"✅ 卖出成功：{coin_balance:.6f} {base_currency} @ ${price:.2f}")
            except Exception as e:
                print(f"❌ 卖出失败：{e}")

    else:
        print(f"⏸ 无交易信号，当前价格 ${price:.2f}")

if __name__ == "__main__":
    execute_live_trade()