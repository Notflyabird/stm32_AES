#!/usr/bin/env python3
"""
LIN TP Flash Configuration
==========================
Project : TI LIN Reprogramming (No SBL)
Hardware: PCAN-USB Pro FD  – PEAK System
VBF     : PNORFlashArea_RTSW.vbf  (data_format_identifier = 0x10, LZSS compressed)
NAD     : 0x67

Author  : Generated
Date    : 2026-04-28
"""

import os

# --------------------------------------------------------------------------
# PEAK PLIN-API
# --------------------------------------------------------------------------
_BASE_DIR        = os.path.dirname(os.path.abspath(__file__))
PLIN_API_INCLUDE = os.path.join(_BASE_DIR, "DLL")
PLIN_DLL_PATH    = os.path.join(_BASE_DIR, "DLL", "PLinApi.dll")

# --------------------------------------------------------------------------
# LIN Hardware
# --------------------------------------------------------------------------
TARGET_CHANNEL   = 1       # LIN channel number (channel=1 on PCAN-USB Pro FD)
LIN_BAUD_RATE    = 19200   # LIN bus baud rate (9600 / 19200)

# LIN diagnostic frame IDs (unprotected → protected with parity)
#   0x3C: P0=0 P1=0 → protected 0x3C
#   0x3D: P0=1 P1=0 → protected 0x7D
LIN_MASTER_REQUEST_ID  = 0x3C   # unprotected
LIN_SLAVE_RESPONSE_ID  = 0x3D   # unprotected
LIN_MASTER_REQ_PROT    = 0x3C   # protected
LIN_SLAVE_RESP_PROT    = 0x7D   # protected

# --------------------------------------------------------------------------
# LIN TP Node Addressing
# --------------------------------------------------------------------------
NAD = 0x67   # Node Address (from VBF ecu_address = 0x1B67, lower byte)
NAD_FUNCTIONAL = 0x7E   # Functional addressing NAD per ISO 17987

# --------------------------------------------------------------------------
# LIN TP Timing (ms)
# Read from ECU 0x10 positive response: 50 02 00 32 01 F4
#   P2_Server_Max  = 0x0032        =   50 ms
#   P2*_Server_Max = 0x01F4 × 10ms = 5000 ms  (= S3 session timeout)
# --------------------------------------------------------------------------
P2_TIMEOUT_MS       = 150     # Poll window per 0x7D burst (3× P2 for LIN overhead)
P2_STAR_TIMEOUT_MS  = 5000    # Extended timeout after NRC 0x78 (P2* = 5s)
S3_TIMEOUT_MS       = 5000    # ECU session keep-alive timeout (S3 = 5s)
INTER_FRAME_DELAY_S = 0.010   # Delay between sending/polling consecutive frames

# --------------------------------------------------------------------------
# UDS Download
# --------------------------------------------------------------------------
# data_format_identifier from VBF (0x10 = LZSS compressed upload)
VBF_DATA_FORMAT     = 0x10
# Address & length format identifier: 0x44 = 4-byte address + 4-byte length
ADDR_LEN_FORMAT     = 0x44
# Default transfer block size (bytes). Updated from 0x34 positive response.
DEFAULT_BLOCK_SIZE  = 0x0100   # 256 bytes (will be overridden from ECU)

# --------------------------------------------------------------------------
# Security Access
# --------------------------------------------------------------------------
SA_REQUEST_LEVEL    = 0x01   # Seed request sub-function (level 1)
SA_SEND_KEY_LEVEL   = 0x02   # Key send sub-function

# --------------------------------------------------------------------------
# VBF File
# --------------------------------------------------------------------------
_SCRIPT_DIR          = os.path.dirname(os.path.abspath(__file__))
VBF_FILE             = os.path.join(_SCRIPT_DIR, "VBF", "PNORFlashArea_RTSW.vbf")
# Older (incomplete) VBF: block[1] length=0xA99B vs 0xB0C6 in current.
# Used to trigger CheckCompleteAndCompatible status 0x05 (App incomplete).
# Extracted from git commit 9452265 (2026-04-28).
VBF_FILE_INCOMPLETE  = os.path.join(_SCRIPT_DIR, "VBF", "PNORFlashArea_RTSW_incomplete.vbf")
# Version-incompatible VBF: same block size as current but FBL version mismatch.
# Used to trigger CheckCompleteAndCompatible status 0x06 (FBL/App incompatible).
VBF_FILE_INCOMPATIBLE = os.path.join(_SCRIPT_DIR, "VBF", "PNORFlashArea_RTSW_incompatible.vbf")
# Uncompressed VBF (data_format_identifier = 0x00, no LZSS).
VBF_FILE_NO_LZSS     = os.path.join(_SCRIPT_DIR, "VBF", "PNORFlashArea_RTSW_NO_LZSS.vbf")

# --------------------------------------------------------------------------
# Result / Log Output
# --------------------------------------------------------------------------
LOG_DIR = os.path.join(_SCRIPT_DIR, "Result")
os.makedirs(LOG_DIR, exist_ok=True)
