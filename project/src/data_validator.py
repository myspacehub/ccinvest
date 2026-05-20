# =====================================================
# CC Invest - 数据真实性保障模块
# 确保数据获取的真实性、完整性和可靠性
# =====================================================

import os
import json
import time
import hmac
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict
import threading

import requests
import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text, and_, or_
from dotenv import load_dotenv
from loguru import logger

load_dotenv()


class DataSource(Enum):
    """数据源枚举"""
    BINANCE = "binance"
    COINGECKO = "coingecko"
    CRYPTOCOMPARE = "cryptocompare"
    ETHERSCAN = "etherscan"
    CUSTOM = "custom"


class DataQuality(Enum):
    """数据质量等级"""
    EXCELLENT = "excellent"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"
    INVALID = "invalid"


@dataclass
class DataValidationResult:
    """数据验证结果"""
    is_valid: bool
    quality: DataQuality
    score: float  # 0-100
    issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            "is_valid": self.is_valid,
            "quality": self.quality.value,
            "score": self.score,
            "issues": self.issues,
            "warnings": self.warnings
        }


@dataclass
class PriceData:
    """价格数据结构"""
    symbol: str
    price: float
    source: str
    timestamp: datetime
    volume_24h: Optional[float] = None
    change_24h: Optional[float] = None
    high_24h: Optional[float] = None
    low_24h: Optional[float] = None
    
    def is_fresh(self, max_age_seconds: int = 60) -> bool:
        """检查数据是否新鲜"""
        age = (datetime.utcnow() - self.timestamp).total_seconds()
        return age < max_age_seconds
    
    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "price": self.price,
            "source": self.source,
            "timestamp": self.timestamp.isoformat(),
            "age_seconds": (datetime.utcnow() - self.timestamp).total_seconds()
        }


class DataAuthenticator:
    """数据真实性验证器"""
    
    # 价格合理性范围
    PRICE_MIN = 0.00000001  # 最小价格
    PRICE_MAX = 1_000_000_000  # 最大价格（防止异常）
    
    # 24小时涨跌幅限制
    CHANGE_MAX = 100  # 最大涨跌幅 100%
    
    # 交易量最小值
    VOLUME_MIN = 0
    
    def __init__(self):
        # 数据源可靠性评分
        self.source_weights = {
            "binance": 1.0,
            "coinbase": 0.95,
            "kraken": 0.9,
            "coingecko": 0.85,
            "cryptocompare": 0.8,
            "etherscan": 0.7
        }
    
    def validate_price_data(self, data: Dict, source: str = "binance") -> DataValidationResult:
        """验证价格数据的真实性"""
        issues = []
        warnings = []
        score = 100.0
        
        # 1. 检查必要字段
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
        
        # 5. 交易量验证
        if "volume_24h" in data and data["volume_24h"] is not None:
            try:
                volume = float(data["volume_24h"])
                if volume < self.VOLUME_MIN:
                    warnings.append("交易量为负数")
                    score -= 10
            except (TypeError, ValueError):
                warnings.append("交易量格式错误")
                score -= 5
        
        # 6. 高低价关系验证
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
        
        # 7. 时间戳验证
        if "timestamp" in data:
            ts = data.get("timestamp")
            if isinstance(ts, datetime):
                age = (datetime.utcnow() - ts).total_seconds()
            elif isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    age = (datetime.utcnow() - ts).total_seconds()
                except:
                    age = 0
            else:
                age = 0
            
            if age > 300:  # 5分钟以上
                warnings.append(f"数据延迟较大: {age:.0f}秒")
                score -= 20
            elif age > 60:  # 1分钟以上
                warnings.append(f"数据有一定延迟: {age:.0f}秒")
                score -= 10
        
        # 8. 数据源可靠性评分
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
        elif score >= 40:
            quality = DataQuality.FAIR
            is_valid = True
        else:
            quality = DataQuality.POOR
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
            volume = float(data.get("volume", 0))
            
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
            
            # 交易量验证
            if volume < 0:
                issues.append("交易量为负数")
                score -= 20
            
            # 价格合理性
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
        self.seen_records = {}  # {table: {unique_key: timestamp}}
        self.lock = threading.Lock()
        self.dedup_window = 60  # 去重时间窗口（秒）
    
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
                    # 超出时间窗口，更新记录
                    self.seen_records[table][key_str] = timestamp
                    return False
            else:
                self.seen_records[table][key_str] = timestamp
                return False
    
    def cleanup(self, max_age_seconds: int = 3600):
        """清理过期记录"""
        with self.lock:
            now = datetime.utcnow()
            for table in self.seen_records:
                to_remove = []
                for key, timestamp in self.seen_records[table].items():
                    if (now - timestamp).total_seconds() > max_age_seconds:
                        to_remove.append(key)
                for key in to_remove:
                    del self.seen_records[table][key]


class MultiSourceValidator:
    """多数据源交叉验证器"""
    
    def __init__(self):
        self.price_tolerance = 0.01  # 价格差异容忍度 1%
        self.max_price_diff = 0.05  # 最大价格差异 5%
    
    def validate_cross_sources(self, price_data_list: List[PriceData]) -> DataValidationResult:
        """交叉验证多个数据源的价格"""
        if len(price_data_list) < 2:
            return DataValidationResult(
                is_valid=True,
                quality=DataQuality.GOOD,
                score=70,
                warnings=["单数据源，无交叉验证"]
            )
        
        # 过滤有效数据
        valid_prices = [d for d in price_data_list if d.is_fresh()]
        if len(valid_prices) < 2:
            return DataValidationResult(
                is_valid=True,
                quality=DataQuality.FAIR,
                score=50,
                warnings=["可用数据源不足"]
            )
        
        prices = [d.price for d in valid_prices]
        avg_price = sum(prices) / len(prices)
        
        issues = []
        warnings = []
        score = 100.0
        
        # 检查价格差异
        for data in valid_prices:
            diff = abs(data.price - avg_price) / avg_price
            
            if diff > self.max_price_diff:
                issues.append(
                    f"{data.source} 价格偏离均值 {diff*100:.2f}%: ${data.price}"
                )
                score -= 25
            elif diff > self.price_tolerance:
                warnings.append(
                    f"{data.source} 价格有轻微差异: {diff*100:.2f}%"
                )
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


class BinanceSignedAPI:
    """Binance 签名 API 客户端"""
    
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://api.binance.com"
    
    def _generate_signature(self, params: Dict) -> str:
        """生成签名"""
        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        return signature
    
    def get_signed_request_params(self, params: Dict = None) -> Dict:
        """生成带签名的请求参数"""
        params = params or {}
        params["timestamp"] = int(time.time() * 1000)
        params["signature"] = self._generate_signature(params)
        return params
    
    def fetch_balance(self) -> Optional[Dict]:
        """获取账户余额（需签名）"""
        try:
            params = self.get_signed_request_params()
            headers = {"X-MBX-APIKEY": self.api_key}
            
            response = requests.get(
                f"{self.base_url}/api/v3/account",
                headers=headers,
                params=params,
                timeout=10
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"余额查询失败: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"余额查询异常: {e}")
            return None


class EnhancedDataCollector:
    """增强版数据采集器（带真实性保障）"""
    
    def __init__(self, database_url: Optional[str] = None):
        self.db_url = database_url or os.getenv("DATABASE_URL", "sqlite:///data/ccinvest.db")
        self.engine = create_engine(self.db_url)
        
        # 初始化验证器
        self.authenticator = DataAuthenticator()
        self.deduplicator = DataDeduplicator()
        self.multi_source_validator = MultiSourceValidator()
        
        # API 配置
        self.binance_api_key = os.getenv("BINANCE_API_KEY")
        self.binance_api_secret = os.getenv("BINANCE_API_SECRET")
        self.binance_signed = None
        
        if self.binance_api_key and self.binance_api_secret:
            self.binance_signed = BinanceSignedAPI(
                self.binance_api_key,
                self.binance_api_secret
            )
        
        # 交易对
        self.default_symbols = [
            "BTCUSDT", "ETHUSDT", "BNBUSDT",
            "SOLUSDT", "XRPUSDT", "ADAUSDT"
        ]
        
        # 数据质量统计
        self.quality_stats = defaultdict(lambda: {"total": 0, "valid": 0, "failed": 0})
        
        logger.info("增强版数据采集器初始化完成")
    
    def fetch_binance_ticker_validated(self, symbol: str = "BTCUSDT") -> Tuple[Optional[Dict], DataValidationResult]:
        """获取并验证 Binance 行情数据"""
        try:
            url = f"https://api.binance.com/api/v3/ticker/24hr"
            params = {"symbol": symbol}
            headers = {"X-MBX-APIKEY": self.binance_api_key or ""}
            
            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            raw_data = response.json()
            
            # 验证数据真实性
            validation = self.authenticator.validate_price_data(raw_data, "binance")
            
            # 记录统计
            self.quality_stats[symbol]["total"] += 1
            if validation.is_valid:
                self.quality_stats[symbol]["valid"] += 1
            else:
                self.quality_stats[symbol]["failed"] += 1
                logger.warning(f"数据验证失败 [{symbol}]: {validation.issues}")
            
            if not validation.is_valid:
                return None, validation
            
            return raw_data, validation
            
        except requests.exceptions.RequestException as e:
            logger.error(f"API 请求失败 [{symbol}]: {e}")
            return None, DataValidationResult(False, DataQuality.INVALID, 0, [str(e)])
    
    def fetch_multi_source_price(self, symbol: str) -> Tuple[Optional[float], DataValidationResult]:
        """多数据源获取价格"""
        price_data_list = []
        
        # 1. Binance
        binance_data, binance_validation = self.fetch_binance_ticker_validated(symbol)
        if binance_data and binance_validation.is_valid:
            price_data_list.append(PriceData(
                symbol=symbol,
                price=float(binance_data["lastPrice"]),
                source="binance",
                timestamp=datetime.utcnow()
            ))
        
        # 2. CoinGecko (备用数据源)
        coingecko_price = self._fetch_coingecko_price(symbol)
        if coingecko_price:
            price_data_list.append(PriceData(
                symbol=symbol,
                price=coingecko_price,
                source="coingecko",
                timestamp=datetime.utcnow()
            ))
        
        # 交叉验证
        if len(price_data_list) >= 2:
            cross_validation = self.multi_source_validator.validate_cross_sources(price_data_list)
            
            # 使用平均值或加权平均
            weights = {"binance": 1.0, "coingecko": 0.8}
            weighted_sum = sum(
                d.price * weights.get(d.source, 0.5) 
                for d in price_data_list
            )
            weight_total = sum(
                weights.get(d.source, 0.5) 
                for d in price_data_list
            )
            final_price = weighted_sum / weight_total if weight_total > 0 else price_data_list[0].price
            
            return final_price, cross_validation
        elif price_data_list:
            return price_data_list[0].price, price_data_list[0]
        
        return None, DataValidationResult(False, DataQuality.INVALID, 0, ["无可用数据源"])
    
    def _fetch_coingecko_price(self, symbol: str) -> Optional[float]:
        """获取 CoinGecko 价格作为备用"""
        # 将交易对转换为 CoinGecko ID
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
            params = {
                "ids": coin_id,
                "vs_currencies": "usd"
            }
            
            response = requests.get(url, params=params, timeout=5)
            if response.status_code == 200:
                data = response.json()
                return float(data[coin_id]["usd"])
        except Exception as e:
            logger.warning(f"CoinGecko API 失败: {e}")
        
        return None
    
    def save_market_data_with_validation(self, data: List[Dict]) -> Tuple[int, int]:
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
            unique_key = {
                "symbol": record["symbol"],
                "timestamp": str(record.get("timestamp"))
            }
            timestamp = record.get("timestamp", datetime.utcnow())
            if isinstance(timestamp, str):
                timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            
            if self.deduplicator.is_duplicate("market_data", unique_key, timestamp):
                skipped += 1
                continue
            
            # 保存到数据库
            try:
                df = pd.DataFrame([record])
                df.to_sql("market_data", self.engine, if_exists="append", index=False)
                saved += 1
            except Exception as e:
                logger.error(f"保存数据失败: {e}")
        
        return saved, skipped
    
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
                "success_rate": f"{success_rate:.2f}%",
                "quality_score": f"{success_rate:.2f}%"
            }
        
        return report
    
    def cleanup_old_data(self, days: int = 30):
        """清理过期数据"""
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            
            with self.engine.connect() as conn:
                for table in ["market_data", "ohlc_data", "chain_data"]:
                    try:
                        conn.execute(text(f"""
                            DELETE FROM {table}
                            WHERE timestamp < :cutoff
                        """), {"cutoff": cutoff_date})
                        conn.commit()
                        logger.info(f"已清理 {table} 中 {days} 天前的数据")
                    except Exception as e:
                        logger.warning(f"清理 {table} 失败: {e}")
            
            # 清理去重记录
            self.deduplicator.cleanup()
            
        except Exception as e:
            logger.error(f"清理过期数据失败: {e}")


# =====================================================
# 主程序
# =====================================================

if __name__ == "__main__":
    collector = EnhancedDataCollector()
    
    # 测试数据验证
    print("=" * 60)
    print("数据真实性保障测试")
    print("=" * 60)
    
    # 测试有效数据
    valid_data = {
        "symbol": "BTCUSDT",
        "price": 50000.00,
        "volume_24h": 1000000,
        "change_24h": 2.5,
        "high_24h": 51000,
        "low_24h": 49000,
        "timestamp": datetime.utcnow()
    }
    
    validation = collector.authenticator.validate_price_data(valid_data)
    print(f"\n✅ 有效数据验证:")
    print(f"   有效: {validation.is_valid}")
    print(f"   质量: {validation.quality.value}")
    print(f"   分数: {validation.score}")
    
    # 测试异常数据
    invalid_data = {
        "symbol": "BTCUSDT",
        "price": -100,  # 负价格
        "volume_24h": -500,
        "timestamp": datetime.utcnow()
    }
    
    validation = collector.authenticator.validate_price_data(invalid_data)
    print(f"\n❌ 异常数据验证:")
    print(f"   有效: {validation.is_valid}")
    print(f"   问题: {validation.issues}")
    print(f"   警告: {validation.warnings}")
    
    # 测试 K 线数据
    ohlc_data = {
        "open_price": 50000,
        "high_price": 51000,
        "low_price": 49000,
        "close_price": 50500,
        "volume": 1000000
    }
    
    validation = collector.authenticator.validate_ohlc_data(ohlc_data)
    print(f"\n📊 K线数据验证:")
    print(f"   有效: {validation.is_valid}")
    print(f"   质量: {validation.quality.value}")
    
    print("\n" + "=" * 60)
    print("数据真实性保障模块测试完成！")
    print("=" * 60)