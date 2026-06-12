#!/usr/bin/env python3
"""
Service 0x36 – TransferData (LIN)
===================================
Request : 36 <blockSeqCounter> <data chunk>
Response: 76 <blockSeqCounter>

blockSeqCounter wraps 1..0xFF.

NRC test cases (ref: Service_34_36_37_SBL.py):
  NRC 0x13 – incorrectMessageLength  (36 only, no seq/data bytes)
  NRC 0x24 – requestSequenceError    (36 without prior 34)
  NRC 0x71 – transferDataSuspended   (wrong seq counter)
  NRC 0x73 – wrongBlockSequenceCounter
"""

import sys
import time
from lin_tp_transport import LinTpTransport
from lin_uds_log import LinUdsLog, bytes_to_hex, check_positive_response, check_negative_response
from lin_tp_config import VBF_FILE

SID_TD = 0x36

NRC_INCORRECT_MSG_LENGTH      = 0x13
NRC_REQUEST_SEQUENCE_ERROR    = 0x24
NRC_TRANSFER_DATA_SUSPENDED   = 0x71
NRC_WRONG_BLOCK_SEQ_COUNTER   = 0x73


# --------------------------------------------------------------------------
# Positive – TransferData
# --------------------------------------------------------------------------
def service_36_transfer_data(tp: LinTpTransport, log: LinUdsLog,
                              block_seq: int, chunk: bytes) -> bool:
    """Send one 0x36 data chunk. block_seq wraps 1..0xFF."""
    req = bytes([SID_TD, block_seq]) + chunk
    log.tx(bytes_to_hex(req[:16]) + ("..." if len(req) > 16 else ""),
           f"TransferData block={block_seq} len={len(chunk)}")
    resp = tp.send_uds(req, frame_delay_s=0.010)   # 10 ms inter-frame for 0x36
    log.rx(bytes_to_hex(resp))

    passed = check_positive_response(resp, SID_TD, log,
                                     f"TransferData block={block_seq}")
    if passed and len(resp) >= 2:
        if resp[1] != block_seq:
            log.error(f"Block seq mismatch: sent {block_seq}, got {resp[1]}")
            return False
    return passed


# --------------------------------------------------------------------------
# NRC 0x13 – incorrectMessageLength (36 only, no seq/data)
# --------------------------------------------------------------------------
def service_36_nrc13_too_short(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """
    Send 36 with only SID, no blockSeqCounter or data.
    Requires a prior valid 34 to be in transfer state.
    """
    log.start_test("0x36 – NRC 0x13 incorrectMessageLength (SID only, 1 byte)")
    req  = bytes([SID_TD])
    log.tx(bytes_to_hex(req), "TransferData length=1 (too short, no seq/data)")
    resp = tp.send_uds(req, frame_delay_s=0.010)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID_TD, NRC_INCORRECT_MSG_LENGTH, log,
                                   "NRC 0x13 for length=1")


# --------------------------------------------------------------------------
# NRC 0x24 – requestSequenceError (36 without prior 34)
# --------------------------------------------------------------------------
def service_36_nrc24_no_prior_34(tp: LinTpTransport, log: LinUdsLog) -> bool:
    """Send 36 without a preceding 34 → NRC 0x24."""
    log.start_test("0x36 – NRC 0x24 requestSequenceError (no prior 34)")
    req  = bytes([SID_TD, 0x01, 0xFF])
    log.tx(bytes_to_hex(req), "TransferData block=1 (no prior RequestDownload)")
    resp = tp.send_uds(req, frame_delay_s=0.010)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID_TD, NRC_REQUEST_SEQUENCE_ERROR, log,
                                   "NRC 0x24 requestSequenceError")


# --------------------------------------------------------------------------
# NRC 0x73 – wrongBlockSequenceCounter
# --------------------------------------------------------------------------
def service_36_nrc73_wrong_seq(tp: LinTpTransport, log: LinUdsLog,
                                chunk: bytes) -> bool:
    """
    After a valid 34, send block_seq=0xFF (instead of expected 0x01).
    ECU should reject with NRC 0x73.
    Requires the caller to have issued a valid 34 beforehand.
    """
    log.start_test("0x36 – NRC 0x73 wrongBlockSequenceCounter (seq=0xFF instead of 0x01)")
    req  = bytes([SID_TD, 0xFF]) + chunk
    log.tx(bytes_to_hex(req[:16]) + ("..." if len(req) > 16 else ""),
           "TransferData wrong seq=0xFF")
    resp = tp.send_uds(req, frame_delay_s=0.010)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID_TD, NRC_WRONG_BLOCK_SEQ_COUNTER, log,
                                   "NRC 0x73 wrongBlockSequenceCounter")


# --------------------------------------------------------------------------
# NRC 0x24 – requestSequenceError (seq jumps mid-transfer)
# --------------------------------------------------------------------------
def service_36_nrc24_seq_jump(tp: LinTpTransport, log: LinUdsLog,
                               chunk: bytes) -> bool:
    """
    After sending block_seq=1 successfully, skip to block_seq=0xF7 (non-sequential).
    ECU returns NRC 0x24 (requestSequenceError) for wrong seq counter mid-transfer.
    Requires the caller to have issued a valid 34 and one correct 36 (seq=1).
    """
    log.start_test("0x36 – NRC 0x24 requestSequenceError (seq jump to 0xF7 after seq=1)")
    req  = bytes([SID_TD, 0xF7]) + chunk
    log.tx(bytes_to_hex(req[:16]) + ("..." if len(req) > 16 else ""),
           "TransferData seq jump 0xF7")
    resp = tp.send_uds(req, frame_delay_s=0.010)
    log.rx(bytes_to_hex(resp))
    return check_negative_response(resp, SID_TD, NRC_REQUEST_SEQUENCE_ERROR, log,
                                   "NRC 0x24 requestSequenceError (seq jump)")


# --------------------------------------------------------------------------
if __name__ == "__main__":
    from lin_tp_vbf_parser import parse_vbf
    from lin_tp_config import DEFAULT_BLOCK_SIZE
    log = LinUdsLog("Service_36")
    tp  = LinTpTransport(logger=log)
    try:
        tp.open()
        hdr, blocks = parse_vbf(VBF_FILE)
        blk         = blocks[0]
        data_format = hdr.data_format_identifier
        erase_addr, erase_len = hdr.erase_regions[0]
        dummy_chunk = bytes([0xFF])   # minimal data for NRC tests

        from Service_10 import service_10_programming_session
        from Service_27 import service_27_security_access
        from Service_31_Erase import service_31_erase_memory
        from Service_34 import service_34_request_download
        from Service_37 import service_37_transfer_exit

        log.info("=" * 60)
        log.info("Service 0x36 TransferData – Full NRC Test")
        log.info("=" * 60)

        # ------------------------------------------------------------------
        # NRC 0x24 – requestSequenceError (no prior 34, fresh session)
        # ------------------------------------------------------------------
        log.info("--- NRC 0x24: requestSequenceError (no prior 34) ---")
        service_10_programming_session(tp, log)
        service_27_security_access(tp, log)
        service_36_nrc24_no_prior_34(tp, log)

        # ------------------------------------------------------------------
        # Prepare: erase + 34 for remaining NRC tests
        # ------------------------------------------------------------------
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
        first_chunk = blk.data[:chunk_size]

        # ------------------------------------------------------------------
        # NRC 0x13 – incorrectMessageLength (36 SID only, inside transfer)
        # ------------------------------------------------------------------
        log.info("--- NRC 0x13: incorrectMessageLength (SID only) ---")
        service_36_nrc13_too_short(tp, log)

        # ------------------------------------------------------------------
        # NRC 0x73 – wrongBlockSequenceCounter (seq=0xFF, expected 0x01)
        # ------------------------------------------------------------------
        log.info("--- NRC 0x73: wrongBlockSequenceCounter ---")
        service_36_nrc73_wrong_seq(tp, log, dummy_chunk)

        # ------------------------------------------------------------------
        # Send seq=1 correctly, then test NRC 0x71 (seq jump)
        # ------------------------------------------------------------------
        log.info("--- Send block=1 (valid), then NRC 0x71: transferDataSuspended ---")
        log.start_test("0x36 block=1  offset=0 (valid, prepare for NRC 0x24 seq jump)")
        service_36_transfer_data(tp, log, 1, first_chunk)

        service_36_nrc24_seq_jump(tp, log, dummy_chunk)

        # Close this transfer session
        service_37_transfer_exit(tp, log)

        # ------------------------------------------------------------------
        # Positive – full TransferData for block 1
        # ------------------------------------------------------------------
        log.info("--- Positive Test: TransferData (block 1, nominal) ---")
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
        service_37_transfer_exit(tp, log)

    except Exception as e:
        log.error(str(e))
        import traceback; traceback.print_exc()
    finally:
        tp.close()
        log.close()
        sys.exit(0 if log.all_passed else 1)

