#!/usr/bin/env python3
"""
Thin entry point for fixed ADC test cases.
All logic lives in Service_31_ADC_CAN.py — this file just provides CLI compatibility.

Examples:
  python Service_31_ADC_CAN_Cases.py --dry-run
  python Service_31_ADC_CAN_Cases.py --case a043_03_00_07
  python Service_31_ADC_CAN_Cases.py --list-cases
  python Service_31_ADC_CAN_Cases.py --run-all
"""

import argparse
import sys

from Service_31_ADC_CAN import (
    DEFAULT_RX_ID,
    DEFAULT_TX_ID,
    DEFAULT_CASE_NAME,
    EXPECTED_POSITIVE,
    EXPECTED_RESPONSE_MAP,
    FIXED_CASES,
    FIXED_CASES_BY_NAME,
    run_all_fixed_cases,
    run_fixed_case,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run fixed CAN ADC routine test cases for RID 0xA043"
    )
    parser.add_argument("--list-cases", action="store_true",
                        help="Print available fixed test cases and exit")
    parser.add_argument("--run-all", action="store_true",
                        help="Run all built-in fixed cases sequentially")
    parser.add_argument("--case", choices=sorted(FIXED_CASES_BY_NAME), default=DEFAULT_CASE_NAME,
                        help="Select a fixed test case")
    parser.add_argument("--expect", choices=sorted(EXPECTED_RESPONSE_MAP), default=EXPECTED_POSITIVE,
                        help="Expected response type for verdict, default: positive")
    parser.add_argument("--channel", default="PCAN_USBBUS1")
    parser.add_argument("--bitrate", type=int, default=500000)
    parser.add_argument("--no-fd", dest="fd", action="store_false", default=True)
    parser.add_argument("--data-bitrate", type=int, default=5_000_000)
    parser.add_argument("--tx-id", type=lambda v: int(v, 0), default=DEFAULT_TX_ID)
    parser.add_argument("--rx-id", type=lambda v: int(v, 0), default=DEFAULT_RX_ID)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--busy-retries", type=int, default=3)
    parser.add_argument("--busy-wait", type=float, default=0.2)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.list_cases:
        for case in FIXED_CASES:
            print(f"{case.name}: {case.description}")
        return 0

    if args.run_all:
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


if __name__ == "__main__":
    sys.exit(main())