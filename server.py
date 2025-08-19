import os
from typing import Any, Dict, List, Optional
import httpx

from fastmcp import FastMCP, Context
from notion_client import Client
from dotenv import load_dotenv, find_dotenv

APP_NAME = "NotionMCP"

# 서버 프로세스에서 .env 파일을 직접 로드합니다.
load_dotenv(find_dotenv(), override=False)

mcp = FastMCP(APP_NAME)

# 백엔드 API 주소
BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "http://localhost:8080")

# Notion 클라이언트는 사용자별로 동적 생성
notion_clients: Dict[str, Client] = {}

def _get_notion_client(access_token: str) -> Client:
    """사용자의 AccessToken으로 Notion Client를 생성/반환합니다."""
    if access_token not in notion_clients:
        notion_clients[access_token] = Client(auth=access_token)
    return notion_clients[access_token]


def _ensure_notion() -> None:
    """기본 NOTION_TOKEN 확인 (호환성 유지)"""
    token = os.getenv("NOTION_TOKEN")
    if not token:
        raise RuntimeError("NOTION_TOKEN 환경 변수가 설정되어 있지 않습니다.")
    # 기본 클라이언트는 더 이상 사용하지 않지만 호환성을 위해 유지


def _rich_text_to_plain(rt_items: List[Dict[str, Any]]) -> str:
    """Notion의 rich_text 배열을 일반 문자열로 합칩니다."""
    out: List[str] = []
    if not rt_items:
        return ""
    for item in rt_items:
        if isinstance(item, dict):
            out.append(item.get("plain_text") or item.get("text", {}).get("content", ""))
    return "".join(out).strip()


def _extract_title(obj: Dict[str, Any]) -> str:
    """페이지/데이터베이스 객체에서 제목 문자열을 추출합니다."""
    otype = obj.get("object")
    if otype == "page":
        props: Dict[str, Any] = obj.get("properties", {})
        for name, prop in props.items():
            if prop and prop.get("type") == "title":
                return _rich_text_to_plain(prop.get("title", [])) or name
        return ""
    if otype == "database":
        return _rich_text_to_plain(obj.get("title", []))
    return ""


def _list_block_children_recursive(block_id: str, max_depth: int = 10) -> List[Dict[str, Any]]:
    """
    블록 자식들을 페이지네이션/재귀적으로 모두 가져옵니다.
    최대 깊이는 max_depth로 제한합니다(과도한 트리 방지).
    """
    assert isinstance(notion, Client)
    results: List[Dict[str, Any]] = []

    # 현재 레벨의 children 전부 수집
    cursor: Optional[str] = None
    while True:
        resp = notion.blocks.children.list(block_id=block_id, start_cursor=cursor, page_size=100)
        batch = resp.get("results", [])
        results.extend(batch)
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")

    # 자식이 있는 블록은 재귀적으로 children 삽입
    if max_depth <= 0:
        return results

    enriched: List[Dict[str, Any]] = []
    for b in results:
        b = dict(b)  # 복사
        if b.get("has_children"):
            child_id = b.get("id")
            try:
                b["children"] = _list_block_children_recursive(child_id, max_depth=max_depth - 1)
            except Exception:
                b["children"] = []
        enriched.append(b)
    return enriched

def _list_block_children_recursive_with_client(notion_client: Client, block_id: str, max_depth: int = 10) -> List[Dict[str, Any]]:
    """
    특정 클라이언트를 사용하여 블록 자식들을 페이지네이션/재귀적으로 모두 가져옵니다.
    최대 깊이는 max_depth로 제한합니다(과도한 트리 방지).
    """
    results: List[Dict[str, Any]] = []

    # 현재 레벨의 children 전부 수집
    cursor: Optional[str] = None
    while True:
        resp = notion_client.blocks.children.list(block_id=block_id, start_cursor=cursor, page_size=100)
        batch = resp.get("results", [])
        results.extend(batch)
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")

    # 자식이 있는 블록은 재귀적으로 children 삽입
    if max_depth <= 0:
        return results

    enriched: List[Dict[str, Any]] = []
    for b in results:
        b = dict(b)  # 복사
        if b.get("has_children"):
            child_id = b.get("id")
            try:
                b["children"] = _list_block_children_recursive_with_client(notion_client, child_id, max_depth=max_depth - 1)
            except Exception:
                b["children"] = []
        enriched.append(b)
    return enriched

def _blocks_to_markdown(blocks: List[Dict[str, Any]], depth: int = 0) -> List[str]:
    """
    주요 텍스트성 블록을 Markdown 유사 포맷으로 변환합니다.
    복잡한 테이블/데이터베이스 뷰 등은 간단 표기 또는 생략합니다.
    """
    lines: List[str] = []
    indent = "  " * depth

    for blk in blocks:
        btype = blk.get("type")
        data = blk.get(btype, {}) if isinstance(blk.get("type"), str) else {}
        text = _rich_text_to_plain(data.get("rich_text", []))

        if btype == "heading_1":
            lines.append(f"{indent}# {text}")
        elif btype == "heading_2":
            lines.append(f"{indent}## {text}")
        elif btype == "heading_3":
            lines.append(f"{indent}### {text}")
        elif btype == "paragraph":
            lines.append(f"{indent}{text}")
        elif btype == "bulleted_list_item":
            lines.append(f"{indent}- {text}")
        elif btype == "numbered_list_item":
            lines.append(f"{indent}1. {text}")  # 간단 표기
        elif btype == "to_do":
            checked = data.get("checked")
            mark = "x" if checked else " "
            lines.append(f"{indent}- [{mark}] {text}")
        elif btype == "quote":
            lines.append(f"{indent}> {text}")
        elif btype == "callout":
            emoji = (data.get("icon") or {}).get("emoji") if isinstance(data.get("icon"), dict) else None
            prefix = emoji or "💡"
            lines.append(f"{indent}{prefix} {text}")
        elif btype == "code":
            language = data.get("language") or ""
            code_text = _rich_text_to_plain(data.get("rich_text", []))
            lines.append(f"{indent}```{language}".rstrip())
            lines.append(code_text)
            lines.append(f"{indent}```")
        elif btype == "toggle":
            lines.append(f"{indent}▸ {text}")
        elif btype == "divider":
            lines.append(f"{indent}---")
        elif btype == "image":
            caption = _rich_text_to_plain(data.get("caption", []))
            lines.append(f"{indent}![image]  {caption}".rstrip())
        else:
            # 기타 블록은 간단 표기로 남김
            lines.append(f"{indent}[{btype}] {text}".rstrip())

        # 자식 블록 있으면 재귀적으로 이어붙임
        children = blk.get("children") or []
        if children:
            lines.extend(_blocks_to_markdown(children, depth=depth + 1))

    return lines


# -----------------------------
# 백엔드 API 도구
# -----------------------------
@mcp.tool
async def get_user_info(user_id: str, auth_token: str = "", cookies: str = "") -> Dict[str, Any]:
    """백엔드에서 사용자 정보와 노션 액세스 토큰을 조회합니다.
    
    사용자의 기본 정보와 노션 연동 상태를 확인하는 핵심 도구입니다.
    사용자별 노션 작업을 수행하기 전에 호출하여 access_token을 얻어야 합니다.
    
    인자:
        user_id: 사용자 ID (필수)
        auth_token: 인증 토큰 (HTTP Authorization 헤더에서 전달)
        cookies: 쿠키 문자열 (HTTP Cookie 헤더에서 전달)
        
    반환:
        사용자 정보 객체:
        - id, nickname: 사용자 기본 정보
        - notion_user_id: 노션 사용자 ID
        - access_token: 노션 API 호출용 토큰 (중요!)
        - refresh_token: 토큰 갱신용
    
    사용 케이스:
        - "내 정보 알려줘"
        - "노션 연동 상태 확인해줘"
        - 모든 사용자별 노션 작업의 전제 조건
        
    중요: 반환된 access_token을 notion_search_with_token, notion_page_content_with_token, get_complete_notion_pages_with_token 등에 전달 필수
    """
    async with httpx.AsyncClient() as client:
        try:
            headers = {}
            if auth_token:
                headers["Authorization"] = f"Bearer {auth_token}"
            
            # sessionID 쿠키는 필수, 기존 쿠키와 결합
            session_cookie = f"sessionID={user_id}"
            if cookies:
                headers["Cookie"] = f"{cookies}; {session_cookie}"
            else:
                headers["Cookie"] = session_cookie
                
            response = await client.get(
                f"{BACKEND_BASE_URL}/api/users/{user_id}",
                headers=headers
            )
            if response.status_code == 200:
                return response.json()
            else:
                return {"error": f"Failed to get user info: {response.status_code}", "detail": response.text}
        except Exception as e:
            return {"error": f"Request failed: {str(e)}"}


@mcp.tool
async def save_notion_data_to_backend(
    user_id: str, 
    content: str, 
    notion_url: str, 
    notion_page_id: str, 
    summary: str,
    auth_token: str = "",
    cookies: str = ""
) -> Dict[str, Any]:
    """노션 페이지 데이터를 백엔드 데이터베이스에 저장합니다.
    
    사용자의 노션 페이지 내용과 요약을 데이터베이스에 저장하는 핵심 도구입니다.
    노션 페이지를 분석하고 저장하거나, 사용자가 직접 저장을 요청할 때 사용하세요.
    
    인자:
        user_id: 사용자 ID
        content: 노션 페이지의 전체 텍스트 내용
        notion_url: 노션 페이지 URL
        notion_page_id: 노션 페이지 ID  
        summary: 페이지 내용의 간결한 요약 (2-3문장 권장)
        auth_token: 인증 토큰 (HTTP Authorization 헤더에서 전달)
        cookies: 쿠키 문자열 (HTTP Cookie 헤더에서 전달)
        
    반환:
        저장 결과 - 성공시 저장된 데이터 정보, 실패시 에러 메시지
        
    사용 케이스:
        - "노션 페이지를 저장해줘"
        - "내 노션 글을 백엔드에 저장해줘"
        - "분석한 노션 데이터를 데이터베이스에 저장해줘"
    
    """
    async with httpx.AsyncClient() as client:
        try:
            headers = {}
            if auth_token:
                headers["Authorization"] = f"Bearer {auth_token}"
            
            # sessionID 쿠키는 필수, 기존 쿠키와 결합
            session_cookie = f"sessionID={user_id}"
            if cookies:
                headers["Cookie"] = f"{cookies}; {session_cookie}"
            else:
                headers["Cookie"] = session_cookie
                
            payload = {
                "user_id": user_id,
                "content": content,
                "notion_url": notion_url,
                "notion_page_id": notion_page_id,
                "summary": summary
            }
            response = await client.post(
                f"{BACKEND_BASE_URL}/api/users/{user_id}/notion",
                json=payload,
                headers=headers
            )
            if response.status_code in [200, 201]:
                return response.json()
            else:
                return {"error": f"Failed to save notion data: {response.status_code}", "detail": response.text}
        except Exception as e:
            return {"error": f"Request failed: {str(e)}"}

@mcp.tool
async def save_bulk_notion_data_to_backend(
    user_id: str,
    notion_data_list: List[Dict[str, Any]],
    auth_token: str = "",
    cookies: str = ""
) -> Dict[str, Any]:
    """여러 노션 페이지 데이터를 백엔드 데이터베이스에 일괄 저장합니다.
    
    대량의 노션 페이지를 효율적으로 저장하는 도구입니다.
    여러 페이지를 한 번의 API 호출로 저장하여 성능을 향상시킵니다.
    백엔드 API는 배열 형태의 데이터를 직접 받습니다.
    
    인자:
        user_id: 사용자 ID
        notion_data_list: 저장할 노션 페이지 데이터 배열, 각 항목은 다음을 포함:
            - content: 노션 페이지의 전체 텍스트 내용
            - notion_url: 노션 페이지 URL
            - notion_page_id: 노션 페이지 ID
            - summary: 페이지 내용의 간결한 요약 (2-3문장 권장)
        auth_token: 인증 토큰 (HTTP Authorization 헤더에서 전달)
        cookies: 쿠키 문자열 (HTTP Cookie 헤더에서 전달)
        
    반환:
        일괄 저장 결과 - 성공시 저장된 데이터 정보, 실패시 에러 메시지
        
    사용 케이스:
        - "여러 노션 페이지를 한 번에 저장해줘"
        - "검색된 모든 노션 글을 백엔드에 저장해줘"
        - "분석 완료된 여러 노션 데이터를 일괄 저장해줘"
        - STEP 2: Content Analysis and Storage에서 다수 페이지 처리 시 권장
    
    워크플로우 참고: 일괄 저장 완료시 "STEP 2 COMPLETE: Stored [X] pages with summaries in database" 로그 출력
    
    API 호출 형태:
        POST /api/users/{user_id}/notion/bulk
        Request Body: [
            {
                "user_id": "user123",
                "content": "페이지1 내용...",
                "notion_url": "https://notion.so/page1",
                "notion_page_id": "page1_id",
                "summary": "페이지1 요약"
            },
            {
                "user_id": "user123",
                "content": "페이지2 내용...",
                "notion_url": "https://notion.so/page2", 
                "notion_page_id": "page2_id",
                "summary": "페이지2 요약"
            }
        ]
    """
    async with httpx.AsyncClient() as client:
        try:
            headers = {}
            if auth_token:
                headers["Authorization"] = f"Bearer {auth_token}"
            
            # sessionID 쿠키는 필수, 기존 쿠키와 결합
            session_cookie = f"sessionID={user_id}"
            if cookies:
                headers["Cookie"] = f"{cookies}; {session_cookie}"
            else:
                headers["Cookie"] = session_cookie
                
            # 백엔드가 배열을 직접 받으므로 배열 형태로 전송
            payload = [
                {
                    "user_id": user_id,
                    "content": item.get("content", ""),
                    "notion_url": item.get("notion_url", ""),
                    "notion_page_id": item.get("notion_page_id", ""),
                    "summary": item.get("summary", "")
                }
                for item in notion_data_list
            ]
            
            response = await client.post(
                f"{BACKEND_BASE_URL}/api/users/{user_id}/notion/bulk",
                json=payload,
                headers=headers
            )
            if response.status_code in [200, 201]:
                return {"result": response.json()}
            else:
                return {"error": f"Failed to save bulk notion data: {response.status_code}", "detail": response.text}
        except Exception as e:
            return {"error": f"Request failed: {str(e)}"}


# -----------------------------
# 백엔드 Notion API 도구들
# -----------------------------
@mcp.tool
async def get_all_notion_pages(
    user_id: str,
    auth_token: str = "",
    cookies: str = ""
) -> Dict[str, Any]:
    """사용자의 모든 노션 페이지 목록을 백엔드에서 조회합니다.
    
    백엔드 데이터베이스에 저장된 사용자의 모든 노션 페이지 데이터를 가져옵니다.
    
    인자:
        user_id: 사용자 ID
        auth_token: 인증 토큰 (HTTP Authorization 헤더에서 전달)
        cookies: 쿠키 문자열 (HTTP Cookie 헤더에서 전달)
        
    반환:
        노션 페이지 목록 배열, 각 항목 포함:
        - id: 백엔드 데이터베이스의 레코드 ID
        - user_id: 사용자 ID
        - content: 페이지 내용
        - notion_url: 노션 페이지 URL
        - notion_page_id: 노션 페이지 ID
        - summary: 페이지 요약
    """
    async with httpx.AsyncClient() as client:
        try:
            headers = {}
            if auth_token:
                headers["Authorization"] = f"Bearer {auth_token}"
            
            # sessionID 쿠키는 필수, 기존 쿠키와 결합
            session_cookie = f"sessionID={user_id}"
            if cookies:
                headers["Cookie"] = f"{cookies}; {session_cookie}"
            else:
                headers["Cookie"] = session_cookie
                
            response = await client.get(
                f"{BACKEND_BASE_URL}/api/users/{user_id}/notion",
                headers=headers
            )
            if response.status_code == 200:
                return {"result":response.json()}
            else:
                return {"error": f"Failed to get notion pages: {response.status_code}", "detail": response.text}
        except Exception as e:
            return {"error": f"Request failed: {str(e)}"}


@mcp.tool
async def get_notion_page_by_id(
    user_id: str,
    notion_page_id: str,
    auth_token: str = "",
    cookies: str = ""
) -> Dict[str, Any]:
    """백엔드에서 특정 노션 페이지를 조회합니다.
    
    백엔드 데이터베이스에 저장된 특정 노션 페이지의 상세 정보를 가져옵니다.
    
    인자:
        user_id: 사용자 ID
        notion_page_id: 조회할 노션 페이지 ID
        auth_token: 인증 토큰 (HTTP Authorization 헤더에서 전달)
        cookies: 쿠키 문자열 (HTTP Cookie 헤더에서 전달)
        
    반환:
        노션 페이지 상세 정보:
        - id: 백엔드 데이터베이스의 레코드 ID
        - user_id: 사용자 ID
        - content: 페이지 내용
        - notion_url: 노션 페이지 URL
        - notion_page_id: 노션 페이지 ID
        - summary: 페이지 요약
    """
    async with httpx.AsyncClient() as client:
        try:
            headers = {}
            if auth_token:
                headers["Authorization"] = f"Bearer {auth_token}"
            
            # sessionID 쿠키는 필수, 기존 쿠키와 결합
            session_cookie = f"sessionID={user_id}"
            if cookies:
                headers["Cookie"] = f"{cookies}; {session_cookie}"
            else:
                headers["Cookie"] = session_cookie
                
            response = await client.get(
                f"{BACKEND_BASE_URL}/api/users/{user_id}/notion/{notion_page_id}",
                headers=headers
            )
            if response.status_code == 200:
                return response.json()
            else:
                return {"error": f"Failed to get notion page: {response.status_code}", "detail": response.text}
        except Exception as e:
            return {"error": f"Request failed: {str(e)}"}


@mcp.tool
async def update_notion_page(
    user_id: str,
    notion_page_id: str,
    content: str = "",
    notion_url: str = "",
    summary: str = "",
    auth_token: str = "",
    cookies: str = ""
) -> Dict[str, Any]:
    """백엔드에서 노션 페이지 정보를 수정합니다.
    
    백엔드 데이터베이스에 저장된 노션 페이지의 정보를 업데이트합니다.
    
    인자:
        user_id: 사용자 ID
        notion_page_id: 수정할 노션 페이지 ID
        content: 새로운 페이지 내용 (선택사항)
        notion_url: 새로운 노션 페이지 URL (선택사항)
        summary: 새로운 페이지 요약 (선택사항)
        auth_token: 인증 토큰 (HTTP Authorization 헤더에서 전달)
        cookies: 쿠키 문자열 (HTTP Cookie 헤더에서 전달)
        
    반환:
        수정된 노션 페이지 정보
    """
    async with httpx.AsyncClient() as client:
        try:
            headers = {}
            if auth_token:
                headers["Authorization"] = f"Bearer {auth_token}"
            
            # sessionID 쿠키는 필수, 기존 쿠키와 결합
            session_cookie = f"sessionID={user_id}"
            if cookies:
                headers["Cookie"] = f"{cookies}; {session_cookie}"
            else:
                headers["Cookie"] = session_cookie
                
            # 값이 제공된 필드만 업데이트 payload에 포함
            payload = {}
            if content:
                payload["content"] = content
            if notion_url:
                payload["notion_url"] = notion_url
            if summary:
                payload["summary"] = summary
            
            if not payload:
                return {"error": "No fields to update provided"}
                
            response = await client.put(
                f"{BACKEND_BASE_URL}/api/users/{user_id}/notion/{notion_page_id}",
                json=payload,
                headers=headers
            )
            if response.status_code == 200:
                return response.json()
            else:
                return {"error": f"Failed to update notion page: {response.status_code}", "detail": response.text}
        except Exception as e:
            return {"error": f"Request failed: {str(e)}"}


@mcp.tool
async def delete_notion_page(
    user_id: str,
    notion_page_id: str,
    auth_token: str = "",
    cookies: str = ""
) -> Dict[str, Any]:
    """백엔드에서 노션 페이지를 삭제합니다.
    
    백엔드 데이터베이스에서 특정 노션 페이지 데이터를 삭제합니다.
    
    인자:
        user_id: 사용자 ID
        notion_page_id: 삭제할 노션 페이지 ID
        auth_token: 인증 토큰 (HTTP Authorization 헤더에서 전달)
        cookies: 쿠키 문자열 (HTTP Cookie 헤더에서 전달)
        
    반환:
        삭제 결과
    """
    async with httpx.AsyncClient() as client:
        try:
            headers = {}
            if auth_token:
                headers["Authorization"] = f"Bearer {auth_token}"
            
            # sessionID 쿠키는 필수, 기존 쿠키와 결합
            session_cookie = f"sessionID={user_id}"
            if cookies:
                headers["Cookie"] = f"{cookies}; {session_cookie}"
            else:
                headers["Cookie"] = session_cookie
                
            response = await client.delete(
                f"{BACKEND_BASE_URL}/api/users/{user_id}/notion/{notion_page_id}",
                headers=headers
            )
            if response.status_code == 200:
                return response.json()
            else:
                return {"error": f"Failed to delete notion page: {response.status_code}", "detail": response.text}
        except Exception as e:
            return {"error": f"Request failed: {str(e)}"}


# -----------------------------
# 백엔드 MindMap API 도구들
# -----------------------------
@mcp.tool
async def create_mindmap(
    user_id: str,
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    auth_token: str = "",
    cookies: str = ""
) -> Dict[str, Any]:
    """백엔드에 마인드맵을 생성합니다.
    
    키워드 노드들과 엣지들로 구성된 마인드맵을 백엔드에 저장합니다.
    
    인자:
        user_id: 사용자 ID
        nodes: 키워드 노드 배열, 각 항목 포함:
            - keyword: 키워드 문자열
            - notion_page_id: 연결된 노션 페이지 ID (선택사항)
        edges: 엣지 배열, 각 항목 포함:
            - idx1: 첫 번째 노드의 인덱스
            - idx2: 두 번째 노드의 인덱스
        auth_token: 인증 토큰 (HTTP Authorization 헤더에서 전달)
        cookies: 쿠키 문자열 (HTTP Cookie 헤더에서 전달)
        
    반환:
        생성된 마인드맵 정보
    """
    async with httpx.AsyncClient() as client:
        try:
            headers = {}
            if auth_token:
                headers["Authorization"] = f"Bearer {auth_token}"
            
            # sessionID 쿠키는 필수, 기존 쿠키와 결합
            session_cookie = f"sessionID={user_id}"
            if cookies:
                headers["Cookie"] = f"{cookies}; {session_cookie}"
            else:
                headers["Cookie"] = session_cookie
                
            payload = {
                "nodes": nodes,
                "edges": edges
            }
                
            response = await client.post(
                f"{BACKEND_BASE_URL}/api/users/{user_id}/mindmap",
                json=payload,
                headers=headers
            )
            if response.status_code in [200, 201]:
                return response.json()
            else:
                return {"error": f"Failed to create mindmap: {response.status_code}", "detail": response.text}
        except Exception as e:
            return {"error": f"Request failed: {str(e)}"}


@mcp.tool
async def get_mindmap(
    user_id: str,
    auth_token: str = "",
    cookies: str = ""
) -> Dict[str, Any]:
    """백엔드에서 사용자의 마인드맵을 조회합니다.
    
    사용자의 마인드맵 데이터(노드와 엣지)를 백엔드에서 가져옵니다.
    
    인자:
        user_id: 사용자 ID
        auth_token: 인증 토큰 (HTTP Authorization 헤더에서 전달)
        cookies: 쿠키 문자열 (HTTP Cookie 헤더에서 전달)
        
    반환:
        마인드맵 데이터:
        - user_id: 사용자 ID
        - nodes: 키워드 노드 배열
        - edges: 키워드 엣지 배열
    """
    async with httpx.AsyncClient() as client:
        try:
            headers = {}
            if auth_token:
                headers["Authorization"] = f"Bearer {auth_token}"
            
            # sessionID 쿠키는 필수, 기존 쿠키와 결합
            session_cookie = f"sessionID={user_id}"
            if cookies:
                headers["Cookie"] = f"{cookies}; {session_cookie}"
            else:
                headers["Cookie"] = session_cookie
                
            response = await client.get(
                f"{BACKEND_BASE_URL}/api/users/{user_id}/mindmap",
                headers=headers
            )
            if response.status_code == 200:
                return response.json()
            else:
                return {"error": f"Failed to get mindmap: {response.status_code}", "detail": response.text}
        except Exception as e:
            return {"error": f"Request failed: {str(e)}"}


@mcp.tool
async def delete_mindmap(
    user_id: str,
    auth_token: str = "",
    cookies: str = ""
) -> Dict[str, Any]:
    """백엔드에서 사용자의 마인드맵을 삭제합니다.
    
    사용자의 모든 마인드맵 데이터를 백엔드에서 삭제합니다.
    
    인자:
        user_id: 사용자 ID
        auth_token: 인증 토큰 (HTTP Authorization 헤더에서 전달)
        cookies: 쿠키 문자열 (HTTP Cookie 헤더에서 전달)
        
    반환:
        삭제 결과
    """
    async with httpx.AsyncClient() as client:
        try:
            headers = {}
            if auth_token:
                headers["Authorization"] = f"Bearer {auth_token}"
            
            # sessionID 쿠키는 필수, 기존 쿠키와 결합
            session_cookie = f"sessionID={user_id}"
            if cookies:
                headers["Cookie"] = f"{cookies}; {session_cookie}"
            else:
                headers["Cookie"] = session_cookie
                
            response = await client.delete(
                f"{BACKEND_BASE_URL}/api/users/{user_id}/mindmap",
                headers=headers
            )
            if response.status_code == 200:
                return response.json()
            else:
                return {"error": f"Failed to delete mindmap: {response.status_code}", "detail": response.text}
        except Exception as e:
            return {"error": f"Request failed: {str(e)}"}


@mcp.tool
async def get_complete_notion_pages_with_token(
    access_token: str,
    page_ids: List[str],
    format: str = "markdown",
    max_depth: int = 10
) -> List[Dict[str, Any]]:
    """노션 액세스 토큰을 사용하여 여러 페이지의 상세 내용을 조회합니다.
    
    사용자의 노션 액세스 토큰을 직접 사용하여 페이지 ID 목록으로부터 
    각 페이지의 완전한 내용(제목, 본문, 구조 등)을 가져옵니다.
    bulk 저장을 위한 데이터 준비에 최적화되어 있습니다.
    
    인자:
        access_token: 노션 API 액세스 토큰 (get_user_info에서 얻은 토큰)
        page_ids: 조회할 노션 페이지 ID 목록
        format: 'markdown' (구조화된 내용, 추천) 또는 'plain' (단순 텍스트)  
        max_depth: 중첩 블록 처리 깊이 (기본 10)
        
    반환:
        페이지 정보 배열, 각 항목 포함:
        - page_id: 페이지 ID
        - title: 페이지 제목  
        - url: 노션 페이지 URL
        - content: 완전한 페이지 내용
        - format: 반환된 내용 포맷
        - success: 성공/실패 여부
        - error: 실패 시 오류 메시지
        
    사용 케이스:
        - "이 페이지들의 상세 내용을 모두 가져와줘"
        - "bulk 저장을 위해 여러 페이지 내용 조회"
        - "검색된 페이지들의 전체 내용 분석"
        - STEP 1-2 연결에서 효율적인 다중 페이지 처리
        
    워크플로우:
        1. get_user_info로 access_token 획득
        2. notion_search_with_user로 page_ids 획득  
        3. 이 도구로 상세 내용 조회
        4. save_bulk_notion_data_to_backend로 일괄 저장
    """
    if not access_token:
        return [{"error": "Access token is required", "success": False}]
    
    if not page_ids:
        return [{"error": "Page IDs list is empty", "success": False}]
    
    try:
        notion_client = _get_notion_client(access_token)
        results = []
        
        for page_id in page_ids:
            try:
                # 페이지 메타데이터 조회
                page = notion_client.pages.retrieve(page_id=page_id)
                title = _extract_title(page) or ""
                page_url = page.get("url", "")
                
                # 본문 블록 전체 수집(재귀)
                blocks = _list_block_children_recursive_with_client(
                    notion_client, page_id, max_depth=max_depth
                )
                
                # 마크다운 변환
                md_lines = _blocks_to_markdown(blocks)
                md_content = "\n".join(md_lines).strip()
                
                if format.lower() == "plain":
                    # 단순한 플레인 텍스트 변환
                    plain_content = (
                        md_content.replace("# ", "")
                                 .replace("## ", "")
                                 .replace("### ", "")
                                 .replace("- [x] ", "")
                                 .replace("- [ ] ", "")
                    )
                    content = plain_content
                    out_format = "plain"
                else:
                    content = md_content
                    out_format = "markdown"
                
                results.append({
                    "page_id": page_id,
                    "title": title,
                    "url": page_url,
                    "content": content,
                    "format": out_format,
                    "success": True
                })
                
            except Exception as page_error:
                results.append({
                    "page_id": page_id,
                    "title": "",
                    "url": "",
                    "content": "",
                    "format": format,
                    "success": False,
                    "error": f"Failed to retrieve page: {str(page_error)}"
                })
        
        return results
        
    except Exception as e:
        return [{"error": f"Notion client error: {str(e)}", "success": False}]


# -----------------------------
# MCP 노션 도구 (사용자별 토큰 지원)
# -----------------------------
@mcp.tool
async def notion_search_with_token(access_token: str, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """사용자의 노션 워크스페이스에서 페이지와 데이터베이스를 검색합니다.

    사용자별 노션 액세스 토큰을 사용하여 해당 사용자의 워크스페이스에서 페이지를 찾습니다.
    키워드나 구문으로 검색하여 관련 노션 페이지들을 발견할 수 있습니다.
    
    인자:
        access_token: 노션 API 액세스 토큰 (필수)
        query: 검색할 키워드 또는 구문 (예: "프로젝트", "회의록", "TODO", "아이디어")
        top_k: 반환할 검색 결과 최대 개수 (기본값: 5)

    반환:
        검색된 페이지 목록 (각 항목 포함 정보):
        - id: 페이지 ID (상세 내용 조회시 필요)
        - type: "page" 또는 "database"
        - url: 노션 페이지 URL
        - title: 페이지 제목
        
    사용 케이스:
        - "내 노션에서 '프로젝트' 관련 페이지 찾아줘"
        - "회의록 페이지들 보여줘"
        - "최근 작성한 노션 글 검색해줘"
        - STEP 1: Search and Discovery 워크플로우에서도 활용
        
    다음 단계: 상세 내용이 필요하면 각 page_id로 notion_page_content_with_token 호출
    """
    
    try:
        notion_client = _get_notion_client(access_token)
        res = notion_client.search(query=query, page_size=int(top_k))
        items: List[Dict[str, Any]] = []
        for r in res.get("results", []):
            items.append(
                {
                    "id": r.get("id"),
                    "type": r.get("object"),
                    "url": r.get("url"),
                    "title": _extract_title(r),
                }
            )
        return items
    except Exception as e:
        return [{"error": f"Notion API error: {str(e)}"}]


@mcp.tool
async def notion_page_content_with_token(
    access_token: str,
    page_id: str,
    format: str = "markdown",
    max_depth: int = 10,
) -> Dict[str, Any]:
    """사용자의 특정 노션 페이지 내용을 상세히 가져옵니다.

    페이지 ID를 알고 있을 때 해당 페이지의 전체 내용을 마크다운이나 플레인 텍스트로 가져옵니다.
    중첩된 블록, 표, 이미지 등 복잡한 구조도 처리하여 완전한 페이지 내용을 제공합니다.
    
    인자:
        access_token: 노션 API 액세스 토큰 (필수)
        page_id: 노션 페이지 ID (검색 결과나 직접 제공받은 ID)
        format: 'markdown' (구조화된 내용, 추천) 또는 'plain' (단순 텍스트)
        max_depth: 중첩 블록 처리 깊이 (기본 10, 복잡한 페이지도 충분히 처리)

    반환:
        페이지 상세 정보:
        - page_id: 페이지 ID
        - title: 페이지 제목
        - format: 반환된 내용 포맷
        - content: 완전한 페이지 내용 (텍스트, 구조, 링크 등 모두 포함)
        
    사용 케이스:
        - "이 노션 페이지 내용 보여줘"
        - "특정 페이지 분석해줘"
        - "페이지 내용을 요약해줘"
        - STEP 1-2 연결: 검색된 페이지들의 상세 내용 수집에도 사용
        
    후속 작업: 내용을 분석/요약하여 저장하려면 save_notion_data_to_backend 사용
    """
    
    try:
        notion_client = _get_notion_client(access_token)

        # 페이지 메타(제목 등)
        page = notion_client.pages.retrieve(page_id=page_id)
        title = _extract_title(page) or ""

        # 본문 블록 전체 수집(재귀) - 사용자별 클라이언트 사용
        blocks = _list_block_children_recursive_with_client(notion_client, page_id, max_depth=max_depth)

        # 변환
        md_lines = _blocks_to_markdown(blocks)
        md = "\n".join(md_lines).strip()

        if format.lower() == "plain":
            # 매우 단순한 플레인 변환(마크다운 기호 최소 제거)
            plain = (
                md.replace("# ", "")
                  .replace("## ", "")
                  .replace("### ", "")
                  .replace("- [x] ", "")
                  .replace("- [ ] ", "")
            )
            content = plain
            out_format = "plain"
        else:
            content = md
            out_format = "markdown"

        return {
            "page_id": page_id,
            "title": title,
            "format": out_format,
            "content": content,
        }
    except Exception as e:
        return {"error": f"Notion API error: {str(e)}"}

# -----------------------------
# MCP 노션 도구 (기본 토큰)
# -----------------------------
@mcp.tool
def notion_page_content(
    page_id: str,
    format: str = "markdown",
    max_depth: int = 10,
) -> Dict[str, Any]:
    """지정한 페이지의 본문을 가져옵니다(마크다운/플레인 텍스트). (기본 토큰 사용 - 호환성)

    인자:
        page_id: Notion 페이지 ID.
        format: 'markdown' 또는 'plain' 중 선택(기본값 'markdown').
        max_depth: 자식 블록 재귀 깊이(기본 10).

    반환:
        {
          "page_id": <str>,
          "title": <str>,
          "format": <'markdown'|'plain'>,
          "content": <str>
        }
    """
    try:
        _ensure_notion()
        token = os.getenv("NOTION_TOKEN")
        if not token:
            return {"error": "NOTION_TOKEN not configured"}
        
        notion_client = _get_notion_client(token)

        # 페이지 메타(제목 등)
        page = notion_client.pages.retrieve(page_id=page_id)
        title = _extract_title(page) or ""

        # 본문 블록 전체 수집(재귀)
        blocks = _list_block_children_recursive_with_client(notion_client, page_id, max_depth=max_depth)

        # 변환
        md_lines = _blocks_to_markdown(blocks)
        md = "\n".join(md_lines).strip()

        if format.lower() == "plain":
            # 매우 단순한 플레인 변환(마크다운 기호 최소 제거)
            plain = (
                md.replace("# ", "")
                  .replace("## ", "")
                  .replace("### ", "")
                  .replace("- [x] ", "")
                  .replace("- [ ] ", "")
            )
            content = plain
            out_format = "plain"
        else:
            content = md
            out_format = "markdown"

        return {
            "page_id": page_id,
            "title": title,
            "format": out_format,
            "content": content,
        }
    except Exception as e:
        return {"error": f"Notion API error: {str(e)}"}

@mcp.tool
def notion_search(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """Notion 워크스페이스에서 페이지/데이터베이스를 검색합니다. (기본 토큰 사용 - 호환성)

    인자:
        query: 전체 텍스트 검색어.
        top_k: 최대 반환 개수.

    반환:
        id, type, url, title을 담은 항목 리스트.
    """
    try:
        _ensure_notion()
        token = os.getenv("NOTION_TOKEN")
        if not token:
            return [{"error": "NOTION_TOKEN not configured"}]
        
        notion_client = _get_notion_client(token)
        res = notion_client.search(query=query, page_size=int(top_k))
        items: List[Dict[str, Any]] = []
        for r in res.get("results", []):
            items.append(
                {
                    "id": r.get("id"),
                    "type": r.get("object"),
                    "url": r.get("url"),
                    "title": _extract_title(r),
                }
            )
        return items
    except Exception as e:
        return [{"error": f"Notion API error: {str(e)}"}]




# (선택) 기존에 있던 문단 추가 도구는 유지합니다.
@mcp.tool
def notion_append_paragraph(page_id: str, text: str) -> Dict[str, Any]:
    """기존 페이지에 문단(paragraph) 블록을 이어 붙입니다.

    인자:
        page_id: Notion 페이지 ID.
        text: 추가할 일반 텍스트 내용.

    반환:
        page_id와 추가된 블록의 id를 담은 JSON.
    """
    _ensure_notion()
    assert isinstance(notion, Client)

    block = {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": text[:2000]}}]},
    }
    res = notion.blocks.children.append(  # type: ignore[union-attr]
        block_id=page_id,
        children=[block],
    )
    block_id = (res.get("results") or [{}])[0].get("id")
    return {"page_id": page_id, "appended_block_id": block_id}


if __name__ == "__main__":
    # STDIO 전송(transport) 방식으로 MCP 서버를 실행
    mcp.run()
