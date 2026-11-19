"""
规则版行情分析（第一阶段，不接外部大模型）。

定位（产品红线）：
- 只做三件事：行情指标解读、风险提示、交易逻辑复盘素材。
- 全部指标由本地规则从 OKX 公共行情计算，不调用任何付费/外部 AI 接口，
  不需要任何 API Key。
- 输出是"学习参考"，不是交易信号：不给买入/卖出指令，不预测涨跌。
  接口与界面都必须带 disclaimer 原文。

以后若接 DeepSeek 等大模型，只允许在本模块的指标结果之上做文字解读，
不得绕过这里的口径直接给结论。
"""
import statistics
from typing import Optional

from app.core.time import iso_cn, now_cn
from app.services import exchange
from app.services.portfolio import build_account_snapshot

DISCLAIMER = "本分析由本地规则指标生成，仅供学习参考，不构成交易信号或投资建议。"


# ---------- 纯计算（可单测） ----------

def moving_average(values: list[float], window: int) -> Optional[float]:
    """简单移动平均；数据不足返回 None。"""
    if window <= 0 or len(values) < window:
        return None
    return sum(values[-window:]) / window


def volatility_pct(closes: list[float], window: int = 20) -> Optional[float]:
    """最近 window 根 K 线收盘价的对数收益率标准差（%）。数据不足返回 None。"""
    if len(closes) < window + 1:
        return None
    import math
    seg = closes[-(window + 1):]
    rets = [math.log(seg[i] / seg[i - 1]) for i in range(1, len(seg)) if seg[i - 1] > 0]
    if len(rets) < 2:
        return None
    return statistics.pstdev(rets) * 100


def describe_trend(ma_short: Optional[float], ma_long: Optional[float], last: float) -> str:
    """用均线位置描述趋势状态。只描述、不预测、不给指令。"""
    if ma_short is None or ma_long is None:
        return "K 线数据不足，暂时无法判断均线趋势。"
    if ma_short > ma_long:
        base = "短期均线在长期均线上方，近期价格强于中期平均成本。"
    elif ma_short < ma_long:
        base = "短期均线在长期均线下方，近期价格弱于中期平均成本。"
    else:
        base = "短期均线与长期均线基本重合，趋势方向不明显。"
    if last > ma_short:
        base += "现价位于短期均线上方。"
    else:
        base += "现价位于短期均线下方。"
    return base


def risk_level(vol_pct: Optional[float]) -> str:
    """按单根 K 线波动率给风险等级（描述性分档）。"""
    if vol_pct is None:
        return "未知（数据不足）"
    if vol_pct < 0.5:
        return "低"
    if vol_pct < 1.5:
        return "中"
    return "高"


# ---------- 聚合 ----------

async def analyze_symbol(symbol: str) -> dict:
    ticker = await exchange.get_ticker(symbol)
    tickers = await exchange.get_tickers([symbol])
    change24h = tickers[0]["change24h"] if tickers else 0.0
    candles = await exchange.get_kline(symbol, "1h", 100)
    closes = [c[4] for c in candles]

    last = float(ticker["last"])
    ma5 = moving_average(closes, 5)
    ma20 = moving_average(closes, 20)
    vol = volatility_pct(closes, 20)
    level = risk_level(vol)

    snapshot = await build_account_snapshot()
    position = None
    notes: list[str] = []
    for p in snapshot["positions"]:
        if p["symbol"] == symbol:
            weight = (p["market_value"] / snapshot["total_equity"] * 100) if snapshot["total_equity"] else 0.0
            position = {**p, "weight_pct": weight}
            if weight > 50:
                notes.append(f"该币种占总资产 {weight:.1f}%，仓位高度集中，单个币种波动会主导账户盈亏。")
            if p["pnl_pct"] <= -10:
                notes.append(f"该持仓浮亏已达 {p['pnl_pct']:.1f}%，复盘一下当初的买入理由是否还成立。")
            if p["pnl_pct"] >= 20:
                notes.append(f"该持仓浮盈已达 {p['pnl_pct']:.1f}%，注意这只是未实现盈亏，平仓后还要扣卖出手续费。")
            break
    if position is None:
        notes.append("当前没有该币种持仓，这份分析只反映市场状态，与账户无关。")
    if level == "高":
        notes.append("近期波动率处于高档，同样的仓位金额，盈亏摆动会明显大于平时。")
    if abs(change24h) >= 0.10:
        notes.append(f"24 小时涨跌幅已达 {change24h * 100:.1f}%，属于大波动日，追涨杀跌的成本（滑点+手续费）会被放大。")

    return {
        "symbol": symbol,
        "source": "OKX 公共行情",
        "updated_at": iso_cn(now_cn()),
        "price": last,
        "change24h_pct": change24h * 100,
        "ma5": ma5,
        "ma20": ma20,
        "trend": describe_trend(ma5, ma20, last),
        "volatility_pct": vol,
        "risk_level": level,
        "position": position,
        "notes": notes,
        "disclaimer": DISCLAIMER,
    }
