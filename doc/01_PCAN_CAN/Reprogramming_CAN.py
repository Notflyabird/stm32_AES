#!/usr/bin/env python3
"""
CAN ECU Reprogramming – APP (STM32 F103 FBL UDS)
===================================================
Project : STM32 F103 Bootloader UDS
Hardware: PCAN-USB, CAN 2.0 @ 500 kbps
APP     : APP_files/a.hex (Intel HEX, uncompressed)

CAN IDs:
  TX: 0x123  (tester → ECU, 物理请求)
  RX: 0x122  (ECU → tester, 响应)

Transport: ISO 15765-2 (ISO-TP) over CAN 2.0

刷写序列 (与 STM32 F103 FBL UDS 实现完全对齐):
  1. [0x10 03]  Enter Extended Session
  2. [0x10 82]  Enter Programming Session (suppress ×2, ECU 重启进入编程会话)
  3. [0x27 01/02]  Security Access (AES-CMAC 密钥)
  4. [0x31 01 FF00]  Erase Memory (按 S19 地址范围)
  5. For each data block:
        [0x34]  RequestDownload
        [0x36]  TransferData (×N, 同时累计 CRC16-CCITT)
        [0x37]  TransferExit
  6. [0x31 01 0202]  CheckIntegrity (CRC16 校验, 与 ECU 内部累计值比对)
  7. [0x31 01 0205]  CheckCompleteAndCompatible (版本一致性 + CRC, 置位 APP 有效标志)
  8. [0x11 01]  ECUReset – hardReset

重要: 此 FBL 没有实现 0x0212 (CheckMemory), 不要调用!

Usage:
  python Reprogramming_CAN.py [--app APP_files/a.hex]

Author: zlc  2026-06-12
"""

import sys
import time
import argparse

from can_tp_transport import CanTpTransport
from can_uds_log import CanUdsLog, read_current_session
from s19_parser import parse_app_image
from can_tp_config import APP_FILE

# CAN Service modules
from Service_10_CAN import service_10_extended_session, service_10_programming_session_suppress
from Service_11_CAN import service_11_hard_reset
from Service_27_CAN import service_27_security_access
from Service_31_Erase_CAN import (
    service_31_erase_memory,
    service_31_check_integrity_0202,
    service_31_check_complete_and_compatible_0205,
)
from Service_34_36_37_CAN import download_vbf_block


# --------------------------------------------------------------------------
def run_reprogramming(app_path: str, log: CanUdsLog, tp: CanTpTransport) -> bool:
    """
    执行完整的 CAN 刷写流程 (无压缩).
    所有步骤通过则返回 True.
    """
    log.info("=" * 60)
    log.info("CAN ECU Reprogramming START (uncompressed)")
    log.info(f"APP file : {app_path}")
    log.info(f"CAN route: TX=0x{tp.tx_id:X} RX=0x{tp.rx_id:X}")
    log.info("=" * 60)

    # ---------------------------------------------------------------
    # 0. 解析 APP 文件
    # ---------------------------------------------------------------
    log.start_test("Parse APP file")
    hdr, blocks = parse_app_image(app_path)
    log.info(f"APP parsed OK")
    log.info(f"  first_address  : 0x{hdr.first_address:08X}")
    log.info(f"  total_size     : 0x{hdr.total_size:08X} ({hdr.total_size} bytes)")
    log.info(f"  data_format    : 0x{hdr.data_format_identifier:02X} (uncompressed)")
    log.info(f"  erase region   : {[(hex(a), hex(l)) for a, l in hdr.erase_regions]}")
    log.info(f"  data blocks    : {len(blocks)}")
    for b in blocks:
        log.info(f"    {b}")

    log.result(True, description="S19 parse OK")

    # ---------------------------------------------------------------
    # 1. Extended Session (10 03) → Programming Session (10 82)
    # ---------------------------------------------------------------
    log.info("--- 1/8 Entering Extended Session ---")
    service_10_extended_session(tp, log)
    time.sleep(0.1)

    log.info("--- 2/8 Entering Programming Session (suppress ×2) ---")
    service_10_programming_session_suppress(tp, log)
    service_10_programming_session_suppress(tp, log)
    # ECU 在收到 Programming Session 后会软重启进入 FBL 编程模式
    log.info("等待 ECU 重启进入编程模式...")
    time.sleep(1.0)

    # ---------------------------------------------------------------
    # [FBL] Read current session – 确认 ECU 已进入 FBL 模式
    # ---------------------------------------------------------------
    log.info("--- Read Session (in FBL) ---")
    read_current_session(tp, log)

    # ---------------------------------------------------------------
    # 3. Security Access (27 01/02)
    # ---------------------------------------------------------------
    log.info("--- 3/8 Security Access ---")
    if not service_27_security_access(tp, log):
        log.error("Security access failed")
        return False

    # ---------------------------------------------------------------
    # 3. Erase Memory (31 01 FF00)
    # ---------------------------------------------------------------
    log.info("--- 4/8 Erase Memory ---")
    for address, erase_len in hdr.erase_regions:
        if not service_31_erase_memory(tp, log, address, erase_len):
            log.error(f"Erase failed @ 0x{address:08X}")
            return False
        log.info(f"Erase OK @ 0x{address:08X} len=0x{erase_len:08X}")

    # ---------------------------------------------------------------
    # 4. Download S19 data blocks (34 → 36×N → 37, 累计 CRC)
    # ---------------------------------------------------------------
    log.info("--- 5/8 Download Data Blocks ---")
    crc = 0xFFFF  # CRC 初始值, 与 FBL 的 crc_init() 一致
    for idx, blk in enumerate(blocks):
        log.info(f"Downloading block {idx + 1}/{len(blocks)}: {blk}")
        ok, crc = download_vbf_block(tp, log, hdr, blk,
                                      track_crc=True, initial_crc=crc)
        if not ok:
            log.error(f"Block {idx + 1} download FAILED: {blk}")
            return False
        log.info(f"Block {idx + 1}/{len(blocks)} download OK, CRC=0x{crc:04X}")

    # ---------------------------------------------------------------
    # 5. CheckIntegrity – 0x31 01 0202 (CRC16 校验)
    # ---------------------------------------------------------------
    log.info("--- 6/8 CheckIntegrity (CRC16) ---")
    if not service_31_check_integrity_0202(tp, log, crc):
        log.error("CheckIntegrity (CRC16) failed – data may be corrupted")
        # 注意: 即使 CRC 不匹配, 0x0205 仍可能返回, 但 APP 标志不会置位
        # 根据 FBL 代码, 这里选择继续, 让 0x0205 给出最终结果
        log.warning("Continuing to CheckComplete...")

    # ---------------------------------------------------------------
    # 6. CheckCompleteAndCompatible – 0x31 01 0205
    # ---------------------------------------------------------------
    log.info("--- 7/8 CheckCompleteAndCompatible ---")
    if not service_31_check_complete_and_compatible_0205(tp, log):
        log.error("CheckCompleteAndCompatible (0x0205) failed")
        log.error("可能原因: FBL/APP 版本不匹配, 或 CRC 校验失败")
        return False

    # ---------------------------------------------------------------
    # 8. ECU Reset – 0x11 01
    # ---------------------------------------------------------------
    log.info("--- 8/8 ECU Reset ---")
    service_11_hard_reset(tp, log)

    # ---------------------------------------------------------------
    # [APP] Read current session – 等待 APP 启动后读取会话
    # ---------------------------------------------------------------
    log.info("等待 APP 启动...")
    time.sleep(3.0)

    log.info("--- Read Session (in APP) ---")
    read_current_session(tp, log)

    log.info("=" * 60)
    log.info("CAN ECU Reprogramming DONE")
    log.info("=" * 60)
    return True


# --------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="CAN ECU Reprogramming via PCAN – S19 APP (STM32 F103 FBL UDS)")
    parser.add_argument("--app", dest="app_path", default=APP_FILE,
                        help=f"APP file path (default: {APP_FILE})")
    args = parser.parse_args()

    log = CanUdsLog("Reprogramming_CAN")
    tp = CanTpTransport(logger=log)

    try:
        tp.open()
        success = run_reprogramming(args.app_path, log, tp)
    except KeyboardInterrupt:
        log.error("Interrupted by user")
        success = False
    except Exception as e:
        log.error(str(e))
        import traceback
        traceback.print_exc()
        success = False
    finally:
        tp.close()
        log.close()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
