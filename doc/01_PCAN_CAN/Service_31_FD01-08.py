#!/usr/bin/env python3
"""
Service 0x31 – RoutineControl: startRoutine FD01 (LIN)
=======================================================
Standalone script.

Request : 31 01 FD 01 01 00
Response: 71 01 FD 01 [...]

Usage:
  python Service_31_FD01.py
"""

import sys
from lin_tp_transport import LinTpTransport
from lin_uds_log import LinUdsLog, bytes_to_hex, check_positive_response

SID = 0x31


def service_31_routine_fd01(tp: LinTpTransport, log: LinUdsLog) -> bool:
    log.start_test("0x31 01 FD01 \u2013 RoutineControl startRoutine FD01")
    req  = bytes([SID, 0x01, 0xFD, 0x09, 0x05, 0x00])
    log.tx(bytes_to_hex(req), "RoutineControl startRoutine FD01")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_positive_response(resp, SID, log, "RoutineControl FD01 positive response")


def service_31_routine_fd03(tp: LinTpTransport, log: LinUdsLog) -> bool:
    log.start_test("0x31 01 FD03 \u2013 RoutineControl startRoutine FD03")
    req  = bytes([SID, 0x01, 0xFD, 0x03, 0x01, 0x01])
    log.tx(bytes_to_hex(req), "RoutineControl startRoutine FD03")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_positive_response(resp, SID, log, "RoutineControl FD03 positive response")


def service_31_routine_fd08(tp: LinTpTransport, log: LinUdsLog) -> bool:
    log.start_test("0x31 01 FD08 \u2013 RoutineControl startRoutine FD08")
    req  = bytes([0x10, 0x82, 0xFF, 0xFF, 0xFF, 0xFF])  # startRoutine, routine ID 0xFD08, param 0x00 0x01 0x00
    log.tx(bytes_to_hex(req), "RoutineControl startRoutine FD08")
    resp = tp.send_uds(req)
    log.rx(bytes_to_hex(resp))
    return check_positive_response(0x02, SID, log, "RoutineControl FD08 positive response")


if __name__ == "__main__":
    log = LinUdsLog("Service_31_FD01~08")
    tp  = LinTpTransport(logger=log)
    try:
        tp.open()
        # FD01 is an application-level routine, available in Default Session only.
        # Do NOT switch to Programming Session (10 02) – that enters FBL where FD01 does not exist.
        #service_31_routine_fd01(tp, log)
        service_31_routine_fd08(tp, log)
    except Exception as e:
        log.error(str(e))
    finally:
        tp.close()
        log.close()
        sys.exit(0 if log.all_passed else 1)
