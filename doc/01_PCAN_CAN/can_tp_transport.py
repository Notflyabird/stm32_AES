#!/usr/bin/env python3
"""
CAN TP Transport Layer (ISO 15765-2) – with TI-style CAN frame logging
========================================================================
Implements ISO 15765-2 Transport Protocol over PCAN via python-can + can-isotp.
Logs individual CAN frames and ISO-TP message summaries matching the
TI pytester log format (ref: pytester_2026_03_12_00_11_31.log).

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
import struct

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
# ISO-TP frame helpers (for logging / simulation)
# ==========================================================================

def _isotp_frame_type(pci_byte: int) -> str:
    """Describe ISO-TP frame type from PCI byte."""
    if (pci_byte & 0xF0) == 0x00:
        return "single frame"
    elif (pci_byte & 0xF0) == 0x10:
        return "first frame"
    elif (pci_byte & 0xF0) == 0x20:
        return "consecutive frame"
    elif (pci_byte & 0xF0) == 0x30:
        return "flow control"
    return f"unknown(0x{pci_byte:02X})"


def _simulate_isotp_tx_frames(log, can_id: int, uds_data: bytes,
                                tx_padding: int = 0xAA):
    """
    Given a UDS payload, simulate and log the CAN frames that would be
    sent as ISO-TP frames.

    This reconstructs the ISO-TP framing from the UDS data for logging
    purposes. The actual transmission is done by can-isotp internally.
    """
    data_len = len(uds_data)
    frame_count = 0

    if data_len <= 7:
        # Single frame: PCI = len, data follows
        pci = data_len & 0x0F
        frame = bytes([pci]) + uds_data
        frame = frame[:8].ljust(8, bytes([tx_padding]))
        log.can_frame("Tx", can_id, frame)
        frame_count = 1
        # ISO-TP message summary
        full_hex = "".join(f"{b:02X}" for b in frame)
        log.isotp_message("single frame", full_hex, data_len,
                          " ".join(f"{b:02X}" for b in uds_data))
    else:
        # First frame: PCI 0x10 | (len >> 8), len & 0xFF, first 6 data bytes
        ff_len = min(6, data_len)
        ff_payload = bytes([0x10 | ((data_len >> 8) & 0x0F), data_len & 0xFF])
        ff_data = ff_payload + uds_data[:ff_len]
        ff_frame = ff_data[:8].ljust(8, bytes([tx_padding]))
        log.can_frame("Tx", can_id, ff_frame)
        frame_count += 1
        # ISO-TP first frame message
        ff_hex = "".join(f"{b:02X}" for b in ff_frame)
        log.isotp_message("first frame", ff_hex, data_len,
                          " ".join(f"{b:02X}" for b in uds_data))

        # Flow control from ECU (will be received later, log on Rx side)

        # Consecutive frames: PCI 0x21-0x2F, each with 7 bytes data
        remaining = uds_data[ff_len:]
        seq = 1
        offset = 0
        while offset < len(remaining):
            seq_byte = 0x20 | ((seq & 0x0F) if seq <= 0x0F else (seq % 0x10))
            chunk = remaining[offset:offset + 7]
            cf_data = bytes([seq_byte]) + chunk
            cf_frame = cf_data[:8].ljust(8, bytes([tx_padding]))
            log.can_frame("Tx", can_id, cf_frame)
            frame_count += 1
            offset += 7
            seq += 1

    return frame_count


def _simulate_isotp_rx_frames(log, can_id: int, response: bytes,
                                rx_padding: int = 0xAA):
    """Log received ISO-TP frames (simulated from assembled response)."""
    data_len = len(response)
    frame_count = 0

    if data_len <= 6:
        # Single frame (6 bytes + 1 PCI = 7, actually 7 bytes max for SF on CAN)
        pci = data_len & 0x0F
        frame = bytes([pci]) + response
        frame = frame[:8].ljust(8, bytes([rx_padding]))
        log.can_frame("Rx", can_id, frame)
        frame_count = 1
        full_hex = "".join(f"{b:02X}" for b in frame) if len(frame) <= 8 else ""
        if full_hex:
            log.isotp_message("single frame", full_hex, data_len,
                              " ".join(f"{b:02X}" for b in response))
    else:
        # First frame: first 6 bytes of response with PCI
        ff_len = min(6, data_len)
        ff_payload = bytes([0x10 | ((data_len >> 8) & 0x0F), data_len & 0xFF])
        ff_data = ff_payload + response[:ff_len]
        ff_frame = ff_data[:8].ljust(8, bytes([rx_padding]))
        log.can_frame("Rx", can_id, ff_frame)
        frame_count += 1

        # Flow control from tester (log on Tx side when sending)

        # Consecutive frames
        remaining = response[ff_len:]
        seq = 1
        offset = 0
        while offset < len(remaining):
            seq_byte = 0x20 | ((seq & 0x0F) if seq <= 0x0F else (seq % 0x10))
            chunk = remaining[offset:offset + 7]
            cf_data = bytes([seq_byte]) + chunk
            cf_frame = cf_data[:8].ljust(8, bytes([rx_padding]))
            log.can_frame("Rx", can_id, cf_frame)
            frame_count += 1
            offset += 7
            seq += 1

    return frame_count


def _log_flow_control(log, can_id: int, blocksize: int = 0, stmin: int = 0,
                       padding: int = 0xAA):
    """Log an ISO-TP flow control frame."""
    fc = bytes([0x30, blocksize & 0xFF, stmin & 0xFF])
    fc_frame = fc[:8].ljust(8, bytes([padding]))
    log.can_frame("Tx" if can_id == CAN_TX_ID else "Rx", can_id, fc_frame)


# ==========================================================================
# CanTpTransport
# ==========================================================================
class CanTpTransport:
    """
    CAN ISO-TP transport layer for UDS diagnostics.
    Call open() before use, close() when done.
    Provides send_uds() for full UDS message exchange over CAN.

    Logs CAN frames and ISO-TP messages in TI pytester format when
    a logger is provided.
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

        # ISO-TP tx_padding (used for frame simulation)
        self._tx_padding = 0xAA

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

        # Clear any residual PCAN channel state
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
                nom_brp=10, nom_tseg1=12, nom_tseg2=3, nom_sjw=1,
                data_brp=2, data_tseg1=5, data_tseg2=2, data_sjw=1,
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
        self._tx_padding = 0xAA  # FBL uses 0xAA as CAN frame padding
        isotp_params = {
            "stmin": ISO_TP_STMIN,
            "blocksize": ISO_TP_BLOCKSIZE,
            "wftmax": ISO_TP_WFTMAX,
            "rx_flowcontrol_timeout": 1000,
            "rx_consecutive_frame_timeout": 1000,
            "tx_data_length": 8,
            "tx_padding": self._tx_padding,
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
    def send_uds(self, uds_data: bytes, expect_response: bool = True,
                 timeout_ms: int = None) -> bytes:
        """
        Send a complete UDS request and return the complete UDS response.

        Logs CAN frames and ISO-TP message summaries in TI format.
        """
        from can_uds_log import bytes_to_hex

        if self._stack is None:
            raise RuntimeError("CAN TP transport is not open")

        self._last_isotp_error = None

        # Log simulated CAN frames for the TX path
        _simulate_isotp_tx_frames(self._log, self.tx_id, uds_data,
                                   self._tx_padding)

        # Send via can-isotp
        self._stack.send(uds_data)

        if not expect_response:
            try:
                return self._receive_with_timeout(timeout_ms)
            except TimeoutError:
                self._info("No response received (suppress positive response – expected)")
                return bytes()

        return self._receive_with_timeout(timeout_ms)

    # ------------------------------------------------------------------
    # Private – receiving
    # ------------------------------------------------------------------
    def _receive_with_timeout(self, timeout_ms: int = None) -> bytes:
        """Wait for UDS response with CAN frame logging."""
        from can_uds_log import bytes_to_hex

        if timeout_ms is None:
            timeout_ms = P2_TIMEOUT_MS

        deadline = time.monotonic() + timeout_ms / 1000.0

        while time.monotonic() < deadline:
            self._stack.process()
            if self._last_isotp_error is not None:
                raise RuntimeError(f"ISO-TP transport error: {self._last_isotp_error}")
            if self._stack.available():
                response = bytes(self._stack.recv())

                # Log simulated CAN frames for the RX path
                _simulate_isotp_rx_frames(self._log, self.rx_id, response,
                                           self._tx_padding)

                # Check for NRC 0x78 (ResponsePending)
                if (len(response) >= 3
                        and response[0] == 0x7F
                        and response[2] == 0x78):
                    self._info("NRC 0x78 – ResponsePending, waiting P2*...")
                    # Log flow control before extended wait
                    _log_flow_control(self._log, self.tx_id, ISO_TP_BLOCKSIZE, ISO_TP_STMIN,
                                      self._tx_padding)
                    return self._receive_extended()
                return response
            time.sleep(0.002)

        raise TimeoutError(f"CAN TP: No response from ECU (timeout={timeout_ms}ms)")

    def _receive_extended(self) -> bytes:
        """Wait up to P2* timeout for final response after NRC 0x78."""
        from can_uds_log import bytes_to_hex

        deadline = time.monotonic() + P2_STAR_TIMEOUT_MS / 1000.0
        while time.monotonic() < deadline:
            self._stack.process()
            if self._last_isotp_error is not None:
                raise RuntimeError(f"ISO-TP transport error: {self._last_isotp_error}")
            if self._stack.available():
                response = bytes(self._stack.recv())

                # Log simulated CAN frames for the RX path
                _simulate_isotp_rx_frames(self._log, self.rx_id, response,
                                           self._tx_padding)

                # Handle nested ResponsePending
                if (len(response) >= 3
                        and response[0] == 0x7F
                        and response[2] == 0x78):
                    self._info("NRC 0x78 (nested) – continuing wait...")
                    continue
                return response
            time.sleep(0.002)

        raise TimeoutError("CAN TP: Timeout waiting for final response after NRC 0x78")

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
