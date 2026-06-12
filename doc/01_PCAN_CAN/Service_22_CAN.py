#!/usr/bin/env python3
"""
Service 0x22 – ReadDataByIdentifier (CAN / UDS context)
=========================================================
Standalone script for CAN-based reading data by identifier.

Request:  22 <DID 2B>
Response: 62 <DID 2B> <data...>

Common DIDs:
  0xF186 – ActiveDiagnosticSession
  0xF187 – ECUBootIdentification (boot software identification)
  0xF188 – ECUApplicationIdentification (application software identification)
  0xF1C0 – VIN
  0xF197 – SystemSupplierECUIdentification
"""

import sys
from can_tp_transport import CanTpTransport
from can_uds_log import (
    CanUdsLog,
    check_positive_response, check_negative_response,
    read_current_session,
)


SID = 0x22

# Common DIDs
DID_ACTIVE_SESSION          = 0xF186
DID_BOOT_ID                 = 0xF187
DID_APPLICATION_ID          = 0xF188
DID_VIN                     = 0xF1C0
DID_SYSTEM_SUPPLIER_ID      = 0xF197


def service_22_read_by_identifier(tp: CanTpTransport, log: CanUdsLog,
                                   did: int) -> bytes:
    """
    ReadDataByIdentifier.
    Returns the raw response bytes.
    """
    desc = f"0x22 {did:04X} – ReadDataByIdentifier"
    log.start_test(desc)

    req = bytes([SID, (did >> 8) & 0xFF, did & 0xFF])
    resp = tp.send_uds(req)

    check_positive_response(resp, SID, log, f"ReadDataByIdentifier 0x{did:04X}")
    return resp


def service_22_read_ecu_identification(tp: CanTpTransport,
                                        log: CanUdsLog) -> dict:
    """
    Read standard ECU identification DIDs.
    Returns dict of {did_name: raw_response_bytes}.
    """
    results = {}
    dids = {
        "ActiveSession":    DID_ACTIVE_SESSION,
        "BootID":           DID_BOOT_ID,
        "ApplicationID":    DID_APPLICATION_ID,
        "SystemSupplierID": DID_SYSTEM_SUPPLIER_ID,
    }

    for name, did in dids.items():
        resp = service_22_read_by_identifier(tp, log, did)
        results[name] = resp

    return results


# --------------------------------------------------------------------------
if __name__ == "__main__":
    log = CanUdsLog("Service_22_CAN")
    tp = CanTpTransport(logger=log)
    try:
        tp.open()
        service_22_read_ecu_identification(tp, log)
    except Exception as e:
        log.error(str(e))
    finally:
        tp.close()
        log.close()
        sys.exit(0 if log.all_passed else 1)
