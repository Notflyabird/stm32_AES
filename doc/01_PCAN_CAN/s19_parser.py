#!/usr/bin/env python3
"""
S19 (Motorola S-record) Parser for STM32 F103 FBL UDS Reprogramming
====================================================================
Parses Motorola S-record (S19) files and provides data blocks compatible
with the VbfDataBlock/VbfHeader interface used by the CAN reprogramming
scripts.

APP binary source: APP_files/a.s19
Format: S3 records (32-bit address) for data payload.
Termination: S7 record.

Example S3 record:
  S3 25 0800C000 006000203D260108...  B3
  │  │  │         │                   └─ checksum
  │  │  │         └─ data bytes (32 bytes = 0x25 - 4 - 1)
  │  │  └─ address (4 bytes, 32-bit)
  │  └─ byte count (0x25 = 37: 4 addr + 32 data + 1 checksum)
  └─ record type (S3 = data with 32-bit address)

STM32 F103 FBL flash layout:
  - APPLICATION_ADDRESS: 0x0800C000
  - APP binary in a.s19: 0x0800C000 – 0x0801FFFF (80 KB)
"""

import os
import struct


# ==========================================================================
# Data structures (VbfDataBlock / VbfHeader compatible interface)
# ==========================================================================

class S19DataBlock:
    """One contiguous data block parsed from S19 file.

    Interface compatible with VbfDataBlock:
      .address (int) – start address
      .data    (bytes) – raw payload
      .length  (int) – len(data)
    """
    def __init__(self, address: int, data: bytes):
        self.address = address
        self.data    = data
        self.length  = len(data)

    def __repr__(self):
        return (f"S19DataBlock(address=0x{self.address:08X}, "
                f"length=0x{self.length:08X})")


class S19Header:
    """Minimal header derived from S19 data.

    Interface compatible with VbfHeader:
      .data_format_identifier (int) – 0x00 for uncompressed
      .erase_regions          (list) – [(address, length), ...]
      .sw_part_number         (str)
      .sw_version             (str)
      .sw_part_type           (str)
    """
    def __init__(self, first_address: int, total_size: int):
        self.first_address          = first_address
        self.total_size             = total_size
        self.data_format_identifier = 0x00   # uncompressed
        self.sw_part_number         = "APP_S19"
        self.sw_version             = "1.0"
        self.sw_part_type           = "APP"
        self.erase_regions          = []     # set by caller or derived

        # Derive a single erase region by default
        # STM32F103 page size: 1 KB (medium-density) or 2 KB (high-density).
        # Use 1 KB granularity (each 1 KB is evenly divisible into 2 KB).
        PAGE_SIZE = 0x0400  # 1 KB
        erase_start = (first_address // PAGE_SIZE) * PAGE_SIZE
        erase_end   = ((first_address + total_size + PAGE_SIZE - 1)
                       // PAGE_SIZE) * PAGE_SIZE
        self.erase_regions = [(erase_start, erase_end - erase_start)]

    def __repr__(self):
        return (f"S19Header(first=0x{self.first_address:08X}, "
                f"size=0x{self.total_size:08X}, "
                f"erase={[(hex(a), hex(l)) for a, l in self.erase_regions]})")


# ==========================================================================
# S19 Checksum
# ==========================================================================

def _s19_checksum_valid(line: str) -> bool:
    """Validate an S-record checksum (byte after count)."""
    if len(line) < 10:
        return False
    payload = line[2:]  # everything after "Sx"
    # Sum all decoded bytes in payload (count + addr + data + checksum)
    total = 0
    for i in range(0, len(payload), 2):
        total += int(payload[i:i + 2], 16)
    # checksum byte = 0xFF - ((sum - checksum) & 0xFF)
    sum_without_checksum = total - int(payload[-2:], 16)
    expected = (0xFF - (sum_without_checksum & 0xFF)) & 0xFF
    actual = int(payload[-2:], 16)
    return expected == actual


# ==========================================================================
# Main parser
# ==========================================================================

def parse_s19(filepath: str):
    """Parse S19 file, return (S19Header, [S19DataBlock, ...]).

    Reads all S3 records, merges contiguous address ranges into blocks,
    and derives an erase region covering the full data range.

    Args:
        filepath: Path to the .s19 file (e.g. APP_files/a.s19).

    Returns:
        (S19Header, list of S19DataBlock)
    """
    with open(filepath, "r") as f:
        lines = f.readlines()

    # ------------------------------------------------------------------
    # Pass 1: collect all (address, data) from S3 records
    # ------------------------------------------------------------------
    records = []  # list of (address, bytes)
    for line in lines:
        line = line.strip()
        if not line or line[0] != "S":
            continue
        rec_type = line[1]

        if rec_type == "0":
            continue        # header record, ignore

        elif rec_type == "3":
            # S3: 32-bit address data record
            byte_count = int(line[2:4], 16)          # addr + data + checksum
            address    = int(line[4:12], 16)          # 4-byte address
            data_len   = byte_count - 5               # subtract addr(4) + chk(1)
            data_hex   = line[12:12 + data_len * 2]
            data       = bytes.fromhex(data_hex)
            records.append((address, data))

        elif rec_type in ("7", "8", "9"):
            break               # termination record, stop parsing

    if not records:
        raise ValueError(f"No S3 data records found in {filepath}")

    # ------------------------------------------------------------------
    # Pass 2: sort by address and merge contiguous blocks
    # ------------------------------------------------------------------
    records.sort(key=lambda x: x[0])

    blocks = []
    cur_addr = records[0][0]
    cur_data = bytearray()

    for addr, data in records:
        expected = cur_addr + len(cur_data)
        if addr == expected:
            # Contiguous – extend current block
            cur_data.extend(data)
        else:
            # Gap – finalize current block, start new one
            if cur_data:
                blocks.append(S19DataBlock(cur_addr, bytes(cur_data)))
            cur_addr = addr
            cur_data = bytearray(data)

    if cur_data:
        blocks.append(S19DataBlock(cur_addr, bytes(cur_data)))

    # ------------------------------------------------------------------
    # Compute total range
    # ------------------------------------------------------------------
    first_addr = blocks[0].address
    last_end   = blocks[-1].address + blocks[-1].length
    total_size = last_end - first_addr

    header = S19Header(first_addr, total_size)

    return header, blocks


# ==========================================================================
# Convenience function (compatible with parse_vbf call sites)
# ==========================================================================

def parse_app_image(filepath: str = None):
    """Parse the APP binary (S19) for reprogramming.

    If *filepath* is None, looks for ``APP_files/a.s19`` relative to
    this script's directory.

    Returns (S19Header, [S19DataBlock, ...]).
    """
    if filepath is None:
        filepath = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "APP_files", "a.s19",
        )
    return parse_s19(filepath)


# ==========================================================================
# CLI test
# ==========================================================================

if __name__ == "__main__":
    import sys
    fp = sys.argv[1] if len(sys.argv) > 1 else None
    hdr, blks = parse_app_image(fp)

    print("=== S19 File Summary ===")
    print(f"  File          : {fp or os.path.join(os.path.dirname(__file__), 'APP_files', 'a.s19')}")
    print(f"  First address : 0x{hdr.first_address:08X}")
    print(f"  Total size    : 0x{hdr.total_size:08X} ({hdr.total_size} bytes)")
    print(f"  Data format   : 0x{hdr.data_format_identifier:02X} (uncompressed)")
    print(f"  Erase region  : {[(hex(a), hex(l)) for a, l in hdr.erase_regions]}")
    print(f"  Data blocks   : {len(blks)}")
    for b in blks:
        print(f"    {b}")
    total_data = sum(b.length for b in blks)
    print(f"  Total data    : {total_data} bytes")
