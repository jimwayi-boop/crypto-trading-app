import streamlit as st
import ccxt
import pandas as pd
import requests
import json
from strategy import MomentumBreakoutStrategy
from strategy_news import NewsSentimentStrategy
from backtest import run_backtest

st.set_page_config(page_title="Crypto Trading App", layout="wide")
st.title("📈 Crypto 交易应用")

# ==================== 配置 ====================
PAPER_STATE_URL = (
    "https://raw.githubusercontent.com/jimwayi-boop/crypto-trading-app/main/paper_state.json"
)
INITIAL_CAPITAL = 500.0


# ==================== 侧边栏 ====================
st.sidebar.header("设置")
symbol = st.sidebar.selectbox("交易对", ["BTCUSDC", "ETHUSDC", "SOLUSDC"])
timeframe = st.sidebar.selectbox("K线周期", ["1h", "4h", "1d"])
capital = st.sidebar.number_input("回测初始资金 ($)", value=500)
mode = st.sidebar.radio("模式", ["纸面交易监控", "回测"])


# ==================== 数据获取 ====================
@st.cache_data(ttl=300)
def fetch_ohlcv(symbol, timeframe, limit=100):
    exchange = ccxt.bullish({"enableRateLimit": True})
    exchange.load_markets()
    data = exchange.fetch_ohlcv(symbol, "1h", limit=limit)
    df = pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)

    if timeframe == "4h":
        df = df.resample("4h").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna()

    return df


@st.cache_data(ttl=60)
def fetch_paper_state():
    try:
        resp = requests.get(PAPER_STATE_URL, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None


# ==================== 回测模式 ====================
if mode == "回测":
    st.subheader("📊 策略回测")
    st.caption("回测使用纯技术策略（MomentumBreakoutStrategy），因为新闻情绪无法做历史回测。")

    df = fetch_ohlcv(symbol, timeframe)
    strategy = MomentumBreakoutStrategy()
    results = run_backtest(df, strategy, initial_capital=capital)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("总收益率", f"{results['total_return_pct']}%")
    col2.metric("最大回撤", f"{results['max_drawdown_pct']}%")
    col3.metric("交易次数", results["total_trades"])
    col4.metric("胜率", f"{results['win_rate_pct']}%")

    st.line_chart(results["equity_curve"]["equity"])
    st.dataframe(pd.DataFrame(results["trades"]))


# ==================== 纸面交易监控 ====================
elif mode == "纸面交易监控":
    st.subheader("📊 纸面交易实时状态")
    st.caption(
        "数据来自 GitHub 仓库中的 paper_state.json。"
        "GitHub Actions 每 2 小时自动更新一次。"
    )

    if st.button("🔄 刷新数据"):
        st.cache_data.clear()

    state = fetch_paper_state()

    if state is None:
        st.error(
            "❌ 无法读取 paper_state.json。"
            "请确认文件已上传到 GitHub 仓库，且仓库是公开的。"
        )
    else:
        try:
            df_now = fetch_ohlcv(symbol, "1h", limit=5)
            current_price = df_now["close"].iloc[-1]
        except Exception:
            current_price = state.get("entry_price", 0)

        cash = state.get("cash", 0)
        position = state.get("position", 0)
        portfolio_value = cash + position * current_price
        pnl_pct = (portfolio_value / INITIAL_CAPITAL - 1) * 100
        total_pnl = portfolio_value - INITIAL_CAPITAL

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("虚拟现金", f"${cash:.2f}")
        col2.metric("持仓数量", f"{position:.6f} BTC")
        col3.metric("组合总值", f"${portfolio_value:.2f}", delta=f"{pnl_pct:+.2f}%")
        col4.metric("总盈亏", f"${total_pnl:+.2f}", delta=f"{pnl_pct:+.2f}%")

        st.divider()

        st.subheader("💼 当前持仓")
        if position > 0:
            entry_price = state.get("entry_price", 0)
            position_value = position * current_price
            unrealized_pnl = (current_price - entry_price) * position
            unrealized_pct = (
                (current_price / entry_price - 1) * 100 if entry_price > 0 else 0
            )

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("入场价", f"${entry_price:.2f}")
            c2.metric("当前价", f"${current_price:.2f}")
            c3.metric("持仓市值", f"${position_value:.2f}")
            c4.metric("未实现盈亏", f"${unrealized_pnl:+.2f}", delta=f"{unrealized_pct:+.2f}%")
        else:
            st.info("当前无持仓，等待买入信号。")

        st.divider()

        st.subheader("📜 交易历史")
        trades = state.get("trades", [])
        if not trades:
            st.info("暂无交易记录。")
        else:
            trades_df = pd.DataFrame(trades)
            if "type" in trades_df.columns:
                cols_order = [
                    c
                    for c in [
                        "type", "time", "price", "amount",
                        "cost", "proceeds", "realized_pnl",
                        "sentiment", "reason",
                    ]
                    if c in trades_df.columns
                ]
                trades_df = trades_df[cols_order]
            st.dataframe(trades_df, use_container_width=True)

            st.subheader("📈 交易统计")
            buy_trades = [t for t in trades if t.get("type") == "BUY"]
            sell_trades = [t for t in trades if t.get("type") == "SELL"]
            realized_trades = [t for t in sell_trades if "realized_pnl" in t]

            if realized_trades:
                pnls = [t["realized_pnl"] for t in realized_trades]
                wins = [p for p in pnls if p > 0]
                losses = [p for p in pnls if p < 0]
                win_rate = len(wins) / len(pnls) * 100 if pnls else 0

                s1, s2, s3, s4 = st.columns(4)
                s1.metric("买入次数", len(buy_trades))
                s2.metric("卖出次数", len(sell_trades))
                s3.metric("胜率", f"{win_rate:.1f}%")
                s4.metric("已实现盈亏", f"${sum(pnls):+.2f}")

        st.divider()

        st.caption(
            f"创建时间: {state.get('created', 'N/A')} | "
            f"最后更新: {state.get('last_updated', 'N/A')}"
        )
