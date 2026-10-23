"""Path of Market Python 研究服务入口。"""

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.api.routes.research import router
from app.api.routes.tools import router as tools_router

app = FastAPI(
    title="Path of Market 研究服务",
    description="保留演示与模型分析；M1-2 提供官方年报发现、下载与按页读取工具，模型循环在 M1-3 接入。",
    version="0.3.0",
)
app.include_router(router)
app.include_router(tools_router)


@app.get("/", include_in_schema=False)
def open_api_docs() -> RedirectResponse:
    """浏览器打开服务根地址时进入接口说明。"""
    return RedirectResponse(url="/docs")
