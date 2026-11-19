"""
FastAPI 入口。
- CORS
- 路由注册
- 启动时建表 + 拉起限价单撮合 + 从数据库恢复机器人
- 关闭时只 cancel 任务；DB 状态保留，下次启动继续
"""
import asyncio
import logging

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import account, analysis, auth, bot, health, market, trade
from app.config import settings
from app.core.auth import require_auth, validate_auth_config
from app.models.db import init_db
from app.services.matching import limit_order_worker
from app.services.portfolio import equity_snapshot_worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("cryptosim")

app = FastAPI(
    title="Crypto Sim Backend",
    description="加密货币自动交易模拟系统 — 后端 API",
    version="1.2.0",
)

# ---------- CORS ----------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Routes ----------
app.include_router(health.router)   # /health 开放（探活）；/api/v1/config 在函数级单独验
app.include_router(auth.router)     # 登录接口本身开放（登录/状态/退出）
_protected = [Depends(require_auth)]
app.include_router(market.router, dependencies=_protected)
app.include_router(account.router, dependencies=_protected)
app.include_router(trade.router, dependencies=_protected)
app.include_router(bot.router, dependencies=_protected)
app.include_router(analysis.router, dependencies=_protected)


# ---------- Lifecycle ----------
@app.on_event("startup")
async def on_startup():
    validate_auth_config()  # REQUIRE_AUTH=1 但没配密码 → 直接起不来，不许裸奔
    from app.core.auth import auth_enabled
    if not auth_enabled():
        log.warning("⚠️ 登录验证未配置（本地模式）：所有接口不设防，切勿暴露到公网！部署请看 docs/部署方案.md")
    log.info("Initializing database at %s ...", settings.DB_PATH)
    init_db()
    log.info("Starting limit-order matching worker ...")
    asyncio.create_task(limit_order_worker(interval_sec=2.0))

    log.info("Starting equity-snapshot worker (every 60s) ...")
    asyncio.create_task(equity_snapshot_worker(interval_sec=60))

    # ★ 关键：从 SQLite 恢复运行中的机器人（重启 / 刷新都不丢）
    from app.services.bot import bot_manager
    try:
        restored = await bot_manager.resume_from_db()
        if restored:
            log.info("✓ 从数据库恢复了 %d 个机器人", restored)
        else:
            log.info("数据库中没有需要恢复的运行中机器人")
    except Exception as e:
        log.error("恢复机器人失败: %s", e)

    log.info("Backend ready. CORS origins: %s", settings.cors_origins_list)


@app.on_event("shutdown")
async def on_shutdown():
    """
    优雅关机：只取消异步 task，不改 DB 里的 status。
    这样下次启动时还能把这些机器人恢复回来。
    """
    from app.services.bot import bot_manager
    log.info("Shutdown: 取消运行中的机器人任务，DB 状态保留以便下次恢复...")
    bot_manager.cancel_tasks_preserve_status()


@app.get("/")
async def root():
    _idx = _Path(__file__).resolve().parents[2] / "frontend" / "dist" / "index.html"
    import os as _os2
    _env_dist = _os2.environ.get("FRONTEND_DIST")
    if _env_dist:
        _idx = _Path(_env_dist) / "index.html"
    if _idx.is_file():
        from fastapi.responses import FileResponse as _FR
        return _FR(_idx)
    return {
        "name": "Crypto Sim Backend",
        "version": "1.2.0",
        "docs": "/docs",
        "health": "/health",
    }


# ---------- 静态前端（部署形态：单服务） ----------
# 若 frontend/dist 存在（Docker 构建或手动 npm run build 后），后端直接托管前端，
# 一个进程一个端口搞定部署：API 与页面同源，Cookie/CORS 都最简单。
# 本地开发（分别跑 Vite 与后端）时 dist 不存在，这段自动跳过，行为不变。
import os as _os
from pathlib import Path as _Path

from fastapi import HTTPException as _HTTPException
from fastapi.responses import FileResponse as _FileResponse
from fastapi.staticfiles import StaticFiles as _StaticFiles

_FRONTEND_DIST = _Path(_os.environ.get(
    "FRONTEND_DIST",
    _Path(__file__).resolve().parents[2] / "frontend" / "dist",
))
if _FRONTEND_DIST.is_dir():
    log.info("Serving frontend from %s", _FRONTEND_DIST)
    _assets_dir = _FRONTEND_DIST / "assets"
    if _assets_dir.is_dir():
        app.mount("/assets", _StaticFiles(directory=_assets_dir), name="assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        # 后端自己的路径不走 SPA 回退
        if full_path.startswith(("api/", "health", "docs", "openapi.json", "redoc")):
            raise _HTTPException(status_code=404)
        candidate = _FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return _FileResponse(candidate)
        return _FileResponse(_FRONTEND_DIST / "index.html")


