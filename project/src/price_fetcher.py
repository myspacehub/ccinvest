"""
优化的价格获取模块 v4
支持多个数据源,智能切换和验证
"""

import requests
import time
from typing import Dict, Optional
from loguru import logger

# 缓存配置
_cache: Dict = {}
CACHE_TTL = 10

# 数据源 ID 映射
COINLORE_IDS = {
    "BTC": "90", "ETH": "80", "SOL": "48543",
    "BNB": "2710", "XRP": "5185", "ADA": "5186",
    "DOGE": "2492", "DOT": "2831", "LINK": "28571",
    "MATIC": "29514", "UNI": "34091",
    "LTC": "2911", "FIL": "5673", "AVAX": "29515"
}

COINGECKO_IDS = {
    "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
    "BNB": "binancecoin", "XRP": "ripple", "ADA": "cardano",
    "DOGE": "dogecoin", "DOT": "polkadot", "LINK": "chainlink",
    "MATIC": "matic-network", "UNI": "uniswap", "ATOM": "cosmos",
    "LTC": "litecoin", "FIL": "filecoin", "AVAX": "avalanche-2",
    "ARB": "arbitrum", "OP": "optimism", "PEPE": "pepe",
    "SHIB": "shiba-inu", "BONK": "bonk", "NEAR": "near",
    "HYPE": "hyperliquid"
}

COINPAPRIKA_IDS = {
    "BTC": "btc-bitcoin",
    "ETH": "eth-ethereum",
    "SOL": "sol-solana",
    "BNB": "bnb-binance-coin",
    "XRP": "xrp-xrp",
    "ADA": "ada-cardano",
    "DOGE": "doge-dogecoin",
    "DOT": "dot-polkadot",
    "LINK": "link-chainlink",
    "AVAX": "avax-avalanche",
    "HYPE": "hype-hyperliquid",
}

COINBASE_TICKERS = {
    "BTC": "BTC", "ETH": "ETH", "SOL": "SOL",
    "DOGE": "DOGE", "ADA": "ADA", "XRP": "XRP",
    "LTC": "LTC", "BCH": "BCH", "ETC": "ETC"
}

def get_cached(key: str) -> Optional[Dict]:
    if key in _cache:
        data, timestamp = _cache[key]
        if time.time() - timestamp < CACHE_TTL:
            return data
    return None

def set_cached(key: str, data: Dict):
    _cache[key] = (data, time.time())

def normalize_crypto_symbol(symbol: str) -> str:
    return symbol.upper().replace("USDT", "").replace("USD", "").strip()

def resolve_coingecko_id(symbol: str) -> Optional[str]:
    """Resolve a ticker to CoinGecko coin id using static aliases first, then public search."""
    normalized = normalize_crypto_symbol(symbol)
    if not normalized:
        return None

    mapped = COINGECKO_IDS.get(normalized)
    if mapped:
        return mapped

    cache_key = f"cg_id_{normalized}"
    cached = get_cached(cache_key)
    if cached:
        return cached.get("id")

    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/search",
            params={"query": normalized},
            timeout=8
        )
        if not r.ok:
            return None
        coins = r.json().get("coins", [])
        if not coins:
            return None

        exact_symbol = [
            coin for coin in coins
            if str(coin.get("symbol", "")).upper() == normalized
        ]
        candidates = exact_symbol or coins
        candidates.sort(key=lambda coin: coin.get("market_cap_rank") or 10**9)
        coin_id = candidates[0].get("id")
        if coin_id:
            set_cached(cache_key, {"id": coin_id})
            return coin_id
    except Exception as e:
        logger.debug(f"CoinGecko ID 解析失败 {normalized}: {e}")
    return None

def resolve_coinpaprika_id(symbol: str) -> Optional[str]:
    """Resolve a ticker to CoinPaprika id."""
    normalized = normalize_crypto_symbol(symbol)
    if not normalized:
        return None

    mapped = COINPAPRIKA_IDS.get(normalized)
    if mapped:
        return mapped

    cache_key = f"paprika_id_{normalized}"
    cached = get_cached(cache_key)
    if cached:
        return cached.get("id")

    try:
        r = requests.get(
            "https://api.coinpaprika.com/v1/search/",
            params={"q": normalized, "c": "currencies", "limit": 10},
            timeout=8
        )
        if not r.ok:
            return None
        currencies = r.json().get("currencies", [])
        exact_symbol = [
            item for item in currencies
            if str(item.get("symbol", "")).upper() == normalized and item.get("is_active", True)
        ]
        candidates = exact_symbol or currencies
        candidates.sort(key=lambda item: item.get("rank") or 10**9)
        coin_id = candidates[0].get("id") if candidates else None
        if coin_id:
            set_cached(cache_key, {"id": coin_id})
            return coin_id
    except Exception as e:
        logger.debug(f"CoinPaprika ID 解析失败 {normalized}: {e}")
    return None

def fetch_cryptocompare(symbol: str) -> Optional[Dict]:
    """CryptoCompare API - 免费稳定"""
    full_data = fetch_cryptocompare_full(symbol)
    if full_data:
        return {
            "price": full_data["price"],
            "change_24h": full_data.get("change_24h", 0),
            "market_cap": full_data.get("market_cap", 0),
            "rank": 0,
            "source": "cryptocompare"
        }

    try:
        url = f"https://min-api.cryptocompare.com/data/price?fsym={symbol.upper()}&tsyms=USD"
        r = requests.get(url, timeout=5)
        if r.ok:
            data = r.json()
            if "USD" in data:
                return {"price": float(data["USD"]), "source": "cryptocompare"}
    except:
        pass
    return None

def fetch_cryptocompare_full(symbol: str) -> Optional[Dict]:
    """CryptoCompare full price payload with market stats."""
    normalized = normalize_crypto_symbol(symbol)
    if not normalized:
        return None

    try:
        url = "https://min-api.cryptocompare.com/data/pricemultifull"
        r = requests.get(url, params={"fsyms": normalized, "tsyms": "USD"}, timeout=8)
        if not r.ok:
            return None
        raw = r.json().get("RAW", {}).get(normalized, {}).get("USD", {})
        if not raw or not raw.get("PRICE"):
            return None
        image_url = raw.get("IMAGEURL") or ""
        if image_url.startswith("/"):
            image_url = f"https://www.cryptocompare.com{image_url}"
        return {
            "price": float(raw.get("PRICE") or 0),
            "change_24h": float(raw.get("CHANGEPCT24HOUR") or 0),
            "market_cap": float(raw.get("CIRCULATINGSUPPLYMKTCAP") or raw.get("MKTCAP") or 0),
            "total_volume": float(raw.get("TOTALVOLUME24HTO") or raw.get("VOLUME24HOURTO") or 0),
            "high_24h": float(raw.get("HIGH24HOUR") or raw.get("HIGHDAY") or 0),
            "low_24h": float(raw.get("LOW24HOUR") or raw.get("LOWDAY") or 0),
            "name": normalized,
            "image": image_url,
            "source": "cryptocompare"
        }
    except Exception as e:
        logger.debug(f"CryptoCompare full payload 失败 {normalized}: {e}")
    return None

def fetch_coinlore(symbol: str) -> Optional[Dict]:
    """Coinlore API"""
    coin_id = COINLORE_IDS.get(symbol.upper())
    if not coin_id:
        return None

    try:
        url = f"https://api.coinlore.com/api/ticker/?id={coin_id}"
        r = requests.get(url, timeout=5)
        if r.ok:
            data = r.json()
            if data and len(data) > 0:
                coin = data[0]
                return {
                    "price": float(coin["price_usd"]),
                    "change_24h": float(coin["percent_change_24h"]),
                    "market_cap": float(coin.get("market_cap_usd", 0)),
                    "rank": int(coin.get("rank", 0)),
                    "source": "coinlore"
                }
    except:
        pass
    return None

def fetch_coingecko(symbol: str) -> Optional[Dict]:
    """CoinGecko API"""
    cg_id = resolve_coingecko_id(symbol)
    if not cg_id:
        return None

    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={cg_id}&vs_currencies=usd&include_24hr_change=true"
        r = requests.get(url, timeout=5)
        if r.ok:
            data = r.json()
            if cg_id in data:
                return {
                    "price": data[cg_id]["usd"],
                    "change_24h": data[cg_id].get("usd_24h_change", 0),
                    "source": "coingecko"
                }
    except:
        pass
    return None

def fetch_coingecko_market(symbol: str) -> Optional[Dict]:
    """CoinGecko 市场数据"""
    cg_id = resolve_coingecko_id(symbol)
    if not cg_id:
        return None

    try:
        url = "https://api.coingecko.com/api/v3/coins/markets"
        params = {"vs_currency": "usd", "ids": cg_id, "order": "market_cap_desc", "per_page": 1, "page": 1, "sparkline": False}
        r = requests.get(url, params=params, timeout=10)
        if r.ok:
            data = r.json()
            if data and len(data) > 0:
                coin = data[0]
                return {
                    "market_cap": coin.get("market_cap") or 0,
                    "market_cap_rank": coin.get("market_cap_rank") or 0,
                    "total_volume": coin.get("total_volume") or 0,
                    "high_24h": coin.get("high_24h") or 0,
                    "low_24h": coin.get("low_24h") or 0,
                    "name": coin.get("name", symbol),
                    "image": coin.get("image", "")
                }
    except:
        pass
    return None

def fetch_cryptocompare_market(symbol: str) -> Optional[Dict]:
    """CryptoCompare market stats fallback."""
    data = fetch_cryptocompare_full(symbol)
    if not data:
        return None
    return {
        "market_cap": data.get("market_cap", 0),
        "market_cap_rank": 0,
        "total_volume": data.get("total_volume", 0),
        "high_24h": data.get("high_24h", 0),
        "low_24h": data.get("low_24h", 0),
        "name": data.get("name", symbol),
        "image": data.get("image", "")
    }

def fetch_coinpaprika_market(symbol: str) -> Optional[Dict]:
    """CoinPaprika market stats and latest OHLC fallback."""
    coin_id = resolve_coinpaprika_id(symbol)
    if not coin_id:
        return None

    market = {}
    try:
        ticker = requests.get(f"https://api.coinpaprika.com/v1/tickers/{coin_id}", timeout=8)
        if ticker.ok:
            data = ticker.json()
            quote = data.get("quotes", {}).get("USD", {})
            market.update({
                "market_cap": quote.get("market_cap") or 0,
                "market_cap_rank": data.get("rank") or 0,
                "total_volume": quote.get("volume_24h") or 0,
                "name": data.get("name", symbol),
            })
    except Exception as e:
        logger.debug(f"CoinPaprika ticker 失败 {symbol}: {e}")

    try:
        ohlc = requests.get(f"https://api.coinpaprika.com/v1/coins/{coin_id}/ohlcv/latest/", timeout=8)
        if ohlc.ok:
            rows = ohlc.json()
            if rows:
                latest = rows[0]
                market.update({
                    "high_24h": latest.get("high") or 0,
                    "low_24h": latest.get("low") or 0,
                    "total_volume": market.get("total_volume") or latest.get("volume") or 0,
                    "market_cap": market.get("market_cap") or latest.get("market_cap") or 0,
                })
    except Exception as e:
        logger.debug(f"CoinPaprika OHLC 失败 {symbol}: {e}")

    return market or None

def merge_market_data(primary: Dict, fallback: Dict) -> Dict:
    merged = dict(primary or {})
    for key, value in (fallback or {}).items():
        if key in {"market_cap", "market_cap_rank", "total_volume", "high_24h", "low_24h"}:
            if not merged.get(key):
                merged[key] = value
        elif key in {"name", "image"} and not merged.get(key):
            merged[key] = value
    return merged

def fetch_coinbase(symbol: str) -> Optional[Dict]:
    """Coinbase API"""
    ticker = COINBASE_TICKERS.get(symbol.upper())
    if not ticker:
        return None

    try:
        url = f"https://api.coinbase.com/v2/prices/{ticker}-USD/spot"
        r = requests.get(url, timeout=5)
        if r.ok:
            data = r.json()
            return {"price": float(data["data"]["amount"]), "source": "coinbase"}
    except:
        pass
    return None

def get_price_with_fallback(symbol: str) -> Dict:
    """获取价格 - 智能回退"""
    cache_key = f"price_{symbol.upper()}"

    cached = get_cached(cache_key)
    if cached:
        return cached

    result = None
    source = "unknown"
    change_24h = 0
    market_cap = 0
    rank = 0

    # 优先级1: CoinGecko
    cg_data = fetch_coingecko(symbol)
    if cg_data:
        result = cg_data
        source = "coingecko"
        change_24h = cg_data.get("change_24h", 0)

    # 如果 CoinGecko 没有 change_24h，从 Coinlore 获取
    if change_24h == 0:
        cl_data = fetch_coinlore(symbol)
        if cl_data:
            change_24h = cl_data.get("change_24h", 0)
            market_cap = cl_data.get("market_cap", 0)
            rank = cl_data.get("rank", 0)

    # 优先级2: Coinbase
    if not result:
        cb_data = fetch_coinbase(symbol)
        if cb_data:
            result = cb_data
            source = "coinbase"
            # Coinbase 不返回 change_24h，尝试从 Coinlore 获取
            if change_24h == 0:
                cl_data = fetch_coinlore(symbol)
                if cl_data:
                    change_24h = cl_data.get("change_24h", 0)
                    market_cap = cl_data.get("market_cap", 0)
                    rank = cl_data.get("rank", 0)

    # 优先级3: CryptoCompare
    if not result:
        cc_data = fetch_cryptocompare(symbol)
        if cc_data:
            result = cc_data
            source = "cryptocompare"
            # CryptoCompare 也不返回 change_24h
            if change_24h == 0:
                cl_data = fetch_coinlore(symbol)
                if cl_data:
                    change_24h = cl_data.get("change_24h", 0)
                    market_cap = cl_data.get("market_cap", 0)
                    rank = cl_data.get("rank", 0)

    # 优先级4: Coinlore
    if not result:
        cl_data = fetch_coinlore(symbol)
        if cl_data:
            result = cl_data
            source = "coinlore"
            change_24h = cl_data.get("change_24h", 0)
            market_cap = cl_data.get("market_cap", 0)
            rank = cl_data.get("rank", 0)

    if result:
        result["source"] = source
        result["change_24h"] = change_24h
        result["market_cap"] = market_cap
        result["rank"] = rank
        set_cached(cache_key, result)

    return result or {"price": 0, "change_24h": 0, "source": "failed", "market_cap": 0, "rank": 0}

def get_market_data_with_fallback(symbol: str) -> Dict:
    """获取市场数据"""
    cache_key = f"market_{symbol.upper()}"

    cached = get_cached(cache_key)
    if cached:
        return cached

    result: Dict = {}

    cg_data = fetch_coingecko_market(symbol)
    if cg_data:
        result = merge_market_data(result, cg_data)

    if not all(result.get(key) for key in ("market_cap", "total_volume", "high_24h", "low_24h")):
        cp_data = fetch_coinpaprika_market(symbol)
        if cp_data:
            result = merge_market_data(result, cp_data)

    if not all(result.get(key) for key in ("market_cap", "total_volume", "high_24h", "low_24h")):
        cc_data = fetch_cryptocompare_market(symbol)
        if cc_data:
            result = merge_market_data(result, cc_data)

    if result:
        set_cached(cache_key, result)

    return result or {"market_cap": 0, "market_cap_rank": 0, "total_volume": 0}

# 测试
if __name__ == "__main__":
    print("=== 优化价格获取模块测试 v4 ===\n")

    symbols = ["BTC", "ETH", "SOL", "DOGE", "XRP", "ADA", "DOT", "LINK", "MATIC", "UNI", "AVAX", "ATOM"]

    success = 0
    for symbol in symbols:
        start = time.time()
        price_data = get_price_with_fallback(symbol)
        market_data = get_market_data_with_fallback(symbol)
        elapsed = (time.time() - start) * 1000

        mc = market_data.get('market_cap', 0)
        status = "✅" if price_data.get('price', 0) > 0 else "❌"

        if mc > 1e9:
            mc_str = f"${mc/1e9:.1f}B"
        elif mc > 0:
            mc_str = f"${mc/1e6:.1f}M"
        else:
            mc_str = "-"

        print(f"{status} {symbol:6}: ${price_data.get('price', 0):>12,.2f} ({price_data.get('change_24h', 0):>+6.2f}%) | {mc_str:>10} | #{market_data.get('market_cap_rank', 0):>3} | {elapsed:.0f}ms [{price_data.get('source', 'N/A'):12}]")

        if price_data.get('price', 0) > 0:
            success += 1

    print(f"\n成功: {success}/{len(symbols)}")
