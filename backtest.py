import pandas as pd
import numpy as np

def run_backtest(df, strategy, initial_capital=500,
                 fee_rate=0.001, slippage=0.0005):
    df = strategy.generate_signals(df)
    capital = initial_capital
    position = 0
    entry_price = 0
    trades = []
    equity_curve = []

    for i in range(1, len(df)):
        price = df['close'].iloc[i]
        sig = df['signal'].iloc[i]
        atr = df['atr'].iloc[i]

        if sig == 1 and position == 0 and not np.isnan(atr):
            buy_price = price * (1 + slippage)
            position = capital / buy_price
            entry_price = buy_price
            capital = 0
            trades.append({'type': 'BUY', 'price': buy_price,
                           'time': df.index[i], 'shares': position})
        elif sig == -1 and position > 0:
            sell_price = price * (1 - slippage)
            capital = position * sell_price * (1 - fee_rate)
            pnl = capital - (position * entry_price)
            trades.append({'type': 'SELL', 'price': sell_price,
                           'time': df.index[i], 'shares': position, 'pnl': pnl})
            position = 0

        current_value = capital + position * price
        equity_curve.append({'time': df.index[i], 'equity': current_value})

    eq_df = pd.DataFrame(equity_curve).set_index('time')
    total_return = (eq_df['equity'].iloc[-1] / initial_capital - 1) * 100
    eq_df['peak'] = eq_df['equity'].cummax()
    eq_df['drawdown'] = (eq_df['equity'] - eq_df['peak']) / eq_df['peak']
    max_dd = eq_df['drawdown'].min() * 100
    win_trades = [t for t in trades if t.get('pnl', 0) > 0]
    lose_trades = [t for t in trades if t.get('pnl', 0) < 0]
    win_rate = len(win_trades) / max(len(win_trades)+len(lose_trades), 1) * 100

    return {
        'total_return_pct': round(total_return, 2),
        'max_drawdown_pct': round(max_dd, 2),
        'total_trades': len(trades),
        'win_rate_pct': round(win_rate, 2),
        'equity_curve': eq_df,
        'trades': trades
    }