"""Path of Market 本地后端，提供网页 API 和研究工具。"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.routes import history, jobs, research, tools
from app.core.config import ModelServiceError
from app.services.research_jobs import job_store
from app.storage import get_storage, writer_lease


@asynccontextmanager
async def lifespan(app: FastAPI):
    with writer_lease():
        await asyncio.to_thread(get_storage)
        try:
            yield
        finally:
            await job_store.shutdown()
            get_storage.cache_clear()


app = FastAPI(title="Path of Market 研究服务", version="0.5.0", lifespan=lifespan)
app.include_router(history.router)
for router in (research.router, jobs.router):
    app.include_router(router, prefix="/api")
    app.include_router(router, include_in_schema=False)
app.include_router(research.health_router)
app.include_router(tools.router)


@app.exception_handler(ModelServiceError)
async def service_error(request: Request, error: ModelServiceError):
    message = error.message
    if request.url.path.startswith("/api/"):
        # 网页只接收已知错误和本地文案，不回显提供方的响应或配置。
        messages = {
            "RESEARCH_NOT_RESUMABLE": "此任务暂时无法接续，请检查原任务状态、模型配置与会话记录。",
            "MODEL_NOT_CONFIGURED": "请在项目根目录 .env 填写模型密钥并保存。",
            "MODEL_CONFIG_ERROR": "模型配置无效，请检查本地配置。",
            "MODEL_AUTH_FAILED": "模型密钥验证失败，请检查密钥和账户权限。",
            "MODEL_BALANCE_INSUFFICIENT": "模型账户余额或额度不足，请到供应商平台检查。",
            "MODEL_RATE_LIMITED": "模型调用过于频繁或额度受限，请稍后再试。",
            "MODEL_UPSTREAM_ERROR": "模型接口暂时无法完成请求，请检查模型配置或稍后重试。",
            "MODEL_TIMEOUT": "模型响应超时，请重试或缩短问题。",
            "MODEL_UNAVAILABLE": "无法连接模型接口，请检查网络和接口地址。",
            "MODEL_INVALID_RESPONSE": "模型未返回完整且有效的报告，请重试或调整输出长度。",
        }
        message = messages.get(error.code, "研究任务暂时无法执行，请稍后重试。")
    return JSONResponse({"error": {"code": error.code, "message": message}}, status_code=error.status)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, error: RequestValidationError):
    if request.url.path.startswith("/api/"):
        for issue in error.errors():
            if issue["type"] == "json_invalid" or issue["loc"] == ("body",) and issue["type"] == "missing":
                return JSONResponse({"error": {"code": "INVALID_JSON", "message": "请求体必须包含有效的 JSON。"}}, 400)
            if issue["loc"][0] in ("path", "query"):
                return JSONResponse({"error": {"code": "INVALID_PARAMETER", "message": "路径或查询参数格式无效。"}}, 400)
    return await request_validation_exception_handler(request, error)


@app.get("/", include_in_schema=False)
def open_api_docs() -> RedirectResponse:
    return RedirectResponse(url="/docs")
