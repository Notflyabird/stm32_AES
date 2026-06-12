#!/usr/bin/env python3
"""
CAN UDS Logger – TI-Style Log Format
======================================
Generates structured log files matching the TI pytester log format.

Reference: pytester_2026_03_12_00_11_31.log (TI_MSPM0_Reprog_Script)

Log format:
  <rel_time> - <spaces> :     - <LEVEL> : <message>

  CAN frames:
    Tx   <id>    <hex bytes 8x 2-digit>  <ascii repr>
    Rx   <id>    <hex bytes 8x 2-digit>  <ascii repr>

  ISO-TP message summary:
    ISO TP message (<type>): <full hex>
    size: 0x<size>(<decimal>)
    data: <uds payload hex>

  Test result:
    SVVR\t<script>\t<func>\tline <N>\t\n<desc>\tresult :True/False
"""

import os
import sys
import time
import datetime
from typing import List


# ==========================================================================
class CanUdsLog:
    """
    TI-style logger for CAN UDS service scripts.

    Usage:
        log = CanUdsLog("Reprogramming_CAN")
        log.info("Tester initialization...")
        log.can_frame("Tx", 0x123, bytes([0x02, 0x10, 0x03, 0x00, 0x00, 0x00, 0x00, 0x00]))
        log.isotp_message("single frame", "06500300320190aa", 6, "500300320190")
        log.svvr_result("FunctionName", 123, "Test desc", True)
        log.close()
    """

    # Class-level start time for relative timestamps
    _start_time = time.monotonic()

    def __init__(self, script_name: str):
        ts  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fn  = f"SVVR_{script_name}_{ts}.log"
        self.log_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "Result", fn)
        self._script_name = script_name
        self._pass_count = 0
        self._fail_count = 0
        self._current_step = ""
        self._file = None
        self._tx_id = None   # set by transport layer

        # Create directory if needed
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)

        # Open log file
        self._file = open(self.log_path, "w", encoding="utf-8")

        # Console output handle
        self._console = sys.stdout

        # Header
        self._writeln("INFO", "Tester initialization...")
        self._write_separator("=")
        self._writeln("INFO", f"Log started {datetime.datetime.now().strftime('%a %d. %b %Y %H:%M:%S')}")
        self._write_separator("=")
        self._writeln("INFO", f"Script : {script_name}")
        self._writeln("INFO", f"Log    : {self.log_path}")

    # ------------------------------------------------------------------
    # Public API – General logging
    # ------------------------------------------------------------------

    def info(self, msg: str):
        """Log an informational message."""
        self._writeln("INFO", msg)

    def warning(self, msg: str):
        """Log a warning message."""
        self._writeln("WARNING", msg)

    def error(self, msg: str):
        """Log an error message."""
        self._writeln("ERROR", msg)
        self._fail_count += 1

    # ------------------------------------------------------------------
    # Public API – CAN frame logging (TI format)
    # ------------------------------------------------------------------

    def can_frame(self, direction: str, can_id: int, data: bytes):
        """
        Log a raw CAN frame in TI format.

        Args:
            direction: "Tx" or "Rx"
            can_id:    CAN identifier (e.g. 0x123)
            data:      8-byte CAN data payload
        """
        # Hex bytes padded to 23 chars (8 × 2-digit-hex + 7 spaces)
        hex_str = " ".join(f"{b:02X}" for b in data)
        hex_str = hex_str.ljust(23)

        # ASCII representation (printable chars or '.')
        ascii_str = "".join(chr(b) if 32 <= b < 127 else "." for b in data)

        msg = f"{direction:3s}   {can_id:03X}    {hex_str}  {ascii_str}"
        self._writeln("INFO", msg)

    # ------------------------------------------------------------------
    # Public API – ISO-TP message summary
    # ------------------------------------------------------------------

    def isotp_message(self, msg_type: str, full_hex: str, size: int, data: str):
        """
        Log an ISO-TP message summary.

        Args:
            msg_type: Frame type description (e.g. "single frame", "first frame")
            full_hex: Complete hex dump including PCI bytes
            size:     UDS payload size in bytes
            data:     UDS payload hex string
        """
        self._writeln("INFO", f"ISO TP message ({msg_type}): {full_hex}")
        self._writeln("INFO", f"size: 0x{size:x}({size})")
        self._writeln("INFO", f"data: {data}")

    # ------------------------------------------------------------------
    # Public API – Test step management
    # ------------------------------------------------------------------

    def start_test(self, description: str):
        """Mark beginning of a test step."""
        self._current_step = description

    def result(self, passed: bool, expected: str = "", received: str = "",
               description: str = ""):
        """
        Record pass/fail for current step.
        Logs in TI style with descriptive message.

        The 'expected' and 'received' fields are appended inline when provided.
        For SVVR-style logging, use svvr_result() instead.
        """
        status = "PASS" if passed else "FAIL"
        step   = description or self._current_step
        msg = f"{step}"
        if expected:
            msg += f" | expected: {expected}"
        if received:
            msg += f" | received: {received}"
        self._writeln(status, msg)
        if passed:
            self._pass_count += 1
        else:
            self._fail_count += 1

    def svvr_result(self, func_name: str, line_no: int, description: str,
                    result: bool):
        """
        Log a test result in TI SVVR format.

        Format:
          SVVR\t<script>\t<func>\tline <N>\t
          <desc>\tresult :True/False
        """
        status_str = "True" if result else "False"
        self._writeln("INFO",
            f"SVVR\t{self._script_name}\t{func_name}\tline {line_no}\t")
        self._writeln("INFO",
            f"{description}\tresult :{status_str}")
        if result:
            self._pass_count += 1
        else:
            self._fail_count += 1

    # ------------------------------------------------------------------
    # Public API – Lifecycle
    # ------------------------------------------------------------------

    def close(self):
        """Write summary and close log file."""
        total = self._pass_count + self._fail_count
        self._write_separator("=")
        self._writeln("INFO",
            f"PASS={self._pass_count}  FAIL={self._fail_count}  "
            f"TOTAL={total}  "
            f"{'ALL PASS' if self._fail_count == 0 else 'FAILED'}")
        self._write_separator("=")
        self._writeln("INFO", f"PCANTester Destruction")

        if self._file:
            self._file.close()
            self._file = None

        print(f"\n  Log saved to: {self.log_path}")

    @property
    def all_passed(self) -> bool:
        return self._fail_count == 0

    # ------------------------------------------------------------------
    # Internal – timestamp & formatting
    # ------------------------------------------------------------------

    @classmethod
    def _get_timestamp(cls) -> str:
        """Relative timestamp in H:MM:SS.mmm format."""
        elapsed = time.monotonic() - cls._start_time
        hours = int(elapsed // 3600)
        minutes = int((elapsed % 3600) // 60)
        seconds = int(elapsed % 60)
        ms = int((elapsed * 1000) % 1000)
        return f"{hours}:{minutes:02d}:{seconds:02d}.{ms:03d}"

    def _writeln(self, level: str, message: str):
        """Write a line to both log file and console in TI format."""
        ts = self._get_timestamp()
        # TI format: <ts> - <21 spaces> :     - <LEVEL:5s> : <msg>
        line = f"{ts} -                     :     - {level:5s} : {message}"
        if self._file:
            self._file.write(line + "\n")
            self._file.flush()
        # Console output
        print(line)

    def _write_separator(self, char: str = "-"):
        """Write a separator line."""
        self._writeln("INFO", char * 72)


# ==========================================================================
# Helpers used by all CAN service scripts
# ==========================================================================

def bytes_to_hex(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


def hex_to_bytes(hex_str: str) -> bytes:
    return bytes(int(x, 16) for x in hex_str.split())


def can_frame_bytes(can_id: int, data: bytes) -> bytes:
    """
    Build a CAN frame representation (not an actual CAN frame).
    Used for display/logging purposes.
    """
    # Pad data to 8 bytes with 0xAA (padding byte)
    padded = data[:8].ljust(8, b'\xAA')
    return padded


def format_can_ascii(data: bytes) -> str:
    """Format data bytes as ASCII representation (printable chars or '.')."""
    return "".join(chr(b) if 32 <= b < 127 else "." for b in data)


# ==========================================================================
# ISO-TP frame analysis
# ==========================================================================

def isotp_frame_info(data: bytes):
    """
    Analyze an ISO-TP frame and return (type_str, payload_offset).

    Returns:
        (frame_type_string, payload_offset)
        frame_type: "single frame", "first frame", "consecutive frame",
                    "flow control"
        payload_offset: index where UDS payload starts
    """
    if not data:
        return "unknown", 0

    pci = data[0]
    if (pci & 0xF0) == 0x00:
        # Single frame: PCI = 00-0F, length in low nibble, or 00-07 for SF with 12-bit len
        if (pci & 0x0F) == 0x00 and len(data) >= 2:
            # 12-bit extended length
            sf_len = ((pci & 0x0F) << 8) | data[1]
            return "single frame", 2
        else:
            return "single frame", 1
    elif (pci & 0xF0) == 0x10:
        # First frame: PCI = 10-1F
        return "first frame", 2
    elif (pci & 0xF0) == 0x20:
        # Consecutive frame: PCI = 20-2F
        return "consecutive frame", 1
    elif (pci & 0xF0) == 0x30:
        # Flow control frame: PCI = 30-3F
        return "flow control", 0
    else:
        return f"unknown(0x{pci:02X})", 1


# ==========================================================================
# Session reading helper
# ==========================================================================

def read_current_session(tp, log: CanUdsLog) -> bytes:
    """
    Send 22 F1 86 (ReadDataByIdentifier – ActiveDiagnosticSession).
    Returns the raw response bytes.
    """
    log.start_test("0x22 F1 86 – Read Active Diagnostic Session")
    req = bytes([0x22, 0xF1, 0x86])
    # UDS-level log (data field in ISO-TP)
    resp = tp.send_uds(req)
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


# ==========================================================================
# Response check helpers (maintaining backward compatibility)
# ==========================================================================

def check_negative_response(response: bytes, sid: int, nrc: int, log: CanUdsLog,
                             step_desc: str = "") -> bool:
    """Verify UDS negative response: 7F <SID> <NRC>."""
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
    """Verify that no response was received (suppress bit)."""
    if len(response) == 0:
        log.result(True, expected="(no response)", received="(empty)", description=step_desc)
        return True
    else:
        log.result(False, expected="(no response)", received=bytes_to_hex(response),
                   description=step_desc)
        return False


_NRC_NAMES = {
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


def check_positive_response(response: bytes, sid: int, log: CanUdsLog,
                             step_desc: str = "") -> bool:
    """Verify UDS positive response: first byte = SID + 0x40."""
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
        nrc_name = _NRC_NAMES.get(nrc, f"unknown(0x{nrc:02X})")
        log.result(False,
                   expected=f"{expected_sid:02X} ...",
                   received=f"NegResp 7F {response[1]:02X} {nrc:02X} ({nrc_name})",
                   description=step_desc)
        return False
    else:
        log.result(False, expected=f"{expected_sid:02X} ...", received=resp_hex,
                   description=step_desc)
        return False
