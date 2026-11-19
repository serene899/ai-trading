"""登录接口：状态查询 / 登录 / 退出。本地模式（未配置密码）下状态接口如实标注。"""
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from app.config import settings
from app.core import auth
from app.core.response import ok

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginBody(BaseModel):
    password: str


@router.get("/status")
async def auth_status(request: Request):
    enabled = auth.auth_enabled()
    token = request.cookies.get(auth.COOKIE_NAME)
    authenticated = (not enabled) or auth.verify_session_token(token, settings.SESSION_SECRET)
    return ok({"auth_enabled": enabled, "authenticated": authenticated})


@router.post("/login")
async def login(body: LoginBody, request: Request, response: Response):
    if not auth.auth_enabled():
        # 本地模式没有密码可验，直接视为已登录（状态接口会标明 auth_enabled=false）
        return ok({"auth_enabled": False, "authenticated": True})
    ip = request.client.host if request.client else "unknown"
    auth.check_login_throttle(ip)
    if not auth.verify_password(body.password, auth.effective_password_hash()):
        auth.record_login_failure(ip)
        raise HTTPException(status_code=401, detail="密码不正确")
    auth.record_login_success(ip)
    token = auth.make_session_token(settings.SESSION_SECRET, days=settings.SESSION_DAYS)
    response.set_cookie(
        key=auth.COOKIE_NAME,
        value=token,
        max_age=settings.SESSION_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.COOKIE_SECURE,
        path="/",
    )
    return ok({"auth_enabled": True, "authenticated": True})


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(key=auth.COOKIE_NAME, path="/")
    return ok({"authenticated": False})
