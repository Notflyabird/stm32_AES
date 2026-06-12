#!/usr/bin/env python3
"""
Service 0x31 – RoutineControl: Erase Memory (LIN)
===================================================
Standalone script.

Routine ID 0xFF00 = EraseMemory
Request : 31 01 FF 00 <address 4B> <length 4B>
Response: 71 01 FF 00 [status]
"""

import sys
import struct
from lin_tp_transport import LinTpTransport
from lin_uds_log import LinUdsLog, bytes_to_hex, check_positive_response, check_negative_response
from lin_tp_vbf_parser import parse_vbf
from lin_tp_config import VBF_FILE

SID = 0x31
ROUTINE_ERASE  = 0xFF00
ROUTINE_CHECK  = 0x0202   # CheckProgrammingDependencies (optional)

NRC_INCORRECT_MSG_LENGTH  = 0x13
NRC_CONDITIONS_NOT_CORRECT = 0x22
NRC_REQUEST_OUT_OF_RANGE   = 0x31
NRC_SECURITY_ACCESS_DENIED = 0x33


def service_31_erase_memory(tp: LinTpTransport, log: LinUdsLog,
                             address: int, length: int) -> bool:
    """
    Erase memory routine.
    address / length must match the 'erase' entry in the VBF header.
    """
    desc = f"0x31 01 FF00 – EraseMemory @ 0x{address:08X} len=0x{length:08X}"
    log.start_test(desc)

    req = (bytes([SID, 0x01, 0xFF, 0x00])
           + struct.pack(">I", address)
           + struct.pack(">I", length))
    log.tx(bytes_to_hex(req), "RoutineControl EraseMemory")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))

    passed = check_positive_response(resp, SID, log, "EraseMemory positive response")
    if passed:
        # Check routine status byte (71 01 FF 00 [status])
        if len(resp) >= 5:
            status = resp[4]
            if status == 0x00:
                log.info("Erase routine status: 0x00 (success)")
            else:
                log.info(f"Erase routine status: 0x{status:02X}")
    return passed


def service_31_check_complete_and_compatible(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """Routine 0x0202 – CheckProgrammingDependencies (optional)."""
    log.start_test("0x31 01 0202 – CheckCompleteAndCompatible")
    req  = bytes([SID, 0x01, 0x02, 0x02])
    log.tx(bytes_to_hex(req), "RoutineControl CheckCompleteAndCompatible")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_positive_response(resp, SID, log, "CheckCompleteAndCompatible positive response")


def service_31_check_memory(tp: LinTpTransport, log: LinUdsLog,
                             signature_hex: str,
                             fallback_sig_hex: str = "") -> bool:
    """
    Routine 0x0212 – CheckMemory: 31 01 02 12 + signature bytes.
    Tries sw_signature_dev first; if ECU returns positive response with
    status 10 01 (verification failed), retries with fallback_sig_hex
    (sw_signature / production key) when provided.
    Success requires response 71 01 02 12 10 00 (status last byte = 0x00).
    """
    VERIFY_FAILED = bytes([0x71, 0x01, 0x02, 0x12, 0x10, 0x01])
    VERIFY_OK     = bytes([0x71, 0x01, 0x02, 0x12, 0x10, 0x00])

    def _send_once(sig_hex: str, label: str) -> bytes:
        sig_bytes = bytes.fromhex(sig_hex)
        req = bytes([SID, 0x01, 0x02, 0x12]) + sig_bytes
        preview = bytes_to_hex(req[:16]) + ("..." if len(req) > 16 else "")
        log.tx(preview, f"RoutineControl CheckMemory ({label})")
        resp = tp.send_uds(req)
        log.rx(bytes_to_hex(resp))
        return resp

    log.start_test("0x31 01 0212 – CheckMemory (signature verification)")
    resp = _send_once(signature_hex, "sw_signature_dev")

    if resp == VERIFY_FAILED:
        if fallback_sig_hex:
            log.info("CheckMemory: dev-key verification failed (status 10 01) "
                     "– retrying with production signature (sw_signature)")
            resp = _send_once(fallback_sig_hex, "sw_signature (prod)")
        else:
            log.info("CheckMemory: dev-key verification failed (status 10 01) "
                     "– no fallback signature provided")

    ok = (resp == VERIFY_OK)
    log.result(ok,
               expected=bytes_to_hex(VERIFY_OK),
               received=bytes_to_hex(resp),
               description="CheckMemory positive response (status 10 00)")
    return ok


def service_31_check_complete_and_compatible_0205(tp: LinTpTransport,
                                                   log: LinUdsLog) -> bool:
    """Routine 0x0205 – CheckCompleteAndCompatible (final programming check)."""
    log.start_test("0x31 01 0205 – CheckCompleteAndCompatible")
    req  = bytes([SID, 0x01, 0x02, 0x05])
    log.tx(bytes_to_hex(req), "RoutineControl CheckCompleteAndCompatible 0205")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_positive_response(resp, SID, log,
                                   "CheckCompleteAndCompatible 0205 positive response")


# ==========================================================================
# NRC test cases for 0x31 01 FF 00 – EraseMemory
# ==========================================================================

def service_31_erase_nrc13_too_short(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """NRC 0x13 – incorrectMessageLength: only SID + type + routine ID (3 bytes, missing address/length)."""
    log.start_test("0x31 01 FF – NRC 0x13 incorrectMessageLength (3 bytes, too short)")
    req  = bytes([SID, 0x01, 0xFF])
    log.tx(bytes_to_hex(req), "RoutineControl EraseMemory length=3 (too short)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID, NRC_INCORRECT_MSG_LENGTH, log,
                                   "NRC 0x13 for length=3")


def service_31_erase_nrc13_partial(tp: LinTpTransport, log: LinUdsLog,
                                   address: int, length: int) -> bool:
    """NRC 0x13 – incorrectMessageLength: 11 bytes (missing last byte of length field)."""
    log.start_test("0x31 01 FF00 – NRC 0x13 incorrectMessageLength (11 bytes, 1 byte short)")
    # Full request is 12 bytes; send only 11 (drop last byte of length)
    full = (bytes([SID, 0x01, 0xFF, 0x00])
            + struct.pack(">I", address)
            + struct.pack(">I", length))
    req = full[:11]
    log.tx(bytes_to_hex(req), "RoutineControl EraseMemory length=11 (too short)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID, NRC_INCORRECT_MSG_LENGTH, log,
                                   "NRC 0x13 for length=11")


def service_31_erase_nrc13_too_long(tp: LinTpTransport, log: LinUdsLog,
                                    address: int, length: int) -> bool:
    """NRC 0x13 – incorrectMessageLength: 14 bytes (2 extra bytes appended)."""
    log.start_test("0x31 01 FF00 – NRC 0x13 incorrectMessageLength (14 bytes, too long)")
    req = (bytes([SID, 0x01, 0xFF, 0x00])
           + struct.pack(">I", address)
           + struct.pack(">I", length)
           + bytes([0xAA, 0xAA]))
    log.tx(bytes_to_hex(req), "RoutineControl EraseMemory length=14 (too long)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID, NRC_INCORRECT_MSG_LENGTH, log,
                                   "NRC 0x13 for length=14")


def service_31_erase_nrc31_wrong_sub_id(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """NRC 0x31 – requestOutOfRange: routine ID FF01 does not exist."""
    log.start_test("0x31 01 FF01 – NRC 0x31 requestOutOfRange (invalid routine ID FF01)")
    req  = bytes([SID, 0x01, 0xFF, 0x01])
    log.tx(bytes_to_hex(req), "RoutineControl unknown routine FF01")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID, NRC_REQUEST_OUT_OF_RANGE, log,
                                   "NRC 0x31 for routine ID FF01")


def service_31_erase_nrc31_invalid_address(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """NRC 0x31 – requestOutOfRange: address 0xFFFFFF00 is outside valid flash region."""
    log.start_test("0x31 01 FF00 – NRC 0x31 requestOutOfRange (address 0xFFFFFF00 out of range)")
    req = (bytes([SID, 0x01, 0xFF, 0x00])
           + struct.pack(">I", 0xFFFFFF00)
           + struct.pack(">I", 0x00006000))
    log.tx(bytes_to_hex(req), "RoutineControl EraseMemory invalid address 0xFFFFFF00")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID, NRC_REQUEST_OUT_OF_RANGE, log,
                                   "NRC 0x31 for out-of-range address")


def service_31_erase_nrc33_no_sa(tp: LinTpTransport, log: LinUdsLog,
                                  address: int, length: int) -> bool:
    """NRC 0x33 – securityAccessDenied: erase without security access unlocked."""
    log.start_test("0x31 01 FF00 – NRC 0x33 securityAccessDenied (no SA)")
    req = (bytes([SID, 0x01, 0xFF, 0x00])
           + struct.pack(">I", address)
           + struct.pack(">I", length))
    log.tx(bytes_to_hex(req), "RoutineControl EraseMemory (no security access)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID, NRC_SECURITY_ACCESS_DENIED, log,
                                   "NRC 0x33 securityAccessDenied")


# --------------------------------------------------------------------------
if __name__ == "__main__":
    log = LinUdsLog("Service_31_Erase")
    tp  = LinTpTransport(logger=log)
    try:
        tp.open()
        # Read erase regions from VBF
        hdr, _ = parse_vbf(VBF_FILE)
        log.info(f"VBF erase regions: {[(hex(a), hex(l)) for a,l in hdr.erase_regions]}")
        address, length = hdr.erase_regions[0]

        from Service_10 import service_10_programming_session
        from Service_27 import service_27_security_access

        # ------------------------------------------------------------------
        # NRC 0x33 – securityAccessDenied (must be tested BEFORE SA unlock)
        # ------------------------------------------------------------------
        log.info("--- NRC Tests: 0x31 01 FF00 EraseMemory ---")
        service_10_programming_session(tp, log)
        service_31_erase_nrc33_no_sa(tp, log, address, length)

        # ------------------------------------------------------------------
        # NRC 0x13 – incorrectMessageLength
        # ------------------------------------------------------------------
        service_10_programming_session(tp, log)
        service_27_security_access(tp, log)
        service_31_erase_nrc13_too_short(tp, log)
        service_31_erase_nrc13_partial(tp, log, address, length)
        service_31_erase_nrc13_too_long(tp, log, address, length)

        # ------------------------------------------------------------------
        # NRC 0x31 – requestOutOfRange
        # ------------------------------------------------------------------
        service_31_erase_nrc31_wrong_sub_id(tp, log)
        service_31_erase_nrc31_invalid_address(tp, log)

        # ------------------------------------------------------------------
        # Positive – EraseMemory (nominal)
        # ------------------------------------------------------------------
        log.info("--- Positive Test: EraseMemory ---")
        for addr, ln in hdr.erase_regions:
            service_31_erase_memory(tp, log, addr, ln)

    except Exception as e:
        log.error(str(e))
    finally:
        tp.close()
        log.close()
        sys.exit(0 if log.all_passed else 1)
