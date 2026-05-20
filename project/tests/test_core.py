"""
CC Invest - 测试套件
"""
import pytest
import sys
from pathlib import Path
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestRiskManager:
    """风控模块测试"""
    
    def test_risk_config_defaults(self):
        """测试风控配置默认值"""
        from src.risk import RiskConfig
        config = RiskConfig()
        
        assert config.max_position_size == 0.02
        assert config.max_daily_loss == 1000.0
        assert config.max_drawdown == 0.05
    
    def test_order_request_validation(self):
        """测试订单请求验证"""
        from src.risk import OrderRequest
        
        order = OrderRequest(
            symbol="BTCUSDT",
            side="BUY",
            quantity=0.1,
            price=50000
        )
        
        assert order.symbol == "BTCUSDT"
        assert order.side == "BUY"
        assert order.quantity == 0.1


class TestDataCollector:
    """数据采集模块测试"""
    
    def test_symbol_list(self):
        """测试交易对列表"""
        from src.collector import DataCollector
        collector = DataCollector()
        
        assert "BTCUSDT" in collector.default_symbols
        assert "ETHUSDT" in collector.default_symbols


class TestSimulator:
    """模拟交易模块测试"""
    
    def test_order_id_generation(self):
        """测试订单 ID 生成"""
        from datetime import datetime
        import uuid
        
        order_id = f"SIM_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6].upper()}"
        
        assert order_id.startswith("SIM_")
        assert len(order_id) > 20
    
    def test_rejects_sell_without_position(self, tmp_path):
        """测试空仓卖出会被拒绝"""
        from src.simulator import SimulatorEngine
        
        db_url = f"sqlite:///{tmp_path / 'simulator.db'}"
        simulator = SimulatorEngine(database_url=db_url, initial_balance=10000)
        
        result = simulator.place_order("BTCUSDT", "SELL", 0.1)
        
        assert result["status"] == "rejected"
        assert "持仓不足" in result["reason"]
    
    def test_sell_does_not_double_count_pnl(self, tmp_path):
        """测试卖出后余额只增加成交收入，不重复叠加已实现盈亏"""
        from pytest import approx
        from src.simulator import SimulatorEngine
        
        db_url = f"sqlite:///{tmp_path / 'simulator.db'}"
        simulator = SimulatorEngine(database_url=db_url, initial_balance=10000)
        
        buy = simulator.place_order("BTCUSDT", "BUY", 0.001)
        sell = simulator.place_order("BTCUSDT", "SELL", 0.0005)
        
        assert buy["status"] == "filled"
        assert sell["status"] == "filled"
        assert simulator.account.balance == approx(9974.849975)
        assert simulator.account.total_pnl == approx(-0.05)


class TestCollector:
    """数据采集模块测试"""
    
    def test_save_ohlc_data_matches_schema(self, tmp_path):
        """测试 K 线保存字段与数据库表结构一致"""
        from src.simulator import SimulatorEngine
        from src.collector import DataCollector
        
        db_url = f"sqlite:///{tmp_path / 'collector.db'}"
        SimulatorEngine(database_url=db_url)
        collector = DataCollector(database_url=db_url)
        
        saved = collector.save_ohlc_data([{
            "symbol": "BTCUSDT",
            "timeframe": "1h",
            "open_time": datetime(2024, 1, 1),
            "open_price": 1,
            "high_price": 2,
            "low_price": 0.5,
            "close_price": 1.5,
            "volume": 100,
            "close_time": datetime(2024, 1, 1, 1),
            "quote_volume": 150,
        }])
        
        assert saved == 1


class TestWebhook:
    """Webhook 模块测试"""
    
    def test_signal_endpoint_uses_raw_request_for_signature(self, tmp_path, monkeypatch):
        """测试业务 payload 不会覆盖 FastAPI 原始请求对象"""
        from src.simulator import SimulatorEngine
        from fastapi.testclient import TestClient
        from src.webhook_server import app
        
        db_url = f"sqlite:///{tmp_path / 'webhook.db'}"
        monkeypatch.setenv("DATABASE_URL", db_url)
        SimulatorEngine(database_url=db_url)
        
        client = TestClient(app)
        response = client.post("/webhooks/signal", json={
            "symbol": "BTCUSDT",
            "strategy": "unit_test",
            "signal_type": "BUY",
        })
        
        assert response.status_code == 200
        assert response.json()["status"] == "recorded"
    
    def test_history_endpoint_returns_ohlc_data(self, monkeypatch):
        """测试历史 K 线接口返回前端需要的 OHLC 字段"""
        from datetime import datetime
        from fastapi.testclient import TestClient
        import src.collector
        from src.collector import DataValidationResult, DataQuality
        from src.webhook_server import app
        
        class FakeCollector:
            def fetch_ohlc(self, symbol, interval, limit):
                return ([{
                    "symbol": symbol,
                    "timeframe": interval,
                    "open_time": datetime(2024, 1, 1),
                    "open_price": 100.0,
                    "high_price": 110.0,
                    "low_price": 95.0,
                    "close_price": 105.0,
                    "volume": 1234.0,
                    "close_time": datetime(2024, 1, 2),
                    "quote_volume": 129570.0,
                }], DataValidationResult(True, DataQuality.EXCELLENT, 100))
            
            def save_ohlc_data(self, data):
                return len(data)
        
        monkeypatch.setattr(src.collector, "DataCollector", FakeCollector)
        
        client = TestClient(app)
        response = client.get("/webhooks/history/BTCUSDT?interval=1d&limit=10")
        
        assert response.status_code == 200
        body = response.json()
        assert body["symbol"] == "BTCUSDT"
        assert body["interval"] == "1d"
        assert body["data"][0]["open"] == 100.0
        assert body["data"][0]["close"] == 105.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
