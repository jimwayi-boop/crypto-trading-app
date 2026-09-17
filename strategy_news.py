"""
多源新闻情绪 + 技术指标复合策略
整合 Free Crypto News API / CryptoCompare / CoinGecko / RSS 四个新闻源
"""

import os
import re
import requests
import pandas as pd
import numpy as np
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer


class NewsAggregator:
    """从多个来源抓取加密货币新闻，归一化为统一格式"""

    RSS_FEEDS = {
        "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "CoinTelegraph": "https://cointelegraph.com/rss",
    }

    def __init__(self, lookback_hours=2, max_per_source=20):
        self.lookback_hours = lookback_hours
        self.max_per_source = max_per_source

    # ---------- 工具函数 ----------
    @staticmethod
    def _parse_time(time_str):
        """尝试多种格式解析时间字符串"""
        if not time_str:
            return datetime.utcnow()
        formats = [
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S",
            "%a, %d %b %Y %H:%M:%S %z",
            "%a, %d %b %Y %H:%M:%S %Z",
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(time_str.strip(), fmt)
                if dt.tzinfo is not None:
                    dt = dt.astimezone(tz=None).replace(tzinfo=None)
                return dt
            except Exception:
                continue
        return datetime.utcnow()

    def _is_recent(self, dt):
        """检查新闻是否在回看窗口内"""
        return dt >= datetime.utcnow() - timedelta(hours=self.lookback_hours)

    # ---------- 源1: Free Crypto News API ----------
    def fetch_free_crypto_news(self, symbol):
        base = symbol.replace("USDC", "").replace("USDT", "").upper()
        url = f"https://cryptocurrency.cv/api/{base.lower()}"
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            articles = data if isinstance(data, list) else data.get("articles", data.get("data", []))
            results = []
            for item in articles[: self.max_per_source]:
                title = item.get("title", "")
                pub = self._parse_time(item.get("published_at", item.get("pubDate", "")))
                if title and self._is_recent(pub):
                    results.append({
                        "title": title,
                        "source": "FreeCryptoNews",
                        "published": pub,
                        "url": item.get("url", item.get("link", "")),
                    })
            print(f"    [FreeCryptoNews] {len(results)} 条")
            return results
        except Exception as e:
            print(f"    [FreeCryptoNews] 失败: {e}")
            return []

    # ---------- 源2: CryptoCompare News ----------
    def fetch_cryptocompare(self, symbol):
        base = symbol.replace("USDC", "").replace("USDT", "").upper()
        url = "https://min-api.cryptocompare.com/data/v2/news/"
        params = {"lang": "EN", "categories": base}
        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            results = []
            for item in data.get("Data", [])[: self.max_per_source]:
                title = item.get("title", "")
                pub = self._parse_time(item.get("published_on", ""))
                if title and self._is_recent(pub):
                    results.append({
                        "title": title,
                        "source": "CryptoCompare",
                        "published": pub,
                        "url": item.get("url", ""),
                    })
            print(f"    [CryptoCompare] {len(results)} 条")
            return results
        except Exception as e:
            print(f"    [CryptoCompare] 失败: {e}")
            return []

    # ---------- 源3: CoinGecko News ----------
    def fetch_coingecko(self, symbol):
        url = "https://api.coingecko.com/api/v3/news"
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            articles = data if isinstance(data, list) else data.get("data", [])
            results = []
            for item in articles[: self.max_per_source]:
                title = item.get("title", "")
                pub = self._parse_time(item.get("created_at", item.get("updated_at", "")))
                if title and self._is_recent(pub):
                    results.append({
                        "title": title,
                        "source": "CoinGecko",
                        "published": pub,
                        "url": item.get("url", ""),
                    })
            print(f"    [CoinGecko] {len(results)} 条")
            return results
        except Exception as e:
            print(f"    [CoinGecko] 失败: {e}")
            return []

    # ---------- 源4: RSS Feeds ----------
    def fetch_rss(self, symbol):
        base = symbol.replace("USDC", "").replace("USDT", "").upper()
        results = []
        for name, feed_url in self.RSS_FEEDS.items():
            try:
                resp = requests.get(feed_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
                root = ET.fromstring(resp.content)
                items = root.findall(".//item")
                count = 0
                for item in items[: self.max_per_source]:
                    title_el = item.find("title")
                    pub_el = item.find("pubDate")
                    link_el = item.find("link")
                    title = title_el.text if title_el is not None else ""
                    if not title:
                        continue
                    pub = self._parse_time(pub_el.text if pub_el is not None else "")
                    if not self._is_recent(pub):
                        continue
                    results.append({
                        "title": title,
                        "source": name,
                        "published": pub,
                        "url": link_el.text if link_el is not None else "",
                    })
                    count += 1
                print(f"    [{name}] {count} 条")
            except Exception as e:
                print(f"    [{name}] 失败: {e}")
        return results

    # ---------- 聚合入口 ----------
    def aggregate(self, symbol):
        """从所有源抓取新闻，去重后返回统一列表"""
        print(f"  📡 从 5 个来源抓取 {symbol} 新闻...")
        all_news = []
        all_news.extend(self.fetch_free_crypto_news(symbol))
        all_news.extend(self.fetch_cryptocompare(symbol))
        all_news.extend(self.fetch_coingecko(symbol))
        all_news.extend(self.fetch_rss(symbol))

        # 按标题去重（简单版本：标题小写后前50字符相同则视为重复）
        seen = set()
        unique_news = []
        for news in all_news:
            key = re.sub(r"\W+", "", news["title"].lower())[:50]
            if key not in seen:
                seen.add(key)
                unique_news.append(news)

        print(f"  📰 去重后共 {len(unique_news)} 条新闻")
        return unique_news


class NewsSentimentStrategy:
    """
    多源新闻情绪 + 技术指标复合策略
    """

    def __init__(self,
                 fast_ema=20,
                 slow_ema=50,
                 lookback=20,
                 sentiment_threshold=0.3,
                 news_lookback_hours=2,
                 max_news_per_source=20):
        self.fast_ema = fast_ema
        self.slow_ema = slow_ema
        self.lookback = lookback
        self.sentiment_threshold = sentiment_threshold
        self.aggregator = NewsAggregator(
            lookback_hours=news_lookback_hours,
            max_per_source=max_news_per_source,
        )
        self.analyzer = SentimentIntensityAnalyzer()

    def analyze_sentiment(self, news_list):
        """对新闻标题做 VADER 情绪打分"""
        if not news_list:
            return 0.0, 0, 0, 0
        scores = []
        positive = negative = neutral = 0
        for news in news_list:
            title = news["title"]
            if not title:
                continue
            compound = self.analyzer.polarity_scores(title)["compound"]
            scores.append(compound)
            if compound >= 0.05:
                positive += 1
            elif compound <= -0.05:
                negative += 1
            else:
                neutral += 1
        if not scores:
            return 0.0, 0, 0, 0
        avg = float(np.mean(scores))
        print(f"  🧠 情绪: 平均 {avg:+.3f} | 正面 {positive} 负面 {negative} 中性 {neutral}")
        return avg, positive, negative, neutral

    def compute_technical(self, df):
        df = df.copy()
        df["ema_fast"] = df["close"].ewm(span=self.fast_ema).mean()
        df["ema_slow"] = df["close"].ewm(span=self.slow_ema).mean()
        df["high_roll"] = df["high"].rolling(self.lookback).max()
        return df

    def generate_signals(self, df, symbol="BTCUSDC"):
        df = self.compute_technical(df)
        df["signal"] = 0

        news_list = self.aggregator.aggregate(symbol)
        sentiment_score, pos, neg, neu = self.analyze_sentiment(news_list)

        latest = df.iloc[-1]
        tech_buy = (
            latest["ema_fast"] > latest["ema_slow"]
            and latest["close"] > latest["high_roll"]
        )
        tech_sell = (
            latest["ema_fast"] < latest["ema_slow"]
            or latest["close"] < latest["ema_slow"]
        )

        signal = 0
        reason = "无信号"

        if tech_buy and sentiment_score >= self.sentiment_threshold:
            signal = 1
            reason = f"技术突破 + 情绪积极 ({sentiment_score:+.2f})"
        elif tech_sell and sentiment_score <= -self.sentiment_threshold:
            signal = -1
            reason = f"技术走弱 + 情绪消极 ({sentiment_score:+.2f})"
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