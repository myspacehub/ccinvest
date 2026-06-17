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

    def test_infer_asset_class_recognizes_new_crypto_symbols(self):
        """测试热门新代币不会被误判为美股"""
        from src.webhook_server import infer_asset_class

        for symbol in ["HYPE", "INJ", "TIA", "SUI"]:
            assert infer_asset_class(symbol, "auto") == "crypto"
    
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
    
    def test_price_endpoint_supports_us_equity_yahoo_fallback(self, monkeypatch):
        """测试美股价格接口走 Yahoo fallback 时不会触发缓存异常"""
        from fastapi.testclient import TestClient
        import requests
        import src.webhook_server as webhook_server
        
        class FakeResponse:
            def __init__(self, ok, payload):
                self.ok = ok
                self._payload = payload
            
            def json(self):
                return self._payload
        
        def fake_get(url, *args, **kwargs):
            if "query1.finance.yahoo.com" in url and "AAPL" in url:
                return FakeResponse(True, {
                    "chart": {
                        "result": [{
                            "meta": {
                                "regularMarketPrice": 210.0,
                                "previousClose": 200.0,
                                "regularMarketVolume": 50_000_000,
                                "regularMarketDayHigh": 212.0,
                                "regularMarketDayLow": 198.0,
                                "longName": "Apple Inc.",
                            }
                        }]
                    }
                })
            return FakeResponse(False, {})
        
        monkeypatch.setattr(webhook_server, "HAS_PRICE_FETCHER", False)
        monkeypatch.delattr(webhook_server.webhook_price, "_cache", raising=False)
        monkeypatch.setattr(requests, "get", fake_get)
        
        client = TestClient(webhook_server.app)
        response = client.get("/webhooks/price/AAPL")
        
        assert response.status_code == 200
        body = response.json()
        assert body["symbol"] == "AAPL"
        assert body["price"] == 210.0
        assert body["total_volume"] == 50_000_000
    
    def test_price_endpoint_uses_equity_history_when_quote_is_unavailable(self, monkeypatch):
        """测试美股报价不可用时使用日线 K 线生成价格卡片"""
        from fastapi.testclient import TestClient
        import requests
        import src.webhook_server as webhook_server
        
        class FakeResponse:
            ok = False
            
            def json(self):
                return {}
        
        monkeypatch.setattr(webhook_server, "HAS_PRICE_FETCHER", False)
        monkeypatch.delattr(webhook_server.webhook_price, "_cache", raising=False)
        monkeypatch.setattr(requests, "get", lambda *args, **kwargs: FakeResponse())
        monkeypatch.setattr(webhook_server, "fetch_yahoo_history", lambda symbol, interval, limit: [
            {"close": 200.0, "high": 202.0, "low": 198.0, "volume": 40_000_000},
            {"close": 210.0, "high": 212.0, "low": 205.0, "volume": 50_000_000},
        ])
        
        client = TestClient(webhook_server.app)
        response = client.get("/webhooks/price/AAPL?asset_class=us_equity")
        
        assert response.status_code == 200
        body = response.json()
        assert body["price"] == 210.0
        assert body["change_24h"] == 5.0
        assert body["source"] == "yahoo_finance"
        assert body["total_volume"] == 50_000_000


class TestStrategyEngine:
    """多资产策略引擎测试"""
    
    def test_waits_when_history_is_insufficient(self):
        """历史样本不足时必须拒绝给方向"""
        from src.strategy_engine import MultiAssetStrategyEngine
        
        rows = [
            {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000}
            for _ in range(20)
        ]
        signal = MultiAssetStrategyEngine().generate_signal(rows, "BTCUSDT", "crypto")
        
        assert signal["action"] == "WAIT_CONFIRMATION"
        assert signal["position_risk_pct"] == 0.0
    
    def test_crypto_trend_signal_is_conservative(self):
        """趋势充分但仍输出谨慎信号和风控参数"""
        from src.strategy_engine import MultiAssetStrategyEngine
        
        rows = []
        price = 100.0
        for i in range(140):
            price *= 1.003
            rows.append({
                "open": price * 0.995,
                "high": price * 1.01,
                "low": price * 0.99,
                "close": price,
                "volume": 1000 + i * 8,
            })
        
        signal = MultiAssetStrategyEngine().generate_signal(rows, "BTCUSDT", "crypto")
        
        assert signal["action"] in {"CAUTIOUS_LONG", "WAIT_CONFIRMATION"}
        assert "不是投资建议" in signal["disclaimer"]
        if signal["action"] == "CAUTIOUS_LONG":
            assert signal["stop_loss"] < rows[-1]["close"]
            assert signal["take_profit"] > rows[-1]["close"]
    
    def test_strategy_endpoint_supports_us_equity(self, monkeypatch):
        """策略接口支持美股资产类别，且不依赖外部网络"""
        from fastapi.testclient import TestClient
        import src.webhook_server as webhook_server
        
        rows = []
        price = 100.0
        for i in range(120):
            price *= 1.001
            rows.append({
                "time": f"2024-01-{(i % 28) + 1:02d}T00:00:00",
                "open": price * 0.998,
                "high": price * 1.006,
                "low": price * 0.994,
                "close": price,
                "volume": 1_000_000 + i * 10_000,
            })
        
        async def fake_load_history_rows(symbol, interval, limit):
            assert symbol == "AAPL"
            assert interval == "1d"
            return {
                "symbol": symbol,
                "interval": interval,
                "count": len(rows),
                "data": rows,
                "source": "unit_test",
            }
        
        monkeypatch.setattr(webhook_server, "load_history_rows", fake_load_history_rows)
        client = TestClient(webhook_server.app)
        
        response = client.get("/webhooks/strategy_signal/AAPL?asset_class=us_equity&interval=1d&limit=120")
        
        assert response.status_code == 200
        body = response.json()
        assert body["symbol"] == "AAPL"
        assert body["asset_class"] == "us_equity"
        assert body["data_source"] == "unit_test"
        assert body["action"] in {"CAUTIOUS_LONG", "RISK_OFF", "WAIT_CONFIRMATION"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
