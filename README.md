# STM32F103 Flash Bootloader — UDS over CAN

<p align="center">
  <img src="https://img.shields.io/badge/MCU-STM32F103ZET6-blue" alt="MCU"/>
  <img src="https://img.shields.io/badge/Core-ARM_Cortex--M3-brightgreen" alt="Core"/>
  <img src="https://img.shields.io/badge/Protocol-UDS_ISO_14229--1-orange" alt="UDS"/>
  <img src="https://img.shields.io/badge/Transport-ISO_15765--2_(ISO--TP)-red" alt="ISO-TP"/>
  <img src="https://img.shields.io/badge/CAN-500kbps-lightgrey" alt="CAN"/>
  <img src="https://img.shields.io/badge/Build-CMake_%2B_Ninja-green" alt="Build"/>
  <img src="https://img.shields.io/badge/License-Proprietary-lightgrey" alt="License"/>
</p>

<p align="center">
  <b>English</b> | <a href="#简体中文">简体中文</a>
</p>

---

## English

A **Flash Bootloader (FBL)** for **STM32F103ZET6** with **UDS (ISO 14229-1)** diagnostic protocol over **CAN bus**, enabling remote firmware update (OTA-like) via the vehicle-standard Unified Diagnostic Services.

### Key Features

- **16 UDS services** implemented: session control, security access, data transfer, routine control, DTC management, etc.
- **ISO 15765-2 (ISO-TP)** transport layer: multi-frame transmission with flow control
- **AES-128 CMAC** based security access (SID 0x27) for secure reprogramming
- **Independent Watchdog (IWDG)** for system reliability
- **Three boot decision modes**: RAM fallback flag, Flash valid flag, CAN request timeout
- **Full reprogramming flow**: RequestDownload → TransferData → TransferExit → Reset

### Memory Map

| Region | Address | Size |
|--------|---------|------|
| FBL Code | 0x08000000 - 0x08007FFF | 32 KB |
| FBL Version | 0x08007FFC | 4 B |
| Reserved | 0x08008000 - 0x08009FFF | 8 KB |
| APP Valid Flag | 0x0800A000 | 4 B |
| APP Code | 0x0800C000 - 0x0801FFFF | 80 KB |
| APP Version | 0x0801FFFC | 4 B |

### Build Systems

| Method | Generator | Debugger |
|--------|-----------|----------|
| **CMake + Ninja** (primary) | `cmake --preset Debug && ninja -C build/Debug` | ST-Link GDB |
| **GNU Make** (legacy) | `make` | ST-Link GDB |
| **Keil MDK-ARM** | MDK-ARM/ project | J-Link / ST-Link |

### Quick Start

```bash
# 1. Clone the repository
git clone <repo-url>

# 2. Build with CMake + Ninja
cmake --preset Debug
ninja -C build/Debug

# 3. Flash via ST-Link
openocd -f interface/stlink.cfg -f target/stm32f1x.cfg -c "program build/Debug/a.hex verify reset exit"

# 4. Connect PCAN-USB and run UDS diagnostics
cd doc/01_PCAN_CAN
python SID10_SessionControl.py    # Test session control
python Reprogramming_CAN.py       # Full firmware update
```

### CAN Communication

| Parameter | Value |
|-----------|-------|
| Bitrate | 500 kbps |
| CAN ID (Request) | 0x123 |
| CAN ID (Response) | 0x122 |
| Frame Size | 8 bytes |
| Padding | 0xAA |
| Protocol | CAN 2.0B (11-bit ID) |

### Documentation

| Document | Description |
|----------|-------------|
| [doc/技术栈总览.md](doc/%E6%8A%80%E6%9C%AF%E6%A0%88%E6%80%BB%E8%A7%88.md) | Technical stack reference (Chinese) |
| [doc/技术栈讲解.md](doc/%E6%8A%80%E6%9C%AF%E6%A0%88%E8%AE%B2%E8%A7%A3.md) | Technical presentation script (Chinese) |
| [doc/memory.md](doc/memory.md) | Memory map specification |
| [doc/report.md](doc/report.md) | IWDG implementation report |
| [doc/01_PCAN_CAN](doc/01_PCAN_CAN) | PCAN Python toolchain |

---

## 简体中文

基于 **STM32F103ZET6** 的 **Flash Bootloader (FBL)**，通过 **CAN 总线** 承载 **UDS (ISO 14229-1)** 汽车诊断协议，支持远程固件升级。

### 核心功能

- 实现 **16 个 UDS 服务**：会话控制、安全访问、数据传输、例行程序控制、DTC 管理等
- **ISO 15765-2 (ISO-TP)** 传输层：支持多帧传输与流量控制
- **AES-128 CMAC** 安全访问认证（SID 0x27），防止非法刷写
- **独立看门狗 (IWDG)** 保障系统可靠性
- **三阶段启动判决**：RAM 回退标志 / Flash 有效标志 / CAN 请求超时
- **完整刷写流程**：RequestDownload → TransferData → TransferExit → 复位

### 内存布局

| 区域 | 地址 | 大小 |
|------|------|------|
| FBL 代码 | 0x08000000 - 0x08007FFF | 32 KB |
| FBL 版本号 | 0x08007FFC | 4 B |
| 隔离预留区 | 0x08008000 - 0x08009FFF | 8 KB |
| APP 有效标志 | 0x0800A000 | 4 B |
| APP 代码 | 0x0800C000 - 0x0801FFFF | 80 KB |
| APP 版本号 | 0x0801FFFC | 4 B |

### 构建方式

| 方式 | 命令 | 调试器 |
|------|------|--------|
| **CMake + Ninja**（主力） | `cmake --preset Debug && ninja -C build/Debug` | ST-Link GDB |
| **GNU Make**（备用） | `make` | ST-Link GDB |
| **Keil MDK-ARM** | 打开 MDK-ARM/ 工程 | J-Link / ST-Link |

### 快速开始

```bash
# 1. 克隆仓库
git clone <仓库地址>

# 2. 构建
cmake --preset Debug
ninja -C build/Debug

# 3. 烧录 (ST-Link)
openocd -f interface/stlink.cfg -f target/stm32f1x.cfg -c "program build/Debug/a.hex verify reset exit"

# 4. 连接 PCAN-USB，运行诊断工具
cd doc/01_PCAN_CAN
python SID10_SessionControl.py    # 测试会话控制
python Reprogramming_CAN.py       # 一键固件刷写
```

### CAN 通信参数

| 参数 | 值 |
|------|-----|
| 波特率 | 500 kbps |
| 请求 ID | 0x123 |
| 响应 ID | 0x122 |
| 帧长度 | 8 字节 |
| 填充字节 | 0xAA |
| 协议 | CAN 2.0B (11-bit ID) |

### 文档导航

| 文档 | 说明 |
|------|------|
| [doc/技术栈总览.md](doc/%E6%8A%80%E6%9C%AF%E6%A0%88%E6%80%BB%E8%A7%88.md) | 技术栈参考手册 |
| [doc/技术栈讲解.md](doc/%E6%8A%80%E6%9C%AF%E6%A0%88%E8%AE%B2%E8%A7%A3.md) | 技术栈讲解脚本 (~45 min) |
| [doc/memory.md](doc/memory.md) | Flash 内存映射规格 |
| [doc/report.md](doc/report.md) | IWDG 实现报告 |
| [doc/01_PCAN_CAN](doc/01_PCAN_CAN) | PCAN Python 工具链 |

### 项目结构

```
FBL-STM32-Bootload-UDS/
├── Core/                 # HAL 驱动与核心代码
│   ├── Src/              #   CAN, USART, Flash, IWDG, AES-CMAC
│   └── Inc/              #   头文件
├── UDSBase/              # UDS 协议栈核心
│   ├── uds_tp.c/h        #   ISO-TP 传输层
│   ├── uds_service.c/h   #   服务分发与会话管理
│   └── uds_port.c/h      #   端口适配层
├── UDSLogic/             # 16 个 UDS 服务实现
│   ├── service_cfg.c/h   #   服务配置表
│   ├── SID10_*.c         #   每个 SID 独立文件
│   └── ...
├── RingBuf/              # 环形缓冲区
├── Drivers/              # STM32 HAL / CMSIS
├── doc/                  # 文档与 PCAN 工具链
│   └── 01_PCAN_CAN/      # Python UDS 测试脚本
├── cmake/                # CMake 工具链文件
├── MDK-ARM/              # Keil MDK 工程
└── CMakeLists.txt        # CMake 构建配置
```

### 技术栈

| 层级 | 技术 |
|------|------|
| MCU | STM32F103ZET6 (Cortex-M3, 64 MHz) |
| 通信 | CAN 2.0B @ 500kbps |
| 传输 | ISO 15765-2 (ISO-TP) |
| 诊断 | UDS ISO 14229-1 (16 SIDs) |
| 安全 | AES-128 CMAC (RFC 4493) |
| 看门狗 | IWDG, ~500ms timeout |
| 编译器 | arm-none-eabi-gcc 13.3.1 |
| 构建 | CMake + Ninja / Make / Keil |
| 主机工具 | Python 3.9+, python-can, can-isotp, PCAN-USB |
| 调试 | ST-Link GDB, clangd |
