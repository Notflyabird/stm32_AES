#!/usr/bin/env python3
"""
Service 0x31 - RoutineControl: ADC Test over CAN
================================================

Implements the protocol described for:
  Request : 31 01 A0 43 02 <channel_count> <port0> <pin0> ... <portN> <pinN>
  Positive: 71 01 A0 43 <routineInfo> <routineStatus>
  Negative: 7F 31 <NRC>

Protocol notes from the supplied definition:
  - SubFunction = 0x01  (StartRoutine)
  - Routine ID  = 0xA043
  - TestCommand = 0x02  (ADC test, asynchronous read)
  - ADC channel count is 0x01..0xFF
  - Each ADC channel is encoded as one Port ID byte + one Pin ID byte

This script only implements the StartRoutine request because the provided
protocol fragment does not define how the asynchronous ADC conversion result is
retrieved later. If the ECU returns additional bytes beyond the 6-byte positive
response, they are logged as raw payload for analysis.

Examples:
  Dry-run only (build request, do not open CAN):
    python Service_31_ADC_CAN.py --dry-run --adc-channel 0xFF:0x01

    Interactive wizard:
        python Service_31_ADC_CAN.py

    Preset test case for 31 01 A0 43 03 01 00 07:
        python Service_31_ADC_CAN.py --test-case tc_a043_03_single --dry-run

    Send one ADC channel on PCAN-USB channel 1:
        python Service_31_ADC_CAN.py --tx-id 0x772 --rx-id 0x77A \
        --adc-channel 0xFF:0x01

      Sample one channel 10 times and print statistics:
          python Service_31_ADC_CAN.py --tx-id 0x772 --rx-id 0x77A \
          --adc-channel 0x00:0x07 --samples 10 --sample-interval 0.1

  Send two ADC channels:
        python Service_31_ADC_CAN.py --tx-id 0x772 --rx-id 0x77A \
        --adc-channel 0xFF:0x01 --adc-channel 0xFF:0x02
"""

from __future__ import annotations

import argparse
import datetime
import logging
import os
import sys
import time
from dataclasses import dataclass
from typing import Sequence, Tuple


SID_ROUTINE_CONTROL = 0x31
POSITIVE_SID = 0x71
SUBFUNCTION_START_ROUTINE = 0x01
ROUTINE_ADC_TEST = 0xA043
ADC_TEST_COMMAND_ASYNC_READ = 0x02

NRC_BUSY_REPEAT_REQUEST = 0x21
NRC_REQUEST_CORRECTLY_RECEIVED_RESPONSE_PENDING = 0x78

RINFO_ROUTINE_ACTIVE = 0x01
RINFO_ROUTINE_RESULTS = 0x02
RSTATUS_SUCCESS = 0x00

DEFAULT_DEMO_ADC_CHANNELS = ((0xFF, 0x01),)
DEFAULT_TX_ID = 0x772
DEFAULT_RX_ID = 0x77A
TEST_CASE_A043_03_SINGLE = "tc_a043_03_single"


def bytes_to_hex(data: Sequence[int]) -> str:
    return " ".join(f"{value:02X}" for value in data)


def format_can_id(can_id: int) -> str:
    return f"0x{can_id:X}"


def channel_label(port_id: int, pin_id: int) -> str:
    """Return a human-readable label for an ADC channel.

    port=0xFF (255) → ANxx  (matches schematic AN naming)
    others          → P{port}.{pin}
    """
    if port_id == 0xFF:
        return f"AN{pin_id}"
    return f"P{port_id}.{pin_id}"


def _int_arg(value: str) -> int:
    return int(value, 0)


def _parse_adc_channel(spec: str) -> Tuple[int, int]:
    separators = (":", ",", "/")
    for separator in separators:
        if separator in spec:
            left, right = spec.split(separator, 1)
            port_id = _int_arg(left.strip())
            pin_id = _int_arg(right.strip())
            _validate_u8(port_id, "ADC Port ID")
            _validate_u8(pin_id, "ADC Pin ID")
            return port_id, pin_id
    raise argparse.ArgumentTypeError(
        f"Invalid ADC channel '{spec}'. Use PORT:PIN, for example 0xFF:0x01"
    )


def _validate_u8(value: int, field_name: str) -> None:
    if not 0 <= value <= 0xFF:
        raise ValueError(f"{field_name} must be in range 0x00..0xFF, got 0x{value:X}")


def log_can_exchange_context(log: "CanUdsLog", tx_id: int, rx_id: int,
                             timeout_s: float, expect_response: bool = True) -> None:
    log.info(
        f"CAN route: request TX ID={format_can_id(tx_id)}, response RX ID={format_can_id(rx_id)}"
    )
    if expect_response:
        log.info(
            f"Expected ECU response: should receive a reply on CAN ID {format_can_id(rx_id)} "
            f"within {timeout_s:.3f}s"
        )


def log_transport_failure_context(log: "CanUdsLog", exc: Exception,
                                  tx_id: int | None = None, rx_id: int | None = None) -> None:
    message = str(exc)
    if "Missing dependency" in message:
        route = ""
        if tx_id is not None and rx_id is not None:
            route = (
                f" on TX ID {format_can_id(tx_id)} / RX ID {format_can_id(rx_id)}"
            )
        log.info(
            "No CAN request was transmitted because the CAN transport could not be opened"
            f"{route}."
        )
        return

    if isinstance(exc, TimeoutError):
        if rx_id is not None:
            log.info(
                f"No ECU response was received on CAN ID {format_can_id(rx_id)} before timeout."
            )
        else:
            log.info("No ECU response was received before timeout.")


def ensure_can_transport_dependencies() -> None:
    missing_modules = []
    for module_name in ("can", "isotp"):
        try:
            __import__(module_name)
        except ImportError:
            missing_modules.append(module_name)

    if missing_modules:
        raise RuntimeError(
            "Missing dependency. Install with: pip install python-can can-isotp "
            f"(missing: {', '.join(missing_modules)})"
        )


def _prompt_text(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or default


def _prompt_bool(prompt: str, default: bool) -> bool:
    default_hint = "Y/n" if default else "y/N"
    while True:
        value = input(f"{prompt} [{default_hint}]: ").strip().lower()
        if not value:
            return default
        if value in {"y", "yes", "1", "true"}:
            return True
        if value in {"n", "no", "0", "false"}:
            return False
        print("Please answer with y or n.")


def _prompt_int(prompt: str, default: int | None = None) -> int:
    default_text = "" if default is None else hex(default)
    while True:
        raw_value = _prompt_text(prompt, default_text)
        if not raw_value and default is None:
            print("A value is required.")
            continue
        try:
            return _int_arg(raw_value)
        except ValueError:
            print(f"Invalid number '{raw_value}'. Use decimal or hex, for example 0x6F1.")


def _prompt_float(prompt: str, default: float) -> float:
    while True:
        raw_value = _prompt_text(prompt, str(default))
        try:
            return float(raw_value)
        except ValueError:
            print(f"Invalid float '{raw_value}'.")


def _prompt_adc_channels(default_channels: Sequence[Tuple[int, int]] | None = None) -> list[Tuple[int, int]]:
    if default_channels:
        default_text = " ".join(
            f"0x{port_id:02X}:0x{pin_id:02X}" for port_id, pin_id in default_channels
        )
    else:
        default_text = "0xFF:0x01"

    while True:
        raw_value = _prompt_text(
            "ADC channels, separated by spaces using PORT:PIN format",
            default_text,
        )
        channels: list[Tuple[int, int]] = []
        try:
            for token in raw_value.split():
                channels.append(_parse_adc_channel(token))
        except (argparse.ArgumentTypeError, ValueError) as exc:
            print(exc)
            continue

        if channels:
            return channels
        print("At least one ADC channel is required.")


def run_interactive_wizard(args: argparse.Namespace, log: "CanUdsLog") -> argparse.Namespace:
    log.info("Launching interactive ADC request wizard")

    args.dry_run = _prompt_bool("Dry-run only", True if not args.dry_run else args.dry_run)
    args.adc_channels = _prompt_adc_channels(args.adc_channels or DEFAULT_DEMO_ADC_CHANNELS)

    if not args.dry_run:
        args.channel = _prompt_text("PCAN channel", args.channel)
        args.bitrate = _prompt_int("CAN bitrate", args.bitrate)
        args.tx_id = _prompt_int("Tester -> ECU CAN ID", args.tx_id)
        args.rx_id = _prompt_int("ECU -> Tester CAN ID", args.rx_id)
        args.timeout = _prompt_float("Response timeout seconds", args.timeout)

    return args


def apply_test_case_defaults(args: argparse.Namespace, log: "CanUdsLog") -> argparse.Namespace:
    if args.test_case != TEST_CASE_A043_03_SINGLE:
        return args

    args.test_command = 0x03
    args.adc_channels = [(0x00, 0x07)]
    log.info(
        "Applied preset test case tc_a043_03_single -> request 31 01 A0 43 03 01 00 07"
    )
    return args


class CanUdsLog:
    PASS = "PASS"
    FAIL = "FAIL"

    def __init__(self, script_name: str):
        log_dir = os.path.join(os.path.dirname(__file__), "Result")
        os.makedirs(log_dir, exist_ok=True)

        timestamp = datetime.datetime.now().strftime("%H%M%S")
        filename = f"SVVR_{script_name}_{timestamp}.log"
        self.log_path = os.path.join(log_dir, filename)
        self._current_step = ""
        self._pass_count = 0
        self._fail_count = 0

        self._logger = logging.getLogger(f"{script_name}_{timestamp}")
        self._logger.setLevel(logging.DEBUG)
        self._logger.handlers.clear()
        self._logger.propagate = False

        formatter = logging.Formatter("%(asctime)s.%(msecs)03d %(message)s", datefmt="%H:%M:%S")

        file_handler = logging.FileHandler(self.log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        self._logger.addHandler(file_handler)

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        self._logger.addHandler(console_handler)

        self._write_separator("=")
        self._logger.info(f"[START ] Script : {script_name}")
        self._logger.info(f"[START ] Log    : {self.log_path}")
        self._write_separator("=")

    def _write_separator(self, char: str) -> None:
        self._logger.info(char * 72)

    def start_test(self, description: str) -> None:
        self._current_step = description
        self._write_separator("-")
        self._logger.info(f"[STEP  ] {description}")

    def info(self, message: str) -> None:
        self._logger.info(f"[INFO  ] {message}")

    def tx(self, hex_bytes: str, description: str = "") -> None:
        label = f"TX {description}".strip()
        self._logger.info(f"[{label:<6}] {hex_bytes}")

    def rx(self, hex_bytes: str, description: str = "") -> None:
        label = f"RX {description}".strip()
        self._logger.info(f"[{label:<6}] {hex_bytes}")

    def result(self, passed: bool, expected: str = "", received: str = "",
               description: str = "") -> None:
        status = self.PASS if passed else self.FAIL
        step = description or self._current_step
        self._logger.info(
            f"[{status:<6}] {step}"
            + (f" | expected: {expected}" if expected else "")
            + (f" | received: {received}" if received else "")
        )
        if passed:
            self._pass_count += 1
        else:
            self._fail_count += 1

    def error(self, message: str) -> None:
        self._logger.error(f"[ERROR ] {message}")
        self._fail_count += 1

    def close(self) -> None:
        total = self._pass_count + self._fail_count
        self._write_separator("=")
        self._logger.info(
            f"[SUMRY ] PASS={self._pass_count} FAIL={self._fail_count} "
            f"TOTAL={total} {'ALL PASS' if self._fail_count == 0 else 'FAILED'}"
        )
        self._write_separator("=")
        for handler in self._logger.handlers[:]:
            handler.close()
            self._logger.removeHandler(handler)

    @property
    def all_passed(self) -> bool:
        return self._fail_count == 0


@dataclass(frozen=True)
class AdcRoutineResponse:
    raw: bytes
    is_positive: bool
    routine_info: int | None = None
    routine_status: int | None = None
    nrc: int | None = None
    extra_data: bytes = b""


@dataclass(frozen=True)
class AdcChannelValue:
    port_id: int
    pin_id: int
    value: int


@dataclass(frozen=True)
class AdcSample:
    index: int
    response: AdcRoutineResponse
    channel_values: tuple[AdcChannelValue, ...]


def build_adc_start_request(test_command: int,
                            adc_channels: Sequence[Tuple[int, int]]) -> bytes:
    _validate_u8(test_command, "Test command")
    if not adc_channels:
        raise ValueError("At least one ADC channel must be provided")
    if len(adc_channels) > 0xFF:
        raise ValueError("ADC channel count must be in range 0x01..0xFF")

    request = bytearray([
        SID_ROUTINE_CONTROL,
        SUBFUNCTION_START_ROUTINE,
        (ROUTINE_ADC_TEST >> 8) & 0xFF,
        ROUTINE_ADC_TEST & 0xFF,
        test_command,
        len(adc_channels),
    ])
    for port_id, pin_id in adc_channels:
        _validate_u8(port_id, "ADC Port ID")
        _validate_u8(pin_id, "ADC Pin ID")
        request.extend([port_id, pin_id])
    return bytes(request)


def parse_adc_routine_response(response: bytes) -> AdcRoutineResponse:
    if not response:
        raise ValueError("ECU response is empty")

    if len(response) >= 3 and response[0] == 0x7F and response[1] == SID_ROUTINE_CONTROL:
        return AdcRoutineResponse(raw=response, is_positive=False, nrc=response[2])

    if len(response) < 6:
        raise ValueError(
            "Positive response is shorter than 6 bytes: "
            f"{bytes_to_hex(response)}"
        )

    if response[0] != POSITIVE_SID:
        raise ValueError(f"Unexpected positive SID: 0x{response[0]:02X}")
    if response[1] != SUBFUNCTION_START_ROUTINE:
        raise ValueError(f"Unexpected subfunction in response: 0x{response[1]:02X}")

    routine_id = (response[2] << 8) | response[3]
    if routine_id != ROUTINE_ADC_TEST:
        raise ValueError(f"Unexpected routine ID in response: 0x{routine_id:04X}")

    routine_info = response[4]
    return AdcRoutineResponse(
        raw=response,
        is_positive=True,
        routine_info=routine_info,
        routine_status=response[5],
        extra_data=response[6:],
    )


def decode_adc_channel_values(extra_data: bytes) -> tuple[AdcChannelValue, ...]:
    if len(extra_data) < 4:
        return tuple()

    if len(extra_data) % 4 == 0:
        values = []
        for offset in range(0, len(extra_data), 4):
            values.append(
                AdcChannelValue(
                    port_id=extra_data[offset],
                    pin_id=extra_data[offset + 1],
                    value=(extra_data[offset + 2] << 8) | extra_data[offset + 3],
                )
            )
        return tuple(values)

    count = extra_data[0]
    offset = 1
    values = []
    for _ in range(count):
        if offset + 3 >= len(extra_data):
            break
        values.append(
            AdcChannelValue(
                port_id=extra_data[offset],
                pin_id=extra_data[offset + 1],
                value=(extra_data[offset + 2] << 8) | extra_data[offset + 3],
            )
        )
        offset += 4
    return tuple(values)


def nrc_name(nrc: int) -> str:
    mapping = {
        0x10: "generalReject",
        0x11: "serviceNotSupported",
        0x12: "subFunctionNotSupported",
        0x13: "incorrectMessageLengthOrInvalidFormat",
        0x21: "busyRepeatRequest",
        0x22: "conditionsNotCorrect",
        0x24: "requestSequenceError",
        0x31: "requestOutOfRange",
        0x33: "securityAccessDenied",
        0x78: "requestCorrectlyReceivedResponsePending",
        0xF1: "parameterErrorOrNotSupported",
    }
    return mapping.get(nrc, f"unknown(0x{nrc:02X})")


def routine_info_name(value: int) -> str:
    mapping = {
        RINFO_ROUTINE_ACTIVE: "RoutineActive",
        RINFO_ROUTINE_RESULTS: "RoutineResults",
    }
    return mapping.get(value, f"Unknown(0x{value:02X})")


def routine_status_name(value: int) -> str:
    mapping = {
        RSTATUS_SUCCESS: "RoutineExecutionSuccessful",
    }
    return mapping.get(value, f"Unknown(0x{value:02X})")


class CanIsoTpUdsClient:
    def __init__(self, channel: str, bitrate: int, tx_id: int, rx_id: int,
                 log: CanUdsLog, poll_interval_s: float = 0.002,
                 fd: bool = True, data_bitrate: int = 5_000_000,
                 f_clock_mhz: int = 80, tx_data_length: int = 0):
        """ISO-TP UDS client over PCAN.

        tx_data_length:
            CAN FD DLC for transmitted frames (bytes in the data field).
            Valid FD values: 12, 16, 20, 24, 32, 48, 64.  0 = auto-select
            (12 for FD, 8 for classic CAN).  Increase to 16 when the UDS
            payload exceeds 10 bytes so it fits in a single frame.
        """
        self.channel = channel
        self.bitrate = bitrate
        self.tx_id = tx_id
        self.rx_id = rx_id
        self.log = log
        self.poll_interval_s = poll_interval_s
        self.fd = fd
        self.data_bitrate = data_bitrate
        self.f_clock_mhz = f_clock_mhz
        self.tx_data_length = tx_data_length  # 0 = auto
        self._bus = None
        self._stack = None
        self._last_isotp_error = None

    def open(self) -> None:
        try:
            import can
            import isotp
        except ImportError as exc:
            raise RuntimeError(
                "Missing dependency. Install with: pip install python-can can-isotp"
            ) from exc

        mode_str = "CAN-FD" if self.fd else "CAN"
        self.log.info(
            f"Opening PCAN bus [{mode_str}] channel={self.channel} bitrate={self.bitrate} "
            + (f"data_bitrate={self.data_bitrate} " if self.fd else "")
            + f"tx_id=0x{self.tx_id:X} rx_id=0x{self.rx_id:X}"
        )

        # Clear any residual PCAN channel state to avoid Bus-Heavy errors
        try:
            from can.interfaces.pcan.basic import PCANBasic, PCAN_USBBUS1, PCAN_USBBUS2
            channel_map = {"PCAN_USBBUS1": PCAN_USBBUS1, "PCAN_USBBUS2": PCAN_USBBUS2}
            pcan_handle = channel_map.get(self.channel, PCAN_USBBUS1)
            pcan = PCANBasic()
            pcan.Uninitialize(pcan_handle)
            del pcan
            import time
            time.sleep(0.1)
        except Exception:
            pass

        self._open_stack()

    def _open_stack(self) -> None:
        import can
        import isotp

        if self.fd:
            self._bus = can.Bus(
                interface="pcan", channel=self.channel, fd=True,
                f_clock_mhz=self.f_clock_mhz,
                nom_brp=10, nom_tseg1=12, nom_tseg2=3, nom_sjw=1,   # 500 kbps
                data_brp=2, data_tseg1=5, data_tseg2=2, data_sjw=1,  # 5 Mbps
            )
        else:
            self._bus = can.Bus(interface="pcan", channel=self.channel, bitrate=self.bitrate)

        address = isotp.Address(
            isotp.AddressingMode.Normal_11bits,
            txid=self.tx_id,
            rxid=self.rx_id,
        )

        isotp_params = {
            "stmin": 0,
            "blocksize": 8,
            "wftmax": 0,
            "rx_flowcontrol_timeout": 1000,
            "rx_consecutive_frame_timeout": 1000,
        }
        if self.fd:
            # Auto-select DLC: 12 unless caller overrides.
            # CAN FD extended-SF header costs 2 bytes, so:
            #   DLC=12 → max SF payload = 10 bytes
            #   DLC=16 → max SF payload = 14 bytes  (use for 11-byte requests)
            _dlc = self.tx_data_length if self.tx_data_length > 0 else 12
            isotp_params["tx_data_length"] = _dlc
            isotp_params["tx_padding"] = 0xCC
            # The ECU only accepts a FlowControl frame transmitted as an FD frame
            # padded to DLC=8.  Without this floor, can-isotp emits the 3-byte FC
            # as an FD DLC=3 frame, which this ECU silently ignores, so it never
            # sends the Consecutive Frame ("CONSECUTIVE_FRAME timed out").
            # tx_data_min_length=8 pads small frames (FC) up to DLC=8 while the
            # 10-byte single frame still uses DLC=12.
            isotp_params["tx_data_min_length"] = 8
            isotp_params["can_fd"] = True
            self.log.info(f"ISO-TP tx_data_length=DLC{_dlc} tx_data_min_length=DLC8 "
                          f"(max SF payload={(  _dlc - 2)} bytes)")
        else:
            isotp_params["tx_data_length"] = 8

        self.log.info(f"PCAN active mode: {'CAN-FD' if self.fd else 'CAN classic'}")

        self._stack = isotp.CanStack(
            bus=self._bus,
            address=address,
            error_handler=self._handle_isotp_error,
            params=isotp_params,
        )

    def close(self) -> None:
        if self._bus is not None:
            try:
                self._bus.shutdown()
            finally:
                self._bus = None
                self._stack = None

    def _handle_isotp_error(self, error: Exception) -> None:
        self._last_isotp_error = error

    def send_uds(self, request: bytes, timeout_s: float) -> bytes:
        if self._stack is None:
            raise RuntimeError("CAN ISO-TP stack is not open")
        return self._send_uds_once(request, timeout_s)

    def _send_uds_once(self, request: bytes, timeout_s: float) -> bytes:
        self._last_isotp_error = None
        self._stack.send(request)
        deadline = time.monotonic() + timeout_s
        saw_response_pending = False

        while time.monotonic() < deadline:
            self._stack.process()
            if self._last_isotp_error is not None:
                raise RuntimeError(f"ISO-TP transport error: {self._last_isotp_error}")
            if self._stack.available():
                response = self._stack.recv()
                if (
                    len(response) >= 3
                    and response[0] == 0x7F
                    and response[1] == SID_ROUTINE_CONTROL
                    and response[2] == NRC_REQUEST_CORRECTLY_RECEIVED_RESPONSE_PENDING
                ):
                    saw_response_pending = True
                    self.log.info("Received NRC 0x78 responsePending, waiting for final response")
                    continue
                return bytes(response)
            time.sleep(self.poll_interval_s)

        if saw_response_pending:
            raise TimeoutError("Timed out waiting for final ECU response after NRC 0x78")
        raise TimeoutError(f"Timed out waiting for ECU response after {timeout_s:.3f}s")


def send_adc_start_routine(client: CanIsoTpUdsClient, request: bytes,
                           timeout_s: float, busy_retries: int,
                           busy_wait_s: float, log: CanUdsLog,
                           step_label: str = "0x31 0x01 0xA043 ADC StartRoutine") -> AdcRoutineResponse:
    for attempt in range(1, busy_retries + 2):
        log.start_test(f"{step_label} attempt {attempt}")
        log_can_exchange_context(log, client.tx_id, client.rx_id, timeout_s)
        log.tx(
            bytes_to_hex(request),
            f"CAN {format_can_id(client.tx_id)} RoutineControl ADC Test"
        )
        raw_response = client.send_uds(request, timeout_s=timeout_s)
        log.rx(bytes_to_hex(raw_response), f"CAN {format_can_id(client.rx_id)}")

        parsed = parse_adc_routine_response(raw_response)
        if not parsed.is_positive and parsed.nrc == NRC_BUSY_REPEAT_REQUEST and attempt <= busy_retries:
            log.info(
                f"ECU returned NRC 0x21 ({nrc_name(parsed.nrc)}), retrying after {busy_wait_s:.3f}s"
            )
            time.sleep(busy_wait_s)
            continue
        return parsed

    raise RuntimeError("Unexpected retry loop exit")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Send UDS 0x31 0x01 0xA043 ADC Test over CAN/ISO-TP via PCAN"
    )
    parser.add_argument("--channel", default="PCAN_USBBUS1",
                        help="PCAN channel name for python-can, default: PCAN_USBBUS1")
    parser.add_argument("--bitrate", type=int, default=500000,
                        help="CAN nominal bitrate in bit/s, default: 500000")
    parser.add_argument("--no-fd", dest="fd", action="store_false", default=True,
                        help="Disable CAN FD, use classic CAN instead")
    parser.add_argument("--data-bitrate", type=int, default=5_000_000,
                        help="CAN FD data phase bitrate, default: 5000000")
    parser.add_argument("--tx-id", type=_int_arg, default=DEFAULT_TX_ID,
                        help="Tester to ECU CAN ID, default: 0x772")
    parser.add_argument("--rx-id", type=_int_arg, default=DEFAULT_RX_ID,
                        help="ECU to tester CAN ID, default: 0x77A")
    parser.add_argument("--test-command", type=_int_arg, default=ADC_TEST_COMMAND_ASYNC_READ,
                        help="Routine test command byte, default: 0x02")
    parser.add_argument("--test-case", choices=[TEST_CASE_A043_03_SINGLE],
                        help="Apply a preset request payload")
    parser.add_argument("--adc-channel", dest="adc_channels", type=_parse_adc_channel,
                        action="append",
                        help="ADC channel as PORT:PIN, repeat for multiple channels")
    parser.add_argument("--timeout", type=float, default=2.0,
                        help="Final ECU response timeout in seconds, default: 2.0")
    parser.add_argument("--busy-retries", type=int, default=3,
                        help="Retry count when ECU returns NRC 0x21, default: 3")
    parser.add_argument("--busy-wait", type=float, default=0.2,
                        help="Delay before retry after NRC 0x21, default: 0.2")
    parser.add_argument("--samples", type=int, default=1,
                        help="Number of ADC acquisitions to perform, default: 1")
    parser.add_argument("--sample-interval", type=float, default=0.0,
                        help="Delay in seconds between acquisitions, default: 0.0")
    parser.add_argument("--interactive", action="store_true",
                        help="Launch an interactive wizard to collect parameters")
    parser.add_argument("--dry-run", action="store_true",
                        help="Only build and print the request, do not open CAN")
    # Fixed test case options
    parser.add_argument("--case", choices=sorted(FIXED_CASES_BY_NAME),
                        help="Run a built-in fixed test case by name")
    parser.add_argument("--expect", choices=sorted(EXPECTED_RESPONSE_MAP), default=EXPECTED_POSITIVE,
                        help="Expected response type for fixed case verdict, default: positive")
    parser.add_argument("--list-cases", action="store_true",
                        help="Print available fixed test cases and exit")
    parser.add_argument("--run-all-cases", action="store_true",
                        help="Run all built-in fixed cases sequentially")
    parser.add_argument("--read-all", action="store_true",
                        help="Read all 16 default ADC channels one-by-one")
    return parser


def log_request_summary(request: bytes, adc_channels: Sequence[Tuple[int, int]], log: CanUdsLog) -> None:
    log.info(f"ADC channel count: {len(adc_channels)}")
    for index, (port_id, pin_id) in enumerate(adc_channels):
        log.info(f"ADC[{index}] Port=0x{port_id:02X} Pin=0x{pin_id:02X}")
    log.info(f"UDS request payload: {bytes_to_hex(request)}")


def _log_adc_values(extra_data: bytes, log: CanUdsLog) -> None:
    for index, sample in enumerate(decode_adc_channel_values(extra_data)):
        log.info(
            f"ADC result[{index}] Port=0x{sample.port_id:02X} Pin=0x{sample.pin_id:02X} "
            f"Value=0x{sample.value:04X} ({sample.value})"
        )


def collect_adc_samples(client: CanIsoTpUdsClient, request: bytes,
                        timeout_s: float, busy_retries: int,
                        busy_wait_s: float, sample_count: int,
                        sample_interval_s: float, log: CanUdsLog) -> list[AdcSample]:
    if sample_count < 1:
        raise ValueError("--samples must be >= 1")
    if sample_interval_s < 0:
        raise ValueError("--sample-interval must be >= 0")

    samples: list[AdcSample] = []
    for sample_index in range(1, sample_count + 1):
        response = send_adc_start_routine(
            client=client,
            request=request,
            timeout_s=timeout_s,
            busy_retries=busy_retries,
            busy_wait_s=busy_wait_s,
            log=log,
            step_label=f"ADC sample {sample_index}/{sample_count}",
        )
        samples.append(
            AdcSample(
                index=sample_index,
                response=response,
                channel_values=decode_adc_channel_values(response.extra_data),
            )
        )
        if sample_index < sample_count and sample_interval_s > 0:
            log.info(
                f"Waiting {sample_interval_s:.3f}s before next ADC acquisition"
            )
            time.sleep(sample_interval_s)
    return samples


def log_adc_statistics(samples: Sequence[AdcSample], log: CanUdsLog) -> None:
    if len(samples) <= 1:
        return

    grouped: dict[tuple[int, int], list[int]] = {}
    for sample in samples:
        for channel_value in sample.channel_values:
            key = (channel_value.port_id, channel_value.pin_id)
            grouped.setdefault(key, []).append(channel_value.value)

    if not grouped:
        log.info("ADC statistics unavailable because no decoded ADC values were returned")
        return

    log.info(f"ADC statistics summary across {len(samples)} samples")
    for (port_id, pin_id), values in sorted(grouped.items()):
        average = sum(values) / len(values)
        log.info(
            f"ADC stats Port=0x{port_id:02X} Pin=0x{pin_id:02X} "
            f"count={len(values)} min={min(values)} max={max(values)} avg={average:.2f} last={values[-1]}"
        )


def log_response_summary(response: AdcRoutineResponse, log: CanUdsLog) -> bool:
    if response.is_positive:
        info_name = routine_info_name(response.routine_info)
        if response.routine_status is not None:
            status_name = routine_status_name(response.routine_status)
            log.info(
                f"Positive response: routineInfo=0x{response.routine_info:02X} ({info_name}), "
                f"routineStatus=0x{response.routine_status:02X} ({status_name})"
            )
        if response.extra_data:
            log.info(f"Extra response bytes: {bytes_to_hex(response.extra_data)}")

        passed = response.routine_info in (RINFO_ROUTINE_ACTIVE, RINFO_ROUTINE_RESULTS)
        log.result(
            passed,
            expected="71 01 A0 43 (01|02) ...",
            received=bytes_to_hex(response.raw),
            description="ADC StartRoutine positive response",
        )
        if passed and response.extra_data:
            _log_adc_values(response.extra_data, log)
        return passed

    log.result(
        False,
        expected="71 01 A0 43 01 00",
        received=f"7F 31 {response.nrc:02X} ({nrc_name(response.nrc)})",
        description="ADC StartRoutine negative response",
    )
    return False


# ═══════════════════════════════════════════════════════════════════════════════
# Fixed Test Cases — callable test functions
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class FixedCase:
    name: str
    test_command: int
    adc_channels: tuple[tuple[int, int], ...]
    description: str


FIXED_CASES: tuple[FixedCase, ...] = (
    FixedCase(
        name="a043_03_00_01",
        test_command=0x03,
        adc_channels=((0x00, 0x01),),
        description="31 01 A0 43 03 01 00 01",
    ),
    FixedCase(
        name="a043_03_00_02",
        test_command=0x03,
        adc_channels=((0x00, 0x02),),
        description="31 01 A0 43 03 01 00 02",
    ),
    FixedCase(
        name="a043_03_00_03",
        test_command=0x03,
        adc_channels=((0x00, 0x03),),
        description="31 01 A0 43 03 01 00 03",
    ),
    FixedCase(
        name="a043_03_00_07",
        test_command=0x03,
        adc_channels=((0x00, 0x07),),
        description="31 01 A0 43 03 01 00 07",
    ),
    FixedCase(
        name="a043_03_21_04",
        test_command=0x03,
        adc_channels=((0x21, 0x04),),
        description="31 01 A0 43 03 01 21 04",
    ),
    FixedCase(
        name="a043_03_21_05",
        test_command=0x03,
        adc_channels=((0x21, 0x05),),
        description="31 01 A0 43 03 01 21 05",
    ),
    FixedCase(
        name="a043_03_22_02",
        test_command=0x03,
        adc_channels=((0x22, 0x02),),
        description="31 01 A0 43 03 01 22 02",
    ),
    FixedCase(
        name="a043_03_22_03",
        test_command=0x03,
        adc_channels=((0x22, 0x03),),
        description="31 01 A0 43 03 01 22 03",
    ),
    FixedCase(
        name="a043_03_22_04",
        test_command=0x03,
        adc_channels=((0x22, 0x04),),
        description="31 01 A0 43 03 01 22 04",
    ),
)

FIXED_CASES_BY_NAME = {case.name: case for case in FIXED_CASES}
DEFAULT_CASE_NAME = "a043_03_00_07"

EXPECTED_POSITIVE = "positive"
EXPECTED_NRC13 = "nrc13"
EXPECTED_NRC21 = "nrc21"
EXPECTED_NRCF1 = "nrcf1"

EXPECTED_RESPONSE_MAP = {
    EXPECTED_POSITIVE: (True, None, "71 01 A0 43 02 ..."),
    EXPECTED_NRC13: (False, 0x13, "7F 31 13"),
    EXPECTED_NRC21: (False, 0x21, "7F 31 21"),
    EXPECTED_NRCF1: (False, 0xF1, "7F 31 F1"),
}


def evaluate_expected_response(response: AdcRoutineResponse, expected: str, log: CanUdsLog) -> bool:
    expect_positive, expected_nrc, expected_hex = EXPECTED_RESPONSE_MAP[expected]

    if expect_positive:
        passed = (
            response.is_positive
            and response.routine_info in (RINFO_ROUTINE_ACTIVE, RINFO_ROUTINE_RESULTS)
        )
        log.result(
            passed,
            expected=expected_hex,
            received=" ".join(f"{byte:02X}" for byte in response.raw),
            description="Fixed case expected positive response",
        )
        return passed

    passed = (not response.is_positive and response.nrc == expected_nrc)
    received = (
        f"7F 31 {response.nrc:02X} ({nrc_name(response.nrc)})"
        if not response.is_positive and response.nrc is not None
        else " ".join(f"{byte:02X}" for byte in response.raw)
    )
    log.result(
        passed,
        expected=f"{expected_hex} ({nrc_name(expected_nrc)})",
        received=received,
        description="Fixed case expected NRC response",
    )
    return passed


def run_fixed_case(
    case_name: str = DEFAULT_CASE_NAME,
    expected: str = EXPECTED_POSITIVE,
    channel: str = "PCAN_USBBUS1",
    bitrate: int = 500000,
    fd: bool = True,
    data_bitrate: int = 5_000_000,
    tx_id: int = DEFAULT_TX_ID,
    rx_id: int = DEFAULT_RX_ID,
    timeout_s: float = 2.0,
    busy_retries: int = 3,
    busy_wait_s: float = 0.2,
    dry_run: bool = False,
    log: CanUdsLog | None = None,
) -> bool:
    """Run a single fixed ADC test case. Returns True if verdict matches expectation."""
    case = FIXED_CASES_BY_NAME[case_name]
    own_log = log is None
    if own_log:
        log = CanUdsLog("Service_31_ADC_CAN_Cases")

    client = None
    try:
        log.info(f"Selected fixed case: {case.name}")
        log.info(f"Case payload: {case.description}")
        log.info(f"Expected verdict: {expected}")
        log_can_exchange_context(log, tx_id, rx_id, timeout_s)

        request = build_adc_start_request(case.test_command, case.adc_channels)
        log_request_summary(request, case.adc_channels, log)

        if dry_run:
            log.info(
                f"Dry-run note: request would be sent on CAN ID {format_can_id(tx_id)} "
                f"and should receive a reply on CAN ID {format_can_id(rx_id)}"
            )
            log.info("Dry-run enabled, request built successfully and CAN transport was skipped")
            log.result(True, description=f"Fixed case {case.name} request build")
            return True

        ensure_can_transport_dependencies()

        client = CanIsoTpUdsClient(
            channel=channel,
            bitrate=bitrate,
            tx_id=tx_id,
            rx_id=rx_id,
            log=log,
            fd=fd,
            data_bitrate=data_bitrate,
        )
        client.open()
        response = send_adc_start_routine(
            client=client,
            request=request,
            timeout_s=timeout_s,
            busy_retries=busy_retries,
            busy_wait_s=busy_wait_s,
            log=log,
        )
        log_response_summary(response, log)
        return evaluate_expected_response(response, expected, log)
    except Exception as exc:
        log_transport_failure_context(log, exc, tx_id, rx_id)
        log.error(str(exc))
        return False
    finally:
        if client is not None:
            client.close()
        if own_log:
            log.close()


def run_adc_sampling(
    adc_channels: Sequence[Tuple[int, int]],
    test_command: int = ADC_TEST_COMMAND_ASYNC_READ,
    samples: int = 1,
    sample_interval_s: float = 0.0,
    channel: str = "PCAN_USBBUS1",
    bitrate: int = 500000,
    fd: bool = True,
    data_bitrate: int = 5_000_000,
    tx_id: int = DEFAULT_TX_ID,
    rx_id: int = DEFAULT_RX_ID,
    timeout_s: float = 2.0,
    busy_retries: int = 3,
    busy_wait_s: float = 0.2,
    log: CanUdsLog | None = None,
) -> list[AdcSample]:
    """Run ADC sampling with configurable channels and repetition count.

    Returns the list of collected AdcSample results.
    """
    own_log = log is None
    if own_log:
        log = CanUdsLog("Service_31_ADC_CAN")

    client = None
    try:
        request = build_adc_start_request(test_command, adc_channels)
        log_request_summary(request, adc_channels, log)

        ensure_can_transport_dependencies()

        client = CanIsoTpUdsClient(
            channel=channel,
            bitrate=bitrate,
            tx_id=tx_id,
            rx_id=rx_id,
            log=log,
            fd=fd,
            data_bitrate=data_bitrate,
        )
        client.open()
        collected = collect_adc_samples(
            client=client,
            request=request,
            timeout_s=timeout_s,
            busy_retries=busy_retries,
            busy_wait_s=busy_wait_s,
            sample_count=samples,
            sample_interval_s=sample_interval_s,
            log=log,
        )
        all_passed = True
        for sample in collected:
            log.info(f"ADC sample {sample.index}/{len(collected)} result summary")
            all_passed = log_response_summary(sample.response, log) and all_passed
        log_adc_statistics(collected, log)
        return collected
    except Exception as exc:
        log_transport_failure_context(log, exc, tx_id, rx_id)
        log.error(str(exc))
        return []
    finally:
        if client is not None:
            client.close()
        if own_log:
            log.close()


def run_all_fixed_cases(
    expected: str = EXPECTED_POSITIVE,
    channel: str = "PCAN_USBBUS1",
    bitrate: int = 500000,
    fd: bool = True,
    data_bitrate: int = 5_000_000,
    tx_id: int = DEFAULT_TX_ID,
    rx_id: int = DEFAULT_RX_ID,
    timeout_s: float = 2.0,
    busy_retries: int = 3,
    busy_wait_s: float = 0.2,
    log: CanUdsLog | None = None,
) -> dict[str, bool]:
    """Run all built-in fixed cases and return {case_name: passed} dict."""
    own_log = log is None
    if own_log:
        log = CanUdsLog("Service_31_ADC_CAN_AllCases")

    results: dict[str, bool] = {}
    client = None
    try:
        ensure_can_transport_dependencies()
        client = CanIsoTpUdsClient(
            channel=channel,
            bitrate=bitrate,
            tx_id=tx_id,
            rx_id=rx_id,
            log=log,
            fd=fd,
            data_bitrate=data_bitrate,
        )
        client.open()

        for case in FIXED_CASES:
            log.info(f"Running fixed case: {case.name} ({case.description})")
            request = build_adc_start_request(case.test_command, case.adc_channels)
            log_request_summary(request, case.adc_channels, log)
            try:
                response = send_adc_start_routine(
                    client=client,
                    request=request,
                    timeout_s=timeout_s,
                    busy_retries=busy_retries,
                    busy_wait_s=busy_wait_s,
                    log=log,
                )
                log_response_summary(response, log)
                results[case.name] = evaluate_expected_response(response, expected, log)
            except Exception as exc:
                log.error(f"Case {case.name} failed: {exc}")
                results[case.name] = False

        log.info("All fixed cases summary:")
        for name, passed in results.items():
            log.info(f"  {name}: {'PASS' if passed else 'FAIL'}")
    except Exception as exc:
        log_transport_failure_context(log, exc, tx_id, rx_id)
        log.error(str(exc))
    finally:
        if client is not None:
            client.close()
        if own_log:
            log.close()
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Sequential multi-channel read — read each channel one-by-one over single bus
# ═══════════════════════════════════════════════════════════════════════════════

ALL_ADC_CHANNELS: tuple[tuple[int, int], ...] = (
    # P0.1 ~ P0.12
    (0, 1), (0, 2), (0, 3), (0, 4), (0, 5), (0, 6), (0, 7), (0, 8),
    (0, 9), (0, 10), (0, 11), (0, 12),
    # P1.3 ~ P1.5
    (1, 3), (1, 4), (1, 5),
    # P2.11
    (2, 11),
    # P33.4 ~ P33.5
    (0x21, 4), (0x21, 5),
    # P34.2 ~ P34.4
    (0x22, 2), (0x22, 3), (0x22, 4),
    # P40.0 ~ P40.15
    (0x28, 0), (0x28, 1), (0x28, 2), (0x28, 3), (0x28, 4), (0x28, 5),
    (0x28, 6), (0x28, 7), (0x28, 8), (0x28, 9), (0x28, 10), (0x28, 11),
    (0x28, 12), (0x28, 13), (0x28, 14), (0x28, 15),
    # P41.0 ~ P41.8
    (0x29, 0), (0x29, 1), (0x29, 2), (0x29, 3), (0x29, 4),
    (0x29, 5), (0x29, 6), (0x29, 7), (0x29, 8),
    # AN0 ~ AN16  (port=0xFF)
    (0xFF, 0), (0xFF, 1), (0xFF, 2), (0xFF, 3), (0xFF, 4), (0xFF, 5),
    (0xFF, 6), (0xFF, 7), (0xFF, 8), (0xFF, 9), (0xFF, 10), (0xFF, 11),
    (0xFF, 12), (0xFF, 13), (0xFF, 14), (0xFF, 15), (0xFF, 16),
    # AN20 ~ AN23
    (0xFF, 20), (0xFF, 21), (0xFF, 22), (0xFF, 23),
    # AN30 ~ AN31
    (0xFF, 30), (0xFF, 31),
    # AN34 ~ AN35
    (0xFF, 34), (0xFF, 35),
    # AN40 ~ AN47
    (0xFF, 40), (0xFF, 41), (0xFF, 42), (0xFF, 43),
    (0xFF, 44), (0xFF, 45), (0xFF, 46), (0xFF, 47),
    # AN48 ~ AN53
    (0xFF, 48), (0xFF, 49), (0xFF, 50), (0xFF, 51), (0xFF, 52), (0xFF, 53),
    # AN56 ~ AN61
    (0xFF, 56), (0xFF, 57), (0xFF, 58), (0xFF, 59), (0xFF, 60), (0xFF, 61),
    # AN65 ~ AN66
    (0xFF, 65), (0xFF, 66),
)
ALL_16_ADC_CHANNELS = ALL_ADC_CHANNELS  # backward compat alias


@dataclass
class ChannelReadResult:
    port_id: int
    pin_id: int
    passed: bool
    value: int | None
    response: AdcRoutineResponse | None


def read_all_adc_channels(
    channels: Sequence[tuple[int, int]] = ALL_16_ADC_CHANNELS,
    test_command: int = 0x03,
    channel: str = "PCAN_USBBUS1",
    bitrate: int = 500000,
    fd: bool = True,
    data_bitrate: int = 5_000_000,
    tx_id: int = DEFAULT_TX_ID,
    rx_id: int = DEFAULT_RX_ID,
    timeout_s: float = 2.0,
    busy_retries: int = 3,
    busy_wait_s: float = 0.2,
    log: CanUdsLog | None = None,
) -> list[ChannelReadResult]:
    """Read ADC channels one-by-one sequentially over a single CAN connection.

    Returns a list of ChannelReadResult (one per channel).
    """
    own_log = log is None
    if own_log:
        log = CanUdsLog("Service_31_ADC_ALL_CH")

    results: list[ChannelReadResult] = []
    client = None
    try:
        ensure_can_transport_dependencies()
        client = CanIsoTpUdsClient(
            channel=channel,
            bitrate=bitrate,
            tx_id=tx_id,
            rx_id=rx_id,
            log=log,
            fd=fd,
            data_bitrate=data_bitrate,
        )
        client.open()

        total = len(channels)
        for idx, (port_id, pin_id) in enumerate(channels, 1):
            label = channel_label(port_id, pin_id)
            log.info(f"--- Channel {idx}/{total}: {label} ---")
            request = build_adc_start_request(test_command, ((port_id, pin_id),))
            try:
                response = send_adc_start_routine(
                    client=client,
                    request=request,
                    timeout_s=timeout_s,
                    busy_retries=busy_retries,
                    busy_wait_s=busy_wait_s,
                    log=log,
                )
                passed = log_response_summary(response, log)
                adc_value = None
                if response.is_positive and response.extra_data and len(response.extra_data) >= 4:
                    adc_value = (response.extra_data[2] << 8) | response.extra_data[3]
                results.append(ChannelReadResult(port_id, pin_id, passed, adc_value, response))
            except Exception as exc:
                log.error(f"{channel_label(port_id, pin_id)} failed: {exc}")
                results.append(ChannelReadResult(port_id, pin_id, False, None, None))

        # Print summary table
        log.info("=" * 50)
        log.info("Channel read summary:")
        log.info(f"{'Channel':<10} {'Status':<8} {'ADC Value'}")
        for r in results:
            lbl = channel_label(r.port_id, r.pin_id)
            val_str = f"0x{r.value:04X} ({r.value})" if r.value is not None else "N/A"
            log.info(f"{lbl:<10} {'PASS' if r.passed else 'FAIL':<8} {val_str}")
        pass_count = sum(1 for r in results if r.passed)
        log.info(f"Total: {pass_count}/{total} PASS")
    except Exception as exc:
        log_transport_failure_context(log, exc, tx_id, rx_id)
        log.error(str(exc))
    finally:
        if client is not None:
            client.close()
        if own_log:
            log.close()
    return results


def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    parser = build_arg_parser()
    args = parser.parse_args(raw_argv)

    # --- Fixed test case modes ---
    if args.list_cases:
        for case in FIXED_CASES:
            print(f"{case.name}: {case.description}")
        return 0

    if args.run_all_cases:
        results = run_all_fixed_cases(
            expected=args.expect,
            channel=args.channel,
            bitrate=args.bitrate,
            fd=args.fd,
            data_bitrate=args.data_bitrate,
            tx_id=args.tx_id,
            rx_id=args.rx_id,
            timeout_s=args.timeout,
            busy_retries=args.busy_retries,
            busy_wait_s=args.busy_wait,
        )
        return 0 if all(results.values()) else 1

    if args.case:
        passed = run_fixed_case(
            case_name=args.case,
            expected=args.expect,
            channel=args.channel,
            bitrate=args.bitrate,
            fd=args.fd,
            data_bitrate=args.data_bitrate,
            tx_id=args.tx_id,
            rx_id=args.rx_id,
            timeout_s=args.timeout,
            busy_retries=args.busy_retries,
            busy_wait_s=args.busy_wait,
            dry_run=args.dry_run,
        )
        return 0 if passed else 1

    if args.read_all:
        results = read_all_adc_channels(
            channels=ALL_ADC_CHANNELS,
            test_command=0x03,
            channel=args.channel,
            bitrate=args.bitrate,
            fd=args.fd,
            data_bitrate=args.data_bitrate,
            tx_id=args.tx_id,
            rx_id=args.rx_id,
            timeout_s=args.timeout,
            busy_retries=args.busy_retries,
            busy_wait_s=args.busy_wait,
        )
        return 0 if all(r.passed for r in results) else 1

    # --- ADC sampling mode (original behavior) ---
    log = CanUdsLog("Service_31_ADC_CAN")
    client = None
    try:
        args = apply_test_case_defaults(args, log)

        if args.interactive or not raw_argv:
            args = run_interactive_wizard(args, log)

        if not args.adc_channels:
            if args.dry_run:
                args.adc_channels = list(DEFAULT_DEMO_ADC_CHANNELS)
                log.info(
                    "No ADC channels provided, using demo channel Port=0xFF Pin=0x01"
                )
            else:
                parser.error("--adc-channel is required unless using dry-run demo mode")

        request = build_adc_start_request(args.test_command, args.adc_channels)
        log_request_summary(request, args.adc_channels, log)

        if args.dry_run:
            if args.samples > 1:
                log.info(f"Dry-run note: sampling loop would run {args.samples} times")
            log.info("Dry-run enabled, request built successfully and CAN transport was skipped")
            log.result(True, description="ADC StartRoutine request build")
            return 0

        ensure_can_transport_dependencies()

        client = CanIsoTpUdsClient(
            channel=args.channel,
            bitrate=args.bitrate,
            tx_id=args.tx_id,
            rx_id=args.rx_id,
            log=log,
            fd=args.fd,
            data_bitrate=args.data_bitrate,
        )
        client.open()
        samples = collect_adc_samples(
            client=client,
            request=request,
            timeout_s=args.timeout,
            busy_retries=args.busy_retries,
            busy_wait_s=args.busy_wait,
            sample_count=args.samples,
            sample_interval_s=args.sample_interval,
            log=log,
        )
        all_passed = True
        for sample in samples:
            log.info(f"ADC sample {sample.index}/{len(samples)} result summary")
            all_passed = log_response_summary(sample.response, log) and all_passed
        log_adc_statistics(samples, log)
        return 0 if all_passed else 1
    except Exception as exc:
        log_transport_failure_context(log, exc, args.tx_id, args.rx_id)
        log.error(str(exc))
        return 1
    finally:
        if client is not None:
            client.close()
        log.close()


if __name__ == "__main__":
    sys.exit(main())