#!/usr/bin/env python3
"""
Service 0x34 / 0x36 / 0x37 – Download orchestration (CAN)
============================================================
Combines RequestDownload → TransferData (×N) → TransferExit
for a single S19 data block over CAN/ISO-TP.

与 STM32 F103 FBL 的下载流程完全对齐:
  1. 0x34 RequestDownload  → 获取 max_block_size
  2. 0x36 TransferData ×N  → 分块发送数据，同时累计 CRC16-CCITT
  3. 0x37 TransferExit     → 结束传输

CRC16 累计方式与 FBL 的 CRC.c 一致:
  - crc_init() 设置初始值 0xFFFF
  - 每个 TransferData 块调用 crc16_ccitt(data, len) 累加
  - 最终的 CRCValue 用于 0x0202 CheckIntegrity

Usage:
  python Service_34_36_37_CAN.py  (uses default VBF from config)
"""

import sys
import time
from can_tp_transport import CanTpTransport
from can_uds_log import CanUdsLog, bytes_to_hex
from s19_parser import parse_app_image, S19DataBlock, S19Header
from can_tp_config import APP_S19_FILE

from Service_34_CAN import service_34_request_download
from Service_36_CAN import service_36_transfer_data
from Service_37_CAN import service_37_transfer_exit
from Service_31_Erase_CAN import crc16_ccitt


def download_vbf_block(tp: CanTpTransport, log: CanUdsLog,
                        header: S19Header, block: S19DataBlock,
                        inter_frame_delay: float = 0.01,
                        track_crc: bool = True,
                        initial_crc: int = 0xFFFF) -> tuple:
    """
    下载单个数据块 (S19):
      34 → 36 (×N) → 37

    参数:
      track_crc:   是否累计 CRC16 (与 FBL 内部 crc16_ccitt 累加一致)
      initial_crc: CRC 初始值 (第一次调用用 0xFFFF, 后续块用前一次返回值)

    返回:
      (success: bool, crc_value: int)
      success=True 表示下载成功
      crc_value 为累计后的 CRC16 值
    """
    log.info(f"--- Downloading block: {block} ---")

    # 0x34 Request Download
    max_block = service_34_request_download(
        tp, log,
        data_format=header.data_format_identifier,
        address=block.address,
        length=block.length,
    )

    if max_block == 0:
        log.error("RequestDownload failed or returned zero block size")
        return False, initial_crc

    # 0x36 Transfer Data (chunked)
    data       = block.data
    offset     = 0
    block_seq  = 1
    total      = len(data)
    transferred = 0
    crc        = initial_crc

    # Effective payload per 0x36 = max_block - 2 (SID + seq bytes)
    chunk_size = max(1, max_block - 2)

    while offset < total:
        chunk     = data[offset:offset + chunk_size]
        step_desc = (f"0x36 block={block_seq}  "
                     f"offset={offset}/{total}  ({offset*100//total}%)")
        log.start_test(step_desc)

        if not service_36_transfer_data(tp, log, block_seq, chunk):
            log.error(f"TransferData failed at offset {offset}")
            return False, crc

        # 累计 CRC16 (与 FBL 的 crc16_ccitt 累加方式一致)
        if track_crc:
            crc = crc16_ccitt(chunk, crc)

        offset      += len(chunk)
        transferred += len(chunk)
        block_seq    = (block_seq % 0xFF) + 1   # wraps 1..0xFF
        time.sleep(inter_frame_delay)

    log.info(f"Transfer complete: {transferred} bytes sent  CRC16=0x{crc:04X}")

    # 0x37 Transfer Exit
    exit_ok = service_37_transfer_exit(tp, log)

    return exit_ok, crc


# --------------------------------------------------------------------------
if __name__ == "__main__":
    log = CanUdsLog("Service_34_36_37_CAN")
    tp = CanTpTransport(logger=log)
    try:
        tp.open()
        hdr, blocks = parse_app_image(APP_S19_FILE)
        log.info(f"S19: {hdr}")
        log.info(f"Data blocks: {len(blocks)}")

        from Service_10_CAN import service_10_programming_session
        from Service_27_CAN import service_27_security_access
        from Service_31_Erase_CAN import service_31_erase_memory

        service_10_programming_session(tp, log)
        time.sleep(0.1)
        service_27_security_access(tp, log)
        time.sleep(0.1)

        for address, length in hdr.erase_regions:
            service_31_erase_memory(tp, log, address, length)
            time.sleep(0.1)

        crc = 0xFFFF
        for blk in blocks:
            ok, crc = download_vbf_block(tp, log, hdr, blk,
                                          track_crc=True, initial_crc=crc)
            if not ok:
                log.error(f"Block download failed: {blk}")
                break

        log.info(f"Final accumulated CRC16: 0x{crc:04X}")

    except Exception as e:
        log.error(str(e))
        import traceback
        traceback.print_exc()
    finally:
        tp.close()
        log.close()
        sys.exit(0 if log.all_passed else 1)
