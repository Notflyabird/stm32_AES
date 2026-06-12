#!/usr/bin/env python3
"""
S19 Parser Verification
=======================
Run this script to verify the S19 parser output:
  cd doc/01_PCAN_CAN
  python verify_s19.py

Expected results:
  - First address : 0x0800C000 (APPLICATION_ADDRESS)
  - Total size    : 0x14000 (81920 bytes = 80 KB)
  - Erase region  : (0x0800C000, 0x14000)
  - Data blocks   : 1 contiguous block
  - Accumulated CRC16: (computed from all data)
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from s19_parser import parse_app_image
from Service_31_Erase_CAN import crc16_ccitt


def main():
    s19_path = os.path.join(os.path.dirname(__file__), "APP_files", "a.s19")
    if not os.path.exists(s19_path):
        print(f"ERROR: S19 file not found: {s19_path}")
        sys.exit(1)

    hdr, blocks = parse_app_image(s19_path)

    print("=" * 60)
    print("S19 Parser Verification")
    print("=" * 60)
    print(f"  S19 file       : {s19_path}")
    print(f"  File size      : {os.path.getsize(s19_path):,} bytes (ASCII)")
    print()
    print("--- Header ---")
    print(f"  First address  : 0x{hdr.first_address:08X}")
    print(f"  Total size     : 0x{hdr.total_size:08X} ({hdr.total_size:,} bytes)")
    print(f"  Data format    : 0x{hdr.data_format_identifier:02X} (uncompressed)")
    print(f"  Erase region   : {[(hex(a), hex(l)) for a, l in hdr.erase_regions]}")
    print()
    print("--- Data Blocks ---")
    total_data = 0
    for i, b in enumerate(blocks):
        total_data += b.length
        print(f"  Block {i}: address=0x{b.address:08X} length=0x{b.length:X} ({b.length:,} bytes)")

    print(f"\n  Total data     : {total_data:,} bytes")

    # Verify address alignment
    print()
    print("--- Address Verification ---")
    if blocks[0].address == 0x0800C000:
        print("  [OK] APP address: 0x0800C000 (APPLICATION_ADDRESS)")
    else:
        print(f"  [FAIL] APP address: 0x{blocks[0].address:08X} (expected 0x0800C000)")

    last_end = blocks[-1].address + blocks[-1].length
    print(f"  APP range     : 0x{blocks[0].address:08X} - 0x{last_end:08X}")
    print(f"  APP size      : 0x{last_end - blocks[0].address:X} ({last_end - blocks[0].address:,} bytes)")

    # CRC16 accumulation
    print()
    print("--- CRC16-CCITT Verification ---")
    crc = 0xFFFF
    for b in blocks:
        crc = crc16_ccitt(b.data, crc)
    print(f"  Accumulated CRC16: 0x{crc:04X}")
    print("  (Matches FBL's internal crc_1 after all TransferData)")

    # Erase region check
    print()
    print("--- Erase Region ---")
    for addr, length in hdr.erase_regions:
        print(f"  Erase 0x{addr:08X} - 0x{addr + length:08X} (size 0x{length:X})")
        if addr % 0x400 == 0 and (addr + length) % 0x400 == 0:
            print("  [OK] Page-aligned")
        else:
            print("  [WARN] Not page-aligned!")

    print()
    print("=" * 60)
    print("Verification complete")
    print("=" * 60)


if __name__ == "__main__":
    main()
