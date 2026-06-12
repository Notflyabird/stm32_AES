#!/usr/bin/env python3
"""
sign_vbf.py  –  Auto-sign VBF files using VbfSignTestProd_Geely.exe
====================================================================
Usage:
    python sign_vbf.py [vbf_file]          # default: PNORFlashArea_RTSW.vbf
    python sign_vbf.py PNORFlashArea_RTSW_NO_LZSS.vbf

Logic:
    - If the VBF already carries a valid sw_signature → skip (already signed).
    - Otherwise  → copy to the signing tool folder, run the tool, copy back.

Signing tool  : BaseTechTestVBFsign tool/VbfSignTestProd_Geely.exe
Hash algorithm: SHA256
Private key   : privatekey2048_TestSpecific_Prod.pem
"""

import os
import re
import sys
import shutil
import subprocess

# --------------------------------------------------------------------------
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
TOOL_DIR    = os.path.join(SCRIPT_DIR, "BaseTechTestVBFsign tool")
TOOL_EXE    = os.path.join(TOOL_DIR, "VbfSignTestProd_Geely.exe")
HASH_ALG    = "SHA256"
KEY_FILE    = "privatekey2048_TestSpecific_Prod.pem"   # relative to TOOL_DIR
DEFAULT_VBF = "PNORFlashArea_RTSW.vbf"


# --------------------------------------------------------------------------
def read_header(vbf_path: str) -> str:
    """Return the text of the VBF header block."""
    with open(vbf_path, "rb") as f:
        raw = f.read(8192)          # header is always well within 8 KB
    text  = raw.decode("latin-1")
    depth = 0
    for i, c in enumerate(text):
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[: i + 1]
    raise ValueError(f"Cannot find closing '}}' in VBF header: {vbf_path}")


def is_signed(vbf_path: str) -> bool:
    """
    Return True when sw_signature is present and non-zero.
    A zero signature looks like:  sw_signature = 0x000...000;
    An absent or all-zero value → not signed.
    """
    try:
        header = read_header(vbf_path)
    except Exception:
        return False

    m = re.search(r'sw_signature\s*=\s*(0x[0-9A-Fa-f]+)\s*;', header)
    if not m:
        return False
    val = m.group(1)[2:]            # strip '0x'
    return any(c != '0' for c in val)


# --------------------------------------------------------------------------
def sign(vbf_path: str) -> None:
    vbf_name  = os.path.basename(vbf_path)
    tool_copy = os.path.join(TOOL_DIR, vbf_name)

    print(f"[sign_vbf] Copying '{vbf_name}' to signing tool folder …")
    shutil.copy2(vbf_path, tool_copy)

    print(f"[sign_vbf] Running: {os.path.basename(TOOL_EXE)} {vbf_name} {HASH_ALG} {KEY_FILE}")
    result = subprocess.run(
        [TOOL_EXE, vbf_name, HASH_ALG, KEY_FILE],
        cwd=TOOL_DIR,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Signing tool exited with code {result.returncode}")

    # Verify signature was actually written
    if not is_signed(tool_copy):
        raise RuntimeError("Signing tool reported success but sw_signature not found in output VBF")

    print(f"[sign_vbf] Copying signed VBF back to '{vbf_path}' …")
    shutil.copy2(tool_copy, vbf_path)
    print("[sign_vbf] Done.")


# --------------------------------------------------------------------------
def main():
    vbf_name = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_VBF
    vbf_path = vbf_name if os.path.isabs(vbf_name) else os.path.join(SCRIPT_DIR, vbf_name)

    if not os.path.isfile(vbf_path):
        print(f"[sign_vbf] ERROR: VBF not found: {vbf_path}", file=sys.stderr)
        sys.exit(1)

    if not os.path.isfile(TOOL_EXE):
        print(f"[sign_vbf] ERROR: Signing tool not found: {TOOL_EXE}", file=sys.stderr)
        sys.exit(1)

    print(f"[sign_vbf] Checking: {vbf_path}")
    if is_signed(vbf_path):
        print("[sign_vbf] Already signed – nothing to do.")
        sys.exit(0)

    print("[sign_vbf] Not signed (or signature is zero) – signing now …")
    sign(vbf_path)


if __name__ == "__main__":
    main()
