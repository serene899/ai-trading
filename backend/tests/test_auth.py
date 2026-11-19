"""
登录验证测试（v1.2.0 新增）。

- 纯函数：密码哈希/校验、会话令牌签发/校验（含篡改与过期）。
- 配置校验：REQUIRE_AUTH=1 但没配密码时必须拒绝启动（fail-closed）。
- 全流程（子进程，环境变量注入测试密码）：未登录 401 → 错密码 401 →
  正确登录 200 → 带 Cookie 访问业务接口 200 → 退出后 401 → 连续错 5 次锁定 429。

运行方式同 test_trading.py：pytest tests -q
"""
import os
import subprocess
import sys
import tempfile
import textwrap

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

from app.core import auth  # noqa: E402


def test_password_hash_roundtrip():
    h = auth.hash_password("correct horse battery")
    assert auth.verify_password("correct horse battery", h)
    assert not auth.verify_password("wrong password", h)
    assert not auth.verify_password("correct horse battery", "garbage")
    # 同一密码两次哈希不同（随机盐）
    assert auth.hash_password("correct horse battery") != h


def test_session_token_roundtrip_and_tamper():
    tok = auth.make_session_token("s3cret", days=1)
    assert auth.verify_session_token(tok, "s3cret")
    assert not auth.verify_session_token(tok, "other-secret")
    assert not auth.verify_session_token(tok + "x", "s3cret")
    assert not auth.verify_session_token(None, "s3cret")
    expired = auth.make_session_token("s3cret", days=-1)
    assert not auth.verify_session_token(expired, "s3cret")


def test_validate_auth_config_fail_closed(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "REQUIRE_AUTH", True)
    monkeypatch.setattr(settings, "AUTH_PASSWORD_HASH", "")
    monkeypatch.setattr(settings, "SESSION_SECRET", "")
    try:
        auth.validate_auth_config()
        raise AssertionError("REQUIRE_AUTH 且未配密码时应当抛错")
    except RuntimeError:
        pass
    monkeypatch.setattr(settings, "AUTH_PASSWORD_HASH", "x")
    monkeypatch.setattr(settings, "SESSION_SECRET", "y")
    auth.validate_auth_config()  # 配好后不抛


def test_auth_flow_subprocess():
    tmp = tempfile.mkdtemp(prefix="ai-trading-auth-")
    db = os.path.join(tmp, "auth.db")
    pw_hash = auth.hash_password("test-pass-123")
    helper = textwrap.dedent(f"""
        import os, sys
        os.environ["DB_PATH"] = r"{db}"
        os.environ["AUTH_PASSWORD_HASH"] = r"{pw_hash}"
        os.environ["SESSION_SECRET"] = "test-session-secret"
        os.environ["SLIPPAGE_PCT"] = "0"
        sys.path.insert(0, r"{BACKEND_DIR}")
        from fastapi.testclient import TestClient
        from app.main import app

        with TestClient(app) as c:
            # 状态：验证开启、未登录
            d = c.get("/api/v1/auth/status").json()["data"]
            assert d == {{"auth_enabled": True, "authenticated": False}}, d
            # 未登录访问业务接口 → 401
            assert c.get("/api/v1/account").status_code == 401
            assert c.get("/api/v1/analysis", params={{"symbol": "BTC-USDT"}}).status_code == 401
            assert c.get("/api/v1/config").status_code == 401
            # /health 仍开放且标明验证已开启
            h = c.get("/health").json()
            assert h["status"] == "ok" and h["auth_enabled"] is True and h["version"] == "1.2.0"
            # 错密码 → 401
            assert c.post("/api/v1/auth/login", json={{"password": "nope-nope"}}).status_code == 401
            # 正确密码 → 200，之后业务接口放行
            r = c.post("/api/v1/auth/login", json={{"password": "test-pass-123"}})
            assert r.status_code == 200, r.text
            assert c.get("/api/v1/account").status_code == 200
            d = c.get("/api/v1/auth/status").json()["data"]
            assert d["authenticated"] is True
            # 退出 → 业务接口重新 401
            assert c.post("/api/v1/auth/logout").status_code == 200
            assert c.get("/api/v1/account").status_code == 401
            # 连续错 5 次后锁定：即使密码正确也 429
            for _ in range(5):
                c.post("/api/v1/auth/login", json={{"password": "bad-bad-bad"}})
            r = c.post("/api/v1/auth/login", json={{"password": "test-pass-123"}})
            assert r.status_code == 429, r.status_code
        print("AUTH FLOW PASS")
    """)
    out = subprocess.run([sys.executable, "-c", helper], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert "AUTH FLOW PASS" in out.stdout


def test_plain_password_env_fallback(monkeypatch):
    """只配 AUTH_PASSWORD（明文）时验证同样开启，且能校验密码。"""
    from app.config import settings
    monkeypatch.setattr(settings, "AUTH_PASSWORD_HASH", "")
    monkeypatch.setattr(settings, "AUTH_PASSWORD", "plain-pass-456")
    monkeypatch.setattr(settings, "SESSION_SECRET", "abc")
    assert auth.auth_enabled()
    eff = auth.effective_password_hash()
    assert auth.verify_password("plain-pass-456", eff)
    assert not auth.verify_password("nope", eff)
