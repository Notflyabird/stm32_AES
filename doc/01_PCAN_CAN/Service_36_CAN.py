#!/usr/bin/env python3
"""
Service 0x36 – TransferData (CAN / UDS context)
=================================================
Standalone script for CAN-based TransferData.

Request:  36 <block_seq> <data...>
Response: 76 <block_seq> [<data...>]

Block sequence number: 1-based, wraps 1..0xFF (i.e., 1, 2, 3, ... FF, 1, 2, ...)

From the log:
  Tx: 14 00 36 01 ...  (multi-frame, first frame with 20 data bytes)
  Rx: 02 76 01         (response with block_seq=1 confirmed)

  Tx: 14 00 36 02 ...  (next block, seq=2)
  Rx: 02 76 02         (response with block_seq=2)

  Tx: 14 00 36 51 ...  (block_seq=0x51, wrapping)
  Rx: 02 76 51         (response)
"""

import sys
from can_tp_transport import CanTpTransport
from can_uds_log import (
    CanUdsLog, bytes_to_hex,
    check_positive_response, check_negative_response,
)


SID = 0x36

NRC_INCORRECT_MSG_LENGTH        = 0x13
NRC_REQUEST_OUT_OF_RANGE        = 0x31
NRC_UPLOAD_DOWNLOAD_NOT_ACCEPTED = 0x70
NRC_TRANSFER_DATA_SUSPENDED     = 0x71
NRC_GENERAL_PROGRAMMING_FAILURE = 0x72


def service_36_transfer_data(tp: CanTpTransport, log: CanUdsLog,
                              block_seq: int, data: bytes) -> bool:
    """
    TransferData – send one block of data to the ECU.

    block_seq: sequence number (1-based, wraps at 0xFF → 1).
    data:      payload bytes for this block.

    Returns True on positive response.
    """
    desc = f"0x36 – TransferData  seq={block_seq}  len={len(data)}"
    log.start_test(desc)

    req = bytes([SID, block_seq & 0xFF]) + data
    log.tx(bytes_to_hex(req), "TransferData")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))

    passed = check_positive_response(resp, SID, log, "TransferData positive response")
    if passed:
        # Log block sequence number echo from response
        if len(resp) >= 2:
            log.info(f"TransferData seq {block_seq} confirmed")
    return passed


# --------------------------------------------------------------------------
if __name__ == "__main__":
    log = CanUdsLog("Service_36_CAN")
    tp = CanTpTransport(logger=log)
    try:
        tp.open()

        from Service_10_CAN import service_10_programming_session
        from Service_27_CAN import service_27_security_access
        from Service_34_CAN import service_34_request_download
        from lin_tp_vbf_parser import parse_vbf
        from can_tp_config import VBF_FILE

        service_10_programming_session(tp, log)
        service_27_security_access(tp, log)

        hdr, blocks = parse_vbf(VBF_FILE)
        blk = blocks[0]
        max_block = service_34_request_download(tp, log,
                                                  data_format=hdr.data_format_identifier,
                                                  address=blk.address,
                                                  length=blk.length)

        if max_block > 0:
            chunk = blk.data[:min(len(blk.data), max_block - 2)]
            service_36_transfer_data(tp, log, 1, chunk)
    except Exception as e:
        log.error(str(e))
        import traceback
        traceback.print_exc()
    finally:
        tp.close()
        log.close()
        sys.exit(0 if log.all_passed else 1)
