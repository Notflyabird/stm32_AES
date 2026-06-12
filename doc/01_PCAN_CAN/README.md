# PCAN_LIN

LIN UDS diagnostic and reprogramming scripts based on PCAN-USB.

## Requirements

| Item | Details |
|------|---------|
| Hardware | PCAN-USB PRO |
| Driver | Latest PCAN LIN driver |
| IDE | VS Code |
| Python | 3.9 or later |

## Wiring (PCAN Channel 1)

| DB9 Pin | Signal |
|---------|--------|
| Pin 4 | LIN |
| Pin 5 | GND |
| Pin 9 | LIN Power (12V) |


python sign_vbf.py PNORFlashArea_RTSW_NO_LZSS.vbf
python sign_vbf.py PNORFlashArea_RTSW.vbf

## CAN Diagnostic Scripts

CAN UDS diagnostic and reprogramming scripts using PCAN-USB (CAN 2.0 @ 500 kbps).

### CAN Hardware Configuration

| Item | Details |
|------|---------|
| Hardware | PCAN-USB or PCAN-USB Pro FD |
| CAN bitrate | 500 kbps |
| CAN mode | CAN 2.0 (classic) |
| TX ID (tester → ECU) | 0x123 |
| RX ID (ECU → tester) | 0x122 |
| Transport | ISO 15765-2 (ISO-TP) |

### Dependencies

```bash
pip install python-can can-isotp
```

### CAN File Structure

| File | Description |
|------|-------------|
| `can_tp_config.py` | CAN transport configuration (IDs, timing, VBF paths) |
| `can_tp_transport.py` | CAN ISO-TP transport layer using python-can + can-isotp |
| `can_uds_log.py` | CAN UDS logger with helper functions |
| `Service_10_CAN.py` | DiagnosticSessionControl (10 01/02/03) |
| `Service_11_CAN.py` | ECUReset (11 01/02/03) |
| `Service_22_CAN.py` | ReadDataByIdentifier (22) |
| `Service_27_CAN.py` | SecurityAccess (27 01/02) with AES-CMAC key |
| `Service_31_Erase_CAN.py` | EraseMemory (31 01 FF00), CheckMemory (0212), CheckComplete (0205) |
| `Service_34_CAN.py` | RequestDownload (34) |
| `Service_36_CAN.py` | TransferData (36) |
| `Service_37_CAN.py` | TransferExit (37) |
| `Service_34_36_37_CAN.py` | Download orchestration (34→36×N→37) |
| `Service_3E_CAN.py` | TesterPresent (3E) |
| `Reprogramming_CAN.py` | Full reprogramming sequence (uncompressed VBF) |
| `Reprogramming_CAN_LZSS.py` | Full reprogramming sequence (LZSS compressed VBF) |

### Usage

```bash
# Read current session
python Service_22_CAN.py

# Switch sessions
python Service_10_CAN.py

# Security access
python Service_27_CAN.py

# Full reprogramming (uncompressed VBF)
python Reprogramming_CAN.py --vbf path/to/file.vbf

# Full reprogramming (LZSS compressed VBF)
python Reprogramming_CAN_LZSS.py
```

### Reprogramming Sequence (CAN)

1. **Extended Session** `10 03` → `50 03`
2. **Programming Session** `10 82` (suppress) ×2
3. **Security Access** `27 01` → seed → `27 02` + CMAC key → `67 02`
4. **Erase Memory** `31 01 FF00` + address + length → `71 01 FF00`
5. **For each VBF block:**
   - **RequestDownload** `34 00 44 Fmt Addr Len` → `74 MaxBlockSize`
   - **TransferData** `36 Seq Data` × N → `76 Seq`
   - **TransferExit** `37` → `77`
6. **CheckMemory** `31 01 0212` + signature → `71 01 0212 10 00`
7. **CheckComplete** `31 01 0205` → `71 01 0205 10`
8. **ECU Reset** `11 01` → ECU reboots

## CAN ADC Routine

`Service_31_ADC_CAN.py` sends the ADC start routine over CAN/ISO-TP using PCAN.

```bash
python Service_31_ADC_CAN.py --dry-run --tx-id 0x6F1 --rx-id 0x651 --adc-channel 0xFF:0x01
python Service_31_ADC_CAN.py --tx-id 0x6F1 --rx-id 0x651 --adc-channel 0xFF:0x01 --adc-channel 0xFF:0x02
```

### Fixed Test Cases

`Service_31_ADC_CAN_Cases.py` provides standalone fixed request cases for RID `0xA043`.

```bash
python Service_31_ADC_CAN_Cases.py --list-cases
python Service_31_ADC_CAN_Cases.py --case a043_03_00_03 --dry-run
```

Built-in cases:

```text
a043_03_00_01 -> 31 01 A0 43 03 01 00 01
a043_03_00_02 -> 31 01 A0 43 03 01 00 02
a043_03_00_03 -> 31 01 A0 43 03 01 00 03
```

