#!/usr/bin/env python3
"""
Service 0x27 – SecurityAccess (CAN / UDS context)
===================================================
Standalone script for CAN-based security access.
Must be in Programming Session before running.

Positive response:
  27 01 → 67 01 + seed (16 bytes)
  27 02 + key (16 bytes) → 67 02

Security key algorithm: AES-CMAC(CMAC_KEY, seed)

Notes:
  - Replace CMAC_KEY with the actual 16-byte AES key for this project.
  - Seed length is 16 bytes, key length is 16 bytes.
"""

import sys
import time
from can_tp_transport import CanTpTransport
from can_uds_log import (
    CanUdsLog, bytes_to_hex,
    check_positive_response, check_negative_response,
    read_current_session,
)


SID = 0x27

NRC_SUB_FUNC_NOT_SUPPORTED     = 0x12
NRC_INCORRECT_MSG_LENGTH       = 0x13
NRC_REQUEST_SEQUENCE_ERROR     = 0x24
NRC_INVALID_KEY                = 0x35
NRC_EXCEEDED_ATTEMPTS          = 0x36
NRC_TIME_DELAY_NOT_EXPIRED     = 0x37

# Default wrong key for negative tests (all zeros – guaranteed incorrect)
_WRONG_KEY = bytes(16)

# Delay timer T1 after NRC 0x36 lockout (seconds)
LOCKOUT_WAIT_S = 10.0

# --------------------------------------------------------------------------
# Security Key Algorithm
# Replace CMAC_KEY with the actual 16-byte (128-bit) AES key for this project.
# --------------------------------------------------------------------------
# TODO: Replace with real key – current value is a placeholder!
CMAC_KEY = "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF"   # ← REPLACE THIS

SA_REQUEST_LEVEL  = 0x01
SA_SEND_KEY_LEVEL = 0x02


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
        c = cmac.CMAC(algorithms.AES(key), backend=default_backend())
        c.update(seed)
        return c.finalize()[:len(seed)]
    except ImportError:
        # Fallback: XOR placeholder (NOT production-safe!)
        return bytes(b ^ 0xFF for b in seed)


# ==========================================================================
# Public API
# ==========================================================================

def service_27_security_access(tp: CanTpTransport, log: CanUdsLog) -> bool:
    """
    Full SecurityAccess flow:
      1. Request seed (27 01) → receive seed (67 01 + 16 bytes)
      2. Compute key via AES-CMAC
      3. Send key (27 02 + key) → receive OK (67 02)

    Returns True on success.
    """
    log.start_test("0x27 01 – SecurityAccess: Request Seed")

    req_seed = bytes([0x27, SA_REQUEST_LEVEL])
    resp = tp.send_uds(req_seed)

    if not check_positive_response(resp, SID, log, "RequestSeed positive response"):
        return False

    # Extract seed (response = 67 01 + seed_bytes)
    seed = resp[2:]
    log.info(f"Seed ({len(seed)} bytes): {bytes_to_hex(seed)}")

    if len(seed) < 1:
        log.error(f"Seed is empty or too short ({len(seed)} bytes)")
        return False

    # Compute key
    log.start_test("0x27 02 – SecurityAccess: Send Key")
    key = _compute_key(seed)
    log.info(f"Computed key ({len(key)} bytes): {bytes_to_hex(key)}")

    req_key = bytes([0x27, SA_SEND_KEY_LEVEL]) + key
    resp = tp.send_uds(req_key)

    return check_positive_response(resp, SID, log, "SendKey positive response")


# ==========================================================================
# Negative test helpers
# ==========================================================================

def service_27_wrong_key(tp: CanTpTransport, log: CanUdsLog) -> bool:
    """Send known-wrong key → expect NRC 0x35 (invalidKey)."""
    log.start_test("0x27 02 – Wrong key → NRC 0x35")

    # First get a valid seed
    req_seed = bytes([0x27, SA_REQUEST_LEVEL])
    resp = tp.send_uds(req_seed)
    if len(resp) < 3:
        log.error("No seed received")
        return False

    # Send wrong key
    req = bytes([0x27, SA_SEND_KEY_LEVEL]) + _WRONG_KEY
    resp = tp.send_uds(req)
    return check_negative_response(resp, SID, NRC_INVALID_KEY, log, "NRC 0x35 for wrong key")


# ==========================================================================
# Full test sequence
# ==========================================================================

def service_27_all_tests(tp: CanTpTransport, log: CanUdsLog):
    log.info("=" * 60)
    log.info("Service 0x27 SecurityAccess – Full Test (CAN)")
    log.info("=" * 60)

    # Read current session
    read_current_session(tp, log)

    # Positive test
    log.info("--- Positive: Security Access ---")
    service_27_security_access(tp, log)

    # Negative test
    log.info("--- Negative: Wrong key ---")
    service_27_wrong_key(tp, log)


# --------------------------------------------------------------------------
if __name__ == "__main__":
    log = CanUdsLog("Service_27_CAN")
    tp = CanTpTransport(logger=log)
    try:
        tp.open()
        from Service_10_CAN import service_10_programming_session
        service_10_programming_session(tp, log)
        time.sleep(0.1)
        service_27_all_tests(tp, log)
    except Exception as e:
        log.error(str(e))
        import traceback
        traceback.print_exc()
    finally:
        tp.close()
        log.close()
        sys.exit(0 if log.all_passed else 1)
