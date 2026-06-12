#!/usr/bin/env python3
"""
Service 0x31 RoutineControl – PWM Test (RID 0xA045)
====================================================

Sets PWM frequency and duty cycle on one or more GPIO pins via CAN ISO-TP.

Request format:
    31 01 A0 45 <test_cmd> <count> [<port> <pin> <freq_H> <freq_L> <duty>] × N

    Byte 0 : SID  = 0x31
    Byte 1 : SF   = 0x01  (StartRoutine)
    Byte 2 : RID  = 0xA0  (high byte)
    Byte 3 : RID  = 0x45  (low byte)
    Byte 4 : Test Command  (default 0x01)
    Byte 5 : Channel count (N)
    Byte 6+5*i : Port  number for channel i
    Byte 7+5*i : Pin   number for channel i
    Byte 8+5*i : Frequency high byte (Hz, 0–20000)
    Byte 9+5*i : Frequency low  byte
    Byte10+5*i : Duty cycle (%, 0–100)

Positive response:
    71 01 A0 45 <RINF> <RSTS> [<ch0_status> … <chN_status>]

    RINF = 0x02  RoutineNotActiveOrFinishedCorrectly
    RSTS = 0x00  Routine execution successful
           0x01  Routine execution failure
    ch_status:
           0x00  Config Success
           0x01  Config Fail
           0x02  Invalid Param

Negative response:
    7F 31 <NRC>

    NRC 0x13  IMLOIF (IncorrectMessageLengthOrInvalidFormat)
    NRC 0x31  RequestOutOfRange
    NRC 0x78  RequestCorrectlyReceivedResponsePending
    NRC 0xF1  Parameter ERROR / not supported

Examples:
    # Single channel: P0.7 → 1000 Hz, 50% duty
    python Service_31_PWM_CAN.py --pwm-channel 0:7:1000:50

    # Two channels simultaneously
    python Service_31_PWM_CAN.py --pwm-channel 0:7:1000:50 --pwm-channel 0:8:2000:25

    # P40.0 → 500 Hz, 75%
    python Service_31_PWM_CAN.py --pwm-channel 0x28:0:500:75

    # Dry-run (build request, no CAN traffic)
    python Service_31_PWM_CAN.py --pwm-channel 0:7:1000:50 --dry-run
"""

from __future__ import annotations

import argparse
import sys
import textwrap
from dataclasses import dataclass
from typing import Sequence

# ---------------------------------------------------------------------------
# Import shared transport / logging from the ADC script
# ---------------------------------------------------------------------------
try:
    from Service_31_ADC_CAN import (
        CanUdsLog,
        CanIsoTpUdsClient,
        ensure_can_transport_dependencies,
        log_transport_failure_context,
        log_can_exchange_context,
        DEFAULT_TX_ID,
        DEFAULT_RX_ID,
    )
except ImportError as _e:
    raise SystemExit(
        f"Cannot import shared transport from Service_31_ADC_CAN.py: {_e}\n"
        "Ensure Service_31_ADC_CAN.py is in the same directory."
    ) from _e

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SID_ROUTINE_CONTROL: int = 0x31
POSITIVE_SID: int = 0x71
NR_SID: int = 0x7F
SUBFUNCTION_START_ROUTINE: int = 0x01

ROUTINE_PWM_TEST_H: int = 0xA0
ROUTINE_PWM_TEST_L: int = 0x45
ROUTINE_PWM_TEST: int = (ROUTINE_PWM_TEST_H << 8) | ROUTINE_PWM_TEST_L  # 0xA045

DEFAULT_TEST_COMMAND: int = 0x01

# Per-channel status codes in positive response
PWM_STATUS_OK: int = 0x00       # Config Success
PWM_STATUS_FAIL: int = 0x01     # Config Fail
PWM_STATUS_INVALID: int = 0x02  # Invalid Param

_CH_STATUS_DESC: dict[int, str] = {
    PWM_STATUS_OK: "Config Success",
    PWM_STATUS_FAIL: "Config Fail",
    PWM_STATUS_INVALID: "Invalid Param",
}

_NRC_DESC: dict[int, str] = {
    0x13: "IMLOIF – IncorrectMessageLengthOrInvalidFormat",
    0x22: "ConditionsNotCorrect",
    0x31: "RequestOutOfRange",
    0x78: "RequestCorrectlyReceivedResponsePending",
    0xF1: "Parameter ERROR / not supported",
}

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PwmChannel:
    """Single PWM output channel configuration."""
    port_id: int    # Port byte (e.g. 0x00 for P0, 0x28 for P40)
    pin_id: int     # Pin number within port
    frequency: int  # Hz, 0–20000
    duty: int       # %, 0–100

    def label(self) -> str:
        return f"P{self.port_id}.{self.pin_id}"

    def validate(self) -> None:
        if not (0 <= self.port_id <= 0xFF):
            raise ValueError(f"{self.label()} port_id 0x{self.port_id:02X} out of range 0x00–0xFF")
        if not (0 <= self.pin_id <= 0xFF):
            raise ValueError(f"{self.label()} pin_id {self.pin_id} out of range 0–255")
        if not (0 <= self.frequency <= 20000):
            raise ValueError(
                f"{self.label()} frequency {self.frequency} Hz out of range 0–20000"
            )
        if not (0 <= self.duty <= 100):
            raise ValueError(f"{self.label()} duty {self.duty}% out of range 0–100")


@dataclass(frozen=True)
class PwmRoutineResponse:
    """Parsed response to a PWM StartRoutine request."""
    is_positive: bool
    rinf: int | None                   # Routine Info  (positive only)
    rsts: int | None                   # Routine Status (positive only)
    channel_statuses: tuple[int, ...]  # Per-channel status bytes (positive only)
    nrc: int | None                    # Negative Response Code (negative only)
    raw: bytes                         # Raw response bytes


@dataclass
class PwmChannelResult:
    """Outcome for a single PWM channel after the routine call."""
    channel: PwmChannel
    status_code: int | None   # 0=OK, 1=Fail, 2=Invalid, None=no data
    passed: bool

    @property
    def status_desc(self) -> str:
        if self.status_code is None:
            return "No data"
        return _CH_STATUS_DESC.get(self.status_code, f"0x{self.status_code:02X}")


# ---------------------------------------------------------------------------
# Protocol helpers
# ---------------------------------------------------------------------------

def build_pwm_start_request(
    channels: Sequence[PwmChannel],
    test_command: int = DEFAULT_TEST_COMMAND,
) -> bytes:
    """Build the 0x31 StartRoutine request frame for PWM (RID 0xA045).

    Layout:
        31 01 A0 45 <test_cmd> <count>
        [<port> <pin> <freq_H> <freq_L> <duty>] × count
    """
    if not channels:
        raise ValueError("At least one PWM channel is required")
    if len(channels) > 0xFF:
        raise ValueError("Channel count must not exceed 255")

    buf = bytearray([
        SID_ROUTINE_CONTROL,          # 0x31
        SUBFUNCTION_START_ROUTINE,    # 0x01
        ROUTINE_PWM_TEST_H,           # 0xA0
        ROUTINE_PWM_TEST_L,           # 0x45
        test_command & 0xFF,
        len(channels),
    ])
    for ch in channels:
        freq_h = (ch.frequency >> 8) & 0xFF
        freq_l = ch.frequency & 0xFF
        buf += bytes([ch.port_id, ch.pin_id, freq_h, freq_l, ch.duty])
    return bytes(buf)


def parse_pwm_routine_response(data: bytes) -> PwmRoutineResponse:
    """Parse a raw ISO-TP payload into a PwmRoutineResponse."""
    if not data:
        return PwmRoutineResponse(
            is_positive=False, rinf=None, rsts=None,
            channel_statuses=(), nrc=None, raw=b""
        )

    # Negative response: 7F 31 <NRC>
    if data[0] == NR_SID:
        nrc = data[2] if len(data) >= 3 else None
        return PwmRoutineResponse(
            is_positive=False, rinf=None, rsts=None,
            channel_statuses=(), nrc=nrc, raw=data
        )

    # Positive response: 71 01 A0 45 <RINF> <RSTS> [ch_status ...]
    if data[0] == POSITIVE_SID and len(data) >= 6:
        return PwmRoutineResponse(
            is_positive=True,
            rinf=data[4],
            rsts=data[5],
            channel_statuses=tuple(data[6:]),
            nrc=None,
            raw=data,
        )

    return PwmRoutineResponse(
        is_positive=False, rinf=None, rsts=None,
        channel_statuses=(), nrc=None, raw=data
    )


def _log_pwm_response(
    response: PwmRoutineResponse,
    channels: Sequence[PwmChannel],
    log: CanUdsLog,
) -> bool:
    """Log response details; return True if all channels report Config Success."""
    rx_hex = " ".join(f"{b:02X}" for b in response.raw)
    log.info(f"[RX CAN 0x77A PWM Response] {rx_hex}")

    if not response.is_positive:
        if response.nrc is not None:
            nrc_desc = _NRC_DESC.get(response.nrc, "Unknown NRC")
            log.error(f"Negative response NRC=0x{response.nrc:02X}: {nrc_desc}")
        else:
            log.error(f"Unexpected response bytes: {rx_hex}")
        return False

    rsts_ok = (response.rsts == 0x00)
    log.info(
        f"  RINF=0x{response.rinf:02X}  RSTS=0x{response.rsts:02X} "
        f"({'Execution OK' if rsts_ok else 'Execution FAIL'})"
    )

    all_passed = rsts_ok
    for i, ch in enumerate(channels):
        if i < len(response.channel_statuses):
            code = response.channel_statuses[i]
            desc = _CH_STATUS_DESC.get(code, f"0x{code:02X}")
            passed = (code == PWM_STATUS_OK)
            verdict = "PASS" if passed else "FAIL"
            log.info(
                f"  {ch.label():<12s}  {ch.frequency:>6d} Hz  {ch.duty:>3d}%"
                f"  ->  {verdict}  ({desc})"
            )
            if not passed:
                all_passed = False
        else:
            log.error(f"  {ch.label():<12s}  -> No status byte in response")
            all_passed = False

    return all_passed


# ---------------------------------------------------------------------------
# High-level API
# ---------------------------------------------------------------------------

def run_pwm_routine(
    channels: Sequence[PwmChannel],
    test_command: int = DEFAULT_TEST_COMMAND,
    can_channel: str = "PCAN_USBBUS1",
    bitrate: int = 500_000,
    fd: bool = True,
    data_bitrate: int = 5_000_000,
    tx_id: int = DEFAULT_TX_ID,
    rx_id: int = DEFAULT_RX_ID,
    timeout_s: float = 2.0,
    dry_run: bool = False,
    log: CanUdsLog | None = None,
    tx_data_length: int = 16,
) -> list[PwmChannelResult]:
    """Send a PWM StartRoutine request and return per-channel results.

    Parameters
    ----------
    channels:
        List of PwmChannel describing port, pin, frequency (Hz), duty (%).
    test_command:
        Byte4 of the request (default 0x01).
    can_channel, bitrate, fd, data_bitrate:
        CAN bus configuration.
    tx_data_length:
        CAN FD DLC for TX frames.  Default 16 (DLC=16 → max SF payload 14
        bytes).  A 1-channel PWM request is 11 bytes which does NOT fit in
        DLC=12 (max SF payload 10 bytes) and would be sent as a multi-frame
        FF+CF that the ECU ignores.  Use 16 so the 11-byte request goes out
        as a single frame and the ECU responds correctly.
    tx_id / rx_id:
        UDS CAN IDs.
    timeout_s:
        ISO-TP response timeout.
    dry_run:
        If True, print the request bytes and return without opening CAN.
    log:
        Caller-supplied CanUdsLog; a new one is created if None.

    Returns
    -------
    list[PwmChannelResult] – one entry per input channel.
    """
    own_log = (log is None)
    if own_log:
        log = CanUdsLog("Service_31_PWM")

    # Validate input
    for ch in channels:
        ch.validate()

    request = build_pwm_start_request(channels, test_command)

    log.info(
        f"PWM request: {len(channels)} channel(s), "
        f"test_cmd=0x{test_command:02X}"
    )
    for ch in channels:
        log.info(
            f"  {ch.label():<12s}  freq={ch.frequency} Hz  duty={ch.duty}%"
        )

    # Show request bytes
    tx_hex = " ".join(f"{b:02X}" for b in request)
    log.info(f"[TX CAN 0x{tx_id:X} RoutineControl PWM] {tx_hex}")

    if dry_run:
        log.info("[DRY-RUN] CAN not opened, request not transmitted")
        if own_log:
            log.close()
        return [PwmChannelResult(ch, None, False) for ch in channels]

    results: list[PwmChannelResult] = []
    client = None
    try:
        ensure_can_transport_dependencies()
        client = CanIsoTpUdsClient(
            channel=can_channel,
            bitrate=bitrate,
            tx_id=tx_id,
            rx_id=rx_id,
            log=log,
            fd=fd,
            data_bitrate=data_bitrate,
            tx_data_length=tx_data_length,
        )
        client.open()

        log.start_test(f"0x31 0x01 0xA045 PWM StartRoutine (test_cmd=0x{test_command:02X})")
        log_can_exchange_context(log, tx_id, rx_id, timeout_s)

        response_bytes = client.send_uds(request, timeout_s)
        response = parse_pwm_routine_response(response_bytes)
        all_ok = _log_pwm_response(response, channels, log)

        # Build per-channel results
        for i, ch in enumerate(channels):
            if response.is_positive and i < len(response.channel_statuses):
                code = response.channel_statuses[i]
                passed = (code == PWM_STATUS_OK)
            else:
                code = None
                passed = False
            results.append(PwmChannelResult(ch, code, passed))

        log.result(all_ok, description="PWM routine overall")

    except Exception as exc:
        log_transport_failure_context(log, exc, tx_id, rx_id)
        err_msg = str(exc)
        log.error(err_msg)
        if "CONSECUTIVE_FRAME" in err_msg:
            log.info(
                ">>> HINT: 'CONSECUTIVE_FRAME timed out' – check CAN bus termination.\n"
                "    PCAN-View > right-click PCAN_USBBUS1 > Bus Termination > Enable"
            )
        results = [PwmChannelResult(ch, None, False) for ch in channels]
    finally:
        if client is not None:
            client.close()
        if own_log:
            log.close()

    return results


# ---------------------------------------------------------------------------
# All hardware PWM channels (from schematic pin map)
# ---------------------------------------------------------------------------
#
# Format: (port_byte, pin_number)
# port_byte = port decimal number  (P1=0x01, P11=0x0B, P13=0x0D, …)
#
ALL_PWM_CHANNELS: tuple[tuple[int, int], ...] = (
    # HSD
    (0x01, 13),  # P1.13   HSD      TOM4_7_B
    # MC-SEAT
    (0x02,  2),  # P2.2    MC-SEAT  TOM0_10_A
    (0x02,  3),  # P2.3    MC-SEAT  TOM0_11_A
    (0x02,  7),  # P2.7    MC-SEAT  TOM0_15_A
    (0x02,  8),  # P2.8    MC-SEAT  TOM0_8_A
    # MC-EPB
    (0x0B, 14),  # P11.14  MC-EPB   TOM2_7_A
    (0x0B, 15),  # P11.15  MC-EPB   TOM2_8_A
    # HSD P13
    (0x0D,  4),  # P13.4   HSD      TOM4_3_B
    (0x0D,  6),  # P13.6   HSD      TOM4_5_B
    (0x0D, 10),  # P13.10  HSD      TOM4_1_B
    (0x0D, 11),  # P13.11  HSD      TOM4_0_B
    (0x0D, 13),  # P13.13  HSD      TOM4_12_B
    (0x0D, 14),  # P13.14  HSD      TOM4_2_B
    (0x0D, 15),  # P13.15  HSD      TOM4_14_B
    # HSD P14 / HSD_LIGHT
    (0x0E, 12),  # P14.12  HSD      TOM4_11_B
    (0x0E, 13),  # P14.13  HSD      TOM4_10_B
    (0x0E, 14),  # P14.14  HSD      TOM4_9_B
    (0x0E, 15),  # P14.15  HSD_LIGHT TOM4_13_B
    # MC-MIRROR
    (0x14,  0),  # P20.0   MC-MIRROR TOM0_6_A
    # MC-Doorlock
    (0x16,  8),  # P22.8   MC-Doorlock TOM2_11_A
    (0x16,  9),  # P22.9   MC-Doorlock TOM2_12_A
    # MC-Windows
    (0x16, 10),  # P22.10  MC-Windows  TOM2_13_A
    (0x16, 11),  # P22.11  MC-Windows  TOM2_14_A
    # TMS P25
    (0x19,  0),  # P25.0   TMS      TOM3_0_A
    (0x19,  1),  # P25.1   TMS      TOM3_1_A
    (0x19,  2),  # P25.2   TMS      TOM3_2_A
    (0x19,  9),  # P25.9   TMS      TOM3_9_A
    # HSD P31
    (0x1F,  6),  # P31.6   HSD      TOM3_6_A
)


def run_all_pwm_channels(
    channels: Sequence[tuple[int, int]] = ALL_PWM_CHANNELS,
    frequency: int = 1000,
    duty: int = 50,
    test_command: int = DEFAULT_TEST_COMMAND,
    can_channel: str = "PCAN_USBBUS1",
    bitrate: int = 500_000,
    fd: bool = True,
    data_bitrate: int = 5_000_000,
    tx_id: int = DEFAULT_TX_ID,
    rx_id: int = DEFAULT_RX_ID,
    timeout_s: float = 2.0,
    dry_run: bool = False,
    log: CanUdsLog | None = None,
    tx_data_length: int = 16,
) -> list[PwmChannelResult]:
    """Send PWM StartRoutine for every channel in *channels* one-by-one.

    Each channel is sent as a separate single-frame request to stay within
    the ECU's ISO-TP single-frame constraint (max DLC-12 payload).
    All channels share the same *frequency* and *duty* unless a caller
    passes pre-built PwmChannel objects via a different path.

    Returns a flat list of PwmChannelResult (one per channel).
    """
    own_log = (log is None)
    if own_log:
        log = CanUdsLog("Service_31_PWM_ALL")

    pwm_channels = [PwmChannel(p, n, frequency, duty) for p, n in channels]
    total = len(pwm_channels)
    results: list[PwmChannelResult] = []
    client = None

    try:
        ensure_can_transport_dependencies()
        client = CanIsoTpUdsClient(
            channel=can_channel,
            bitrate=bitrate,
            tx_id=tx_id,
            rx_id=rx_id,
            log=log,
            fd=fd,
            data_bitrate=data_bitrate,
            tx_data_length=tx_data_length,
        )
        if not dry_run:
            client.open()

        for idx, ch in enumerate(pwm_channels, 1):
            log.info(f"--- Channel {idx}/{total}: {ch.label()} {ch.frequency}Hz {ch.duty}% ---")
            request = build_pwm_start_request([ch], test_command)
            tx_hex = " ".join(f"{b:02X}" for b in request)
            log.info(f"[TX CAN 0x{tx_id:X} RoutineControl PWM] {tx_hex}")

            if dry_run:
                results.append(PwmChannelResult(ch, None, False))
                continue

            try:
                response_bytes = client.send_uds(request, timeout_s)
                response = parse_pwm_routine_response(response_bytes)
                all_ok = _log_pwm_response(response, [ch], log)
                code = response.channel_statuses[0] if response.channel_statuses else None
                passed = (code == PWM_STATUS_OK) if code is not None else False
                results.append(PwmChannelResult(ch, code, passed))
            except Exception as exc:
                err_msg = str(exc)
                log.error(f"{ch.label()} failed: {err_msg}")
                if idx == 1 and "CONSECUTIVE_FRAME" in err_msg:
                    log.info(
                        ">>> HINT: 'CONSECUTIVE_FRAME timed out' – check CAN bus termination.\n"
                        "    PCAN-View > right-click PCAN_USBBUS1 > Bus Termination > Enable"
                    )
                results.append(PwmChannelResult(ch, None, False))

        # Summary table
        log.info("=" * 56)
        log.info("PWM channel summary:")
        log.info(f"{'Channel':<12}  {'Freq(Hz)':>8}  {'Duty%':>5}  {'Result':<6}  Status")
        for r in results:
            verdict = "PASS" if r.passed else "FAIL"
            log.info(
                f"{r.channel.label():<12}  {r.channel.frequency:>8}  {r.channel.duty:>5}"
                f"  {verdict:<6}  {r.status_desc}"
            )
        pass_count = sum(1 for r in results if r.passed)
        fail_count = total - pass_count
        log.info(f"Total: {pass_count}/{total} PASS")
        if dry_run:
            log.info("[DRY-RUN] No CAN frames transmitted")

    except Exception as exc:
        log_transport_failure_context(log, exc, tx_id, rx_id)
        log.error(str(exc))
    finally:
        if client is not None and not dry_run:
            client.close()
        if own_log:
            log.close()

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_pwm_channel_spec(spec: str) -> PwmChannel:
    """Parse 'PORT:PIN:FREQ:DUTY' → PwmChannel."""
    parts = spec.split(":")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(
            f"Invalid spec '{spec}'. Expected PORT:PIN:FREQ:DUTY  "
            f"(e.g. '0:7:1000:50' or '0x28:0:500:75')"
        )
    try:
        port = int(parts[0], 0)
        pin = int(parts[1], 0)
        freq = int(parts[2], 0)
        duty = int(parts[3], 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return PwmChannel(port, pin, freq, duty)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="UDS Service 0x31 RoutineControl – PWM Test (RID 0xA045)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Channel spec format:  PORT:PIN:FREQ:DUTY
              PORT  – port byte  (decimal or 0x hex)  e.g. 0 for P0, 0x28 for P40
              PIN   – pin number (decimal or 0x hex)
              FREQ  – frequency in Hz, 0–20000
              DUTY  – duty cycle in %, 0–100

            Examples:
              # P0.7 → 1000 Hz 50%
              python Service_31_PWM_CAN.py --pwm-channel 0:7:1000:50

              # P0.7 1000 Hz 50%  AND  P0.8 2000 Hz 25% in one request
              python Service_31_PWM_CAN.py --pwm-channel 0:7:1000:50 --pwm-channel 0:8:2000:25

              # P40.0 (port=0x28) → 500 Hz 75%
              python Service_31_PWM_CAN.py --pwm-channel 0x28:0:500:75

              # Show request bytes without sending
              python Service_31_PWM_CAN.py --pwm-channel 0:7:1000:50 --dry-run
        """),
    )

    parser.add_argument(
        "--pwm-channel",
        metavar="PORT:PIN:FREQ:DUTY",
        action="append",
        dest="pwm_channels",
        type=_parse_pwm_channel_spec,
        help="PWM channel spec (repeatable for multiple channels)",
    )
    parser.add_argument(
        "--test-command",
        default=DEFAULT_TEST_COMMAND,
        type=lambda x: int(x, 0),
        metavar="HEX",
        help=f"Test command byte (default: 0x{DEFAULT_TEST_COMMAND:02X})",
    )
    parser.add_argument(
        "--channel",
        default="PCAN_USBBUS1",
        help="PCAN channel name (default: PCAN_USBBUS1)",
    )
    parser.add_argument(
        "--bitrate",
        default=500_000,
        type=int,
        help="CAN nominal bitrate in bps (default: 500000)",
    )
    parser.add_argument(
        "--no-fd",
        dest="fd",
        action="store_false",
        default=True,
        help="Use classic CAN instead of CAN FD",
    )
    parser.add_argument(
        "--data-bitrate",
        default=5_000_000,
        type=int,
        help="CAN FD data bitrate in bps (default: 5000000)",
    )
    parser.add_argument(
        "--tx-id",
        default=DEFAULT_TX_ID,
        type=lambda x: int(x, 0),
        metavar="HEX",
        help=f"UDS request CAN ID (default: 0x{DEFAULT_TX_ID:X})",
    )
    parser.add_argument(
        "--rx-id",
        default=DEFAULT_RX_ID,
        type=lambda x: int(x, 0),
        metavar="HEX",
        help=f"UDS response CAN ID (default: 0x{DEFAULT_RX_ID:X})",
    )
    parser.add_argument(
        "--timeout",
        default=2.0,
        type=float,
        metavar="SEC",
        help="Response timeout in seconds (default: 2.0)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build and print request bytes without opening CAN bus",
    )
    parser.add_argument(
        "--tx-data-length",
        dest="tx_data_length",
        default=16,
        type=int,
        metavar="DLC",
        help=(
            "CAN FD TX frame DLC byte-count (default: 16).  "
            "Valid FD values: 12, 16, 20, 24, 32, 48, 64.  "
            "A 1-channel PWM request is 11 bytes; DLC=12 only allows 10-byte "
            "single-frames so the request is fragmented into FF+CF which the "
            "ECU ignores.  DLC=16 fits 14 bytes in a single frame.  "
            "Use 12 only if the ECU rejects DLC=16."
        ),
    )
    # --- run-all mode ---
    parser.add_argument(
        "--run-all",
        action="store_true",
        help="Send PWM to all 28 predefined hardware channels (ALL_PWM_CHANNELS) one-by-one",
    )
    parser.add_argument(
        "--freq",
        default=1000,
        type=int,
        metavar="HZ",
        help="Frequency for --run-all mode in Hz, 0–20000 (default: 1000)",
    )
    parser.add_argument(
        "--duty",
        default=50,
        type=int,
        metavar="PCT",
        help="Duty cycle for --run-all mode in %%, 0–100 (default: 50)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])

    # --- --run-all mode: send all 28 predefined hardware channels ---
    if args.run_all:
        results = run_all_pwm_channels(
            channels=ALL_PWM_CHANNELS,
            frequency=args.freq,
            duty=args.duty,
            test_command=args.test_command,
            can_channel=args.channel,
            bitrate=args.bitrate,
            fd=args.fd,
            data_bitrate=args.data_bitrate,
            tx_id=args.tx_id,
            rx_id=args.rx_id,
            timeout_s=args.timeout,
            dry_run=args.dry_run,
            tx_data_length=args.tx_data_length,
        )
        pass_count = sum(1 for r in results if r.passed)
        total = len(results)
        return 0 if (args.dry_run or pass_count == total) else 1

    # --- single / multi channel mode ---
    channels: list[PwmChannel] = args.pwm_channels or []
    if not channels:
        parser.error(
            "Specify at least one --pwm-channel PORT:PIN:FREQ:DUTY  "
            "or use --run-all to send all 28 hardware channels"
        )

    results = run_pwm_routine(
        channels=channels,
        test_command=args.test_command,
        can_channel=args.channel,
        bitrate=args.bitrate,
        fd=args.fd,
        data_bitrate=args.data_bitrate,
        tx_id=args.tx_id,
        rx_id=args.rx_id,
        timeout_s=args.timeout,
        dry_run=args.dry_run,
        tx_data_length=args.tx_data_length,
    )

    # Summary table
    print()
    print(f"{'Channel':<12}  {'Freq(Hz)':>8}  {'Duty%':>5}  {'Result':<6}  Status")
    print("-" * 52)
    for r in results:
        verdict = "PASS" if r.passed else "FAIL"
        print(
            f"{r.channel.label():<12}  {r.channel.frequency:>8}  {r.channel.duty:>5}"
            f"  {verdict:<6}  {r.status_desc}"
        )
    print("-" * 52)
    pass_count = sum(1 for r in results if r.passed)
    total = len(results)
    print(f"Total: {pass_count}/{total} PASS")

    return 0 if pass_count == total else 1


if __name__ == "__main__":
    sys.exit(main())
