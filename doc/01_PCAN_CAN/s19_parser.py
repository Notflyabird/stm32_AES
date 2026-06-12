#!/usr/bin/env python3
"""
APP Binary Parser – S19 (Motorola S-record) / Intel HEX
==========================================================
Parses Motorola S-record (.s19) and Intel HEX (.hex) files,
providing data blocks compatible with the VbfDataBlock/VbfHeader
interface used by the CAN reprogramming scripts.

APP binary source: APP_files/a.hex (Intel HEX format)
  Extended Linear Address records set 32-bit base addresses.
  Data records contain up to 32 bytes each.
  Termination: EOF record (type 01).

Also supports .s19 files with S3 records (32-bit address).

STM32 F103 FBL flash layout:
  - APPLICATION_ADDRESS: 0x0800C000
  - APP binary: 0x0800C000 – 0x0801FFFF (80 KB)
"""

import os
import struct


# ==========================================================================
# Data structures (VbfDataBlock / VbfHeader compatible interface)
# ==========================================================================

class S19DataBlock:
    """One contiguous data block parsed from APP binary.

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
    """Minimal header derived from APP binary.

    Interface compatible with VbfHeader:
      .data_format_identifier (int) – 0x00 for uncompressed
      .erase_regions          (list) – [(address, length), ...]
      .sw_part_number         (str)
      .sw_version             (str)
      .sw_part_type           (str)
    """
    def __init__(self, first_address: int, total_size: int,
                 min_erase_addr: int = None):
        """
        Args:
            first_address: Start address of APP data.
            total_size:    Total size of APP data in bytes.
            min_erase_addr: Optional minimum erase address (inclusive).
                           The erase region will start at or before this
                           address (page-aligned). Use to ensure areas
                           like the APP valid flag (0x0800A000) are
                           erased before writing.
        """
        self.first_address          = first_address
        self.total_size             = total_size
        self.data_format_identifier = 0x00   # uncompressed
        self.sw_part_number         = "APP"
        self.sw_version             = "1.0"
        self.sw_part_type           = "APP"
        self.erase_regions          = []     # set by caller or derived

        # Derive a single erase region by default
        # STM32F103 page size: 1 KB (medium-density) or 2 KB (high-density).
        # Use 1 KB granularity (each 1 KB is evenly divisible into 2 KB).
        PAGE_SIZE = 0x0400  # 1 KB

        # Extend erase start downward to cover min_erase_addr (e.g. APP valid flag)
        raw_start = first_address
        if min_erase_addr is not None and min_erase_addr < raw_start:
            raw_start = min_erase_addr

        erase_start = (raw_start // PAGE_SIZE) * PAGE_SIZE
        erase_end   = ((first_address + total_size + PAGE_SIZE - 1)
                       // PAGE_SIZE) * PAGE_SIZE
        self.erase_regions = [(erase_start, erase_end - erase_start)]

    def __repr__(self):
        return (f"S19Header(first=0x{self.first_address:08X}, "
                f"size=0x{self.total_size:08X}, "
                f"erase={[(hex(a), hex(l)) for a, l in self.erase_regions]})")


# ==========================================================================
# Intel HEX parser
# ==========================================================================

def _parse_intel_hex(filepath: str):
    """
    Parse Intel HEX file, return list of (address, data_bytes) records.

    Supports:
      - Record type 00 (Data)
      - Record type 01 (End Of File)
      - Record type 04 (Extended Linear Address)
    """
    records = []        # list of (address, data_bytes)
    base_address = 0    # upper 16 bits from Extended Linear Address records

    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line[0] != ":":
                continue

            # Parse Intel HEX record
            byte_count = int(line[1:3], 16)
            address    = int(line[3:7], 16)
            rec_type   = int(line[7:9], 16)
            data_hex   = line[9:9 + byte_count * 2]
            # checksum = int(line[9 + byte_count * 2:9 + byte_count * 2 + 2], 16)
            # (checksum validation is optional)

            if rec_type == 0x00:
                # Data record: full address = base + offset
                full_addr = base_address + address
                data = bytes.fromhex(data_hex)
                records.append((full_addr, data))

            elif rec_type == 0x01:
                # End Of File record
                break

            elif rec_type == 0x04:
                # Extended Linear Address record
                # Data contains upper 16 bits of the base address
                base_address = int(data_hex, 16) << 16

            # Other record types (02, 03, 05) are not used in this file

    if not records:
        raise ValueError(f"No data records found in Intel HEX file: {filepath}")

    return records


# ==========================================================================
# Motorola S-record parser
# ==========================================================================

def _parse_s19_records(filepath: str):
    """
    Parse Motorola S-record file, return list of (address, data_bytes) records.

    Supports S3 (32-bit address) data records.
    Terminates on S7/S8/S9 records.
    """
    records = []

    with open(filepath, "r") as f:
        for line in f:
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

    return records


# ==========================================================================
# Common: merge contiguous records into blocks
# ==========================================================================

def _merge_records(records):
    """Sort records by address, merge contiguous ranges into blocks.

    Args:
        records: list of (address, data_bytes)

    Returns:
        list of S19DataBlock
    """
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

    return blocks


# ==========================================================================
# Auto-detect and parse
# ==========================================================================

def parse_app_image(filepath: str = None, min_erase_addr: int = 0x0800A000):
    """
    Parse an APP binary file (.hex or .s19) and return data blocks.

    Auto-detects Intel HEX (starts with ':') vs Motorola S-record (starts with 'S').

    If *filepath* is None, looks for ``APP_files/a.hex`` (or ``a.s19`` as fallback)
    relative to this script's directory.

    The default *min_erase_addr* is 0x0800A000 (APP_VALID_FLAG_ADDR),
    which ensures the APP valid flag area is erased before writing.

    Returns (S19Header, [S19DataBlock, ...]).
    """
    if filepath is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        app_dir    = os.path.join(script_dir, "APP_files")
        filepath   = os.path.join(app_dir, "a.hex")
        if not os.path.exists(filepath):
            filepath = os.path.join(app_dir, "a.s19")  # fallback
        if not os.path.exists(filepath):
            raise FileNotFoundError(
                f"APP binary not found: tried a.hex and a.s19 in {app_dir}")

    # Auto-detect format by reading first non-empty line
    with open(filepath, "r") as f:
        first_char = None
        for line in f:
            stripped = line.strip()
            if stripped:
                first_char = stripped[0]
                break

    if first_char == ":":
        records = _parse_intel_hex(filepath)
    elif first_char == "S":
        records = _parse_s19_records(filepath)
    else:
        raise ValueError(
            f"Unknown file format: {filepath} (first char={first_char!r})")

    # Merge contiguous records into blocks
    blocks = _merge_records(records)

    # Compute total range
    first_addr = blocks[0].address
    last_end   = blocks[-1].address + blocks[-1].length
    total_size = last_end - first_addr

    header = S19Header(first_addr, total_size, min_erase_addr=min_erase_addr)

    return header, blocks


# ==========================================================================
# CLI test
# ==========================================================================

if __name__ == "__main__":
    import sys
    fp = sys.argv[1] if len(sys.argv) > 1 else None
    hdr, blks = parse_app_image(fp)

    print("=== APP Binary Summary ===")
    print(f"  File          : {fp or 'auto'}")
    print(f"  First address : 0x{hdr.first_address:08X}")
    print(f"  Total size    : 0x{hdr.total_size:08X} ({hdr.total_size} bytes)")
    print(f"  Data format   : 0x{hdr.data_format_identifier:02X} (uncompressed)")
    print(f"  Erase region  : {[(hex(a), hex(l)) for a, l in hdr.erase_regions]}")
    print(f"  Data blocks   : {len(blks)}")
    for b in blks:
        print(f"    {b}")
    total_data = sum(b.length for b in blks)
    print(f"  Total data    : {total_data} bytes")
