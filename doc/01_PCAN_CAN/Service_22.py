#!/usr/bin/env python3
"""
Service 0x22 – ReadDataByIdentifier (LIN / FBL context)
=========================================================
Standalone script. Must be in Programming Session before running.

Positive response:
  22 <DID_HI> <DID_LO>  →  62 <DID_HI> <DID_LO> <data...>

Negative responses:
  NRC 0x13 – incorrectMessageLength  : 22 F1 (too short) / 22 F1 8C 01 (too long)
  NRC 0x22 – conditionNotCorrect     : 22 D0 1C  (public key not written yet)
  NRC 0x31 – requestOutOfRange       : 22 F1 FF  (unsupported DID)

Reference: Service_22&2E_PBL.py / Service_22&2E_SBL.py
           (U:\\sandbox_2\\ZCU_VAVE\\03_tools\\ZCUP_Py_scripts\\LZCUP_Py_script\\05_Script\\Script)
"""

import sys
import time
from lin_tp_transport import LinTpTransport
from lin_uds_log import (
    LinUdsLog, bytes_to_hex, hex_to_bytes,
    check_positive_response, check_negative_response,
    read_current_session,
)
from lin_tp_config import NAD_FUNCTIONAL

SID = 0x22
SID_WRITE = 0x2E
NRC_INCORRECT_MSG_LENGTH   = 0x13
NRC_CONDITION_NOT_CORRECT  = 0x22
NRC_REQUEST_OUT_OF_RANGE   = 0x31

# ---------------------------------------------------------------------------
# DID table: [DID_hex, expected_data_len_bytes, default_value_hex, description]
# expected_data_len: length of data field AFTER the 3-byte prefix (62 DI DI)
# default_value_hex: "" means any value accepted; otherwise exact match checked
# ---------------------------------------------------------------------------
DID_TABLE = [
    # DID       len   default_value(hex, "" = any)   description
    ("F1 86",    1,   "",                            "Active Diagnostic Session"),
    ("F1 21",    7,   "",                            "PBL Diagnostic DB Part Number (Volvo)"),
    ("F1 25",    7,   "",                            "PBL SW Part Number (Volvo)"),
    ("F1 2A",    7,   "",                            "ECU Core Assembly Number (Volvo)"),
    ("F1 2B",    7,   "",                            "ECU Delivery Assembly Number (Volvo)"),
    ("F1 8A",    6,   "",                            "ECU Software Version Number"),
    ("F1 8C",    4,   "",                            "ECU Serial Number"),
    ("F1 A1",    8,   "",                            "PBL Diagnostic DB Part Number (Geely)"),
    ("F1 A5",    8,   "",                            "PBL SW Part Number (Geely)"),
    ("F1 AA",    8,   "",                            "ECU Core Assembly Number (Geely)"),
    ("F1 AB",    8,   "",                            "ECU Delivery Assembly Number (Geely)"),
    ("ED 20",   46,   "",                            "Number Collection (Geely)"),
    ("ED A0",   42,   "",                            "Number Collection (Volvo)"),
]



# ===========================================================================
# Positive Tests
# ===========================================================================

def service_22_read_did(tp: LinTpTransport, log: LinUdsLog,
                        did_hex: str, expected_len: int,
                        default_val: str, description: str,
                        nad: int = None) -> bool:
    """
    Send 22 <DID> and verify the response.
    - If default_val is non-empty: verify exact data bytes.
    - Otherwise: verify response length only.
    """
    nad_sfx = f" [NAD=0x{nad:02X}]" if nad is not None else ""
    log.start_test(f"0x22 {did_hex}{nad_sfx} – {description}")

    req = hex_to_bytes(f"22 {did_hex}")
    log.tx(bytes_to_hex(req), f"ReadDataByIdentifier {did_hex} ({description}){nad_sfx}")
    resp = tp.send_uds(req, nad=nad)
    log.rx(bytes_to_hex(resp))

    # Positive response SID = 0x62
    if not resp or resp[0] != 0x62:
        log.result(False,
                   expected=f"62 {did_hex} ...",
                   received=bytes_to_hex(resp),
                   description=f"ReadDataByIdentifier {did_hex} positive response{nad_sfx}")
        return False

    data = resp[3:]  # strip 62 DI DI

    if default_val:
        # Exact value check
        expected_data = hex_to_bytes(default_val)
        match = (data == expected_data)
        log.result(match,
                   expected=f"62 {did_hex} {default_val}",
                   received=bytes_to_hex(resp),
                   description=f"ReadDataByIdentifier {did_hex} value check{nad_sfx}")
        return match
    else:
        # Length check only
        match = (len(data) >= expected_len)
        log.result(match,
                   expected=f"62 {did_hex} + {expected_len} data bytes",
                   received=bytes_to_hex(resp),
                   description=f"ReadDataByIdentifier {did_hex} length check{nad_sfx}")
        return match


def service_22_all_dids(tp: LinTpTransport, log: LinUdsLog, nad: int = None) -> bool:
    """Read all DIDs in DID_TABLE and verify responses."""
    results = []
    for did_hex, exp_len, default_val, desc in DID_TABLE:
        results.append(service_22_read_did(tp, log, did_hex, exp_len, default_val, desc, nad=nad))
        time.sleep(0.05)
    return all(results)


# ===========================================================================
# Negative Tests
# ===========================================================================

def service_22_nrc13(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """NRC 0x13 – incorrectMessageLength"""
    all_pass = True

    # Case 1: too long (4 bytes: SID + 3-byte DID)
    log.start_test("0x22 F1 8C 01 – NRC 0x13 incorrectMessageLength (length > 3)")
    req = bytes([0x22, 0xF1, 0x8C, 0x01])
    log.tx(bytes_to_hex(req), "ReadDataByIdentifier length=4 (too long)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    all_pass &= check_negative_response(resp, SID, NRC_INCORRECT_MSG_LENGTH, log,
                                        "NRC 0x13 length > 3")

    # Case 2: too short (2 bytes: SID + 1-byte DID fragment)
    log.start_test("0x22 F1 – NRC 0x13 incorrectMessageLength (length < 3)")
    req = bytes([0x22, 0xF1])
    log.tx(bytes_to_hex(req), "ReadDataByIdentifier length=2 (too short)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    all_pass &= check_negative_response(resp, SID, NRC_INCORRECT_MSG_LENGTH, log,
                                        "NRC 0x13 length < 3")

    return all_pass


def service_22_d01c_sequence(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """[D01C] Full 22/2E D01C test sequence (requires fresh ECU - manual erase before run)
    Step 1: 22 D0 1C  -> NRC 0x22  conditionNotCorrect (key not written)
    Step 2: 27 unlock -> SecurityAccess level 01 (needed for 2E write)
    Step 3: 2E D0 1C + 292B -> 6E D0 1C  (write RSA public key)
    Step 4: 22 D0 1C  -> 62 D0 1C + 32B  checksum (key written, immediate effect)
    """
    from Service_27 import service_27_security_access
    from Service_2E import RSA_PUBLIC_KEY
    all_pass = True
    key_bytes = hex_to_bytes(RSA_PUBLIC_KEY)
    expected_checksum = key_bytes[-32:]

    # --- Step 1: 22 D0 1C before write -> NRC 0x22 ---
    log.start_test("D01C-1 | 22 D0 1C - NRC 0x22 conditionNotCorrect (key not written)")
    req = bytes([0x22, 0xD0, 0x1C])
    log.tx(bytes_to_hex(req), "ReadDataByIdentifier D01C (before write)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    all_pass &= check_negative_response(resp, SID, NRC_CONDITION_NOT_CORRECT, log,
                                        "D01C-1: NRC 0x22 key not written")

    # --- Step 2: SecurityAccess unlock (required for 2E write) ---
    log.info("--- D01C: SecurityAccess unlock (required for 2E D01C write) ---")
    all_pass &= service_27_security_access(tp, log)
    time.sleep(0.05)

    # --- Step 3: 2E D0 1C + 292B -> 6E D0 1C ---
    log.start_test("D01C-2 | 2E D0 1C + 292B - Write RSA public key -> 6E D0 1C")
    req_write = bytes([0x2E, 0xD0, 0x1C]) + key_bytes
    log.tx(bytes_to_hex(req_write[:9]) + " ... (292B)", "WriteDataByIdentifier D01C (292B RSA key)")
    resp = tp.send_uds(req_write)
    log.rx(bytes_to_hex(resp))
    all_pass &= check_positive_response(resp, SID_WRITE, log, "D01C-2: positive 6E D0 1C")

    # --- Step 4: 22 D0 1C after write -> 62 D0 1C + 32B checksum ---
    log.start_test("D01C-3 | 22 D0 1C - 62 D0 1C + 32B checksum (key written)")
    req = bytes([0x22, 0xD0, 0x1C])
    log.tx(bytes_to_hex(req), "ReadDataByIdentifier D01C (after write, read checksum)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    if len(resp) >= 3 + 32 and resp[:3] == bytes([0x62, 0xD0, 0x1C]):
        match = (resp[3:3 + 32] == expected_checksum)
        log.result(match,
                   expected="62 D0 1C " + bytes_to_hex(expected_checksum),
                   received=bytes_to_hex(resp),
                   description="D01C-3: checksum matches written key")
        all_pass &= match
    else:
        log.result(False,
                   expected="62 D0 1C + 32B checksum",
                   received=bytes_to_hex(resp),
                   description="D01C-3: unexpected response")
        all_pass = False

    return all_pass


def service_22_nrc31(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """NRC 0x31 – requestOutOfRange (unsupported DID)"""
    log.start_test("0x22 F1 FF – NRC 0x31 requestOutOfRange (unsupported DID)")
    req = bytes([0x22, 0xF1, 0xFF])
    log.tx(bytes_to_hex(req), "ReadDataByIdentifier F1FF (unsupported DID)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID, NRC_REQUEST_OUT_OF_RANGE, log,
                                   "NRC 0x31 unsupported DID")


# ===========================================================================
# Full test sequence
# ===========================================================================

def service_22_all_tests(tp: LinTpTransport, log: LinUdsLog):
    """
    Full Service 0x22 test suite (FBL/PBL):

    Setup        Enter Programming Session
    N13-01       NRC 0x13 too long  (22 F1 8C 01)
    N13-02       NRC 0x13 too short (22 F1)
    N31-01       NRC 0x31 unsupported DID (22 F1 FF)
    PREREQUISITE: Manual erase (re-flash) ECU before each run to ensure D01C is empty.

    D01C-1       22 D0 1C -> NRC 0x22 (key not written)     [requires fresh ECU]
    D01C-2       27 unlock + 2E D0 1C + 292B -> 6E D0 1C   (write key)
    D01C-3       22 D0 1C -> 62 D0 1C + 32B checksum        (verify write)
    P-xx         Positive read all DIDs in DID_TABLE (physical NAD=0x67)
    P-Fxx        Positive read all DIDs (functional NAD=0x7E, no response expected)

    DIDs tested: F186 F121 F125 F12A F12B F18C F1A1 F1A5 F1AA F1AB ED20 EDA0
    """
    from Service_10 import service_10_programming_session

    log.info("=" * 60)
    log.info("Service 0x22 ReadDataByIdentifier – Full Test")
    log.info("=" * 60)

    read_current_session(tp, log)

    log.info("--- Setup: Enter Programming Session ---")
    service_10_programming_session(tp, log)
    time.sleep(0.1)

    # Negative tests
    log.info("--- [N13] Negative Tests: NRC 0x13 incorrectMessageLength ---")
    service_22_nrc13(tp, log)

    log.info("--- [N31] Negative Tests: NRC 0x31 requestOutOfRange ---")
    service_22_nrc31(tp, log)

    # D01C: NRC 0x22 (not written) or 62 D0 1C + 32B (written)
    log.info("--- [D01C] 22 D0 1C \u2013 NRC 0x22 (not written) / 62 D0 1C +32B (written) ---")
    service_22_d01c_sequence(tp, log)

    # Positive tests – physical addressing
    log.info("--- [P] Positive Tests: Read all DIDs (physical NAD=0x67) ---")
    service_22_all_dids(tp, log)

    # Positive tests – functional addressing (no response expected)
    log.info("--- [P-F] Positive Tests: Read all DIDs (functional NAD=0x7E, no response) ---")
    for did_hex, exp_len, default_val, desc in DID_TABLE:
        log.start_test(f"0x22 {did_hex} [NAD=0x7E] – {desc} (functional, no response)")
        req = hex_to_bytes(f"22 {did_hex}")
        log.tx(bytes_to_hex(req), f"ReadDataByIdentifier {did_hex} (functional)")
        tp.send_uds(req, nad=NAD_FUNCTIONAL, expect_response=False)
        time.sleep(0.05)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    log = LinUdsLog("Service_22")
    tp  = LinTpTransport(logger=log)
    try:
        tp.open()
        service_22_all_tests(tp, log)
    except Exception as e:
        log.error(str(e))
        raise
    finally:
        tp.close()
        log.close()
        sys.exit(0 if log.all_passed else 1)
