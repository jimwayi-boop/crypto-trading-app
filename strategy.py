import pandas as pd
import numpy as np

class MomentumBreakoutStrategy:
    def __init__(self, fast_ema=20, slow_ema=50, atr_period=14,
                 atr_multiplier=2.5, lookback=20):
        self.fast_ema = fast_ema
        self.slow_ema = slow_ema
        self.atr_period = atr_period
        self.atr_multiplier = atr_multiplier
        self.lookback = lookback

    def generate_signals(self, df):
        df = df.copy()
        df['ema_fast'] = df['close'].ewm(span=self.fast_ema).mean()
        df['ema_slow'] = df['close'].ewm(span=self.slow_ema).mean()
        df['high_roll'] = df['high'].rolling(self.lookback).max()

        df['tr'] = np.maximum(
            df['high'] - df['low'],
            np.maximum(
                abs(df['high'] - df['close'].shift(1)),
                abs(df['low'] - df['close'].shift(1))
            )
        )
        df['atr'] = df['tr'].rolling(self.atr_period).mean()

        df['signal'] = 0
        df.loc[
            (df['ema_fast'] > df['ema_slow']) &
            (df['close'] > df['high_roll'].shift(1)), 'signal'
        ] = 1
        df.loc[
            (df['ema_fast'] < df['ema_slow']) |
            (df['close'] < df['ema_slow']), 'signal'
        ] = -1
        return df