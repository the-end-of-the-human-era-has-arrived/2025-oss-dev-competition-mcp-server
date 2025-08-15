#!/usr/bin/env python3
"""
AI Agent Web Server 시작 스크립트
"""
import os
import sys
import uvicorn
from dotenv import load_dotenv

# 환경 변수 로드
load_dotenv()

def main():
    """서버 시작"""
    # 환경 변수 확인
    required_vars = ["OPENAI_API_KEY", "NOTION_TOKEN"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        print("❌ 다음 환경 변수가 설정되지 않았습니다:")
        for var in missing_vars:
            print(f"   - {var}")
        print("\n.env 파일을 확인하거나 환경 변수를 설정해주세요.")
        return 1
    
    print("🚀 AI Agent Web Server를 시작합니다...")
    print("📍 서버 주소: http://localhost:8081")
    print("📖 API 문서: http://localhost:8081/docs")
    print("🔍 헬스 체크: http://localhost:8081/api/health")
    print("💬 채팅 API: POST http://localhost:8081/api/chat")
    print("\n서버를 중지하려면 Ctrl+C를 누르세요.\n")
    
    try:
        uvicorn.run(
            "web_server:app",
            host="0.0.0.0",
            port=8081,
            reload=True,
            log_level="info"
        )
    except KeyboardInterrupt:
        print("\n👋 서버를 종료합니다.")
        return 0
    except Exception as e:
        print(f"❌ 서버 시작 중 오류가 발생했습니다: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
