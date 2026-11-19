"""
pytest 全局前置：在任何 app 模块被 import 之前，先把测试环境变量钉好。

为什么必须放这里：app.config 在 import 时就读环境变量生成 settings，
app.models.db 在 import 时就按 DB_PATH 建引擎。任一测试文件先 import 了 app，
都会把配置冻结成当时的值。所以环境只能在 conftest 里统一设置——
它由 pytest 在收集测试文件之前加载。
"""
import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="ai-trading-test-")
os.environ["DB_PATH"] = os.path.join(_TMP, "test.db")
os.environ["FEE_RATE"] = "0.001"
os.environ["SLIPPAGE_PCT"] = "0"  # 关滑点，专心核对手续费/盈亏数学
os.environ["INITIAL_CAPITAL"] = "10000"
# 测试进程内不开启登录验证（auth 全流程在 test_auth.py 的子进程里单独验）
os.environ.pop("AUTH_PASSWORD_HASH", None)
os.environ.pop("SESSION_SECRET", None)
os.environ.pop("REQUIRE_AUTH", None)
