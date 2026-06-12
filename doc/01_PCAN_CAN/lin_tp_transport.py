#!/usr/bin/env python3
"""
LIN TP Transport Layer
======================
Implements ISO 17987 / LIN 2.x Transport Protocol over PCAN-USB Pro FD.

Frame layout on LIN bus (8 bytes):
  [NAD][PCI ...][Data ...][Padding 0xFF]

PCI types:
  SF (Single Frame)   : PCI = 0x0N  (N = data length, 1-6)
  FF (First Frame)    : PCI = [0x1H][0xLL]  (HL = total UDS length)  → 5 data bytes
  CF (Consecutive F.) : PCI = [0x2N]  (N = sequence 1..F,0,..)      → 6 data bytes

No Flow-Control in LIN TP direction master→slave.
Master polls slave response by sending 0x3D subscriber headers.
"""

import os
import sys
import time

from lin_tp_config import (
    PLIN_API_INCLUDE, PLIN_DLL_PATH,
    TARGET_CHANNEL, LIN_BAUD_RATE, NAD,
    LIN_MASTER_REQ_PROT, LIN_SLAVE_RESP_PROT, LIN_SLAVE_RESPONSE_ID,
    P2_TIMEOUT_MS, P2_STAR_TIMEOUT_MS, S3_TIMEOUT_MS, INTER_FRAME_DELAY_S,
)

# --------------------------------------------------------------------------
# Load PEAK PLIN-API
# --------------------------------------------------------------------------
if PLIN_API_INCLUDE not in sys.path:
    sys.path.insert(0, PLIN_API_INCLUDE)
os.environ["PATH"] = os.path.dirname(PLIN_DLL_PATH) + os.pathsep + os.environ["PATH"]

from PLinApi import (
    PLinApi, TLINMsg, TLINRcvMsg, TLINFrameEntry,
    HLINCLIENT, HLINHW,
    TLIN_ERROR_OK, TLIN_ERROR_RCVQUEUE_EMPTY,
    TLIN_HARDWAREMODE_MASTER,
    TLIN_CHECKSUMTYPE_CLASSIC,
    TLIN_DIRECTION_PUBLISHER, TLIN_DIRECTION_SUBSCRIBER,
    TLIN_MSGTYPE_STANDARD,
    TLIN_HARDWAREPARAM_CHANNEL_NUMBER,
)
from ctypes import c_ubyte, c_ushort, c_ulong, c_int


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _bytes_to_hex(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


def _make_lin_frame(nad: int, payload: bytes) -> TLINMsg:
    """Pack NAD + payload into a padded 8-byte TLINMsg on ID 0x3C."""
    msg = TLINMsg()
    msg.FrameId      = LIN_MASTER_REQ_PROT
    msg.Length       = c_ubyte(8)
    msg.Direction    = TLIN_DIRECTION_PUBLISHER
    msg.ChecksumType = TLIN_CHECKSUMTYPE_CLASSIC
    raw = bytes([nad]) + payload
    raw = raw[:8] + bytes([0xFF] * (8 - len(raw)))  # pad
    for i, b in enumerate(raw[:8]):
        msg.Data[i] = b
    return msg


# ==========================================================================
# LinTpTransport
# ==========================================================================
class LinTpTransport:
    """
    LIN TP transport layer.  Call open() before use, close() when done.
    Provides send_uds() / receive_uds() for full UDS message exchange.
    """

    def __init__(self, logger=None):
        self._plin    = PLinApi()
        self._hClient = HLINCLIENT(0)
        self._hHw     = None
        self._log     = logger  # optional LinUdsLog instance
        self._is_open = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def open(self):
        """Initialize hardware and configure receive filter for 0x3D."""
        if not self._plin.isLoaded():
            raise RuntimeError(f"PLinApi.dll could not be loaded from {PLIN_DLL_PATH}")

        # Register client
        ret = self._plin.RegisterClient("LIN_TP_Flash", c_ulong(0), self._hClient)
        self._check(ret, "RegisterClient")

        # Enumerate hardware and select by channel
        hw_count = c_ushort(0)
        self._plin.GetAvailableHardware(HLINHW(0), c_ushort(0), hw_count)
        count = hw_count.value
        if count == 0:
            raise RuntimeError("No LIN hardware found. Check USB connection.")

        hw_array = (HLINHW * count)()
        self._plin.GetAvailableHardware(hw_array, c_ushort(count * 2), hw_count)

        self._hHw = None
        for i in range(count):
            ch_buf = c_int(0)
            self._plin.GetHardwareParam(
                HLINHW(hw_array[i]), TLIN_HARDWAREPARAM_CHANNEL_NUMBER,
                ch_buf, c_ushort(4))
            if ch_buf.value == TARGET_CHANNEL:
                self._hHw = HLINHW(hw_array[i])
                break

        if self._hHw is None:
            raise RuntimeError(f"No LIN hardware on channel {TARGET_CHANNEL}")

        ret = self._plin.ConnectClient(self._hClient, self._hHw)
        self._check(ret, "ConnectClient")

        ret = self._plin.InitializeHardware(
            self._hClient, self._hHw,
            TLIN_HARDWAREMODE_MASTER, c_ushort(LIN_BAUD_RATE))
        self._check(ret, "InitializeHardware")

        # Configure 0x3D as Subscriber so hardware captures slave responses
        slave_entry = TLINFrameEntry()
        slave_entry.FrameId      = c_ubyte(LIN_SLAVE_RESPONSE_ID)
        slave_entry.Length       = c_ubyte(8)
        slave_entry.Direction    = TLIN_DIRECTION_SUBSCRIBER
        slave_entry.ChecksumType = TLIN_CHECKSUMTYPE_CLASSIC
        self._plin.SetFrameEntry(self._hClient, self._hHw, slave_entry)
        self._plin.RegisterFrameId(
            self._hClient, self._hHw,
            c_ubyte(LIN_SLAVE_RESPONSE_ID), c_ubyte(LIN_SLAVE_RESPONSE_ID))

        self._is_open = True
        self._info("LIN TP transport open  "
                   f"(hw={self._hHw.value}, channel={TARGET_CHANNEL}, {LIN_BAUD_RATE} baud)")

    def close(self):
        if self._is_open:
            self._plin.DisconnectClient(self._hClient, self._hHw)
            self._plin.RemoveClient(self._hClient)
            self._is_open = False
            self._info("LIN TP transport closed")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def send_uds(self, uds_data: bytes, frame_delay_s: float = None,
                 expect_response: bool = True, nad: int = None) -> bytes:
        """
        Send a complete UDS request and return the complete UDS response.
        Handles LIN TP SF / FF+CF framing automatically.
        frame_delay_s: inter-frame delay override in seconds (default: INTER_FRAME_DELAY_S).
        expect_response: set to False for suppress-positive-response requests (sub-function
                         bit 7 = 1).  A timeout is then treated as the normal outcome and
                         an empty bytes object is returned instead of raising.
        nad: override the Node Address byte. Use NAD_FUNCTIONAL (0x7E) for functional
             addressing or NAD_BROADCAST (0x7F) for broadcast. Defaults to the physical NAD.
        """
        tx_nad = nad if nad is not None else NAD
        self._send_request(uds_data, frame_delay_s=frame_delay_s, nad=tx_nad)
        if not expect_response:
            try:
                return self._receive_response()
            except TimeoutError:
                self._info("No response received (suppress positive response – expected)")
                return bytes()
        return self._receive_response()

    # ------------------------------------------------------------------
    # Private – sending
    # ------------------------------------------------------------------
    def _send_request(self, data: bytes, frame_delay_s: float = None, nad: int = None):
        """Segment and send UDS data as LIN TP frames on 0x3C."""
        delay      = frame_delay_s if frame_delay_s is not None else INTER_FRAME_DELAY_S
        tx_nad     = nad if nad is not None else NAD
        length     = len(data)

        if length <= 6:
            # Single Frame – one write, then wait before polling
            pci     = bytes([length & 0x0F])
            payload = pci + data
            frame   = _make_lin_frame(tx_nad, payload)
            self._tx_frame(frame)           # raw write, no sleep inside
            raw = bytes([tx_nad]) + pci + data
            raw = raw + bytes([0xFF] * (8 - len(raw)))
            self._log_frame("TX SF", raw)
            time.sleep(delay)               # single inter-frame gap after SF
        else:
            # First Frame
            pci_ff  = bytes([0x10 | ((length >> 8) & 0x0F), length & 0xFF])
            payload = pci_ff + data[:5]
            frame   = _make_lin_frame(tx_nad, payload)
            self._tx_frame(frame)           # raw write, no sleep inside
            raw = bytes([tx_nad]) + pci_ff + data[:5]
            self._log_frame("TX FF", raw)
            time.sleep(delay)               # inter-frame gap: FF → CF1

            # Consecutive Frames
            sn      = 1
            offset  = 5
            while offset < length:
                chunk   = data[offset:offset + 6]
                pci_cf  = bytes([0x20 | (sn & 0x0F)])
                payload = pci_cf + chunk
                frame   = _make_lin_frame(tx_nad, payload)
                self._tx_frame(frame)       # raw write, no sleep inside
                raw = bytes([tx_nad]) + pci_cf + chunk
                raw = raw + bytes([0xFF] * (8 - len(raw)))
                self._log_frame(f"TX CF{sn}", raw)
                sn     = (sn + 1) & 0x0F
                offset += 6
                time.sleep(delay)           # inter-frame gap: CFn → CFn+1

    def _tx_frame(self, msg: TLINMsg, frame_delay_s: float = None):
        """Write one LIN frame. No sleep – caller controls inter-frame timing."""
        ret = self._plin.Write(self._hClient, self._hHw, msg)
        self._check(ret, "Write")

    # ------------------------------------------------------------------
    # Private – receiving
    # ------------------------------------------------------------------
    def _receive_response(self) -> bytes:
        """Poll 0x3D for response frames and reassemble full UDS payload."""
        # Poll for first frame (SF or FF)
        raw = self._poll_slave_frame(timeout_ms=P2_TIMEOUT_MS)
        if raw is None:
            raise TimeoutError("LIN TP: No response from slave (timeout)")

        nad_rcv = raw[0]
        pci1    = raw[1]
        pci_type = (pci1 >> 4) & 0x0F

        if pci_type == 0x0:
            # Single Frame
            length = pci1 & 0x0F
            result = bytes(raw[2:2 + length])
            self._log_frame("RX SF", bytes(raw))
            # Handle NRC 0x78 (ResponsePending) recursively
            if len(result) >= 3 and result[0] == 0x7F and result[2] == 0x78:
                self._info("NRC 0x78 – ResponsePending, waiting P2*...")
                return self._receive_response_extended()
            return result

        elif pci_type == 0x1:
            # First Frame
            length = ((pci1 & 0x0F) << 8) | raw[2]
            result = bytearray(raw[3:8])  # first 5 data bytes
            self._log_frame("RX FF", bytes(raw))

            # Receive consecutive frames
            sn_expected = 1
            while len(result) < length:
                cf_raw = self._poll_slave_frame(timeout_ms=P2_TIMEOUT_MS)
                if cf_raw is None:
                    raise TimeoutError("LIN TP: Timeout waiting for CF")
                cf_pci = cf_raw[1]
                if (cf_pci >> 4) != 0x2:
                    raise ValueError(f"LIN TP: Expected CF, got PCI=0x{cf_pci:02X}")
                sn = cf_pci & 0x0F
                if sn != sn_expected:
                    raise ValueError(f"LIN TP: CF sequence error: expected {sn_expected}, got {sn}")
                result.extend(cf_raw[2:8])
                self._log_frame(f"RX CF{sn}", bytes(cf_raw))
                sn_expected = (sn_expected + 1) & 0x0F

            return bytes(result[:length])

        else:
            raise ValueError(f"LIN TP: Unexpected PCI type 0x{pci_type:X} in first frame")

    def _receive_response_extended(self) -> bytes:
        """Wait up to P2* timeout for final response after NRC 0x78."""
        deadline = time.time() + P2_STAR_TIMEOUT_MS / 1000.0
        while time.time() < deadline:
            raw = self._poll_slave_frame(timeout_ms=int(P2_STAR_TIMEOUT_MS))
            if raw is None:
                break
            pci1     = raw[1]
            pci_type = (pci1 >> 4) & 0x0F
            length   = pci1 & 0x0F if pci_type == 0 else None
            if pci_type == 0x0:
                result = bytes(raw[2:2 + length])
                self._log_frame("RX SF (after NRC78)", bytes(raw))
                if len(result) >= 3 and result[0] == 0x7F and result[2] == 0x78:
                    continue  # Another pending
                return result
        raise TimeoutError("LIN TP: Timeout waiting for final response after NRC 0x78")

    def _poll_slave_frame(self, timeout_ms: int) -> list:
        """
        Repeatedly send 0x7D subscriber headers until a valid slave response
        is received or timeout expires.

        In LIN, the slave can only respond when the master issues a frame
        header for 0x3D (protected: 0x7D).  For services that require ECU
        processing time (e.g. 0x27 seed generation, 0x31 erase), a single
        header is not enough – we must keep polling.
        """
        # How often to re-send the 0x7D header (≈ one LIN frame time at 19200)
        POLL_INTERVAL_S = 0.020   # 20 ms between successive headers

        deadline = time.time() + timeout_ms / 1000.0
        rcv      = TLINRcvMsg()

        while time.time() < deadline:
            # Issue a fresh 0x7D subscriber header
            req = TLINMsg()
            req.FrameId      = LIN_SLAVE_RESP_PROT
            req.Length       = c_ubyte(8)
            req.Direction    = TLIN_DIRECTION_SUBSCRIBER
            req.ChecksumType = TLIN_CHECKSUMTYPE_CLASSIC
            ret = self._plin.Write(self._hClient, self._hHw, req)
            self._check(ret, "Write(0x7D)")

            # Drain the receive queue for a short window after the header
            poll_end = time.time() + POLL_INTERVAL_S
            while time.time() < poll_end:
                ret = self._plin.Read(self._hClient, rcv)
                if ret == TLIN_ERROR_OK:
                    raw_id   = rcv.FrameId & 0x3F
                    msg_type = rcv.Type
                    err_flags = rcv.ErrorFlags
                    if (raw_id == LIN_SLAVE_RESPONSE_ID
                            and msg_type == TLIN_MSGTYPE_STANDARD.value
                            and err_flags == 0):   # err_flags!=0 means no-response frame
                        if rcv.Data[0] == NAD:
                            return list(rcv.Data)
                time.sleep(0.002)

        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _check(self, ret, name: str):
        if ret != TLIN_ERROR_OK:
            raise RuntimeError(f"PLIN API error in {name}: 0x{ret:08X}")

    def _info(self, msg: str):
        if self._log:
            self._log.info(msg)
        else:
            print(f"[INFO] {msg}")

    def _log_frame(self, direction: str, raw: bytes):
        hex_str = _bytes_to_hex(raw)
        if self._log:
            self._log.frame(direction, hex_str)
        else:
            print(f"  [{direction:12s}] {hex_str}")
