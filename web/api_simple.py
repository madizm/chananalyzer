"""
ChanAnalyzer FastAPI 后端服务 - 简化版

只提供模拟数据，用于测试前后端通信
"""
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# ============ 应用初始化 ============
app = FastAPI(
    title="ChanAnalyzer API",
    description="A股缠论分析系统 - 后端接口",
    version="1.0.0"
)

# CORS 跨域配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件目录
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    from fastapi.responses import RedirectResponse

    @app.get("/")
    async def redirect_to_index():
        return RedirectResponse(url="/static/index.html")


@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "time": datetime.now().isoformat(),
        "message": "API is running"
    }


@app.get("/api/ping")
async def ping():
    """简单的 ping 测试"""
    return {"pong": True}


# ============ 模拟数据接口 ============

@app.get("/api/dashboard/market")
async def get_market_overview():
    """获取市场概况（模拟数据）"""
    return {
        "sh_index": {"value": 3086.81, "change": 0.52},
        "sz_index": {"value": 10125.36, "change": 0.38},
        "cyb_index": {"value": 2018.92, "change": -0.15},
        "stats": {"up": 2845, "down": 1923},
        "update_time": datetime.now().strftime("%H:%M:%S")
    }


@app.get("/api/dashboard/bs-stats")
async def get_bs_stats():
    """获取买卖点统计（模拟数据）"""
    return {
        "buy": {"1": 23, "2": 67, "3a": 28, "3b": 17},
        "sell": {"1": 18, "2s": 34, "3a": 22, "3b": 6},
        "heat": {
            "volume": "8,632亿",
            "limit_up": 52,
            "limit_down": 12
        }
    }


@app.get("/api/dashboard/sectors")
async def get_hot_sectors():
    """获取热门板块（模拟数据）"""
    return {
        "top_gainers": [
            {"name": "人工智能 · 算力", "change": 4.12},
            {"name": "半导体 · 芯片", "change": 3.28},
            {"name": "新能源 · 光伏", "change": 2.56},
            {"name": "通信设备", "change": 1.89},
            {"name": "汽车整车", "change": 1.45}
        ],
        "top_losers": [
            {"name": "大消费 · 白酒", "change": -2.18},
            {"name": "房地产", "change": -1.76},
            {"name": "银行", "change": -1.23},
            {"name": "创新药 · 生物", "change": -0.89},
            {"name": "钢铁", "change": -0.56}
        ]
    }


@app.get("/api/dashboard/recommend")
async def get_recommendations(limit: int = 10):
    """获取买点推荐（模拟数据）"""
    stocks = [
        {"code": "300750", "name": "宁德时代", "price": 168.30, "change": 2.34, "bs_type": "二买", "bs_type_raw": "2", "direction": "buy", "industry": "新能源", "date": "2024-12-20"},
        {"code": "688981", "name": "中芯国际", "price": 52.68, "change": 4.12, "bs_type": "三买A", "bs_type_raw": "3a", "direction": "buy", "industry": "半导体", "date": "2024-12-20"},
        {"code": "002475", "name": "立讯精密", "price": 31.25, "change": 1.89, "bs_type": "二买", "bs_type_raw": "2", "direction": "buy", "industry": "消费电子", "date": "2024-12-20"},
        {"code": "300059", "name": "东方财富", "price": 14.82, "change": 0.95, "bs_type": "三买B", "bs_type_raw": "3b", "direction": "buy", "industry": "证券", "date": "2024-12-20"},
        {"code": "688111", "name": "金山办公", "price": 286.50, "change": -0.32, "bs_type": "一买", "bs_type_raw": "1", "direction": "buy", "industry": "软件", "date": "2024-12-20"},
        {"code": "002594", "name": "比亚迪", "price": 215.80, "change": 1.56, "bs_type": "二买", "bs_type_raw": "2", "direction": "buy", "industry": "汽车整车", "date": "2024-12-20"},
        {"code": "600519", "name": "贵州茅台", "price": 1728.00, "change": -1.25, "bs_type": "二卖", "bs_type_raw": "2s", "direction": "sell", "industry": "白酒", "date": "2024-12-20"},
        {"code": "000858", "name": "五粮液", "price": 138.50, "change": -1.82, "bs_type": "二卖", "bs_type_raw": "2s", "direction": "sell", "industry": "白酒", "date": "2024-12-20"},
        {"code": "300274", "name": "阳光电源", "price": 68.90, "change": 3.45, "bs_type": "三买A", "bs_type_raw": "3a", "direction": "buy", "industry": "光伏设备", "date": "2024-12-20"},
        {"code": "002415", "name": "海康威视", "price": 32.15, "change": 0.78, "bs_type": "二买", "bs_type_raw": "2", "direction": "buy", "industry": "安防设备", "date": "2024-12-20"},
    ]
    return {"stocks": stocks[:limit]}


@app.get("/api/scan/status")
async def get_scan_status():
    """获取扫描状态"""
    return {
        "scanning": False,
        "progress": 0,
        "total": 0,
        "found": 0,
        "message": "空闲"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=True)
