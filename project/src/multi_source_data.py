# =====================================================
# CC Invest - 多源数据获取策略
# 严格禁用模拟数据，所有数据必须来自真实来源
# =====================================================
# 快捷函数
# =====================================================

def get_real_price(symbol: str) -> Optional[float]:
    """获取真实价格"""
    manager = MultiSourceDataManager()
    result, _ = manager.get_price(symbol)
    return result["price"] if result else None


# =====================================================
# 主程序测试
# =====================================================

if __name__ == "__main__":
    manager = MultiSourceDataManager()
    
    print()
    print("=" * 60)
    print("多源数据获取系统 - 纯真实数据版")
    print("=" * 60)
    print()
    
    print("📋 数据源列表:")
    for s in manager.sources:
        print(f"   [{s.priority:2d}] {s.name}")
    print()
    
    symbol = "ETHUSDT"
    print(f"🔍 获取 {symbol} 价格...")
    print()
    
    result = manager.get_price_with_fallback(symbol)
    
    if result["success"]:
        data = result["data"]
        print("✅ 获取成功!")
        print()
        print("📊 价格数据:")
        print(f"   交易对: {data['symbol']}")
        print(f"   价格:   ${data['price']:,.2f}")
        print(f"   来源:   {data['source']}")
        print(f"   时间:   {data['timestamp']}")
        if data.get("change_24h"):
            print(f"   24h:    {data['change_24h']:+.2f}%")
        
        if result["meta"].get("cross_validation"):
            cv = result["meta"]["cross_validation"]
            print()
            print("🔍 交叉验证:")
            print(f"   发现 {cv['sources_found']} 个数据源")
            print(f"   最大差异: {cv['max_diff_percent']:.2f}%")
            print(f"   一致性: {'✅ 一致' if cv['is_consistent'] else '⚠️ 不一致'}")
    else:
        print("❌ 获取失败")
        print(f"   错误: {result['error']}")
        print(f"   尝试: {result['attempts']} 个数据源")
    
    print()
    print("=" * 60)

# =====================================================
# Solana 区块链数据源
# =====================================================

class SolanaSource(DataSourceBase):
    """Solana 区块链数据源"""
    
    name = "solana"
    priority = 6
    
    def __init__(self):
        super().__init__()
        self.api_key = os.getenv("COINGECKO_API_KEY", "")
    
    def is_available(self) -> bool:
        try:
            r = requests.get(
                "https://api.coingecko.com/api/v3/ping",
                timeout=5
            )
            return r.status_code == 200
        except:
            return False
    
    def fetch_price(self, symbol: str) -> Optional[Dict]:
        """通过 CoinGecko 获取 Solana 代币价格"""
        try:
            # Solana 代币映射
            token_map = {
                "SOLUSDT": "solana",
                "BONKUSDT": "bonk",
                "WIFUSDT": "dogwifcoin",
                "POPCATUSDT": "popcat",
                "BOOKOFMEMEUSDT": "book-of-meme",
                "FWOGUSDT": "fwog",
                "CHICKYSUSDT": "chicky-sols",
                "PNUTUSDT": "peanut-the-frog",
                "GOATUSDT": "goatcoin",
                "MEUSDT": "me-a-tagaino",
                "SLERFUSDT": "slerf",
            }
            
            coin_id = token_map.get(symbol.upper())
            
            # 如果不在映射中，尝试通用查询
            if not coin_id:
                # 尝试解析 symbol 获取 coin id
                base = symbol.replace("USDT", "").upper()
                coin_id = base.lower()
            
            url = f"https://api.coingecko.com/api/v3/simple/price"
            params = {
                "ids": coin_id,
                "vs_currencies": "usd",
                "include_24hr_change": "true"
            }
            
            if self.api_key:
                params["x_cg_demo_api_key"] = self.api_key
            
            response = requests.get(url, params=params, timeout=self.timeout)
            
            if response.status_code == 200:
                data = response.json()
                if coin_id in data:
                    price_data = data[coin_id]
                    return {
                        "symbol": symbol,
                        "price": price_data.get("usd", 0),
                        "change_24h": price_data.get("usd_24h_change", 0),
                        "source": "coingecko_solana",
                        "timestamp": datetime.utcnow()
                    }
            
            return None
            
        except Exception as e:
            log_debug(f"Solana 价格获取失败: {e}")
            return None
    
    def validate_data(self, data: Dict) -> Tuple[bool, str]:
        if not data or data.get("price", 0) <= 0:
            return False, "Invalid price"
        return True, "Valid"


class SolanaContractSource(DataSourceBase):
    """Solana 合约地址数据源"""
    
    name = "solana_contract"
    priority = 7
    
    def __init__(self):
        super().__init__()
        self.rpc_url = "https://api.mainnet-beta.solana.com"
    
    def is_available(self) -> bool:
        try:
            r = requests.post(
                self.rpc_url,
                json={"jsonrpc": "2.0", "id": 1, "method": "getHealth"},
                timeout=5
            )
            return r.status_code == 200
        except:
            return False
    
    def fetch_price(self, symbol: str) -> Optional[Dict]:
        """通过合约地址获取 Solana 代币价格"""
        try:
            # 常见 Solana 代币合约地址
            contract_map = {
                "So11111111111111111111111111111111111111112": "SOL",
                "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs": "BONK",
                "EKpGSQ84TVPg5LdJEBH2bBi1U7oL1vKPMcFYYME4H3X": "WIF",
                "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr": "POPCAT",
            }
            
            # 如果输入的是合约地址
            if symbol.startswith("0x") or len(symbol) > 44:
                # 尝试解析 Solana 地址
                address = symbol
            
            return None  # 需要第三方价格源
            
        except Exception as e:
            log_debug(f"Solana 合约价格获取失败: {e}")
            return None


# =====================================================
# BSC (Binance Smart Chain) 数据源
# =====================================================

class BSCSource(DataSourceBase):
    """BSC (Binance Smart Chain) 数据源"""
    
    name = "bsc"
    priority = 5
    
    def __init__(self):
        super().__init__()
        self.api_key = os.getenv("COINGECKO_API_KEY", "")
    
    def is_available(self) -> bool:
        try:
            r = requests.get("https://api.coingecko.com/api/v3/ping", timeout=5)
            return r.status_code == 200
        except:
            return False
    
    def fetch_price(self, symbol: str) -> Optional[Dict]:
        """通过 CoinGecko 获取 BSC 代币价格"""
        try:
            # BSC 热门代币映射
            token_map = {
                "BNBUSDT": "binancecoin",
                "BUSDUSDT": "binance-usd",
                "PEPEUSDT": "pepe",
                "SHIBUSDT": "shiba-inu",
                "DOGEUSDT": "dogecoin",
                "CAKEUSDT": "pancakeswap-token",
                "BSWUSDT": "bitswift",
                "HIGHUSDT": "highstreet",
                "ARENAUSDT": "sandbox",
                "SANDUSDT": "the-sandbox",
                "AXSUSDT": "axie-infinity",
                "CHESSUSDT": "tronbook",
                "TRIASUSDT": "tronbook",
                "BTTUSDT": "bittensor",
                "WBNBUSDT": "wrapped-bnb",
                "ETHUSDT": "ethereum",
                "BTCUSDT": "bitcoin",
            }
            
            coin_id = token_map.get(symbol.upper())
            
            if not coin_id:
                # 尝试通用映射
                base = symbol.replace("USDT", "").upper()
                coin_id = base.lower()
                
                # 特殊处理
                if base == "PEPE": coin_id = "pepe"
                elif base == "SHIB": coin_id = "shiba-inu"
                elif base == "DOGE": coin_id = "dogecoin"
            
            url = "https://api.coingecko.com/api/v3/simple/price"
            params = {
                "ids": coin_id,
                "vs_currencies": "usd",
                "include_24hr_change": "true"
            }
            
            response = requests.get(url, params=params, timeout=self.timeout)
            
            if response.status_code == 200:
                data = response.json()
                if coin_id in data:
                    price_data = data[coin_id]
                    return {
                        "symbol": symbol,
                        "price": price_data.get("usd", 0),
                        "change_24h": price_data.get("usd_24h_change", 0),
                        "source": "coingecko_bsc",
                        "timestamp": datetime.utcnow()
                    }
            
            return None
            
        except Exception as e:
            log_debug(f"BSC 价格获取失败: {e}")
            return None
    
    def validate_data(self, data: Dict) -> Tuple[bool, str]:
        if not data or data.get("price", 0) <= 0:
            return False, "Invalid price"
        return True, "Valid"


class BSCContractSource(DataSourceBase):
    """BSC 合约地址数据源"""
    
    name = "bsc_contract"
    priority = 8
    
    def __init__(self):
        super().__init__()
        self.api_key = os.getenv("BSCSCAN_API_KEY", "")
    
    def is_available(self) -> bool:
        return bool(self.api_key) or True  # 可用公开端点
    
    def fetch_price(self, symbol: str) -> Optional[Dict]:
        """通过 BSCScan API 获取代币价格"""
        try:
            # 如果是合约地址
            if symbol.startswith("0x"):
                # 需要 BSCScan API key
                pass
            
            return None
            
        except Exception as e:
            log_debug(f"BSC 合约价格获取失败: {e}")
            return None




# =====================================================
# Base Chain 数据源
# =====================================================

class BaseSource(DataSourceBase):
    """Base 区块链数据源 (Coinbase L2)"""
    
    name = "base"
    priority = 10
    
    def is_available(self) -> bool:
        return True  # 始终可用
    
    def fetch_price(self, symbol: str) -> Optional[Dict]:
        """通过 DexScreener 获取 Base 代币价格"""
        try:
            # 合约地址
            if symbol.startswith("0x"):
                url = f"https://api.dexscreener.com/latest/dex/tokens/{symbol}"
            elif len(symbol) > 40:
                url = f"https://api.dexscreener.com/latest/dex/tokens/{symbol}"
            else:
                # 尝试搜索
                search_url = f"https://api.dexscreener.com/latest/dex/search?q={symbol}"
                r = requests.get(search_url, timeout=self.timeout)
                if not r.ok:
                    return None
                data = r.json()
                pairs = data.get("pairs", [])
                base_pairs = [p for p in pairs if p.get("chainId") == "base"]
                if not base_pairs:
                    return None
                p = max(base_pairs, key=lambda x: float(x.get("liquidity", {}).get("usd", 0) or 0))
                return {
                    "symbol": p.get("baseToken", {}).get("symbol", symbol),
                    "name": p.get("baseToken", {}).get("name", ""),
                    "price": float(p.get("priceUsd", 0)),
                    "change_24h": float(p.get("priceChange", {}).get("m24", 0)),
                    "volume_24h": float(p.get("volume", {}).get("h24", 0)),
                    "liquidity": float(p.get("liquidity", {}).get("usd", 0)),
                    "source": "dexscreener_base",
                    "chain": "base",
                    "timestamp": datetime.utcnow()
                }
            
            response = requests.get(url, timeout=self.timeout)
            if not response.ok:
                return None
            
            data = response.json()
            pairs = data.get("pairs", [])
            if not pairs:
                return None
            
            # 取 Base 链流动性最高的
            base_pairs = [p for p in pairs if p.get("chainId") == "base"]
            if not base_pairs:
                base_pairs = pairs
            
            best = max(base_pairs, key=lambda x: float(x.get("liquidity", {}).get("usd", 0) or 0))
            
            return {
                "symbol": best.get("baseToken", {}).get("symbol", symbol),
                "name": best.get("baseToken", {}).get("name", ""),
                "price": float(best.get("priceUsd", 0)),
                "change_24h": float(best.get("priceChange", {}).get("m24", 0)),
                "volume_24h": float(best.get("volume", {}).get("h24", 0)),
                "liquidity": float(best.get("liquidity", {}).get("usd", 0)),
                "source": "dexscreener_base",
                "chain": "base",
                "timestamp": datetime.utcnow()
            }
            
        except Exception as e:
            log_debug(f"Base 价格获取失败: {e}")
            return None
    
    def validate_data(self, data: Dict) -> Tuple[bool, str]:
        if not data or data.get("price", 0) <= 0:
            return False, "Invalid price"
        return True, "Valid"


# =====================================================
# DexScreener 多链数据源
# =====================================================

class DexScreenerSource(DataSourceBase):
    """DexScreener 多链代币数据源 (Solana/BSC/ETH)"""
    
    name = "dexscreener"
    priority = 9  # 低优先级备选
    
    def is_available(self) -> bool:
        try:
            r = requests.get("https://api.dexscreener.com/health", timeout=5)
            return r.status_code == 200
        except:
            return True  # 始终可用作为备选
    
    # 代币符号映射到 DexScreener 搜索关键词
    TOKEN_SEARCH_MAP = {
        # Solana
        "SOL": "SOL", "BONK": "BONK", "WIF": "dogwifcoin", "POPCAT": "POPCAT",
        "FWOG": "FWOG", "PNUT": "peanut", "GOAT": "GOAT", "SLERF": "SLERF", "MEW": "MEW",
        # Base
        "BRETT": "BRETT", "CBBTC": "cbBTC", "DEGEN": "DEGEN", "MUBI": "MUBI",
        "HOURS": "HOURS", "DOLS": "DOLS",
        # BSC
        "BNB": "BNB", "PEPE": "PEPE", "SHIB": "SHIB", "DOGE": "DOGE", "CAKE": "Cake",
        "HIGH": "HIGH", "BUSD": "BUSD",
        # Ethereum
        "ETH": "ETH", "BTC": "WBTC", "ARB": "ARB", "OP": "OP", "MATIC": "MATIC",
        "AVAX": "AVAX", "LINK": "LINK", "UNI": "UNI", "AAVE": "AAVE", "CRV": "CRV",
    }
    
    def fetch_price(self, symbol: str) -> Optional[Dict]:
        """通过 DexScreener 获取代币价格"""
        try:
            # 检测是否为合约地址
            if symbol.startswith("0x"):
                url = f"https://api.dexscreener.com/latest/dex/tokens/{symbol}"
            elif len(symbol) > 44:
                url = f"https://api.dexscreener.com/latest/dex/tokens/{symbol}"
            else:
                # 使用映射表搜索
                search_term = self.TOKEN_SEARCH_MAP.get(symbol.upper(), symbol)
                r = requests.get(f"https://api.dexscreener.com/latest/dex/search?q={search_term}", timeout=self.timeout)
                if not r.ok:
                    return None
                data = r.json()
                pairs = data.get("pairs", [])
                if pairs:
                    best = max(pairs, key=lambda x: float(x.get("liquidity", {}).get("usd", 0) or 0))
                    return {
                        "symbol": best.get("baseToken", {}).get("symbol", symbol),
                        "name": best.get("baseToken", {}).get("name", ""),
                        "price": float(best.get("priceUsd", 0)),
                        "change_24h": float(best.get("priceChange", {}).get("m24", 0)),
                        "source": f"dexscreener_{best.get('chainId', 'unknown')}",
                        "timestamp": datetime.utcnow()
                    }
                return None
            
            response = requests.get(url, timeout=self.timeout)
            
            if response.status_code == 200:
                data = response.json()
                pairs = data.get("pairs", [])
                
                if pairs:
                    # 取流动性最高的交易对
                    best_pair = max(pairs, key=lambda x: float(x.get("liquidity", {}).get("usd", 0) or 0))
                    
                    base_token = best_pair.get("baseToken", {})
                    quote_token = best_pair.get("quoteToken", {})
                    
                    return {
                        "symbol": base_token.get("symbol", symbol),
                        "price": float(best_pair.get("priceUsd", 0)),
                        "change_24h": float(best_pair.get("priceChange", {}).get("m24", 0)),
                        "volume_24h": float(best_pair.get("volume", {}).get("h24", 0)),
                        "liquidity": float(best_pair.get("liquidity", {}).get("usd", 0)),
                        "source": f"dexscreener_{best_pair.get('chainId', 'unknown')}",
                        "timestamp": datetime.utcnow()
                    }
            
            return None
            
        except Exception as e:
            log_debug(f"DexScreener 价格获取失败: {e}")
            return None
    
    def validate_data(self, data: Dict) -> Tuple[bool, str]:
        if not data or data.get("price", 0) <= 0:
            return False, "Invalid price"
        return True, "Valid"


# =====================================================
# 多源数据管理器 (移到文件末尾以解决前向引用)
# =====================================================


# =====================================================

import os
import re
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
from abc import ABC, abstractmethod

import requests


def log_info(msg):
    print(f"[INFO] {msg}")

def log_warning(msg):
    print(f"[WARNING] {msg}")

def log_error(msg):
    print(f"[ERROR] {msg}")

def log_debug(msg):
    print(f"[DEBUG] {msg}")


# =====================================================
# 数据源基类
# =====================================================

class DataSourceBase(ABC):
    """数据源抽象基类"""
    
    name: str = "base"
    priority: int = 100
    timeout: int = 15
    
    @abstractmethod
    def fetch_price(self, symbol: str) -> Optional[Dict]:
        """获取价格数据"""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """检查数据源是否可用"""
        pass
    
    def validate_data(self, data: Dict) -> Tuple[bool, str]:
        """验证数据真实性"""
        if not data or "price" not in data:
            return False, "缺少价格字段"
        
        try:
            price = float(data["price"])
            if price <= 0:
                return False, "价格必须大于0"
            return True, "OK"
        except (TypeError, ValueError):
            return False, "价格格式错误"


# =====================================================
# 数据源1: Yahoo Finance API (最可靠)
# =====================================================

class YahooFinanceSource(DataSourceBase):
    """Yahoo Finance API 数据源"""
    
    name = "yahoo_finance"
    priority = 5
    
    def is_available(self) -> bool:
        return True
    
    def fetch_price(self, symbol: str) -> Optional[Dict]:
        """通过 Yahoo Finance 获取"""
        symbol_map = {
            "BTCUSDT": "BTC-USD",
            "ETHUSDT": "ETH-USD",
            "BNBUSDT": "BNB-USD",
            "SOLUSDT": "SOL-USD",
            "XRPUSDT": "XRP-USD",
            "ADAUSDT": "ADA-USD",
            "DOGEUSDT": "DOGE-USD",
            "DOTUSDT": "DOT-USD",
        }
        yahoo_symbol = symbol_map.get(symbol, symbol.replace("USDT", "-USD"))
        
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            }
            response = requests.get(url, headers=headers, timeout=self.timeout)
            
            if response.status_code == 200:
                data = response.json()
                result = data.get("chart", {}).get("result", [])
                if result:
                    meta = result[0].get("meta", {})
                    price = meta.get("regularMarketPrice")
                    if price:
                        return {
                            "symbol": symbol,
                            "price": float(price),
                            "source": "yahoo_finance",
                            "timestamp": datetime.utcnow(),
                            "currency": meta.get("currency", "USD")
                        }
        except Exception as e:
            log_debug(f"Yahoo Finance 失败: {e}")
        
        return None


# =====================================================
# 数据源2: CoinGecko API
# =====================================================

class CoinGeckoSource(DataSourceBase):
    """CoinGecko API 数据源"""
    
    name = "coingecko"
    priority = 10
    
    def is_available(self) -> bool:
        return True
    
    def fetch_price(self, symbol: str) -> Optional[Dict]:
        """通过 CoinGecko 获取"""
        symbol_map = {
            "BTCUSDT": "bitcoin",
            "ETHUSDT": "ethereum",
            "BNBUSDT": "binancecoin",
            "SOLUSDT": "solana",
            "XRPUSDT": "ripple",
            "ADAUSDT": "cardano",
            "DOGEUSDT": "dogecoin",
            "DOTUSDT": "polkadot",
        }
        
        coin_id = symbol_map.get(symbol)
        if not coin_id:
            return None
        
        try:
            url = f"https://api.coingecko.com/api/v3/simple/price"
            params = {
                "ids": coin_id,
                "vs_currencies": "usd",
                "include_24hr_change": "true"
            }
            
            response = requests.get(url, params=params, timeout=self.timeout)
            if response.status_code == 200:
                data = response.json()
                if coin_id in data and "usd" in data[coin_id]:
                    return {
                        "symbol": symbol,
                        "price": float(data[coin_id]["usd"]),
                        "change_24h": data[coin_id].get("usd_24h_change", 0),
                        "source": "coingecko",
                        "timestamp": datetime.utcnow()
                    }
        except Exception as e:
            log_debug(f"CoinGecko 失败: {e}")
        
        return None


# =====================================================
# 数据源3: CryptoCompare API
# =====================================================

class CryptoCompareSource(DataSourceBase):
    """CryptoCompare API 数据源"""
    
    name = "cryptocompare"
    priority = 8
    
    def is_available(self) -> bool:
        return True
    
    def fetch_price(self, symbol: str) -> Optional[Dict]:
        """通过 CryptoCompare 获取"""
        crypto_symbol = symbol.replace("USDT", "")
        
        try:
            url = "https://min-api.cryptocompare.com/data/price"
            params = {"fsym": crypto_symbol, "tsyms": "USD"}
            
            response = requests.get(url, params=params, timeout=self.timeout)
            if response.status_code == 200:
                data = response.json()
                if "USD" in data:
                    return {
                        "symbol": symbol,
                        "price": float(data["USD"]),
                        "source": "cryptocompare",
                        "timestamp": datetime.utcnow()
                    }
        except Exception as e:
            log_debug(f"CryptoCompare 失败: {e}")
        
        return None


# =====================================================
# 数据源4: 交易所 API (Binance/Coinbase/Kraken)
# =====================================================

class ExchangeAPISource(DataSourceBase):
    """交易所 API 数据源"""
    
    name = "exchange_api"
    priority = 12
    
    def is_available(self) -> bool:
        try:
            requests.get("https://httpbin.org/ip", timeout=5)
            return True
        except:
            return False
    
    def fetch_price(self, symbol: str) -> Optional[Dict]:
        """通过多个交易所 API 获取"""
        exchanges = [
            ("binance", "https://api.binance.com/api/v3/ticker/price", {"symbol": symbol}),
            ("kraken", "https://api.kraken.com/0/public/Ticker", {"pair": symbol.replace("USDT", "USD").replace("BTC", "XXBT")}),
            ("coinbase", "https://api.coinbase.com/v2/prices/spot", {"currency": symbol.replace("USDT", "USD")}),
        ]
        
        for name, url, params in exchanges:
            try:
                response = requests.get(url, params=params, timeout=self.timeout)
                if response.status_code == 200:
                    data = response.json()
                    # Parse different exchange responses
                    price = None
                    if name == "binance" and "price" in data:
                        price = data["price"]
                    elif name == "kraken":
                        # Kraken returns {"result":{"XXBTZUSD":{"c":[price, volume]}}}
                        try:
                            ticker = list(data["result"].values())[0]
                            price = ticker["c"][0]
                        except:
                            pass
                    elif name == "coinbase":
                        # Coinbase returns {"data":{"amount":"price", ...}}
                        try:
                            price = data["data"]["amount"]
                        except:
                            pass
                    
                    if price:
                        return {
                            "symbol": symbol,
                            "price": float(price),
                            "source": name,
                            "timestamp": datetime.utcnow()
                        }
            except Exception as e:
                log_debug(f"{name} 失败: {e}")
                continue
        
        return None


# =====================================================
# 数据源5: Web Scraping (DuckDuckGo)
# =====================================================

class WebScrapingSource(DataSourceBase):
    """网页抓取数据源"""
    
    name = "web_scraping"
    priority = 20
    
    def is_available(self) -> bool:
        return True
    
    def fetch_price(self, symbol: str) -> Optional[Dict]:
        """从网页提取价格"""
        queries = {
            "BTCUSDT": "BTC Bitcoin price USD now 2024",
            "ETHUSDT": "ETH Ethereum price USD now 2024",
            "BNBUSDT": "BNB Binance coin price USD",
            "SOLUSDT": "SOL Solana price USD",
        }
        query = queries.get(symbol, f"{symbol} crypto price USD")
        
        try:
            search_url = f"https://lite.duckduckgo.com/lite/?q={query.replace(' ', '+')}"
            headers = {"User-Agent": "Mozilla/5.0"}
            response = requests.get(search_url, headers=headers, timeout=self.timeout)
            
            if response.status_code == 200:
                text = response.text
                price_patterns = [
                    r'\$([0-9,]+\.?[0-9]*)',
                    r'([0-9,]+\.[0-9]{2})\s*(?:USD|USDT)',
                ]
                
                for pattern in price_patterns:
                    matches = re.findall(pattern, text, re.IGNORECASE)
                    for match in matches[:10]:
                        try:
                            price = float(match.replace(",", ""))
                            if self._is_valid_price(symbol, price):
                                return {
                                    "symbol": symbol,
                                    "price": price,
                                    "source": "duckduckgo",
                                    "timestamp": datetime.utcnow()
                                }
                        except:
                            continue
        except Exception as e:
            log_debug(f"DuckDuckGo 失败: {e}")
        
        return None
    
    def _is_valid_price(self, symbol: str, price: float) -> bool:
        """验证价格是否合理"""
        expected_ranges = {
            "BTCUSDT": (10000, 200000),
            "ETHUSDT": (1000, 20000),
            "BNBUSDT": (100, 2000),
            "SOLUSDT": (10, 1000),
            "XRPUSDT": (0.1, 20),
            "ADAUSDT": (0.1, 10),
        }
        min_price, max_price = expected_ranges.get(symbol, (0, float("inf")))
        return min_price <= price <= max_price


# =====================================================
# 数据源6: 链上预言机 (Uniswap)
# =====================================================

class BlockchainSource(DataSourceBase):
    """区块链预言机数据源"""
    
    name = "blockchain"
    priority = 25
    
    def is_available(self) -> bool:
        return True
    
    def fetch_price(self, symbol: str) -> Optional[Dict]:
        """通过链上 DEX 获取价格"""
        if "ETH" not in symbol:
            return None
        
        try:
            url = "https://api.thegraph.com/subgraphs/name/uniswap/uniswap-v2"
            query = """
            {
                pair(id: "0x0d4a11d5eeaac28ec3f61d100daf4d40471f1852") {
                    token1Price
                }
            }
            """
            response = requests.post(url, json={"query": query}, timeout=self.timeout)
            if response.status_code == 200:
                data = response.json()
                price_str = data.get("data", {}).get("pair", {}).get("token1Price")
                if price_str:
                    eth_per_usdt = float(price_str)
                    return {
                        "symbol": symbol,
                        "price": 1 / eth_per_usdt,
                        "source": "uniswap",
                        "timestamp": datetime.utcnow()
                    }
        except Exception as e:
            log_debug(f"Uniswap 失败: {e}")
        
        return None


# =====================================================
# 数据源7: 历史缓存 (有时限)
# =====================================================

class HistoricalSource(DataSourceBase):
    """历史数据缓存源"""
    
    name = "historical"
    priority = 50
    max_age_hours = 6
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or "data/ccinvest.db"
    
    def is_available(self) -> bool:
        return os.path.exists(self.db_path)
    
    def fetch_price(self, symbol: str) -> Optional[Dict]:
        """从历史数据库获取"""
        try:
            import sqlite3
            
            if not os.path.exists(self.db_path):
                return None
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT price, timestamp FROM market_data 
                WHERE symbol = ?
                ORDER BY timestamp DESC LIMIT 1
            """, (symbol,))
            
            row = cursor.fetchone()
            conn.close()
            
            if row:
                timestamp = datetime.fromisoformat(row[1]) if isinstance(row[1], str) else row[1]
                # 确保时间戳是 naive 的，以便比较
                if timestamp.tzinfo is not None:
                    timestamp = timestamp.replace(tzinfo=None)
                age_hours = (datetime.utcnow() - timestamp).total_seconds() / 3600
                
                if age_hours <= self.max_age_hours:
                    return {
                        "symbol": symbol,
                        "price": float(row[0]),
                        "source": "historical_cache",
                        "timestamp": timestamp,
                        "is_stale": False,
                        "age_hours": age_hours
                    }
                else:
                    log_warning(f"历史数据过期: {age_hours:.1f}小时")
                    return {
                        "symbol": symbol,
                        "price": float(row[0]),
                        "source": "historical_cache_expired",
                        "timestamp": timestamp,
                        "is_stale": True,
                        "age_hours": age_hours
                    }
        except Exception as e:
            log_debug(f"历史数据获取失败: {e}")
        
        return None


# =====================================================
# 多源数据获取管理器
# =====================================================

class MultiSourceDataManager:
    """多源数据获取管理器 - 仅使用真实数据源"""
    
    def __init__(self):
        self.sources: List[DataSourceBase] = [
            YahooFinanceSource(),      # Yahoo Finance
            CryptoCompareSource(),      # CryptoCompare
            CoinGeckoSource(),          # CoinGecko (多链)
            SolanaSource(),            # Solana 区块链
            BSCSource(),               # BSC 区块链
            ExchangeAPISource(),       # 交易所 API
            BlockchainSource(),        # 链上预言机
            WebScrapingSource(),        # 网页抓取
            HistoricalSource(),        # 历史缓存
            BaseSource(),              # Base 链
            DexScreenerSource(),       # DexScreener 多链
        ]
        
        self.sources.sort(key=lambda x: x.priority)
        self.quality_stats = defaultdict(lambda: {"attempts": 0, "success": 0})
        
        log_info("多源数据管理器初始化完成")
    
    def get_price(self, symbol: str) -> Tuple[Optional[Dict], Dict]:
        """获取价格（尝试所有真实数据源）"""
        results = []
        meta = {
            "attempts": 0,
            "sources_tried": [],
            "final_source": None,
            "success": False
        }
        
        for source in self.sources:
            meta["attempts"] += 1
            meta["sources_tried"].append(source.name)
            
            try:
                data = source.fetch_price(symbol)
                
                if data:
                    is_valid, msg = source.validate_data(data)
                    
                    if is_valid:
                        data["source_priority"] = source.priority
                        results.append(data)
                        
                        if meta["final_source"] is None:
                            meta["final_source"] = source.name
                            meta["success"] = True
            except Exception as e:
                log_debug(f"{source.name} 失败: {e}")
        
        if not results:
            meta["error"] = "所有数据源均失败"
            log_error(f"获取 {symbol} 价格失败 | 尝试了 {meta['attempts']} 个数据源")
            return None, meta
        
        best = results[0]
        self.quality_stats[symbol]["success"] += 1
        
        if len(results) > 1:
            prices = [r["price"] for r in results]
            avg_price = sum(prices) / len(prices)
            max_diff = max(abs(p - avg_price) / avg_price for p in prices)
            
            meta["cross_validation"] = {
                "sources_found": len(results),
                "prices": prices,
                "max_diff_percent": max_diff * 100,
                "is_consistent": max_diff < 0.05
            }
        
        return best, meta
    
    def get_price_with_fallback(self, symbol: str) -> Dict:
        """获取价格，包含详细状态"""
        result, meta = self.get_price(symbol)
        
        if result:
            return {
                "success": True,
                "data": result,
                "meta": meta
            }
        else:
            return {
                "success": False,
                "error": meta.get("error", "未知错误"),
                "attempts": meta["attempts"],
                "sources_tried": meta["sources_tried"],
                "suggestion": "请检查网络连接"
            }

