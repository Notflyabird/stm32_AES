#!/usr/bin/env python3
"""
Service 0x10 – DiagnosticSessionControl (LIN / FBL context)
============================================================
Standalone script. Run directly to test session switching.

Positive responses:
  10 01 → 50 01  (default session)
  10 02 → 50 02  (programming session)

Suppress positive response (MSB 0x80 set):
  10 81 → no response  (default session, suppressed)
  10 82 → no response  (programming session, suppressed)

Negative responses:
  NRC 0x12 – subFunctionNotSupported  : 10 00 / 10 03 / 10 04 / 10 FF
                                        (0x03 extended session not supported in FBL)
  NRC 0x13 – incorrectMessageLength   : 10  (too short) / 10 01 00 (too long)
"""

import sys
import time
from lin_tp_config import NAD_FUNCTIONAL
from lin_tp_transport import LinTpTransport
from lin_uds_log import (
    LinUdsLog, bytes_to_hex,
    check_positive_response, check_negative_response, check_no_response,
    read_current_session,
)


# --------------------------------------------------------------------------
SID  = 0x10
NRC_SUB_FUNC_NOT_SUPPORTED   = 0x12
NRC_INCORRECT_MSG_LENGTH      = 0x13


# ==========================================================================
# Positive test cases
# ==========================================================================

def service_10_default_session(tp: LinTpTransport, log: LinUdsLog) -> bool:
    log.start_test("0x10 01 – Switch to Default Session")
    req  = bytes([0x10, 0x01])
    log.tx(bytes_to_hex(req), "DiagnosticSessionControl defaultSession")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_positive_response(resp, SID, log, "DefaultSession positive response")


def service_10_programming_session(tp: LinTpTransport, log: LinUdsLog) -> bool:
    log.start_test("0x10 02 – Switch to Programming Session")
    req  = bytes([0x10, 0x02])
    log.tx(bytes_to_hex(req), "DiagnosticSessionControl programmingSession")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_positive_response(resp, SID, log, "ProgrammingSession positive response")


# ==========================================================================
# Suppress positive response (bit 7 of sub-function = 1)
# ==========================================================================

def service_10_default_session_suppress(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """10 81 – default session with suppress positive response bit; expect no reply."""
    log.start_test("0x10 81 – Default Session (suppress positive response)")
    req  = bytes([0x10, 0x81])
    log.tx(bytes_to_hex(req), "DiagnosticSessionControl defaultSession suppressPosRsp")
    resp = tp.send_uds(req, expect_response=False)
    log.rx(bytes_to_hex(resp) if resp else "(no response)")
    return check_no_response(resp, log, "No response expected (suppress bit set)")


def service_10_programming_session_suppress(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """10 82 – programming session with suppress positive response bit; expect no reply."""
    log.start_test("0x10 82 – Programming Session (suppress positive response)")
    req  = bytes([0x10, 0x82])
    log.tx(bytes_to_hex(req), "DiagnosticSessionControl programmingSession suppressPosRsp")
    resp = tp.send_uds(req, expect_response=False)
    log.rx(bytes_to_hex(resp) if resp else "(no response)")
    return check_no_response(resp, log, "No response expected (suppress bit set)")

# ==========================================================================
# NRC 0x12 – subFunctionNotSupported
# ==========================================================================

def service_10_nrc12(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """Test sub-functions that are not supported → expect 7F 10 12."""
    all_pass = True

    # Case 1: sub-function 0x00 (reserved / invalid)
    log.start_test("0x10 00 – NRC 0x12 subFunctionNotSupported (sub-function 0x00)")
    req  = bytes([0x10, 0x00])
    log.tx(bytes_to_hex(req), "DiagnosticSessionControl subFunction=0x00")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    all_pass &= check_negative_response(resp, SID, NRC_SUB_FUNC_NOT_SUPPORTED, log,
                                        "NRC 0x12 for sub-function 0x00")

    # Case 2: sub-function 0x03 (extended session – not supported in FBL)
    log.start_test("0x10 03 – NRC 0x12 subFunctionNotSupported (extended session not supported in FBL)")
    req  = bytes([0x10, 0x03])
    log.tx(bytes_to_hex(req), "DiagnosticSessionControl extendedSession (unsupported in FBL)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    all_pass &= check_negative_response(resp, SID, NRC_SUB_FUNC_NOT_SUPPORTED, log,
                                        "NRC 0x12 for sub-function 0x03 (FBL)")

    # Case 3: sub-function 0x04 (out of range)
    log.start_test("0x10 04 – NRC 0x12 subFunctionNotSupported (sub-function 0x04)")
    req  = bytes([0x10, 0x04])
    log.tx(bytes_to_hex(req), "DiagnosticSessionControl subFunction=0x04")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    all_pass &= check_negative_response(resp, SID, NRC_SUB_FUNC_NOT_SUPPORTED, log,
                                        "NRC 0x12 for sub-function 0x04")

    # Case 4: sub-function 0xFF (max, out of range)
    log.start_test("0x10 FF – NRC 0x12 subFunctionNotSupported (sub-function 0xFF)")
    req  = bytes([0x10, 0xFF])
    log.tx(bytes_to_hex(req), "DiagnosticSessionControl subFunction=0xFF")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    all_pass &= check_negative_response(resp, SID, NRC_SUB_FUNC_NOT_SUPPORTED, log,
                                        "NRC 0x12 for sub-function 0xFF")

    return all_pass


# ==========================================================================
# NRC 0x13 – incorrectMessageLengthOrInvalidFormat
# ==========================================================================

def service_10_nrc13(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """Test messages with wrong length → expect 7F 10 13."""
    all_pass = True

    # Case 1: too short – SID only, no sub-function
    log.start_test("0x10 – NRC 0x13 incorrectMessageLength (length < 2, SID only)")
    req  = bytes([0x10])
    log.tx(bytes_to_hex(req), "DiagnosticSessionControl length=1 (too short)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    all_pass &= check_negative_response(resp, SID, NRC_INCORRECT_MSG_LENGTH, log,
                                        "NRC 0x13 for length=1")

    # Case 2: too long – SID + sub-function + extra byte
    log.start_test("0x10 01 00 – NRC 0x13 incorrectMessageLength (length > 2)")
    req  = bytes([0x10, 0x01, 0x00])
    log.tx(bytes_to_hex(req), "DiagnosticSessionControl length=3 (too long)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    all_pass &= check_negative_response(resp, SID, NRC_INCORRECT_MSG_LENGTH, log,
                                        "NRC 0x13 for length=3")

    return all_pass


# ==========================================================================
# Full test sequence
# ==========================================================================

def service_10_all_tests(tp: LinTpTransport, log: LinUdsLog):
    log.info("=" * 60)
    log.info("Service 0x10 DiagnosticSessionControl – Full Test")
    log.info("=" * 60)

    # --- Read initial session ---
    read_current_session(tp, log)

    # --- Positive: session switching ---
    log.info("--- Positive Tests: Session Switching ---")
    service_10_programming_session(tp, log)
    time.sleep(0.1)
    service_10_default_session(tp, log)
    time.sleep(0.1)

    # --- Suppress positive response ---
    log.info("--- Suppress Positive Response Tests ---")
    service_10_programming_session_suppress(tp, log)
    time.sleep(0.1)
    service_10_default_session_suppress(tp, log)
    time.sleep(0.5)   # ECU may restart after default session switch

    # --- Negative: NRC 0x12 ---
    log.info("--- Negative Tests: NRC 0x12 subFunctionNotSupported ---")
    service_10_nrc12(tp, log)

    # --- Negative: NRC 0x13 ---
    log.info("--- Negative Tests: NRC 0x13 incorrectMessageLength ---")
    service_10_nrc13(tp, log)


    # --- Functional addressing (NAD=0x7E) ---
    # Per ISO 17987: functional addressing nodes shall NOT send a response
    log.info("--- Functional Addressing Tests (NAD=0x7E) – no response expected ---")

    log.start_test(f"0x10 02 [NAD={NAD_FUNCTIONAL:02X}] – Functional Addressing: Programming Session (no response)")
    req = bytes([0x10, 0x02])
    log.tx(bytes_to_hex(req), f"DiagnosticSessionControl programmingSession (NAD=0x{NAD_FUNCTIONAL:02X})")
    resp = tp.send_uds(req, nad=NAD_FUNCTIONAL, expect_response=False)
    log.rx(bytes_to_hex(resp) if resp else "(no response)")
    check_no_response(resp, log, "No response expected for functional programmingSession")
    time.sleep(0.1)

    log.start_test(f"0x10 01 [NAD={NAD_FUNCTIONAL:02X}] – Functional Addressing: Default Session (no response)")
    req = bytes([0x10, 0x01])
    log.tx(bytes_to_hex(req), f"DiagnosticSessionControl defaultSession (NAD=0x{NAD_FUNCTIONAL:02X})")
    resp = tp.send_uds(req, nad=NAD_FUNCTIONAL, expect_response=False)
    log.rx(bytes_to_hex(resp) if resp else "(no response)")
    check_no_response(resp, log, "No response expected for functional defaultSession")
    time.sleep(0.5)


# --------------------------------------------------------------------------
if __name__ == "__main__":
    log = LinUdsLog("Service_10")
    tp  = LinTpTransport(logger=log)
    try:
        tp.open()
        service_10_all_tests(tp, log)
    except Exception as e:
        log.error(str(e))
    finally:
        tp.close()
        log.close()
        sys.exit(0 if log.all_passed else 1)
