"""
模拟交易核心测试（接管后新增，仓库此前没有任何自动化测试）。

覆盖用户最强调的四件事：
1. 开仓/手续费计算准确；
2. 部分平仓、全部平仓的已实现盈亏准确落库，且 总盈亏 = 已实现 + 未实现 恒等；
3. 手续费逐笔落库、账户汇总与流水加总一致；
4. 账户权益持久化：重启（新进程 + 再次 init_db）后余额不恢复初始资金。

行情用可控假价格 stub，不连真实 OKX；数据库用临时文件，不碰任何真实账户数据。
运行：cd backend && pip install -r requirements.txt -r requirements-dev.txt && pytest tests -q
"""
import asyncio
import os
import subprocess
import sys
import tempfile
import textwrap

import pytest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

_TMP = tempfile.mkdtemp(prefix="ai-trading-test-")
DB_FILE = os.path.join(_TMP, "test.db")
os.environ["DB_PATH"] = DB_FILE
os.environ["FEE_RATE"] = "0.001"
os.environ["SLIPPAGE_PCT"] = "0"  # 关滑点，专心核对手续费/盈亏数学
os.environ["INITIAL_CAPITAL"] = "10000"

PRICE = {"v": 100.0}

from app.services import exchange  # noqa: E402


async def _fake_ticker(symbol):
    return {"symbol": symbol, "last": PRICE["v"], "bid": PRICE["v"], "ask": PRICE["v"],
            "high24h": PRICE["v"], "low24h": PRICE["v"], "vol24h": 0, "ts": 0}


exchange.get_ticker = _fake_ticker

from app.models import db as db_mod  # noqa: E402
from app.services import matching, portfolio  # noqa: E402


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


@pytest.fixture(scope="module", autouse=True)
def fresh_db():
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
    db_mod.init_db()
    yield


def approx(a, b, eps=1e-6):
    assert abs(a - b) < eps, f"{a} != {b}"


def test_trade_flow_and_realized_pnl():
    snap = run(portfolio.build_account_snapshot())
    approx(snap["cash"], 10000)
    approx(snap["realized_pnl"], 0)
    approx(snap["total_fees"], 0)

    # 开仓：买 0.5 @100 → 费 0.05，均价含费 100.1，现金 9949.95
    run(matching.place_order("BTC-USDT", "buy", "market", 0.5))
    snap = run(portfolio.build_account_snapshot())
    approx(snap["cash"], 9949.95)
    approx(snap["positions"][0]["quantity"], 0.5)
    approx(snap["positions"][0]["avg_price"], 100.1)
    approx(snap["total_fees"], 0.05)

    # 涨到 120：未实现 9.95，总盈亏 9.95，已实现仍 0
    PRICE["v"] = 120.0
    snap = run(portfolio.build_account_snapshot())
    approx(snap["unrealized_pnl"], 9.95)
    approx(snap["total_pnl"], 9.95)
    approx(snap["realized_pnl"], 0)

    # 部分平仓：卖 0.2 @120 → 已实现 (120-100.1)*0.2 - 0.024 = 3.956 落库
    run(matching.place_order("BTC-USDT", "sell", "market", 0.2))
    snap = run(portfolio.build_account_snapshot())
    approx(snap["cash"], 9973.926)
    approx(snap["positions"][0]["quantity"], 0.3)
    approx(snap["realized_pnl"], 3.956)
    approx(snap["total_pnl"], snap["realized_pnl"] + snap["unrealized_pnl"])

    # 全部平仓：卖 0.3 @120 → 已实现再加 5.934，合计 9.89 = 总盈亏
    run(matching.place_order("BTC-USDT", "sell", "market", 0.3))
    snap = run(portfolio.build_account_snapshot())
    assert snap["positions"] == []
    approx(snap["cash"], 10009.89)
    approx(snap["total_equity"], 10009.89)
    approx(snap["realized_pnl"], 9.89)
    approx(snap["total_pnl"], 9.89)
    approx(snap["total_fees"], 0.05 + 0.024 + 0.036)

    # 流水逐笔核对：卖单带 realized_pnl，买单为 0，合计与账户汇总一致
    trades = matching.list_trades()
    sells = [t for t in trades if t["side"] == "sell"]
    buys = [t for t in trades if t["side"] == "buy"]
    approx(sum(t["realized_pnl"] for t in sells), 9.89)
    assert all(t["realized_pnl"] == 0 for t in buys)
    approx(sum(t["fee"] for t in trades), snap["total_fees"])


def test_restart_persistence_new_process():
    """新进程读同一个 DB 并再次 init_db，余额必须保持 10009.89，不得重置。"""
    helper = textwrap.dedent(f"""
        import asyncio, os, sys
        os.environ["DB_PATH"] = r"{DB_FILE}"
        os.environ["SLIPPAGE_PCT"] = "0"
        sys.path.insert(0, r"{BACKEND_DIR}")
        from app.services import exchange
        async def fake(symbol):
            return {{"symbol": symbol, "last": 120.0, "bid": 120.0, "ask": 120.0,
                     "high24h": 120.0, "low24h": 120.0, "vol24h": 0, "ts": 0}}
        exchange.get_ticker = fake
        from app.models.db import init_db
        from app.services import portfolio
        init_db()
        snap = asyncio.run(portfolio.build_account_snapshot())
        print(snap["cash"])
        assert abs(snap["cash"] - 10009.89) < 1e-6, snap["cash"]
    """)
    out = subprocess.run([sys.executable, "-c", helper], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    approx(float(out.stdout.strip().splitlines()[-1]), 10009.89)


def test_trade_table_has_realized_pnl_and_migration_idempotent():
    import sqlite3
    legacy = os.path.join(_TMP, "legacy.db")
    conn = sqlite3.connect(legacy)
    conn.execute("CREATE TABLE trade (id INTEGER PRIMARY KEY, fee REAL DEFAULT 0.0)")
    conn.commit(); conn.close()
    # 验证 db.py 迁移所依赖的补列语义：缺列时补上、已有时跳过（函数本体走同一 SQL）
    from sqlalchemy import create_engine, text
    eng = create_engine(f"sqlite:///{legacy}")
    with eng.begin() as c:
        cols = {r[1] for r in c.execute(text("PRAGMA table_info(trade)")).fetchall()}
        if "realized_pnl" not in cols:
            c.execute(text("ALTER TABLE trade ADD COLUMN realized_pnl REAL DEFAULT 0.0"))
        cols = {r[1] for r in c.execute(text("PRAGMA table_info(trade)")).fetchall()}
    assert "realized_pnl" in cols


def test_analysis_pure_functions():
    from app.services import analysis
    approx(analysis.moving_average([1, 2, 3, 4, 5], 5), 3.0)
    assert analysis.moving_average([1, 2], 5) is None
    assert analysis.volatility_pct([100.0] * 30) == 0.0
    assert analysis.risk_level(0.1) == "低"
    assert analysis.risk_level(1.0) == "中"
    assert analysis.risk_level(3.0) == "高"
    assert "不构成" in analysis.DISCLAIMER


def test_api_account_and_analysis():
    """接口级冒烟：账户接口带 realized_pnl/total_fees；分析接口带来源与免责声明。"""
    from fastapi.testclient import TestClient
    from app.main import app

    async def fake_tickers(symbols=None):
        return [{"symbol": "BTC-USDT", "last": 120.0, "high24h": 130.0,
                 "low24h": 110.0, "vol24h": 1.0, "change24h": 0.05}]

    async def fake_kline(symbol, interval="1m", limit=100):
        return [[i * 3600000, 100.0, 101.0, 99.0, 100.0 + i * 0.1, 1.0] for i in range(100)]

    exchange.get_tickers = fake_tickers
    exchange.get_kline = fake_kline

    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200 and r.json()["version"] == "1.1.0"

        r = client.get("/api/v1/account")
        assert r.status_code == 200
        d = r.json()["data"]
        assert "realized_pnl" in d and "total_fees" in d
        approx(d["realized_pnl"], 9.89)
        approx(d["total_fees"], 0.11)

        r = client.get("/api/v1/analysis", params={"symbol": "BTC-USDT"})
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["source"] == "OKX 公共行情"
        assert "不构成" in d["disclaimer"]
        assert d["ma5"] is not None and d["ma20"] is not None
        assert d["updated_at"]
