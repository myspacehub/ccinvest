import requests
# =====================================================
# CC Invest - 风控断路器模块
# 实现仓位限制、自动断路、合规审计
# =====================================================

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from decimal import Decimal
from dataclasses import dataclass, field
from enum import Enum

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from dotenv import load_dotenv
from loguru import logger

load_dotenv()


class RiskLevel(Enum):
    """风险等级"""
    SAFE = "safe"
    WARNING = "warning"
    CRITICAL = "critical"
    STOP_LOSS = "stop_loss"


class CircuitBreakerLevel(Enum):
    """断路器等级"""
    LEVEL_1_WARNING = 1  # 警告，减少仓位
    LEVEL_2_FORCE_CLOSE = 2  # 强制平仓
    LEVEL_3_STOP_TRADING = 3  # 停止交易


@dataclass
class RiskConfig:
    """风控配置"""
    max_position_size: float = 0.02  # 单笔最大仓位 2%
    max_total_position: float = 0.10  # 总持仓上限 10%
    max_daily_loss: float = 1000.0  # 单日最大亏损 USDT
    max_drawdown: float = 0.05  # 最大回撤 5%
    stop_loss_percent: float = 0.02  # 止损线 2%
    max_leverage: float = 1.0  # 最大杠杆
    max_orders_per_day: int = 50  # 单日最大订单数
    max_correlated_positions: int = 3  # 最大关联持仓数


@dataclass
class RiskMetrics:
    """风险指标"""
    total_exposure: float = 0.0  # 总敞口
    daily_pnl: float = 0.0  # 当日盈亏
    daily_loss: float = 0.0  # 当日亏损
    current_drawdown: float = 0.0  # 当前回撤
    unrealized_pnl: float = 0.0  # 未实现盈亏
    position_count: int = 0  # 持仓数量
    order_count_today: int = 0  # 当日订单数
    risk_level: RiskLevel = RiskLevel.SAFE


@dataclass
class OrderRequest:
    """订单请求"""
    symbol: str
    side: str  # BUY or SELL
    quantity: float
    price: Optional[float] = None
    order_type: str = "market"  # market, limit, stop_loss
    stop_loss_price: Optional[float] = None


@dataclass
class OrderResult:
    """订单结果"""
    approved: bool
    risk_level: RiskLevel
    message: str
    adjusted_quantity: Optional[float] = None
    adjusted_price: Optional[float] = None
    warnings: List[str] = field(default_factory=list)
    circuit_breaker_level: Optional[CircuitBreakerLevel] = None


class RiskManager:
    """风控管理器"""
    
    def __init__(self, database_url: Optional[str] = None, config: Optional[RiskConfig] = None):
        self.db_url = database_url or os.getenv("DATABASE_URL", "sqlite:///data/ccinvest.db")
        self.engine = create_engine(self.db_url)
        self.SessionLocal = sessionmaker(bind=self.engine)
        
        # 风控配置
        self.config = config or RiskConfig(
            max_position_size=float(os.getenv("MAX_POSITION_SIZE", "0.02")),
            max_total_position=float(os.getenv("MAX_TOTAL_POSITION", "0.10")),
            max_daily_loss=float(os.getenv("MAX_DAILY_LOSS", "1000.0")),
            max_drawdown=float(os.getenv("MAX_DRAWDOWN", "0.05")),
            stop_loss_percent=float(os.getenv("STOP_LOSS_PERCENT", "0.02")),
        )
        
        self.current_circuit_breaker = None
        self.last_reset_time = datetime.utcnow()
        
        logger.info(f"风控模块初始化 | 最大仓位: {self.config.max_position_size*100}%")
    
    def check_and_trigger_circuit_breaker(self, account_id: int = 1):
        """检查是否需要触发断路器"""
        metrics = self.calculate_metrics(account_id)
        
        # 检查各项风险指标并触发对应级别的断路器
        if metrics.daily_loss >= self.config.max_daily_loss * 0.5 and not self.current_circuit_breaker:
            # L1: 日亏损达 50%
            self.trigger_circuit_breaker(
                CircuitBreakerLevel.LEVEL_1_WARNING,
                f"日亏损达到 ${metrics.daily_loss:.2f}，超过限额的 50%"
            )
        elif metrics.daily_loss >= self.config.max_daily_loss * 0.8:
            # L2: 日亏损达 80%，强制平仓
            if self.current_circuit_breaker != CircuitBreakerLevel.LEVEL_2_FORCE_CLOSE:
                self.trigger_circuit_breaker(
                    CircuitBreakerLevel.LEVEL_2_FORCE_CLOSE,
                    f"日亏损达到 ${metrics.daily_loss:.2f}，超过限额的 80%，强制平仓"
                )
        elif metrics.daily_loss >= self.config.max_daily_loss:
            # L3: 日亏损达 100%，停止交易
            if self.current_circuit_breaker != CircuitBreakerLevel.LEVEL_3_STOP_TRADING:
                self.trigger_circuit_breaker(
                    CircuitBreakerLevel.LEVEL_3_STOP_TRADING,
                    f"日亏损达到 ${metrics.daily_loss:.2f}，超过限额，停止所有交易"
                )
        
        return self.current_circuit_breaker
    
    def get_session(self) -> Session:
        """获取数据库会话"""
        return self.SessionLocal()
    
    def calculate_metrics(self, account_id: int = 1) -> RiskMetrics:
        """计算当前风险指标"""
        session = self.get_session()
        metrics = RiskMetrics()
        
        try:
            # 获取账户信息
            account = session.execute(
                text("SELECT * FROM accounts WHERE id = :id"),
                {"id": account_id}
            ).fetchone()
            
            if not account:
                logger.warning("账户不存在，使用默认配置")
                return metrics
            
            # 计算总敞口
            positions = session.execute(
                text("SELECT * FROM positions WHERE account_id = :id AND status = 'open'"),
                {"id": account_id}
            ).fetchall()
            
            total_exposure = 0.0
            for pos in positions:
                exposure = float(pos.quantity) * (float(pos.current_price) if pos.current_price else float(pos.entry_price))
                total_exposure += exposure
            
            metrics.total_exposure = total_exposure
            metrics.position_count = len(positions)
            
            # 计算当日盈亏
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            daily_trades = session.execute(
                text("""
                    SELECT SUM(CASE WHEN side = 'SELL' THEN quantity * price - commission 
                                    ELSE -(quantity * price + commission) END) as pnl
                    FROM trades 
                    WHERE account_id = :id AND timestamp >= :today
                """),
                {"id": account_id, "today": today_start}
            ).fetchone()
            
            metrics.daily_pnl = daily_trades.pnl if daily_trades and daily_trades.pnl else 0.0
            metrics.daily_loss = abs(metrics.daily_pnl) if metrics.daily_pnl < 0 else 0.0
            
            # 计算未实现盈亏
            unrealized = 0.0
            for pos in positions:
                if pos.current_price:
                    if pos.side == "LONG":
                        unrealized += (float(pos.current_price) - float(pos.entry_price)) * float(pos.quantity)
                    else:
                        unrealized += (float(pos.entry_price) - float(pos.current_price)) * float(pos.quantity)
            
            metrics.unrealized_pnl = unrealized
            
            # 计算当前回撤
            initial_balance = account.initial_balance
            current_balance = account.balance + total_exposure
            if initial_balance > 0:
                metrics.current_drawdown = max(0, (initial_balance - current_balance) / initial_balance)
            
            # 当日订单数
            orders_today = session.execute(
                text("""
                    SELECT COUNT(*) as count 
                    FROM orders 
                    WHERE account_id = :id AND created_at >= :today
                """),
                {"id": account_id, "today": today_start}
            ).fetchone()
            
            metrics.order_count_today = orders_today.count if orders_today else 0
            
            # 评估风险等级
            metrics.risk_level = self._evaluate_risk_level(metrics)
            
        except Exception as e:
            logger.error(f"计算风险指标失败: {e}")
        finally:
            session.close()
        
        return metrics
    
    def _evaluate_risk_level(self, metrics: RiskMetrics) -> RiskLevel:
        """评估风险等级"""
        # 检查各项风险指标
        if metrics.daily_loss >= self.config.max_daily_loss:
            return RiskLevel.STOP_LOSS
        
        if metrics.current_drawdown >= self.config.max_drawdown:
            return RiskLevel.STOP_LOSS
        
        if metrics.daily_pnl < -self.config.max_daily_loss * 0.5:
            return RiskLevel.CRITICAL
        
        if metrics.daily_pnl < 0:
            return RiskLevel.WARNING
        
        return RiskLevel.SAFE
    
    def check_order(self, order: OrderRequest, account_id: int = 1) -> OrderResult:
        """检查订单是否通过风控"""
        metrics = self.calculate_metrics(account_id)
        
        # 检查断路器状态
        if self.current_circuit_breaker == CircuitBreakerLevel.LEVEL_3_STOP_TRADING:
            return OrderResult(
                approved=False,
                risk_level=RiskLevel.STOP_LOSS,
                message="断路器已触发，系统停止交易",
                circuit_breaker_level=CircuitBreakerLevel.LEVEL_3_STOP_TRADING
            )
        
        warnings = []
        
        # 1. 检查仓位限制
        session = self.get_session()
        try:
            account = session.execute(
                text("SELECT * FROM accounts WHERE id = :id"),
                {"id": account_id}
            ).fetchone()
            
            balance = account.balance if account else 10000.0
            
            # 计算订单金额
            order_value = order.quantity * (order.price or self._get_current_price(order.symbol))
            
            # 检查单笔仓位限制
            position_ratio = order_value / balance
            if position_ratio > self.config.max_position_size:
                warnings.append(f"单笔仓位超出限制: {position_ratio*100:.2f}% > {self.config.max_position_size*100}%")
                order.adjusted_quantity = balance * self.config.max_position_size / (order.price or 1)
            
            # 检查总持仓限制
            current_exposure = metrics.total_exposure
            new_exposure = current_exposure + order_value
            total_ratio = new_exposure / balance
            if total_ratio > self.config.max_total_position:
                warnings.append(f"总持仓超出限制: {total_ratio*100:.2f}% > {self.config.max_total_position*100}%")
            
            # 检查止损
            if order.order_type == "stop_loss":
                entry_price = self._get_current_price(order.symbol)
                if order.stop_loss_price and entry_price:
                    loss_percent = abs(order.stop_loss_price - entry_price) / entry_price
                    if loss_percent > self.config.stop_loss_percent:
                        warnings.append(f"止损比例过大: {loss_percent*100:.2f}% > {self.config.stop_loss_percent*100}%")
            
            # 2. 检查日亏损限制
            if metrics.daily_loss + order_value > self.config.max_daily_loss:
                warnings.append(f"日亏损将超出限制")
            
            # 3. 检查订单频率
            if metrics.order_count_today >= self.config.max_orders_per_day:
                warnings.append(f"日订单数已达上限: {metrics.order_count_today}")
            
            # 4. 检查风险等级
            if metrics.risk_level == RiskLevel.CRITICAL:
                warnings.append("当前风险等级: CRITICAL")
            elif metrics.risk_level == RiskLevel.WARNING:
                warnings.append("当前风险等级: WARNING")
            
        finally:
            session.close()
        
        # 决定是否批准
        if metrics.risk_level == RiskLevel.STOP_LOSS:
            return OrderResult(
                approved=False,
                risk_level=RiskLevel.STOP_LOSS,
                message="风险等级STOP_LOSS，禁止开仓",
                circuit_breaker_level=CircuitBreakerLevel.LEVEL_2_FORCE_CLOSE
            )
        
        approved = len([w for w in warnings if "超出限制" in w]) == 0
        
        return OrderResult(
            approved=approved,
            risk_level=metrics.risk_level,
            message="订单已通过风控检查" if approved else "订单需要调整",
            warnings=warnings
        )
    
    def _get_current_price(self, symbol: str) -> float:
        """"获取当前价格（简化实现）"""
        session = self.get_session()
        try:
            result = session.execute(
                text("""
                    SELECT price FROM market_data 
                    WHERE symbol = :symbol 
                    ORDER BY timestamp DESC LIMIT 1
                """),
                {"symbol": symbol}
            ).fetchone()
            # 修复：将 Decimal 转换为 float
            return float(result.price) if result else 50000.0
        finally:
            session.close()
    
    def trigger_circuit_breaker(self, level: CircuitBreakerLevel, reason: str):
        """触发断路器"""
        self.current_circuit_breaker = level
        
        session = self.get_session()
        try:
            # 记录风控日志
            session.execute(
                text("""
                    INSERT INTO risk_logs (event_type, severity, message, details, triggered_at)
                    VALUES (:event_type, :severity, :message, :details, :triggered_at)
                """),
                {
                    "event_type": f"circuit_breaker_level_{level.value}",
                    "severity": "critical",
                    "message": reason,
                    "details": json.dumps({"level": level.value, "reason": reason}),
                    "triggered_at": datetime.utcnow()
                }
            )
            session.commit()
            
            logger.critical(f"断路器触发 | 等级: {level.name} | 原因: {reason}")
            
            # 发送通知（可选）
            self._send_alert(f"🚨 断路器触发: {reason}")
            
        finally:
            session.close()
    
    def reset_circuit_breaker(self):
        """重置断路器（每日或手动）"""
        now = datetime.utcnow()
        if (now - self.last_reset_time).total_seconds() >= CIRCUIT_BREAKER_RESET_INTERVAL:  # 24小时
            self.current_circuit_breaker = None
            self.last_reset_time = now
            logger.info("断路器已重置")
    
    def _send_alert(self, message: str):
        """发送告警通知"""
        import requests  # 修复：移到函数内导入，避免循环导入
        
        # Slack 通知
        slack_webhook = os.getenv("SLACK_WEBHOOK_URL")
        if slack_webhook:
            try:
                requests.post(slack_webhook, json={"text": message}, timeout=5)
            except Exception as e:
                logger.warning(f"Slack 通知失败: {e}")
        
        # Telegram 通知
        telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
        telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if telegram_token and telegram_chat_id:
            try:
                requests.post(
                    f"https://api.telegram.org/bot{telegram_token}/sendMessage",
                    json={"chat_id": telegram_chat_id, "text": message},
                    timeout=5
                )
            except Exception as e:
                logger.warning(f"Telegram 通知失败: {e}")
    
    def log_risk_event(self, event_type: str, severity: str, message: str, details: Dict = None):
        """记录风控事件"""
        session = self.get_session()
        try:
            session.execute(
                text("""
                    INSERT INTO risk_logs (event_type, severity, message, details, triggered_at)
                    VALUES (:event_type, :severity, :message, :details, :triggered_at)
                """),
                {
                    "event_type": event_type,
                    "severity": severity,
                    "message": message,
                    "details": json.dumps(details) if details else None,
                    "triggered_at": datetime.utcnow()
                }
            )
            session.commit()
            logger.info(f"风控日志 | {severity} | {message}")
        except Exception as e:
            logger.error(f"记录风控日志失败: {e}")
        finally:
            session.close()
    
    def get_risk_report(self, account_id: int = 1) -> Dict:
        """生成风险报告"""
        metrics = self.calculate_metrics(account_id)
        
        report = {
            "timestamp": datetime.utcnow().isoformat(),
            "account_id": account_id,
            "risk_level": metrics.risk_level.value,
            "circuit_breaker": self.current_circuit_breaker.name if self.current_circuit_breaker else None,
            "metrics": {
                "total_exposure": f"${metrics.total_exposure:,.2f}",
                "daily_pnl": f"${metrics.daily_pnl:,.2f}",
                "daily_loss": f"${metrics.daily_loss:,.2f}",
                "current_drawdown": f"{metrics.current_drawdown*100:.2f}%",
                "unrealized_pnl": f"${metrics.unrealized_pnl:,.2f}",
                "position_count": metrics.position_count,
                "order_count_today": metrics.order_count_today,
            },
            "limits": {
                "max_position_size": f"{self.config.max_position_size*100}%",
                "max_total_position": f"{self.config.max_total_position*100}%",
                "max_daily_loss": f"${self.config.max_daily_loss:,.2f}",
                "max_drawdown": f"{self.config.max_drawdown*100}%",
                "stop_loss": f"{self.config.stop_loss_percent*100}%",
            },
            "status": "正常" if metrics.risk_level == RiskLevel.SAFE else "警告"
        }
        
        return report



if __name__ == "__main__":
    risk_manager = RiskManager()
    
    # 示例：检查订单
    order = OrderRequest(
        symbol="BTCUSDT",
        side="BUY",
        quantity=0.1,
        price=50000
    )
    
    result = risk_manager.check_order(order)
    print(f"订单检查结果: {result.message}")
    print(f"批准状态: {result.approved}")
    print(f"风险等级: {result.risk_level.value}")
    
    # 生成风险报告
    report = risk_manager.get_risk_report()
    print(f"\n风险报告:\n{json.dumps(report, indent=2, ensure_ascii=False)}")