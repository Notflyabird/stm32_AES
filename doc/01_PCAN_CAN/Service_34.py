#!/usr/bin/env python3
"""
Service 0x34 – RequestDownload (LIN)
=====================================
Request : 34 [dataFormatId] [addrLenFmt] <address 4B> <length 4B>
Response: 74 [lengthFmtId] <maxBlockLen>

NRC test cases (ref: Service_34_36_37_SBL.py):
  NRC 0x13 – incorrectMessageLength
  NRC 0x22 – conditionsNotCorrect  (34→36→34, re-request during transfer)
  NRC 0x31 – requestOutOfRange     (invalid addrLenFmt / out-of-range address)
  NRC 0x33 – securityAccessDenied  (no SA)
  NRC 0x70 – uploadDownloadNotAccepted (non-erased area / double download)
"""

import sys
import struct
from lin_tp_transport import LinTpTransport
from lin_uds_log import LinUdsLog, bytes_to_hex, check_positive_response, check_negative_response
from lin_tp_config import VBF_FILE, ADDR_LEN_FORMAT, DEFAULT_BLOCK_SIZE

SID_RD = 0x34

NRC_INCORRECT_MSG_LENGTH        = 0x13
NRC_CONDITIONS_NOT_CORRECT      = 0x22
NRC_REQUEST_OUT_OF_RANGE        = 0x31
NRC_SECURITY_ACCESS_DENIED      = 0x33
NRC_UPLOAD_DOWNLOAD_NOT_ACCEPTED = 0x70


# --------------------------------------------------------------------------
# Positive – RequestDownload
# --------------------------------------------------------------------------
def service_34_request_download(tp: LinTpTransport, log: LinUdsLog,
                                 data_format: int,
                                 address: int, length: int) -> int:
    """
    Send RequestDownload. Returns max block length from ECU response.
    Raises RuntimeError on failure.
    """
    desc = (f"0x34 – RequestDownload  "
            f"addr=0x{address:08X}  len=0x{length:08X}  fmt=0x{data_format:02X}")
    log.start_test(desc)

    req = (bytes([SID_RD, data_format, ADDR_LEN_FORMAT])
           + struct.pack(">I", address)
           + struct.pack(">I", length))
    log.tx(bytes_to_hex(req), "RequestDownload")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))

    if not check_positive_response(resp, SID_RD, log, "RequestDownload positive response"):
        raise RuntimeError(f"RequestDownload failed: {bytes_to_hex(resp)}")

    # Parse max block length: 74 [lengthFmtId] [maxBlockLen...]
    # high nibble of lengthFmtId = byte count of maxBlockLen field
    if len(resp) < 3:
        return DEFAULT_BLOCK_SIZE

    length_fmt = resp[1]
    num_bytes  = (length_fmt >> 4) & 0x0F
    max_block  = 0
    for i in range(num_bytes):
        max_block = (max_block << 8) | resp[2 + i]

    log.info(f"ECU max block size: 0x{max_block:X} ({max_block}) bytes")
    return max_block if max_block > 0 else DEFAULT_BLOCK_SIZE


# --------------------------------------------------------------------------
# NRC 0x13 – incorrectMessageLength
# --------------------------------------------------------------------------
def service_34_nrc13_too_short(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """34 00 – only 2 bytes, missing addrLenFmt / address / length."""
    log.start_test("0x34 – NRC 0x13 incorrectMessageLength (2 bytes, too short)")
    req  = bytes([SID_RD, 0x10])
    log.tx(bytes_to_hex(req), "RequestDownload length=2 (too short)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID_RD, NRC_INCORRECT_MSG_LENGTH, log,
                                   "NRC 0x13 for length=2")


def service_34_nrc13_one_byte_short(tp: LinTpTransport, log: LinUdsLog,
                                    data_format: int,
                                    address: int, length: int) -> bool:
    """34 fmt 44 <addr 4B> <len 3B> – 10 bytes, last byte of length missing."""
    log.start_test("0x34 – NRC 0x13 incorrectMessageLength (10 bytes, 1 byte short)")
    full = (bytes([SID_RD, data_format, ADDR_LEN_FORMAT])
            + struct.pack(">I", address)
            + struct.pack(">I", length))
    req  = full[:10]   # drop last byte
    log.tx(bytes_to_hex(req), "RequestDownload length=10 (too short)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID_RD, NRC_INCORRECT_MSG_LENGTH, log,
                                   "NRC 0x13 for length=10")


# --------------------------------------------------------------------------
# NRC 0x22 – conditionsNotCorrect (34→36→34, re-request during transfer)
# --------------------------------------------------------------------------
def service_34_nrc22_reenter_during_transfer(tp: LinTpTransport, log: LinUdsLog,
                                              data_format: int,
                                              address: int, length: int) -> bool:
    """
    Start 34→send one 36 chunk→send 34 again without 37 exit.
    ECU should reject the second 34 with NRC 0x22.
    """
    log.start_test("0x34 – NRC 0x22 conditionsNotCorrect (34→36→34 without TransferExit)")

    # Step 1: valid 34
    req1 = (bytes([SID_RD, data_format, ADDR_LEN_FORMAT])
            + struct.pack(">I", address)
            + struct.pack(">I", length))
    log.tx(bytes_to_hex(req1), "RequestDownload (step 1)")
    resp1 = tp.send_uds(req1)
    log.rx(bytes_to_hex(resp1))
    if not (len(resp1) >= 1 and resp1[0] == 0x74):
        log.error("Step 1 RequestDownload failed – cannot proceed with NRC22 test")
        return False

    # Step 2: send one dummy 36 chunk (1 byte of data)
    req2 = bytes([0x36, 0x01, 0xFF])
    log.tx(bytes_to_hex(req2), "TransferData block=1 (dummy, step 2)")
    resp2 = tp.send_uds(req2)
    log.rx(bytes_to_hex(resp2))

    # Step 3: send 34 again – expect NRC 0x22
    req3 = (bytes([SID_RD, data_format, ADDR_LEN_FORMAT])
            + struct.pack(">I", address)
            + struct.pack(">I", length))
    log.tx(bytes_to_hex(req3), "RequestDownload (step 3, re-enter → NRC 0x22)")
    resp3 = tp.send_uds(req3)
    log.rx(bytes_to_hex(resp3))
    return check_negative_response(resp3, SID_RD, NRC_CONDITIONS_NOT_CORRECT, log,
                                   "NRC 0x22 conditionsNotCorrect (re-enter during transfer)")


# --------------------------------------------------------------------------
# NRC 0x31 – requestOutOfRange
# --------------------------------------------------------------------------
def service_34_nrc31_invalid_addr_len_fmt(tp: LinTpTransport, log: LinUdsLog,
                                           address: int, length: int) -> bool:
    """34 10 02 ... – addrLenFmt=0x02 is invalid (not 0x44)."""
    log.start_test("0x34 – NRC 0x31 requestOutOfRange (invalid addrLenFmt 0x02)")
    req = (bytes([SID_RD, 0x10, 0x02])
           + struct.pack(">I", address)
           + struct.pack(">I", length))
    log.tx(bytes_to_hex(req), "RequestDownload invalid addrLenFmt=0x02")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID_RD, NRC_REQUEST_OUT_OF_RANGE, log,
                                   "NRC 0x31 for invalid addrLenFmt 0x02")


def service_34_nrc31_out_of_range_address(tp: LinTpTransport, log: LinUdsLog,
                                           data_format: int) -> bool:
    """34 fmt 44 FFFFFF00 00000060 – address outside valid flash region."""
    log.start_test("0x34 – NRC 0x31 requestOutOfRange (address 0xFFFFFF00 out of range)")
    req = (bytes([SID_RD, data_format, ADDR_LEN_FORMAT])
           + struct.pack(">I", 0xFFFFFF00)
           + struct.pack(">I", 0x00000060))
    log.tx(bytes_to_hex(req), "RequestDownload out-of-range address 0xFFFFFF00")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID_RD, NRC_REQUEST_OUT_OF_RANGE, log,
                                   "NRC 0x31 for out-of-range address 0xFFFFFF00")


# --------------------------------------------------------------------------
# NRC 0x33 – securityAccessDenied (no SA unlock)
# --------------------------------------------------------------------------
def service_34_nrc33_no_sa(tp: LinTpTransport, log: LinUdsLog,
                            data_format: int,
                            address: int, length: int) -> bool:
    """Send 34 without security access unlocked → NRC 0x33."""
    log.start_test("0x34 – NRC 0x33 securityAccessDenied (no SA)")
    req = (bytes([SID_RD, data_format, ADDR_LEN_FORMAT])
           + struct.pack(">I", address)
           + struct.pack(">I", length))
    log.tx(bytes_to_hex(req), "RequestDownload (no security access)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID_RD, NRC_SECURITY_ACCESS_DENIED, log,
                                   "NRC 0x33 securityAccessDenied")


# --------------------------------------------------------------------------
# NRC 0x70 – uploadDownloadNotAccepted (non-erased / double download)
# --------------------------------------------------------------------------
def service_34_nrc70_non_erased(tp: LinTpTransport, log: LinUdsLog,
                                 data_format: int,
                                 address: int, length: int) -> bool:
    """Send 34 to a region that has NOT been erased → NRC 0x70."""
    log.start_test("0x34 – NRC 0x70 uploadDownloadNotAccepted (non-erased region)")
    req = (bytes([SID_RD, data_format, ADDR_LEN_FORMAT])
           + struct.pack(">I", address)
           + struct.pack(">I", length))
    log.tx(bytes_to_hex(req), "RequestDownload to non-erased region")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID_RD, NRC_UPLOAD_DOWNLOAD_NOT_ACCEPTED, log,
                                   "NRC 0x70 uploadDownloadNotAccepted (non-erased)")


# --------------------------------------------------------------------------
if __name__ == "__main__":
    from lin_tp_vbf_parser import parse_vbf
    log = LinUdsLog("Service_34")
    tp  = LinTpTransport(logger=log)
    try:
        tp.open()
        hdr, blocks = parse_vbf(VBF_FILE)
        address     = blocks[0].address
        length      = blocks[0].length
        data_format = hdr.data_format_identifier
        erase_addr, erase_len = hdr.erase_regions[0]

        from Service_10 import service_10_programming_session
        from Service_27 import service_27_security_access
        from Service_31_Erase import service_31_erase_memory

        log.info("=" * 60)
        log.info("Service 0x34 RequestDownload – Full NRC Test")
        log.info("=" * 60)

        # ------------------------------------------------------------------
        # NRC 0x33 – securityAccessDenied (must be before SA unlock)
        # ------------------------------------------------------------------
        log.info("--- NRC 0x33: securityAccessDenied (no SA) ---")
        service_10_programming_session(tp, log)
        service_34_nrc33_no_sa(tp, log, data_format, address, length)

        # ------------------------------------------------------------------
        # NRC 0x70 – uploadDownloadNotAccepted (non-erased, before erase)
        # ------------------------------------------------------------------
        log.info("--- NRC 0x70: uploadDownloadNotAccepted (non-erased region) ---")
        service_10_programming_session(tp, log)
        service_27_security_access(tp, log)
        service_34_nrc70_non_erased(tp, log, data_format, address, length)

        # ------------------------------------------------------------------
        # NRC 0x13 – incorrectMessageLength
        # ------------------------------------------------------------------
        log.info("--- NRC 0x13: incorrectMessageLength ---")
        service_10_programming_session(tp, log)
        service_27_security_access(tp, log)
        service_31_erase_memory(tp, log, erase_addr, erase_len)
        service_34_nrc13_too_short(tp, log)
        service_34_nrc13_one_byte_short(tp, log, data_format, address, length)

        # ------------------------------------------------------------------
        # NRC 0x31 – requestOutOfRange
        # ------------------------------------------------------------------
        log.info("--- NRC 0x31: requestOutOfRange ---")
        service_34_nrc31_invalid_addr_len_fmt(tp, log, address, length)
        service_34_nrc31_out_of_range_address(tp, log, data_format)

        # ------------------------------------------------------------------
        # NRC 0x22 – conditionsNotCorrect (34→36→34)
        # ------------------------------------------------------------------
        log.info("--- NRC 0x22: conditionsNotCorrect (re-enter during transfer) ---")
        service_34_nrc22_reenter_during_transfer(tp, log, data_format, address, length)

        # ------------------------------------------------------------------
        # Positive – nominal RequestDownload (first block only; full
        # 34→36→37 sequence is covered by Service_34_36_37.py)
        # ------------------------------------------------------------------
        log.info("--- Positive Test: RequestDownload (block 1 only) ---")
        service_10_programming_session(tp, log)
        service_27_security_access(tp, log)
        service_31_erase_memory(tp, log, erase_addr, erase_len)
        blk = blocks[0]
        service_34_request_download(
            tp, log,
            data_format=data_format,
            address=blk.address,
            length=blk.length,
        )

    except Exception as e:
        log.error(str(e))
        import traceback; traceback.print_exc()
    finally:
        tp.close()
        log.close()
        sys.exit(0 if log.all_passed else 1)
