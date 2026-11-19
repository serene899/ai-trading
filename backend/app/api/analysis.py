"""规则版分析接口。只给指标解读与风险提示，不给交易信号（见 services/analysis.py）。"""
from fastapi import APIRouter, HTTPException, Query

from app.core.response import ok
from app.services import analysis, exchange

router = APIRouter(prefix="/api/v1/analysis", tags=["analysis"])


@router.get("")
async def get_analysis(symbol: str = Query(..., description="如 BTC-USDT")):
    try:
        data = await analysis.analyze_symbol(symbol)
        return ok(data)
    except exchange.ExchangeError as e:
        raise HTTPException(status_code=502, detail=str(e))
