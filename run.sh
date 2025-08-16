#!/bin/bash

# AI Agent Web Server 실행 스크립트
# 사용법: ./run.sh 또는 bash run.sh

echo "🚀 AI Agent Web Server를 시작합니다..."
echo "📍 현재 디렉토리: $(pwd)"

# 가상환경 활성화 및 서버 시작
if [ -d "venv" ]; then
    echo "🔄 가상환경을 활성화합니다..."
    source venv/bin/activate
    
    echo "📦 Python 버전: $(python --version)"
    echo "📍 서버 주소: http://localhost:8081"
    echo "📖 API 문서: http://localhost:8081/docs"
    echo ""
    echo "서버를 중지하려면 Ctrl+C를 누르세요."
    echo "========================================"
    
    python start_server.py
else
    echo "❌ 가상환경이 없습니다. 먼저 다음 명령어를 실행하세요:"
    echo "   /opt/homebrew/bin/python3 -m venv venv"
    echo "   source venv/bin/activate"
    echo "   pip install -r requirements.txt"
fi
