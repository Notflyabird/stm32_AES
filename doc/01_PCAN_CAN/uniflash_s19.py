#!/usr/bin/env python3
"""
UniFlash S19 Flash Script
Target : MSPM0G3518
Debugger: XDS110 (USB)
UniFlash : C:\\ti\\uniflash_9.4.1
"""

import os
import sys
import subprocess
import time

# ── 配置 ─────────────────────────────────────────────────────────────────────
UNIFLASH_DSLITE = r"C:\ti\uniflash_9.4.1\dslite.bat"

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

# ccxml 与本脚本放在同一目录
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
CCXML_PATH  = os.path.join(SCRIPT_DIR, "mspm0g3518_xds110.ccxml")

# ── 辅助函数 ─────────────────────────────────────────────────────────────────

def log(msg: str):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def ensure_ccxml():
    """如果 ccxml 不存在则自动生成。"""
    if not os.path.isfile(CCXML_PATH):
        with open(CCXML_PATH, "w", encoding="utf-8") as f:
            f.write(CCXML_CONTENT)
        log(f"Generated config file: {CCXML_PATH}")
    else:
        log(f"Using existing config file: {CCXML_PATH}")


def get_s19_path() -> str:
    """2选1：1=默认路径，2=拖入文件。"""
    DEFAULT_S19 = r"U:\sandbox_2\TI\01_code\AA\build\fbl_posm_lin.Debug\bin\geely_posm_fbl_utip.s19"
    print("\nSelect S19 file source:")
    print(f"  [1] Default : {DEFAULT_S19}")
    print(f"  [2] Custom  : drag & drop or enter path manually")
    while True:
        choice = input("Enter choice [1/2]: ").strip()
        if choice == "1":
            if not os.path.isfile(DEFAULT_S19):
                raise FileNotFoundError(f"S19 file not found: {DEFAULT_S19}")
            return DEFAULT_S19
        elif choice == "2":
            while True:
                raw = input("Enter S19 file path: ").strip().strip('"').strip("'")
                if not raw:
                    print("  Path cannot be empty. Please try again.")
                    continue
                if not os.path.isfile(raw):
                    print(f"  File not found: {raw}")
                    continue
                return raw
        else:
            print("  Invalid choice. Please enter 1 or 2.")


# ── 主流程 ───────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  UniFlash S19 Flash Tool  |  MSPM0G3518 + XDS110")
    print("=" * 60)

    # 1. 检查 dslite.bat
    if not os.path.isfile(UNIFLASH_DSLITE):
        log(f"[ERROR] dslite.bat not found: {UNIFLASH_DSLITE}")
        sys.exit(1)

    # 2. 准备 ccxml
    ensure_ccxml()

    # 3. 获取 S19 路径
    s19_path = get_s19_path()

    log(f"S19 file  : {s19_path}")
    log(f"Device    : MSPM0G3518")
    log(f"Debugger  : XDS110")
    log("Flashing, please wait...")
    print()

    # 4. 调用 dslite
    cmd = [UNIFLASH_DSLITE, "-c", CCXML_PATH, "-f", s19_path]
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    print(proc.stdout)

    # 5. 结果处理
    if proc.returncode == 0:
        log("[SUCCESS] Flash completed successfully!")
    else:
        log(f"[ERROR] Flash failed, return code: {proc.returncode}")

    print()
    input("Press Enter to exit...")
    sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
