#!/usr/bin/env python3
"""
LIN ECU Reprogramming – Uncompressed VBF (No LZSS)
====================================================
Project : TI LIN  (No SBL – direct APP download)
Hardware: PCAN-USB Pro FD, channel 1
VBF     : PNORFlashArea_RTSW_NO_LZSS.vbf  (raw / uncompressed, data_format_identifier=0x00)

Reprogramming sequence (LIN, no SBL):
  1.  [0x10 02]  Enter Programming Session
  2.  [0x27 01/02]  Security Access (Seed + Key)
  3.  [0x31 01 FF00]  Erase Memory (per VBF erase regions)
  4.  For each VBF data block:
        [0x34]  RequestDownload
        [0x36]  TransferData  (×N chunks)
        [0x37]  TransferExit
  5.  [0x31 01 0212]  CheckMemory (signature verification)
  6.  [0x31 01 0205]  CheckCompleteAndCompatible
  7.  [0x11 01]  ECUReset – hardReset

Usage:
  python Reprogramming_LIN_NO_LZSS.py [--vbf path/to/file.vbf]

Author: Generated  2026-05-11
"""

import sys
import time
import argparse

from lin_tp_transport import LinTpTransport
from lin_tp_vbf_parser import parse_vbf
from lin_uds_log import LinUdsLog, bytes_to_hex
from lin_tp_config import VBF_FILE_NO_LZSS

# Service modules
from Service_10 import (service_10_programming_session_suppress,)
from Service_11 import service_11_hard_reset
from Service_27 import service_27_security_access
from Service_31_Erase import (service_31_erase_memory,
                               service_31_check_memory,
                               service_31_check_complete_and_compatible_0205)
from Service_34_36_37 import download_vbf_block


# --------------------------------------------------------------------------
def run_reprogramming(vbf_path: str, log: LinUdsLog, tp: LinTpTransport) -> bool:
    """
    Execute the full LIN reprogramming sequence using an uncompressed VBF.
    Returns True if all steps passed.
    """
    log.info("=" * 60)
    log.info("LIN ECU Reprogramming START (No LZSS / uncompressed)")
    log.info(f"VBF file : {vbf_path}")
    log.info("=" * 60)

    # ---------------------------------------------------------------
    # 0. Parse VBF
    # ---------------------------------------------------------------
    log.start_test("Parse VBF file")
    hdr, blocks = parse_vbf(vbf_path)
    log.info(f"VBF parsed OK")
    log.info(f"  sw_part_number  : {hdr.sw_part_number}")
    log.info(f"  sw_version      : {hdr.sw_version}")
    log.info(f"  sw_part_type    : {hdr.sw_part_type}")
    log.info(f"  data_format     : 0x{hdr.data_format_identifier:02X} "
             f"({'LZSS compressed' if hdr.data_format_identifier == 0x10 else 'uncompressed/raw'})")
    log.info(f"  ecu_address     : 0x{hdr.ecu_address:08X}")
    log.info(f"  erase regions   : {[(hex(a), hex(l)) for a,l in hdr.erase_regions]}")
    log.info(f"  data blocks     : {len(blocks)}")
    for b in blocks:
        log.info(f"    {b}")

    if hdr.data_format_identifier != 0x00:
        log.error(
            f"Expected uncompressed VBF (data_format_identifier=0x00), "
            f"got 0x{hdr.data_format_identifier:02X}. Aborting."
        )
        return False

    log.result(True, description="VBF parse OK")

    # ---------------------------------------------------------------
    # 1. Enter Programming Session (10 82 × 2, no response expected)
    # ---------------------------------------------------------------
    service_10_programming_session_suppress(tp, log)
    service_10_programming_session_suppress(tp, log)
    time.sleep(1.0)   # wait for ECU to restart and become ready

    # ---------------------------------------------------------------
    # 2. Security Access
    # ---------------------------------------------------------------
    if not service_27_security_access(tp, log):
        log.error("Security access failed")
        return False

    # ---------------------------------------------------------------
    # 3. Erase Memory
    # ---------------------------------------------------------------
    for address, erase_len in hdr.erase_regions:
        if not service_31_erase_memory(tp, log, address, erase_len):
            log.error(f"Erase failed @ 0x{address:08X}")
            return False
        log.info(f"Erase OK @ 0x{address:08X} len=0x{erase_len:08X}")

    # ---------------------------------------------------------------
    # 4. Download VBF data blocks (uncompressed – data_format=0x00)
    # ---------------------------------------------------------------
    for idx, blk in enumerate(blocks):
        log.info(f"Downloading block {idx + 1}/{len(blocks)}: {blk}")
        ok = download_vbf_block(tp, log, hdr, blk)
        if not ok:
            log.error(f"Block {idx + 1} download FAILED: {blk}")
            return False
        log.info(f"Block {idx + 1}/{len(blocks)} download OK")

    # ---------------------------------------------------------------
    # 5. Check Memory – 0x31 01 0212 + VBF sw_signature_dev
    # ---------------------------------------------------------------
    if not service_31_check_memory(tp, log, hdr.sw_signature_dev,
                                    fallback_sig_hex=hdr.sw_signature):
        log.error("CheckMemory (signature verification) failed")
        return False

    # ---------------------------------------------------------------
    # 6. Check Complete and Compatible – 0x31 01 0205
    # ---------------------------------------------------------------
    if not service_31_check_complete_and_compatible_0205(tp, log):
        log.error("CheckCompleteAndCompatible (0x0205) failed")
        return False

    # ---------------------------------------------------------------
    # 7. ECU Reset
    # ---------------------------------------------------------------
    service_11_hard_reset(tp, log)

    log.info("=" * 60)
    log.info("LIN ECU Reprogramming DONE (No LZSS)")
    log.info("=" * 60)
    return True


# --------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="LIN ECU Reprogramming via PCAN-USB Pro FD – uncompressed VBF (No SBL)")
    parser.add_argument("--vbf", default=VBF_FILE_NO_LZSS,
                        help=f"VBF file path (default: {VBF_FILE_NO_LZSS})")
    args = parser.parse_args()

    log = LinUdsLog("Reprogramming_LIN_NO_LZSS")
    tp  = LinTpTransport(logger=log)

    try:
        tp.open()
        success = run_reprogramming(args.vbf, log, tp)
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
