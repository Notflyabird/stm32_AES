#!/usr/bin/env python3
"""
Service 0x27 – SecurityAccess (LIN / FBL context)
==================================================
Standalone script. Must be in Programming Session before running.

Positive response:
  27 01 → 67 01 + seed (16 bytes)
  27 02 + key (16 bytes) → 67 02

Negative responses (ReqID 853765):
  NRC 0x12 – subFunctionNotSupported  : 27 00 / 27 03
  NRC 0x13 – incorrectMessageLength   : 27 / 27 01 00 / 27 02 00
  NRC 0x24 – requestSequenceError     : 27 02 before 27 01
  NRC 0x35 – invalidKey               : wrong key, attempt 1
  NRC 0x36 – exceededNumberOfAttempts : wrong key, attempt 2 → triggers T1 lockout
  NRC 0x37 – requiredTimeDelayNotExp  : RequestSeed during T1 lockout

Lockout rules (ReqID 661292):
  T1 (delay after false attempts) : 10 s  (default; ECU may configure longer)
  T2 (delay at every start)       : 0 s
  Max false attempts before T1    : 2
  Lockout stored in NVM – ECU Reset does NOT clear lockout when cnt=2
  ECU Reset clears counter only when cnt=1
"""

import sys
import time
from lin_tp_transport import LinTpTransport
from lin_uds_log import (
    LinUdsLog, bytes_to_hex,
    check_positive_response, check_negative_response,
    read_current_session,
)
from lin_tp_config import SA_REQUEST_LEVEL, SA_SEND_KEY_LEVEL

SID = 0x27

NRC_SUB_FUNC_NOT_SUPPORTED   = 0x12
NRC_INCORRECT_MSG_LENGTH      = 0x13
NRC_REQUEST_SEQUENCE_ERROR    = 0x24
NRC_INVALID_KEY               = 0x35
NRC_EXCEEDED_ATTEMPTS         = 0x36
NRC_TIME_DELAY_NOT_EXPIRED    = 0x37

# Wrong key used for negative tests (all zeros – guaranteed incorrect)
_WRONG_KEY = bytes(16)

# Delay timer T1 after NRC 0x36 lockout (seconds).
# Spec default = 10 s (ReqID 661292). ECU may configure longer.
# Lockout is stored in NVM – ECU Reset does not clear it when cnt=2.
LOCKOUT_WAIT_S = 10.0

# --------------------------------------------------------------------------
# Security Key Algorithm
# Replace CMAC_KEY with the actual 16-byte (128-bit) AES key for this project.
# --------------------------------------------------------------------------
# TODO: Replace with real key – current value is a placeholder!
CMAC_KEY = "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF"   # ← REPLACE THIS


def _compute_key(seed: bytes) -> bytes:
    """
    AES-CMAC of seed using CMAC_KEY.
    Replace or extend for project-specific algorithm.
    """
    try:
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives import cmac
        from cryptography.hazmat.primitives.ciphers import algorithms

        key = bytes.fromhex(CMAC_KEY)
        c   = cmac.CMAC(algorithms.AES(key), backend=default_backend())
        c.update(seed)
        return c.finalize()[:len(seed)]
    except ImportError:
        return bytes(b ^ 0xFF for b in seed)   # fallback placeholder


# ==========================================================================
# Positive test
# ==========================================================================

def service_27_security_access(tp: LinTpTransport, log: LinUdsLog,
                                nad: int = None) -> bool:
    """Full seed-key SecurityAccess sequence. Returns True on success."""
    sfx = f" [NAD={nad:02X}]" if nad is not None else ""

    # Step 1 – Request seed
    log.start_test(f"0x27 {SA_REQUEST_LEVEL:02X}{sfx} – SecurityAccess: Request Seed")
    req_seed = bytes([SID, SA_REQUEST_LEVEL])
    log.tx(bytes_to_hex(req_seed), f"SecurityAccess requestSeed{sfx}")
    resp = tp.send_uds(req_seed, nad=nad)
    log.rx(bytes_to_hex(resp))

    if not check_positive_response(resp, SID, log, f"Seed request positive response{sfx}"):
        return False

    if len(resp) < 18:
        log.error(f"Seed response too short: {len(resp)} bytes (expected 18)")
        return False

    seed = resp[2:]
    log.info(f"Seed received: {bytes_to_hex(seed)}")

    if all(b == 0 for b in seed):
        log.info("Seed = 0x00... – ECU already unlocked")
        return True

    # Step 2 – Send key
    log.start_test(f"0x27 {SA_SEND_KEY_LEVEL:02X}{sfx} – SecurityAccess: Send Key")
    key     = _compute_key(seed)
    req_key = bytes([SID, SA_SEND_KEY_LEVEL]) + key
    log.tx(bytes_to_hex(req_key), f"SecurityAccess sendKey{sfx}")
    resp = tp.send_uds(req_key, nad=nad)
    log.rx(bytes_to_hex(resp))

    return check_positive_response(resp, SID, log, f"Key accepted positive response{sfx}")


# ==========================================================================
# NRC 0x12 – subFunctionNotSupported
# ==========================================================================

def service_27_nrc12(tp: LinTpTransport, log: LinUdsLog,
                     nad: int = None) -> bool:
    sfx      = f" [NAD={nad:02X}]" if nad is not None else ""
    all_pass = True

    # Case 1: sub-function 0x00 (reserved)
    log.start_test(f"0x27 00{sfx} – NRC 0x12 subFunctionNotSupported (sub-function 0x00)")
    req  = bytes([0x27, 0x00])
    log.tx(bytes_to_hex(req), f"SecurityAccess subFunction=0x00{sfx}")
    resp = tp.send_uds(req, nad=nad)
    log.rx(bytes_to_hex(resp))
    all_pass &= check_negative_response(resp, SID, NRC_SUB_FUNC_NOT_SUPPORTED, log,
                                        f"NRC 0x12 for sub-function 0x00{sfx}")

    # Case 2: sub-function 0x03 (unsupported level)
    log.start_test(f"0x27 03{sfx} – NRC 0x12 subFunctionNotSupported (sub-function 0x03)")
    req  = bytes([0x27, 0x03])
    log.tx(bytes_to_hex(req), f"SecurityAccess subFunction=0x03{sfx}")
    resp = tp.send_uds(req, nad=nad)
    log.rx(bytes_to_hex(resp))
    all_pass &= check_negative_response(resp, SID, NRC_SUB_FUNC_NOT_SUPPORTED, log,
                                        f"NRC 0x12 for sub-function 0x03{sfx}")

    return all_pass


# ==========================================================================
# NRC 0x13 – incorrectMessageLengthOrInvalidFormat
# Split into two functions:
#   service_27_nrc13_no_key  – cases that don't need locked state (cases 1 & 2)
#   service_27_nrc13_key_length – case 3: ECU must be locked for length check to
#                                 take priority over sequence check
# ==========================================================================

def service_27_nrc13_no_key(tp: LinTpTransport, log: LinUdsLog,
                             nad: int = None) -> bool:
    sfx      = f" [NAD={nad:02X}]" if nad is not None else ""
    all_pass = True

    # Case 1: too short – SID only
    log.start_test(f"0x27{sfx} – NRC 0x13 incorrectMessageLength (SID only, length=1)")
    req  = bytes([0x27])
    log.tx(bytes_to_hex(req), f"SecurityAccess length=1 (too short){sfx}")
    resp = tp.send_uds(req, nad=nad)
    log.rx(bytes_to_hex(resp))
    all_pass &= check_negative_response(resp, SID, NRC_INCORRECT_MSG_LENGTH, log,
                                        f"NRC 0x13 for length=1{sfx}")

    # Case 2: 27 01 with extra byte (seed request must be exactly 2 bytes)
    log.start_test(f"0x27 01 00{sfx} – NRC 0x13 incorrectMessageLength (seed request length > 2)")
    req  = bytes([0x27, 0x01, 0x00])
    log.tx(bytes_to_hex(req), f"SecurityAccess seedRequest length=3 (too long){sfx}")
    resp = tp.send_uds(req, nad=nad)
    log.rx(bytes_to_hex(resp))
    all_pass &= check_negative_response(resp, SID, NRC_INCORRECT_MSG_LENGTH, log,
                                        f"NRC 0x13 for 27 01 length=3{sfx}")

    return all_pass


def service_27_nrc13_key_length(tp: LinTpTransport, log: LinUdsLog,
                                nad: int = None) -> bool:
    """
    Case 3: 27 02 with wrong key length.
    ECU must be in LOCKED state; only then does NRC 0x13 (length) take priority
    over NRC 0x24 (sequence). Pre-step requests a seed to establish sequence.
    """
    sfx      = f" [NAD={nad:02X}]" if nad is not None else ""
    all_pass = True

    # Pre-step: request seed to establish correct sequence context
    log.start_test(f"0x27 01{sfx} – NRC 0x13 pre-step: request seed before wrong-length key")
    req  = bytes([0x27, SA_REQUEST_LEVEL])
    log.tx(bytes_to_hex(req), f"SecurityAccess requestSeed (pre-step for NRC 0x13 key-length test){sfx}")
    resp = tp.send_uds(req, nad=nad)
    log.rx(bytes_to_hex(resp))
    check_positive_response(resp, SID, log, f"Seed received (NRC 0x13 pre-step){sfx}")

    log.start_test(f"0x27 02 00{sfx} – NRC 0x13 incorrectMessageLength (key length wrong, need 18 bytes)")
    req  = bytes([0x27, 0x02, 0x00])
    log.tx(bytes_to_hex(req), f"SecurityAccess sendKey length=3 wrong (need 18){sfx}")
    resp = tp.send_uds(req, nad=nad)
    log.rx(bytes_to_hex(resp))
    all_pass &= check_negative_response(resp, SID, NRC_INCORRECT_MSG_LENGTH, log,
                                        f"NRC 0x13 for 27 02 wrong key length{sfx}")

    return all_pass


def service_27_nrc13(tp: LinTpTransport, log: LinUdsLog,
                     nad: int = None) -> bool:
    """Run all NRC 0x13 cases (caller must ensure ECU is in locked state)."""
    r1 = service_27_nrc13_no_key(tp, log, nad=nad)
    r2 = service_27_nrc13_key_length(tp, log, nad=nad)
    return r1 and r2


# ==========================================================================
# NRC 0x24 – requestSequenceError
# ==========================================================================

def service_27_nrc24(tp: LinTpTransport, log: LinUdsLog,
                     nad: int = None) -> bool:
    """Send key (27 02) before requesting seed (27 01) → expect 7F 27 24."""
    sfx = f" [NAD={nad:02X}]" if nad is not None else ""
    log.start_test(f"0x27 02 + key{sfx} – NRC 0x24 requestSequenceError (key before seed)")
    req  = bytes([0x27, 0x02]) + _WRONG_KEY
    log.tx(bytes_to_hex(req), f"SecurityAccess sendKey without prior seedRequest{sfx}")
    resp = tp.send_uds(req, nad=nad)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID, NRC_REQUEST_SEQUENCE_ERROR, log,
                                   f"NRC 0x24 key before seed{sfx}")


# ==========================================================================
# NRC 0x35 – invalidKey  (1st wrong key attempt)
# ==========================================================================

def service_27_nrc35(tp: LinTpTransport, log: LinUdsLog,
                     nad: int = None) -> bool:
    """Request valid seed then send wrong key → expect 7F 27 35."""
    sfx = f" [NAD={nad:02X}]" if nad is not None else ""

    log.start_test(f"0x27 01{sfx} – NRC 0x35 invalidKey: request seed")
    req  = bytes([0x27, SA_REQUEST_LEVEL])
    log.tx(bytes_to_hex(req), f"SecurityAccess requestSeed{sfx}")
    resp = tp.send_uds(req, nad=nad)
    log.rx(bytes_to_hex(resp))
    if not check_positive_response(resp, SID, log, f"Seed received for NRC 0x35 test{sfx}"):
        return False

    log.start_test(f"0x27 02 + wrong key{sfx} – NRC 0x35 invalidKey")
    req  = bytes([0x27, SA_SEND_KEY_LEVEL]) + _WRONG_KEY
    log.tx(bytes_to_hex(req), f"SecurityAccess sendKey wrong key (attempt 1){sfx}")
    resp = tp.send_uds(req, nad=nad)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID, NRC_INVALID_KEY, log,
                                   f"NRC 0x35 wrong key attempt 1{sfx}")


# ==========================================================================
# NRC 0x36 – exceededNumberOfAttempts  (2nd wrong key, triggers lockout)
# ==========================================================================

def service_27_nrc36(tp: LinTpTransport, log: LinUdsLog,
                     nad: int = None) -> bool:
    """Send another wrong key after NRC 0x35 to exceed attempt counter → 7F 27 36."""
    sfx = f" [NAD={nad:02X}]" if nad is not None else ""

    log.start_test(f"0x27 01{sfx} – NRC 0x36 exceededAttempts: request seed again")
    req  = bytes([0x27, SA_REQUEST_LEVEL])
    log.tx(bytes_to_hex(req), f"SecurityAccess requestSeed{sfx}")
    resp = tp.send_uds(req, nad=nad)
    log.rx(bytes_to_hex(resp))
    if not check_positive_response(resp, SID, log, f"Seed received for NRC 0x36 test{sfx}"):
        return False

    log.start_test(f"0x27 02 + wrong key{sfx} – NRC 0x36 exceededNumberOfAttempts")
    req  = bytes([0x27, SA_SEND_KEY_LEVEL]) + _WRONG_KEY
    log.tx(bytes_to_hex(req), f"SecurityAccess sendKey wrong key (attempt 2 – triggers lockout){sfx}")
    resp = tp.send_uds(req, nad=nad)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID, NRC_EXCEEDED_ATTEMPTS, log,
                                   f"NRC 0x36 exceeded attempts{sfx}")


# ==========================================================================
# NRC 0x37 – requiredTimeDelayNotExpired  (after lockout)
# ==========================================================================

def service_27_nrc37(tp: LinTpTransport, log: LinUdsLog,
                     nad: int = None) -> bool:
    """Attempt seed request immediately after NRC 0x36 lockout → 7F 27 37."""
    sfx = f" [NAD={nad:02X}]" if nad is not None else ""
    log.start_test(f"0x27 01{sfx} – NRC 0x37 requiredTimeDelayNotExpired (after lockout)")
    req  = bytes([0x27, SA_REQUEST_LEVEL])
    log.tx(bytes_to_hex(req), f"SecurityAccess requestSeed during delay timer{sfx}")
    resp = tp.send_uds(req, nad=nad)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID, NRC_TIME_DELAY_NOT_EXPIRED, log,
                                   f"NRC 0x37 time delay not expired{sfx}")


# ==========================================================================
# Full test sequence
# ==========================================================================

def service_27_all_tests(tp: LinTpTransport, log: LinUdsLog):
    """
    Test execution order per SWRS ReqID 663979 / 661292 (§11 of test spec):

    P-01/02   Positive seed-key unlock
    N12       NRC 0x12 sub-function not supported
    N13-01/02 NRC 0x13 too short / too long (no locked-state dependency)
    N24-01    NRC 0x24 key before seed (ECU Reset first to clear seed state)
    N13-03    NRC 0x13 wrong key length (locked state required)
    N35-01    NRC 0x35 first wrong key (cnt: 0→1)
    N36-01    NRC 0x36 second wrong key (cnt: 1→2, triggers T1 lockout)
    N37-01    NRC 0x37 immediately after lockout
    N37-02    ECUReset after lockout → NRC 0x37 still (NVM persistence, ReqID 661292)
    [wait T1] delay timer expires
    P-01/02   Final positive verification
    """
    from Service_10 import service_10_programming_session, service_10_default_session
    from Service_11 import service_11_hard_reset

    log.info("=" * 60)
    log.info("Service 0x27 SecurityAccess – Full Test")
    log.info("=" * 60)

    # --- Read initial session ---
    read_current_session(tp, log)

    # --- Enter programming session ---
    log.info("--- Setup: Enter Programming Session ---")
    service_10_programming_session(tp, log)
    time.sleep(0.1)

    # --- P-01 / P-02: Positive test ---
    log.info("--- [P-01/P-02] Positive Test: Seed-Key Security Access ---")
    service_27_security_access(tp, log)

    # --- N12: NRC 0x12 ---
    log.info("--- [N12] Negative Tests: NRC 0x12 subFunctionNotSupported ---")
    service_27_nrc12(tp, log)

    # --- N13-01/02: NRC 0x13 (no locked-state dependency) ---
    log.info("--- [N13-01/02] Negative Tests: NRC 0x13 incorrectMessageLength (cases 1 & 2) ---")
    service_27_nrc13_no_key(tp, log)

    # --- N24-01: NRC 0x24 (seed consumed by positive test; send key without seed) ---
    log.info("--- [N24-01] Negative Tests: NRC 0x24 requestSequenceError ---")
    service_27_nrc24(tp, log)

    # --- Reset to locked state before NRC 0x13 key-length / 0x35 / 0x36 / 0x37 tests ---
    # Positive test leaves ECU unlocked. Locked state required for NRC 0x13 case 3
    # and for NRC 0x35/0x36 chain (ReqID 661292: cnt=0 after successful unlock).
    log.info("--- Reset to locked state (11 01 hardReset, cnt=0) ---")
    service_11_hard_reset(tp, log)
    service_10_programming_session(tp, log)
    time.sleep(0.1)

    # --- N13-03: NRC 0x13 key-length wrong (locked state required) ---
    log.info("--- [N13-03] Negative Tests: NRC 0x13 key-length case (locked state) ---")
    service_27_nrc13_key_length(tp, log)

    # --- Reset to clear attempt counter before NRC 0x35/0x36/0x37 chain ---
    # ECU counts a sendKey with NRC 0x13 (wrong length) as a failed attempt (cnt: 0→1).
    # Reset here ensures cnt=0 when entering the NRC 0x35 test.
    log.info("--- Reset to clear attempt counter before NRC 0x35 test (cnt=0) ---")
    service_11_hard_reset(tp, log)
    service_10_programming_session(tp, log)
    time.sleep(0.1)

    # --- N35-01: NRC 0x35 first wrong key (cnt: 0→1) ---
    log.info("--- [N35-01] Negative Tests: NRC 0x35 invalidKey (attempt 1, cnt: 0→1) ---")
    service_27_nrc35(tp, log)

    # --- N36-01: NRC 0x36 second wrong key (cnt: 1→2, T1 lockout starts) ---
    log.info("--- [N36-01] Negative Tests: NRC 0x36 exceededNumberOfAttempts (attempt 2, T1 starts) ---")
    service_27_nrc36(tp, log)

    # --- N37-01: NRC 0x37 immediately after lockout ---
    log.info("--- [N37-01] Negative Tests: NRC 0x37 requiredTimeDelayNotExpired (immediately after lockout) ---")
    service_27_nrc37(tp, log)

    # --- N37-02: ECUReset after lockout → NRC 0x37 still (NVM persistence, ReqID 661292) ---
    # Per spec: when cnt=2, ECU stores T1 activation in NVM.
    # ECU Reset does NOT clear lockout – NRC 0x37 must still be returned.
    log.info("--- [N37-02] NRC 0x37 NVM persistence: ECUReset after lockout → NRC 0x37 still returned ---")
    service_11_hard_reset(tp, log)
    service_10_programming_session(tp, log)
    time.sleep(0.1)
    service_27_nrc37(tp, log)

    # --- Wait for T1 delay timer to expire (ReqID 661292: default T1=10s) ---
    log.info(f"--- Waiting T1={LOCKOUT_WAIT_S}s for delay timer to expire (ReqID 661292) ---")
    if LOCKOUT_WAIT_S > 2:
        time.sleep(LOCKOUT_WAIT_S - 2.3)
        log.info("--- [N37-03] NRC 0x37 test at T1-2s ---")
        service_27_nrc37(tp, log)
        time.sleep(2)
    else:
        time.sleep(LOCKOUT_WAIT_S)

    # --- Final positive verification after T1 expired ---
    log.info("--- Post-T1: Enter Programming Session and Verify Security Access ---")
    service_10_programming_session(tp, log)
    time.sleep(0.1)
    service_27_security_access(tp, log)

    # --- N37-04: ECUReset at T1-5s → NRC 0x37 still, then wait remaining 5s → positive ---
    # Trigger a fresh lockout (cnt=2), wait 5s, then perform ECU Reset mid-lockout.
    # After reset: NRC 0x37 expected (NVM persists timer).
    # After remaining ~5s: T1 expires → positive seed-key succeeds.
    log.info("--- [N37-04] ECUReset at T1-5s: setup lockout again ---")
    service_10_programming_session(tp, log)
    time.sleep(0.1)

    # Generate new lockout (2 wrong keys)
    log.info("--- [N37-04] Setup: 2 wrong keys to trigger lockout ---")
    service_27_nrc35(tp, log)   # cnt: 0→1
    service_27_nrc36(tp, log)   # cnt: 1→2, T1 starts

    # Wait until T1-5s, then reset
    _wait_before_reset = LOCKOUT_WAIT_S - 5.0
    if _wait_before_reset > 0:
        log.info(f"--- [N37-04] Waiting {_wait_before_reset}s (T1-5s) before ECUReset ---")
        time.sleep(_wait_before_reset)

    log.info("--- [N37-04] ECUReset at T1-5s ---")
    service_11_hard_reset(tp, log)
    service_10_programming_session(tp, log)
    time.sleep(0.1)

    # Immediately after reset: NRC 0x37 expected (NVM timer persists)
    log.info("--- [N37-04a] NRC 0x37 immediately after reset at T1-5s ---")
    service_27_nrc37(tp, log)

    # Wait remaining ~5s for T1 to expire
    log.info("--- [N37-04] Waiting 5.0s for remaining T1 to expire ---")
    time.sleep(5.0)

    # After T1 expired: positive seed-key expected
    log.info("--- [N37-04b] Positive SecurityAccess after remaining T1 expired ---")
    service_10_programming_session(tp, log)
    time.sleep(0.1)
    service_27_security_access(tp, log)


# --------------------------------------------------------------------------
if __name__ == "__main__":
    log = LinUdsLog("Service_27")
    tp  = LinTpTransport(logger=log)
    try:
        tp.open()
        service_27_all_tests(tp, log)
    except Exception as e:
        log.error(str(e))
    finally:
        tp.close()
        log.close()
        sys.exit(0 if log.all_passed else 1)
