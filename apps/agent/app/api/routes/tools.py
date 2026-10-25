"""开发验收入口；产品研究页面的模型循环在 M1-3 使用同一注册表。"""

from fastapi import APIRouter

from app.tools.contracts import ToolCall
from app.tools.registry import get_research_tools

router = APIRouter(prefix="/tools", tags=["研究工具（开发验收）"])


@router.get("")
def list_tools():
    from app.services.agent_runner import declarations

    tools = get_research_tools()
    return {"tools": tools.declarations(), "modelLoopConnected": True, "agentTools": declarations(),
            "mcp": {"enabled": tools.public_web.gateway.settings.enabled, "searchServer": "Exa (Streamable HTTP)",
                    "readerServer": "MCP reference Fetch (stdio)", "connectionChecked": False,
                    "instruction": "配置可用不代表已连通；实际搜索/正文工具事件才记录成功或失败。"}}


@router.post("/execute")
def execute_tool(call: ToolCall):
    return get_research_tools().execute(call.name, call.arguments)
