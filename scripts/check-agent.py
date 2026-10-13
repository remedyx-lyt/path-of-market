"""通过实际 HTTP 检查 M0-1 接口；先运行 start-agent.ps1，再执行本脚本。"""

import argparse
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def request(base_url: str, path: str, payload: dict | None = None) -> tuple[int, bytes]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {} if data is None else {"Content-Type": "application/json; charset=utf-8"}
    http_request = Request(base_url.rstrip("/") + path, data=data, headers=headers)
    try:
        with urlopen(http_request, timeout=5) as response:
            return response.status, response.read()
    except HTTPError as error:
        return error.code, error.read()


def check(base_url: str) -> None:
    status, body = request(base_url, "/health")
    health = json.loads(body)
    assert status == 200 and health["status"] == "ok" and health["mode"] == "mock"
    print("PASS health")

    payload = {
        "target": "示例公司",
        "question": "如何研究研发投入变化？",
        "userStyle": "关注长期增长和风险验证",
        "omens": ["opportunity", "abyssal_echoes"],
    }
    status, body = request(base_url, "/research/mock", payload)
    report = json.loads(body)
    assert status == 200 and report["mode"] == "mock" and report["isMock"] is True
    for field, value in payload.items():
        assert report[field] == value, f"请求字段没有正确传递：{field}"
    assert report["sections"] and report["sources"] == [] and report["toolCalls"] == []
    assert "user_style" not in report and "is_mock" not in report
    print("PASS Chinese input, JSON aliases, mock report")

    status, body = request(base_url, "/research/mock", {"target": "  示例公司  ", "question": "  研究问题  "})
    minimal = json.loads(body)
    assert status == 200 and minimal["target"] == "示例公司" and minimal["question"] == "研究问题"
    assert minimal["userStyle"] == "" and minimal["omens"] == []
    print("PASS whitespace normalization and optional defaults")

    invalid_requests = [
        ("empty target", {**payload, "target": ""}),
        ("blank target", {**payload, "target": " \t\n "}),
        ("empty question", {**payload, "question": ""}),
        ("blank question", {**payload, "question": " \n "}),
        ("missing question", {"target": "示例公司"}),
        ("wrong target type", {**payload, "target": 123}),
        ("wrong question type", {**payload, "question": False}),
        ("wrong preference type", {**payload, "userStyle": ["growth"]}),
        ("unknown omen", {**payload, "omens": ["unknown"]}),
        ("wrong omens type", {**payload, "omens": "opportunity"}),
        ("target too long", {**payload, "target": "a" * 121}),
        ("question too long", {**payload, "question": "a" * 2001}),
        ("preference too long", {**payload, "userStyle": "a" * 501}),
        ("too many omens", {**payload, "omens": ["exalted"] * 5}),
        ("unknown field", {**payload, "unexpected": "value"}),
    ]
    for label, invalid in invalid_requests:
        status, body = request(base_url, "/research/mock", invalid)
        assert status == 422 and json.loads(body)["detail"], label
        print(f"PASS validation: {label}")

    status, body = request(base_url, "/docs")
    assert status == 200 and b"swagger" in body.lower()
    status, body = request(base_url, "/openapi.json")
    schema = json.loads(body)
    assert status == 200 and "/health" in schema["paths"] and "/research/mock" in schema["paths"]
    print("PASS API docs and OpenAPI")
    print("M0-1 HTTP checks passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    check(args.base_url)
