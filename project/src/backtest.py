# =====================================================
# CC Invest - 回测模块
# 支持 Backtrader、VectorBT 多框架回测
# =====================================================

import os
import sys
import json
import logging
import argparse
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path

import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
from loguru import logger
import backtrader as bt

# 加载配置
load_dotenv()


class BacktestResult:
    """回测结果"""
    def __init__(self):
        self.initial_capital = 0.0
        self.final_capital = 0.0
        self.total_return = 0.0
        self.sharpe_ratio = 0.0
        self.max_drawdown = 0.0
        self.win_rate = 0.0
        self.profit_factor = 0.0
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.avg_win = 0.0
        self.avg_loss = 0.0
        self.equity_curve = []
        self.trades = []
        self.parameters = {}


class EquityCurveAnalyzer(bt.Analyzer):
    """记录每个 bar 结束时的账户权益。"""
    
    def start(self):
        self.values = []
    
    def next(self):
        self.values.append({
            "date": self.strategy.datas[0].datetime.datetime(0),
            "value": self.strategy.broker.getvalue()
        })
    
    def get_analysis(self):
        return self.values


class StrategyBase(bt.Strategy):
    """基础策略类"""
    
    def __init__(self):
        self.order = None
        self.entry_price = None
        self.entry_date = None
        
        # 技术指标
        self.sma_short = bt.ind.SMA(period=20)
        self.sma_long = bt.ind.SMA(period=50)
        self.rsi = bt.ind.RSI(period=14)
    
    def log(self, txt, dt=None):
        dt = dt or self.datas[0].datetime.date(0)
        logger.info(f'{dt.isoformat()} {txt}')
    
    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        
        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f'BUY EXECUTED, Price: {order.executed.price:.2f}')
            else:
                self.log(f'SELL EXECUTED, Price: {order.executed.price:.2f}')
            self.order = None
        
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log('Order Canceled/Margin/Rejected')
            self.order = None
    
    def notify_trade(self, trade):
        if trade.isclosed:
            self.log(f'TRADE PROFIT, GROSS: {trade.pnl:.2f}, NET: {trade.pnlcomm:.2f}')


class MeanReversionStrategy(StrategyBase):
    """均值回归策略"""
    
    params = (
        ('period_short', 20),
        ('period_long', 50),
        ('rsi_period', 14),
        ('rsi_lower', 30),
        ('rsi_upper', 70),
        ('bb_period', 20),
        ('bb_dev', 2),
    )
    
    def __init__(self):
        super().__init__()
        
        # 布林带
        self.bb = bt.ind.BollingerBands(
            period=self.params.bb_period,
            devfactor=self.params.bb_dev
        )
        
        self.buy_signal = bt.ind.CrossOver(self.data, self.bb.lines.bot)
        self.sell_signal = bt.ind.CrossOver(self.data, self.bb.lines.top)
    
    def next(self):
        if self.order:
            return
        
        # 买入信号：价格触及布林带下轨
        if not self.position:
            if self.data.close[0] < self.bb.lines.bot[0]:
                self.log(f'BUY CREATE, Price: {self.data[0]:.2f}')
                self.order = self.buy()
        
        # 卖出信号：价格触及布林带上轨
        else:
            if self.data.close[0] > self.bb.lines.top[0]:
                self.log(f'SELL CREATE, Price: {self.data[0]:.2f}')
                self.order = self.sell()


class TrendFollowingStrategy(StrategyBase):
    """趋势跟踪策略"""
    
    params = (
        ('period_short', 20),
        ('period_long', 50),
        ('atr_period', 14),
    )
    
    def __init__(self):
        super().__init__()
        
        # ATR 用于止损
        self.atr = bt.ind.ATR(period=self.params.atr_period)
        
        # 交叉信号
        self.crossover = bt.ind.CrossOver(self.sma_short, self.sma_long)
    
    def next(self):
        if self.order:
            return
        
        # 金叉买入
        if not self.position:
            if self.crossover > 0:
                self.log(f'BUY CREATE, Price: {self.data[0]:.2f}')
                self.order = self.buy()
        
        # 死叉卖出
        elif self.crossover < 0:
            self.log(f'SELL CREATE, Price: {self.data[0]:.2f}')
            self.order = self.sell()


class RSIStrategy(StrategyBase):
    """RSI 策略"""
    
    params = (
        ('rsi_period', 14),
        ('rsi_lower', 30),
        ('rsi_upper', 70),
    )
    
    def next(self):
        if self.order:
            return
        
        # RSI 超卖买入
        if not self.position:
            if self.rsi < self.params.rsi_lower:
                self.log(f'BUY CREATE, RSI: {self.rsi[0]:.2f}')
                self.order = self.buy()
        
        # RSI 超买卖出
        elif self.rsi > self.params.rsi_upper:
            self.log(f'SELL CREATE, RSI: {self.rsi[0]:.2f}')
            self.order = self.sell()


class BacktestEngine:
    """回测引擎"""
    
    def __init__(self, database_url: Optional[str] = None):
        self.db_url = database_url or os.getenv("DATABASE_URL", "sqlite:///data/ccinvest.db")
        self.engine = create_engine(self.db_url)
        
        # 策略映射
        self.strategies = {
            'mean_reversion': MeanReversionStrategy,
            'trend_following': TrendFollowingStrategy,
            'rsi': RSIStrategy,
        }
        
        logger.info("回测引擎初始化完成")
    
    def load_data(self, symbol: str, start_date: str, end_date: str, 
                  timeframe: str = "1h") -> pd.DataFrame:
        """从数据库加载 K 线数据"""
        try:
            query = text("""
                SELECT timestamp as datetime, 
                       open_price as open, 
                       high_price as high, 
                       low_price as low, 
                       close_price as close, 
                       volume
                FROM ohlc_data
                WHERE symbol = :symbol 
                  AND timeframe = :timeframe
                  AND timestamp BETWEEN :start_date AND :end_date
                ORDER BY datetime ASC
            """)
            
            df = pd.read_sql(query, self.engine, params={
                "symbol": symbol,
                "timeframe": timeframe,
                "start_date": start_date,
                "end_date": end_date
            })
            
            if len(df) == 0:
                logger.warning(f"未找到 {symbol} 的数据，生成示例数据")
                df = self._generate_sample_data(symbol, start_date, end_date)
            
            logger.info(f"加载数据: {symbol}, {len(df)} 条记录")
            return df
            
        except Exception as e:
            logger.error(f"加载数据失败: {e}")
            return self._generate_sample_data(symbol, start_date, end_date)
    
    def _generate_sample_data(self, symbol: str, start_date: str, 
                              end_date: str, freq: str = "1h") -> pd.DataFrame:
        """生成示例数据用于回测"""
        start = pd.to_datetime(start_date)
        end = pd.to_datetime(end_date)
        
        dates = pd.date_range(start, end, freq=freq)
        
        # 模拟价格走势
        initial_price = 50000 if "BTC" in symbol else 3000
        np.random.seed(42)
        
        returns = np.random.normal(0.0005, 0.02, len(dates))
        prices = initial_price * np.exp(np.cumsum(returns))
        
        df = pd.DataFrame({
            'datetime': dates,
            'open': prices * (1 + np.random.uniform(-0.005, 0.005, len(dates))),
            'high': prices * (1 + np.random.uniform(0, 0.01, len(dates))),
            'low': prices * (1 - np.random.uniform(0, 0.01, len(dates))),
            'close': prices,
            'volume': np.random.uniform(100, 1000, len(dates))
        })
        
        df['datetime'] = pd.to_datetime(df['datetime'])
        return df
    
    def run_backtrader_backtest(self, symbol: str, strategy_name: str,
                                 start_date: str, end_date: str,
                                 initial_capital: float = 10000,
                                 commission: float = 0.001,
                                 **strategy_params) -> BacktestResult:
        """使用 Backtrader 运行回测"""
        logger.info(f"启动 Backtrader 回测 | 策略: {strategy_name}")
        
        # 加载数据
        df = self.load_data(symbol, start_date, end_date)
        
        # 创建 Cerebro 引擎
        cerebro = bt.Cerebro()
        cerebro.broker.setcommission(commission=commission)
        cerebro.broker.setcash(initial_capital)
        
        # 添加数据
        data = bt.feeds.PandasData(
            dataname=df,
            datetime=0,
            open=1,
            high=2,
            low=3,
            close=4,
            volume=5,
            openinterest=-1
        )
        cerebro.adddata(data)
        
        # 添加策略
        strategy_class = self.strategies.get(strategy_name, MeanReversionStrategy)
        cerebro.addstrategy(strategy_class, **strategy_params)
        
        # 添加分析器
        cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
        cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
        cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
        cerebro.addanalyzer(EquityCurveAnalyzer, _name='equity')
                
        # 结果
        result = BacktestResult()
        result.initial_capital = initial_capital
        result.parameters = strategy_params
        
        # 运行回测
        try:
            strategies = cerebro.run()
            strategy = strategies[0]
            
            # 获取最终资金
            result.final_capital = cerebro.broker.getvalue()
            result.total_return = (result.final_capital - result.initial_capital) / result.initial_capital * 100
            
            # 获取分析结果
            sharpe = strategy.analyzers.sharpe.get_analysis()
            result.sharpe_ratio = sharpe.get('sharperatio', 0) or 0
            
            drawdown = strategy.analyzers.drawdown.get_analysis()
            result.max_drawdown = drawdown.get('max', {}).get('drawdown', 0) or 0
            
            trades = strategy.analyzers.trades.get_analysis()
            result.total_trades = trades.get('total', {}).get('total', 0) or 0
            result.winning_trades = trades.get('won', {}).get('total', 0) or 0
            result.losing_trades = trades.get('lost', {}).get('total', 0) or 0
            
            if result.total_trades > 0:
                result.win_rate = result.winning_trades / result.total_trades * 100
            
            # 计算盈亏比
            avg_win = trades.get('won', {}).get('pnl', {}).get('average', 0) or 0
            avg_loss = trades.get('lost', {}).get('pnl', {}).get('average', 0) or 0
            result.avg_win = avg_win
            result.avg_loss = abs(avg_loss)
            if result.avg_loss > 0:
                result.profit_factor = abs(avg_win / result.avg_loss)
            
            # 生成权益曲线
            result.equity_curve = strategy.analyzers.equity.get_analysis()
            
            logger.info(f"回测完成 | 收益率: {result.total_return:.2f}%")
            
        except Exception as e:
            logger.error(f"回测执行失败: {e}")
        
        return result
    
    def run_vectorbt_backtest(self, symbol: str, strategy_name: str,
                                start_date: str, end_date: str,
                                initial_capital: float = 10000,
                                commission: float = 0.001) -> BacktestResult:
        """使用 VectorBT 运行向量化回测"""
        logger.info(f"启动 VectorBT 回测 | 策略: {strategy_name}")
        try:
            import vectorbt as vbt
        except Exception as e:
            raise RuntimeError(f"VectorBT 当前不可用，请改用 backtrader 引擎: {e}") from e
        
        # 加载数据
        df = self.load_data(symbol, start_date, end_date)
        close = df['close'].values
        
        result = BacktestResult()
        result.initial_capital = initial_capital
        
        try:
            if strategy_name == 'mean_reversion':
                # 均值回归策略
                entries = close < pd.Series(close).rolling(20).mean() - 2 * pd.Series(close).rolling(20).std()
                exits = close > pd.Series(close).rolling(20).mean() + 2 * pd.Series(close).rolling(20).std()
            
            elif strategy_name == 'trend_following':
                # 趋势跟踪策略
                ma_short = pd.Series(close).rolling(20).mean()
                ma_long = pd.Series(close).rolling(50).mean()
                entries = ma_short > ma_long
                exits = ma_short < ma_long
            
            elif strategy_name == 'rsi':
                # RSI 策略
                delta = pd.Series(close).diff()
                gain = delta.where(delta > 0, 0).rolling(14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
                rs = gain / loss
                rsi = 100 - (100 / (1 + rs))
                entries = rsi < 30
                exits = rsi > 70
            
            else:
                entries = pd.Series([False] * len(close))
                exits = pd.Series([False] * len(close))
            
            # 转换为布尔数组
            entries = entries.values
            exits = exits.values
            
            # 运行回测
            pf = vbt.Portfolio.from_signals(
                close=close,
                entries=entries,
                exits=exits,
                freq='1h',
                init_cash=initial_capital,
                commission=commission,
                slippage=0.001
            )
            
            # 获取结果
            result.final_capital = pf.value().iloc[-1]
            result.total_return = (pf.total_return() * 100).iloc[0]
            result.sharpe_ratio = (pf.sharpe_ratio() * np.sqrt(24 * 365)).iloc[0] if not np.isnan(pf.sharpe_ratio().iloc[0]) else 0
            
            dd = pf.max_drawdown()
            result.max_drawdown = (dd / 100).iloc[0] if not np.isnan(dd.iloc[0]) else 0
            
            stats = pf.stats()
            result.total_trades = int(stats['trades'])
            result.winning_trades = int(stats['winning_trades'])
            result.losing_trades = int(stats['lost_trades'])
            result.win_rate = stats['win_rate'] * 100 if not np.isnan(stats['win_rate']) else 0
            result.profit_factor = stats['profit_factor'] if not np.isnan(stats['profit_factor']) else 0
            
            result.equity_curve = [
                {'date': df['datetime'].iloc[i], 'value': v}
                for i, v in enumerate(pf.value().values)
            ]
            
            logger.info(f"VectorBT 回测完成 | 收益率: {result.total_return:.2f}%")
            
        except Exception as e:
            logger.error(f"VectorBT 回测失败: {e}")
        
        return result
    
    def run_monte_carlo(self, result: BacktestResult, 
                        n_simulations: int = 100) -> Dict:
        """蒙特卡洛压力测试"""
        logger.info(f"启动蒙特卡洛测试 | 模拟次数: {n_simulations}")
        
        if not result.equity_curve:
            logger.warning("无权益曲线数据，跳过蒙特卡洛测试")
            return {}
        
        equity_values = [e['value'] for e in result.equity_curve]
        returns = np.diff(equity_values) / equity_values[:-1]
        
        final_capitals = []
        max_drawdowns = []
        
        np.random.seed(42)
        
        for _ in range(n_simulations):
            # 随机重采样收益率
            sampled_returns = np.random.choice(returns, size=len(returns), replace=True)
            
            # 模拟权益曲线
            capital = result.initial_capital
            equity = [capital]
            peak = capital
            
            for ret in sampled_returns:
                capital *= (1 + ret)
                equity.append(capital)
                peak = max(peak, capital)
            
            final_capitals.append(capital)
            
            # 计算最大回撤
            max_dd = 0
            running_peak = equity[0]
            for e in equity:
                running_peak = max(running_peak, e)
                dd = (running_peak - e) / running_peak
                max_dd = max(max_dd, dd)
            max_drawdowns.append(max_dd)
        
        analysis = {
            'n_simulations': n_simulations,
            'final_capital': {
                'mean': np.mean(final_capitals),
                'median': np.median(final_capitals),
                'std': np.std(final_capitals),
                'min': np.min(final_capitals),
                'max': np.max(final_capitals),
                'percentile_5': np.percentile(final_capitals, 5),
                'percentile_95': np.percentile(final_capitals, 95),
            },
            'max_drawdown': {
                'mean': np.mean(max_drawdowns) * 100,
                'median': np.median(max_drawdowns) * 100,
                'max': np.max(max_drawdowns) * 100,
                'percentile_95': np.percentile(max_drawdowns, 95) * 100,
            },
            'survival_rate': sum(1 for c in final_capitals if c >= result.initial_capital) / n_simulations * 100
        }
        
        logger.info(f"蒙特卡洛测试完成 | 存活率: {analysis['survival_rate']:.1f}%")
        
        return analysis
    
    def save_result(self, result: BacktestResult, strategy_name: str,
                    symbol: str, start_date: str, end_date: str):
        """保存回测结果到数据库"""
        session = self.engine.connect()
        try:
            query = text("""
                INSERT INTO backtest_results (
                    strategy, symbol, start_date, end_date,
                    initial_capital, final_capital, total_return,
                    sharpe_ratio, max_drawdown, win_rate,
                    total_trades, parameters, equity_curve,
                    created_at
                ) VALUES (
                    :strategy, :symbol, :start_date, :end_date,
                    :initial_capital, :final_capital, :total_return,
                    :sharpe_ratio, :max_drawdown, :win_rate,
                    :total_trades, :parameters, :equity_curve,
                    :created_at
                )
            """)
            
            session.execute(query, {
                'strategy': strategy_name,
                'symbol': symbol,
                'start_date': start_date,
                'end_date': end_date,
                'initial_capital': result.initial_capital,
                'final_capital': result.final_capital,
                'total_return': result.total_return,
                'sharpe_ratio': result.sharpe_ratio,
                'max_drawdown': result.max_drawdown,
                'win_rate': result.win_rate,
                'total_trades': result.total_trades,
                'parameters': json.dumps(result.parameters),
                'equity_curve': json.dumps(result.equity_curve, default=str),
                'created_at': datetime.utcnow()
            })
            session.commit()
            
            logger.info("回测结果已保存")
            
        except Exception as e:
            logger.error(f"保存回测结果失败: {e}")
        finally:
            session.close()
    
    def generate_report(self, result: BacktestResult, 
                        monte_carlo: Optional[Dict] = None) -> str:
        """生成回测报告"""
        report = f"""
═══════════════════════════════════════════════════════
                    回 测 报 告
═══════════════════════════════════════════════════════

📊 收益指标
─────────────────────────────────────────────────────
  初始资金:     ${result.initial_capital:,.2f}
  最终资金:     ${result.final_capital:,.2f}
  总收益率:     {result.total_return:+.2f}%
  夏普比率:     {result.sharpe_ratio:.4f}

⚠️ 风险指标
─────────────────────────────────────────────────────
  最大回撤:     {result.max_drawdown:.2f}%
  盈利因子:     {result.profit_factor:.2f}

📈 交易统计
─────────────────────────────────────────────────────
  总交易次数:   {result.total_trades}
  盈利次数:     {result.winning_trades}
  亏损次数:     {result.losing_trades}
  胜率:         {result.win_rate:.2f}%
  平均盈利:     ${result.avg_win:,.2f}
  平均亏损:     ${result.avg_loss:,.2f}

"""
        
        if monte_carlo:
            fc = monte_carlo['final_capital']
            dd = monte_carlo['max_drawdown']
            report += f"""
🎲 蒙特卡洛压力测试 (n={monte_carlo['n_simulations']})
─────────────────────────────────────────────────────
  最终资金:
    均值:       ${fc['mean']:,.2f}
    中位数:     ${fc['median']:,.2f}
    标准差:     ${fc['std']:,.2f}
    5%分位数:   ${fc['percentile_5']:,.2f}
    95%分位数:  ${fc['percentile_95']:,.2f}
  
  最大回撤:
    均值:       {dd['mean']:.2f}%
    95%分位数:  {dd['percentile_95']:.2f}%
  
  存活率:       {monte_carlo['survival_rate']:.1f}%

"""
        
        report += """═══════════════════════════════════════════════════════
"""
        
        return report


def main():
    """命令行回测入口"""
    parser = argparse.ArgumentParser(description='CC Invest 回测系统')
    parser.add_argument('--symbol', default='BTCUSDT', help='交易对')
    parser.add_argument('--strategy', default='mean_reversion', 
                        choices=['mean_reversion', 'trend_following', 'rsi'],
                        help='策略名称')
    parser.add_argument('--start', default='2023-01-01', help='开始日期')
    parser.add_argument('--end', default='2024-01-01', help='结束日期')
    parser.add_argument('--capital', type=float, default=10000, help='初始资金')
    parser.add_argument('--commission', type=float, default=0.001, help='手续费率')
    parser.add_argument('--engine', default='backtrader', 
                        choices=['backtrader', 'vectorbt'],
                        help='回测引擎')
    parser.add_argument('--monte-carlo', type=int, default=100, help='蒙特卡洛模拟次数')
    parser.add_argument('--save', action='store_true', help='保存结果到数据库')
    
    args = parser.parse_args()
    
    # 初始化回测引擎
    engine = BacktestEngine()
    
    # 运行回测
    if args.engine == 'backtrader':
        result = engine.run_backtrader_backtest(
            symbol=args.symbol,
            strategy_name=args.strategy,
            start_date=args.start,
            end_date=args.end,
            initial_capital=args.capital,
            commission=args.commission
        )
    else:
        result = engine.run_vectorbt_backtest(
            symbol=args.symbol,
            strategy_name=args.strategy,
            start_date=args.start,
            end_date=args.end,
            initial_capital=args.capital,
            commission=args.commission
        )
    
    # 蒙特卡洛测试
    monte_carlo = None
    if args.monte_carlo > 0:
        monte_carlo = engine.run_monte_carlo(result, args.monte_carlo)
    
    # 生成报告
    report = engine.generate_report(result, monte_carlo)
    print(report)
    
    # 保存结果
    if args.save:
        engine.save_result(result, args.strategy, args.symbol, args.start, args.end)


if __name__ == "__main__":
    main()
