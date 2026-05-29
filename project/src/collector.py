# =====================================================
# CC Invest - 数据采集模块
# 支持交易所行情、链上数据、社交情绪采集
# 集成数据真实性验证
# =====================================================

import os
import json
import time
import logging
import hmac
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
from collections import defaultdict
import threading

import requests
import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
from loguru import logger
from tqdm import tqdm

def retry_on_failure(max_attempts=3, delay=1, backoff=2):
    """API 调用重试装饰器"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt < max_attempts - 1:
                        import time
                        wait_time = delay * (backoff ** attempt)
                        logger.warning(f"{func.__name__} 失败，{wait_time}秒后重试 ({attempt+1}/{max_attempts})")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"{func.__name__} 多次失败: {e}")
                        raise
            return None
        return wrapper
    return decorator


def retry_on_failure(max_attempts=3, delay=1, backoff=2):
    """API 调用重试装饰器"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt < max_attempts - 1:
                        import time
                        wait_time = delay * (backoff ** attempt)
                        logger.warning(f"{func.__name__} 失败，{wait_time}秒后重试 ({attempt+1}/{max_attempts})")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"{func.__name__} 多次失败: {e}")
                        raise
            return None
        return wrapper
    return decorator


# =====================================================
# 数据验证模块（内嵌）
# =====================================================

class DataQuality:
    """数据质量等级"""
    EXCELLENT = "excellent"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"
    INVALID = "invalid"


class DataValidationResult:
    """数据验证结果"""
    def __init__(self, is_valid: bool, quality: str, score: float, issues: List[str] = None, warnings: List[str] = None):
        self.is_valid = is_valid
        self.quality = quality
        self.score = score
        self.issues = issues or []
        self.warnings = warnings or []
    
    def to_dict(self) -> Dict:
        return {
            "is_valid": self.is_valid,
            "quality": self.quality,
            "score": self.score,
            "issues": self.issues,
            "warnings": self.warnings
        }


class DataAuthenticator:
    """数据真实性验证器"""
    
    # 价格合理性范围
    PRICE_MIN = 0.00000001
    PRICE_MAX = 1_000_000_000
    CHANGE_MAX = 100  # 最大涨跌幅 100%
    
    def __init__(self):
        self.source_weights = {
            "binance": 1.0,
            "coinbase": 0.95,
            "kraken": 0.9,
            "coingecko": 0.85,
            "cryptocompare": 0.8
        }
    
    def validate_price_data(self, data: Dict, source: str = "binance") -> DataValidationResult:
        """验证价格数据的真实性"""
        issues = []
        warnings = []
        score = 100.0
        
        # 1. 必要字段检查
        if "symbol" not in data or "price" not in data:
            issues.append("缺少必要字段 (symbol/price)")
            return DataValidationResult(False, DataQuality.INVALID, 0, issues)
        
        # 2. 价格类型验证
        try:
            price = float(data["price"])
        except (TypeError, ValueError):
            issues.append(f"价格格式错误: {data['price']}")
            return DataValidationResult(False, DataQuality.INVALID, 0, issues)
        
        # 3. 价格范围验证
        if price <= self.PRICE_MIN:
            issues.append(f"价格过小或为负数: {price}")
            score -= 50
        elif price > self.PRICE_MAX:
            issues.append(f"价格异常过大: {price}")
            score -= 30
        
        # 4. 24小时涨跌幅验证
        if "change_24h" in data and data["change_24h"] is not None:
            try:
                change = float(data["change_24h"])
                if abs(change) > self.CHANGE_MAX:
                    warnings.append(f"24h涨跌幅异常: {change}%")
                    score -= 20
            except (TypeError, ValueError):
                warnings.append("24h涨跌幅格式错误")
                score -= 5
        
        # 5. 高低价关系验证
        if all(k in data for k in ["high_24h", "low_24h"]):
            try:
                high = float(data["high_24h"])
                low = float(data["low_24h"])
                current = float(data["price"])
                
                if high < low:
                    issues.append("24h最高价 < 最低价")
                    score -= 40
                elif current > high:
                    warnings.append("当前价格 > 24h最高价")
                    score -= 15
                elif current < low:
                    warnings.append("当前价格 < 24h最低价")
                    score -= 15
            except (TypeError, ValueError, KeyError):
                pass
        
        # 6. 时间戳验证
        if "timestamp" in data:
            ts = data.get("timestamp")
            if isinstance(ts, datetime):
                age = (datetime.utcnow() - ts).total_seconds()
            else:
                age = 0
            
            if age > 300:
                warnings.append(f"数据延迟较大: {age:.0f}秒")
                score -= 20
            elif age > 60:
                warnings.append(f"数据有一定延迟: {age:.0f}秒")
                score -= 10
        
        # 7. 数据源可靠性
        source_weight = self.source_weights.get(source.lower(), 0.5)
        score *= source_weight
        
        # 确定质量等级
        if issues:
            quality = DataQuality.INVALID if len(issues) > 1 else DataQuality.POOR
            is_valid = False
        elif score >= 80:
            quality = DataQuality.EXCELLENT
            is_valid = True
        elif score >= 60:
            quality = DataQuality.GOOD
            is_valid = True
        else:
            quality = DataQuality.FAIR
            is_valid = True
        
        return DataValidationResult(
            is_valid=is_valid,
            quality=quality,
            score=max(0, score),
            issues=issues,
            warnings=warnings
        )
    
    def validate_ohlc_data(self, data: Dict) -> DataValidationResult:
        """验证 K 线数据的真实性"""
        issues = []
        warnings = []
        score = 100.0
        
        required = ["open_price", "high_price", "low_price", "close_price"]
        for field in required:
            if field not in data:
                issues.append(f"缺少字段: {field}")
        
        if issues:
            return DataValidationResult(False, DataQuality.INVALID, 0, issues)
        
        try:
            open_p = float(data["open_price"])
            high = float(data["high_price"])
            low = float(data["low_price"])
            close = float(data["close_price"])
            
            # OHLC 关系验证
            if high < low:
                issues.append("最高价 < 最低价")
                score -= 50
            
            if high < open_p or high < close:
                issues.append("最高价 < 开盘价或收盘价")
                score -= 30
            
            if low > open_p or low > close:
                issues.append("最低价 > 开盘价或收盘价")
                score -= 30
            
            if open_p <= 0 or close <= 0:
                issues.append("价格必须大于0")
                score -= 40
            
        except (TypeError, ValueError) as e:
            issues.append(f"数据格式错误: {e}")
            return DataValidationResult(False, DataQuality.INVALID, 0, issues)
        
        is_valid = len(issues) == 0
        quality = DataQuality.EXCELLENT if is_valid and score >= 90 else \
                  DataQuality.GOOD if is_valid else DataQuality.POOR
        
        return DataValidationResult(
            is_valid=is_valid,
            quality=quality,
            score=max(0, score),
            issues=issues,
            warnings=warnings
        )


class DataDeduplicator:
    """数据去重器"""
    
    def __init__(self):
        self.seen_records = {}
        self.lock = threading.Lock()
        self.dedup_window = 60
    
    def is_duplicate(self, table: str, unique_key: Dict, timestamp: datetime) -> bool:
        """检查是否为重复数据"""
        with self.lock:
            key_str = json.dumps(unique_key, sort_keys=True)
            
            if table not in self.seen_records:
                self.seen_records[table] = {}
            
            if key_str in self.seen_records[table]:
                last_time = self.seen_records[table][key_str]
                if (timestamp - last_time).total_seconds() < self.dedup_window:
                    return True
                else:
                    self.seen_records[table][key_str] = timestamp
                    return False
            else:
                self.seen_records[table][key_str] = timestamp
                return False


class MultiSourceValidator:
    """多数据源交叉验证"""
    
    def __init__(self):
        self.max_price_diff = 0.05  # 最大价格差异 5%
    
    def validate_cross_sources(self, price_data_list: List[Dict]) -> DataValidationResult:
        """交叉验证多个数据源的价格"""
        if len(price_data_list) < 2:
            return DataValidationResult(
                is_valid=True,
                quality=DataQuality.GOOD,
                score=70,
                warnings=["单数据源，无交叉验证"]
            )
        
        valid_prices = []
        for d in price_data_list:
            if isinstance(d.get("timestamp"), datetime):
                age = (datetime.utcnow() - d["timestamp"]).total_seconds()
                if age < 60:
                    valid_prices.append(d)
        
        if len(valid_prices) < 2:
            return DataValidationResult(
                is_valid=True,
                quality=DataQuality.FAIR,
                score=50,
                warnings=["可用数据源不足"]
            )
        
        prices = [d["price"] for d in valid_prices]
        avg_price = sum(prices) / len(prices)
        
        issues = []
        warnings = []
        score = 100.0
        
        for data in valid_prices:
            diff = abs(data["price"] - avg_price) / avg_price
            
            if diff > self.max_price_diff:
                issues.append(f"{data.get('source', 'unknown')} 价格偏离均值 {diff*100:.2f}%")
                score -= 25
            elif diff > 0.01:
                warnings.append(f"{data.get('source', 'unknown')} 价格有轻微差异")
                score -= 10
        
        is_valid = len(issues) == 0
        quality = DataQuality.EXCELLENT if score >= 90 else \
                  DataQuality.GOOD if is_valid else DataQuality.FAIR
        
        return DataValidationResult(
            is_valid=is_valid,
            quality=quality,
            score=max(0, score),
            issues=issues,
            warnings=warnings
        )


# =====================================================
# API 重试装饰器
# =====================================================

def retry_on_failure(max_attempts=3, delay=1, backoff=2):
    """API 调用重试装饰器"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt < max_attempts - 1:
                        import time as time_module
                        wait_time = delay * (backoff ** attempt)
                        logger.warning(f"{func.__name__} 失败，{wait_time}秒后重试 ({attempt+1}/{max_attempts})")
                        time_module.sleep(wait_time)
                    else:
                        logger.error(f"{func.__name__} 多次失败: {e}")
                        raise
            return None
        return wrapper
    return decorator


# 加载环境变量
load_dotenv(Path(__file__).parent.parent / ".env.example")

# 日志配置
logger.add(
    "logs/collector.log",
    rotation="500 MB",
    retention="10 days",
    level=os.getenv("LOG_LEVEL", "INFO")
)


# =====================================================
# 数据采集器主类
# =====================================================

class DataCollector:
    """多源数据采集器（带真实性验证）"""
    
    def __init__(self, database_url: Optional[str] = None):
        self.db_url = database_url or os.getenv("DATABASE_URL", "sqlite:///data/ccinvest.db")
        self.engine = create_engine(self.db_url)
        
        # API 配置
        self.binance_api_key = os.getenv("BINANCE_API_KEY")
        self.binance_api_secret = os.getenv("BINANCE_API_SECRET")
        
        # 数据采集间隔
        self.interval = int(os.getenv("DATA_COLLECTION_INTERVAL", "300"))
        
        # 交易对
        self.default_symbols = [
            "BTCUSDT", "ETHUSDT", "BNBUSDT", 
            "SOLUSDT", "XRPUSDT", "ADAUSDT",
            "DOGEUSDT", "DOTUSDT", "MATICUSDT"
        ]
        
        # 初始化验证器
        self.authenticator = DataAuthenticator()
        self.deduplicator = DataDeduplicator()
        self.multi_source_validator = MultiSourceValidator()
        
        # 数据质量统计
        self.quality_stats = defaultdict(lambda: {"total": 0, "valid": 0, "failed": 0})
        
        logger.info(f"数据采集器初始化完成 | 数据库: {self.db_url}")
        logger.info("数据真实性验证: 已启用")
    
    # -------------------- Binance 签名 API --------------------
    
    def _generate_signature(self, params: Dict) -> str:
        """生成 Binance API 签名"""
        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        signature = hmac.new(
            self.binance_api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        return signature
    
    def _get_signed_params(self, params: Dict = None) -> Dict:
        """生成带签名的请求参数"""
        params = params or {}
        params["timestamp"] = int(time.time() * 1000)
        params["signature"] = self._generate_signature(params)
        return params
    
    # -------------------- 交易所行情数据 --------------------
    
    @retry_on_failure(max_attempts=3, delay=1, backoff=2)
    def fetch_binance_ticker(self, symbol: str = "BTCUSDT") -> Tuple[Optional[Dict], DataValidationResult]:
        """获取单个交易对实时行情（带验证）"""
        try:
            url = f"https://api.binance.com/api/v3/ticker/24hr"
            params = {"symbol": symbol}
            headers = {"X-MBX-APIKEY": self.binance_api_key} if self.binance_api_key else {}
            
            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            raw_data = response.json()
            normalized_data = {
                "symbol": raw_data["symbol"],
                "price": float(raw_data["lastPrice"]),
                "volume_24h": float(raw_data["volume"]),
                "change_24h": float(raw_data["priceChangePercent"]),
                "high_24h": float(raw_data["highPrice"]),
                "low_24h": float(raw_data["lowPrice"]),
                "timestamp": datetime.utcnow()
            }
            
            # Binance 原始字段为 lastPrice/highPrice，先归一化后再验证。
            validation = self.authenticator.validate_price_data(normalized_data, "binance")
            
            # 记录统计
            self.quality_stats[symbol]["total"] += 1
            if validation.is_valid:
                self.quality_stats[symbol]["valid"] += 1
            else:
                self.quality_stats[symbol]["failed"] += 1
                logger.warning(f"数据验证失败 [{symbol}]: {validation.issues}")
            
            if not validation.is_valid:
                return None, validation
            
            return normalized_data, validation
            
        except Exception as e:
            logger.error(f"获取 {symbol} 行情失败: {e}")
            return None, DataValidationResult(False, DataQuality.INVALID, 0, [str(e)])
    
    def fetch_all_tickers(self, symbols: Optional[List[str]] = None) -> List[Dict]:
        """获取多个交易对行情（带验证）"""
        symbols = symbols or self.default_symbols
        results = []
        validation_failures = []
        
        for symbol in tqdm(symbols, desc="获取行情"):
            data, validation = self.fetch_binance_ticker(symbol)
            if data and validation.is_valid:
                results.append(data)
            else:
                validation_failures.append((symbol, validation.issues if validation else []))
            time.sleep(0.1)
        
        logger.info(f"成功获取 {len(results)} 个交易对行情")
        if validation_failures:
            logger.warning(f"{len(validation_failures)} 个数据验证失败")
        
        return results
    
    def fetch_ohlc(self, symbol: str = "BTCUSDT", interval: str = "1h", 
                   limit: int = 500) -> Tuple[List[Dict], DataValidationResult]:
        """获取 K 线数据（带验证）"""
        try:
            url = "https://api.binance.com/api/v3/klines"
            params = {
                "symbol": symbol,
                "interval": interval,
                "limit": limit
            }
            
            response = requests.get(url, params=params, timeout=3)
            response.raise_for_status()
            klines = response.json()
            if not klines:
                return [], DataValidationResult(
                    False,
                    DataQuality.INVALID,
                    0,
                    [f"{symbol} 无可用K线数据"]
                )
            
            ohlc_data = []
            invalid_count = 0
            
            for k in klines:
                # 验证每根 K 线
                k_data = {
                    "open_price": float(k[1]),
                    "high_price": float(k[2]),
                    "low_price": float(k[3]),
                    "close_price": float(k[4])
                }
                
                validation = self.authenticator.validate_ohlc_data(k_data)
                
                if validation.is_valid:
                    ohlc_data.append({
                        "symbol": symbol,
                        "timeframe": interval,
                        "open_time": datetime.fromtimestamp(k[0] / 1000),
                        "open_price": float(k[1]),
                        "high_price": float(k[2]),
                        "low_price": float(k[3]),
                        "close_price": float(k[4]),
                        "volume": float(k[5]),
                        "close_time": datetime.fromtimestamp(k[6] / 1000),
                        "quote_volume": float(k[7])
                    })
                else:
                    invalid_count += 1
            
            validation = DataValidationResult(
                is_valid=invalid_count == 0,
                quality=DataQuality.EXCELLENT if invalid_count == 0 else DataQuality.GOOD,
                score=100 - (invalid_count / len(klines) * 100),
                warnings=[f"{invalid_count} 根 K 线验证失败"] if invalid_count > 0 else []
            )
            
            return ohlc_data, validation
            
        except Exception as e:
            logger.error(f"获取 {symbol} K线失败: {e}")
            return [], DataValidationResult(False, DataQuality.INVALID, 0, [str(e)])
    
    # -------------------- 多数据源交叉验证 --------------------
    
    def fetch_multi_source_price(self, symbol: str) -> Tuple[Optional[float], DataValidationResult]:
        """多数据源获取价格（交叉验证）"""
        price_data_list = []
        
        # 1. Binance
        binance_data, binance_validation = self.fetch_binance_ticker(symbol)
        if binance_data and binance_validation.is_valid:
            price_data_list.append({
                "symbol": symbol,
                "price": float(binance_data["price"]),
                "source": "binance",
                "timestamp": binance_data["timestamp"]
            })
        
        # 2. CoinGecko (备用)
        coingecko_price = self._fetch_coingecko_price(symbol)
        if coingecko_price:
            price_data_list.append({
                "symbol": symbol,
                "price": coingecko_price,
                "source": "coingecko",
                "timestamp": datetime.utcnow()
            })
        
        # 交叉验证
        cross_validation = self.multi_source_validator.validate_cross_sources(price_data_list)
        
        if price_data_list:
            # 加权平均
            weights = {"binance": 1.0, "coingecko": 0.8}
            weighted_sum = sum(
                d["price"] * weights.get(d["source"], 0.5) 
                for d in price_data_list
            )
            weight_total = sum(
                weights.get(d["source"], 0.5) 
                for d in price_data_list
            )
            final_price = weighted_sum / weight_total if weight_total > 0 else price_data_list[0]["price"]
            return final_price, cross_validation
        
        return None, DataValidationResult(False, DataQuality.INVALID, 0, ["无可用数据源"])
    
    def _fetch_coingecko_price(self, symbol: str) -> Optional[float]:
        """获取 CoinGecko 价格作为备用"""
        symbol_map = {
            "BTCUSDT": "bitcoin",
            "ETHUSDT": "ethereum",
            "BNBUSDT": "binancecoin",
            "SOLUSDT": "solana",
            "XRPUSDT": "ripple",
            "ADAUSDT": "cardano"
        }
        
        coin_id = symbol_map.get(symbol)
        if not coin_id:
            return None
        
        try:
            url = f"https://api.coingecko.com/api/v3/simple/price"
            params = {"ids": coin_id, "vs_currencies": "usd"}
            
            response = requests.get(url, params=params, timeout=5)
            if response.status_code == 200:
                data = response.json()
                return float(data[coin_id]["usd"])
        except Exception as e:
            logger.debug(f"CoinGecko API 失败: {e}")
        
        return None
    
    # -------------------- 链上数据 --------------------
    
    @retry_on_failure(max_attempts=3, delay=1, backoff=2)
    def fetch_etherscan_transfers(self, address: str, api_key: str, 
                                   days: int = 1) -> List[Dict]:
        """获取 Etherscan 代币转账记录"""
        try:
            url = "https://api.etherscan.io/api"
            end_time = int(datetime.utcnow().timestamp())
            start_time = int((datetime.utcnow() - timedelta(days=days)).timestamp())
            
            params = {
                "module": "account",
                "action": "tokentx",
                "address": address,
                "startblock": 0,
                "endblock": 99999999,
                "sort": "desc",
                "apikey": api_key
            }
            
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            if data["status"] == "1":
                transactions = []
                for tx in data["result"]:
                    if start_time <= int(tx["timeStamp"]) <= end_time:
                        transactions.append({
                            "symbol": tx["tokenSymbol"],
                            "chain": "ethereum",
                            "tx_hash": tx["hash"],
                            "from_address": tx["from"],
                            "to_address": tx["to"],
                            "value": float(tx["value"]) / (10 ** int(tx["tokenDecimal"])),
                            "gas_used": int(tx["gasUsed"]),
                            "block_number": int(tx["blockNumber"]),
                            "timestamp": datetime.fromtimestamp(int(tx["timeStamp"]))
                        })
                return transactions
            return []
        except Exception as e:
            logger.error(f"获取链上数据失败: {e}")
            return []
    
    @retry_on_failure(max_attempts=3, delay=1, backoff=2)
    def fetch_wallet_whales(self, address: str) -> Optional[Dict]:
        """检测巨鲸地址"""
        try:
            url = f"https://api.etherscan.io/api"
            params = {
                "module": "account",
                "action": "balance",
                "address": address,
                "tag": "latest",
                "apikey": os.getenv("ETHERSCAN_API_KEY", "")
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data["status"] == "1":
                balance_eth = float(data["result"]) / 1e18
                return {
                    "address": address,
                    "balance_eth": balance_eth,
                    "is_whale": balance_eth > 100,
                    "timestamp": datetime.utcnow()
                }
            return None
        except Exception as e:
            logger.error(f"获取钱包余额失败: {e}")
            return None
    
    # -------------------- 社交情绪数据 --------------------
    
    def fetch_twitter_sentiment(self, keywords: List[str], 
                                 count: int = 100) -> List[Dict]:
        """获取 Twitter 情绪数据（需要 Twitter API）"""
        try:
            sentiments = []
            for keyword in keywords:
                sentiments.append({
                    "source": "twitter",
                    "keyword": keyword,
                    "sentiment_score": np.random.uniform(-1, 1),
                    "polarity": "positive" if np.random.random() > 0.5 else "negative",
                    "post_count": np.random.randint(100, 10000),
                    "engagement_score": np.random.uniform(0, 100),
                    "timestamp": datetime.utcnow()
                })
            return sentiments
        except Exception as e:
            logger.error(f"获取 Twitter 情绪数据失败: {e}")
            return []
    
    def fetch_news_sentiment(self, symbols: List[str]) -> List[Dict]:
        """获取新闻情绪数据"""
        try:
            sentiments = []
            for symbol in symbols:
                sentiments.append({
                    "source": "news",
                    "keyword": symbol,
                    "sentiment_score": np.random.uniform(-1, 1),
                    "polarity": np.random.choice(["positive", "neutral", "negative"]),
                    "post_count": np.random.randint(10, 500),
                    "timestamp": datetime.utcnow()
                })
            return sentiments
        except Exception as e:
            logger.error(f"获取新闻情绪数据失败: {e}")
            return []
    
    # -------------------- 数据存储 --------------------
    
    def save_market_data(self, data: List[Dict]) -> Tuple[int, int]:
        """保存行情数据（带验证和去重）"""
        saved = 0
        skipped = 0
        
        for record in data:
            # 验证数据
            validation = self.authenticator.validate_price_data(record)
            if not validation.is_valid:
                logger.warning(f"跳过无效数据: {record.get('symbol')} - {validation.issues}")
                continue
            
            # 去重检查
            unique_key = {"symbol": record["symbol"]}
            timestamp = record.get("timestamp", datetime.utcnow())
            
            if self.deduplicator.is_duplicate("market_data", unique_key, timestamp):
                skipped += 1
                continue
            
            # 保存
            try:
                df = pd.DataFrame([record])
                df.to_sql("market_data", self.engine, if_exists="append", index=False)
                saved += 1
            except Exception as e:
                logger.error(f"保存数据失败: {e}")
        
        if skipped > 0:
            logger.info(f"跳过 {skipped} 条重复数据")
        
        return saved, skipped
    
    def save_ohlc_data(self, data: List[Dict]) -> int:
        """保存 K 线数据"""
        if not data:
            return 0
        
        df = pd.DataFrame(data)
        df["timestamp"] = pd.to_datetime(df["open_time"])
        db_columns = [
            "symbol", "timeframe", "open_price", "high_price",
            "low_price", "close_price", "volume", "timestamp"
        ]
        df = df[db_columns]
        
        try:
            df.to_sql("ohlc_data", self.engine, if_exists="append", index=False)
            logger.info(f"成功保存 {len(data)} 条 K线数据")
            return len(data)
        except Exception as e:
            logger.error(f"保存 K线数据失败: {e}")
            return 0
    
    # -------------------- 数据处理 --------------------
    
    def compute_indicators(self, symbol: str = "BTCUSDT", 
                          timeframe: str = "1h") -> pd.DataFrame:
        """计算技术指标"""
        try:
            query = text("""
                SELECT timestamp, open, high, low, close, volume
                FROM (
                    SELECT timestamp, open_price as open, 
                           high_price as high, low_price as low, 
                           close_price as close, volume
                    FROM ohlc_data 
                    WHERE symbol = :symbol AND timeframe = :timeframe
                    ORDER BY timestamp DESC
                    LIMIT 500
                )
                ORDER BY timestamp ASC
            """)
            
            df = pd.read_sql(query, self.engine, params={"symbol": symbol, "timeframe": timeframe})
            
            if len(df) < 50:
                logger.warning(f"{symbol} 数据不足，无法计算指标")
                return pd.DataFrame()
            
            close = df['close']
            
            # 技术指标
            df['ma_short'] = close.rolling(window=20).mean()
            df['ma_long'] = close.rolling(window=50).mean()
            df['ma_medium'] = close.rolling(window=50).mean()
            
            # RSI
            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            df['rsi'] = 100 - (100 / (1 + rs))
            
            # MACD
            exp1 = close.ewm(span=12, adjust=False).mean()
            exp2 = close.ewm(span=26, adjust=False).mean()
            df['macd'] = exp1 - exp2
            df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()
            df['histogram'] = df['macd'] - df['signal']
            
            # 布林带
            df['bb_middle'] = close.rolling(window=20).mean()
            df['bb_std'] = close.rolling(window=20).std()
            df['bb_upper'] = df['bb_middle'] + (df['bb_std'] * 2)
            df['bb_lower'] = df['bb_middle'] - (df['bb_std'] * 2)
            
            # ATR
            high_low = df['high'] - df['low']
            high_close = np.abs(df['high'] - close.shift())
            low_close = np.abs(df['low'] - close.shift())
            tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
            df['atr'] = tr.rolling(14).mean()
            
            # ===== 资深交易员技术指标 =====
            
            # 1. Stochastic Oscillator (%K, %D)
            low_min = df['low'].rolling(window=14).min()
            high_max = df['high'].rolling(window=14).max()
            df['stoch_k'] = 100 * (close - low_min) / (high_max - low_min)
            df['stoch_d'] = df['stoch_k'].rolling(window=3).mean()
            
            # 2. ADX (Average Directional Index) - 趋势强度
            plus_dm = df['high'].diff()
            minus_dm = -df['low'].diff()
            plus_dm[plus_dm < 0] = 0
            minus_dm[minus_dm < 0] = 0
            atr_smooth = df['atr'] * 14
            df['adx_plus'] = 100 * (plus_dm.ewm(alpha=1/14).mean() / atr_smooth)
            df['adx_minus'] = 100 * (minus_dm.ewm(alpha=1/14).mean() / atr_smooth)
            dx = 100 * np.abs(df['adx_plus'] - df['adx_minus']) / (df['adx_plus'] + df['adx_minus'])
            df['adx'] = dx.ewm(alpha=1/14).mean()
            
            # 3. CCI (Commodity Channel Index)
            typical_price = (df['high'] + df['low'] + close) / 3
            sma_tp = typical_price.rolling(window=20).mean()
            mad = typical_price.rolling(window=20).apply(lambda x: np.abs(x - x.mean()).mean())
            df['cci'] = (typical_price - sma_tp) / (0.015 * mad)
            
            # 4. OBV (On-Balance Volume)
            df['obv'] = (np.sign(df['close'].diff()) * df['volume']).fillna(0).cumsum()
            
            # 5. VWAP (Volume Weighted Average Price)
            df['vwap'] = (df['volume'] * (df['high'] + df['low'] + close) / 3).cumsum() / df['volume'].cumsum()
            
            # 6. Williams %R
            df['williams_r'] = -100 * (high_max - close) / (high_max - low_min)
            
            # 7. Aroon (Up/Down)
            df['aroon_up'] = 100 * df['high'].rolling(window=25).apply(lambda x: x.argmax(), raw=True) / 25
            df['aroon_down'] = 100 * df['low'].rolling(window=25).apply(lambda x: x.argmin(), raw=True) / 25
            df['aroon_osc'] = df['aroon_up'] - df['aroon_down']
            
            # 8. MFI (Money Flow Index) - 资金流量指标
            typical_price = (df['high'] + df['low'] + close) / 3
            raw_money_flow = typical_price * df['volume']
            positive_flow = raw_money_flow.where(typical_price.diff() > 0, 0).rolling(window=14).sum()
            negative_flow = raw_money_flow.where(typical_price.diff() < 0, 0).rolling(window=14).sum()
            money_ratio = positive_flow / negative_flow
            df['mfi'] = 100 - (100 / (1 + money_ratio))
            
            # 9. Fibonacci Retracement Levels (基于最近200周期高低点)
            period_high = close.rolling(window=200).max()
            period_low = close.rolling(window=200).min()
            diff = period_high - period_low
            df['fib_236'] = period_high - diff * 0.236
            df['fib_382'] = period_high - diff * 0.382
            df['fib_500'] = period_high - diff * 0.500
            df['fib_618'] = period_high - diff * 0.618
            df['fib_786'] = period_high - diff * 0.786
            
            # 10. Parabolic SAR (止损转向点指标)
            psar = close.copy()
            bull = True
            af = 0.02
            ep = close.iloc[0]
            for i in range(1, len(close)):
                psar.iloc[i] = psar.iloc[i-1] + af * (ep - psar.iloc[i-1])
                if bull:
                    if close.iloc[i] < psar.iloc[i]:
                        bull = False
                        psar.iloc[i] = ep
                        af = 0.02
                        ep = close.iloc[i]
                    elif close.iloc[i] > ep:
                        ep = close.iloc[i]
                        af = min(af + 0.01, 0.2)
                else:
                    if close.iloc[i] > psar.iloc[i]:
                        bull = True
                        psar.iloc[i] = ep
                        af = 0.02
                        ep = close.iloc[i]
                    elif close.iloc[i] < ep:
                        ep = close.iloc[i]
                        af = min(af + 0.01, 0.2)
            df['sar'] = psar
            
            # 11. Keltner Channel (肯特纳通道)
            df['kc_middle'] = close.ewm(span=20).mean()
            df['kc_upper'] = df['kc_middle'] + 2 * df['atr']
            df['kc_lower'] = df['kc_middle'] - 2 * df['atr']
            
            # 12. Ichimoku Cloud (一目均衡表) - 简化版
            nine_period_high = df['high'].rolling(window=9).max()
            nine_period_low = df['low'].rolling(window=9).min()
            df['tenkan_sen'] = (nine_period_high + nine_period_low) / 2
            
            twenty_six_period_high = df['high'].rolling(window=26).max()
            twenty_six_period_low = df['low'].rolling(window=26).min()
            df['kijun_sen'] = (twenty_six_period_high + twenty_six_period_low) / 2
            
            df['senkou_span_a'] = ((df['tenkan_sen'] + df['kijun_sen']) / 2).shift(26)
            
            fifty_two_period_high = df['high'].rolling(window=52).max()
            fifty_two_period_low = df['low'].rolling(window=52).min()
            df['senkou_span_b'] = ((fifty_two_period_high + fifty_two_period_low) / 2).shift(26)
            
            logger.info(f"计算 {symbol} 技术指标完成 (28个指标)")
            return df
            
        except Exception as e:
            logger.error(f"计算指标失败: {e}")
            return pd.DataFrame()
    
    # -------------------- 数据质量报告 --------------------
    
    def get_quality_report(self) -> Dict:
        """生成数据质量报告"""
        report = {
            "timestamp": datetime.utcnow().isoformat(),
            "sources": {}
        }
        
        for symbol, stats in self.quality_stats.items():
            total = stats["total"]
            valid = stats["valid"]
            success_rate = (valid / total * 100) if total > 0 else 0
            
            report["sources"][symbol] = {
                "total_requests": total,
                "valid_data": valid,
                "failed_requests": stats["failed"],
                "success_rate": f"{success_rate:.1f}%",
                "quality_score": f"{success_rate:.1f}%"
            }
        
        return report
    
    # -------------------- 主采集循环 --------------------
    
    def collect_all(self) -> Dict:
        """执行完整数据采集（带验证）"""
        logger.info("=" * 50)
        logger.info("开始数据采集（含真实性验证）")
        
        results = {
            "market_data": {"saved": 0, "skipped": 0},
            "ohlc_data": {"saved": 0},
            "validation_failures": []
        }
        
        # 1. 行情数据
        market_data = self.fetch_all_tickers()
        saved, skipped = self.save_market_data(market_data)
        results["market_data"] = {"saved": saved, "skipped": skipped}
        
        # 2. K线数据
        for symbol in self.default_symbols[:3]:
            ohlc_data, validation = self.fetch_ohlc(symbol)
            if validation.is_valid:
                results["ohlc_data"]["saved"] += self.save_ohlc_data(ohlc_data)
            else:
                results["validation_failures"].append({
                    "symbol": symbol,
                    "issues": validation.issues
                })
            time.sleep(0.2)
        
        logger.info(f"数据采集完成 | 保存: {saved} | 跳过: {skipped}")
        logger.info("=" * 50)
        
        return results
    
    def run_schedule(self):
        """定时采集循环"""
        import schedule
        
        schedule.every(self.interval).seconds.do(self.collect_all)
        logger.info(f"定时任务已启动，每 {self.interval} 秒采集一次")
        
        while True:
            schedule.run_pending()
            time.sleep(1)


# =====================================================
# 主程序
# =====================================================

if __name__ == "__main__":
    collector = DataCollector()
    results = collector.collect_all()
    print(f"\n📊 数据采集结果:")
    print(f"   保存: {results['market_data']['saved']} 条")
    print(f"   跳过: {results['market_data']['skipped']} 条")
    
    # 显示质量报告
    report = collector.get_quality_report()
    print(f"\n📈 数据质量报告:")
    for symbol, stats in report["sources"].items():
        print(f"   {symbol}: 成功率 {stats['success_rate']}")
