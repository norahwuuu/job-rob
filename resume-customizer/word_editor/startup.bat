@echo off
REM 简历优化服务 - 启动脚本
REM 将此文件放入 Windows 启动文件夹即可开机自启
REM 启动文件夹路径: %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup

cd /d "%~dp0"

REM 检查 Python 是否可用
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Python 未安装或未添加到 PATH
    pause
    exit /b 1
)

REM 启动系统托盘服务
start "" pythonw tray_launcher.py

echo 简历优化服务已启动（系统托盘模式）
