#!/usr/bin/env python3
"""
生成登录密码哈希（部署时用一次）。

用法（在 backend 目录）：
    python hash_password.py
按提示输入两遍密码（输入不回显），会打印一行 AUTH_PASSWORD_HASH=...，
把它和随机生成的 SESSION_SECRET 一起写进 backend/.env（或部署平台的环境变量）。
密码本身不会被保存到任何地方。
"""
import getpass
import secrets
import sys

sys.path.insert(0, ".")
from app.core.auth import hash_password  # noqa: E402


def main() -> None:
    pw1 = getpass.getpass("设置登录密码: ")
    if len(pw1) < 8:
        print("密码至少 8 位。")
        raise SystemExit(1)
    pw2 = getpass.getpass("再输一遍确认: ")
    if pw1 != pw2:
        print("两次输入不一致。")
        raise SystemExit(1)
    print()
    print("把下面两行写进 backend/.env（或部署平台的环境变量设置）：")
    print(f"AUTH_PASSWORD_HASH={hash_password(pw1)}")
    print(f"SESSION_SECRET={secrets.token_hex(32)}")
    print("REQUIRE_AUTH=1")
    print("COOKIE_SECURE=1   # 部署在 HTTPS 后面时打开；本地 http 调试时删掉这行")


if __name__ == "__main__":
    main()
