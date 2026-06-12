#!/usr/bin/env python3
"""
Service 0x31 RoutineControl - IO pre-enable + PWM output (CAN)
===============================================================

Flow:
  1) Send IO set-level request(s) via RID 0xA044, test_cmd=0x04
     Request format (single IO each frame):
       31 01 A0 44 04 <port> <pin> <value>

     Example (from user):
       31 01 A0 44 04 21 0D 00   -> P33.13 = 0
       31 01 A0 44 04 21 0F 00   -> P33.15 = 0
       31 01 A0 44 04 22 01 01   -> P34.1  = 1

  2) Send PWM request via RID 0xA045 (reuse logic from Service_31_PWM_CAN.py).

Notes:
  - This script adds pre-condition IO control before PWM output.
    - Blower channels use P25.x PWM with enable IO prerequisites:
            P25.0 -> DOH_F_BLW_EN (P25.11)
            P25.1 -> DOH_R_BLW_EN (P25.10)
            P25.2 -> DOH_F_BLW_EN + DOH_R_BLW_EN
"""

from __future__ import annotations

import argparse
import sys
import textwrap
from dataclasses import dataclass
from typing import Iterable, Sequence

try:
    from Service_31_ADC_CAN import (
        CanIsoTpUdsClient,
        CanUdsLog,
        DEFAULT_RX_ID,
        DEFAULT_TX_ID,
        ensure_can_transport_dependencies,
        log_can_exchange_context,
        log_transport_failure_context,
    )
    from Service_31_PWM_CAN import (
        PwmChannel,
        build_pwm_start_request,
        run_pwm_routine,
    )
except ImportError as _e:
    raise SystemExit(
        f"Import failed: {_e}\n"
        "Ensure Service_31_ADC_CAN.py and Service_31_PWM_CAN.py are in the same directory."
    ) from _e


SID_ROUTINE_CONTROL = 0x31
SUBFUNCTION_START_ROUTINE = 0x01
POSITIVE_SID = 0x71

ROUTINE_IO_TEST_H = 0xA0
ROUTINE_IO_TEST_L = 0x44
IO_TEST_COMMAND_SET_PIN_LEVEL = 0x04


@dataclass(frozen=True)
class IoPinConfig:
    port_id: int
    pin_id: int
    value: int
    name: str

    def validate(self) -> None:
        if not (0 <= self.port_id <= 0xFF):
            raise ValueError(f"{self.name} port_id out of range: 0x{self.port_id:X}")
        if not (0 <= self.pin_id <= 0xFF):
            raise ValueError(f"{self.name} pin_id out of range: 0x{self.pin_id:X}")
        if self.value not in (0, 1):
            raise ValueError(f"{self.name} value must be 0 or 1, got {self.value}")


# IO prerequisites
IO_DOH_HSD_EN = IoPinConfig(0x0F, 0x0D, 1, "DOH_HSD_EN(P15.13)")
IO_DOH_F_BLW_EN = IoPinConfig(0x19, 0x0B, 1, "DOH_F_BLW_EN(P25.11)")
IO_DOH_R_BLW_EN = IoPinConfig(0x19, 0x0A, 1, "DOH_R_BLW_EN(P25.10)")


# User-provided PWM targets
PRESET_PWM_TARGETS: tuple[PwmChannel, ...] = (
    PwmChannel(0x01, 13, 20, 50),
    PwmChannel(0x0D, 11, 200, 50),
    PwmChannel(0x0D, 13, 200, 50),
    PwmChannel(0x0D, 14, 200, 50),
    PwmChannel(0x0D, 15, 100, 50),
    PwmChannel(0x0E, 12, 200, 50),
    PwmChannel(0x0E, 13, 200, 50),
    PwmChannel(0x0E, 14, 200, 50),
    PwmChannel(0x0E, 15, 200, 50),
    PwmChannel(0x1F, 6, 200, 50),
    PwmChannel(0x19, 0, 1000, 50),
    PwmChannel(0x19, 1, 1000, 50),
    PwmChannel(0x19, 2, 1000, 50),
    PwmChannel(0x19, 9, 200, 50),
    PwmChannel(0x0D, 4, 1000, 50),
    PwmChannel(0x0D, 6, 200, 20),
)


def bytes_to_hex(data: Sequence[int]) -> str:
    return " ".join(f"{value:02X}" for value in data)


def parse_pwm_channel_spec(spec: str) -> PwmChannel:
    parts = spec.split(":")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(
            f"Invalid spec '{spec}'. Expected PORT:PIN:FREQ:DUTY"
        )
    try:
        port = int(parts[0], 0)
        pin = int(parts[1], 0)
        freq = int(parts[2], 0)
        duty = int(parts[3], 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return PwmChannel(port, pin, freq, duty)


def build_io_set_level_request(io_cfg: IoPinConfig) -> bytes:
    io_cfg.validate()
    return bytes([
        SID_ROUTINE_CONTROL,
        SUBFUNCTION_START_ROUTINE,
        ROUTINE_IO_TEST_H,
        ROUTINE_IO_TEST_L,
        IO_TEST_COMMAND_SET_PIN_LEVEL,
        io_cfg.port_id,
        io_cfg.pin_id,
        io_cfg.value,
    ])


def _is_blower_channel(ch: PwmChannel) -> bool:
    return ch.port_id == 0x19 and ch.pin_id in (0, 1, 2)


def _is_bts_hsd_channel(ch: PwmChannel) -> bool:
    return (
        (ch.port_id == 0x01 and ch.pin_id == 13)
        or (ch.port_id == 0x0D and ch.pin_id in (4, 6, 11, 13, 14, 15))
        or (ch.port_id == 0x0E and ch.pin_id in (12, 13, 14, 15))
        or (ch.port_id == 0x1F and ch.pin_id == 6)
    )


def collect_required_io(channels: Iterable[PwmChannel]) -> list[IoPinConfig]:
    needs_hsd = False
    needs_f_blw_en = False
    needs_r_blw_en = False
    for ch in channels:
        if _is_bts_hsd_channel(ch):
            needs_hsd = True
        if ch.port_id == 0x19 and ch.pin_id == 0:
            needs_f_blw_en = True
        elif ch.port_id == 0x19 and ch.pin_id == 1:
            needs_r_blw_en = True
        elif ch.port_id == 0x19 and ch.pin_id == 2:
            needs_f_blw_en = True
            needs_r_blw_en = True

    req: list[IoPinConfig] = []
    if needs_hsd:
        req.append(IO_DOH_HSD_EN)
    if needs_f_blw_en:
        req.append(IO_DOH_F_BLW_EN)
    if needs_r_blw_en:
        req.append(IO_DOH_R_BLW_EN)
    return req


def _io_for_channel(ch: PwmChannel) -> list[IoPinConfig]:
    req: list[IoPinConfig] = []
    if _is_bts_hsd_channel(ch):
        req.append(IO_DOH_HSD_EN)
    if ch.port_id == 0x19 and ch.pin_id == 0:
        req.append(IO_DOH_F_BLW_EN)
    elif ch.port_id == 0x19 and ch.pin_id == 1:
        req.append(IO_DOH_R_BLW_EN)
    elif ch.port_id == 0x19 and ch.pin_id == 2:
        req.append(IO_DOH_F_BLW_EN)
        req.append(IO_DOH_R_BLW_EN)
    return req


def send_io_preconditions(
    io_list: Sequence[IoPinConfig],
    can_channel: str,
    bitrate: int,
    fd: bool,
    data_bitrate: int,
    tx_id: int,
    rx_id: int,
    timeout_s: float,
    log: CanUdsLog,
    dry_run: bool,
) -> bool:
    if not io_list:
        log.info("No IO preconditions required for selected PWM channels")
        return True

    log.info("IO pre-enable step before PWM:")
    for cfg in io_list:
        req = build_io_set_level_request(cfg)
        log.info(f"  {cfg.name:<24} -> {cfg.value} | {bytes_to_hex(req)}")

    if dry_run:
        log.info("[DRY-RUN] IO pre-enable requests not transmitted")
        return True

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
            tx_data_length=16,
        )
        client.open()

        for cfg in io_list:
            req = build_io_set_level_request(cfg)
            log.start_test(f"0x31 0x01 0xA044 SetPinLevel {cfg.name}={cfg.value}")
            log_can_exchange_context(log, tx_id, rx_id, timeout_s)
            log.tx(bytes_to_hex(req), f"CAN 0x{tx_id:X} RoutineControl IO")
            resp = client.send_uds(req, timeout_s)
            log.rx(bytes_to_hex(resp), f"CAN 0x{rx_id:X}")

            if not (len(resp) >= 4 and resp[0] == POSITIVE_SID and resp[1] == 0x01 and resp[2] == 0xA0 and resp[3] == 0x44):
                log.result(False, description=f"IO pre-enable {cfg.name}")
                return False

            log.result(True, description=f"IO pre-enable {cfg.name}")

        return True
    except Exception as exc:
        log_transport_failure_context(log, exc, tx_id, rx_id)
        log.error(f"IO pre-enable failed: {exc}")
        return False
    finally:
        if client is not None:
            client.close()


def log_command_summary(
    io_list: Sequence[IoPinConfig],
    channels: Sequence[PwmChannel],
    test_command: int,
    log: CanUdsLog,
) -> None:
    log.info("=" * 72)
    log.info("Command summary (per channel):")
    log.info("Format: <Channel> <Freq> <Duty> <Type> <Command> <Note>")

    if not channels:
        log.info("(none)")
        return

    for ch in channels:
        ch_name = f"P{ch.port_id}.{ch.pin_id}"
        io_for_ch = _io_for_channel(ch)
        for cfg in io_for_ch:
            io_req = build_io_set_level_request(cfg)
            log.info(
                f"{ch_name} {ch.frequency} {ch.duty} IO {bytes_to_hex(io_req)} {cfg.name}=1"
            )

        pwm_req = build_pwm_start_request([ch], test_command)
        log.info(
            f"{ch_name} {ch.frequency} {ch.duty} PWM {bytes_to_hex(pwm_req)} {ch_name} PWM"
        )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="PWM with IO pre-enable (A044 then A045)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            PWM channel format: PORT:PIN:FREQ:DUTY

            Examples:
              # Run all preset channels from requirement list
              python Service_31_PWM_IO_CAN.py --run-preset

              # Run one channel, auto pre-enable required IO
              python Service_31_PWM_IO_CAN.py --pwm-channel 14:13:200:50

              # Only preview A044 + A045 payloads
              python Service_31_PWM_IO_CAN.py --run-preset --dry-run
        """),
    )

    parser.add_argument(
        "--run-preset",
        action="store_true",
        help="Use built-in 13 PWM channels from current requirement list",
    )
    parser.add_argument(
        "--pwm-channel",
        metavar="PORT:PIN:FREQ:DUTY",
        action="append",
        dest="pwm_channels",
        type=parse_pwm_channel_spec,
        help="PWM channel spec (repeatable)",
    )
    parser.add_argument(
        "--skip-io",
        action="store_true",
        help="Skip A044 IO pre-enable step (not recommended)",
    )

    parser.add_argument("--test-command", default=0x01, type=lambda x: int(x, 0))
    parser.add_argument("--channel", default="PCAN_USBBUS1")
    parser.add_argument("--bitrate", default=500_000, type=int)
    parser.add_argument("--no-fd", dest="fd", action="store_false", default=True)
    parser.add_argument("--data-bitrate", default=5_000_000, type=int)
    parser.add_argument("--tx-id", default=DEFAULT_TX_ID, type=lambda x: int(x, 0))
    parser.add_argument("--rx-id", default=DEFAULT_RX_ID, type=lambda x: int(x, 0))
    parser.add_argument("--timeout", default=2.0, type=float)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--tx-data-length", default=16, type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])

    channels: list[PwmChannel] = []
    if args.run_preset:
        channels.extend(PRESET_PWM_TARGETS)
    if args.pwm_channels:
        channels.extend(args.pwm_channels)

    if not channels:
        parser.error("Specify --run-preset or at least one --pwm-channel")

    log = CanUdsLog("Service_31_PWM_IO_CAN")
    req_io: list[IoPinConfig] = []
    try:
        for ch in channels:
            ch.validate()

        req_io = collect_required_io(channels)
        has_blower = any(_is_blower_channel(ch) for ch in channels)
        if has_blower:
            log.info(
                "Blower channels detected (P25.x): using IO pre-enable mapping "
                "P25.0->P25.11, P25.1->P25.10, P25.2->both enables."
            )

        if not args.skip_io:
            io_ok = send_io_preconditions(
                io_list=req_io,
                can_channel=args.channel,
                bitrate=args.bitrate,
                fd=args.fd,
                data_bitrate=args.data_bitrate,
                tx_id=args.tx_id,
                rx_id=args.rx_id,
                timeout_s=args.timeout,
                log=log,
                dry_run=args.dry_run,
            )
            if not io_ok:
                log_command_summary(req_io, channels, args.test_command, log)
                return 1
        else:
            log.info("Skipping IO pre-enable by user option --skip-io")

        log.info(f"PWM send mode: one-by-one ({len(channels)} channel(s))")
        pwm_results = []
        total = len(channels)
        for idx, ch in enumerate(channels, 1):
            log.info(
                f"PWM channel {idx}/{total}: P{ch.port_id}.{ch.pin_id} "
                f"freq={ch.frequency}Hz duty={ch.duty}%"
            )
            one_results = run_pwm_routine(
                channels=[ch],
                test_command=args.test_command,
                can_channel=args.channel,
                bitrate=args.bitrate,
                fd=args.fd,
                data_bitrate=args.data_bitrate,
                tx_id=args.tx_id,
                rx_id=args.rx_id,
                timeout_s=args.timeout,
                dry_run=args.dry_run,
                log=log,
                tx_data_length=args.tx_data_length,
            )
            pwm_results.extend(one_results)

        if args.dry_run:
            log_command_summary(req_io, channels, args.test_command, log)
            return 0

        pass_count = sum(1 for r in pwm_results if r.passed)
        total = len(pwm_results)
        log.info(f"PWM summary: {pass_count}/{total} PASS")
        log_command_summary(req_io, channels, args.test_command, log)
        return 0 if pass_count == total else 1
    finally:
        log.close()


if __name__ == "__main__":
    sys.exit(main())
