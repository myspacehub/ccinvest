# =====================================================
# CC Invest - 主程序入口
# 一键启动数据采集、回测、模拟交易
# =====================================================

import os
import sys
import time
import signal
import asyncio
import schedule
from datetime import datetime
from pathlib import Path
from typing import List, Optional
import threading

from dotenv import load_dotenv
from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm
import click

# 加载配置
load_dotenv()

console = Console()


def iter_sql_statements(sql: str):
    """按语句切分 SQL，并忽略整行注释。"""
    cleaned_lines = []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        cleaned_lines.append(line)
    
    for statement in "\n".join(cleaned_lines).split(";"):
        statement = statement.strip()
        if statement:
            yield statement

# =====================================================
# 全局配置
# =====================================================

class Config:
    """全局配置"""
    PROJECT_DIR = Path(__file__).parent
    DATA_DIR = PROJECT_DIR / "data"
    LOGS_DIR = PROJECT_DIR / "logs"
    SKILLS_DIR = PROJECT_DIR / "skills"
    
    # 确保目录存在
    DATA_DIR.mkdir(exist_ok=True)
    LOGS_DIR.mkdir(exist_ok=True)
    
    # 日志配置
    LOG_FILE = LOGS_DIR / f"ccinvest_{datetime.now().strftime('%Y%m%d')}.log"
    
    # 数据库
    DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR}/ccinvest.db")
    
    # 交易配置
    TRADING_MODE = os.getenv("TRADING_MODE", "paper")
    INITIAL_BALANCE = float(os.getenv("INITIAL_CAPITAL", "10000"))
    
    # 风控参数
    MAX_POSITION_SIZE = float(os.getenv("MAX_POSITION_SIZE", "0.02"))
    MAX_DAILY_LOSS = float(os.getenv("MAX_DAILY_LOSS", "1000"))
    
    # 数据采集
    COLLECTION_INTERVAL = int(os.getenv("DATA_COLLECTION_INTERVAL", "300"))


# 配置日志
logger.add(
    Config.LOG_FILE,
    rotation="100 MB",
    retention="30 days",
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}"
)

# =====================================================
# 服务管理
# =====================================================

class ServiceManager:
    """服务管理器"""
    
    def __init__(self):
        self.running = False
        self.services = {}
        
        # 信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """信号处理"""
        console.print("\n[bold yellow]接收到停止信号，正在关闭服务...[/bold yellow]")
        self.stop()
        sys.exit(0)
    
    def start_data_collector(self, interval: int = None):
        """启动数据采集服务"""
        interval = interval or Config.COLLECTION_INTERVAL
        
        def run_collector():
            from src.collector import DataCollector
            collector = DataCollector(Config.DATABASE_URL)
            
            while self.running:
                try:
                    logger.info("执行数据采集")
                    collector.collect_all()
                except Exception as e:
                    logger.error(f"数据采集失败: {e}")
                
                # 等待下次采集
                time.sleep(interval)
        
        thread = threading.Thread(target=run_collector, daemon=True)
        thread.start()
        self.services['collector'] = thread
        logger.info(f"数据采集服务已启动 (间隔: {interval}秒)")
    
    def start_simulator(self, mode: str = None):
        """启动模拟交易引擎"""
        mode = mode or Config.TRADING_MODE
        
        def run_simulator():
            from src.simulator import SimulatorEngine
            simulator = SimulatorEngine(
                database_url=Config.DATABASE_URL,
                trading_mode=mode,
                initial_balance=Config.INITIAL_BALANCE
            )
            
            symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
            simulator.run_live_mode(symbols, interval=5)
        
        thread = threading.Thread(target=run_simulator, daemon=True)
        thread.start()
        self.services['simulator'] = thread
        logger.info(f"模拟交易引擎已启动 (模式: {mode})")
    
    def start_webhook_server(self):
        """启动 Webhook 服务"""
        def run_server():
            import uvicorn
            from src.webhook_server import app
            
            uvicorn.run(
                app,
                host="0.0.0.0",
                port=10000,
                log_level="info"
            )
        
        thread = threading.Thread(target=run_server, daemon=True)
        thread.start()
        self.services['webhook'] = thread
        logger.info("Webhook 服务已启动 (端口: 10000)")
    
    def stop(self):
        """停止所有服务"""
        self.running = False
        for name, service in self.services.items():
            logger.info(f"停止服务: {name}")
        self.services.clear()
    
    def status(self) -> Table:
        """显示服务状态"""
        table = Table(title="🔧 服务状态")
        table.add_column("服务", style="cyan")
        table.add_column("状态", style="green")
        table.add_column("说明", style="white")
        
        services_status = {
            'collector': ('数据采集', '定期采集市场数据'),
            'simulator': ('模拟交易', '执行模拟订单'),
            'webhook': ('Webhook', 'API 接口服务')
        }
        
        for name, (display_name, desc) in services_status.items():
            status = "[green]运行中[/green]" if name in self.services else "[gray]未启动[/gray]"
            table.add_row(display_name, status, desc)
        
        return table


# =====================================================
# 命令行界面
# =====================================================

@click.group()
@click.version_option(version="1.0.0")
def cli():
    """🚀 CC Invest - 加密货币投资系统
    
    支持技术分析、回测、模拟交易
    """
    pass

@cli.command()
def init():
    """初始化项目环境和数据库"""
    console.print(Panel.fit(
        "[bold cyan]CC Invest 项目初始化[/bold cyan]\n\n"
        "正在创建目录结构和数据库...",
        title="初始化"
    ))
    
    # 创建目录
    for directory in [Config.DATA_DIR, Config.LOGS_DIR, Config.SKILLS_DIR]:
        directory.mkdir(parents=True, exist_ok=True)
        console.print(f"✓ 创建目录: {directory}")
    
    # 初始化数据库
    from sqlalchemy import create_engine, text
    engine = create_engine(Config.DATABASE_URL)
    
    # 读取并执行 SQL
    sql_file = Config.PROJECT_DIR / "migrations" / "001_initial_schema.sql"
    if sql_file.exists():
        with open(sql_file, 'r') as f:
            sql = f.read()
        
        with engine.connect() as conn:
            # SQLite 兼容性处理
            for statement in iter_sql_statements(sql):
                try:
                    conn.execute(text(statement))
                except Exception as e:
                    if "already exists" not in str(e):
                        logger.warning(f"SQL 执行警告: {e}")
            conn.commit()
        
        console.print(f"✓ 数据库初始化完成: {Config.DATABASE_URL}")
    else:
        console.print(f"[yellow]⚠ SQL 文件不存在，跳过数据库初始化[/yellow]")
    
    console.print("[bold green]✓ 初始化完成![/bold green]")

@cli.command()
@click.option('--symbols', '-s', default='BTCUSDT,ETHUSDT,BNBUSDT', help='交易对列表')
def collect(symbols: str):
    """采集市场数据"""
    symbol_list = [s.strip() for s in symbols.split(',')]
    
    console.print(f"[cyan]开始采集数据: {symbol_list}[/cyan]")
    
    from src.collector import DataCollector
    collector = DataCollector(Config.DATABASE_URL)
    collector.collect_all()
    
    console.print("[bold green]✓ 数据采集完成[/bold green]")

@cli.command()
@click.option('--symbol', '-s', default='BTCUSDT', help='交易对')
@click.option('--strategy', '-t', default='mean_reversion', 
              type=click.Choice(['mean_reversion', 'trend_following', 'rsi']),
              help='交易策略')
@click.option('--start', default='2023-01-01', help='开始日期')
@click.option('--end', default='2024-01-01', help='结束日期')
@click.option('--capital', default=10000.0, help='初始资金')
@click.option('--monte-carlo', '-m', default=0, help='蒙特卡洛模拟次数')
def backtest(symbol: str, strategy: str, start: str, end: str, capital: float, monte_carlo: int):
    """运行策略回测"""
    console.print(Panel.fit(
        f"[bold cyan]策略回测[/bold cyan]\n\n"
        f"交易对: {symbol}\n"
        f"策略: {strategy}\n"
        f"周期: {start} ~ {end}",
        title="回测"
    ))
    
    from src.backtest import BacktestEngine
    engine = BacktestEngine(Config.DATABASE_URL)
    
    result = engine.run_backtrader_backtest(
        symbol=symbol,
        strategy_name=strategy,
        start_date=start,
        end_date=end,
        initial_capital=capital
    )
    
    # 蒙特卡洛测试
    mc_result = None
    if monte_carlo > 0:
        mc_result = engine.run_monte_carlo(result, monte_carlo)
    
    # 显示报告
    report = engine.generate_report(result, mc_result)
    console.print(Panel(report, title="回测报告"))

@cli.command()
@click.option('--mode', '-m', default='paper', type=click.Choice(['paper', 'live']), help='交易模式')
def trade(mode: str):
    """启动模拟交易引擎"""
    console.print(Panel.fit(
        f"[bold green]模拟交易引擎[/bold green]\n\n"
        f"模式: {mode}\n"
        f"初始资金: ${Config.INITIAL_BALANCE:,.2f}",
        title="交易"
    ))
    
    from src.simulator import SimulatorEngine
    simulator = SimulatorEngine(
        database_url=Config.DATABASE_URL,
        trading_mode=mode,
        initial_balance=Config.INITIAL_BALANCE
    )
    
    symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
    simulator.run_live_mode(symbols, interval=5)

@cli.command()
def webhook():
    """启动 Webhook API 服务"""
    console.print(Panel.fit(
        "[bold yellow]Webhook API 服务[/bold yellow]\n\n"
        "监听端口: 10000\n"
        "API 文档: http://localhost:10000/docs",
        title="API"
    ))
    
    import uvicorn
    from src.webhook_server import app
    
    port = int(os.getenv("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")

@cli.command()
@click.option('--port', '-p', default=10000, help='端口')
def dashboard(port: int):
    """启动 Web 控制面板"""
    console.print(f"[cyan]启动控制面板...[/cyan] (端口: {port})")
    
    # 这里可以启动一个简单的 Web UI
    # 暂时使用 Swagger UI (通过 webhook 命令)
    import webbrowser
    import threading
    
    def open_browser():
        time.sleep(2)
        webbrowser.open(f"http://localhost:{port}/docs")
    
    threading.Thread(target=open_browser, daemon=True).start()
    
    import uvicorn
    from src.webhook_server import app
    
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")

@cli.command()
def status():
    """查看系统状态"""
    manager = ServiceManager()
    
    console.print(manager.status())
    
    # 显示账户信息
    try:
        from src.simulator import SimulatorEngine
        simulator = SimulatorEngine(database_url=Config.DATABASE_URL, trading_mode="paper", initial_balance=10000.0)
        
        console.print(Panel(
            f"[bold]余额:[/bold] ${simulator.account.balance:,.2f}\n"
            f"[bold]总盈亏:[/bold] ${simulator.account.total_pnl:,.2f}\n"
            f"[bold]交易次数:[/bold] {simulator.account.total_trades}",
            title="📊 账户状态"
        ))
        
        # 显示持仓
        positions = simulator.get_positions()
        if positions:
            table = Table(title="📈 当前持仓")
            table.add_column("交易对", style="cyan")
            table.add_column("数量", style="white")
            table.add_column("盈亏", style="green")
            
            for pos in positions:
                table.add_row(
                    pos["symbol"],
                    f"{pos['quantity']:.4f}",
                    f"${pos['unrealized_pnl']:,.2f}"
                )
            
            console.print(table)
            
    except Exception as e:
        console.print(f"[yellow]无法获取账户信息: {e}[/yellow]")

@cli.command()
def skills():
    """列出所有技能"""
    table = Table(title="📜 可用技能")
    table.add_column("名称", style="cyan")
    table.add_column("版本", style="white")
    table.add_column("描述", style="dim")
    
    skills_files = list(Config.SKILLS_DIR.glob("*.md"))
    
    if not skills_files:
        console.print("[yellow]⚠ 没有找到技能文件[/yellow]")
        return
    
    for skill_file in skills_files:
        name = skill_file.stem.replace("-", "_")
        # 简单解析版本
        version = "1.0.0"
        description = ""
        
        with open(skill_file, 'r') as f:
            content = f.read()
            if "version:" in content:
                import re
                match = re.search(r'version:\s*([\d.]+)', content)
                if match:
                    version = match.group(1)
        
        table.add_row(name, version, description)
    
    console.print(table)

@cli.command()
@click.confirmation_option(prompt='确定要启动完整系统吗？')
def start():
    """启动完整系统（数据采集 + 模拟交易 + Webhook）"""
    console.print(Panel.fit(
        "[bold green]🚀 启动完整系统[/bold green]\n\n"
        "• 数据采集服务\n"
        "• 模拟交易引擎\n"
        "• Webhook API\n"
        "• 风控模块",
        title="CC Invest"
    ))
    
    manager = ServiceManager()
    manager.running = True
    
    try:
        manager.start_data_collector()
        time.sleep(1)
        manager.start_simulator()
        time.sleep(1)
        manager.start_webhook_server()
        
        console.print(manager.status())
        
        console.print("\n[bold cyan]系统已启动，按 Ctrl+C 停止[/bold cyan]")
        
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        console.print("\n[bold yellow]正在停止系统...[/bold yellow]")
        manager.stop()

# =====================================================
# 主程序
# =====================================================

if __name__ == "__main__":
    cli()
