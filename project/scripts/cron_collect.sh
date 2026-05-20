#!/bin/bash
# 数据采集定时任务 - 每5分钟执行
cd /Users/myworld/.openclaw/cc-invest/project
python3 main.py collect --symbols BTCUSDT,ETHUSDT >> logs/collect_cron.log 2>&1
