import asyncio
import json
import os
from typing import Any, Dict, List, Optional
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastmcp import Client as MCPClient
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="AI Agent Web Server", version="1.0.0")

# CORS 설정 (프론트엔드 연결을 위해)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # 프론트엔드 주소
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 환경 변수 설정
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
SERVER_PATH = os.getenv("MCP_SERVER_PATH", "server.py")
BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "http://localhost:8080")

# 글로벌 변수들
mcp_client: Optional[MCPClient] = None
openai_client: OpenAI = OpenAI()
openai_tools: List[Dict[str, Any]] = []


# 요청/응답 모델
class ChatRequest(BaseModel):
    message: str
    user_id: Optional[str] = None
    cookies: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    status: str = "success"


class NotionPageData(BaseModel):
    notionPageId: str
    notionPageText: str


# ---------- 유틸 함수들 (client.py에서 가져옴) ----------
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


def _mcp_schema_to_openai_tool(tool: Any) -> Dict[str, Any]:
    """FastMCP의 Tool(Pydantic) 또는 dict를 OpenAI tools 스키마로 변환."""
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


# ---------- 백엔드 API 연동 함수들 ----------
async def get_user_info(user_id: str) -> Dict[str, Any]:
    """백엔드에서 사용자 정보를 가져옵니다."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BACKEND_BASE_URL}/api/users/{user_id}")
        if response.status_code == 200:
            return response.json()
        else:
            raise HTTPException(status_code=response.status_code, detail="Failed to get user info")


async def save_notion_page_to_backend(user_id: str, notion_data: NotionPageData) -> Dict[str, Any]:
    """백엔드에 노션 페이지 데이터를 저장합니다."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BACKEND_BASE_URL}/api/users/{user_id}/notion",
            json=notion_data.model_dump()
        )
        if response.status_code in [200, 201]:
            return response.json()
        else:
            raise HTTPException(status_code=response.status_code, detail="Failed to save notion data")


# ---------- AI 에이전트 처리 함수 ----------
async def process_chat_with_ai(message: str, user_id: Optional[str] = None, cookies: Optional[str] = None) -> str:
    """AI 에이전트와 채팅을 처리합니다."""
    global mcp_client, openai_tools
    
    if not mcp_client:
        raise HTTPException(status_code=500, detail="MCP client not initialized")

    # 쿠키 정보를 함수 전체에서 사용할 수 있도록 저장
    final_cookies = cookies or ""

    messages: List[Dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "You are a helpful assistant with access to Notion tools and backend API. "
                "When user asks about their Notion content, use the available tools to search and retrieve information. "
                "If the user asks to update or save Notion data, you should also call the backend API. "
                "Always respond in Korean. "
                f"Current user ID: {user_id if user_id else 'Not provided'}"
            ),
        },
        {"role": "user", "content": _strip_surrogates(message)}
    ]

    # 사용자 ID가 있는 경우 사용자별 노션 도구 사용을 권장
    if user_id:
        auth_instruction = f"user_id=\"{user_id}\""
        if final_cookies:
            auth_instruction += f", cookies=\"{final_cookies}\""
            
        messages[0]["content"] += (
            f"\nIMPORTANT AUTHENTICATION RULES:\n"
            f"- User ID: {user_id}\n"
            f"- MANDATORY: When calling ANY user-specific tool, you MUST include these exact parameters: {auth_instruction}\n"
            f"- ALWAYS use 'notion_search_with_user' and 'notion_page_content_with_user' (never the basic versions)\n"
            f"- ALWAYS use 'get_user_info' with cookies before any Notion operations\n"
            f"- The backend API returns lowercase fields: 'access_token', 'refresh_token', etc.\n"
            f"- Example tool call: notion_search_with_user({auth_instruction}, query=\"search term\")\n"
            f"- If you get an access_token from backend, the user HAS authorized Notion access.\n"
            f"- NOTE: Authentication parameters will be automatically added to tool calls if missing.\n"
        )

    # Tool-call 루프
    max_iterations = 10  # 무한 루프 방지
    iteration = 0
    
    while iteration < max_iterations:
        iteration += 1
        
        resp = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=_sanitize(messages),
            tools=openai_tools,
        )
        choice = resp.choices[0]
        msg = choice.message

        if msg.tool_calls:
            # 툴 호출 처리
            tool_results = []
            for tc in msg.tool_calls:
                tname = tc.function.name
                targs = tc.function.arguments or "{}"
                try:
                    parsed = json.loads(targs)
                except json.JSONDecodeError:
                    parsed = {}

                # MCP 툴 실행 - 사용자별 도구인 경우 인증 정보 자동 추가
                if user_id and tname in ['get_user_info', 'notion_search_with_user', 'notion_page_content_with_user']:
                    # 인증 정보가 없으면 자동으로 추가
                    if 'user_id' not in parsed:
                        parsed['user_id'] = user_id
                    if final_cookies and 'cookies' not in parsed:
                        parsed['cookies'] = final_cookies
                    
                    print(f"🔧 Auto-added auth to {tname}: user_id={user_id}, has_cookies={bool(final_cookies)}")
                
                result = await mcp_client.call_tool(tname, parsed)
                tool_results.append((tc, tname, parsed, result))

            # 모델의 툴 호출 메시지 추가
            messages.append(
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tname, "arguments": json.dumps(parsed, ensure_ascii=False)},
                        }
                        for tc, tname, parsed, _ in tool_results
                    ],
                }
            )
            
            # 툴 결과 메시지들 추가
            for tc, tname, parsed, result in tool_results:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": tname,
                        "content": _to_str(result),
                    }
                )

            # 노션 페이지 컨텐츠를 가져온 경우 - MCP 도구에서 자동으로 백엔드 저장 처리
            # (save_notion_data_to_backend MCP 도구가 이를 처리함)

            # 툴 출력까지 대화에 반영했으니, 한 번 더 요청해 최종 답변 받기
            continue

        # 더 이상 툴 호출이 없으면 최종 답변
        final_text = msg.content or ""
        return _strip_surrogates(final_text)

    return "죄송합니다. 처리 중 문제가 발생했습니다."


# ---------- 시작/종료 이벤트 ----------
@app.on_event("startup")
async def startup_event():
    """서버 시작 시 MCP 클라이언트 초기화"""
    global mcp_client, openai_tools
    
    try:
        # MCP 클라이언트 생성 (stdio 방식)
        mcp_client = MCPClient(SERVER_PATH)
        await mcp_client.__aenter__()
        
        # MCP 툴 목록 가져오기
        tool_list = await mcp_client.list_tools()
        openai_tools = [_mcp_schema_to_openai_tool(t) for t in tool_list]
        openai_tools = _sanitize(openai_tools)
        
        print(f"🔌 MCP server connected: {SERVER_PATH}")
        print(f"🛠️  Available tools: {[t['function']['name'] for t in openai_tools]}")
        
    except Exception as e:
        print(f"❌ Failed to initialize MCP client: {e}")
        raise


@app.on_event("shutdown")
async def shutdown_event():
    """서버 종료 시 MCP 클라이언트 정리"""
    global mcp_client
    if mcp_client:
        try:
            await mcp_client.__aexit__(None, None, None)
        except Exception as e:
            print(f"Warning during MCP client cleanup: {e}")


# ---------- API 엔드포인트들 ----------
@app.get("/")
async def root():
    """서버 상태 확인"""
    return {"message": "AI Agent Web Server is running", "status": "ok"}


@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest, req: Request):
    """프론트엔드에서 채팅 요청을 받는 엔드포인트"""
    try:
        # HTTP 헤더에서 쿠키 추출 (우선순위: 헤더 > 요청 본문)
        cookies_from_header = req.headers.get("cookie", "")
        final_cookies = cookies_from_header or request.cookies or ""
        
        print(f"🍪 Cookies from header: {cookies_from_header}")
        
        response = await process_chat_with_ai(
            request.message, 
            request.user_id, 
            final_cookies
        )
        return ChatResponse(response=response)
    except Exception as e:
        print(f"Error in chat endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/health")
async def health_check():
    """헬스 체크 엔드포인트"""
    return {
        "status": "healthy",
        "mcp_connected": mcp_client is not None,
        "tools_count": len(openai_tools)
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8081, reload=True)
