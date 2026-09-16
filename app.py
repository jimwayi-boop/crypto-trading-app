import streamlit as st
import ccxt
import pandas as pd
from strategy import MomentumBreakoutStrategy
from backtest import run_backtest

st.set_page_config(page_title="Crypto Trading App", layout="wide")
st.title("📈 Crypto 交易应用")

st.sidebar.header("设置")
symbol = st.sidebar.selectbox("交易对", ["BTCUSDC", "ETHUSDC", "SOLUSDC"])
timeframe = st.sidebar.selectbox("K线周期", ["1h", "4h", "1d"])
capital = st.sidebar.number_input("初始资金 ($)", value=500)
mode = st.sidebar.radio("模式", ["回测", "纸面交易"])

@st.cache_data(ttl=300)
def fetch_ohlcv(symbol, timeframe, limit=500):
    exchange = ccxt.bullish({'enableRateLimit': True})
    exchange.load_markets()
    data = exchange.fetch_ohlcv(symbol, '1h', limit=limit)
    df = pd.DataFrame(data, columns=['timestamp','open','high','low','close','volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    if timeframe == '4h':
        df = df.resample('4h').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }).dropna()

    return df

df = fetch_ohlcv(symbol, timeframe)

if mode == "回测":
    strategy = MomentumBreakoutStrategy()
    results = run_backtest(df, strategy, initial_capital=capital)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("总收益率", f"{results['total_return_pct']}%")
    col2.metric("最大回撤", f"{results['max_drawdown_pct']}%")
    col3.metric("交易次数", results['total_trades'])
    col4.metric("胜率", f"{results['win_rate_pct']}%")
    st.line_chart(results['equity_curve']['equity'])
    st.dataframe(pd.DataFrame(results['trades']))

elif mode == "纸面交易":
    st.info("纸面交易模式：使用虚拟资金模拟真实市场操作")
    if 'virtual_balance' not in st.session_state:
        st.session_state.virtual_balance = capital
        st.session_state.virtual_position = 0

    col1, col2 = st.columns(2)
    col1.metric("虚拟余额", f"${st.session_state.virtual_balance:.2f}")
    col2.metric("当前持仓", f"{st.session_state.virtual_position:.6f}")

    if st.button("执行策略信号"):
        strategy = MomentumBreakoutStrategy()
        df_sig = strategy.generate_signals(df)
        latest_sig = df_sig['signal'].iloc[-1]
        price = df_sig['close'].iloc[-1]

        if latest_sig == 1 and st.session_state.virtual_position == 0:
            st.session_state.virtual_position = st.session_state.virtual_balance / price
            st.session_state.virtual_balance = 0
            st.success(f"纸面买入 {st.session_state.virtual_position:.6f} 于 ${price:.2f}")
        elif latest_sig == -1 and st.session_state.virtual_position > 0:
            st.session_state.virtual_balance = st.session_state.virtual_position * price
            st.session_state.virtual_position = 0
            st.success(f"纸面卖出 于 ${price:.2f}")
        else:
            st.warning("当前无交易信号")

    if st.button("重置纸面账户"):
        st.session_state.virtual_balance = capital
        st.session_state.virtual_position = 0
        st.success("已重置")