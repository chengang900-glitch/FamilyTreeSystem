#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."

if [ ! -d ".venv" ]; then
  echo "[1/3] 创建虚拟环境"
  python3 -m venv .venv
  echo "[2/3] 安装依赖"
  .venv/bin/pip install -r server/requirements.txt
else
  echo "[1/3] 虚拟环境已存在"
fi

echo "[3/3] 启动服务"
.venv/bin/python server/run.py
