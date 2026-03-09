#!/bin/bash
# start.sh — 启动 Fangame 后端服务
# 支持局域网和外网访问（监听所有网卡 0.0.0.0）
#
# 用法：
#   ./start.sh          # 默认端口 8768
#   PORT=9000 ./start.sh  # 自定义端口

# 读取端口，默认 8768
PORT=${PORT:-8769}

# 进入项目根目录
ROOT_DIR="$(dirname "$0")"
cd "$ROOT_DIR" || exit 1

# 激活虚拟环境（优先使用本项目 venv，回退到 fangame001 的 venv）
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
    PYTHON=python
elif [ -f "venv/Scripts/activate" ]; then
    source venv/Scripts/activate
    PYTHON=python
elif [ -f "/d/test/fangame001/venv/Scripts/python.exe" ]; then
    PYTHON=/d/test/fangame001/venv/Scripts/python.exe
else
    PYTHON=python
fi

# 进入 backend 目录
cd backend || exit 1

echo "=============================="
echo "  Fangame 服务器启动"
echo "  端口：$PORT"
echo "  本机访问：http://localhost:$PORT"
echo "  局域网/外网：http://<服务器IP>:$PORT"
echo "=============================="

# 启动服务（--host 0.0.0.0 允许外部访问）
"$PYTHON" -m uvicorn main:app --host 0.0.0.0 --port "$PORT"
