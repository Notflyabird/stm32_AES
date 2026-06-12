#!/usr/bin/env python3
"""
CAN TP Flash Configuration
==========================
Project : STM32 FBL UDS Reprogramming (CAN)
Hardware: PCAN-USB (or PCAN-USB Pro FD) – PEAK System
APP     : APP_files/a.s19  (Motorola S-record, no compression)

Author  : zlc
Date    : 2026-06-12
"""

import os

# --------------------------------------------------------------------------
# PEAK PCAN-Basic
# --------------------------------------------------------------------------
_BASE_DIR        = os.path.dirname(os.path.abspath(__file__))

# --------------------------------------------------------------------------
# CAN Hardware
# --------------------------------------------------------------------------
PCAN_CHANNEL     = "PCAN_USBBUS1"   # PCAN channel name for python-can
CAN_BITRATE      = 500000           # CAN nominal bitrate (500 kbps)
CAN_FD           = False            # Classic CAN 2.0 (not CAN-FD)

# CAN diagnostic frame IDs (11-bit standard)
CAN_TX_ID        = 0x123            # Tester -> ECU
CAN_RX_ID        = 0x122            # ECU -> Tester

# --------------------------------------------------------------------------
# ISO-TP Timing (ms)
# Read from ECU 0x10 positive response: 50 02 00 32 01 90
#   P2_Server_Max  = 0x0032        =   50 ms
#   P2*_Server_Max = 0x0190 × 10ms = 4000 ms
# --------------------------------------------------------------------------
P2_TIMEOUT_MS       = 150           # P2 timeout (3× P2 for CAN overhead)
P2_STAR_TIMEOUT_MS  = 5000          # Extended timeout after NRC 0x78 (P2* = 5s)
S3_TIMEOUT_MS       = 5000          # ECU session keep-alive timeout (S3 = 5s)
RESPONSE_TIMEOUT_S  = 2.0           # Final ECU response timeout in seconds
BUSY_RETRIES        = 3             # Retry count when ECU returns NRC 0x21
BUSY_WAIT_S         = 0.2           # Delay before retry after NRC 0x21

# ISO-TP params
ISO_TP_STMIN        = 0             # Minimum separation time (0 = fastest)
ISO_TP_BLOCKSIZE    = 8             # Block size for flow control
ISO_TP_WFTMAX       = 0             # Max wait frames

# --------------------------------------------------------------------------
# UDS Download
# --------------------------------------------------------------------------
# data_format_identifier for S19 (always 0x00 = uncompressed)
S19_DATA_FORMAT     = 0x00
# Address & length format identifier: 0x44 = 4-byte address + 4-byte length
ADDR_LEN_FORMAT     = 0x44
# Default transfer block size (bytes). Updated from 0x34 positive response.
DEFAULT_BLOCK_SIZE  = 0x0100        # 256 bytes (will be overridden from ECU)

# --------------------------------------------------------------------------
# Security Access
# --------------------------------------------------------------------------
SA_REQUEST_LEVEL    = 0x01          # Seed request sub-function (level 1)
SA_SEND_KEY_LEVEL   = 0x02          # Key send sub-function

# --------------------------------------------------------------------------
# APP Binary (S19)
# --------------------------------------------------------------------------
_SCRIPT_DIR          = os.path.dirname(os.path.abspath(__file__))
APP_S19_FILE         = os.path.join(_SCRIPT_DIR, "APP_files", "a.s19")

# --------------------------------------------------------------------------
# Result / Log Output
# --------------------------------------------------------------------------
LOG_DIR = os.path.join(_SCRIPT_DIR, "Result")
os.makedirs(LOG_DIR, exist_ok=True)
