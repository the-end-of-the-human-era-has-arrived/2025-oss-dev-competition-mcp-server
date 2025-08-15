#!/usr/bin/env python3
"""
AI Agent Web Server 테스트 스크립트
"""
import asyncio
import httpx
import json

async def test_server():
    """서버 테스트"""
    base_url = "http://localhost:8081"
    
    async with httpx.AsyncClient() as client:
        try:
            # 1. 헬스 체크
            print("🔍 서버 상태 확인 중...")
            response = await client.get(f"{base_url}/api/health")
            if response.status_code == 200:
                health_data = response.json()
                print(f"✅ 서버 상태: {health_data['status']}")
                print(f"🔗 MCP 연결: {health_data['mcp_connected']}")
                print(f"🛠️  도구 개수: {health_data['tools_count']}")
            else:
                print(f"❌ 헬스 체크 실패: {response.status_code}")
                return
            
            # 2. 채팅 테스트
            print("\n💬 채팅 테스트 중...")
            chat_data = {
                "message": "안녕하세요! 노션에서 제목에 '테스트'가 들어간 글을 찾아주세요.",
                "user_id": "test_user_123"
            }
            
            response = await client.post(
                f"{base_url}/api/chat",
                json=chat_data,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                chat_response = response.json()
                print(f"✅ 채팅 응답 성공:")
                print(f"📝 응답: {chat_response['response'][:200]}...")
            else:
                print(f"❌ 채팅 요청 실패: {response.status_code}")
                print(f"오류 내용: {response.text}")
                
        except httpx.ConnectError:
            print("❌ 서버에 연결할 수 없습니다.")
            print("서버가 실행 중인지 확인하세요: python start_server.py")
        except Exception as e:
            print(f"❌ 테스트 중 오류 발생: {e}")

def main():
    """메인 함수"""
    print("🧪 AI Agent Web Server 테스트를 시작합니다...")
    print("📡 테스트 대상: http://localhost:8081")
    print("-" * 50)
    
    asyncio.run(test_server())
    
    print("-" * 50)
    print("🏁 테스트 완료!")

if __name__ == "__main__":
    main()
