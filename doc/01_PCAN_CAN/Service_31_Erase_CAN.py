#!/usr/bin/env python3
"""
Service 0x31 – RoutineControl (CAN / UDS context for STM32 F103 FBL)
======================================================================
STM32 F103 Bootloader UDS 实现的 0x31 服务。

Routine IDs (根据 FBL 源码):
  0xFF00 – EraseMemory       : 31 01 FF 00 <addr 4B> <len 4B>  → 71 01 FF 00
  0x0202 – CheckIntegrity    : 31 01 02 02 <CRC16 2B>          → 71 01 02 02 <status>
                                 status=0x10: CRC 匹配
                                 status=0x01: CRC 不匹配
  0x0205 – CheckComplete     : 31 01 02 05                    → 71 01 02 05 <status>
                                 status=0x10: 版本+CRC 通过, APP 标志已置位
                                 status=0x01: 版本不匹配
                                 status=0x12: 版本通过但 CRC 失败

注意: 0x0212 (CheckMemory) 在此 FBL 中未实现，不要调用!
"""

import sys
import struct
import time
from can_tp_transport import CanTpTransport
from can_uds_log import (
    CanUdsLog, bytes_to_hex,
    check_positive_response,
)
from can_tp_config import APP_FILE, P2_STAR_TIMEOUT_MS
from s19_parser import parse_app_image


SID = 0x31
ROUTINE_ERASE_MEMORY   = 0xFF00
ROUTINE_CHECK_INTEGRITY = 0x0202
ROUTINE_CHECK_COMPLETE  = 0x0205


# ==========================================================================
# CRC16-CCITT (多项式 0x1021, 初始值 0xFFFF)
# 与 FBL 中 Core/Src/CRC.c 的实现完全一致
# ==========================================================================

def crc16_ccitt(data: bytes, crc: int = 0xFFFF) -> int:
    """
    计算 CRC16-CCITT，与 STM32 FBL 的 CRC.c 实现一致。
    多项式: 0x1021, 初始值: 0xFFFF

    支持增量计算: 传入上一次的 crc 值即可连续计算。
    """
    for byte in data:
        crc ^= (byte << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc = crc << 1
        crc &= 0xFFFF
    return crc


def compute_crc16(data: bytes) -> int:
    """计算整个数据块的 CRC16-CCITT。"""
    return crc16_ccitt(data, 0xFFFF)


# ==========================================================================
# Erase Memory – 0x31 01 FF00
# ==========================================================================

def service_31_erase_memory(tp: CanTpTransport, log: CanUdsLog,
                             address: int, length: int) -> bool:
    """
    擦除内存例程。
    address/length 必须与 VBF 头部的 erase 条目匹配。

    请求: 31 01 FF 00 <address 4B big-endian> <length 4B big-endian>
    响应: 71 01 FF 00
    """
    desc = f"0x31 01 FF00 – EraseMemory @ 0x{address:08X} len=0x{length:08X}"
    log.start_test(desc)

    req = (bytes([SID, 0x01, 0xFF, 0x00])
           + struct.pack(">I", address)
           + struct.pack(">I", length))
    # Flash erase takes longer than P2. Use P2* extended timeout (5000ms).
    resp = tp.send_uds(req, timeout_ms=P2_STAR_TIMEOUT_MS)

    return check_positive_response(resp, SID, log, "EraseMemory positive response")


# ==========================================================================
# CheckIntegrity – 0x31 01 0202 (CRC16 校验)
# ==========================================================================

def service_31_check_integrity_0202(tp: CanTpTransport, log: CanUdsLog,
                                     crc_value: int) -> bool:
    """
    CheckIntegrity – 发送 CRC16 与 ECU 内部累计的 CRC 比较。

    FBL 实现在 TransferData 过程中用 crc16_ccitt() 累计计算 CRC，
    然后在 0x0202 请求中比对。

    请求: 31 01 02 02 <CRC16_H> <CRC16_L>
    响应: 71 01 02 02 <status>
          status=0x10: CRC 匹配
          status=0x01: CRC 不匹配
    """
    log.start_test("0x31 01 0202 – CheckIntegrity (CRC16)")

    crc_bytes = struct.pack(">H", crc_value & 0xFFFF)
    req = bytes([SID, 0x01, 0x02, 0x02]) + crc_bytes
    resp = tp.send_uds(req)

    passed = check_positive_response(resp, SID, log, "CheckIntegrity positive response")
    if passed and len(resp) >= 5:
        status = resp[4]
        if status == 0x10:
            log.info("CheckIntegrity status: 0x10 (CRC match)")
        elif status == 0x01:
            log.info("CheckIntegrity status: 0x01 (CRC mismatch)")
            passed = False
        else:
            log.info(f"CheckIntegrity status: 0x{status:02X}")
    return passed


# ==========================================================================
# CheckCompleteAndCompatible – 0x31 01 0205
# ==========================================================================

def service_31_check_complete_and_compatible_0205(tp: CanTpTransport,
                                                   log: CanUdsLog) -> bool:
    """
    CheckCompleteAndCompatible – 版本一致性 + CRC 检查。

    FBL 逻辑:
      - 检查 FBL 版本号 == APP 版本号
      - 检查 CRC 结果 (crc_check_result)
      - 如果都通过: 调用 Set_APP_valid_flag() 置位 APP 有效标志
      - 然后 ECU Reset 后跳转到 APP

    请求: 31 01 02 05
    响应: 71 01 02 05 <status>
          status=0x10: 版本+CRC 都通过, APP 有效标志已置位
          status=0x01: FBL/APP 版本不匹配
          status=0x12: 版本匹配但 CRC 检查失败
    """
    log.start_test("0x31 01 0205 – CheckCompleteAndCompatible")
    req = bytes([SID, 0x01, 0x02, 0x05])
    resp = tp.send_uds(req)

    passed = check_positive_response(resp, SID, log,
                                     "CheckCompleteAndCompatible positive response")
    if passed and len(resp) >= 5:
        status = resp[4]
        status_map = {
            0x10: "version+CRC OK, APP valid flag set",
            0x01: "FBL/APP version mismatch",
            0x12: "version OK but CRC check failed",
        }
        status_name = status_map.get(status, f"unknown(0x{status:02X})")
        log.info(f"CheckComplete status: 0x{status:02X} ({status_name})")
        if status != 0x10:
            passed = False
    return passed


# --------------------------------------------------------------------------
if __name__ == "__main__":
    log = CanUdsLog("Service_31_Erase_CAN")
    tp = CanTpTransport(logger=log)
    try:
        tp.open()
        hdr, blocks = parse_app_image(APP_FILE)
        log.info(f"S19: {hdr}")
        log.info(f"Erase regions: {hdr.erase_regions}")

        from Service_10_CAN import service_10_programming_session
        from Service_27_CAN import service_27_security_access

        service_10_programming_session(tp, log)
        time.sleep(0.1)
        service_27_security_access(tp, log)
        time.sleep(0.1)

        for address, length in hdr.erase_regions:
            service_31_erase_memory(tp, log, address, length)
            time.sleep(0.1)

        # 计算所有数据的累计 CRC16 (模拟 FBL 内部的累加过程)
        crc = 0xFFFF
        for blk in blocks:
            crc = crc16_ccitt(blk.data, crc)
        log.info(f"Computed CRC16 for all blocks: 0x{crc:04X}")

        service_31_check_integrity_0202(tp, log, crc)
        service_31_check_complete_and_compatible_0205(tp, log)

    except Exception as e:
        log.error(str(e))
        import traceback
        traceback.print_exc()
    finally:
        tp.close()
        log.close()
        sys.exit(0 if log.all_passed else 1)
