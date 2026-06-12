#!/usr/bin/env python3
"""
Service 0x3E - TesterPresent (LIN / FBL context)
=================================================
Standalone test script. Can be run in any active session
(Default or Programming).

Positive responses:
  3E 00 → 7E 00  (keep current session, send positive response)

Suppress positive response (sub-function 0x80 set):
  3E 80 → no response  (keep session, suppress positive response)

Negative responses:
  NRC 0x12 – subFunctionNotSupported  : 3E 22 (sub-function 0x22 not supported)
  NRC 0x13 – incorrectMessageLength   : 3E      (too short, SID only)
                                        3E F1 84 10  (too long, > 2 bytes)

Functional addressing (NAD=0x7E):
  Per ISO 17987: node processes the request but does NOT send a response
  when addressed functionally, to avoid bus collisions.
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
SID = 0x3E
NRC_SUB_FUNC_NOT_SUPPORTED = 0x12
NRC_INCORRECT_MSG_LENGTH   = 0x13


# ==========================================================================
# Positive test cases
# ==========================================================================

def service_3e_tester_present(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """3E 00 – Keep current session; expect 7E 00."""
    log.start_test("0x3E 00 – TesterPresent: Keep Current Session")
    req  = bytes([0x3E, 0x00])
    log.tx(bytes_to_hex(req), "TesterPresent keepCurrentSession")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_positive_response(resp, SID, log, "TesterPresent positive response 7E 00")


# ==========================================================================
# Suppress positive response (bit 7 of sub-function = 1)
# ==========================================================================

def service_3e_suppress_positive_response(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """3E 80 – Keep session with suppress positive response bit; expect no reply."""
    log.start_test("0x3E 80 – TesterPresent (suppress positive response)")
    req  = bytes([0x3E, 0x80])
    log.tx(bytes_to_hex(req), "TesterPresent keepCurrentSession suppressPosRsp")
    resp = tp.send_uds(req, expect_response=False)
    log.rx(bytes_to_hex(resp) if resp else "(no response)")
    return check_no_response(resp, log, "No response expected (suppress bit set)")


# ==========================================================================
# NRC 0x12 – subFunctionNotSupported
# ==========================================================================

def service_3e_nrc12(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """3E 22 – sub-function 0x22 is not supported → expect 7F 3E 12."""
    log.start_test("0x3E 22 – NRC 0x12 subFunctionNotSupported")
    req  = bytes([0x3E, 0x22])
    log.tx(bytes_to_hex(req), "TesterPresent subFunction=0x22 (unsupported)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID, NRC_SUB_FUNC_NOT_SUPPORTED, log,
                                   "NRC 0x12 for sub-function 0x22")


# ==========================================================================
# NRC 0x13 – incorrectMessageLengthOrInvalidFormat
# ==========================================================================

def service_3e_nrc13(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """Test messages with wrong length → expect 7F 3E 13."""
    all_pass = True

    # Case 1: too short – SID only, no sub-function byte
    log.start_test("0x3E – NRC 0x13 incorrectMessageLength (length < 2, SID only)")
    req  = bytes([0x3E])
    log.tx(bytes_to_hex(req), "TesterPresent length=1 (too short)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    all_pass &= check_negative_response(resp, SID, NRC_INCORRECT_MSG_LENGTH, log,
                                        "NRC 0x13 for length=1 (SID only)")

    # Case 2: too long – SID + sub-function + extra bytes
    log.start_test("0x3E F1 84 10 – NRC 0x13 incorrectMessageLength (length > 2)")
    req  = bytes([0x3E, 0xF1, 0x84, 0x10])
    log.tx(bytes_to_hex(req), "TesterPresent length=4 (too long)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    all_pass &= check_negative_response(resp, SID, NRC_INCORRECT_MSG_LENGTH, log,
                                        "NRC 0x13 for length=4 (too long)")

    return all_pass


# ==========================================================================
# Functional addressing (NAD = 0x7E)
# Per ISO 17987: node shall NOT send a response when addressed functionally
# ==========================================================================

def service_3e_functional_addressing(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """
    3E 00 via functional NAD (0x7E) – no response expected (ISO 17987).
    3E 80 via functional NAD (0x7E) – no response expected.
    """
    all_pass = True

    log.start_test(f"0x3E 00 [NAD={NAD_FUNCTIONAL:02X}] – Functional Addressing: TesterPresent (no response)")
    req = bytes([0x3E, 0x00])
    log.tx(bytes_to_hex(req), f"TesterPresent keepCurrentSession (NAD=0x{NAD_FUNCTIONAL:02X})")
    resp = tp.send_uds(req, nad=NAD_FUNCTIONAL, expect_response=False)
    log.rx(bytes_to_hex(resp) if resp else "(no response)")
    all_pass &= check_no_response(resp, log,
                                  "No response expected for functional TesterPresent 3E 00")
    time.sleep(0.1)

    log.start_test(f"0x3E 80 [NAD={NAD_FUNCTIONAL:02X}] – Functional Addressing: TesterPresent suppressPosRsp (no response)")
    req = bytes([0x3E, 0x80])
    log.tx(bytes_to_hex(req), f"TesterPresent suppressPosRsp (NAD=0x{NAD_FUNCTIONAL:02X})")
    resp = tp.send_uds(req, nad=NAD_FUNCTIONAL, expect_response=False)
    log.rx(bytes_to_hex(resp) if resp else "(no response)")
    all_pass &= check_no_response(resp, log,
                                  "No response expected for functional TesterPresent 3E 80")

    return all_pass


# ==========================================================================
# Full test sequence
# ==========================================================================

def service_3e_all_tests(tp: LinTpTransport, log: LinUdsLog):
    log.info("=" * 60)
    log.info("Service 0x3E TesterPresent – Full Test")
    log.info("=" * 60)

    # --- Read initial session ---
    read_current_session(tp, log)

    # --- Positive: keep current session ---
    log.info("--- Positive Test: TesterPresent ---")
    service_3e_tester_present(tp, log)
    time.sleep(0.1)

    # --- Suppress positive response ---
    log.info("--- Suppress Positive Response Test ---")
    service_3e_suppress_positive_response(tp, log)
    time.sleep(0.1)

    # --- Negative: NRC 0x12 ---
    log.info("--- Negative Test: NRC 0x12 subFunctionNotSupported ---")
    service_3e_nrc12(tp, log)
    time.sleep(0.1)

    # --- Negative: NRC 0x13 ---
    log.info("--- Negative Test: NRC 0x13 incorrectMessageLength ---")
    service_3e_nrc13(tp, log)
    time.sleep(0.1)

    # --- Functional addressing (NAD=0x7E) – no response expected ---
    log.info(f"--- Functional Addressing Tests (NAD=0x{NAD_FUNCTIONAL:02X}) – no response expected ---")
    service_3e_functional_addressing(tp, log)


# --------------------------------------------------------------------------
if __name__ == "__main__":
    log = LinUdsLog("Service_3E")
    tp  = LinTpTransport(logger=log)
    try:
        tp.open()
        service_3e_all_tests(tp, log)
    except Exception as e:
        log.error(str(e))
    finally:
        tp.close()
        log.close()
        sys.exit(0 if log.all_passed else 1)
