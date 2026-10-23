"""Path of Market Python 研究服务入口。"""

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.api.routes.research import router

app = FastAPI(
    title="Path of Market 研究服务",
    description="保留 M0 演示接口；M1-1 接入模型与研究状态，真实资料工具后续接入。",
    version="0.2.0",
)
app.include_router(router)


@app.get("/", include_in_schema=False)
def open_api_docs() -> RedirectResponse:
    """浏览器打开服务根地址时进入接口说明。"""
    return RedirectResponse(url="/docs")
