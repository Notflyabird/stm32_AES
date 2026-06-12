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

## CAN ADC Routine

`Service_31_ADC_CAN.py` sends the ADC start routine over CAN/ISO-TP using PCAN.

Dependencies:

```bash
pip install python-can can-isotp
```

Dry-run request build:

```bash
python Service_31_ADC_CAN.py --dry-run --tx-id 0x6F1 --rx-id 0x651 --adc-channel 0xFF:0x01
```

Send the request to the ECU:

```bash
python Service_31_ADC_CAN.py --tx-id 0x6F1 --rx-id 0x651 --adc-channel 0xFF:0x01 --adc-channel 0xFF:0x02
```

The current protocol fragment only defines the StartRoutine request/response for RID `0xA043`.
If the ECU exposes a separate result-read step for the asynchronous ADC values, that protocol
still needs to be added before the script can decode final ADC conversion data.

### Fixed Test Cases

`Service_31_ADC_CAN_Cases.py` provides standalone fixed request cases for RID `0xA043`.
The default case sends `31 01 A0 43 03 01 00 02`.

```bash
python Service_31_ADC_CAN_Cases.py --dry-run
python Service_31_ADC_CAN_Cases.py --list-cases
python Service_31_ADC_CAN_Cases.py --case a043_03_00_03 --dry-run
python Service_31_ADC_CAN_Cases.py --case a043_03_00_02 --expect positive
python Service_31_ADC_CAN_Cases.py --case a043_03_00_02 --expect nrc13
```

Supported expected verdicts:

```text
positive -> expect 71 01 A0 43 01 00
nrc13    -> expect 7F 31 13
nrc21    -> expect 7F 31 21
nrcf1    -> expect 7F 31 F1
```

Built-in cases:

```text
a043_03_00_01 -> 31 01 A0 43 03 01 00 01
a043_03_00_02 -> 31 01 A0 43 03 01 00 02
a043_03_00_03 -> 31 01 A0 43 03 01 00 03
```

