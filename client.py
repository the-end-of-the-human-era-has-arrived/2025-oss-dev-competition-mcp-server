import asyncio
import json
import os
from typing import Any, Dict, List

from fastmcp import Client as MCPClient
from openai import OpenAI
from dotenv import load_dotenv


# ---------- 유틸: Pydantic 변환 + 서러게이트 제거 ----------
def _to_dict(x: Any):
    """Pydantic(BaseModel) -> dict, 그 외는 그대로"""
    if hasattr(x, "model_dump"):
        return x.model_dump()
    if hasattr(x, "dict"):
        return x.dict()
    return x

# U+D800..U+DFFF 제거용 매핑 (유효하지 않은 서러게이트 범위)
_SURR_MAP = {i: None for i in range(0xD800, 0xE000)}

def _strip_surrogates(s: str) -> str:
    """문자열에서 서러게이트 코드포인트 제거"""
    return s.translate(_SURR_MAP)

def _sanitize(obj: Any):
    """문자열/리스트/딕셔너리(또는 Pydantic)를 재귀적으로 정리"""
    if isinstance(obj, str):
        return _strip_surrogates(obj)
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, dict):
        return {(_sanitize(k) if isinstance(k, str) else k): _sanitize(v) for k, v in obj.items()}
    if hasattr(obj, "model_dump"):
        return _sanitize(obj.model_dump())
    if hasattr(obj, "dict"):
        return _sanitize(obj.dict())
    return obj
# -----------------------------------------------------------


load_dotenv()

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
SERVER_PATH = os.getenv("MCP_SERVER_PATH", "server.py")


def _mcp_schema_to_openai_tool(tool: Any) -> Dict[str, Any]:
    """
    FastMCP의 Tool(Pydantic) 또는 dict를 OpenAI tools 스키마로 변환.
    """
    t = _to_dict(tool)  # Pydantic -> dict
    name = t.get("name") or t.get("tool") or "tool"
    description = t.get("description", "")
    schema = t.get("inputSchema") or t.get("input_schema") or {"type": "object", "properties": {}}

    return {
        "type": "function",
        "function": {
            "name": _strip_surrogates(name),
            "description": _strip_surrogates(description),
            "parameters": _sanitize(schema),
        },
    }


def _to_str(res: Any) -> str:
    """툴 실행 결과를 OpenAI tool 메시지 content로 안전 변환"""
    if isinstance(res, str):
        return _strip_surrogates(res)
    if hasattr(res, "text") and isinstance(res.text, str):
        return _strip_surrogates(res.text)
    d = _to_dict(res)
    try:
        return _strip_surrogates(json.dumps(_sanitize(d), ensure_ascii=False))
    except Exception:
        return _strip_surrogates(str(d))


async def chat_loop() -> None:
    # MCP 서버(stdio) 연결/스폰
    async with MCPClient(SERVER_PATH) as mcp:
        client = OpenAI()

        # MCP 툴 탐색 -> OpenAI tool 스키마로 변환
        tool_list = await mcp.list_tools()
        openai_tools = [_mcp_schema_to_openai_tool(t) for t in tool_list]
        openai_tools = _sanitize(openai_tools)

        print(f"🔌 Connected to MCP server at {SERVER_PATH}")
        print("🛠️  Tools available to the model: " + ", ".join([t['function']['name'] for t in openai_tools]))
        print("💬 한국어/영어로 질문하세요. 종료: /exit 또는 /quit\n")

        messages: List[Dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "You are a helpful assistant. You have access to several tools via MCP. "
                    "Prefer using tools when the user asks about Notion content or actions. "
                    "지원 언어: 한국어와 영어."
                ),
            }
        ]

        while True:
            user_in = input("You: ").strip()
            if not user_in:
                continue
            if user_in.lower() in ("/exit", "/quit"):
                print("Bye!")
                return

            # 사용자 입력도 sanitize
            messages.append({"role": "user", "content": _strip_surrogates(user_in)})

            # Tool-call 루프
            while True:
                resp = client.chat.completions.create(
                    model=OPENAI_MODEL,
                    messages=_sanitize(messages),   # 메시지 payload를 항상 sanitize
                    tools=openai_tools,
                )
                choice = resp.choices[0]
                msg = choice.message

                if msg.tool_calls:
                    # 툴 호출 처리
                    for tc in msg.tool_calls:
                        tname = tc.function.name
                        targs = tc.function.arguments or "{}"
                        try:
                            parsed = json.loads(targs)
                        except json.JSONDecodeError:
                            parsed = {}

                        # MCP 툴 실행
                        result = await mcp.call_tool(tname, parsed)

                        # 모델의 툴 호출 메시지
                        messages.append(
                            {
                                "role": "assistant",
                                "tool_calls": [
                                    {
                                        "id": tc.id,
                                        "type": "function",
                                        "function": {"name": tname, "arguments": json.dumps(parsed, ensure_ascii=False)},
                                    }
                                ],
                            }
                        )
                        # 툴 결과 메시지
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "name": tname,
                                "content": _to_str(result),
                            }
                        )
                    # 툴 출력까지 대화에 반영했으니, 한 번 더 요청해 최종 답변 받기
                    continue

                # 더 이상 툴 호출이 없으면 최종 답변
                final_text = msg.content or ""
                print(f"Assistant: {final_text}\n")
                messages.append({"role": "assistant", "content": _strip_surrogates(final_text)})
                break


if __name__ == "__main__":
    try:
        asyncio.run(chat_loop())
    except KeyboardInterrupt:
        pass
