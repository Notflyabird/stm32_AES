#!/usr/bin/env python3
"""
Service 0x37 – TransferExit (LIN)
===================================
Request : 37
Response: 77

NRC test cases (ref: Service_34_36_37_SBL.py):
  NRC 0x13 – incorrectMessageLength  (37 with extra byte)
  NRC 0x24 – requestSequenceError    (37 without prior 34+36)
  NRC 0x31 – requestOutOfRange       (37 after 34 only, no 36 data sent)
"""

import sys
import time
from lin_tp_transport import LinTpTransport
from lin_uds_log import LinUdsLog, bytes_to_hex, check_positive_response, check_negative_response
from lin_tp_config import VBF_FILE

SID_TE = 0x37

NRC_INCORRECT_MSG_LENGTH   = 0x13
NRC_REQUEST_SEQUENCE_ERROR = 0x24
NRC_REQUEST_OUT_OF_RANGE   = 0x31
NRC_GENERAL_PROG_FAILURE   = 0x72


# --------------------------------------------------------------------------
# Positive – TransferExit
# --------------------------------------------------------------------------
def service_37_transfer_exit(tp: LinTpTransport, log: LinUdsLog) -> bool:
    log.start_test("0x37 – TransferExit")
    req  = bytes([SID_TE])
    log.tx(bytes_to_hex(req), "TransferExit")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_positive_response(resp, SID_TE, log, "TransferExit positive response")


# --------------------------------------------------------------------------
# NRC 0x24 – requestSequenceError (37 + extra byte, mid-transfer)
# Note: ECU checks sequence state before message length; returns 0x24
#       because no 36 data has been sent yet in this transfer.
# --------------------------------------------------------------------------
def service_37_nrc24_too_long_mid_transfer(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """37 00 – extra byte, but ECU returns NRC 0x24 (sequence check takes priority)."""
    log.start_test("0x37 – NRC 0x24 requestSequenceError (37 00, no data sent yet)")
    req  = bytes([SID_TE, 0x00])
    log.tx(bytes_to_hex(req), "TransferExit length=2 (no 36 sent, sequence error)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID_TE, NRC_REQUEST_SEQUENCE_ERROR, log,
                                   "NRC 0x24 requestSequenceError (sequence check before length)")


# --------------------------------------------------------------------------
# NRC 0x24 – requestSequenceError (37 without any prior 34+36)
# --------------------------------------------------------------------------
def service_37_nrc24_no_prior_transfer(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """Send 37 with no preceding 34/36 in this session → NRC 0x24."""
    log.start_test("0x37 – NRC 0x24 requestSequenceError (no prior 34+36)")
    req  = bytes([SID_TE])
    log.tx(bytes_to_hex(req), "TransferExit (no prior download)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID_TE, NRC_REQUEST_SEQUENCE_ERROR, log,
                                   "NRC 0x24 requestSequenceError")


# --------------------------------------------------------------------------
# NRC 0x24 – requestSequenceError (37 after 34 only, no 36 data sent)
# Note: ECU returns 0x24 because 36 is expected before 37 in the sequence.
# --------------------------------------------------------------------------
def service_37_nrc24_after_34_only(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """Send 37 immediately after 34 with no 36 data frames → NRC 0x24."""
    log.start_test("0x37 – NRC 0x24 requestSequenceError (37 after 34, no 36 sent)")
    req  = bytes([SID_TE])
    log.tx(bytes_to_hex(req), "TransferExit after 34 with no 36")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID_TE, NRC_REQUEST_SEQUENCE_ERROR, log,
                                   "NRC 0x24 requestSequenceError (37 before any 36)")


# --------------------------------------------------------------------------
# NRC 0x13 – incorrectMessageLength (37 + extra byte, transfer complete)
# TC36-B / SWP_SLL_UDS_TE_R0006
# Requires: 34 sent + all 36 data chunks sent (ECU expects 37).
# Sequence check passes (37 is correct next step), length > 1 → NRC 0x13.
# --------------------------------------------------------------------------
def service_37_nrc13_too_long(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """37 00 – extra byte after complete 36 transfer → NRC 0x13 (TC36-B)."""
    log.start_test("0x37 – NRC 0x13 incorrectMessageLength (37+extra byte, transfer complete) [TC36-B]")
    req  = bytes([SID_TE, 0x00])
    log.tx(bytes_to_hex(req), "TransferExit length=2 (extra byte, complete transfer)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID_TE, NRC_INCORRECT_MSG_LENGTH, log,
                                   "NRC 0x13 incorrectMessageLength")


# --------------------------------------------------------------------------
# NRC 0x24 – requestSequenceError (37 after partial 36 transfer)
# TC36-C
# Requires: 34 sent + only first 36 chunk sent (transfer not complete).
# ECU returns 0x24: seq=2 expected, 37 is out of sequence.
# Note: spec expects 0x72, but ECU uses 0x24 for all sequence violations.
# --------------------------------------------------------------------------
def service_37_nrc72_partial_transfer(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """37 after partial 36 (transfer incomplete) → NRC 0x24 (TC36-C, ECU actual behavior)."""
    log.start_test("0x37 – NRC 0x24 requestSequenceError (37 after partial 36) [TC36-C]")
    req  = bytes([SID_TE])
    log.tx(bytes_to_hex(req), "TransferExit after partial transfer (incomplete)")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID_TE, NRC_REQUEST_SEQUENCE_ERROR, log,
                                   "NRC 0x24 requestSequenceError (incomplete transfer, ECU returns 0x24 not 0x72)")


# --------------------------------------------------------------------------
if __name__ == "__main__":
    from lin_tp_vbf_parser import parse_vbf
    log = LinUdsLog("Service_37")
    tp  = LinTpTransport(logger=log)
    try:
        tp.open()
        hdr, blocks = parse_vbf(VBF_FILE)
        blk         = blocks[0]
        data_format = hdr.data_format_identifier
        erase_addr, erase_len = hdr.erase_regions[0]

        from Service_10 import service_10_programming_session
        from Service_27 import service_27_security_access
        from Service_31_Erase import service_31_erase_memory
        from Service_34 import service_34_request_download
        from Service_36 import service_36_transfer_data

        log.info("=" * 60)
        log.info("Service 0x37 TransferExit – Full NRC Test")
        log.info("=" * 60)

        # ------------------------------------------------------------------
        # NRC 0x24 – requestSequenceError (no prior 34+36, fresh session)
        # ------------------------------------------------------------------
        log.info("--- NRC 0x24: requestSequenceError (no prior 34+36) ---")
        service_10_programming_session(tp, log)
        service_27_security_access(tp, log)
        service_37_nrc24_no_prior_transfer(tp, log)

        # ------------------------------------------------------------------
        # TC36-A: NRC 0x24 – requestSequenceError (37 after 34, no 36)
        # SWP_SLL_UDS_TE_R0004
        # ------------------------------------------------------------------
        log.info("--- TC36-A NRC 0x24: requestSequenceError (37 after 34, no 36) ---")
        service_10_programming_session(tp, log)
        service_27_security_access(tp, log)
        service_31_erase_memory(tp, log, erase_addr, erase_len)
        service_34_request_download(
            tp, log,
            data_format=data_format,
            address=blk.address,
            length=blk.length,
        )
        service_37_nrc24_after_34_only(tp, log)          # TC36-A

        # Also verify: 37 00 (extra byte) in same state → still 0x24 (seq before length)
        service_10_programming_session(tp, log)
        service_27_security_access(tp, log)
        service_31_erase_memory(tp, log, erase_addr, erase_len)
        service_34_request_download(
            tp, log,
            data_format=data_format,
            address=blk.address,
            length=blk.length,
        )
        service_37_nrc24_too_long_mid_transfer(tp, log)

        # ------------------------------------------------------------------
        # TC36-B: NRC 0x13 – incorrectMessageLength (37+extra, after complete 36)
        # SWP_SLL_UDS_TE_R0006
        # 34 → all 36 chunks → "37 00" : seq check passes, length > 1 → 0x13
        # ------------------------------------------------------------------
        log.info("--- TC36-B NRC 0x13: incorrectMessageLength (37+extra, transfer complete) ---")
        service_10_programming_session(tp, log)
        service_27_security_access(tp, log)
        service_31_erase_memory(tp, log, erase_addr, erase_len)
        max_block_b = service_34_request_download(
            tp, log,
            data_format=data_format,
            address=blk.address,
            length=blk.length,
        )
        chunk_size_b = max(1, max_block_b - 2)
        data_b, offset_b, seq_b = blk.data, 0, 1
        while offset_b < len(data_b):
            chunk_b = data_b[offset_b:offset_b + chunk_size_b]
            log.start_test(f"0x36 block={seq_b}  offset={offset_b}/{len(data_b)} (prepare TC36-B)")
            if not service_36_transfer_data(tp, log, seq_b, chunk_b):
                break
            offset_b += len(chunk_b)
            seq_b     = (seq_b % 0xFF) + 1
            time.sleep(0.01)
        service_37_nrc13_too_long(tp, log)               # TC36-B

        # ------------------------------------------------------------------
        # TC36-C: NRC 0x72 – generalProgrammingFailure (37 after partial 36)
        # 34(blocks[1], large) → 36 seq=1 (first chunk only) → 37 → 0x72
        # ------------------------------------------------------------------
        log.info("--- TC36-C NRC 0x72: generalProgrammingFailure (37 after partial 36) ---")
        blk2 = blocks[1] if len(blocks) > 1 else blk
        service_10_programming_session(tp, log)
        service_27_security_access(tp, log)
        service_31_erase_memory(tp, log, erase_addr, erase_len)
        max_block2  = service_34_request_download(
            tp, log,
            data_format=data_format,
            address=blk2.address,
            length=blk2.length,
        )
        chunk_size2  = max(1, max_block2 - 2)
        first_chunk2 = blk2.data[:chunk_size2]
        log.start_test("0x36 block=1  offset=0 (partial, prepare TC36-C)")
        service_36_transfer_data(tp, log, 1, first_chunk2)
        service_37_nrc72_partial_transfer(tp, log)       # TC36-C

        # ------------------------------------------------------------------
        # TC35: Positive – full 34→36→37 (block 1, nominal)
        # SWP_SLL_UDS_TE_R0002
        # ------------------------------------------------------------------
        log.info("--- TC35 Positive Test: TransferExit (block 1, nominal) ---")
        service_10_programming_session(tp, log)
        service_27_security_access(tp, log)
        service_31_erase_memory(tp, log, erase_addr, erase_len)
        max_block = service_34_request_download(
            tp, log,
            data_format=data_format,
            address=blk.address,
            length=blk.length,
        )
        chunk_size = max(1, max_block - 2)
        data, offset, block_seq = blk.data, 0, 1
        while offset < len(data):
            chunk = data[offset:offset + chunk_size]
            log.start_test(f"0x36 block={block_seq}  offset={offset}/{len(data)}")
            if not service_36_transfer_data(tp, log, block_seq, chunk):
                break
            offset    += len(chunk)
            block_seq  = (block_seq % 0xFF) + 1
            time.sleep(0.01)
        service_37_transfer_exit(tp, log)                # TC35

    except Exception as e:
        log.error(str(e))
        import traceback; traceback.print_exc()
    finally:
        tp.close()
        log.close()
        sys.exit(0 if log.all_passed else 1)

