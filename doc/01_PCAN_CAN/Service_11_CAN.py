#!/usr/bin/env python3
"""
Service 0x11 – ECUReset (CAN / UDS context)
=============================================
Standalone script for CAN-based ECU reset.

Sub-functions:
  0x01 – hardReset
  0x02 – keyOffOnReset
  0x03 – softReset
  0x04 – enableRapidPowerShutDown
  0x05 – disableRapidPowerShutDown

Positive response:
  11 xx → 51 xx
"""

import sys
import time
from can_tp_transport import CanTpTransport
from can_uds_log import (
    CanUdsLog, bytes_to_hex,
    check_positive_response, check_negative_response,
)


SID = 0x11
NRC_SUB_FUNC_NOT_SUPPORTED = 0x12


def service_11_hard_reset(tp: CanTpTransport, log: CanUdsLog) -> bool:
    """11 01 – hardReset. ECU will reboot, no response is expected after reset."""
    log.start_test("0x11 01 – ECU Reset (hardReset)")
    req = bytes([0x11, 0x01])
    log.tx(bytes_to_hex(req), "ECUReset hardReset")
    try:
        resp = tp.send_uds(req, expect_response=False)
        log.rx(bytes_to_hex(resp) if resp else "(no response – ECU reset)")
    except Exception:
        log.info("No response after reset (ECU rebooting – expected)")
        log.result(True, description="ECUReset positive (no response expected after reboot)")
        return True

    if len(resp) > 0:
        return check_positive_response(resp, SID, log, "ECUReset hardReset")
    return True


def service_11_key_off_on_reset(tp: CanTpTransport, log: CanUdsLog) -> bool:
    """11 02 – keyOffOnReset."""
    log.start_test("0x11 02 – ECU Reset (keyOffOnReset)")
    req = bytes([0x11, 0x02])
    log.tx(bytes_to_hex(req), "ECUReset keyOffOnReset")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_positive_response(resp, SID, log, "ECUReset keyOffOnReset")


def service_11_soft_reset(tp: CanTpTransport, log: CanUdsLog) -> bool:
    """11 03 – softReset."""
    log.start_test("0x11 03 – ECU Reset (softReset)")
    req = bytes([0x11, 0x03])
    log.tx(bytes_to_hex(req), "ECUReset softReset")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_positive_response(resp, SID, log, "ECUReset softReset")


# --------------------------------------------------------------------------
if __name__ == "__main__":
    log = CanUdsLog("Service_11_CAN")
    tp = CanTpTransport(logger=log)
    try:
        tp.open()
        service_11_hard_reset(tp, log)
    except Exception as e:
        log.error(str(e))
    finally:
        tp.close()
        log.close()
        sys.exit(0 if log.all_passed else 1)
