@echo off
chcp 65001 >nul
title 中继关机开关
setlocal
rem 这个开关必须走中继自己的写入路径，不许自己写文件。
rem 2026-09-08：状态收口把「下次跑完不关机」从 skip-next-shutdown.flag 搬进了
rem state.json，而这个 bat 还在写旧文件——按下去界面显示「不关机」，中继照常
rem 关机，而且一声不吭。凡是中继会读的状态，只能由中继的代码写。
rem The code is the installed relay's: {app}\versions\<current.txt> (relay/pkg_layout.py).
rem C:\ProgramData\ark-relay keeps only the data (state\); the ark_relay copy there is
rem the old relay's, frozen at the switch-over, and goes when the old relay is removed.
rem Without an installed relay (still on the old service) the old folder is used and the
rem menu says so.
rem CRLF line endings (.gitattributes): with LF only, cmd.exe loses its place in this
rem file and runs fragments of lines as commands (2026-10-11 on the machine).
set "APP=C:\Program Files\ArkRelay"
rem The relay's own Python where it is installed (the version folders are built for it),
rem else AUTO-MAS's.
set "PY=%APP%\runtime\python\python.exe"
if not exist "%PY%" set "PY=D:\ark\automas\environment\python\python.exe"
set "DATA=C:\ProgramData\ark-relay"
set "CODE="
if exist "%APP%\current.txt" for /f "usebackq delims=" %%v in ("%APP%\current.txt") do set "CODE=%APP%\versions\%%v"
if defined CODE if not exist "%CODE%\ark_relay\__init__.py" set "CODE="
set "OLDCODE="
if not defined CODE set "OLDCODE=1"
if not defined CODE set "CODE=%DATA%"

:menu
cls
echo.
echo   ==========================================
echo      中 继 关 机 开 关
echo   ==========================================
echo.
rem `call` first: for /f runs the command through cmd /c, which drops the first and the
rem last quote of a line that starts with one, and the Python path then no longer parses
rem (the menu said 「读不出来」 every time; 2026-10-11 on the machine).
for /f "delims=" %%s in ('call "%PY%" -c "import sys; sys.path.insert(0, r'%CODE%'); from ark_relay.modes import skip_armed; from pathlib import Path; print('已记下，还没用上' if skip_armed(Path(r'%DATA%\state')) else '没记着')" 2^>nul') do set STATE=%%s
if "%STATE%"=="" (
  echo      当前：读不出来 —— 中继没装好，或者 Python 路径不对
  echo      ^(应为 %PY%^)
) else (
  echo      当前「下次跑完不关机」：%STATE%
)
if defined OLDCODE echo      （没找到安装版中继 %APP%\current.txt，用的是旧中继 %DATA% 的代码）
echo.
echo      [1]  下次跑完不关机（一次性：下一趟早班/晚班跑完不关，开到再下一趟跑完才关）
echo      [2]  撤回还没用上的标记（下一趟跑完照常关机；用掉了就没什么可撤）
echo      [0]  关掉这个窗口
echo.
set "c="
set /p c=   输入数字后回车：
if "%c%"=="1" (
  "%PY%" -c "import sys; sys.path.insert(0, r'%CODE%'); from ark_relay.modes import set_skip_shutdown; from pathlib import Path; ok, msg = set_skip_shutdown(Path(r'%DATA%\state'), True); print(msg); sys.exit(0 if ok else 1)"
  if errorlevel 1 (
    echo.
    echo      没设上！上面那行是原因。按任意键回菜单。
    pause >nul
  )
  goto menu
)
if "%c%"=="2" (
  "%PY%" -c "import sys; sys.path.insert(0, r'%CODE%'); from ark_relay.modes import set_skip_shutdown; from pathlib import Path; ok, msg = set_skip_shutdown(Path(r'%DATA%\state'), False); print(msg); sys.exit(0 if ok else 1)"
  if errorlevel 1 (
    echo.
    echo      没撤回！上面那行是原因。按任意键回菜单。
    pause >nul
  )
  goto menu
)
if "%c%"=="0" exit /b
goto menu
