"""
多源新闻情绪 + Polymarket预测市场 + 技术指标复合策略
"""

import re
import requests
import pandas as pd
import numpy as np
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer


class NewsAggregator:
    """从多个免费来源抓取加密货币新闻，归一化为统一格式"""

    RSS_FEEDS = {
        "CoinTelegraph": "https://cointelegraph.com/rss",
        "Decrypt": "https://decrypt.co/feed",
        "CryptoSlate": "https://cryptoslate.com/feed/",
        "CryptoNews": "https://cryptonews.com/news/feed/",
        "CoinGape": "https://coingape.com/feed/",
        "AMBCrypto": "https://ambcrypto.com/feed/",
        "TheDefiant": "https://thedefiant.io/feed/",
        "CryptoBriefing": "https://cryptobriefing.com/feed/",
        "Bitcoinist": "https://bitcoinist.com/feed/",
        "CryptoPotato": "https://cryptopotato.com/feed/",
    }

    def __init__(self, lookback_hours=72, max_per_source=30):
        self.lookback_hours = lookback_hours
        self.max_per_source = max_per_source

    @staticmethod
    def _now_utc():
        return datetime.now(timezone.utc).replace(tzinfo=None)

    def _parse_time(self, time_str):
        if not time_str:
            return self._now_utc()
        formats = [
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%a, %d %b %Y %H:%M:%S %z",
            "%a, %d %b %Y %H:%M:%S %Z",
            "%a, %d %b %Y %H:%M:%S",
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(time_str.strip(), fmt)
                if dt.tzinfo is not None:
                    dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
                return dt
            except Exception:
                continue
        return self._now_utc()

    def _is_recent(self, dt):
        return dt >= self._now_utc() - timedelta(hours=self.lookback_hours)

    def fetch_crypto_cv(self, symbol):
        results = []
        endpoints = [
            ("https://cryptocurrency.cv/api/news", {"limit": self.max_per_source}),
            ("https://cryptocurrency.cv/api/articles", {"limit": self.max_per_source}),
        ]
        for url, params in endpoints:
            try:
                resp = requests.get(url, params=params, timeout=15,
                                    headers={"User-Agent": "Mozilla/5.0"})
                if resp.status_code != 200:
                    continue
                data = resp.json()
                articles = data.get("articles", data.get("data", data if isinstance(data, list) else []))
                for item in articles[: self.max_per_source]:
                    title = item.get("title", "")
                    pub_str = item.get("pubDate", item.get("published_at", item.get("date", "")))
                    pub = self._parse_time(pub_str)
                    if title and self._is_recent(pub):
                        results.append({
                            "title": title,
                            "source": item.get("source", "cryptocurrency.cv"),
                            "published": pub,
                            "url": item.get("link", item.get("url", "")),
                        })
                if results:
                    break
            except Exception:
                continue
        print(f"    [cryptocurrency.cv] {len(results)} 条")
        return results

    def fetch_rss(self, symbol):
        results = []
        for name, feed_url in self.RSS_FEEDS.items():
            try:
                resp = requests.get(
                    feed_url,
                    timeout=15,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                                      "Chrome/120.0.0.0 Safari/537.36",
                        "Accept": "application/rss+xml,application/xml,text/xml,*/*",
                    }
                )
                resp.raise_for_status()
                root = ET.fromstring(resp.content)
                items = root.findall(".//item")
                if not items:
                    items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

                count = 0
                for item in items[: self.max_per_source]:
                    title_el = item.find("title")
                    if title_el is None:
                        title_el = item.find("{http://www.w3.org/2005/Atom}title")
                    pub_el = item.find("pubDate")
                    if pub_el is None:
                        pub_el = item.find("{http://www.w3.org/2005/Atom}published")
                    if pub_el is None:
                        pub_el = item.find("{http://www.w3.org/2005/Atom}updated")
                    link_el = item.find("link")
                    if link_el is None:
                        link_el = item.find("{http://www.w3.org/2005/Atom}link")

                    title = title_el.text if title_el is not None else ""
                    if not title:
                        continue

                    pub_text = pub_el.text if pub_el is not None else ""
                    pub = self._parse_time(pub_text)
                    if not self._is_recent(pub):
                        continue

                    link = ""
                    if link_el is not None:
                        link = link_el.text if link_el.text else link_el.get("href", "")

                    results.append({
                        "title": title,
                        "source": name,
                        "published": pub,
                        "url": link,
                    })
                    count += 1
                print(f"    [{name}] {count} 条")
            except Exception as e:
                print(f"    [{name}] 失败: {str(e)[:80]}")
        return results

    def aggregate(self, symbol):
        print(f"  📡 从多个来源抓取 {symbol} 新闻...")
        all_news = []
        all_news.extend(self.fetch_crypto_cv(symbol))
        all_news.extend(self.fetch_rss(symbol))

        seen = set()
        unique_news = []
        for news in all_news:
            key = re.sub(r"\W+", "", news["title"].lower())[:50]
            if key not in seen:
                seen.add(key)
                unique_news.append(news)

        print(f"  📰 去重后共 {len(unique_news)} 条新闻")
        return unique_news


class PolymarketSentiment:
    """从 Polymarket 获取预测市场数据，转换为情绪分"""

    def __init__(self, timeout=15):
        self.gamma_url = "https://gamma-api.polymarket.com"
        self.timeout = timeout

    def _fetch_markets(self, params):
        try:
            resp = requests.get(
                f"{self.gamma_url}/markets",
                params=params,
                timeout=self.timeout,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"    [Polymarket] 请求失败: {str(e)[:80]}")
            return []

    def fetch_crypto_market_sentiment(self, symbol="BTC"):
        base = symbol.replace("USDC", "").replace("USDT", "").upper()
        keywords = [base.lower(), "bitcoin", "btc", "crypto", "cryptocurrency"]

        all_markets = []

        # 策略1：按 tag 获取加密货币市场
        markets = self._fetch_markets({"closed": "false", "limit": 100, "tag": "crypto"})
        if markets:
            all_markets.extend(markets)

        # 策略2：无 tag 获取大量活跃市场
        if not all_markets:
            markets = self._fetch_markets({"closed": "false", "limit": 100})
            all_markets.extend(markets)

        if not all_markets:
            print("    [Polymarket] 未获取到任何市场数据")
            return 0.0

        relevant = []
        for market in all_markets:
            question = market.get("question", "").lower()
            if any(kw in question for kw in keywords):
                relevant.append(market)

        if not relevant:
            print(f"    [Polymarket] 在 {len(all_markets)} 个市场中未找到与 {base} 相关的市场")
            return 0.0

        scores = []
        for market in relevant[:10]:
            price = (
                market.get("lastTradePrice")
                or market.get("bestBid")
                or market.get("bestAsk")
                or market.get("outcomePrices", [None])[0]
            )
            if price is None:
                continue
            try:
                prob = float(price)
                if prob > 0.6:
                    scores.append(0.5)
                elif prob < 0.4:
                    scores.append(-0.5)
                else:
                    scores.append(0.0)
            except (ValueError, TypeError):
                continue

        if scores:
            avg = float(np.mean(scores))
            print(f"    [Polymarket] 分析 {len(scores)} 个相关市场，情绪分: {avg:+.3f}")
            return avg
        else:
            print(f"    [Polymarket] 找到 {len(relevant)} 个相关市场，但无有效价格数据")
            return 0.0


class NewsSentimentStrategy:
    """多源新闻情绪 + Polymarket预测市场 + 技术指标复合策略"""

    def __init__(self,
                 fast_ema=20,
                 slow_ema=50,
                 lookback=20,
                 sentiment_threshold=0.3,
                 news_lookback_hours=72,
                 max_news_per_source=30,
                 polymarket_weight=0.3):
        self.fast_ema = fast_ema
        self.slow_ema = slow_ema
        self.lookback = lookback
        self.sentiment_threshold = sentiment_threshold
        self.aggregator = NewsAggregator(
            lookback_hours=news_lookback_hours,
            max_per_source=max_news_per_source,
        )
        self.analyzer = SentimentIntensityAnalyzer()
        self.polymarket = PolymarketSentiment()
        self.polymarket_weight = polymarket_weight

    def analyze_news_sentiment(self, news_list):
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
        print(f"  🧠 新闻情绪: 平均 {avg:+.3f} | 正面 {positive} 负面 {negative} 中性 {neutral}")
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
        news_sentiment, pos, neg, neu = self.analyze_news_sentiment(news_list)

        polymarket_sentiment = self.polymarket.fetch_crypto_market_sentiment(
            symbol.replace("USDC", "").replace("USDT", "")
        )

        combined_sentiment = (
            (1 - self.polymarket_weight) * news_sentiment
            + self.polymarket_weight * polymarket_sentiment
        )
        print(f"  🎯 综合情绪分: {combined_sentiment:+.3f} "
              f"(新闻 {news_sentiment:+.3f}, Polymarket {polymarket_sentiment:+.3f})")

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

        if tech_buy and combined_sentiment >= self.sentiment_threshold:
            signal = 1
            reason = f"技术突破 + 情绪积极 ({combined_sentiment:+.2f})"
        elif tech_sell and combined_sentiment <= -self.sentiment_threshold:
            signal = -1
            reason = f"技术走弱 + 情绪消极 ({combined_sentiment:+.2f})"
        elif combined_sentiment >= 0.7:
            signal = 1
            reason = f"极端积极情绪 ({combined_sentiment:+.2f})"
        elif combined_sentiment <= -0.7:
            signal = -1
            reason = f"极端消极情绪 ({combined_sentiment:+.2f})"

        df.loc[df.index[-1], "signal"] = signal
        print(f"  📊 技术: EMA{'↑' if latest['ema_fast'] > latest['ema_slow'] else '↓'} "
              f"| 收盘 {latest['close']:.2f} | 突破位 {latest['high_roll']:.2f}")
        print(f"  🎯 信号: {signal} | 原因: {reason}")
        return df, combined_sentiment, reason
