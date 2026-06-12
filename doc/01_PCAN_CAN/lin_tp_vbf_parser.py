#!/usr/bin/env python3
"""
VBF Parser (AUTOSAR VBF 2.x)
=============================
Parses VBF files used for ECU reprogramming.
Supports both uncompressed and LZSS-compressed blocks
(data_format_identifier = 0x00 / 0x10).

VBF binary data layout after header closing '}':
  For each data block:
    [start_address : 4 bytes, big-endian]
    [length        : 4 bytes, big-endian]
    [data          : <length> bytes]
    [crc16         : 2 bytes, big-endian]  <-- stored as-is; NOT validated here.
                                               VBF integrity is protected by
                                               hash + RSA signature in the header.
"""

import re
import struct
import os


# --------------------------------------------------------------------------
class VbfDataBlock:
    """One data block parsed from a VBF file."""
    def __init__(self, address: int, data: bytes, crc16: int):
        self.address = address
        self.data    = data
        self.crc16   = crc16
        self.length  = len(data)

    def __repr__(self):
        return (f"VbfDataBlock(address=0x{self.address:08X}, "
                f"length=0x{self.length:08X}, crc16=0x{self.crc16:04X})")


# --------------------------------------------------------------------------
class VbfHeader:
    """Parsed VBF header fields."""
    def __init__(self):
        self.vbf_version            = ""
        self.sw_part_number         = ""
        self.sw_version             = ""
        self.sw_part_type           = ""
        self.data_format_identifier = 0x00   # 0x00=raw, 0x10=LZSS
        self.ecu_address            = 0
        self.erase_regions          = []     # list of (address, length) tuples
        self.verification_block_start  = 0
        self.verification_block_length = 0
        self.file_checksum          = 0
        self.sw_signature_dev       = ""     # hex string (no 0x prefix) for 31 01 0212 – dev key
        self.sw_signature           = ""     # hex string (no 0x prefix) for 31 01 0212 – prod key
        self.data_blocks_info       = []     # from comments: (addr, len, crc)

    def __repr__(self):
        return (f"VbfHeader(sw_part={self.sw_part_number!r}, "
                f"sw_ver={self.sw_version!r}, "
                f"sw_part_type={self.sw_part_type}, "
                f"data_format=0x{self.data_format_identifier:02X}, "
                f"ecu=0x{self.ecu_address:08X}, "
                f"erase={self.erase_regions})")


# --------------------------------------------------------------------------
class VbfParser:
    """
    Parse a VBF file into header + list of VbfDataBlock objects.
    Usage:
        parser = VbfParser("path/to/file.vbf")
        header, blocks = parser.parse()
    """

    def __init__(self, filepath: str):
        self.filepath = filepath

    def parse(self):
        """Return (VbfHeader, [VbfDataBlock, ...])."""
        with open(self.filepath, "rb") as f:
            raw = f.read()

        header_text, data_offset = self._extract_header_text(raw)
        header = self._parse_header(header_text)
        blocks = self._parse_data_blocks(raw, data_offset)
        return header, blocks

    # ------------------------------------------------------------------
    # Header extraction
    # ------------------------------------------------------------------
    def _extract_header_text(self, raw: bytes):
        """
        Find the end of the top-level 'header { ... }' block.
        Returns (header_text: str, data_offset: int).
        """
        depth   = 0
        in_hdr  = False
        start   = 0
        i       = 0
        while i < len(raw):
            c = raw[i:i+1]
            if not in_hdr:
                if raw[i:i+7] == b'header ':
                    in_hdr = True
                i += 1
                continue
            if not in_hdr:
                i += 1
                continue
            if c == b'{':
                if depth == 0:
                    start = i
                depth += 1
            elif c == b'}':
                depth -= 1
                if depth == 0:
                    # end of header
                    end = i + 1
                    # skip \r\n after '}'
                    while end < len(raw) and raw[end:end+1] in (b'\r', b'\n'):
                        end += 1
                    text = raw[:end].decode("latin-1")
                    return text, end
            i += 1
        raise ValueError("Could not find closing '}' of VBF header block")

    # ------------------------------------------------------------------
    # Header parsing
    # ------------------------------------------------------------------
    def _parse_header(self, text: str) -> VbfHeader:
        h = VbfHeader()

        m = re.search(r'bf_version\s*=\s*([\d.]+)', text)
        if m:
            h.vbf_version = m.group(1)

        m = re.search(r'sw_part_number\s*=\s*"([^"]+)"', text)
        if m:
            h.sw_part_number = m.group(1)

        m = re.search(r'sw_version\s*=\s*"([^"]+)"', text)
        if m:
            h.sw_version = m.group(1)

        m = re.search(r'sw_part_type\s*=\s*(\w+)', text)
        if m:
            h.sw_part_type = m.group(1)

        m = re.search(r'data_format_identifier\s*=\s*(0x[0-9A-Fa-f]+|\d+)', text)
        if m:
            h.data_format_identifier = int(m.group(1), 0)

        m = re.search(r'ecu_address\s*=\s*(0x[0-9A-Fa-f]+|\d+)', text)
        if m:
            h.ecu_address = int(m.group(1), 0)

        # erase regions: { { addr, len }, { addr, len }, ... }
        # Use [^;]+ to grab everything between 'erase = ' and ';', then find pairs inside
        erase_match = re.search(r'erase\s*=\s*(\{[^;]+\})\s*;', text, re.DOTALL)
        if erase_match:
            inner = erase_match.group(1)
            for pair in re.finditer(r'\{\s*(0x[0-9A-Fa-f]+)\s*,\s*(0x[0-9A-Fa-f]+)\s*\}', inner):
                h.erase_regions.append((int(pair.group(1), 16), int(pair.group(2), 16)))

        m = re.search(r'verification_block_start\s*=\s*(0x[0-9A-Fa-f]+)', text)
        if m:
            h.verification_block_start = int(m.group(1), 16)

        m = re.search(r'verification_block_length\s*=\s*(0x[0-9A-Fa-f]+)', text)
        if m:
            h.verification_block_length = int(m.group(1), 16)

        m = re.search(r'file_checksum\s*=\s*(0x[0-9A-Fa-f]+)', text)
        if m:
            h.file_checksum = int(m.group(1), 16)

        m = re.search(r'sw_signature_dev\s*=\s*(0x[0-9A-Fa-f]+)', text, re.DOTALL)
        if m:
            h.sw_signature_dev = m.group(1)[2:]  # strip '0x', keep plain hex string

        # sw_signature (production) – must NOT match sw_signature_dev
        m = re.search(r'(?<!_dev )sw_signature\s*=\s*(0x[0-9A-Fa-f]+)', text, re.DOTALL)
        if m:
            h.sw_signature = m.group(1)[2:]

        # Block info from comments
        for bm in re.finditer(
                r'DataBlock\d+.*?StartAddress:(0x[0-9A-Fa-f]+).*?Length:(0x[0-9A-Fa-f]+).*?Crc16:(0x[0-9A-Fa-f]+)',
                text):
            h.data_blocks_info.append((
                int(bm.group(1), 16),
                int(bm.group(2), 16),
                int(bm.group(3), 16),
            ))

        return h

    # ------------------------------------------------------------------
    # Binary data block parsing
    # ------------------------------------------------------------------
    def _parse_data_blocks(self, raw: bytes, offset: int):
        blocks = []
        while offset < len(raw) - 10:
            if len(raw) - offset < 10:
                break
            addr   = struct.unpack_from(">I", raw, offset)[0]
            length = struct.unpack_from(">I", raw, offset + 4)[0]
            offset += 8

            if length == 0 or offset + length + 2 > len(raw):
                break

            data   = raw[offset:offset + length]
            crc16  = struct.unpack_from(">H", raw, offset + length)[0]
            # CRC16 field is read but not validated.
            # VBF integrity is verified via hash + RSA (not CRC16).
            blocks.append(VbfDataBlock(addr, data, crc16))
            offset += length + 2

        return blocks



# --------------------------------------------------------------------------
# Convenience function
# --------------------------------------------------------------------------
def parse_vbf(filepath: str):
    """Parse VBF file. Returns (VbfHeader, [VbfDataBlock])."""
    parser = VbfParser(filepath)
    return parser.parse()


# --------------------------------------------------------------------------
# CLI test
# --------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    fp = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(__file__), "PNORFlashArea_RTSW.vbf")
    hdr, blks = parse_vbf(fp)
    print("=== VBF Header ===")
    print(hdr)
    print(f"  Erase regions : {[(hex(a), hex(l)) for a,l in hdr.erase_regions]}")
    print(f"  data_format   : 0x{hdr.data_format_identifier:02X} "
          f"({'LZSS compressed' if hdr.data_format_identifier == 0x10 else 'raw'})")
    print(f"\n=== Data Blocks ({len(blks)}) ===")
    for b in blks:
        print(f"  {b}")
