import ccxt
import os

class BullishClient:
    def __init__(self, api_key, secret, trading_account_id):
        self.exchange = ccxt.bullish({
            'apiKey': api_key,
            'secret': secret,
            'options': {
                'tradingAccountId': trading_account_id
            },
            'enableRateLimit': True,
        })

    def fetch_ohlcv(self, symbol="BTC/USDC", timeframe="4h", limit=200):
        return self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

    def fetch_balance(self):
        return self.exchange.fetch_balance()

    def market_buy(self, symbol, amount):
        return self.exchange.create_market_buy_order(symbol, amount)

    def market_sell(self, symbol, amount):
        return self.exchange.create_market_sell_order(symbol, amount)