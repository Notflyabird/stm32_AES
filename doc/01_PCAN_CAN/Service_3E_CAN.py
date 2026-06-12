#!/usr/bin/env python3
"""
Service 0x3E – TesterPresent (CAN / UDS context)
==================================================
Standalone script for CAN-based TesterPresent.

Used to keep the diagnostic session alive (prevent S3 timeout).

Request:  3E 00  (zeroSubFunction)
          3E 80  (suppress positive response)
Response: 7E 00  (positive – only if not suppressed)
"""

import sys
import time
from can_tp_transport import CanTpTransport
from can_uds_log import (
    CanUdsLog,
    check_positive_response, check_no_response,
)


SID = 0x3E


def service_3e_tester_present(tp: CanTpTransport, log: CanUdsLog) -> bool:
    """3E 00 – TesterPresent."""
    log.start_test("0x3E 00 – TesterPresent")
    req = bytes([0x3E, 0x00])
    resp = tp.send_uds(req)
    return check_positive_response(resp, SID, log, "TesterPresent positive response")


def service_3e_tester_present_suppress(tp: CanTpTransport, log: CanUdsLog) -> bool:
    """3E 80 – TesterPresent with suppress positive response."""
    log.start_test("0x3E 80 – TesterPresent (suppress positive response)")
    req = bytes([0x3E, 0x80])
    resp = tp.send_uds(req, expect_response=False)
    return check_no_response(resp, log, "No response expected (suppress bit set)")


# --------------------------------------------------------------------------
if __name__ == "__main__":
    log = CanUdsLog("Service_3E_CAN")
    tp = CanTpTransport(logger=log)
    try:
        tp.open()
        service_3e_tester_present(tp, log)
    except Exception as e:
        log.error(str(e))
    finally:
        tp.close()
        log.close()
        sys.exit(0 if log.all_passed else 1)
