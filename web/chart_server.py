from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .chart_payload import build_chart_request, build_payload, payload_cache

ROOT_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"
CHARTING_LIBRARY_DIR = ROOT_DIR / "charting_library" / "charting_library"

app = FastAPI(title="ChanAnalyzer Online Chart", version="0.1.0")

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
if CHARTING_LIBRARY_DIR.exists():
    app.mount("/charting_library", StaticFiles(directory=str(CHARTING_LIBRARY_DIR)), name="charting_library")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/chart")


@app.get("/chart", include_in_schema=False)
def chart_page():
    return FileResponse(STATIC_DIR / "chart.html")


@app.get("/api/chart/payload")
def chart_payload(
    code: str = Query(..., description="股票代码，如 002112 / 000001.SZ"),
    lv: str = Query("day", description="级别：day/week/5m/15m/30m/60m"),
    begin: str | None = Query(None, description="开始日期，YYYY-MM-DD"),
    end: str | None = Query(None, description="结束日期，YYYY-MM-DD"),
    data_src: str = Query("TDX", description="数据源：TDX/TUSHARE/CACHE_DB/..."),
    autype: str = Query("QFQ", description="复权：QFQ/HFQ/NONE"),
    x_range: int = Query(200, ge=0, description="初始可见 K 线数量，0 表示全部"),
    plot_mean: bool = Query(False, description="是否展示均线"),
    refresh: bool = Query(False, description="是否跳过内存缓存重新计算"),
):
    try:
        req = build_chart_request(
            code=code,
            lv=lv,
            begin=begin,
            end=end,
            data_src=data_src,
            autype=autype,
            x_range=x_range,
            plot_mean=plot_mean,
        )
        return build_payload(req, use_cache=not refresh)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"生成图表失败: {exc}") from exc


@app.post("/api/chart/cache/clear")
def clear_cache():
    payload_cache.clear()
    return {"ok": True}
