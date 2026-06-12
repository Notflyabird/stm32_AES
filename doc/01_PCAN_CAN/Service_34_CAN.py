#!/usr/bin/env python3
"""
Service 0x34 – RequestDownload (CAN / UDS context)
====================================================
Standalone script for CAN-based RequestDownload.

Request:  34 <addr_len_format> <data_format> <address> <length>
Response: 74 <max_block_size 3B>

STM32 F103 FBL flash layout:
  - Application start: 0x0800C000 (APPLICATION_ADDRESS)
  - FBL size: 32 KB (0x08000000 - 0x08007FFF)
  - APP valid flag: 0x0800A000
  - Total flash: 512 KB

From the TI log (参考):
  Tx: 10 0b 34 00 44 08 00 c0 ... 21 00 00 01 40 00 00 00
  → 34 00 44 08 00 c0 00 00 01 40 00 00 00
  Rx: 04 74 20 03 fe aa aa aa
  → max_block_size = 0x03FE (1022 bytes)

Where:
  34 00      = RequestDownload (sub-function 0x00)
  44         = addr_len_format (4B address + 4B length)
  08 00 c0 00 = address (0x0800C000) — APP 起始地址
  00 01 40 00 = length (0x00014000)
  Response: 74 20 03 FE → max_block_size = 0x03FE (1022 bytes)
"""

import sys
import struct
from can_tp_transport import CanTpTransport
from can_uds_log import CanUdsLog, check_positive_response
from can_tp_config import ADDR_LEN_FORMAT


SID = 0x34

NRC_INCORRECT_MSG_LENGTH  = 0x13
NRC_UPLOAD_DOWNLOAD_NOT_ACCEPTED = 0x70


def service_34_request_download(tp: CanTpTransport, log: CanUdsLog,
                                 data_format: int,
                                 address: int,
                                 length: int,
                                 addr_len_format: int = None) -> int:
    """
    RequestDownload – ask ECU to prepare for data download.

    Returns the max_block_size (in bytes) announced by the ECU in the
    positive response.  Callers use this as the chunk size for TransferData.

    addr_len_format: defaults to ADDR_LEN_FORMAT from config (0x44).
    """
    if addr_len_format is None:
        addr_len_format = ADDR_LEN_FORMAT

    desc = (f"0x34 – RequestDownload  "
            f"addr=0x{address:08X} len=0x{length:08X}  "
            f"fmt=0x{addr_len_format:02X} dataFmt=0x{data_format:02X}")
    log.start_test(desc)

    # FBL format: 34 <dataFormat> <addrLenFormat> <address 4B> <size 4B>
    # NOTE: No sub-function byte — the FBL parses byte[1] as dataFormatIdentifier
    req = (bytes([SID, data_format, addr_len_format])
           + struct.pack(">I", address)
           + struct.pack(">I", length))
    resp = tp.send_uds(req)

    if not check_positive_response(resp, SID, log, "RequestDownload positive response"):
        return 0

    # Parse max_block_size from response
    # FBL response format: 74 <0x20> <MSB> <LSB>
    #   74         = positive response SID
    #   0x20       = fixed format byte (always 0x20)
    #   MSB / LSB  = maxNumberOfBlockLength (16-bit big-endian)
    if len(resp) >= 4:
        max_block = (resp[2] << 8) | resp[3]   # 16-bit only!
        log.info(f"Max block size: {max_block} bytes (0x{max_block:04X})")
        return max_block
    else:
        log.error(f"RequestDownload response too short: {bytes_to_hex(resp)}")
        return 0


# --------------------------------------------------------------------------
if __name__ == "__main__":
    log = CanUdsLog("Service_34_CAN")
    tp = CanTpTransport(logger=log)
    try:
        tp.open()

        from Service_10_CAN import service_10_programming_session
        from Service_27_CAN import service_27_security_access
        from s19_parser import parse_app_image
        from can_tp_config import APP_S19_FILE

        service_10_programming_session(tp, log)
        service_27_security_access(tp, log)

        hdr, blocks = parse_app_image(APP_S19_FILE)
        log.info(f"S19 data_format: 0x{hdr.data_format_identifier:02X}")
        blk = blocks[0]
        max_block = service_34_request_download(tp, log,
                                                  data_format=hdr.data_format_identifier,
                                                  address=blk.address,
                                                  length=blk.length)
        log.info(f"Got max_block_size={max_block}")
    except Exception as e:
        log.error(str(e))
        import traceback
        traceback.print_exc()
    finally:
        tp.close()
        log.close()
        sys.exit(0 if log.all_passed else 1)
