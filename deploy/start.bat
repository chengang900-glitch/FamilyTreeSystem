@echo off
chcp 65001 >nul
setlocal
rem 切到仓库根目录（本脚本位于 deploy/ 下），.venv 与 server\ 都在根目录
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
  echo [1/3] 创建虚拟环境...
  python -m venv .venv
  if errorlevel 1 goto :fail
  echo [2/3] 安装依赖...
  .venv\Scripts\python.exe -m pip install -r server\requirements.txt
  if errorlevel 1 goto :fail
) else (
  echo [1/3] 虚拟环境已存在，跳过安装
)

if not exist "server\webroot\index.html" (
  echo [提示] 未找到前端构建产物 server\webroot\index.html
  echo        请先执行： cd web ^&^& npm install ^&^& npm run build
)

echo [3/3] 启动服务 http://127.0.0.1:8100
.venv\Scripts\python.exe server\run.py
goto :eof

:fail
echo [错误] 环境准备失败，请检查上方输出
pause
exit /b 1
