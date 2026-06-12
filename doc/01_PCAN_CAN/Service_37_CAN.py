#!/usr/bin/env python3
"""
Service 0x37 – TransferExit (CAN / UDS context)
=================================================
Standalone script for CAN-based TransferExit.

Request:  37 <data...>
Response: 77 [<data...>]

From the log:
  Tx: 01 37 00 00 00 00 00 00
  Rx: 01 77 aa aa aa aa aa aa
  → 37 (no extra data) → 77 (positive response)
"""

import sys
from can_tp_transport import CanTpTransport
from can_uds_log import (
    CanUdsLog,
    check_positive_response, check_negative_response,
)


SID = 0x37

NRC_REQUEST_OUT_OF_RANGE        = 0x31
NRC_UPLOAD_DOWNLOAD_NOT_ACCEPTED = 0x70


def service_37_transfer_exit(tp: CanTpTransport, log: CanUdsLog,
                              extra_data: bytes = b"") -> bool:
    """
    TransferExit – signal end of data transfer to the ECU.

    extra_data: optional parameter record bytes (can be empty).

    Returns True on positive response.
    """
    desc = f"0x37 – TransferExit  extra_len={len(extra_data)}"
    log.start_test(desc)

    req = bytes([SID]) + extra_data
    resp = tp.send_uds(req)

    return check_positive_response(resp, SID, log, "TransferExit positive response")


# --------------------------------------------------------------------------
if __name__ == "__main__":
    log = CanUdsLog("Service_37_CAN")
    tp = CanTpTransport(logger=log)
    try:
        tp.open()

        from Service_10_CAN import service_10_programming_session
        from Service_27_CAN import service_27_security_access
        from Service_34_CAN import service_34_request_download
        from Service_36_CAN import service_36_transfer_data
        from s19_parser import parse_app_image
        from can_tp_config import APP_FILE

        service_10_programming_session(tp, log)
        service_27_security_access(tp, log)

        hdr, blocks = parse_app_image(APP_FILE)
        blk = blocks[0]
        max_block = service_34_request_download(tp, log,
                                                  data_format=hdr.data_format_identifier,
                                                  address=blk.address,
                                                  length=blk.length)

        if max_block > 0:
            chunk = blk.data[:min(len(blk.data), max_block - 2)]
            service_36_transfer_data(tp, log, 1, chunk)

        service_37_transfer_exit(tp, log)
    except Exception as e:
        log.error(str(e))
        import traceback
        traceback.print_exc()
    finally:
        tp.close()
        log.close()
        sys.exit(0 if log.all_passed else 1)
