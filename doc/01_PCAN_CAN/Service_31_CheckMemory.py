#!/usr/bin/env python3
"""
Service 0x31 – RoutineControl: CheckMemory (LIN)
==============================================================================
Standalone test script.

Routines tested:
  0x0212  CheckMemory (signature verification)
          Request : 31 01 02 12 <sw_signature_dev: 256 bytes>
          Response: 71 01 02 12

NRC priority (verified against ECU):
  1. NRC 0x33  securityAccessDenied    (27 xx not unlocked)
  2. NRC 0x13  incorrectMessageLength  (frame length < 4 bytes; or signature ≠ 256 bytes)
  3. NRC 0x12  subFunctionNotSupported (SubFunction ≠ 0x01)
  4. NRC 0x31  requestOutOfRange       (RID not supported)
  5. Wrong sig  → positive response 71 01 02 12 10 01 (routineStatus=0x01, verificationFailed)
                  ECU does NOT return NRC 0x72 for wrong signature content.

Note: extra byte appended to correct 256-byte signature → NRC 0x13 (too long).
      The 4-byte minimum check (< 4) also triggers 0x13.
"""

import sys
from lin_tp_transport import LinTpTransport
from lin_uds_log import LinUdsLog, bytes_to_hex, check_positive_response, check_negative_response
from lin_tp_vbf_parser import parse_vbf
from lin_tp_config import VBF_FILE

SID = 0x31

ROUTINE_CHECK_MEMORY    = 0x0212   # CheckMemory (signature)
ROUTINE_CHECK_COMPAT    = 0x0205   # CheckCompleteAndCompatible

NRC_INCORRECT_MSG_LENGTH   = 0x13
NRC_SUB_FUNC_NOT_SUPPORTED = 0x12
NRC_REQUEST_OUT_OF_RANGE   = 0x31
NRC_SECURITY_ACCESS_DENIED = 0x33
NRC_GENERAL_PROG_FAILURE   = 0x72


# ==========================================================================
# Positive functions (reusable by orchestration)
# ==========================================================================

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


# ==========================================================================
# NRC tests – 0x0212 CheckMemory, ordered by priority
# ==========================================================================

# ---------- Priority 1: NRC 0x13 – frame length < 4 bytes ----------
def service_31_cm_nrc13_no_signature(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """NRC 0x13 – incorrectMessageLength: 31 01 02 12 only (4 bytes, no signature). [P2]"""
    log.start_test("0x31 01 0212 – NRC 0x13 incorrectMessageLength (4 bytes only, no signature) [P2]")
    req  = bytes([SID, 0x01, 0x02, 0x12])
    log.tx(bytes_to_hex(req), "RoutineControl CheckMemory length=4 (no signature)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID, NRC_INCORRECT_MSG_LENGTH, log,
                                   "NRC 0x13 incorrectMessageLength (no signature)")


def service_31_cm_nrc13_short_signature(tp: LinTpTransport, log: LinUdsLog,
                                         signature_hex: str) -> bool:
    """NRC 0x13 – incorrectMessageLength: first 10 bytes of signature only (too short). [P2]"""
    log.start_test("0x31 01 0212 – NRC 0x13 incorrectMessageLength (10-byte signature, too short) [P2]")
    sig_bytes = bytes.fromhex(signature_hex)[:10]
    req  = bytes([SID, 0x01, 0x02, 0x12]) + sig_bytes
    log.tx(bytes_to_hex(req), f"RoutineControl CheckMemory length={len(req)} (short signature)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID, NRC_INCORRECT_MSG_LENGTH, log,
                                   "NRC 0x13 incorrectMessageLength (short signature)")


def service_31_cm_nrc13_too_long(tp: LinTpTransport, log: LinUdsLog,
                                  signature_hex: str) -> bool:
    """NRC 0x13 – incorrectMessageLength: full 256-byte signature + 1 extra byte. [P2]"""
    log.start_test("0x31 01 0212 – NRC 0x13 incorrectMessageLength (256+1 bytes, too long) [P2]")
    sig_bytes = bytes.fromhex(signature_hex)
    req  = bytes([SID, 0x01, 0x02, 0x12]) + sig_bytes + bytes([0xAA])
    preview = bytes_to_hex(req[:16]) + "..."
    log.tx(preview, f"RoutineControl CheckMemory length={len(req)} (too long)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID, NRC_INCORRECT_MSG_LENGTH, log,
                                   "NRC 0x13 incorrectMessageLength (too long)")


# ---------- Priority 2: NRC 0x12 – SubFunction ≠ 0x01 ----------
def service_31_cm_nrc12_sub_func(tp: LinTpTransport, log: LinUdsLog,
                                  signature_hex: str) -> bool:
    """NRC 0x12 – subFunctionNotSupported: SubFunction=0x02 (not 0x01). [P3]"""
    log.start_test("0x31 02 0212 – NRC 0x12 subFunctionNotSupported (SubFunction=0x02) [P3]")
    sig_bytes = bytes.fromhex(signature_hex)
    req  = bytes([SID, 0x02, 0x02, 0x12]) + sig_bytes
    preview = bytes_to_hex(req[:16]) + "..."
    log.tx(preview, "RoutineControl subFunction=0x02 (invalid)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID, NRC_SUB_FUNC_NOT_SUPPORTED, log,
                                   "NRC 0x12 subFunctionNotSupported")


# ---------- Priority 3: NRC 0x31 – RID not supported ----------
def service_31_cm_nrc31_wrong_routine(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """NRC 0x31 – requestOutOfRange: routine ID 0x0214 does not exist. [P4]"""
    log.start_test("0x31 01 0214 – NRC 0x31 requestOutOfRange (unknown RID 0x0214) [P4]")
    req  = bytes([SID, 0x01, 0x02, 0x14])
    log.tx(bytes_to_hex(req), "RoutineControl unknown RID 0x0214")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID, NRC_REQUEST_OUT_OF_RANGE, log,
                                   "NRC 0x31 requestOutOfRange (RID 0x0214)")


# ---------- Priority 5: NRC 0x33 – security access denied ----------
def service_31_cm_nrc33_no_sa(tp: LinTpTransport, log: LinUdsLog,
                               signature_hex: str) -> bool:
    """NRC 0x33 – securityAccessDenied: CheckMemory without SA unlocked. [P1]"""
    log.start_test("0x31 01 0212 – NRC 0x33 securityAccessDenied (no SA) [P1]")
    sig_bytes = bytes.fromhex(signature_hex)
    req  = bytes([SID, 0x01, 0x02, 0x12]) + sig_bytes
    preview = bytes_to_hex(req[:16]) + "..."
    log.tx(preview, "RoutineControl CheckMemory (no security access)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID, NRC_SECURITY_ACCESS_DENIED, log,
                                   "NRC 0x33 securityAccessDenied")


# ---------- Priority 5: wrong signature → positive response with status=0x01 ----------
def service_31_cm_nrc72_wrong_signature(tp: LinTpTransport, log: LinUdsLog,
                                         signature_hex: str) -> bool:
    """
    Wrong signature content: correct length but all bytes flipped (XOR 0xFF).
    ECU returns positive response 71 01 02 12 10 01 (status=0x01 = verification failed).
    Requires: valid erase + download already completed. [P5]
    """
    log.start_test("0x31 01 0212 – wrong signature → positive resp status=0x01 [P5]")
    sig_bytes = bytes.fromhex(signature_hex)
    bad_sig   = bytes([b ^ 0xFF for b in sig_bytes])   # flip all bits
    req  = bytes([SID, 0x01, 0x02, 0x12]) + bad_sig
    preview = bytes_to_hex(req[:16]) + "..."
    log.tx(preview, "RoutineControl CheckMemory (corrupted signature, all bytes XOR 0xFF)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    # ECU design: signature failure returns positive response with routineStatus=0x01
    expected = bytes([0x71, 0x01, 0x02, 0x12, 0x10, 0x01])
    ok = (resp == expected)
    log.result(ok,
               expected=bytes_to_hex(expected),
               received=bytes_to_hex(resp),
               description="CheckMemory wrong signature → status=0x01 (verificationFailed)")
    return ok


# ==========================================================================
# (0x0205 NRC tests moved to Service_31_CC.py)
# ==========================================================================


# --------------------------------------------------------------------------
if __name__ == "__main__":
    from Service_10 import service_10_programming_session
    from Service_27 import service_27_security_access
    from Service_31_Erase import service_31_erase_memory
    from Service_34_36_37 import download_vbf_block

    log = LinUdsLog("Service_31_CheckMemory")
    tp  = LinTpTransport(logger=log)
    try:
        tp.open()
        hdr, blocks = parse_vbf(VBF_FILE)
        sig         = hdr.sw_signature_dev
        erase_addr, erase_len = hdr.erase_regions[0]

        log.info("=" * 60)
        log.info("Service 0x31 01 02 12 – CheckMemory – Full NRC Test")
        log.info("NRC priority: 0x33(P1) > 0x13(P2) > 0x12(P3) > 0x31(P4) | P5: wrong sig → 71..10 01")
        log.info(f"  Signature length : {len(sig)//2} bytes")
        log.info(f"  Erase region     : 0x{erase_addr:08X} len=0x{erase_len:08X}")
        log.info(f"  VBF blocks       : {len(blocks)}")
        log.info("=" * 60)

        # ------------------------------------------------------------------
        # P1: NRC 0x33 – securityAccessDenied (highest priority, no SA)
        # ------------------------------------------------------------------
        log.info("--- P1 NRC 0x33: securityAccessDenied (no SA) ---")
        service_10_programming_session(tp, log)
        service_31_cm_nrc33_no_sa(tp, log, sig)

        # ------------------------------------------------------------------
        # P2: NRC 0x13 – incorrectMessageLength (SA unlocked first)
        # SA must be unlocked so ECU proceeds past 0x33 to check length
        # ------------------------------------------------------------------
        log.info("--- P2 NRC 0x13: incorrectMessageLength (SA unlocked) ---")
        service_10_programming_session(tp, log)
        service_27_security_access(tp, log)
        service_31_cm_nrc13_no_signature(tp, log)         # 4 bytes, no sig
        service_10_programming_session(tp, log)
        service_27_security_access(tp, log)
        service_31_cm_nrc13_short_signature(tp, log, sig) # 14 bytes, too short
        service_10_programming_session(tp, log)
        service_27_security_access(tp, log)
        service_31_cm_nrc13_too_long(tp, log, sig)        # 261 bytes, too long

        # ------------------------------------------------------------------
        # P3: NRC 0x12 – subFunctionNotSupported (SA unlocked first)
        # SA must be unlocked so ECU proceeds past 0x33 to check subFunction
        # ------------------------------------------------------------------
        log.info("--- P3 NRC 0x12: subFunctionNotSupported (SA unlocked) ---")
        service_10_programming_session(tp, log)
        service_27_security_access(tp, log)
        service_31_cm_nrc12_sub_func(tp, log, sig)

        # ------------------------------------------------------------------
        # P4: NRC 0x31 – requestOutOfRange (unknown RID 0x0214)
        # No SA needed: RID check is independent
        # ------------------------------------------------------------------
        log.info("--- P4 NRC 0x31: requestOutOfRange (unknown RID 0x0214) ---")
        service_10_programming_session(tp, log)
        service_31_cm_nrc31_wrong_routine(tp, log)

        # ------------------------------------------------------------------
        # P5: wrong signature → positive resp status=0x01 (after valid download)
        # ECU does NOT return NRC 0x72; returns 71 01 02 12 10 01 instead
        # ------------------------------------------------------------------
        log.info("--- P5 wrong signature: expect positive resp 71 01 02 12 10 01 ---")
        service_10_programming_session(tp, log)
        service_27_security_access(tp, log)
        service_31_erase_memory(tp, log, erase_addr, erase_len)
        for blk in blocks:
            download_vbf_block(tp, log, hdr, blk)
        service_31_cm_nrc72_wrong_signature(tp, log, sig)

        # ------------------------------------------------------------------
        # Positive – full sequence: erase → download → CheckMemory
        # ------------------------------------------------------------------
        log.info("--- Positive Test: CheckMemory (nominal) ---")
        service_10_programming_session(tp, log)
        service_27_security_access(tp, log)
        service_31_erase_memory(tp, log, erase_addr, erase_len)
        for blk in blocks:
            download_vbf_block(tp, log, hdr, blk)
        service_31_check_memory(tp, log, sig, fallback_sig_hex=hdr.sw_signature)

    except Exception as e:
        log.error(str(e))
        import traceback; traceback.print_exc()
    finally:
        tp.close()
        log.close()
        sys.exit(0 if log.all_passed else 1)
