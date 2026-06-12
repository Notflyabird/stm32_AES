#!/usr/bin/env python3
"""
PCAN-LIN 直接诊断脚本
====================
绕过 LIN TP 层，直接调用 PLinApi 进行底层验证。

功能：
  1. 检查 DLL 加载状态
  2. 枚举并显示所有 LIN 硬件信息
  3. 初始化 Master 模式
  4. 发送 LIN Wakeup 信号
  5. 发送一帧原始 LIN 报文（0x3C，UDS: 10 02 进编程会话）
  6. 轮询 0x3D 等待 ECU 回复（最多 500ms）
  7. 清理并关闭

用法：
  python pcan_lin_diag.py [--baud 19200] [--channel 1] [--nad 0x67]

Author: Generated 2026-05-08
"""

import sys
import os
import time
import argparse
from ctypes import c_ubyte, c_ushort, c_ulong, c_int

# --------------------------------------------------------------------------
# 将 DLL 目录加入搜索路径
# --------------------------------------------------------------------------
_BASE = os.path.dirname(os.path.abspath(__file__))
_DLL_DIR = os.path.join(_BASE, "DLL")
if _DLL_DIR not in sys.path:
    sys.path.insert(0, _DLL_DIR)
os.environ["PATH"] = _DLL_DIR + os.pathsep + os.environ["PATH"]

from PLinApi import (
    PLinApi,
    TLINMsg, TLINRcvMsg, TLINFrameEntry,
    HLINCLIENT, HLINHW,
    TLIN_ERROR_OK, TLIN_ERROR_RCVQUEUE_EMPTY,
    TLIN_HARDWAREMODE_MASTER,
    TLIN_CHECKSUMTYPE_CLASSIC,
    TLIN_DIRECTION_PUBLISHER, TLIN_DIRECTION_SUBSCRIBER,
    TLIN_MSGTYPE_STANDARD,
    TLIN_HARDWAREPARAM_CHANNEL_NUMBER,
    TLIN_HARDWAREPARAM_NAME,
    TLIN_HARDWAREPARAM_SERIAL_NUMBER,
    TLIN_HARDWAREPARAM_BAUDRATE,
    TLIN_HARDWAREPARAM_MODE,
    TLIN_HARDWAREPARAM_TYPE,
)


# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------
LIN_MASTER_REQ_ID  = 0x3C   # 主节点请求帧 ID（带奇偶校验后为 0x3C）
LIN_SLAVE_RESP_ID  = 0x3D   # 从节点响应帧 ID（带奇偶校验后为 0x7D）
LIN_SLAVE_RESP_PROT = 0x7D  # 0x3D 带奇偶校验


def bh(data) -> str:
    """bytes/list 转十六进制字符串"""
    return " ".join(f"{b:02X}" for b in data)


# --------------------------------------------------------------------------
# 步骤 1：DLL 加载检查
# --------------------------------------------------------------------------
def check_dll() -> PLinApi:
    print("\n[1] 检查 PLinApi.dll 加载状态...")
    plin = PLinApi()
    if not plin.isLoaded():
        print("    ✗ PLinApi.dll 加载失败！")
        print("      请确认已安装 PEAK PLIN 驱动（PCAN-USB Pro FD 驱动包）。")
        print("      下载地址: https://www.peak-system.com/PCAN-USB-Pro-FD.366.0.html")
        sys.exit(1)
    print("    ✓ PLinApi.dll 加载成功")
    return plin


# --------------------------------------------------------------------------
# 步骤 2：枚举硬件
# --------------------------------------------------------------------------
def enumerate_hardware(plin: PLinApi, target_channel: int) -> HLINHW:
    print("\n[2] 枚举 LIN 硬件...")
    hw_count = c_ushort(0)
    plin.GetAvailableHardware(HLINHW(0), c_ushort(0), hw_count)
    count = hw_count.value
    print(f"    发现硬件数量: {count}")
    if count == 0:
        print("    ✗ 未找到任何 LIN 硬件，请检查 USB 连接。")
        sys.exit(1)

    hw_array = (HLINHW * count)()
    plin.GetAvailableHardware(hw_array, c_ushort(count * 2), hw_count)

    found_hw = None
    for i in range(count):
        hw = HLINHW(hw_array[i])

        # 读取 channel 号
        ch_buf = c_int(0)
        plin.GetHardwareParam(hw, TLIN_HARDWAREPARAM_CHANNEL_NUMBER, ch_buf, c_ushort(4))

        # 读取硬件名称
        name_buf = (c_ubyte * 64)()
        plin.GetHardwareParam(hw, TLIN_HARDWAREPARAM_NAME, name_buf, c_ushort(64))
        name = bytes(name_buf).rstrip(b'\x00').decode(errors='replace')

        # 读取序列号
        sn_buf = c_ulong(0)
        plin.GetHardwareParam(hw, TLIN_HARDWAREPARAM_SERIAL_NUMBER, sn_buf, c_ushort(4))

        # 读取类型
        type_buf = c_int(0)
        plin.GetHardwareParam(hw, TLIN_HARDWAREPARAM_TYPE, type_buf, c_ushort(4))

        print(f"    [{i}] hw_handle={hw.value}  channel={ch_buf.value}"
              f"  name='{name}'  SN={sn_buf.value}  type={type_buf.value}")

        if ch_buf.value == target_channel:
            found_hw = hw

    if found_hw is None:
        print(f"    ✗ 未找到 channel={target_channel} 的硬件")
        sys.exit(1)

    print(f"    ✓ 使用 channel={target_channel}  hw_handle={found_hw.value}")
    return found_hw


# --------------------------------------------------------------------------
# 步骤 3：注册客户端 + 初始化硬件
# --------------------------------------------------------------------------
def init_hardware(plin: PLinApi, hHw: HLINHW, baud: int) -> HLINCLIENT:
    print(f"\n[3] 初始化硬件 (Master, {baud} baud)...")
    hClient = HLINCLIENT(0)

    ret = plin.RegisterClient("PCAN_LIN_DIAG", c_ulong(0), hClient)
    if ret != TLIN_ERROR_OK:
        print(f"    ✗ RegisterClient 失败: 0x{ret:08X}")
        sys.exit(1)
    print(f"    ✓ RegisterClient  hClient={hClient.value}")

    ret = plin.ConnectClient(hClient, hHw)
    if ret != TLIN_ERROR_OK:
        print(f"    ✗ ConnectClient 失败: 0x{ret:08X}")
        plin.RemoveClient(hClient)
        sys.exit(1)
    print(f"    ✓ ConnectClient")

    ret = plin.InitializeHardware(hClient, hHw, TLIN_HARDWAREMODE_MASTER, c_ushort(baud))
    if ret != TLIN_ERROR_OK:
        print(f"    ✗ InitializeHardware 失败: 0x{ret:08X}")
        plin.DisconnectClient(hClient, hHw)
        plin.RemoveClient(hClient)
        sys.exit(1)
    print(f"    ✓ InitializeHardware")

    # 注册 0x3D 为 Subscriber，接收从节点响应
    entry = TLINFrameEntry()
    entry.FrameId      = c_ubyte(LIN_SLAVE_RESP_ID)
    entry.Length       = c_ubyte(8)
    entry.Direction    = TLIN_DIRECTION_SUBSCRIBER
    entry.ChecksumType = TLIN_CHECKSUMTYPE_CLASSIC
    plin.SetFrameEntry(hClient, hHw, entry)
    plin.RegisterFrameId(hClient, hHw,
                         c_ubyte(LIN_SLAVE_RESP_ID),
                         c_ubyte(LIN_SLAVE_RESP_ID))
    print(f"    ✓ 0x3D 设置为 Subscriber")

    return hClient


# --------------------------------------------------------------------------
# 步骤 4：发送 LIN Wakeup
# --------------------------------------------------------------------------
def send_wakeup(plin: PLinApi, hClient: HLINCLIENT, hHw: HLINHW):
    print("\n[4] 发送 LIN Wakeup 信号...")
    # LIN Wakeup: 发送一帧长度为 0 的 Publisher 帧触发 break 唤醒
    # PEAK 通过 Write 一个特殊帧实现 Wakeup（长度 0，FrameId=0x00）
    wakeup = TLINMsg()
    wakeup.FrameId      = 0x00
    wakeup.Length       = c_ubyte(0)
    wakeup.Direction    = TLIN_DIRECTION_PUBLISHER
    wakeup.ChecksumType = TLIN_CHECKSUMTYPE_CLASSIC
    ret = plin.Write(hClient, hHw, wakeup)
    print(f"    Write(Wakeup) ret=0x{ret:08X}  ({'OK' if ret == TLIN_ERROR_OK else 'WARN'})")
    time.sleep(0.1)   # 等待 ECU 唤醒（100ms）


# --------------------------------------------------------------------------
# 步骤 5：发送原始 LIN 帧
# --------------------------------------------------------------------------
def send_raw_frame(plin: PLinApi, hClient: HLINCLIENT, hHw: HLINHW,
                   nad: int, uds_data: bytes) -> bool:
    payload = bytes([nad]) + bytes([len(uds_data)]) + uds_data
    payload = payload[:8].ljust(8, b'\xFF')

    msg = TLINMsg()
    msg.FrameId      = LIN_MASTER_REQ_ID   # 0x3C (protected)
    msg.Length       = c_ubyte(8)
    msg.Direction    = TLIN_DIRECTION_PUBLISHER
    msg.ChecksumType = TLIN_CHECKSUMTYPE_CLASSIC
    for i, b in enumerate(payload):
        msg.Data[i] = b

    print(f"\n[5] 发送 LIN 帧 (0x3C): {bh(payload)}")
    ret = plin.Write(hClient, hHw, msg)
    print(f"    Write ret=0x{ret:08X}  ({'OK' if ret == TLIN_ERROR_OK else 'FAIL'})")
    return ret == TLIN_ERROR_OK


# --------------------------------------------------------------------------
# 步骤 6：轮询等待 ECU 回复
# --------------------------------------------------------------------------
def poll_response(plin: PLinApi, hClient: HLINCLIENT, hHw: HLINHW,
                  nad: int, timeout_ms: int = 500) -> bytes | None:
    print(f"\n[6] 轮询 ECU 回复 (0x7D, timeout={timeout_ms}ms)...")
    rcv      = TLINRcvMsg()
    deadline = time.time() + timeout_ms / 1000.0
    poll_cnt = 0

    while time.time() < deadline:
        # 发送 0x7D subscriber header，让从节点有机会响应
        req = TLINMsg()
        req.FrameId      = LIN_SLAVE_RESP_PROT  # 0x7D
        req.Length       = c_ubyte(8)
        req.Direction    = TLIN_DIRECTION_SUBSCRIBER
        req.ChecksumType = TLIN_CHECKSUMTYPE_CLASSIC
        plin.Write(hClient, hHw, req)
        poll_cnt += 1

        # 读取接收队列
        poll_end = time.time() + 0.020
        while time.time() < poll_end:
            ret = plin.Read(hClient, rcv)
            if ret == TLIN_ERROR_OK:
                raw_id   = rcv.FrameId & 0x3F
                err_flag = rcv.ErrorFlags
                print(f"    Read: id=0x{rcv.FrameId:02X}(raw=0x{raw_id:02X})"
                      f"  type={rcv.Type}  err=0x{err_flag:X}"
                      f"  data={bh(list(rcv.Data))}")
                if raw_id == LIN_SLAVE_RESP_ID and err_flag == 0:
                    data = list(rcv.Data)
                    if data[0] == nad:
                        print(f"    ✓ 收到 ECU 响应 (NAD=0x{nad:02X}): {bh(data)}")
                        return bytes(data)
            time.sleep(0.002)

    print(f"    ✗ 超时未收到响应（共发送 {poll_cnt} 次轮询头）")
    return None


# --------------------------------------------------------------------------
# 步骤 7：清理
# --------------------------------------------------------------------------
def cleanup(plin: PLinApi, hClient: HLINCLIENT, hHw: HLINHW):
    print("\n[7] 关闭连接...")
    plin.DisconnectClient(hClient, hHw)
    plin.RemoveClient(hClient)
    print("    ✓ 已关闭")


# --------------------------------------------------------------------------
# 主程序
# --------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="PCAN-LIN 底层诊断通信脚本")
    parser.add_argument("--baud",    type=lambda x: int(x, 0), default=19200,
                        help="LIN 波特率 (默认 19200)")
    parser.add_argument("--channel", type=int, default=1,
                        help="LIN 通道号 (默认 1)")
    parser.add_argument("--nad",     type=lambda x: int(x, 0), default=0x67,
                        help="目标 NAD (默认 0x67)")
    parser.add_argument("--uds",     type=str, default="10 02",
                        help="要发送的 UDS 数据（十六进制，空格分隔，默认: '10 02'）")
    args = parser.parse_args()

    uds_bytes = bytes(int(x, 16) for x in args.uds.split())

    print("=" * 60)
    print("PCAN-LIN 底层诊断通信脚本")
    print(f"  baud={args.baud}  channel={args.channel}"
          f"  NAD=0x{args.nad:02X}  UDS={bh(uds_bytes)}")
    print("=" * 60)

    plin    = check_dll()
    hHw     = enumerate_hardware(plin, args.channel)
    hClient = init_hardware(plin, hHw, args.baud)

    try:
        send_wakeup(plin, hClient, hHw)
        ok = send_raw_frame(plin, hClient, hHw, args.nad, uds_bytes)
        if ok:
            resp = poll_response(plin, hClient, hHw, args.nad, timeout_ms=500)
            if resp is None:
                print("\n>>> 诊断结论：硬件正常，总线无响应。")
                print("    可能原因：")
                print("    1. ECU 未上电 / LIN 总线未接线")
                print("    2. NAD 不匹配（当前 0x{:02X}）".format(args.nad))
                print("    3. 波特率不匹配（当前 {:d} baud）".format(args.baud))
                print("    4. ECU 处于 Sleep，需要更长 Wakeup 等待时间")
            else:
                print("\n>>> 通信成功！")
    finally:
        cleanup(plin, hClient, hHw)


if __name__ == "__main__":
    main()
