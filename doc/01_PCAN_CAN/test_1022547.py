#!/usr/bin/env python3
"""
TC_1022547 – LIN DiagServ PBL: Functional addressed request shall not disturb
             message transmission (R3)
================================================================================
Test Case ID : 1022547
Test Title   : LIN DiagServ PBL - Functional addressed request shall not disturb
               message transmission_R3
Source BLF   : 1022547_TP_FunctionalAddres.blf
Result (ECU) : FAIL  (ECU did not transmit 0x3d response in P2)

Test Purpose:
    Verify that the ECU is able to continue sending a message while receiving a
    functionally addressed request.  When a physical diagnostic request is in
    progress, an interleaved functional-addressed frame (NAD=0x7E) must NOT
    prevent the ECU from completing its response on 0x3D.

Test Sequence (reproduced from XML report):
    Setup  : KL15 on, enter PBL
               11 01 (hardReset)  →  wait 2 s  →  10 02 (ProgrammingSession)
    Step 1 : Send physical ReadDataByIdentifier on 0x3C
               3C  67  03  22  F1  2A  FF  FF   (NAD=0x67, LEN=3, SID=0x22, DID=0xF12A)
    Step 2 : Immediately send functional TesterPresent (suppress) on 0x3C
               3C  7E  02  3E  80  FF  FF  FF   (NAD=0x7E, LEN=2, SID=0x3E, suppress)
    Check  : Master polls 0x3D – ECU MUST respond within P2 (50 ms)

Pass Criterion:
    ECU transmits ANY data on 0x3D (positive response OR NRC) within P2.
    Even NRC 0x31 / NRC 0x11 counts as "responded" – only complete silence = FAIL.

Fail Criterion:
    No 0x3D frame received within P2 timeout after the functional request.
    This indicates the functional frame disturbed the ECU's TP processing.

ECU Defect observed (2026-04-29):
    "The Slave do not transmit 0x3d response in P2!"
    → ECU is silent after functional TesterPresent interrupts physical request handling.
"""

import sys
import time

from lin_tp_transport import LinTpTransport
from lin_uds_log      import (
    LinUdsLog, bytes_to_hex,
    read_current_session,
)
from lin_tp_config import NAD, NAD_FUNCTIONAL

# ---------------------------------------------------------------------------
# Test constants
# ---------------------------------------------------------------------------
_TC_ID    = "1022547"
_TC_TITLE = "PBL – Functional addressed request shall not disturb message transmission (R3)"

# Physical ReadDataByIdentifier: DID 0xF12A (as specified in TC 1022547)
_PHYS_REQ = bytes([0x22, 0xF1, 0x2A])

# Functional TesterPresent with suppressPosRsp bit set
_FUNC_REQ = bytes([0x3E, 0x80])


# ===========================================================================
def tc_1022547(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """
    Execute TC_1022547.

    Steps
    -----
    1. Enter PBL (hardReset + ProgrammingSession)
    2. Send physical 22 F1 2A on 0x3C (NAD=0x67)  — do NOT poll 0x3D yet
    3. Immediately send functional 3E 80 on 0x3C (NAD=0x7E, suppress)
    4. Poll 0x3D — ECU must provide any response to Step 2 despite Step 3

    Returns True if ECU responded (PASS), False if no response (FAIL).
    """
    from Service_10 import service_10_programming_session
    from Service_11 import service_11_hard_reset

    log.info("=" * 60)
    log.info(f"TC_{_TC_ID}: {_TC_TITLE}")
    log.info("=" * 60)

    # ------------------------------------------------------------------
    # Read initial session state
    # ------------------------------------------------------------------
    read_current_session(tp, log)

    # ------------------------------------------------------------------
    # Setup: Enter PBL
    # ------------------------------------------------------------------
    log.info("--- Setup: Enter PBL (hardReset + ProgrammingSession) ---")
    service_11_hard_reset(tp, log)               # 11 01 → 51 01, wait 2 s
    service_10_programming_session(tp, log)      # 10 02 → 50 02
    time.sleep(0.1)

    # ------------------------------------------------------------------
    # Step 1: Send physical ReadDataByIdentifier (22 F1 2A, NAD=0x67)
    #         Do NOT call _receive_response() here – we want the functional
    #         frame to arrive on 0x3C before the master polls 0x3D.
    # ------------------------------------------------------------------
    log.info(f"--- Step1: Physical 22 F1 2A on 0x3C  (NAD=0x{NAD:02X}) ---")

    log.start_test(
        f"TC_{_TC_ID} – Physical 22 F1 2A  then  functional 3E 80  →  ECU must respond on 0x3D"
    )
    log.tx(
        bytes_to_hex(_PHYS_REQ),
        f"ReadDataByIdentifier DID=0xF12A  (physical  NAD=0x{NAD:02X})"
    )
    # _send_request transmits the SF and sleeps INTER_FRAME_DELAY_S (20 ms)
    tp._send_request(_PHYS_REQ, nad=NAD)

    # ------------------------------------------------------------------
    # Step 2: Functional TesterPresent (3E 80, NAD=0x7E, suppress)
    #         Arrives ~20 ms after the physical request.
    #         Must NOT disturb the pending physical response.
    # ------------------------------------------------------------------
    log.info(f"--- Step2: Functional 3E 80 on 0x3C  (NAD=0x{NAD_FUNCTIONAL:02X}, suppress) ---")
    log.tx(
        bytes_to_hex(_FUNC_REQ),
        f"TesterPresent suppressPosRsp  (functional  NAD=0x{NAD_FUNCTIONAL:02X})"
    )
    # _send_request transmits the SF and sleeps INTER_FRAME_DELAY_S (20 ms)
    tp._send_request(_FUNC_REQ, nad=NAD_FUNCTIONAL)

    # ------------------------------------------------------------------
    # Check: Poll 0x3D – ECU must have the response ready
    #        Total elapsed since physical request: ~40 ms < P2_Server_Max (50 ms)
    # ------------------------------------------------------------------
    log.info("--- Check: Poll 0x3D for ECU response to physical request ---")
    try:
        resp = tp._receive_response()          # polls 0x3D with 0x7D headers
        log.rx(bytes_to_hex(resp))

        # Any non-empty response = ECU was not disturbed → PASS
        # (positive response 62 F1 2A ... OR any NRC such as 7F 22 31/11)
        log.result(
            True,
            expected=f"any response on 0x3D (positive or NRC)",
            received=bytes_to_hex(resp),
            description=f"TC_{_TC_ID}: ECU responded – not disturbed by functional addressing"
        )
        return True

    except TimeoutError:
        log.rx("(no response – timeout)")
        log.result(
            False,
            expected="any response on 0x3D within P2",
            received="timeout (no 0x3D frame received)",
            description=(
                f"TC_{_TC_ID}: ECU DID NOT respond – "
                "functional addressing (3E 80) disturbed physical request processing"
            )
        )
        return False


# ===========================================================================
if __name__ == "__main__":
    log = LinUdsLog("TC_1022547")
    tp  = LinTpTransport(logger=log)
    try:
        tp.open()
        tc_1022547(tp, log)
    except Exception as e:
        log.error(str(e))
        raise
    finally:
        tp.close()
        log.close()
        sys.exit(0 if log.all_passed else 1)
