#!/usr/bin/env python3
"""
CAN ECU Reprogramming – S19 APP (STM32 F103 FBL UDS)
=======================================================
Project : STM32 F103 Bootloader UDS
Hardware: PCAN-USB, CAN 2.0 @ 500 kbps
APP     : APP_files/a.s19 (S-record, uncompressed)

CAN IDs:
  TX: 0x123  (tester → ECU)
  RX: 0x122  (ECU → tester)

刷写序列:
  1. [0x10 02]  Enter Programming Session
  2. [0x27 01/02]  Security Access (AES-CMAC)
  3. [0x31 01 FF00]  Erase Memory
  4. For each S19 data block:
        [0x34]  RequestDownload
        [0x36]  TransferData (×N, 累计 CRC16)
        [0x37]  TransferExit
  5. [0x31 01 0202]  CheckIntegrity (CRC16)
  6. [0x31 01 0205]  CheckCompleteAndCompatible
  7. [0x11 01]  ECUReset

Usage:
  python Reprogramming_CAN_LZSS.py [--s19 path/to/a.s19]
"""

import sys
import time
import argparse

from can_tp_transport import CanTpTransport
from can_uds_log import CanUdsLog
from s19_parser import parse_app_image
from can_tp_config import APP_S19_FILE

from Service_10_CAN import service_10_programming_session_suppress
from Service_11_CAN import service_11_hard_reset
from Service_27_CAN import service_27_security_access
from Service_31_Erase_CAN import (
    service_31_erase_memory,
    service_31_check_integrity_0202,
    service_31_check_complete_and_compatible_0205,
)
from Service_34_36_37_CAN import download_vbf_block


# --------------------------------------------------------------------------
def run_reprogramming(s19_path: str, log: CanUdsLog, tp: CanTpTransport) -> bool:
    log.info("=" * 60)
    log.info("CAN ECU Reprogramming START (S19 / uncompressed)")
    log.info(f"APP file : {s19_path}")
    log.info(f"CAN route: TX=0x{tp.tx_id:X} RX=0x{tp.rx_id:X}")
    log.info("=" * 60)

    # 0. Parse S19
    log.start_test("Parse S19 APP file")
    hdr, blocks = parse_app_image(s19_path)
    log.info(f"S19 parsed OK")
    log.info(f"  first_address: 0x{hdr.first_address:08X}")
    log.info(f"  total_size   : 0x{hdr.total_size:08X} ({hdr.total_size} bytes)")
    log.info(f"  data_format  : 0x{hdr.data_format_identifier:02X} (uncompressed)")
    log.info(f"  erase region : {[(hex(a), hex(l)) for a, l in hdr.erase_regions]}")
    log.info(f"  blocks       : {len(blocks)}")
    log.result(True, description="S19 parse OK")

    # 1. Programming Session (10 82 suppress ×2)
    log.info("--- 1/7 Entering Programming Session ---")
    service_10_programming_session_suppress(tp, log)
    service_10_programming_session_suppress(tp, log)
    time.sleep(1.0)

    # 2. Security Access
    log.info("--- 2/7 Security Access ---")
    if not service_27_security_access(tp, log):
        log.error("Security access failed")
        return False

    # 3. Erase
    log.info("--- 3/7 Erase Memory ---")
    for address, erase_len in hdr.erase_regions:
        if not service_31_erase_memory(tp, log, address, erase_len):
            log.error(f"Erase failed @ 0x{address:08X}")
            return False

    # 4. Download (with CRC accumulation)
    log.info("--- 4/7 Download Data Blocks ---")
    crc = 0xFFFF
    for idx, blk in enumerate(blocks):
        ok, crc = download_vbf_block(tp, log, hdr, blk,
                                      track_crc=True, initial_crc=crc)
        if not ok:
            log.error(f"Block {idx + 1} download FAILED")
            return False
        log.info(f"Block {idx + 1}/{len(blocks)} OK, CRC=0x{crc:04X}")

    # 5. CheckIntegrity (CRC16)
    log.info("--- 5/7 CheckIntegrity (CRC16) ---")
    service_31_check_integrity_0202(tp, log, crc)

    # 6. CheckComplete (version + CRC → set APP valid flag)
    log.info("--- 6/7 CheckCompleteAndCompatible ---")
    if not service_31_check_complete_and_compatible_0205(tp, log):
        log.error("CheckComplete failed")
        return False

    # 7. ECU Reset
    log.info("--- 7/7 ECU Reset ---")
    service_11_hard_reset(tp, log)

    log.info("=" * 60)
    log.info("CAN ECU Reprogramming DONE")
    log.info("=" * 60)
    return True


# --------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="CAN ECU Reprogramming via PCAN – S19 APP (STM32 F103 FBL UDS)")
    parser.add_argument("--s19", dest="s19_path", default=APP_S19_FILE,
                        help=f"S19 APP file path (default: {APP_S19_FILE})")
    args = parser.parse_args()

    log = CanUdsLog("Reprogramming_CAN_LZSS")
    tp = CanTpTransport(logger=log)

    try:
        tp.open()
        success = run_reprogramming(args.s19_path, log, tp)
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
