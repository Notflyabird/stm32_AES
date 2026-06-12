#!/usr/bin/env python3
"""
Service 0x34 / 0x36 / 0x37 – Download orchestration (LIN)
===========================================================
Combines RequestDownload → TransferData (×N) → TransferExit
for a single VBF data block.

Individual service modules:
  Service_34.py – RequestDownload
  Service_36.py – TransferData
  Service_37.py – TransferExit
"""

import sys
import time
from lin_tp_transport import LinTpTransport
from lin_uds_log import LinUdsLog
from lin_tp_vbf_parser import parse_vbf, VbfDataBlock, VbfHeader
from lin_tp_config import VBF_FILE

from Service_34 import service_34_request_download
from Service_36 import service_36_transfer_data
from Service_37 import service_37_transfer_exit


def download_vbf_block(tp: LinTpTransport, log: LinUdsLog,
                        header: VbfHeader, block: VbfDataBlock) -> bool:
    """
    Download a single VBF data block:
      34 → 36 (×N) → 37
    Returns True on success.
    """
    log.info(f"--- Downloading block: {block} ---")

    # 0x34 Request Download
    max_block = service_34_request_download(
        tp, log,
        data_format=header.data_format_identifier,
        address=block.address,
        length=block.length,
    )

    # 0x36 Transfer Data (chunked)
    data       = block.data
    offset     = 0
    block_seq  = 1
    total      = len(data)
    transferred = 0

    # Effective payload per 0x36 = max_block - 2 (SID + seq bytes)
    chunk_size = max(1, max_block - 2)

    while offset < total:
        chunk     = data[offset:offset + chunk_size]
        step_desc = (f"0x36 block={block_seq}  "
                     f"offset={offset}/{total}  ({offset*100//total}%)")
        log.start_test(step_desc)

        if not service_36_transfer_data(tp, log, block_seq, chunk):
            log.error(f"TransferData failed at offset {offset}")
            return False

        offset      += len(chunk)
        transferred += len(chunk)
        block_seq    = (block_seq % 0xFF) + 1   # wraps 1..0xFF
        time.sleep(0.01)

    log.info(f"Transfer complete: {transferred} bytes sent")

    # 0x37 Transfer Exit
    return service_37_transfer_exit(tp, log)


# --------------------------------------------------------------------------
if __name__ == "__main__":
    log = LinUdsLog("Service_34_36_37")
    tp  = LinTpTransport(logger=log)
    try:
        tp.open()
        hdr, blocks = parse_vbf(VBF_FILE)
        log.info(f"VBF: {hdr}")
        log.info(f"Data blocks: {len(blocks)}")

        from Service_10 import service_10_programming_session
        from Service_27 import service_27_security_access
        from Service_31_Erase import service_31_erase_memory

        service_10_programming_session(tp, log)
        service_27_security_access(tp, log)

        for address, length in hdr.erase_regions:
            service_31_erase_memory(tp, log, address, length)

        for blk in blocks:
            ok = download_vbf_block(tp, log, hdr, blk)
            if not ok:
                log.error(f"Block download failed: {blk}")
                break

    except Exception as e:
        log.error(str(e))
        import traceback; traceback.print_exc()
    finally:
        tp.close()
        log.close()
        sys.exit(0 if log.all_passed else 1)

