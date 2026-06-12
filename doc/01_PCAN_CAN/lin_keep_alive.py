#!/usr/bin/env python3
"""
LIN Keep-Alive 脚本
====================
每隔 N 秒发送一次 TesterPresent (3E 80, 抑制正响应)，
使 ECU 保持当前会话，不进入 Sleep。

用法:
  python lin_keep_alive.py            # 默认每 4 秒发一次
  python lin_keep_alive.py --interval 2
  Ctrl+C 停止
"""

import sys
import time
import argparse

from lin_tp_transport import LinTpTransport
from lin_uds_log import LinUdsLog, bytes_to_hex


def main():
    parser = argparse.ArgumentParser(description="LIN Keep-Alive（TesterPresent 3E 80）")
    parser.add_argument("--interval", type=float, default=4.0,
                        help="发送间隔（秒），应小于 S3=5s，默认 4.0")
    args = parser.parse_args()

    log = LinUdsLog("lin_keep_alive")
    tp  = LinTpTransport(logger=log)

    try:
        tp.open()
        print(f"[Keep-Alive] 启动，每 {args.interval:.1f}s 发送 3E 80  (Ctrl+C 停止)")
        count = 0
        while True:
            count += 1
            req = bytes([0x3E, 0x80])   # TesterPresent, 抑制正响应
            # expect_response=False: 不等回复，超时不报错
            tp.send_uds(req, expect_response=False)
            ts = time.strftime("%H:%M:%S")
            print(f"  [{ts}] #{count:04d}  TX: {bytes_to_hex(req)}")
            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\n[Keep-Alive] 已停止")
    except Exception as e:
        print(f"[Keep-Alive] 错误: {e}")
        raise
    finally:
        tp.close()
        log.close()


if __name__ == "__main__":
    main()
