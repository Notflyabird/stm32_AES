#!/usr/bin/env python3
"""
UniFlash S19 Flash Tool  —  调试器固定、自动检测 MCU 批量烧录
Target   : MSPM0G3518
Debugger : XDS110 (USB，始终插着)
UniFlash : C:\\ti\\uniflash_9.4.1

工作流程
  WAIT_MCU   : 用 dslite --verify 轻量探针轮询，不烧录
               → 连接失败（MCU不在）→ 继续等待
               → 连接成功（MCU在）  → FLASH
  FLASH      : 执行完整烧录
               → 成功 → WAIT_REMOVAL
               → 失败 → 回 WAIT_MCU
  WAIT_REMOVAL: 继续用 verify 轮询
               → 连接失败（MCU移走）→ 回 WAIT_MCU，准备下一块
               → 连接成功（MCU还在）→ 继续等待
  Ctrl+C 退出
"""

import os
import sys
import subprocess
import time

# ── 配置 ─────────────────────────────────────────────────────────────────────
UNIFLASH_DSLITE = r"C:\ti\uniflash_9.4.1\dslite.bat"

S19_PATH = r"C:\Users\uik07726\Desktop\sw.sys.geely_posm\build\geely_posm.Debug\bin\SLL_TBSW_geely_posm.s19"

# 轮询间隔（秒）
POLL_INTERVAL = 0.5

# dslite verify 探针超时（秒）；连不上 MCU 时 dslite 一般 3~5s 返回错误
PROBE_TIMEOUT = 15

CCXML_CONTENT = """\
<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<configurations XML_version="1.2" id="configurations_0">
    <configuration XML_version="1.2" id="configuration_0">
        <instance XML_version="1.2" desc="Texas Instruments XDS110 USB Debug Probe" href="connections/TIXDS110_Connection.xml" id="Texas Instruments XDS110 USB Debug Probe" xml="TIXDS110_Connection.xml" xmlpath="connections"/>
        <connection XML_version="1.2" desc="Texas Instruments XDS110 USB Debug Probe" id="Texas Instruments XDS110 USB Debug Probe">
            <instance XML_version="1.2" href="drivers/tixds510cs_dap.xml" id="drivers" xml="tixds510cs_dap.xml" xmlpath="drivers"/>
            <instance XML_version="1.2" href="drivers/tixds510cortexM0.xml" id="drivers" xml="tixds510cortexM0.xml" xmlpath="drivers"/>
            <instance XML_version="1.2" href="drivers/tixds510sec_ap.xml" id="drivers" xml="tixds510sec_ap.xml" xmlpath="drivers"/>
            <property Type="choicelist" Value="2" id="SWD Mode Settings">
                <choice Name="SWD Mode - Aux COM port is target TDO pin" value="nothing"/>
            </property>
            <platform XML_version="1.2" id="platform_0">
                <instance XML_version="1.2" desc="MSPM0G3518" href="devices/MSPM0G3518.xml" id="MSPM0G3518" xml="MSPM0G3518.xml" xmlpath="devices"/>
                <device HW_revision="1" XML_version="1.2" desc="MSPM0G3518" description="ARM Cortex-M0 Plus MCU" id="MSPM0G3518" partnum="MSPM0G3518" simulation="no"/>
            </platform>
        </connection>
    </configuration>
</configurations>
"""

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CCXML_PATH = os.path.join(SCRIPT_DIR, "mspm0g3518_xds110.ccxml")

# ── 辅助函数 ─────────────────────────────────────────────────────────────────

def log(msg: str):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def ensure_ccxml():
    if not os.path.isfile(CCXML_PATH):
        with open(CCXML_PATH, "w", encoding="utf-8") as f:
            f.write(CCXML_CONTENT)
        log(f"Generated config: {CCXML_PATH}")


# 这些关键字出现在 dslite 输出中，说明 SWD/JTAG 连接失败（MCU 不在线）
_CONN_FAIL_KEYWORDS = [
    "failed to connect",
    "error connecting",
    "can't open",
    "cannot open",
    "no cortex",
    "no target",
    "0 targets",
    "jtag communication",
    "swd communication",
    "connection failed",
    "device not found",
    "unable to connect",
    "cortexm_openjtag",       # TI 常见错误前缀
    "tijtag",                 # TI JTAG 层错误
    "failed to find",
]


def _run_dslite(extra_args: list) -> tuple[int, str]:
    """运行 dslite 并返回 (returncode, stdout_lower)。"""
    cmd = [UNIFLASH_DSLITE, "-c", CCXML_PATH] + extra_args
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=PROBE_TIMEOUT,
        )
        return proc.returncode, proc.stdout
    except subprocess.TimeoutExpired:
        # 超时说明 dslite 正在与 MCU 通信（连接成功但操作慢）
        return -1, ""
    except Exception as exc:
        return -2, str(exc)


def probe_mcu() -> bool:
    """
    使用 dslite --verify 非破坏性探针检测 MCU 是否在线。
    返回 True  = MCU 在线（verify 执行到了，不管内容匹配与否）
    返回 False = MCU 不在线（连接失败）
    """
    rc, out = _run_dslite(["-v", S19_PATH])
    out_lower = out.lower()

    # 连接层错误 → MCU 不在
    if any(k in out_lower for k in _CONN_FAIL_KEYWORDS):
        return False

    # dslite 超时（rc == -1）→ 正在通信，MCU 在
    if rc == -1:
        return True

    # 其他情况（verify pass/fail 都算 MCU 在线）
    return True


def do_flash() -> bool:
    """执行完整烧录，打印 dslite 输出，返回是否成功。"""
    cmd = [UNIFLASH_DSLITE, "-c", CCXML_PATH, "-f", S19_PATH]
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    for line in proc.stdout.splitlines():
        print(f"    {line}", flush=True)
    return proc.returncode == 0


# ── 主流程 ───────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  UniFlash 批量烧录  |  MSPM0G3518 + XDS110（调试器固定）")
    print("  按 Ctrl+C 退出")
    print("=" * 60)

    if not os.path.isfile(UNIFLASH_DSLITE):
        log(f"[ERROR] 未找到 dslite.bat: {UNIFLASH_DSLITE}")
        sys.exit(1)

    if not os.path.isfile(S19_PATH):
        log(f"[ERROR] 未找到 S19 文件: {S19_PATH}")
        sys.exit(1)

    ensure_ccxml()

    log(f"S19 文件  : {S19_PATH}")
    log(f"目标芯片  : MSPM0G3518")
    log(f"调试器    : XDS110（始终连接）")
    log(f"探针方式  : dslite --verify（非破坏性）")
    print()

    flash_count = 0

    try:
        # ── 状态 1：等待 MCU 上线 ────────────────────────────────────────
        while True:
            log("[ WAIT ] 等待 MCU 上线（正在探针检测…）")
            while not probe_mcu():
                log("  MCU 未响应，继续等待…")
                time.sleep(POLL_INTERVAL)

            # ── 状态 2：烧录 ─────────────────────────────────────────────
            flash_count += 1
            log(f"[ FLASH ] 检测到 MCU，开始烧录 #{flash_count} …")
            success = do_flash()
            print()

            if success:
                log(f"[ OK ]  烧录 #{flash_count} 成功！请移走板子，换下一块。")
            else:
                log(f"[ ERR ] 烧录 #{flash_count} 失败！请检查连接。")

            print()

            # ── 状态 3：等待 MCU 下线（板子被换掉）────────────────────────
            log("[ WAIT ] 等待板子移走…")
            while probe_mcu():
                time.sleep(POLL_INTERVAL)

            log("  MCU 已离线，准备烧录下一块。")
            print("-" * 60)

    except KeyboardInterrupt:
        print()
        log(f"已退出。本次共完成烧录 {flash_count} 块板。")
        sys.exit(0)


if __name__ == "__main__":
    main()
