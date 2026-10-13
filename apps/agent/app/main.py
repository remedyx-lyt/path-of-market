"""Path of Market Python 研究服务入口。"""

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.api.routes.research import router

app = FastAPI(
    title="Path of Market 研究服务",
    description="M0-1 演示接口：验证研究请求与报告格式，尚未接入真实模型或资料。",
    version="0.1.0",
)
app.include_router(router)


@app.get("/", include_in_schema=False)
def open_api_docs() -> RedirectResponse:
    """浏览器打开服务根地址时进入接口说明。"""
    return RedirectResponse(url="/docs")
