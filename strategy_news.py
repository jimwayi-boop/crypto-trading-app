"""
新闻情绪 + 技术指标复合策略
每2小时抓取加密货币新闻，分析情绪，结合技术面生成交易信号
"""

import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer


class NewsSentimentStrategy:
    """
    复合策略：
    1. 新闻情绪打分（-1 到 +1）
    2. 技术指标确认（EMA 趋势 + 突破）
    3. 只有两者同向时才产生信号
    """

    def __init__(self,
                 # 技术指标参数
                 fast_ema=20,
                 slow_ema=50,
                 lookback=20,
                 # 情绪参数
                 sentiment_threshold=0.3,
                 news_lookback_hours=2,
                 max_news_per_symbol=30):
        self.fast_ema = fast_ema
        self.slow_ema = slow_ema
        self.lookback = lookback
        self.sentiment_threshold = sentiment_threshold
        self.news_lookback_hours = news_lookback_hours
        self.max_news_per_symbol = max_news_per_symbol

        self.analyzer = SentimentIntensityAnalyzer()
        self.cryptopanic_token = os.environ.get("CRYPTOPANIC_API_KEY", "")

    # ==================== 新闻抓取 ====================
    def fetch_news(self, symbol):
        """
        从 CryptoPanic 抓取最近 N 小时的新闻
        符号格式: BTCUSDC → BTC
        """
        base_currency = symbol.replace("USDC", "").replace("USDT", "")

        if not self.cryptopanic_token:
            print("⚠️ CRYPTOPANIC_API_KEY 未设置，跳过新闻抓取")
            return []

        url = "https://cryptopanic.com/api/v1/posts/"
        params = {
            "auth_token": self.cryptopanic_token,
            "currencies": base_currency,
            "filter": "hot",
            "kind": "news",
            "public": "true",
        }

        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            cutoff = datetime.utcnow() - timedelta(hours=self.news_lookback_hours)
            news_list = []
            for post in data.get("results", [])[:self.max_news_per_symbol]:
                published = post.get("published_at", "")
                try:
                    pub_time = datetime.strptime(published[:19], "%Y-%m-%dT%H:%M:%S")
                except Exception:
                    pub_time = datetime.utcnow()

                if pub_time < cutoff:
                    continue

                news_list.append({
                    "title": post.get("title", ""),
                    "url": post.get("url", ""),
                    "source": post.get("source", {}).get("title", ""),
                    "published": published,
                    "votes": post.get("votes", {}),
                })

            print(f"  📰 {base_currency}: 找到 {len(news_list)} 条近 {self.news_lookback_hours}h 新闻")
            return news_list

        except Exception as e:
            print(f"  ⚠️ 新闻抓取失败 ({base_currency}): {e}")
            return []

    # ==================== 情绪分析 ====================
    def analyze_sentiment(self, news_list):
        """
        对新闻标题做情绪打分
        返回: (平均情绪分, 正面数, 负面数, 中性数)
        """
        if not news_list:
            return 0.0, 0, 0, 0

        scores = []
        positive = negative = neutral = 0

        for news in news_list:
            title = news["title"]
            if not title:
                continue

            score = self.analyzer.polarity_scores(title)
            compound = score["compound"]
            scores.append(compound)

            if compound >= 0.05:
                positive += 1
            elif compound <= -0.05:
                negative += 1
            else:
                neutral += 1

        if not scores:
            return 0.0, 0, 0, 0

        avg = np.mean(scores)
        print(f"  🧠 情绪: 平均 {avg:+.3f} | 正面 {positive} 负面 {negative} 中性 {neutral}")
        return avg, positive, negative, neutral

    # ==================== 技术指标 ====================
    def compute_technical(self, df):
        """计算 EMA 和突破位"""
        df = df.copy()
        df["ema_fast"] = df["close"].ewm(span=self.fast_ema).mean()
        df["ema_slow"] = df["close"].ewm(span=self.slow_ema).mean()
        df["high_roll"] = df["high"].rolling(self.lookback).max()
        return df

    # ==================== 综合信号 ====================
    def generate_signals(self, df, symbol="BTCUSDC"):
        """
        综合新闻情绪和技术指标，生成交易信号
        返回: df (含 signal 列), 情绪分, 信号原因
        """
        df = self.compute_technical(df)
        df["signal"] = 0

        # --- 获取新闻和情绪 ---
        news_list = self.fetch_news(symbol)
        sentiment_score, pos, neg, neu = self.analyze_sentiment(news_list)

        # --- 技术信号 ---
        latest = df.iloc[-1]
        prev = df.iloc[-2]

        tech_buy = (
            latest["ema_fast"] > latest["ema_slow"]
            and latest["close"] > latest["high_roll"]
        )
        tech_sell = (
            latest["ema_fast"] < latest["ema_slow"]
            or latest["close"] < latest["ema_slow"]
        )

        # --- 综合判断 ---
        signal = 0
        reason = "无信号"

        # 买入：技术看涨 + 情绪积极
        if tech_buy and sentiment_score >= self.sentiment_threshold:
            signal = 1
            reason = f"技术突破 + 情绪积极 ({sentiment_score:+.2f})"

        # 卖出：技术看跌 + 情绪消极
        elif tech_sell and sentiment_score <= -self.sentiment_threshold:
            signal = -1
            reason = f"技术走弱 + 情绪消极 ({sentiment_score:+.2f})"

        # 强情绪单独触发（极端情况）
        elif sentiment_score >= 0.7:
            signal = 1
            reason = f"极端积极情绪 ({sentiment_score:+.2f})"
        elif sentiment_score <= -0.7:
            signal = -1
            reason = f"极端消极情绪 ({sentiment_score:+.2f})"

        df.loc[df.index[-1], "signal"] = signal

        print(f"  📊 技术: EMA{'↑' if latest['ema_fast'] > latest['ema_slow'] else '↓'} "
              f"| 收盘 {latest['close']:.2f} | 突破位 {latest['high_roll']:.2f}")
        print(f"  🎯 信号: {signal} | 原因: {reason}")

        return df, sentiment_score, reason