"""隔离MCP服务：真实SDK/stdio协议，无网络或真实模型。"""
import json
from mcp.server import MCPServer


def make_server(*, body=None, failure=False, unknown_date=False):
    server = MCPServer("path-of-market-test")
    text = body if body is not None else "公司收入100亿元，同比增长20%。\n" * 1800

    @server.tool()
    def web_search_advanced_exa(query: str, numResults: int = 4, endPublishedDate: str = "", textMaxCharacters: int = 600,
                                enableSummary: bool = False, includeDomains: list[str] | None = None) -> str:
        return json.dumps({"results": [
            {"title": "官方新闻", "url": "https://example.org/news", "publishedDate": None if unknown_date else "2026-10-20", "text": "检索摘要，不能当全文"},
            {"title": "未来新闻", "url": "https://example.org/future", "publishedDate": "2027-01-01"},
            {"title": "内网", "url": "https://127.0.0.1/private", "publishedDate": "2026-10-01"},
        ]}, ensure_ascii=False)

    @server.tool()
    def fetch(url: str, max_length: int = 5000, start_index: int = 0, raw: bool = False) -> str:
        if failure:
            raise ValueError("isolated fetch failure")
        content = text[start_index:start_index+max_length]
        if start_index+max_length < len(text):
            content += f"\n\n<error>Content truncated. Call the fetch tool with a start_index of {start_index+len(content)} to get more content.</error>"
        return f"Contents of {url}:\n" + content

    return server


if __name__ == "__main__":
    make_server(body="隔离stdio正文100亿元。", unknown_date=False).run()
