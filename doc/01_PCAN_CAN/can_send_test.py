"""
Minimal CAN send test - uses PCANBasic DLL directly (bypasses python-can).
Run with: python can_send_test.py
"""
import sys
import time
import ctypes

print(f"Python executable: {sys.executable}")
print(f"Python version: {sys.version}")

try:
    from can.interfaces.pcan.basic import (
        PCANBasic,
        PCAN_USBBUS1,
        PCAN_BAUD_500K,
        PCAN_ERROR_OK,
        PCAN_ERROR_QRCVEMPTY,
        TPCANMsg,
        PCAN_MESSAGE_STANDARD,
    )
    print("PCANBasic loaded OK")
except ImportError as e:
    print(f"ERROR: {e}")
    print("Run: python -m pip install python-can")
    sys.exit(1)

pcan = PCANBasic()

# Step 1: Uninitialize
print("\n[1] Uninitialize...")
pcan.Uninitialize(PCAN_USBBUS1)
time.sleep(0.2)

# Step 2: Initialize
print("[2] Initialize PCAN_USBBUS1 @ 500k...")
result = pcan.Initialize(PCAN_USBBUS1, PCAN_BAUD_500K)
if result != PCAN_ERROR_OK:
    print(f"    FAILED: 0x{result:X}")
    sys.exit(1)
print("    OK")

# Step 3: Send frame
print("[3] Sending: ID=0x772 [02 10 01 00 00 00 00 00]...")
msg = TPCANMsg()
msg.ID = 0x772
msg.LEN = 8
msg.MSGTYPE = PCAN_MESSAGE_STANDARD
msg.DATA = (ctypes.c_ubyte * 8)(0x02, 0x10, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00)
result = pcan.Write(PCAN_USBBUS1, msg)
if result != PCAN_ERROR_OK:
    print(f"    Write FAILED: 0x{result:X}")
else:
    print("    Write OK")

time.sleep(0.1)

# Step 4: Send second frame
print("[4] Sending: ID=0x7FF [AA BB CC DD 00 00 00 00]...")
msg2 = TPCANMsg()
msg2.ID = 0x7FF
msg2.LEN = 8
msg2.MSGTYPE = PCAN_MESSAGE_STANDARD
msg2.DATA = (ctypes.c_ubyte * 8)(0xAA, 0xBB, 0xCC, 0xDD, 0x00, 0x00, 0x00, 0x00)
result = pcan.Write(PCAN_USBBUS1, msg2)
if result != PCAN_ERROR_OK:
    print(f"    Write FAILED: 0x{result:X}")
else:
    print("    Write OK")

# Step 5: Wait and read any response
print("[5] Listening 3s for any response...")
time.sleep(0.5)
start = time.monotonic()
count = 0
while time.monotonic() - start < 3.0:
    result, rx_msg, _ = pcan.Read(PCAN_USBBUS1)
    if result == PCAN_ERROR_OK:
        data_hex = " ".join(f"{rx_msg.DATA[i]:02X}" for i in range(rx_msg.LEN))
        print(f"    RX ID=0x{rx_msg.ID:03X} [{data_hex}]")
        count += 1
    elif result == PCAN_ERROR_QRCVEMPTY:
        time.sleep(0.01)
    else:
        print(f"    Read error: 0x{result:X}")
        break

if count == 0:
    print("    No frames received")

# Step 6: Get status
from can.interfaces.pcan.basic import PCAN_ERROR_BUSOFF, PCAN_ERROR_BUSHEAVY, PCAN_ERROR_BUSLIGHT, PCAN_ERROR_BUSPASSIVE
result = pcan.GetStatus(PCAN_USBBUS1)
status_names = {0: "OK/BUS_ACTIVE", 0x40: "BUS_LIGHT", 0x80: "BUS_HEAVY",
                0x100: "BUS_OFF", 0x200: "BUS_PASSIVE"}
print(f"[6] Bus status: 0x{result:X} ({status_names.get(result, 'unknown')})")

pcan.Uninitialize(PCAN_USBBUS1)
print("\n[DONE] Check CANoe - did you see ID=0x772 and ID=0x7FF?")
