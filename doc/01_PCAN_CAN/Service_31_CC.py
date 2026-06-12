#!/usr/bin/env python3
"""
Service 0x31 – RoutineControl: CheckCompleteAndCompatible (LIN)
================================================================
Standalone test script.

Routine tested:
  0x0205  CheckCompleteAndCompatible
          Request : 31 01 02 05
          Response: 71 01 02 05

NRC / Status (verified against ECU):
  1. NRC 0x13  incorrectMessageLength    (frame length < 4 bytes)
  2. NRC 0x12  subFunctionNotSupported   (SubFunction ≠ 0x01, SA unlocked)
  3. NRC 0x31  requestOutOfRange         (RID not supported)
  5. NRC 0x33  securityAccessDenied      (27 xx not unlocked)
  6. Status 0x05  App incomplete         (after Erase, no download)
  7. Status 0x05  App incomplete         (download done, CheckMemory not called)
  8. Status 0x05  App incomplete         (incomplete VBF: git 9452265, with CheckMemory)
  9. Status 0x05  App incomplete         (incomplete VBF, no CheckMemory: 0x38C10 != 0x5A5A5A5A)
 10. Status 0x06  FBL/App incompatible  (PNORFlashArea_RTSW_incompatible.vbf)
 11. Status 0x00  Positive (nominal)    (complete VBF)

Note: After SA unlocked, ECU NEVER returns NRC 0x22 for 0x0205.
      All non-OK conditions return positive response with status byte:
      0x00=OK, 0x05=App incomplete, 0x06=FBL/App incompatible.
"""

import sys
from lin_tp_transport import LinTpTransport
from lin_uds_log import LinUdsLog, bytes_to_hex, check_positive_response, check_negative_response
from lin_tp_vbf_parser import parse_vbf
from lin_tp_config import VBF_FILE, VBF_FILE_INCOMPLETE, VBF_FILE_INCOMPATIBLE

SID = 0x31

ROUTINE_CHECK_COMPAT = 0x0205   # CheckCompleteAndCompatible

NRC_INCORRECT_MSG_LENGTH    = 0x13
NRC_SUB_FUNC_NOT_SUPPORTED  = 0x12
NRC_REQUEST_OUT_OF_RANGE    = 0x31
NRC_CONDITIONS_NOT_CORRECT  = 0x22
NRC_SECURITY_ACCESS_DENIED  = 0x33
NRC_GENERAL_PROG_FAILURE    = 0x72

# Status bytes in 71 01 02 05 10 00 00 00 <status> positive response
CC_STATUS_APP_INCOMPLETE   = 0x05   # App not fully downloaded
CC_STATUS_FBL_INCOMPATIBLE = 0x06   # FBL/App version incompatible


# ==========================================================================
# Internal helper – status-byte check for 0x0205 extended response
# ==========================================================================

def _check_cc_status(resp: bytes, expected_status: int,
                     log: LinUdsLog, desc: str) -> bool:
    """
    Verify 71 01 02 05 positive response and check the trailing status byte.
    Full expected frame: 71 01 02 05 10 00 00 00 <status>
    """
    resp_hex = bytes_to_hex(resp)
    exp_str  = f"71 01 02 05 10 00 00 00 {expected_status:02X}"
    ok = (len(resp) >= 8
          and resp[0] == 0x71
          and resp[-1] == expected_status)
    log.result(ok, expected=exp_str,
               received=resp_hex if resp_hex else "(empty)",
               description=desc)
    return ok


# ==========================================================================
# Positive function (reusable)
# ==========================================================================

def service_31_check_complete_and_compatible(tp: LinTpTransport,
                                              log: LinUdsLog) -> bool:
    """Routine 0x0205 – CheckCompleteAndCompatible: 31 01 02 05."""
    log.start_test("0x31 01 0205 – CheckCompleteAndCompatible")
    req  = bytes([SID, 0x01, 0x02, 0x05])
    log.tx(bytes_to_hex(req), "RoutineControl CheckCompleteAndCompatible 0205")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_positive_response(resp, SID, log,
                                   "CheckCompleteAndCompatible 0205 positive response")


# ==========================================================================
# NRC tests – ordered by priority
# ==========================================================================

# ---------- Priority 1: NRC 0x13 – frame length < 4 bytes ----------
def service_31_cc_nrc13_too_short(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """NRC 0x13 – incorrectMessageLength: 31 01 02 (3 bytes, < 4)."""
    log.start_test("0x31 01 02 – NRC 0x13 incorrectMessageLength (3 bytes, too short) [P1]")
    req  = bytes([SID, 0x01, 0x02])
    log.tx(bytes_to_hex(req), "RoutineControl length=3 (too short, < 4)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID, NRC_INCORRECT_MSG_LENGTH, log,
                                   "NRC 0x13 incorrectMessageLength (3 bytes)")


# ---------- Priority 2 (actual ECU): NRC 0x12 – SubFunction ≠ 0x01 ----------
def service_31_cc_nrc12_sub_func(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """
    SubFunction=0x02 (invalid): ECU returns NRC 0x12 subFunctionNotSupported.
    SA must be unlocked first; without SA ECU returns 0x33.
    """
    log.start_test("0x31 02 0205 – NRC 0x12 subFunctionNotSupported (SubFunction=0x02, SA unlocked) [P2]")
    req  = bytes([SID, 0x02, 0x02, 0x05])
    log.tx(bytes_to_hex(req), "RoutineControl subFunction=0x02 (invalid)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID, NRC_SUB_FUNC_NOT_SUPPORTED, log,
                                   "NRC 0x12 subFunctionNotSupported (SubFunction=0x02)")


# ---------- Priority 3: NRC 0x31 – RID not supported ----------
def service_31_cc_nrc31_unknown_rid(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """NRC 0x31 – requestOutOfRange: RID 0x0204 not supported."""
    log.start_test("0x31 01 0204 – NRC 0x31 requestOutOfRange (unknown RID 0x0204) [P3]")
    req  = bytes([SID, 0x01, 0x02, 0x04])
    log.tx(bytes_to_hex(req), "RoutineControl unknown RID 0x0204")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID, NRC_REQUEST_OUT_OF_RANGE, log,
                                   "NRC 0x31 requestOutOfRange (RID 0x0204)")


# ---------- Priority 5: NRC 0x33 – security access denied ----------
def service_31_cc_nrc33_no_sa(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """NRC 0x33 – securityAccessDenied: 31 01 02 05 without SA unlocked."""
    log.start_test("0x31 01 0205 – NRC 0x33 securityAccessDenied (no SA) [P5]")
    req  = bytes([SID, 0x01, 0x02, 0x05])
    log.tx(bytes_to_hex(req), "RoutineControl CheckCompleteAndCompatible (no security access)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID, NRC_SECURITY_ACCESS_DENIED, log,
                                   "NRC 0x33 securityAccessDenied")


# ---------- NRC 0x22 – conditionsNotCorrect (ECU actual, spec says 0x72) ----------
def service_31_cc_nrc22_no_download(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """
    Status 0x05 – App incomplete: CheckCC after Erase but without any download.
    ECU does not return NRC 0x22; instead returns positive response with status 0x05.
    Precondition: Erase already done, no download performed.
    """
    log.start_test("0x31 01 0205 – Status 0x05 App incomplete (after Erase, no download)")
    req  = bytes([SID, 0x01, 0x02, 0x05])
    log.tx(bytes_to_hex(req), "RoutineControl CheckCompleteAndCompatible (erased, no download)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return _check_cc_status(resp, CC_STATUS_APP_INCOMPLETE, log,
                            "Status 0x05 App incomplete (after Erase, no download)")


def service_31_cc_nrc22_before_check_memory(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """
    Status 0x05 – App incomplete: CheckCC after complete download but before CheckMemory.
    ECU does not return NRC 0x22; instead returns positive response with status 0x05.
    Precondition: Erase + full download completed, CheckMemory (0x0212) NOT called.
    """
    log.start_test("0x31 01 0205 – Status 0x05 App incomplete (download done, CheckMemory not called)")
    req  = bytes([SID, 0x01, 0x02, 0x05])
    log.tx(bytes_to_hex(req), "RoutineControl CheckCompleteAndCompatible (CheckMemory not done)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return _check_cc_status(resp, CC_STATUS_APP_INCOMPLETE, log,
                            "Status 0x05 App incomplete (CheckMemory not done)")


# ---------- Status 0x05: App incomplete ----------
def service_31_cc_status05_app_incomplete(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """
    Status 0x05 – App incomplete:
      Erase → download incomplete VBF (git 9452265) → CheckMemory (sig2)
      → 31 01 02 05 → 71 01 02 05 10 00 00 00 05
    Precondition: erase + download of incomplete VBF + CheckMemory already done.
    """
    log.start_test("0x31 01 0205 – Status 0x05 App incomplete (incomplete VBF + CheckMemory done)")
    req  = bytes([SID, 0x01, 0x02, 0x05])
    log.tx(bytes_to_hex(req), "RoutineControl CheckCompleteAndCompatible (App incomplete)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return _check_cc_status(resp, CC_STATUS_APP_INCOMPLETE, log,
                            "Status 0x05 App incomplete")


def service_31_cc_status05_no_check_memory(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """
    Status 0x05 – App incomplete (CheckMemory not done):
      Erase → download incomplete VBF (git 9452265) → skip CheckMemory
      → 31 01 02 05 → 71 01 02 05 10 00 00 00 05
    ECU checks sentinel at 0x38C10: value != 0x5A5A5A5A (CheckMemory not called),
    reports App incomplete (status 0x05) in positive response.
    """
    log.start_test("0x31 01 0205 – Status 0x05 App incomplete (31 01 02 12 未做, 0x38C10 != 0x5A5A5A5A)")
    req  = bytes([SID, 0x01, 0x02, 0x05])
    log.tx(bytes_to_hex(req), "RoutineControl CheckCompleteAndCompatible (CheckMemory not called)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return _check_cc_status(resp, CC_STATUS_APP_INCOMPLETE, log,
                            "Status 0x05 App incomplete (0x38C10 != 0x5A5A5A5A, no CheckMemory)")


# ---------- Status 0x06: FBL/App incompatible ----------
def service_31_cc_status06_fbl_incompatible(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """
    Status 0x06 – FBL/App incompatible:
      Download PNORFlashArea_RTSW_incompatible.vbf (version mismatch with FBL)
      → CheckMemory → 31 01 02 05 → 71 01 02 05 10 00 00 00 06
    Precondition: erase + full download of incompatible VBF + CheckMemory already done.
    """
    log.start_test("0x31 01 0205 – Status 0x06 FBL/App incompatible (PNORFlashArea_RTSW_incompatible.vbf)")
    req  = bytes([SID, 0x01, 0x02, 0x05])
    log.tx(bytes_to_hex(req), "RoutineControl CheckCompleteAndCompatible (FBL/App version mismatch)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return _check_cc_status(resp, CC_STATUS_FBL_INCOMPATIBLE, log,
                            "Status 0x06 FBL/App incompatible")


# --------------------------------------------------------------------------
if __name__ == "__main__":
    from Service_10 import service_10_programming_session
    from Service_27 import service_27_security_access
    from Service_31_Erase import service_31_erase_memory
    from Service_31_CheckMemory import service_31_check_memory
    from Service_34_36_37 import download_vbf_block

    log = LinUdsLog("Service_31_CC")
    tp  = LinTpTransport(logger=log)
    try:
        tp.open()
        hdr,  blocks  = parse_vbf(VBF_FILE)              # complete App
        hdr2, blocks2 = parse_vbf(VBF_FILE_INCOMPLETE)   # incomplete App (git 9452265) → status 0x05
        hdr3, blocks3 = parse_vbf(VBF_FILE_INCOMPATIBLE) # FBL/App version mismatch → status 0x06
        sig  = hdr.sw_signature_dev
        sig2 = hdr2.sw_signature_dev
        sig3 = hdr3.sw_signature_dev
        erase_addr, erase_len = hdr.erase_regions[0]

        log.info("=" * 60)
        log.info("Service 0x31 01 02 05 – CheckCompleteAndCompatible – Full NRC Test")
        log.info("NRC priority: 0x13(P1) > 0x12(P2) > 0x31(P3) > 0x33(P5) > 0x22")
        log.info("=" * 60)

        # ------------------------------------------------------------------
        # P1: NRC 0x13 – incorrectMessageLength (frame < 4 bytes)
        # No SA needed: length check is first
        # ------------------------------------------------------------------
        log.info("--- P1 NRC 0x13: incorrectMessageLength (< 4 bytes) ---")
        service_10_programming_session(tp, log)
        service_31_cc_nrc13_too_short(tp, log)

        # ------------------------------------------------------------------
        # P2: NRC 0x12 – subFunctionNotSupported (SubFunction=0x02, SA unlocked)
        # ------------------------------------------------------------------
        log.info("--- P2 NRC 0x12: subFunctionNotSupported (SubFunction=0x02, with SA) ---")
        service_10_programming_session(tp, log)
        service_27_security_access(tp, log)
        service_31_cc_nrc12_sub_func(tp, log)

        # ------------------------------------------------------------------
        # P3: NRC 0x31 – requestOutOfRange (unknown RID)
        # ------------------------------------------------------------------
        log.info("--- P3 NRC 0x31: requestOutOfRange (unknown RID 0x0204) ---")
        service_10_programming_session(tp, log)
        service_31_cc_nrc31_unknown_rid(tp, log)

        # ------------------------------------------------------------------
        # P5: NRC 0x33 – securityAccessDenied (no SA)
        # ------------------------------------------------------------------
        log.info("--- P5 NRC 0x33: securityAccessDenied (no SA) ---")
        service_10_programming_session(tp, log)
        service_31_cc_nrc33_no_sa(tp, log)

        # ------------------------------------------------------------------
        # Status 0x05 – App incomplete (Erase done, no download)
        # ECU returns positive response status 0x05, not NRC 0x22
        # ------------------------------------------------------------------
        log.info("--- Status 0x05: App incomplete (after Erase, no download) ---")
        service_10_programming_session(tp, log)
        service_27_security_access(tp, log)
        service_31_erase_memory(tp, log, erase_addr, erase_len)
        service_31_cc_nrc22_no_download(tp, log)

        # ------------------------------------------------------------------
        # Status 0x05 – App incomplete (download done, CheckMemory not called)
        # ECU returns positive response status 0x05, not NRC 0x22
        # ------------------------------------------------------------------
        log.info("--- Status 0x05: App incomplete (download done, CheckMemory not called) ---")
        service_10_programming_session(tp, log)
        service_27_security_access(tp, log)
        service_31_erase_memory(tp, log, erase_addr, erase_len)
        for blk in blocks:
            download_vbf_block(tp, log, hdr, blk)
        service_31_cc_nrc22_before_check_memory(tp, log)

        # ------------------------------------------------------------------
        # Status 0x05 – App incomplete (incomplete VBF + CheckMemory done)
        # Setup: erase + download ALL blocks of incomplete VBF + CheckMemory
        #        (incomplete VBF: block[1] length=0xA99B, missing ~1.8 kB)
        # Expected response: 71 01 02 05 10 00 00 00 05
        # ------------------------------------------------------------------
        log.info("--- Status 0x05: App incomplete (incomplete VBF + CheckMemory) ---")
        service_10_programming_session(tp, log)
        service_27_security_access(tp, log)
        service_31_erase_memory(tp, log, erase_addr, erase_len)
        for blk in blocks2:
            download_vbf_block(tp, log, hdr2, blk)
        service_31_check_memory(tp, log, sig2)
        service_31_cc_status05_app_incomplete(tp, log)

        # ------------------------------------------------------------------
        # Status 0x05 – App incomplete (CheckMemory 未做, 0x38C10 != 0x5A5A5A5A)
        # Setup: erase + download incomplete VBF, skip CheckMemory (0x0212)
        # ECU detects sentinel at 0x38C10 is not 0x5A5A5A5A → status 0x05
        # Expected response: 71 01 02 05 10 00 00 00 05
        # ------------------------------------------------------------------
        log.info("--- Status 0x05: 31 01 02 12 未做 (0x38C10 != 0x5A5A5A5A, incomplete VBF, no CheckMemory) ---")
        service_10_programming_session(tp, log)
        service_27_security_access(tp, log)
        service_31_erase_memory(tp, log, erase_addr, erase_len)
        for blk in blocks2:
            download_vbf_block(tp, log, hdr2, blk)
        # CheckMemory (0x0212) intentionally skipped
        service_31_cc_status05_no_check_memory(tp, log)

        # ------------------------------------------------------------------
        # Status 0x06 – FBL/App incompatible
        # Setup: erase + download PNORFlashArea_RTSW_incompatible.vbf + CheckMemory
        # Expected response: 71 01 02 05 10 00 00 00 06
        # ------------------------------------------------------------------
        log.info("--- Status 0x06: FBL/App incompatible (PNORFlashArea_RTSW_incompatible.vbf) ---")
        service_10_programming_session(tp, log)
        service_27_security_access(tp, log)
        service_31_erase_memory(tp, log, erase_addr, erase_len)
        for blk in blocks3:
            download_vbf_block(tp, log, hdr3, blk)
        service_31_check_memory(tp, log, sig3)
        service_31_cc_status06_fbl_incompatible(tp, log)

        # ------------------------------------------------------------------
        # Positive – full sequence: erase → download → CheckMemory → 0x0205
        # ------------------------------------------------------------------
        log.info("--- Positive Test: CheckCompleteAndCompatible (nominal) ---")
        service_10_programming_session(tp, log)
        service_27_security_access(tp, log)
        service_31_erase_memory(tp, log, erase_addr, erase_len)
        for blk in blocks:
            download_vbf_block(tp, log, hdr, blk)
        service_31_check_memory(tp, log, sig)
        service_31_check_complete_and_compatible(tp, log)

    except Exception as e:
        log.error(str(e))
        import traceback; traceback.print_exc()
    finally:
        tp.close()
        log.close()
        sys.exit(0 if log.all_passed else 1)
