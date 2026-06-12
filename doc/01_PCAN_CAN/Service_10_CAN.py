#!/usr/bin/env python3
"""
Service 0x10 – DiagnosticSessionControl (CAN / UDS context)
=============================================================
Standalone script for CAN-based UDS session switching.

Works over ISO-TP with CAN IDs:
  TX: 0x123  (tester → ECU)
  RX: 0x122  (ECU → tester)

Positive responses:
  10 01 → 50 01  (default session)
  10 02 → 50 02  (programming session)
  10 03 → 50 03  (extended session)

Suppress positive response (MSB 0x80 set):
  10 81 → no response
  10 82 → no response
  10 83 → no response
"""

import sys
import time
from can_tp_transport import CanTpTransport
from can_uds_log import (
    CanUdsLog, bytes_to_hex,
    check_positive_response, check_negative_response, check_no_response,
    read_current_session,
)


SID = 0x10
NRC_SUB_FUNC_NOT_SUPPORTED   = 0x12
NRC_INCORRECT_MSG_LENGTH     = 0x13


# ==========================================================================
# Session switching
# ==========================================================================

def service_10_extended_session(tp: CanTpTransport, log: CanUdsLog) -> bool:
    """10 03 – Switch to Extended Session."""
    log.start_test("0x10 03 – Switch to Extended Session")
    req = bytes([0x10, 0x03])
    log.tx(bytes_to_hex(req), "DiagnosticSessionControl extendedSession")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_positive_response(resp, SID, log, "ExtendedSession positive response")


def service_10_programming_session(tp: CanTpTransport, log: CanUdsLog) -> bool:
    """10 02 – Switch to Programming Session."""
    log.start_test("0x10 02 – Switch to Programming Session")
    req = bytes([0x10, 0x02])
    log.tx(bytes_to_hex(req), "DiagnosticSessionControl programmingSession")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_positive_response(resp, SID, log, "ProgrammingSession positive response")


def service_10_default_session(tp: CanTpTransport, log: CanUdsLog) -> bool:
    """10 01 – Switch to Default Session."""
    log.start_test("0x10 01 – Switch to Default Session")
    req = bytes([0x10, 0x01])
    log.tx(bytes_to_hex(req), "DiagnosticSessionControl defaultSession")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_positive_response(resp, SID, log, "DefaultSession positive response")


def service_10_extended_session_suppress(tp: CanTpTransport, log: CanUdsLog) -> bool:
    """10 83 – Extended Session with suppress positive response; expect no reply."""
    log.start_test("0x10 83 – Extended Session (suppress positive response)")
    req = bytes([0x10, 0x83])
    log.tx(bytes_to_hex(req), "DiagnosticSessionControl extendedSession suppressPosRsp")
    resp = tp.send_uds(req, expect_response=False)
    log.rx(bytes_to_hex(resp) if resp else "(no response)")
    return check_no_response(resp, log, "No response expected (suppress bit set)")


def service_10_programming_session_suppress(tp: CanTpTransport, log: CanUdsLog) -> bool:
    """10 82 – Programming Session with suppress positive response; expect no reply."""
    log.start_test("0x10 82 – Programming Session (suppress positive response)")
    req = bytes([0x10, 0x82])
    log.tx(bytes_to_hex(req), "DiagnosticSessionControl programmingSession suppressPosRsp")
    resp = tp.send_uds(req, expect_response=False)
    log.rx(bytes_to_hex(resp) if resp else "(no response)")
    return check_no_response(resp, log, "No response expected (suppress bit set)")


def service_10_default_session_suppress(tp: CanTpTransport, log: CanUdsLog) -> bool:
    """10 81 – Default Session with suppress positive response; expect no reply."""
    log.start_test("0x10 81 – Default Session (suppress positive response)")
    req = bytes([0x10, 0x81])
    log.tx(bytes_to_hex(req), "DiagnosticSessionControl defaultSession suppressPosRsp")
    resp = tp.send_uds(req, expect_response=False)
    log.rx(bytes_to_hex(resp) if resp else "(no response)")
    return check_no_response(resp, log, "No response expected (suppress bit set)")


# ==========================================================================
# Test sequences
# ==========================================================================

def service_10_nrc12(tp: CanTpTransport, log: CanUdsLog) -> bool:
    """Test sub-functions that are not supported → expect 7F 10 12."""
    all_pass = True

    for subfn, desc in [(0x00, "reserved"), (0x04, "out of range"), (0xFF, "max")]:
        log.start_test(f"0x10 {subfn:02X} – NRC 0x12 ({desc})")
        req = bytes([0x10, subfn])
        log.tx(bytes_to_hex(req), f"DiagnosticSessionControl subFunction=0x{subfn:02X}")
        resp = tp.send_uds(req)
        log.rx(bytes_to_hex(resp))
        all_pass &= check_negative_response(resp, SID, NRC_SUB_FUNC_NOT_SUPPORTED, log,
                                            f"NRC 0x12 for sub-function 0x{subfn:02X}")

    return all_pass


def service_10_nrc13(tp: CanTpTransport, log: CanUdsLog) -> bool:
    """Test messages with wrong length → expect 7F 10 13."""
    all_pass = True

    # Too short: SID only
    log.start_test("0x10 – NRC 0x13 incorrectMessageLength (SID only)")
    req = bytes([0x10])
    log.tx(bytes_to_hex(req), "DiagnosticSessionControl length=1 (too short)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    all_pass &= check_negative_response(resp, SID, NRC_INCORRECT_MSG_LENGTH, log,
                                        "NRC 0x13 for length=1")

    # Too long: SID + sub-function + extra byte
    log.start_test("0x10 01 00 – NRC 0x13 incorrectMessageLength (extra byte)")
    req = bytes([0x10, 0x01, 0x00])
    log.tx(bytes_to_hex(req), "DiagnosticSessionControl length=3 (too long)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    all_pass &= check_negative_response(resp, SID, NRC_INCORRECT_MSG_LENGTH, log,
                                        "NRC 0x13 for length=3")

    return all_pass


def service_10_all_tests(tp: CanTpTransport, log: CanUdsLog):
    log.info("=" * 60)
    log.info("Service 0x10 DiagnosticSessionControl – Full Test (CAN)")
    log.info("=" * 60)

    # Read initial session
    read_current_session(tp, log)

    # Positive tests
    log.info("--- Positive Tests: Session Switching ---")
    service_10_extended_session(tp, log)
    time.sleep(0.1)
    service_10_programming_session(tp, log)
    time.sleep(0.1)
    service_10_default_session(tp, log)
    time.sleep(0.1)

    # Suppress positive response
    log.info("--- Suppress Positive Response Tests ---")
    service_10_programming_session_suppress(tp, log)
    time.sleep(0.1)
    service_10_default_session_suppress(tp, log)
    time.sleep(0.5)

    # Negative tests
    log.info("--- Negative Tests: NRC 0x12 ---")
    service_10_nrc12(tp, log)
    log.info("--- Negative Tests: NRC 0x13 ---")
    service_10_nrc13(tp, log)


# --------------------------------------------------------------------------
if __name__ == "__main__":
    log = CanUdsLog("Service_10_CAN")
    tp = CanTpTransport(logger=log)
    try:
        tp.open()
        service_10_all_tests(tp, log)
    except Exception as e:
        log.error(str(e))
        import traceback
        traceback.print_exc()
    finally:
        tp.close()
        log.close()
        sys.exit(0 if log.all_passed else 1)
