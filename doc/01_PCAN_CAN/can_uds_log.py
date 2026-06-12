#!/usr/bin/env python3
"""
CAN UDS Logger
==============
Generates a structured log file for each CAN diagnostic test run.
Log file: Result/SVVR_<scriptname>_<timestamp>.log

Reuses the same log format as the LIN UDS logger.
"""

import os
import sys
import logging
import datetime

from can_tp_config import LOG_DIR


# ==========================================================================
class CanUdsLog:
    """
    Logger for CAN UDS service scripts.

    Usage:
        log = CanUdsLog("Service_10_CAN")
        log.start_test("Switch to programming session")
        log.tx("10 02")
        log.rx("50 02 00 32 01 90")
        log.result(True, expected="50 02 ...", received="50 02 00 32 01 90")
        log.close()
    """

    PASS = "PASS"
    FAIL = "FAIL"

    def __init__(self, script_name: str):
        ts  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fn  = f"SVVR_{script_name}_{ts}.log"
        self.log_path = os.path.join(LOG_DIR, fn)
        self._pass_count = 0
        self._fail_count = 0
        self._current_step = ""

        # Python logging setup
        self._logger = logging.getLogger(f"{script_name}_{ts}")
        self._logger.setLevel(logging.DEBUG)
        self._logger.handlers.clear()

        # File handler
        fh = logging.FileHandler(self.log_path, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d %(message)s",
                                          datefmt="%H:%M:%S"))
        self._logger.addHandler(fh)

        # Console handler
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d %(message)s",
                                          datefmt="%H:%M:%S"))
        self._logger.addHandler(ch)

        self._write_separator("=")
        self._logger.info(f"[START ] Script : {script_name}")
        self._logger.info(f"[START ] Log    : {self.log_path}")
        self._write_separator("=")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def start_test(self, description: str):
        """Mark beginning of a test step."""
        self._current_step = description
        self._write_separator("-")
        self._logger.info(f"[STEP  ] {description}")

    def info(self, msg: str):
        self._logger.info(f"[INFO  ] {msg}")

    def tx(self, hex_bytes: str, description: str = ""):
        label = f"TX {description}".strip()
        self._logger.info(f"[{label:<6}] {hex_bytes}")

    def rx(self, hex_bytes: str, description: str = ""):
        label = f"RX {description}".strip()
        self._logger.info(f"[{label:<6}] {hex_bytes}")

    def result(self, passed: bool, expected: str = "", received: str = "",
               description: str = ""):
        """Record pass/fail for current step."""
        status = self.PASS if passed else self.FAIL
        step   = description or self._current_step
        self._logger.info(
            f"[{status:<6}] {step}"
            + (f" | expected: {expected}" if expected else "")
            + (f" | received: {received}" if received else "")
        )
        if passed:
            self._pass_count += 1
        else:
            self._fail_count += 1

    def error(self, msg: str):
        self._logger.error(f"[ERROR ] {msg}")
        self._fail_count += 1

    def close(self):
        """Write summary and close log file."""
        total = self._pass_count + self._fail_count
        self._write_separator("=")
        self._logger.info(
            f"[SUMRY ] PASS={self._pass_count}  FAIL={self._fail_count}  "
            f"TOTAL={total}  "
            f"{'ALL PASS' if self._fail_count == 0 else 'FAILED'}"
        )
        self._write_separator("=")
        for h in self._logger.handlers[:]:
            h.close()
            self._logger.removeHandler(h)
        print(f"\n  Log saved to: {self.log_path}")

    @property
    def all_passed(self) -> bool:
        return self._fail_count == 0

    # ------------------------------------------------------------------
    def _write_separator(self, char: str = "-"):
        self._logger.info(char * 72)


# --------------------------------------------------------------------------
# Helpers used by all CAN service scripts
# --------------------------------------------------------------------------
def bytes_to_hex(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


def hex_to_bytes(hex_str: str) -> bytes:
    return bytes(int(x, 16) for x in hex_str.split())


def read_current_session(tp, log: CanUdsLog) -> bytes:
    """
    Send 22 F1 86 (ReadDataByIdentifier – ActiveDiagnosticSession).
    Returns the raw response bytes.
    """
    log.start_test("0x22 F1 86 – Read Active Diagnostic Session")
    req = bytes([0x22, 0xF1, 0x86])
    log.tx(bytes_to_hex(req), "ReadDataByIdentifier activeDiagnosticSession")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp) if resp else "(no response)")
    if len(resp) >= 4 and resp[0] == 0x62:
        session_map = {
            0x01: "DefaultSession",
            0x02: "ProgrammingSession",
            0x03: "ExtendedDiagnosticSession",
        }
        sid_val = resp[3]
        name = session_map.get(sid_val, f"Unknown(0x{sid_val:02X})")
        log.info(f"Current session: 0x{sid_val:02X} ({name})")
        log.result(True, description="Read active session OK")
    else:
        log.result(False, expected="62 F1 86 xx", received=bytes_to_hex(resp),
                   description="Read active session")
    return resp


def check_negative_response(response: bytes, sid: int, nrc: int, log: CanUdsLog,
                             step_desc: str = "") -> bool:
    """
    Verify UDS negative response: 7F <SID> <NRC>.
    Returns True if the expected NRC is received, False otherwise.
    """
    resp_hex = bytes_to_hex(response)
    expected = f"7F {sid:02X} {nrc:02X}"

    if len(response) == 0:
        log.result(False, expected=expected, received="(empty)", description=step_desc)
        return False

    if len(response) >= 3 and response[0] == 0x7F and response[1] == sid and response[2] == nrc:
        log.result(True, expected=expected, received=resp_hex, description=step_desc)
        return True
    else:
        log.result(False, expected=expected, received=resp_hex, description=step_desc)
        return False


def check_no_response(response: bytes, log: CanUdsLog, step_desc: str = "") -> bool:
    """
    Verify that no response was received (suppress positive response bit set).
    """
    if len(response) == 0:
        log.result(True, expected="(no response)", received="(empty)", description=step_desc)
        return True
    else:
        log.result(False, expected="(no response)", received=bytes_to_hex(response),
                   description=step_desc)
        return False


def check_positive_response(response: bytes, sid: int, log: CanUdsLog,
                             step_desc: str = "") -> bool:
    """
    Verify UDS positive response: first byte = SID + 0x40.
    Returns True if positive, False if negative (7F xx NRC).
    """
    expected_sid = sid + 0x40
    resp_hex     = bytes_to_hex(response)

    if len(response) == 0:
        log.result(False, expected=f"{expected_sid:02X} ...", received="(empty)",
                   description=step_desc)
        return False

    if response[0] == expected_sid:
        log.result(True, expected=f"{expected_sid:02X} ...", received=resp_hex,
                   description=step_desc)
        return True
    elif response[0] == 0x7F:
        nrc = response[2] if len(response) >= 3 else 0xFF
        nrc_names = {
            0x10: "generalReject",
            0x11: "serviceNotSupported",
            0x12: "subFunctionNotSupported",
            0x13: "incorrectMessageLengthOrInvalidFormat",
            0x22: "conditionsNotCorrect",
            0x24: "requestSequenceError",
            0x31: "requestOutOfRange",
            0x33: "securityAccessDenied",
            0x35: "invalidKey",
            0x36: "exceededNumberOfAttempts",
            0x37: "requiredTimeDelayNotExpired",
            0x70: "uploadDownloadNotAccepted",
            0x71: "transferDataSuspended",
            0x72: "generalProgrammingFailure",
            0x78: "requestCorrectlyReceivedResponsePending",
        }
        nrc_name = nrc_names.get(nrc, f"unknown(0x{nrc:02X})")
        log.result(False,
                   expected=f"{expected_sid:02X} ...",
                   received=f"NegResp 7F {response[1]:02X} {nrc:02X} ({nrc_name})",
                   description=step_desc)
        return False
    else:
        log.result(False, expected=f"{expected_sid:02X} ...", received=resp_hex,
                   description=step_desc)
        return False
