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
    """백엔드에서 사용자 정보를 가져옵니다.
    
    인자:
        user_id: 사용자 ID
        auth_token: 인증 토큰 (선택사항)
        cookies: 쿠키 문자열 (선택사항)
        
    반환:
        사용자 정보 (id, nickname, notion_user_id, access_token, refresh_token)
    """
    async with httpx.AsyncClient() as client:
        try:
            headers = {}
            if auth_token:
                headers["Authorization"] = f"Bearer {auth_token}"
            if cookies:
                headers["Cookie"] = cookies
                
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
async def save_notion_data_to_backend(user_id: str, notion_page_id: str, notion_page_text: str) -> Dict[str, Any]:
    """백엔드에 노션 페이지 데이터를 저장합니다.
    
    인자:
        user_id: 사용자 ID
        notion_page_id: 노션 페이지 ID
        notion_page_text: 노션 페이지 텍스트 내용
        
    반환:
        저장 결과
    """
    async with httpx.AsyncClient() as client:
        try:
            payload = {
                "notionPageId": notion_page_id,
                "notionPageText": notion_page_text
            }
            response = await client.post(
                f"{BACKEND_BASE_URL}/api/users/{user_id}/notion",
                json=payload
            )
            if response.status_code in [200, 201]:
                return response.json()
            else:
                return {"error": f"Failed to save notion data: {response.status_code}", "detail": response.text}
        except Exception as e:
            return {"error": f"Request failed: {str(e)}"}


# -----------------------------
# MCP 노션 도구 (사용자별 토큰 지원)
# -----------------------------
@mcp.tool
async def notion_search_with_user(user_id: str, query: str, top_k: int = 5, auth_token: str = "", cookies: str = "") -> List[Dict[str, Any]]:
    """사용자의 Notion 워크스페이스에서 페이지/데이터베이스를 검색합니다.

    인자:
        user_id: 사용자 ID
        query: 전체 텍스트 검색어.
        top_k: 최대 반환 개수.

    반환:
        id, type, url, title을 담은 항목 리스트.
    """
    # 사용자 정보 가져오기 - 직접 HTTP 호출
    async with httpx.AsyncClient() as client:
        try:
            headers = {}
            if auth_token:
                headers["Authorization"] = f"Bearer {auth_token}"
            if cookies:
                headers["Cookie"] = cookies
                
            response = await client.get(
                f"{BACKEND_BASE_URL}/api/users/{user_id}",
                headers=headers
            )
            if response.status_code != 200:
                return [{"error": f"Failed to get user info: {response.status_code}"}]
            user_info = response.json()
        except Exception as e:
            return [{"error": f"Request failed: {str(e)}"}]
    
    # 백엔드 응답에서 access_token 추출 (소문자 필드명)
    access_token = user_info.get("access_token") or user_info.get("AccessToken")
    if not access_token:
        return [{"error": "No access_token found for user", "user_info": user_info}]
    
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


@mcp.tool
async def notion_page_content_with_user(
    user_id: str,
    page_id: str,
    format: str = "markdown",
    max_depth: int = 10,
    auth_token: str = "",
    cookies: str = ""
) -> Dict[str, Any]:
    """사용자의 지정한 페이지의 본문을 가져옵니다(마크다운/플레인 텍스트).

    인자:
        user_id: 사용자 ID
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
    # 사용자 정보 가져오기 - 직접 HTTP 호출
    async with httpx.AsyncClient() as client:
        try:
            headers = {}
            if auth_token:
                headers["Authorization"] = f"Bearer {auth_token}"
            if cookies:
                headers["Cookie"] = cookies
                
            response = await client.get(
                f"{BACKEND_BASE_URL}/api/users/{user_id}",
                headers=headers
            )
            if response.status_code != 200:
                return {"error": f"Failed to get user info: {response.status_code}"}
            user_info = response.json()
        except Exception as e:
            return {"error": f"Request failed: {str(e)}"}
    
    # 백엔드 응답에서 access_token 추출 (소문자 필드명)
    access_token = user_info.get("access_token") or user_info.get("AccessToken")
    if not access_token:
        return {"error": "No access_token found for user", "user_info": user_info}
    
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
