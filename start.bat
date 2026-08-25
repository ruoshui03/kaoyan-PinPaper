@echo off
chcp 65001 >nul
title 考研拼好卷系统
cd /d "%~dp0"

echo ===================================================
echo   正在启动 考研拼好卷系统...
echo   系统将在默认浏览器中自动打开: http://localhost:8501
echo ===================================================

:: 自动在系统默认浏览器中打开页面
start http://localhost:8501

:: 直接使用 python.exe -m streamlit，彻底避免 Windows 对中文路径的 launcher 乱码错误
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m streamlit run app.py --browser.gatherUsageStats=false
) else (
    python -m streamlit run app.py --browser.gatherUsageStats=false
)

if errorlevel 1 (
    echo.
    echo 启动发生异常，请检查上方提示。
    pause
)
