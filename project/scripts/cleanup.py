#!/usr/bin/env python3
"""数据清理脚本 - 清理旧数据"""
import sqlite3
import argparse
from datetime import datetime, timedelta

DB_PATH = "data/ccinvest.db"

def cleanup(days: int = 90):
    """清理指定天数前的数据"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    cutoff = datetime.utcnow() - timedelta(days=days)
    
    # 清理 ohlc_data
    cur.execute("DELETE FROM ohlc_data WHERE timestamp < ?", (cutoff,))
    ohlc_deleted = cur.rowcount
    
    # 清理 market_data
    cur.execute("DELETE FROM market_data WHERE timestamp < ?", (cutoff,))
    market_deleted = cur.rowcount
    
    # 清理日志
    cur.execute("DELETE FROM risk_logs WHERE created_at < ?", (cutoff,))
    risk_deleted = cur.rowcount
    
    conn.commit()
    conn.close()
    
    print(f"已清理: ohlc_data={ohlc_deleted}, market_data={market_deleted}, risk_logs={risk_deleted}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90)
    args = parser.parse_args()
    cleanup(args.days)
