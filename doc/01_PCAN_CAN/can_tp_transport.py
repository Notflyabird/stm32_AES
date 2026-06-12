#!/usr/bin/env python3
"""
CAN TP Transport Layer (ISO 15765-2)
=====================================
Implements ISO 15765-2 Transport Protocol over PCAN via python-can + can-isotp.

UDS requests/replies are transported via ISO-TP (ISO 15765-2) over CAN 2.0.
Handles single-frame, multi-frame (FF/CF), and flow-control automatically.

Usage:
    from can_tp_transport import CanTpTransport
    tp = CanTpTransport(logger=log)
    tp.open()
    resp = tp.send_uds(bytes([0x10, 0x02]))
    tp.close()
"""

import os
import sys
import time

from can_tp_config import (
    PCAN_CHANNEL, CAN_BITRATE, CAN_FD,
    CAN_TX_ID, CAN_RX_ID,
    P2_TIMEOUT_MS, P2_STAR_TIMEOUT_MS,
    ISO_TP_STMIN, ISO_TP_BLOCKSIZE, ISO_TP_WFTMAX,
)


def _ensure_dependencies():
    """Check that python-can and can-isotp are installed."""
    missing = []
    for mod in ("can", "isotp"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        raise RuntimeError(
            "Missing CAN dependencies. Install with: pip install python-can can-isotp "
            f"(missing: {', '.join(missing)})"
        )


# ==========================================================================
# CanTpTransport
# ==========================================================================
class CanTpTransport:
    """
    CAN ISO-TP transport layer for UDS diagnostics.
    Call open() before use, close() when done.
    Provides send_uds() for full UDS message exchange over CAN.
    """

    def __init__(self, logger=None):
        self._bus = None
        self._stack = None
        self._log = logger
        self._is_open = False
        self._last_isotp_error = None

        # CAN config
        self.channel = PCAN_CHANNEL
        self.bitrate = CAN_BITRATE
        self.fd = CAN_FD
        self.tx_id = CAN_TX_ID
        self.rx_id = CAN_RX_ID

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def open(self):
        """Initialize CAN bus and ISO-TP stack."""
        _ensure_dependencies()
        import can
        import isotp

        mode_str = "CAN-FD" if self.fd else "CAN 2.0"
        self._info(f"Opening PCAN [{mode_str}] channel={self.channel} "
                   f"bitrate={self.bitrate} tx_id=0x{self.tx_id:X} rx_id=0x{self.rx_id:X}")

        # Clear any residual PCAN channel state to avoid Bus-Heavy errors
        try:
            from can.interfaces.pcan.basic import PCANBasic, PCAN_USBBUS1, PCAN_USBBUS2
            channel_map = {"PCAN_USBBUS1": PCAN_USBBUS1, "PCAN_USBBUS2": PCAN_USBBUS2}
            pcan_handle = channel_map.get(self.channel, PCAN_USBBUS1)
            pcan = PCANBasic()
            pcan.Uninitialize(pcan_handle)
            del pcan
            time.sleep(0.1)
        except Exception:
            pass

        # Open CAN bus
        if self.fd:
            self._bus = can.Bus(
                interface="pcan", channel=self.channel, fd=True,
                f_clock_mhz=80,
                nom_brp=10, nom_tseg1=12, nom_tseg2=3, nom_sjw=1,   # 500 kbps
                data_brp=2, data_tseg1=5, data_tseg2=2, data_sjw=1,  # 5 Mbps
            )
        else:
            self._bus = can.Bus(
                interface="pcan", channel=self.channel,
                bitrate=self.bitrate,
            )

        # ISO-TP address
        address = isotp.Address(
            isotp.AddressingMode.Normal_11bits,
            txid=self.tx_id,
            rxid=self.rx_id,
        )

        # ISO-TP parameters
        isotp_params = {
            "stmin": ISO_TP_STMIN,
            "blocksize": ISO_TP_BLOCKSIZE,
            "wftmax": ISO_TP_WFTMAX,
            "rx_flowcontrol_timeout": 1000,
            "rx_consecutive_frame_timeout": 1000,
            "tx_data_length": 8,
            "tx_padding": 0xAA,         # FBL uses 0xAA as CAN frame padding
        }

        self._stack = isotp.CanStack(
            bus=self._bus,
            address=address,
            error_handler=self._handle_isotp_error,
            params=isotp_params,
        )

        self._is_open = True
        self._info(f"CAN TP transport open  "
                   f"(tx=0x{self.tx_id:X} rx=0x{self.rx_id:X} {mode_str})")

    def close(self):
        if self._is_open:
            try:
                if self._bus is not None:
                    self._bus.shutdown()
            finally:
                self._bus = None
                self._stack = None
                self._is_open = False
                self._info("CAN TP transport closed")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def send_uds(self, uds_data: bytes, expect_response: bool = True) -> bytes:
        """
        Send a complete UDS request and return the complete UDS response.
        Handles ISO-TP SF / FF+CF framing automatically via can-isotp.

        expect_response: set to False for suppress-positive-response requests.
                         Returns empty bytes on timeout instead of raising.
        """
        if self._stack is None:
            raise RuntimeError("CAN TP transport is not open")

        self._last_isotp_error = None

        # Send request
        self._stack.send(uds_data)

        if not expect_response:
            try:
                return self._receive_with_timeout()
            except TimeoutError:
                self._info("No response received (suppress positive response – expected)")
                return bytes()

        return self._receive_with_timeout()

    # ------------------------------------------------------------------
    # Private – receiving
    # ------------------------------------------------------------------
    def _receive_with_timeout(self, timeout_ms: int = None) -> bytes:
        """
        Wait for UDS response with timeout handling.
        Handles NRC 0x78 ResponsePending automatically.
        """
        if timeout_ms is None:
            timeout_ms = P2_TIMEOUT_MS

        deadline = time.monotonic() + timeout_ms / 1000.0

        # Phase 1: Wait for first frame (P2 timeout)
        while time.monotonic() < deadline:
            self._stack.process()
            if self._last_isotp_error is not None:
                raise RuntimeError(f"ISO-TP transport error: {self._last_isotp_error}")
            if self._stack.available():
                response = bytes(self._stack.recv())
                # Check for NRC 0x78 (ResponsePending)
                if (len(response) >= 3
                        and response[0] == 0x7F
                        and response[2] == 0x78):
                    self._info("NRC 0x78 – ResponsePending, waiting P2*...")
                    return self._receive_extended()
                return response
            time.sleep(0.002)

        raise TimeoutError(f"CAN TP: No response from ECU (timeout={timeout_ms}ms)")

    def _receive_extended(self) -> bytes:
        """Wait up to P2* timeout for final response after NRC 0x78."""
        deadline = time.monotonic() + P2_STAR_TIMEOUT_MS / 1000.0
        while time.monotonic() < deadline:
            self._stack.process()
            if self._last_isotp_error is not None:
                raise RuntimeError(f"ISO-TP transport error: {self._last_isotp_error}")
            if self._stack.available():
                response = bytes(self._stack.recv())
                # Handle nested ResponsePending
                if (len(response) >= 3
                        and response[0] == 0x7F
                        and response[2] == 0x78):
                    self._info("NRC 0x78 (nested) – continuing wait...")
                    continue
                return response
            time.sleep(0.002)

        raise TimeoutError(f"CAN TP: Timeout waiting for final response after NRC 0x78")

    def _handle_isotp_error(self, error: Exception) -> None:
        self._last_isotp_error = error

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _info(self, msg: str):
        if self._log:
            self._log.info(msg)
        else:
            print(f"[INFO] {msg}")
