"""
全局配置读取 — 所有敏感信息通过 .env 注入，严禁硬编码。
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Exchange
    # ★ 第一阶段红线：只用 OKX 公共行情（无需任何 Key），系统不保存、不读取、
    #   不接受任何交易所 API Key，也没有任何真实下单接口。
    #   旧版本在这里留过 OKX/BINANCE 的 Key 字段（从未被任何代码调用），
    #   接管时已删除，避免日后误接实盘。
    EXCHANGE: str = "okx"

    # Auth（v1.2.0 单用户登录验证，见 app/core/auth.py）
    # 密码哈希与会话密钥只从环境变量/.env 读，永不写进代码或仓库。
    AUTH_PASSWORD_HASH: str = ""
    # 次选：明文密码环境变量（方便手机上在云平台填环境变量部署）；启动后只在内存中哈希，不落盘
    AUTH_PASSWORD: str = ""
    SESSION_SECRET: str = ""
    # 部署时设 1：验证未配置好就拒绝启动（fail-closed）
    REQUIRE_AUTH: bool = False
    # 部署在 HTTPS 后面时设 1：会话 Cookie 只走 HTTPS
    COOKIE_SECURE: bool = False
    SESSION_DAYS: int = 7

    # Account
    INITIAL_CAPITAL: float = 10000.0

    # 模拟交易成本（贴近真实盘口）
    # 手续费率：默认 0.1%（类似币安/OKX 现货 maker/taker 的中位数）
    FEE_RATE: float = 0.001
    # 市价单滑点：成交价在当前价基础上 ±SLIPPAGE_PCT（买高卖低）
    # 默认 0.05%；限价单不应用滑点（用户已经指定价格）
    SLIPPAGE_PCT: float = 0.0005

    # DB
    DB_PATH: str = "./data.db"

    # CORS
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Server
    BACKEND_PORT: int = 8000

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
