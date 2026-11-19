"""健康检查。"""
import time

from fastapi import APIRouter, Depends

from app.core.auth import require_auth
from app.core.response import ok
from app.core.time import iso_cn, now_utc

router = APIRouter()

_START_TS = time.time()
VERSION = "1.2.0"


@router.get("/health", tags=["system"])
async def health():
    from app.core.auth import auth_enabled
    return {
        "status": "ok",
        "auth_enabled": auth_enabled(),
        "timestamp": iso_cn(now_utc()),
        "timezone": "Asia/Shanghai (UTC+8)",
        "version": VERSION,
        "uptime_seconds": int(time.time() - _START_TS),
    }


@router.get("/api/v1/config", tags=["system"])
async def config(_: None = Depends(require_auth)):
    # 配置里虽无密钥，但含版本/交易对信息，验证开启时同样要登录
    from app.services.exchange import DEFAULT_SYMBOLS
    from app.config import settings
    return ok({
        "exchange": settings.EXCHANGE,
        "symbols": DEFAULT_SYMBOLS,
        "version": VERSION,
    })
