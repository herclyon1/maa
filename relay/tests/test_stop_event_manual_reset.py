"""停服务的事件必须是手动复位的（CreateEvent 第二个参数为 1）。

2026-09-07 09:02 部署停服务时，relay.log 里手机通道打了一整段 traceback
（AttributeError: 'NoneType' object has no attribute 'peek'）。
它的 except 里明明先问了 stop()，可 stop_event 是自动复位事件：
主循环、手机通道、心跳三个线程都用 WaitForSingleObject(…, 0) 轮它，
谁先看到谁把信号吃掉，其余线程看到的就是「没停」。手机通道于是把
被 close() 掐断的连接当成意外断线；心跳同理可能发不出下线。
2026-08-31 几次「卡在 STOP_PENDING」也是同一个根：主循环没抢到信号。
"""
import re
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "service.py"
text = SRC.read_text(encoding="utf-8")
# 只盯 stop_event；proc_evt（进程退出）只有主循环一个消费者，自动复位是对的。
hits = re.findall(r"self\.stop_event\s*=\s*win32event\.CreateEvent\(None,\s*(\d)\s*,", text)
print("  stop_event 的 CreateEvent 第二个参数：", hits)
ok = hits == ["1"]

# 第二道：main() 返回后必须自己报告 STOPPED 并 os._exit，不能交给解释器收尾。
# 2026-09-07 实测：主流程 09:16:42 返回、剩下的全是 daemon 线程，SCM 却 27.5 秒后
# 才看到停止，15 秒硬保险一次都没触发（Timer 线程在收尾阶段拿不到 GIL）。
run = text[text.index("def SvcDoRun"):text.index("\n    def ", text.index("def SvcDoRun") + 10)]
tail_ok = ("ReportServiceStatus(win32service.SERVICE_STOPPED)" in run
           and run.rstrip().endswith("os._exit(0)"))
print("  SvcDoRun 以 ReportServiceStatus(STOPPED) + os._exit 收尾：", tail_ok)
ok = ok and tail_ok
print("all checks passed" if ok else "FAILED: stop_event 不是手动复位（CreateEvent 第二个参数要是 1）")
sys.exit(0 if ok else 1)
