@echo off
chcp 65001 >nul
title 中继关机开关
setlocal
rem 这个开关必须走中继自己的写入路径，不许自己写文件。
rem 2026-09-08：状态收口把「下一次别关机」从 skip-next-shutdown.flag 搬进了
rem state.json，而这个 bat 还在写旧文件——按下去界面显示「不关机」，中继照常
rem 关机，而且一声不吭。凡是中继会读的状态，只能由中继的代码写。
set PY=D:\ark\automas\environment\python\python.exe
set RELAY=C:\ProgramData\ark-relay

:menu
cls
echo.
echo   ==========================================
echo      中 继 关 机 开 关
echo   ==========================================
echo.
for /f "delims=" %%s in ('"%PY%" -c "import sys; sys.path.insert(0, r'%RELAY%'); from ark_relay.modes import skip_armed; from pathlib import Path; print('不关机' if skip_armed(Path(r'%RELAY%\state')) else '正常关机')" 2^>nul') do set STATE=%%s
if "%STATE%"=="" (
  echo      当前：读不出来 —— 中继没装好，或者 Python 路径不对
  echo      ^(应为 %PY%^)
) else (
  echo      当前：下一次跑完  ==^>  %STATE%
)
echo.
echo      [1]  下一次跑完别关机（只跳过这一次）
echo      [2]  恢复正常（跑完就关机）
echo      [0]  关掉这个窗口
echo.
set "c="
set /p c=   输入数字后回车：
if "%c%"=="1" (
  "%PY%" -c "import sys; sys.path.insert(0, r'%RELAY%'); from ark_relay.modes import set_skip_shutdown; from pathlib import Path; ok, msg = set_skip_shutdown(Path(r'%RELAY%\state'), True); print(msg); sys.exit(0 if ok else 1)"
  if errorlevel 1 (
    echo.
    echo      没设上！上面那行是原因。按任意键回菜单。
    pause >nul
  )
  goto menu
)
if "%c%"=="2" (
  "%PY%" -c "import sys; sys.path.insert(0, r'%RELAY%'); from ark_relay.modes import set_skip_shutdown; from pathlib import Path; ok, msg = set_skip_shutdown(Path(r'%RELAY%\state'), False); print(msg); sys.exit(0 if ok else 1)"
  if errorlevel 1 (
    echo.
    echo      没取消！上面那行是原因。按任意键回菜单。
    pause >nul
  )
  goto menu
)
if "%c%"=="0" exit /b
goto menu
