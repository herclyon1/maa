@echo off
chcp 65001 >nul
title 中继关机开关
setlocal
set FLAG=C:\ProgramData\ark-relay\state\skip-next-shutdown.flag

:menu
cls
echo.
echo   ==========================================
echo      中 继 关 机 开 关
echo   ==========================================
echo.
if exist "%FLAG%" (
  echo      当前：下一次跑完  ==^>  不关机
) else (
  echo      当前：下一次跑完  ==^>  正常关机
)
echo.
echo      [1]  下一次跑完别关机（只跳过这一次）
echo      [2]  恢复正常（跑完就关机）
echo      [0]  关掉这个窗口
echo.
set "c="
set /p c=   输入数字后回车：
if "%c%"=="1" (
  echo skip> "%FLAG%"
  goto menu
)
if "%c%"=="2" (
  if exist "%FLAG%" del "%FLAG%" >nul 2>&1
  goto menu
)
if "%c%"=="0" exit /b
goto menu
