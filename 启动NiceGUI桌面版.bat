@echo off
chcp 65001 >nul
title 劳动法律师智能助理 - NiceGUI 桌面版

cd /d "%~dp0"

echo ========================================
echo   ⚖️  劳动法律师智能助理 - NiceGUI 桌面版
echo ========================================
echo.
echo 正在启动原生桌面应用...
echo 首次启动需要加载 Edge WebView2 组件
echo.
echo ========================================
echo.

python gui_nice.py

pause
