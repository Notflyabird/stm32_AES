#!/usr/bin/env python3
"""
Service 0x11 – ECUReset (LIN / FBL context)
============================================
Standalone script. Run directly to test ECU reset.

Positive responses:
  11 01 → 51 01  (hardReset)

Suppress positive response (MSB 0x80 set):
  11 81 → no response  (hardReset, suppressed)

Negative responses:
  NRC 0x12 – subFunctionNotSupported  : 11 00 / 11 03 / 11 22 / 11 FF
                                        (0x03 softReset not supported in FBL)
  NRC 0x13 – incorrectMessageLength   : 11  (too short) / 11 01 00 (too long)

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
SID                        = 0x11
NRC_SUB_FUNC_NOT_SUPPORTED = 0x12
NRC_INCORRECT_MSG_LENGTH   = 0x13
RESET_WAIT_S               = 2.0   # time to wait for ECU to come back after reset


# ==========================================================================
# Positive test cases
# ==========================================================================

def service_11_hard_reset(tp: LinTpTransport, log: LinUdsLog) -> bool:
    log.start_test("0x11 01 – ECUReset hardReset")
    req  = bytes([0x11, 0x01])
    log.tx(bytes_to_hex(req), "ECUReset hardReset")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    result = check_positive_response(resp, SID, log, "hardReset positive response")
    log.info(f"Waiting {RESET_WAIT_S}s for ECU restart...")
    time.sleep(RESET_WAIT_S)
    return result


# ==========================================================================
# Suppress positive response (bit 7 of sub-function = 1)
# ==========================================================================

def service_11_hard_reset_suppress(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """11 81 – hardReset with suppress positive response bit; expect no reply."""
    log.start_test("0x11 81 – ECUReset hardReset (suppress positive response)")
    req  = bytes([0x11, 0x81])
    log.tx(bytes_to_hex(req), "ECUReset hardReset suppressPosRsp")
    resp = tp.send_uds(req, expect_response=False)
    log.rx(bytes_to_hex(resp) if resp else "(no response)")
    result = check_no_response(resp, log, "No response expected (suppress bit set)")
    log.info(f"Waiting {RESET_WAIT_S}s for ECU restart...")
    time.sleep(RESET_WAIT_S)
    return result


# ==========================================================================
# NRC 0x12 – subFunctionNotSupported
# ==========================================================================

def service_11_nrc12(tp: LinTpTransport, log: LinUdsLog, nad: int = None) -> bool:
    """Test sub-functions that are not supported → expect 7F 11 12."""
    suffix   = f" [NAD={nad:02X}]" if nad is not None else ""
    all_pass = True

    # Case 1: sub-function 0x00 (reserved / invalid)
    log.start_test(f"0x11 00{suffix} – NRC 0x12 subFunctionNotSupported (sub-function 0x00)")
    req  = bytes([0x11, 0x00])
    log.tx(bytes_to_hex(req), f"ECUReset subFunction=0x00{suffix}")
    resp = tp.send_uds(req, nad=nad)
    log.rx(bytes_to_hex(resp))
    all_pass &= check_negative_response(resp, SID, NRC_SUB_FUNC_NOT_SUPPORTED, log,
                                        f"NRC 0x12 for sub-function 0x00{suffix}")

    # Case 2: sub-function 0x03 (softReset – not supported in FBL)
    log.start_test(f"0x11 03{suffix} – NRC 0x12 subFunctionNotSupported (softReset not supported in FBL)")
    req  = bytes([0x11, 0x03])
    log.tx(bytes_to_hex(req), f"ECUReset softReset unsupported in FBL{suffix}")
    resp = tp.send_uds(req, nad=nad)
    log.rx(bytes_to_hex(resp))
    all_pass &= check_negative_response(resp, SID, NRC_SUB_FUNC_NOT_SUPPORTED, log,
                                        f"NRC 0x12 for sub-function 0x03 (FBL){suffix}")

    # Case 3: sub-function 0x22 (unknown)
    log.start_test(f"0x11 22{suffix} – NRC 0x12 subFunctionNotSupported (sub-function 0x22)")
    req  = bytes([0x11, 0x22])
    log.tx(bytes_to_hex(req), f"ECUReset subFunction=0x22{suffix}")
    resp = tp.send_uds(req, nad=nad)
    log.rx(bytes_to_hex(resp))
    all_pass &= check_negative_response(resp, SID, NRC_SUB_FUNC_NOT_SUPPORTED, log,
                                        f"NRC 0x12 for sub-function 0x22{suffix}")

    # Case 4: sub-function 0xFF (max, out of range)
    log.start_test(f"0x11 FF{suffix} – NRC 0x12 subFunctionNotSupported (sub-function 0xFF)")
    req  = bytes([0x11, 0xFF])
    log.tx(bytes_to_hex(req), f"ECUReset subFunction=0xFF{suffix}")
    resp = tp.send_uds(req, nad=nad)
    log.rx(bytes_to_hex(resp))
    all_pass &= check_negative_response(resp, SID, NRC_SUB_FUNC_NOT_SUPPORTED, log,
                                        f"NRC 0x12 for sub-function 0xFF{suffix}")

    return all_pass


# ==========================================================================
# NRC 0x13 – incorrectMessageLengthOrInvalidFormat
# ==========================================================================

def service_11_nrc13(tp: LinTpTransport, log: LinUdsLog, nad: int = None) -> bool:
    """Test messages with wrong length → expect 7F 11 13."""
    suffix   = f" [NAD={nad:02X}]" if nad is not None else ""
    all_pass = True

    # Case 1: too short – SID only, no sub-function
    log.start_test(f"0x11{suffix} – NRC 0x13 incorrectMessageLength (length < 2, SID only)")
    req  = bytes([0x11])
    log.tx(bytes_to_hex(req), f"ECUReset length=1 (too short){suffix}")
    resp = tp.send_uds(req, nad=nad)
    log.rx(bytes_to_hex(resp))
    all_pass &= check_negative_response(resp, SID, NRC_INCORRECT_MSG_LENGTH, log,
                                        f"NRC 0x13 for length=1{suffix}")

    # Case 2: too long – SID + sub-function + extra byte
    log.start_test(f"0x11 01 00{suffix} – NRC 0x13 incorrectMessageLength (length > 2)")
    req  = bytes([0x11, 0x01, 0x00])
    log.tx(bytes_to_hex(req), f"ECUReset length=3 (too long){suffix}")
    resp = tp.send_uds(req, nad=nad)
    log.rx(bytes_to_hex(resp))
    all_pass &= check_negative_response(resp, SID, NRC_INCORRECT_MSG_LENGTH, log,
                                        f"NRC 0x13 for length=3{suffix}")

    return all_pass


# ==========================================================================
# Full test sequence
# ==========================================================================

def service_11_all_tests(tp: LinTpTransport, log: LinUdsLog):
    log.info("=" * 60)
    log.info("Service 0x11 ECUReset – Full Test")
    log.info("=" * 60)

    # --- Read initial session ---
    read_current_session(tp, log)

    # --- Physical addressing (NAD=0x67) ---
    log.info("--- Physical Addressing Tests (NAD=0x67) ---")

    log.info("--- Positive Tests ---")
    service_11_hard_reset(tp, log)

    log.info("--- Suppress Positive Response Test ---")
    service_11_hard_reset_suppress(tp, log)

    log.info("--- Negative Tests: NRC 0x12 subFunctionNotSupported ---")
    service_11_nrc12(tp, log)

    log.info("--- Negative Tests: NRC 0x13 incorrectMessageLength ---")
    service_11_nrc13(tp, log)


    # --- Functional addressing (NAD=0x7E) ---
    # Per ISO 17987: functional addressing nodes shall NOT send a response
    log.info("--- Functional Addressing Tests (NAD=0x7E) – no response expected ---")

    log.start_test(f"0x11 01 [NAD={NAD_FUNCTIONAL:02X}] – Functional Addressing: hardReset (no response)")
    req = bytes([0x11, 0x01])
    log.tx(bytes_to_hex(req), f"ECUReset hardReset (NAD=0x{NAD_FUNCTIONAL:02X})")
    resp = tp.send_uds(req, nad=NAD_FUNCTIONAL, expect_response=False)
    log.rx(bytes_to_hex(resp) if resp else "(no response)")
    check_no_response(resp, log, "No response expected for functional hardReset")
    time.sleep(1.0)

    log.start_test(f"0x11 81 [NAD={NAD_FUNCTIONAL:02X}] – Functional Addressing: hardReset suppressPosRsp (no response)")
    req = bytes([0x11, 0x81])
    log.tx(bytes_to_hex(req), f"ECUReset hardReset suppressPosRsp (NAD=0x{NAD_FUNCTIONAL:02X})")
    resp = tp.send_uds(req, nad=NAD_FUNCTIONAL, expect_response=False)
    log.rx(bytes_to_hex(resp) if resp else "(no response)")
    check_no_response(resp, log, "No response expected for functional hardReset suppressPosRsp")


# --------------------------------------------------------------------------
if __name__ == "__main__":
    log = LinUdsLog("Service_11")
    tp  = LinTpTransport(logger=log)
    try:
        tp.open()
        service_11_all_tests(tp, log)
    except Exception as e:
        log.error(str(e))
    finally:
        tp.close()
        log.close()
        sys.exit(0 if log.all_passed else 1)
