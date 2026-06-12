#!/usr/bin/env python3
"""
Service 0x31 RoutineControl - ADC extracted channel set (CAN)
==============================================================

This script reuses Service_31_ADC_CAN.py transport/protocol logic and runs a
curated subset of ADC channels extracted from a measured log.

Usage examples:
  python Service_31_ADC_CAN_Extracted.py --preset all
  python Service_31_ADC_CAN_Extracted.py --preset port
  python Service_31_ADC_CAN_Extracted.py --preset an
"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

try:
    from Service_31_ADC_CAN import (
        CanUdsLog,
        DEFAULT_RX_ID,
        DEFAULT_TX_ID,
        channel_label,
        read_all_adc_channels,
    )
except ImportError as _e:
    raise SystemExit(
        f"Cannot import from Service_31_ADC_CAN.py: {_e}\n"
        "Ensure this script is in the same directory as Service_31_ADC_CAN.py"
    ) from _e


def _int_arg(value: str) -> int:
    return int(value, 0)


# Extracted port/pin channels from user-provided summary
EXTRACTED_PORT_CHANNELS: tuple[tuple[int, int], ...] = (
    # P0.x
    (0x00, 8), (0x00, 9), (0x00, 10),
    # P33.x
    (0x21, 4), (0x21, 5),
    # P34.x
    (0x22, 2), (0x22, 3), (0x22, 4),
    # P40.x
    (0x28, 6), (0x28, 9), (0x28, 10), (0x28, 11), (0x28, 12), (0x28, 15),
    # P41.x
    (0x29, 0), (0x29, 1), (0x29, 2), (0x29, 3),
)

# Extracted AN channels from user-provided summary and mapping notes
EXTRACTED_AN_CHANNELS: tuple[tuple[int, int], ...] = (
    (0xFF, 8), (0xFF, 9), (0xFF, 10), (0xFF, 11),
    (0xFF, 13), (0xFF, 14), (0xFF, 15),
    (0xFF, 20), (0xFF, 21), (0xFF, 22),
    (0xFF, 35), (0xFF, 38),
    (0xFF, 44),
    (0xFF, 56), (0xFF, 57),
    (0xFF, 66),
)

# Keep order stable and remove duplicates while preserving first appearance
EXTRACTED_ALL_CHANNELS: tuple[tuple[int, int], ...] = tuple(
    dict.fromkeys(EXTRACTED_PORT_CHANNELS + EXTRACTED_AN_CHANNELS)
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run extracted ADC channel subset over CAN (reuses Service_31_ADC_CAN.py)",
    )
    parser.add_argument(
        "--preset",
        choices=("all", "port", "an"),
        default="all",
        help="Which extracted channel set to run (default: all)",
    )
    parser.add_argument("--channel", default="PCAN_USBBUS1", help="PCAN channel")
    parser.add_argument("--bitrate", type=int, default=500_000, help="CAN nominal bitrate")
    parser.add_argument("--no-fd", dest="fd", action="store_false", default=True,
                        help="Use classic CAN instead of CAN-FD")
    parser.add_argument("--data-bitrate", type=int, default=5_000_000, help="CAN FD data bitrate")
    parser.add_argument("--tx-id", type=_int_arg, default=DEFAULT_TX_ID, help="Tester TX CAN ID")
    parser.add_argument("--rx-id", type=_int_arg, default=DEFAULT_RX_ID, help="ECU RX CAN ID")
    parser.add_argument("--timeout", type=float, default=2.0, help="Per-channel timeout seconds")
    parser.add_argument("--busy-retries", type=int, default=3, help="Busy-repeat retries")
    parser.add_argument("--busy-wait", type=float, default=0.2, help="Busy-repeat wait seconds")
    parser.add_argument("--test-command", type=_int_arg, default=0x03,
                        help="Routine test command byte (default: 0x03)")
    parser.add_argument(
        "--simple-summary",
        action="store_true",
        help="Print compact table rows: Channel/Status/Value for copy-paste",
    )
    return parser


def _pick_channels(preset: str) -> tuple[tuple[int, int], ...]:
    if preset == "port":
        return EXTRACTED_PORT_CHANNELS
    if preset == "an":
        return EXTRACTED_AN_CHANNELS
    return EXTRACTED_ALL_CHANNELS


def _build_single_channel_diag_cmd(test_command: int, port_id: int, pin_id: int) -> str:
    # Request format for single channel read in this script:
    # 31 01 A0 43 <test_cmd> 01 <port> <pin>
    return f"31 01 A0 43 {test_command & 0xFF:02X} 01 {port_id & 0xFF:02X} {pin_id & 0xFF:02X}"


def _print_simple_summary(results: Sequence[object]) -> None:
    """Print compact rows for test sheets: Channel, Status, Value."""
    print("Channel\tStatus\tValue")
    for r in results:
        lbl = channel_label(r.port_id, r.pin_id)
        status = "PASS" if r.passed else "FAIL"
        if r.value is None:
            value = "N/A"
        else:
            value = f"0x{r.value:04X} ({r.value})"
        print(f"{lbl}\t{status}\t{value}")


def _log_summary_with_diag_cmd(results: Sequence[object], test_command: int, log: CanUdsLog) -> None:
    log.info("=" * 72)
    log.info("Extracted summary with diagnostic command:")
    log.info(f"{'Channel':<10} {'Status':<8} {'Value':<14} Diagnostic Command")
    for r in results:
        lbl = channel_label(r.port_id, r.pin_id)
        status = "PASS" if r.passed else "FAIL"
        value = f"0x{r.value:04X} ({r.value})" if r.value is not None else "N/A"
        cmd = _build_single_channel_diag_cmd(test_command, r.port_id, r.pin_id)
        log.info(f"{lbl:<10} {status:<8} {value:<14} {cmd}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])

    channels = _pick_channels(args.preset)
    log = CanUdsLog("Service_31_ADC_CAN_Extracted")
    try:
        log.info(f"Preset: {args.preset}")
        log.info(f"Total extracted channels: {len(channels)}")
        for idx, (port_id, pin_id) in enumerate(channels, 1):
            log.info(f"[{idx:02d}] {channel_label(port_id, pin_id)}")

        results = read_all_adc_channels(
            channels=channels,
            test_command=args.test_command,
            channel=args.channel,
            bitrate=args.bitrate,
            fd=args.fd,
            data_bitrate=args.data_bitrate,
            tx_id=args.tx_id,
            rx_id=args.rx_id,
            timeout_s=args.timeout,
            busy_retries=args.busy_retries,
            busy_wait_s=args.busy_wait,
            log=log,
        )
        _log_summary_with_diag_cmd(results, args.test_command, log)
        if args.simple_summary:
            _print_simple_summary(results)
        return 0 if all(r.passed for r in results) else 1
    finally:
        log.close()


if __name__ == "__main__":
    sys.exit(main())
