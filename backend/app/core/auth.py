"""
单用户登录验证（v1.2.0，公网部署标准）。

设计（个人单用户系统，不做多用户/注册/OAuth）：
- 密码只存哈希：PBKDF2-HMAC-SHA256（60 万次迭代，随机盐），哈希串放在环境变量
  AUTH_PASSWORD_HASH，永不进仓库。用 backend/hash_password.py 生成。
- 会话：登录成功后发 httpOnly Cookie，内容是 HMAC-SHA256 签名的过期时间戳，
  签名密钥在环境变量 SESSION_SECRET。无服务端会话表，重启不掉线（有效期内）。
- 登录限流：同一 IP 连续失败 5 次锁定 5 分钟（内存计数，个人系统够用）。
- 开关逻辑：
  * AUTH_PASSWORD_HASH 与 SESSION_SECRET 都配置 → 验证开启；
  * 都没配置 → 本地模式（不拦），启动日志会打醒目警告，/health 与状态接口会标明；
  * REQUIRE_AUTH=1（部署时设置）但验证未配置 → 启动直接失败（fail-closed，
    宁可起不来，也不能裸奔上公网）。
"""
import base64
import hashlib
import hmac
import time
from typing import Optional

from fastapi import HTTPException, Request

from app.config import settings

COOKIE_NAME = "cs_session"
_PBKDF2_ITERATIONS = 600_000

# 登录限流：ip -> (失败次数, 锁定截止时间戳)
_login_fails: dict[str, tuple[int, float]] = {}
_MAX_FAILS = 5
_LOCK_SECONDS = 300


# ---------- 密码哈希（纯函数，可单测） ----------

def hash_password(password: str) -> str:
    """生成 pbkdf2_sha256$迭代$盐$哈希 格式的密码哈希串。"""
    import os
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        _PBKDF2_ITERATIONS,
        base64.b64encode(salt).decode(),
        base64.b64encode(dk).decode(),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algo, iters, salt_b64, hash_b64 = encoded.split("$")
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iters))
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


# ---------- 会话令牌（纯函数，可单测） ----------

def make_session_token(secret: str, days: int = 7) -> str:
    exp = int(time.time()) + days * 86400
    payload = str(exp)
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_session_token(token: Optional[str], secret: str) -> bool:
    if not token or "." not in token:
        return False
    payload, _, sig = token.partition(".")
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        return int(payload) > int(time.time())
    except ValueError:
        return False


# ---------- 开关与校验 ----------

_plain_hash_cache: tuple[str, str] | None = None


def effective_password_hash() -> str:
    """实际生效的密码哈希。

    优先 AUTH_PASSWORD_HASH（推荐）；若只配了 AUTH_PASSWORD（明文环境变量，
    方便在手机上完成云平台部署时填写），启动后在内存中哈希使用，不落盘。
    平台环境变量本身是私密配置，对个人单用户系统这是可接受的次选。
    """
    global _plain_hash_cache
    if settings.AUTH_PASSWORD_HASH:
        return settings.AUTH_PASSWORD_HASH
    if settings.AUTH_PASSWORD:
        if _plain_hash_cache is None or _plain_hash_cache[0] != settings.AUTH_PASSWORD:
            _plain_hash_cache = (settings.AUTH_PASSWORD, hash_password(settings.AUTH_PASSWORD))
        return _plain_hash_cache[1]
    return ""


def auth_enabled() -> bool:
    return bool(effective_password_hash() and settings.SESSION_SECRET)


def validate_auth_config() -> None:
    """启动时调用：REQUIRE_AUTH=1 但验证没配好 → 直接失败，不许裸奔。"""
    if settings.REQUIRE_AUTH and not auth_enabled():
        raise RuntimeError(
            "REQUIRE_AUTH=1 但密码（AUTH_PASSWORD_HASH 或 AUTH_PASSWORD）/ SESSION_SECRET 未配置，"
            "拒绝启动。生成哈希见 backend/hash_password.py，或先用 AUTH_PASSWORD 部署。"
        )


# ---------- 登录限流 ----------

def check_login_throttle(ip: str) -> None:
    fails, locked_until = _login_fails.get(ip, (0, 0.0))
    if locked_until > time.time():
        raise HTTPException(status_code=429, detail="登录失败次数过多，请 5 分钟后再试")


def record_login_failure(ip: str) -> None:
    fails, _ = _login_fails.get(ip, (0, 0.0))
    fails += 1
    locked_until = time.time() + _LOCK_SECONDS if fails >= _MAX_FAILS else 0.0
    _login_fails[ip] = (fails, locked_until)


def record_login_success(ip: str) -> None:
    _login_fails.pop(ip, None)


# ---------- FastAPI 依赖 ----------

async def require_auth(request: Request) -> None:
    """保护业务接口：验证开启时，没有效会话一律 401。本地模式（未配置）放行。"""
    if not auth_enabled():
        return
    token = request.cookies.get(COOKIE_NAME)
    if not verify_session_token(token, settings.SESSION_SECRET):
        raise HTTPException(status_code=401, detail="未登录或会话已过期")
