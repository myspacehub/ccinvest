# =====================================================
# CC Invest - 数据库初始化脚本
# 初始化数据库并插入示例数据
# =====================================================

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
from loguru import logger

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/ccinvest.db")


def init_database():
    """初始化数据库"""
    logger.info("开始初始化数据库...")
    
    engine = create_engine(DATABASE_URL)
    
    # 读取 SQL 文件
    sql_file = Path(__file__).parent.parent / "migrations" / "001_initial_schema.sql"
    
    with engine.connect() as conn:
        with open(sql_file, 'r') as f:
            sql = f.read()
        
        # 分割并执行 SQL 语句
        for statement in sql.split(';'):
            statement = statement.strip()
            if statement and not statement.startswith('--'):
                try:
                    conn.execute(text(statement))
                except Exception as e:
                    if "already exists" not in str(e):
                        logger.warning(f"SQL 执行警告: {e}")
        
        conn.commit()
    
    logger.info("✓ 数据库初始化完成")
    return engine


def insert_sample_data(engine):
    """插入示例数据"""
    logger.info("插入示例数据...")
    
    session = engine.connect()
    
    try:
        # 插入示例市场数据
        symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
        base_prices = {"BTCUSDT": 50000, "ETHUSDT": 3000, "BNBUSDT": 350}
        
        for symbol in symbols:
            price = base_prices.get(symbol, 1000)
            
            # 生成 100 条历史价格数据
            for i in range(100):
                timestamp = datetime.utcnow() - timedelta(hours=100-i)
                variation = np.random.uniform(-0.02, 0.02)
                current_price = price * (1 + variation)
                
                session.execute(text("""
                    INSERT INTO market_data (symbol, price, volume_24h, change_24h, high_24h, low_24h, timestamp, source)
                    VALUES (:symbol, :price, :volume, :change, :high, :low, :timestamp, :source)
                """), {
                    "symbol": symbol,
                    "price": current_price,
                    "volume": np.random.uniform(1000, 10000),
                    "change": np.random.uniform(-5, 5),
                    "high": current_price * 1.02,
                    "low": current_price * 0.98,
                    "timestamp": timestamp,
                    "source": "binance"
                })
        
        # 插入示例 K 线数据
        for symbol in symbols:
            price = base_prices.get(symbol, 1000)
            
            for i in range(200):
                timestamp = datetime.utcnow() - timedelta(hours=200-i)
                variation = np.random.uniform(-0.01, 0.01)
                open_price = price * (1 + variation)
                close_price = open_price * (1 + np.random.uniform(-0.005, 0.005))
                high_price = max(open_price, close_price) * 1.002
                low_price = min(open_price, close_price) * 0.998
                
                session.execute(text("""
                    INSERT INTO ohlc_data (symbol, timeframe, open_price, high_price, low_price, close_price, volume, timestamp)
                    VALUES (:symbol, '1h', :open, :high, :low, :close, :volume, :timestamp)
                """), {
                    "symbol": symbol,
                    "open": open_price,
                    "high": high_price,
                    "low": low_price,
                    "close": close_price,
                    "volume": np.random.uniform(100, 1000),
                    "timestamp": timestamp
                })
        
        session.commit()
        logger.info("✓ 示例数据插入完成")
        
    except Exception as e:
        logger.error(f"插入示例数据失败: {e}")
        session.rollback()
    finally:
        session.close()


def verify_data(engine):
    """验证数据"""
    logger.info("验证数据...")
    
    session = engine.connect()
    
    try:
        # 检查表记录数
        tables = ["market_data", "ohlc_data", "accounts"]
        
        for table in tables:
            result = session.execute(text(f"SELECT COUNT(*) as count FROM {table}")).fetchone()
            logger.info(f"  {table}: {result.count} 条记录")
        
        # 检查账户
        account = session.execute(text("SELECT * FROM accounts WHERE id = 1")).fetchone()
        if account:
            logger.info(f"  账户余额: ${account.balance:,.2f}")
        
        logger.info("✓ 数据验证完成")
        
    finally:
        session.close()


def main():
    """主函数"""
    # 初始化数据库
    engine = init_database()
    
    # 插入示例数据
    insert_sample_data(engine)
    
    # 验证数据
    verify_data(engine)
    
    logger.info("数据库初始化完成！")
    print("\n下一步：")
    print("  1. python main.py collect    # 采集实时数据")
    print("  2. python main.py backtest   # 运行回测")
    print("  3. python main.py trade      # 启动模拟交易")


if __name__ == "__main__":
    main()