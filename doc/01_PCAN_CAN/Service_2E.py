#!/usr/bin/env python3
"""
Service 0x2E - WriteDataByIdentifier (FBL/PBL context)
=======================================================
Standalone test script. FBL-only (single-level bootloader, no SBL).
Prerequisite: Programming Session (10 02) + SecurityAccess level 01 unlocked.

Supported DIDs (FBL only):
  F1 09  Security Constant Level 01/02   16 bytes,  write-once (ReqID 677100, 703288)
  D0 1C  RSA-2048 Public Key             292 bytes, write-once (ReqID 664684)

Format of D0 1C payload (292 bytes total):
  [0..255]   256-byte RSA modulus
  [256..259]  4-byte exponent (00 01 00 01 = 65537)
  [260..291] 32-byte SHA256 checksum = SHA256(modulus + exponent)

Requirements coverage:
  ReqID 663993  WriteDataByIdentifier (0x2E) service
  ReqID 664684  DID D01C - Public Key
                  * Write supported in PBL (this ECU has no SBL; BBDOWNLOAD_ENABLE_SBL=0)
                  * Write once; second attempt -> NRC 0x22
                  * Read D01C before write (dev key) -> NRC 0x22
                  * Read D01C after write -> 32-byte checksum (positive)
                  * Write with SHA256 mismatch -> NRC 0x72
  ReqID 677100  DID F109 - Security Constant
                  * Cannot be read in any session -> NRC 0x31
                  * Write supported in PBL
                  * Write once; second attempt -> NRC 0x22
  ReqID 703288  Fixed Bytes Program Frequency Limit: already programmed -> NRC 0x22
  ReqID 850391  Fixed Bytes Run: takes effect immediately after write (no reset needed)
  ReqID 666415  Response to NVM: positive response sent only after NVM write completes

NRC mapping (verified against bbdiagdid.c / bbsecurity_cfg.c):
  NRC 0x13  Incorrect message length (< 4 bytes total, or data != required length)
  NRC 0x22  Condition not correct  (DID already written, or D01C read when no prod key)
  NRC 0x31  Request out of range   (unsupported DID; needs >=1 data byte to pass len check)
  NRC 0x72  General programming failure (D01C: SHA256 checksum mismatch)

NOTE - NRC 0x11 (serviceNotSupported):
  The spec (ReqID 664684) states 2E D01C in PBL shall return NRC 0x11.
  However, this ECU has BBDOWNLOAD_ENABLE_SBL=0 (no SBL), so the SBL guard is
  compiled out and 2E D01C IS processed in PBL. Actual behavior differs from spec.
  Test cases are written against actual ECU behavior.

NOTE - NRC 0x72 for F109:
  bbdiagdid_writeSecurityConstant() has no content validation; it writes any 16
  bytes unconditionally. NRC 0x72 is not achievable via content for F109.
  Never send arbitrary test data to F109 on an empty ECU -- it will be
  permanently written (one-time-write).

SKIP_DESTRUCTIVE_TESTS = True  (default): only non-destructive tests run.
Set to False on a fresh (fully erased) ECU to run the one-time-write tests.
"""

import sys
import time
from lin_tp_transport import LinTpTransport
from lin_uds_log import (
    LinUdsLog, bytes_to_hex, hex_to_bytes,
    check_positive_response, check_negative_response,
    read_current_session,
)

# ---------------------------------------------------------------------------
# Service / NRC constants
# ---------------------------------------------------------------------------
SID_WRITE  = 0x2E
SID_READ   = 0x22
NRC_INCORRECT_MSG_LENGTH   = 0x13
NRC_CONDITION_NOT_CORRECT  = 0x22
NRC_REQUEST_OUT_OF_RANGE   = 0x31
NRC_GENERAL_PROG_FAIL      = 0x72

# ---------------------------------------------------------------------------
# Write data
# ---------------------------------------------------------------------------
# 16-byte AES-CMAC Security Constant for Security Access level 01/02
# Source: supplied by GRI (ReqID 661284). Replace placeholder when received.
SECURITY_CONSTANT = "AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA"

# 292-byte RSA-2048 Public Key for software authentication (ReqID 664684)
# Layout: 256B modulus | 4B exponent (00 01 00 01) | 32B SHA256(modulus+exponent)
RSA_PUBLIC_KEY = (
    "B9 04 58 97 E1 2D AB C8 87 F7 B0 B9 33 46 82 F1 "
    "41 E0 F8 D0 56 4E 26 97 2B 87 13 60 97 74 6A 57 "
    "5C BE 9D 59 48 9B A7 5E E9 59 A4 70 0A B0 26 0C "
    "19 3D F3 2A 47 57 00 3D 10 7F 26 07 5F EE 3F 48 "
    "2B 76 E3 C9 81 84 E0 83 B3 E0 FE 7F 49 EB CE 98 "
    "B7 BB E1 FE 72 89 3E AF DE A5 C3 99 B3 1F B7 A8 "
    "9F CB F1 39 8B F6 A8 7B C0 A8 0E 79 E0 DC 2E 22 "
    "EB F2 48 4E 76 DF AD EF 46 AC 05 F7 CA FB 1B EC "
    "50 36 5A 3C 9F 2C 4F 7E B5 F9 02 32 96 70 18 A3 "
    "9E 23 41 2D 18 9B 60 A8 79 9F 50 FF 3A 17 1F 52 "
    "DE 53 68 48 2F A2 D5 E2 C3 20 E0 8E A5 A2 76 A3 "
    "34 8E C9 C6 7D 75 2E 14 8D C8 DA 76 9E 1A 34 F2 "
    "96 BC 17 2D 57 25 E1 F5 27 D4 03 C9 E3 2B 78 FD "
    "18 05 92 E0 C1 47 9A E1 5B 27 FD 1E E2 62 09 A3 "
    "01 7F 90 DA 45 65 9B 7E 7E AB 20 E6 10 41 D8 9B "
    "F3 34 ED 4B 2F 40 4B 3E 54 C0 6E 8A D5 50 B7 A7 "
    "00 01 00 01 "
    "49 80 2E 7E 19 11 8B 19 F9 E6 76 2E BC F3 3F B8 "
    "CB 14 6F 9D 8D A2 43 5F 0B 08 08 6B C7 CC D2 A5 "
)

# Guard flags for one-time-write tests.
# ECU is re-flashed (erased) before each test run, so both DIDs are always empty.
# Set both to False to run the full positive + already-written sequence each time.
# Set True only if running on an ECU that already has the DID written.
SKIP_F109_WRITE = False
SKIP_D01C_WRITE = False


# ===========================================================================
# N13 - Incorrect message length
# ===========================================================================

def test_n13_general_short(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """[N13-01] ReqID 663993
    2E F1  (2 bytes, < minimum 4 bytes SID+DID+1data) -> NRC 0x13
    """
    log.start_test("N13-01 | 0x2E F1 (2B) - NRC 0x13 incorrectMessageLength")
    req = bytes([0x2E, 0xF1])
    log.tx(bytes_to_hex(req), "2E + 1-byte DID fragment, length < 4")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID_WRITE, NRC_INCORRECT_MSG_LENGTH, log,
                                   "N13-01 NRC 0x13")


def test_n13_f109_wrong_length(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """[N13-F109] ReqID 677100
    2E F1 09 + 4 bytes  (data must be exactly 16B) -> NRC 0x13
    """
    log.start_test("N13-F109 | 0x2E F1 09 + 4B - NRC 0x13 (F109 data must be 16B)")
    req = bytes([0x2E, 0xF1, 0x09, 0xAA, 0xBB, 0xCC, 0xDD])
    log.tx(bytes_to_hex(req), "2E F1 09 + 4B data (need 16B)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID_WRITE, NRC_INCORRECT_MSG_LENGTH, log,
                                   "N13-F109 NRC 0x13")


def test_n13_d01c_no_data(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """[N13-D01C] ReqID 664684
    2E D0 1C  (3 bytes, data must be exactly 292B) -> NRC 0x13
    """
    log.start_test("N13-D01C | 0x2E D0 1C (3B, no data) - NRC 0x13 (D01C data must be 292B)")
    req = bytes([0x2E, 0xD0, 0x1C])
    log.tx(bytes_to_hex(req), "2E D0 1C no data (need 292B)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID_WRITE, NRC_INCORRECT_MSG_LENGTH, log,
                                   "N13-D01C NRC 0x13")


# ===========================================================================
# N22 - Read D01C before write (dev key -> conditions not correct)
# ===========================================================================

def test_n22_d01c_read_no_key(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """[N22-D01C-READ] ReqID 664684
    22 D0 1C when no production key written yet (ECU uses dev key) -> NRC 0x22
    Spec table: "With development Public Key / PBL / Read DID -> NRC 0x22"
    bbdiagdid_ReadPublicKeyChecksum(): isPublicKeyWritable()==TRUE -> NRC 0x22
    """
    log.start_test("N22-D01C-READ | 0x22 D0 1C (dev key, no prod key) - NRC 0x22 conditionNotCorrect")
    req = bytes([0x22, 0xD0, 0x1C])
    log.tx(bytes_to_hex(req), "ReadDataByIdentifier D01C (no prod key programmed)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID_READ, NRC_CONDITION_NOT_CORRECT, log,
                                   "N22-D01C-READ NRC 0x22")


# ===========================================================================
# N31 - Unsupported DID / read-prohibited DID
# ===========================================================================

def test_n31_unsupported_did(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """[N31-01] ReqID 663993
    2E FF FF 00 -> NRC 0x31 requestOutOfRange
    NOTE: must include >=1 data byte; 3-byte request hits NRC 0x13 (min-length) first.
    """
    log.start_test("N31-01 | 0x2E FF FF 00 - NRC 0x31 requestOutOfRange (unsupported DID)")
    req = bytes([0x2E, 0xFF, 0xFF, 0x00])
    log.tx(bytes_to_hex(req), "2E FF FF + 1 dummy byte")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID_WRITE, NRC_REQUEST_OUT_OF_RANGE, log,
                                   "N31-01 NRC 0x31")


def test_n31_f109_read_prohibited(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """[N31-F109-READ] ReqID 677100, 703288
    22 F1 09 -> NRC 0x31 (F109 cannot be read in any diagnostic session)
    Access group READABLE_NEVER_WRITABLE_ONCE: read_supported=FALSE -> NRC 0x31
    """
    log.start_test("N31-F109-READ | 0x22 F1 09 - NRC 0x31 (F109 not readable in any session)")
    req = bytes([0x22, 0xF1, 0x09])
    log.tx(bytes_to_hex(req), "ReadDataByIdentifier F109 (read prohibited)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID_READ, NRC_REQUEST_OUT_OF_RANGE, log,
                                   "N31-F109-READ NRC 0x31")


# ===========================================================================
# N72 - D01C SHA256 checksum mismatch
# ===========================================================================

def test_n72_d01c_bad_sha256(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """[N72-D01C] ReqID 664684
    2E D0 1C + 292B (first 2 bytes of modulus corrupted) -> NRC 0x72
    bbsecuritycfg_writePublicKey(): SHA256(corrupted) != appended checksum -> FALSE -> NRC 0x72
    Safe on empty ECU: SHA256 mismatch causes early return before any flash write.
    """
    log.start_test("N72-D01C | 0x2E D0 1C + bad SHA256 - NRC 0x72 generalProgrammingFailure")
    key_bytes = hex_to_bytes(RSA_PUBLIC_KEY)
    bad_key = bytes([0xFF, 0xFF]) + key_bytes[2:]   # corrupt first 2 bytes of modulus
    req = bytes([0x2E, 0xD0, 0x1C]) + bad_key
    log.tx(bytes_to_hex(req[:9]) + " ...", "2E D0 1C + 292B (SHA256 mismatch, first 2B corrupted)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID_WRITE, NRC_GENERAL_PROG_FAIL, log,
                                   "N72-D01C NRC 0x72")


# ===========================================================================
# Positive + destructive one-time-write tests (guarded by SKIP_DESTRUCTIVE_TESTS)
# ===========================================================================

def test_p_f109_write(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """[P-F109] ReqID 677100, 850391
    2E F1 09 + 16B security constant -> 6E F1 09
    One-time-write. Takes effect immediately (no reset needed) per ReqID 850391.
    DESTRUCTIVE. Requires fresh ECU with empty F109. Guarded by SKIP_F109_WRITE.
    NOTE: current ECU F109 already written with garbage -> keep SKIP_F109_WRITE=True.
    """
    if SKIP_F109_WRITE:
        log.info("[SKIP] P-F109: Write security constant skipped (SKIP_F109_WRITE=True)")
        return True
    log.start_test("P-F109 | 0x2E F1 09 + 16B - Write security constant (positive)")
    req = bytes([0x2E, 0xF1, 0x09]) + hex_to_bytes(SECURITY_CONSTANT)
    log.tx(bytes_to_hex(req[:6]) + " ... (16B)", "2E F1 09 + security constant")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_positive_response(resp, SID_WRITE, log, "P-F109 positive 6E F1 09")


def test_n22_f109_already_written(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """[N22-F109-WR] ReqID 703288
    2E F1 09 + 16B -> NRC 0x22 (F109 already written, write-once)
    Must run in same session as P-F109 (after write). Guarded by SKIP_F109_WRITE.
    """
    if SKIP_F109_WRITE:
        log.info("[SKIP] N22-F109-WR: skipped (SKIP_F109_WRITE=True)")
        return True
    log.start_test("N22-F109-WR | 0x2E F1 09 (already written) - NRC 0x22 conditionNotCorrect")
    req = bytes([0x2E, 0xF1, 0x09]) + hex_to_bytes(SECURITY_CONSTANT)
    log.tx(bytes_to_hex(req[:6]) + " ... (16B)", "2E F1 09 (F109 already written, write-once)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID_WRITE, NRC_CONDITION_NOT_CORRECT, log,
                                   "N22-F109-WR NRC 0x22")


def test_p_d01c_write(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """[P-D01C] ReqID 664684, 850391
    2E D0 1C + 292B correct key -> 6E D0 1C  (positive response)
    One-time-write. Guarded by SKIP_D01C_WRITE.
    """
    if SKIP_D01C_WRITE:
        log.info("[SKIP] P-D01C: Write RSA public key skipped (SKIP_D01C_WRITE=True)")
        return True
    log.start_test("P-D01C | 0x2E D0 1C + 292B - Write RSA public key (positive)")
    req = bytes([0x2E, 0xD0, 0x1C]) + hex_to_bytes(RSA_PUBLIC_KEY)
    log.tx(bytes_to_hex(req[:9]) + " ... (292B)", "2E D0 1C + RSA-2048 public key")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_positive_response(resp, SID_WRITE, log, "P-D01C positive 6E D0 1C")


def test_p22_d01c_read(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """[P22-D01C-READ] ReqID 664684, 850391
    22 D0 1C -> 62 D0 1C + 32B SHA256 checksum (immediate effect after write, ReqID 850391)
    Must run after test_p_d01c_write. Guarded by SKIP_D01C_WRITE.
    """
    if SKIP_D01C_WRITE:
        log.info("[SKIP] P22-D01C-READ: skipped (SKIP_D01C_WRITE=True)")
        return True
    key_bytes = hex_to_bytes(RSA_PUBLIC_KEY)
    expected_checksum = key_bytes[-32:]
    log.start_test("P22-D01C-READ | 0x22 D0 1C \u2013 32B checksum after write (ReqID 664684, 850391)")
    req = bytes([0x22, 0xD0, 0x1C])
    log.tx(bytes_to_hex(req), "ReadDataByIdentifier D01C (key written, read checksum)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    if len(resp) >= 3 + 32 and resp[:3] == bytes([0x62, 0xD0, 0x1C]):
        match = (resp[3:3 + 32] == expected_checksum)
        log.result(match,
                   expected="62 D0 1C " + bytes_to_hex(expected_checksum),
                   received=bytes_to_hex(resp),
                   description="P22-D01C-READ: checksum matches written key")
        return match
    log.result(False,
               expected="62 D0 1C + 32B checksum",
               received=bytes_to_hex(resp),
               description="P22-D01C-READ: unexpected response")
    return False


def test_n22_d01c_already_written(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """[N22-D01C-WR] ReqID 664684, 703288
    After P-D01C: 2E D0 1C + key again -> NRC 0x22
    bbsecuritycfg_writePublicKey(): isPublicKeyWritable()==FALSE -> NRC 0x22
    Runs after P-D01C. Guarded by SKIP_D01C_WRITE.
    """
    if SKIP_D01C_WRITE:
        log.info("[SKIP] N22-D01C-WR: already-written test skipped (SKIP_D01C_WRITE=True)")
        return True
    log.start_test("N22-D01C-WR | 0x2E D0 1C (already written) - NRC 0x22 conditionNotCorrect")
    req = bytes([0x2E, 0xD0, 0x1C]) + hex_to_bytes(RSA_PUBLIC_KEY)
    log.tx(bytes_to_hex(req[:9]) + " ... (292B)", "2E D0 1C (D01C already written, write-once)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID_WRITE, NRC_CONDITION_NOT_CORRECT, log,
                                   "N22-D01C-WR NRC 0x22")


# ===========================================================================
# Full test sequence
# ===========================================================================

def service_2e_all_tests(tp: LinTpTransport, log: LinUdsLog):
    """Service 0x2E WriteDataByIdentifier - Full Test (FBL/PBL, F109 + D01C only)

    Always run (non-destructive):
      N13-01          NRC 0x13  general too-short request          [663993]
      N13-F109        NRC 0x13  F109 wrong data length             [677100]
      N13-D01C        NRC 0x13  D01C no data                       [664684]
      N22-D01C-READ   NRC 0x22  read D01C when no prod key         [664684]
      N31-01          NRC 0x31  unsupported DID                    [663993]
      N31-F109-READ   NRC 0x31  F109 read prohibited               [677100, 703288]
      N72-D01C        NRC 0x72  D01C SHA256 mismatch               [664684]
      N22-F109-WR     NRC 0x22  F109 already written (current ECU: F109 has data) [703288]

    Guarded by SKIP_F109_WRITE (requires fresh ECU with empty F109):
      P-F109          write security constant -> 6E F1 09          [677100, 850391]

    Guarded by SKIP_D01C_WRITE (current ECU: D01C not written -> set False to run):
      P-D01C          write RSA public key -> 6E D0 1C             [664684, 850391]
      P22-D01C-READ   read back checksum -> 62 D0 1C + 32B         [664684, 850391]
      N22-D01C-WR     NRC 0x22 D01C already written                [664684, 703288]
    """
    from Service_10 import service_10_programming_session
    from Service_27 import service_27_security_access

    log.info("=" * 60)
    log.info("Service 0x2E WriteDataByIdentifier - FBL/PBL Full Test")
    log.info("=" * 60)
    log.info(f"SKIP_F109_WRITE = {SKIP_F109_WRITE}  SKIP_D01C_WRITE = {SKIP_D01C_WRITE}")

    read_current_session(tp, log)

    log.info("--- Setup: Enter Programming Session ---")
    service_10_programming_session(tp, log)
    time.sleep(0.1)

    log.info("--- Setup: SecurityAccess level 01 unlock ---")
    service_27_security_access(tp, log)
    time.sleep(0.1)

    # ---- Non-destructive negative tests ------------------------------------
    log.info("--- [N13] NRC 0x13 incorrectMessageLength ---")
    test_n13_general_short(tp, log)
    test_n13_f109_wrong_length(tp, log)
    test_n13_d01c_no_data(tp, log)

    log.info("--- [N22-D01C-READ] NRC 0x22 read D01C when no production key ---")
    test_n22_d01c_read_no_key(tp, log)

    log.info("--- [N31] NRC 0x31 requestOutOfRange ---")
    test_n31_unsupported_did(tp, log)
    test_n31_f109_read_prohibited(tp, log)

    log.info("--- [N72-D01C] NRC 0x72 D01C SHA256 mismatch ---")
    test_n72_d01c_bad_sha256(tp, log)

    # ---- F109 write test (SKIP_F109_WRITE, fresh ECU only) -----------------
    log.info("--- [P-F109] Write security constant (SKIP_F109_WRITE) ---")
    test_p_f109_write(tp, log)

    # ---- N22-F109-WR: always run (F109 already written on current ECU) -----
    log.info("--- [N22-F109-WR] NRC 0x22 F109 already written ---")
    test_n22_f109_already_written(tp, log)

    # ---- D01C write + read + already-written (SKIP_D01C_WRITE) ----------
    log.info("--- [P-D01C] Write RSA public key (SKIP_D01C_WRITE) ---")
    test_p_d01c_write(tp, log)
    log.info("--- [P22-D01C-READ] 22 D0 1C \u2013 read checksum after write (SKIP_D01C_WRITE) ---")
    test_p22_d01c_read(tp, log)

    log.info("--- [N22-D01C-WR] NRC 0x22 D01C already written (SKIP_D01C_WRITE) ---")
    test_n22_d01c_already_written(tp, log)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    log = LinUdsLog("Service_2E")
    tp  = LinTpTransport(logger=log)
    try:
        tp.open()
        service_2e_all_tests(tp, log)
    except Exception as e:
        log.error(str(e))
        raise
    finally:
        tp.close()
        log.close()
        sys.exit(0 if log.all_passed else 1)
