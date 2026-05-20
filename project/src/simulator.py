# =====================================================
# CC Invest - 模拟交易引擎
# 支持市价单、限价单、止损单模拟执行
# =====================================================

import os
import sys
import json
import time
import uuid
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from pathlib import Path
from decimal import Decimal, ROUND_DOWN
from dataclasses import dataclass, field
from enum import Enum

import requests
import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from dotenv import load_dotenv
from loguru import logger
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.live import Live

# 导入风控模块
from src.risk import RiskManager, RiskConfig, OrderRequest, RiskLevel, CircuitBreakerLevel

# 加载配置
load_dotenv()

console = Console()


class OrderStatus(Enum):
    """订单状态"""
    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class OrderSide(Enum):
    """订单方向"""
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class SimulatedOrder:
    """模拟订单"""
    order_id: str
    account_id: int
    symbol: str
    side: str
    order_type: str
    quantity: float
    price: Optional[float] = None
    stop_price: Optional[float] = None
    filled_quantity: float = 0.0
    avg_fill_price: Optional[float] = None
    status: str = "pending"
    created_at: datetime = field(default_factory=datetime.utcnow)
    filled_at: Optional[datetime] = None
    strategy: str = ""
    commission: float = 0.0
    
    def to_dict(self) -> Dict:
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side,
            "type": self.order_type,
            "quantity": self.quantity,
            "price": self.price,
            "filled_qty": self.filled_quantity,
            "avg_price": self.avg_fill_price,
            "status": self.status,
            "created": self.created_at.isoformat(),
            "commission": self.commission
        }


@dataclass
class SimulatedPosition:
    """模拟持仓"""
    position_id: int
    account_id: int
    symbol: str
    side: str
    quantity: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    status: str = "open"
    opened_at: datetime = field(default_factory=datetime.utcnow)
    closed_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict:
        return {
            "position_id": self.position_id,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "entry": self.entry_price,
            "current": self.current_price,
            "pnl": self.unrealized_pnl,
            "pnl_pct": f"{self.unrealized_pnl / (self.entry_price * self.quantity) * 100:.2f}%"
        }


@dataclass
class SimulatedAccount:
    """模拟账户"""
    account_id: int
    balance: float
    initial_balance: float
    total_pnl: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    max_drawdown: float = 0.0
    
    def to_dict(self) -> Dict:
        return {
            "account_id": self.account_id,
            "balance": f"${self.balance:,.2f}",
            "initial": f"${self.initial_balance:,.2f}",
            "pnl": f"${self.total_pnl:,.2f}",
            "pnl_pct": f"{self.total_pnl / self.initial_balance * 100:.2f}%",
            "trades": self.total_trades,
            "win_rate": f"{self.winning_trades / self.total_trades * 100:.1f}%" if self.total_trades > 0 else "N/A"
        }


class SimulatorEngine:
    """模拟交易引擎"""
    
    def __init__(self, database_url: Optional[str] = None, 
                 trading_mode: str = "paper",
                 initial_balance: float = 10000.0):
        self.db_url = database_url or os.getenv("DATABASE_URL", "sqlite:///data/ccinvest.db")
        self.engine = create_engine(self.db_url)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self._ensure_database_schema()
        
        self.trading_mode = trading_mode
        self.initial_balance = initial_balance
        
        # 初始化风控模块
        self.risk_manager = RiskManager(self.db_url)
        
        # 模拟账户
        self.account = self._init_account()
        
        # 持仓和订单缓存
        self.positions: Dict[str, SimulatedPosition] = {}
        self.pending_orders: List[SimulatedOrder] = []
        self.order_history: List[SimulatedOrder] = []
        
        # 价格缓存
        self.current_prices: Dict[str, float] = {}
        
        # 手续费率
        self.commission_rate = 0.001
        
        # 滑点
        self.slippage = 0.001
        # 价格缓存（避免频繁查询数据库）
        self.price_cache_ttl = 60  # 缓存有效期（秒）
        self._price_cache = {}  # {symbol: (price, timestamp)}

        # 价格缓存（避免频繁查询数据库）
        self.price_cache_ttl = 60  # 缓存有效期（秒）
        self._price_cache = {}  # {symbol: (price, timestamp)}

        # 价格缓存（避免频繁查询数据库）
        self.price_cache_ttl = 60  # 缓存有效期（秒）
        self._price_cache = {}  # {symbol: (price, timestamp)}

        
        logger.info(f"模拟交易引擎初始化 | 模式: {trading_mode} | 初始资金: ${initial_balance}")
    
    def _ensure_database_schema(self):
        """确保模拟交易依赖的数据表已创建。"""
        schema_file = Path(__file__).resolve().parent.parent / "migrations" / "001_initial_schema.sql"
        if not schema_file.exists():
            logger.warning(f"数据库迁移文件不存在: {schema_file}")
            return
        
        sql = schema_file.read_text()
        cleaned_lines = [
            line for line in sql.splitlines()
            if not line.strip().startswith("--")
        ]
        with self.engine.begin() as conn:
            for statement in "\n".join(cleaned_lines).split(";"):
                statement = statement.strip()
                if statement:
                    conn.execute(text(statement))
    
    def _init_account(self) -> SimulatedAccount:
        """初始化账户"""
        session = self.get_session()
        try:
            # 检查是否已有账户
            result = session.execute(text("SELECT * FROM accounts WHERE id = 1")).fetchone()
            
            if result:
                account = SimulatedAccount(
                    account_id=result.id,
                    balance=float(result.balance),
                    initial_balance=float(result.initial_balance),
                    total_pnl=float(result.total_pnl),
                    total_trades=result.total_trades,
                    winning_trades=result.winning_trades,
                    losing_trades=result.losing_trades,
                    max_drawdown=float(result.max_drawdown)
                )
            else:
                # 创建新账户
                session.execute(text("""
                    INSERT INTO accounts (id, balance, initial_balance)
                    VALUES (1, :balance, :initial_balance)
                """), {"balance": self.initial_balance, "initial_balance": self.initial_balance})
                session.commit()
                
                account = SimulatedAccount(
                    account_id=1,
                    balance=self.initial_balance,
                    initial_balance=self.initial_balance
                )
            
            return account
        finally:
            session.close()
    
    def get_session(self) -> Session:
        return self.SessionLocal()
    
    def get_current_price(self, symbol: str) -> float:
        """获取当前价格（带缓存）"""
        import time
        now = time.time()
        
        # 检查缓存
        if symbol in self._price_cache:
            price, timestamp = self._price_cache[symbol]
            if now - timestamp < self.price_cache_ttl:
                return price
        
        # 缓存未命中，查询数据库
        if symbol in self.current_prices:
            return self.current_prices[symbol]
        
        session = self.get_session()
        try:
            result = session.execute(text("""
                SELECT price FROM market_data 
                WHERE symbol = :symbol 
                ORDER BY timestamp DESC 
                LIMIT 1
            """), {"symbol": symbol}).fetchone()
            
            if result:
                return float(result.price)
            
            # 默认价格
            default_prices = {
                "BTCUSDT": 50000.0,
                "ETHUSDT": 3000.0,
                "BNBUSDT": 350.0,
                "SOLUSDT": 100.0,
            }
            price = default_prices.get(symbol, 1000.0)
            self._price_cache[symbol] = (price, now)  # 更新缓存
            return price
        finally:
            session.close()
    
    def update_prices(self, symbols: List[str]):
        """更新价格缓存"""
        for symbol in symbols:
            self.current_prices[symbol] = self.get_current_price(symbol)
    
    def check_risk(self, order: OrderRequest) -> Dict:
        """风控检查"""
        return self.risk_manager.check_order(order, self.account.account_id)
    
    def place_order(self, symbol: str, side: str, quantity: float,
                    order_type: str = "market",
                    price: Optional[float] = None,
                    stop_price: Optional[float] = None,
                    strategy: str = "") -> Dict:
        """下单"""
        
        # 生成订单 ID
        order_id = f"SIM_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6].upper()}"
        
        # 获取当前价格
        current_price = self.get_current_price(symbol)
        execution_price = price or current_price
        normalized_side = side.upper()
        normalized_order_type = order_type.lower()
        
        if normalized_side not in {OrderSide.BUY.value, OrderSide.SELL.value}:
            return {
                "status": "rejected",
                "order_id": order_id,
                "reason": "不支持的交易方向",
                "warnings": [f"side 必须是 BUY 或 SELL，当前为 {side}"]
            }
        
        if normalized_order_type == "limit" and price is None:
            return {
                "status": "rejected",
                "order_id": order_id,
                "reason": "限价单必须提供 price",
                "warnings": []
            }
        
        if normalized_side == OrderSide.BUY.value:
            estimated_cost = quantity * execution_price * (1 + self.commission_rate)
            if estimated_cost > self.account.balance:
                return {
                    "status": "rejected",
                    "order_id": order_id,
                    "reason": "账户余额不足",
                    "warnings": [f"预计成本 {estimated_cost:.2f} > 可用余额 {self.account.balance:.2f}"]
                }
        else:
            available_qty = self._get_open_position_quantity(symbol)
            if quantity > available_qty:
                return {
                    "status": "rejected",
                    "order_id": order_id,
                    "reason": "持仓不足，无法卖出",
                    "warnings": [f"可卖数量 {available_qty:.8f} < 下单数量 {quantity:.8f}"]
                }
        
        # 构建订单请求
        order_req = OrderRequest(
            symbol=symbol,
            side=normalized_side,
            quantity=quantity,
            price=execution_price,
            order_type=normalized_order_type,
            stop_loss_price=stop_price
        )
        
        # 风控检查
        risk_result = self.check_risk(order_req)
        
        if not risk_result.approved:
            logger.warning(f"订单被风控拒绝 | {risk_result.message}")
            return {
                "status": "rejected",
                "order_id": order_id,
                "reason": risk_result.message,
                "risk_level": risk_result.risk_level.value,
                "warnings": risk_result.warnings
            }
        
        # 创建模拟订单
        order = SimulatedOrder(
            order_id=order_id,
            account_id=self.account.account_id,
            symbol=symbol,
            side=normalized_side,
            order_type=normalized_order_type,
            quantity=quantity,
            price=price,
            stop_price=stop_price,
            strategy=strategy,
            created_at=datetime.utcnow()
        )
        
        # 执行订单
        if normalized_order_type == "market":
            fill_result = self._fill_market_order(order, current_price)
        elif normalized_order_type == "limit":
            fill_result = self._fill_limit_order(order, price)
        else:
            fill_result = {"status": "rejected", "message": "不支持的订单类型"}
        
        if order.status == OrderStatus.PENDING.value:
            self.pending_orders.append(order)
        else:
            self.order_history.append(order)
        
        logger.info(f"订单已创建 | {order_id} | {side} {quantity} {symbol}")
        
        return {
            "status": "filled" if fill_result["status"] == "filled" else "pending",
            "order_id": order_id,
            "symbol": symbol,
            "side": normalized_side,
            "quantity": quantity,
            "price": fill_result.get("fill_price", execution_price),
            "message": fill_result.get("message", ""),
            "risk_level": risk_result.risk_level.value
        }
    
    def _fill_market_order(self, order: SimulatedOrder, current_price: float) -> Dict:
        """模拟市价单成交"""
        
        # 计算滑点
        if order.side == "BUY":
            fill_price = current_price * (1 + self.slippage)
        else:
            fill_price = current_price * (1 - self.slippage)
        
        # 模拟成交延迟
        time.sleep(0.1)
        
        # 更新订单
        order.filled_quantity = order.quantity
        order.avg_fill_price = fill_price
        order.status = "filled"
        order.filled_at = datetime.utcnow()
        
        # 计算手续费
        order.commission = order.quantity * fill_price * self.commission_rate
        
        # 更新账户和持仓
        self._update_account_and_position(order)
        
        # 记录交易
        self._record_trade(order)
        
        return {
            "status": "filled",
            "fill_price": fill_price,
            "message": f"模拟成交: {order.side} {order.quantity} {order.symbol} @ {fill_price:.2f}"
        }
    
    def _get_open_position_quantity(self, symbol: str) -> float:
        """获取指定交易对当前可卖持仓数量。"""
        session = self.get_session()
        try:
            result = session.execute(text("""
                SELECT COALESCE(SUM(quantity), 0) as quantity
                FROM positions
                WHERE account_id = :account_id AND symbol = :symbol AND status = 'open'
            """), {"account_id": self.account.account_id, "symbol": symbol}).fetchone()
            return float(result.quantity) if result else 0.0
        finally:
            session.close()
    
    def _fill_limit_order(self, order: SimulatedOrder, limit_price: float) -> Dict:
        """模拟限价单成交"""
        
        current_price = self.get_current_price(order.symbol)
        
        # 检查是否满足成交条件
        can_fill = False
        if order.side == "BUY" and current_price <= limit_price:
            can_fill = True
        elif order.side == "SELL" and current_price >= limit_price:
            can_fill = True
        
        if can_fill:
            return self._fill_market_order(order, current_price)
        else:
            return {
                "status": "pending",
                "message": f"限价单等待成交 | 当前价格: {current_price:.2f} | 限价: {limit_price:.2f}"
            }
    
    def _update_account_and_position(self, order: SimulatedOrder):
        """更新账户和持仓"""
        session = self.get_session()
        
        try:
            if order.side == "BUY":
                # 买入：扣除资金，增加持仓
                cost = order.filled_quantity * order.avg_fill_price + order.commission
                self.account.balance -= cost
                
                # 更新或创建持仓
                existing_pos = session.execute(text("""
                    SELECT * FROM positions 
                    WHERE account_id = :account_id AND symbol = :symbol AND status = 'open'
                """), {"account_id": self.account.account_id, "symbol": order.symbol}).fetchone()
                
                if existing_pos:
                    # 更新持仓
                    new_qty = existing_pos.quantity + order.filled_quantity
                    new_cost = existing_pos.entry_price * existing_pos.quantity + order.avg_fill_price * order.filled_quantity
                    new_entry = new_cost / new_qty
                    
                    session.execute(text("""
                        UPDATE positions 
                        SET quantity = :quantity, entry_price = :entry_price
                        WHERE id = :id
                    """), {"quantity": new_qty, "entry_price": new_entry, "id": existing_pos.id})
                else:
                    # 新建持仓
                    session.execute(text("""
                        INSERT INTO positions (account_id, symbol, side, quantity, entry_price, current_price, status)
                        VALUES (:account_id, :symbol, 'LONG', :quantity, :entry_price, :current_price, 'open')
                    """), {
                        "account_id": self.account.account_id,
                        "symbol": order.symbol,
                        "quantity": order.filled_quantity,
                        "entry_price": order.avg_fill_price,
                        "current_price": order.avg_fill_price
                    })
            
            else:
                # 卖出：增加资金，可能平仓
                revenue = order.filled_quantity * order.avg_fill_price - order.commission
                self.account.balance += revenue
                
                # 检查是否有持仓可平
                existing_pos = session.execute(text("""
                    SELECT * FROM positions 
                    WHERE account_id = :account_id AND symbol = :symbol AND status = 'open'
                """), {"account_id": self.account.account_id, "symbol": order.symbol}).fetchone()
                
                pnl = 0
                if existing_pos:
                    if order.filled_quantity >= existing_pos.quantity:
                        # 全部平仓
                        pnl = (order.avg_fill_price - existing_pos.entry_price) * existing_pos.quantity
                        session.execute(text("""
                            UPDATE positions 
                            SET status = 'closed', current_price = :current_price, closed_at = :closed_at
                            WHERE id = :id
                        """), {
                            "current_price": order.avg_fill_price,
                            "closed_at": datetime.utcnow(),
                            "id": existing_pos.id
                        })
                    else:
                        # 部分平仓 - 修复：支持部分平仓
                        remaining_qty = existing_pos.quantity - order.filled_quantity
                        pnl = (order.avg_fill_price - existing_pos.entry_price) * order.filled_quantity
                        session.execute(text("""
                            UPDATE positions 
                            SET quantity = :quantity, current_price = :current_price
                            WHERE id = :id
                        """), {
                            "quantity": remaining_qty,
                            "current_price": order.avg_fill_price,
                            "id": existing_pos.id
                        })
                    
                    self.account.total_pnl += pnl
                    
                    if pnl > 0:
                        self.account.winning_trades += 1
                    else:
                        self.account.losing_trades += 1
                    
                    self.account.total_trades += 1
            
            # 更新账户余额
            session.execute(text("""
                UPDATE accounts 
                SET balance = :balance, total_pnl = :pnl, 
                    total_trades = :total_trades, winning_trades = :winning,
                    losing_trades = :losing, updated_at = :updated_at
                WHERE id = :id
            """), {
                "balance": self.account.balance,
                "pnl": self.account.total_pnl,
                "total_trades": self.account.total_trades,
                "winning": self.account.winning_trades,
                "losing": self.account.losing_trades,
                "updated_at": datetime.utcnow(),
                "id": self.account.account_id
            })
            
            session.commit()
            
        except Exception as e:
            logger.error(f"更新账户失败: {e}")
            session.rollback()
        finally:
            session.close()
    
    def _record_trade(self, order: SimulatedOrder):
        """记录交易"""
        session = self.get_session()
        
        try:
            pnl = 0
            if order.side == "SELL":
                # 计算卖出盈亏
                existing_pos = session.execute(text("""
                    SELECT * FROM positions 
                    WHERE account_id = :account_id AND symbol = :symbol AND status = 'closed'
                    ORDER BY closed_at DESC LIMIT 1
                """), {"account_id": self.account.account_id, "symbol": order.symbol}).fetchone()
                
                if existing_pos:
                    pnl = (order.avg_fill_price - existing_pos.entry_price) * order.filled_quantity
            
            # 插入交易记录
            session.execute(text("""
                INSERT INTO trades (account_id, symbol, side, quantity, price, commission, pnl, strategy, timestamp)
                VALUES (:account_id, :symbol, :side, :quantity, :price, :commission, :pnl, :strategy, :timestamp)
            """), {
                "account_id": self.account.account_id,
                "symbol": order.symbol,
                "side": order.side,
                "quantity": order.filled_quantity,
                "price": order.avg_fill_price,
                "commission": order.commission,
                "pnl": pnl,
                "strategy": order.strategy,
                "timestamp": datetime.utcnow()
            })
            
            # 记录订单
            session.execute(text("""
                INSERT INTO orders (account_id, symbol, side, order_type, quantity, price, filled_quantity, avg_fill_price, status, order_id, created_at, updated_at)
                VALUES (:account_id, :symbol, :side, :order_type, :quantity, :price, :filled_quantity, :avg_fill_price, :status, :order_id, :created_at, :updated_at)
            """), {
                "account_id": self.account.account_id,
                "symbol": order.symbol,
                "side": order.side,
                "order_type": order.order_type,
                "quantity": order.quantity,
                "price": order.price,
                "filled_quantity": order.filled_quantity,
                "avg_fill_price": order.avg_fill_price,
                "status": order.status,
                "order_id": order.order_id,
                "created_at": order.created_at,
                "updated_at": datetime.utcnow()
            })
            
            session.commit()
            
            logger.info(f"交易已记录 | {order.order_id} | {order.side} {order.filled_quantity} {order.symbol}")
            
        except Exception as e:
            logger.error(f"记录交易失败: {e}")
            session.rollback()
        finally:
            session.close()
    
    def get_positions(self) -> List[Dict]:
        """获取当前持仓"""
        session = self.get_session()
        positions = []
        
        try:
            results = session.execute(text("""
                SELECT * FROM positions 
                WHERE account_id = :account_id AND status = 'open'
            """), {"account_id": self.account.account_id}).fetchall()
            
            for pos in results:
                # 计算未实现盈亏
                current_price = self.get_current_price(pos.symbol)
                unrealized_pnl = (current_price - pos.entry_price) * pos.quantity
                
                positions.append({
                    "position_id": pos.id,
                    "symbol": pos.symbol,
                    "side": pos.side,
                    "quantity": pos.quantity,
                    "entry_price": pos.entry_price,
                    "current_price": current_price,
                    "unrealized_pnl": unrealized_pnl,
                    "pnl_pct": f"{unrealized_pnl / (pos.entry_price * pos.quantity) * 100:.2f}%"
                })
            
        finally:
            session.close()
        
        return positions
    
    def get_order_history(self, limit: int = 20) -> List[Dict]:
        """获取订单历史"""
        session = self.get_session()
        orders = []
        
        try:
            results = session.execute(text("""
                SELECT * FROM orders 
                WHERE account_id = :account_id
                ORDER BY created_at DESC
                LIMIT :limit
            """), {"account_id": self.account.account_id, "limit": limit}).fetchall()
            
            for order in results:
                orders.append({
                    "order_id": order.order_id,
                    "symbol": order.symbol,
                    "side": order.side,
                    "type": order.order_type,
                    "quantity": order.quantity,
                    "filled": order.filled_quantity,
                    "avg_price": order.avg_fill_price,
                    "status": order.status,
                    "created": order.created_at.isoformat()
                })
            
        finally:
            session.close()
        
        return orders
    
    def display_status(self):
        """显示状态面板"""
        # 清屏并显示状态
        console.clear()
        
        # 账户信息
        account_table = Table(title="📊 账户信息")
        account_table.add_column("指标", style="cyan")
        account_table.add_column("值", style="green")
        
        account_table.add_row("余额", f"${self.account.balance:,.2f}")
        account_table.add_row("初始资金", f"${self.account.initial_balance:,.2f}")
        account_table.add_row("总盈亏", f"${self.account.total_pnl:,.2f}")
        account_table.add_row("收益率", f"{self.account.total_pnl / self.account.initial_balance * 100:.2f}%")
        account_table.add_row("交易次数", str(self.account.total_trades))
        
        console.print(account_table)
        
        # 持仓信息
        positions = self.get_positions()
        if positions:
            pos_table = Table(title="📈 当前持仓")
            pos_table.add_column("交易对", style="cyan")
            pos_table.add_column("方向", style="yellow")
            pos_table.add_column("数量", style="white")
            pos_table.add_column("入场价", style="white")
            pos_table.add_column("当前价", style="white")
            pos_table.add_column("盈亏", style="green")
            
            for pos in positions:
                pnl_color = "green" if pos["unrealized_pnl"] >= 0 else "red"
                pos_table.add_row(
                    pos["symbol"],
                    pos["side"],
                    f"{pos['quantity']:.4f}",
                    f"${pos['entry_price']:,.2f}",
                    f"${pos['current_price']:,.2f}",
                    f"[{pnl_color}]{pos['unrealized_pnl']:,.2f} ({pos['pnl_pct']})[/]"
                )
            
            console.print(pos_table)
        
        # 风险指标
        risk_report = self.risk_manager.get_risk_report(self.account.account_id)
        console.print(Panel(
            f"[bold]风险等级:[/bold] {risk_report['risk_level']}\n"
            f"[bold]断路器:[/bold] {risk_report['circuit_breaker'] or '正常'}\n"
            f"[bold]总敞口:[/bold] {risk_report['metrics']['total_exposure']}\n"
            f"[bold]日盈亏:[/bold] {risk_report['metrics']['daily_pnl']}",
            title="🛡️ 风险状态",
            border_style="yellow"
        ))
    
    def run_live_mode(self, symbols: List[str], interval: int = 5):
        """实时运行模式"""
        console.print(Panel(
            "[bold green]模拟交易引擎已启动[/bold green]\n"
            f"交易模式: {self.trading_mode}\n"
            f"监控交易对: {', '.join(symbols)}",
            title="🚀 CC Invest Simulator"
        ))
        
        try:
            with Live(console=console, refresh_per_second=1) as live:
                while True:
                    # 更新价格
                    self.update_prices(symbols)
                    
                    # 显示状态
                    self.display_status()
                    
                    time.sleep(interval)
                    
        except KeyboardInterrupt:
            console.print("\n[bold red]模拟交易引擎已停止[/bold red]")


def main():
    """命令行入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description='CC Invest 模拟交易引擎')
    parser.add_argument('--mode', default='paper', choices=['paper', 'live'], help='交易模式')
    parser.add_argument('--capital', type=float, default=10000, help='初始资金')
    parser.add_argument('--symbols', nargs='+', default=['BTCUSDT', 'ETHUSDT'], help='交易对列表')
    parser.add_argument('--interval', type=int, default=5, help='更新间隔(秒)')
    
    args = parser.parse_args()
    
    simulator = SimulatorEngine(
        trading_mode=args.mode,
        initial_balance=args.capital
    )
    
    # 示例命令
    if len(sys.argv) == 1:
        # 默认示例
        console.print("[bold]可用命令:[/bold]")
        console.print("  buy <symbol> <quantity> - 买入")
        console.print("  sell <symbol> <quantity> - 卖出")
        console.print("  positions - 查看持仓")
        console.print("  orders - 查看订单")
        console.print("  status - 显示状态")
        console.print("  exit - 退出")
        
        while True:
            cmd = input("\n> ").strip().split()
            if not cmd:
                continue
            
            if cmd[0] == "exit":
                break
            elif cmd[0] == "buy" and len(cmd) >= 3:
                result = simulator.place_order(cmd[1], "BUY", float(cmd[2]), strategy="manual")
                console.print(f"[green]{result}[/green]")
            elif cmd[0] == "sell" and len(cmd) >= 3:
                result = simulator.place_order(cmd[1], "SELL", float(cmd[2]), strategy="manual")
                console.print(f"[green]{result}[/green]")
            elif cmd[0] == "positions":
                for pos in simulator.get_positions():
                    console.print(pos)
            elif cmd[0] == "orders":
                for order in simulator.get_order_history():
                    console.print(order)
            elif cmd[0] == "status":
                simulator.display_status()
    else:
        simulator.run_live_mode(args.symbols, args.interval)


if __name__ == "__main__":
    main()
