@echo off
chcp 65001 >nul
echo 正在启动 NoneBot 机器人...

cd /d "%~dp0"
if not exist venv\Scripts\activate (
    echo 错误：未找到虚拟环境，请先创建 venv。
    pause
    exit /b 1
)

call venv\Scripts\activate
if errorlevel 1 (
    echo 激活虚拟环境失败。
    pause
    exit /b 1
)
echo 虚拟环境已激活，正在运行 nb run...
nb run

rem 如果 nb run 意外退出，暂停查看信息
pause

