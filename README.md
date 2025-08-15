# AI Agent Web Server

프론트엔드(localhost:3000)와 백엔드(localhost:8080) 사이를 연결하는 AI 에이전트 웹 서버입니다.

## 주요 기능

1. **프론트엔드 채팅 연동**: 터미널 기반 채팅을 웹 기반으로 전환
2. **Notion API 통합**: MCP 서버를 통한 노션 API 호출
3. **백엔드 API 연동**: 사용자 정보 조회 및 노션 데이터 저장
4. **AI 에이전트**: OpenAI API를 통한 지능형 응답

## 아키텍처

```
프론트엔드 (3000) ←→ AI Agent Server (8081) ←→ 백엔드 (8080)
                              ↓
                         MCP Server (Notion API)
```

## 설치 및 실행

### 1. 의존성 설치

```bash
pip install -r requirements.txt
```

### 2. 환경 변수 설정

`.env` 파일을 생성하고 다음 변수들을 설정하세요:

```env
# OpenAI API 키 (필수)
OPENAI_API_KEY=your_openai_api_key_here

# Notion API 토큰 (필수)
NOTION_TOKEN=your_notion_token_here

# OpenAI 모델 (선택사항, 기본값: gpt-4o-mini)
OPENAI_MODEL=gpt-4o-mini

# MCP 서버 경로 (선택사항, 기본값: server.py)
MCP_SERVER_PATH=server.py

# 백엔드 API 주소 (선택사항, 기본값: http://localhost:8080)
BACKEND_BASE_URL=http://localhost:8080
```

### 3. 서버 실행

#### 방법 1: 시작 스크립트 사용
```bash
python start_server.py
```

#### 방법 2: 직접 실행
```bash
uvicorn web_server:app --host 0.0.0.0 --port 8081 --reload
```

## API 엔드포인트

### POST /api/chat
프론트엔드에서 채팅 메시지를 받아 AI 에이전트가 처리합니다.

**요청:**
```json
{
  "message": "내가 작성한 노션 글 목록을 알려줘",
  "user_id": "user123"
}
```

**응답:**
```json
{
  "response": "노션에서 다음과 같은 글들을 찾았습니다...",
  "status": "success"
}
```

### GET /api/health
서버 상태를 확인합니다.

**응답:**
```json
{
  "status": "healthy",
  "mcp_connected": true,
  "tools_count": 3
}
```

## 워크플로우

1. **프론트엔드 요청**: 사용자가 프론트엔드에서 채팅 메시지 전송
2. **AI 에이전트 처리**: OpenAI API를 통해 메시지 분석
3. **MCP 도구 활용**: 필요시 노션 API 호출 (검색, 내용 조회 등)
4. **백엔드 연동**: 
   - 사용자 정보 조회: `GET /api/users/{userID}`
   - 노션 데이터 저장: `POST /api/users/{userID}/notion`
5. **응답 반환**: 처리된 결과를 프론트엔드에 전달

## 파일 구조

- `web_server.py`: FastAPI 웹 서버 메인 파일
- `server.py`: MCP 서버 (Notion API 도구들)
- `client.py`: 기존 터미널 기반 클라이언트 (참고용)
- `start_server.py`: 서버 시작 스크립트
- `requirements.txt`: Python 의존성 목록

## 사용 예시

사용자가 "내가 작성한 노션 글 목록을 알려줘"라고 요청하면:

1. AI 에이전트가 요청을 분석
2. 백엔드에서 사용자 정보 조회
3. 노션 API로 글 목록 검색
4. 각 글의 내용을 조회하여 분석
5. 백엔드에 노션 데이터 저장
6. 사용자에게 정리된 결과 응답

## 개발자 정보

- 포트: 8081
- 개발 모드: 자동 리로드 지원
- API 문서: http://localhost:8081/docs
- 상호 검증: http://localhost:8081/redoc
