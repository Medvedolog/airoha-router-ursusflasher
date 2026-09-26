<div align="center">

<img src="img/ursus-bear.svg" alt="" width="72" height="72">

# UrsusFlasher

### 为 Nokia XG-040G-MD / XG-040G-MF 安装 OpenWrt、备份与恢复

**Airoha AN7581 / AN7583 · 256 MiB SPI-NAND · UrsusBoot · OpenWrt**

[![UrsusFlasher latest prerelease](https://img.shields.io/github/v/release/Medvedolog/airoha-router-ursusflasher?include_prereleases&label=UrsusFlasher&color=6f4b2f)](https://github.com/Medvedolog/airoha-router-ursusflasher/releases)

**[📦 下载最新 PUBLIC TEST（发布页最上方的预发布版）](https://github.com/Medvedolog/airoha-router-ursusflasher/releases)** · [操作说明](INSTRUCTIONS_ZH.md) · [更新记录（英文）](CHANGELOG_EN.md)

🇷🇺 [Русский](../README.md) · 🇬🇧 [English](README_EN.md)

</div>

---

## 项目概览

这个工具包有两个协作但各自独立的部分：

- **UrsusFlasher** 运行在电脑上。它识别路由器当前状态，选择 Nokia 原厂 Web/Telnet、OpenWrt SSH、UrsusBoot HTTP API，必要时选择 USB-UART / Airoha BootROM，并引导操作者完成安装、备份和恢复。
- **[UrsusBoot](https://github.com/Medvedolog/airoha-ursusboot)** 是路由器内基于 U-Boot 的完整恢复环境。它自带网页界面、镜像检查、OpenWrt 安装/更新、RAM 中启动 initramfs、NAND 诊断及恢复操作。即使没有 UrsusFlasher，它也可独立使用。

刷写期间不需要互联网：所需镜像随工具包提供。

<div align="center">

<img src="img/ursusboot-alpha5-recovery.png" alt="UrsusBoot 恢复网页界面" width="760">

<sub>UrsusBoot Recovery：左侧安装 OpenWrt，右侧显示存储布局、UBI 卷、NAND 和坏块等状态。</sub>

</div>

## 当前状态

已发布的 PUBLIC TEST 为 **UrsusFlasher 0.2.71**，为 MD/MF 固定搭配 **UrsusBoot `0.1.0-alpha5-t71`**。t68–t71 改进了 UBI 迁移后的 WebFailsafe 诊断、缺失或损坏的 UBI `fip` 修复（保留 `fip.old`），并提供 MF 的规范 `ursusboot-update.fip`。MD 上的 ONE-KEY Vanilla 与保留 UrsusBoot 路线已在 t71 硬件运行；MF 的对应路线在 t66 运行。t69–t71 的 `fip` 修复仍未完成实机验证。请以[发布页](https://github.com/Medvedolog/airoha-router-ursusflasher/releases)及原版 README 的最新状态为准。

> [!IMPORTANT]
> CI 或构建通过不等于实机验证。刷写之前请阅读[操作说明](INSTRUCTIONS_ZH.md)，并保存属于**本机**的完整备份。

## 为什么需要 UrsusBoot

早期项目使用没有可重现源码的二进制 `tcboot`。现在的 UrsusBoot 基于 U-Boot 2026.07 和 OpenWrt/Airoha 补丁，提供自己的 WebFailsafe 和操作策略。在目标 UBI 布局中，引导程序位于 `fip` 卷，OpenWrt 位于 `fit` 卷；官方 UBI sysupgrade 镜像可按预期布局安装。

UrsusBoot 检查镜像类别、大小和哈希，在适用的布局上写入并读回验证。普通 OpenWrt 更新不会顺带更新引导程序；更新 UrsusBoot 是独立操作。它能救回系统，却不能凭空恢复遗失的原厂 MAC、序列号和光学标定数据。

网页中的“U-Boot 控制台”执行真实 U-Boot 命令，不受网页按钮的保护规则约束；只在明确知道命令效果时使用。

## 开始使用

1. 从 [Releases](https://github.com/Medvedolog/airoha-router-ursusflasher/releases) 下载并解压完整工具包。电脑需要 **Python 3.12+**，无需 `pip` 第三方包。
2. Nokia 原厂固件状态下，在首次安装或失败重试前按住 Reset **至少 20 秒**完成恢复出厂设置，并等待重启。
3. 用网线连接电脑和 **LAN2 或 LAN3**。LAN1 不适合此刷写路线；LAN4 在附带的 OpenWrt 启动后成为 WAN。
4. 普通安装运行 Windows 的 `START_ONECLICK.cmd` 或 Linux/macOS 的 `./START_ONECLICK.sh`。特殊操作运行 `START_EXPERT.cmd` 或 `./START_EXPERT.sh`。

**ONE-CLICK 始终安装 UBI 布局**。如确需原厂布局，应在 EXPERT 第 3 项选择对应 `.bin` 镜像，或在 UrsusBoot 网页中选择原厂布局安装。从已安装的 OpenWrt UBI 返回原厂布局会在写入前被拒绝。

### 按路由器状态选择路线

| 当前状态 | 控制通道 | 文件通道 |
|---|---|---|
| Nokia 原厂系统 | Web + Telnet | TFTP |
| 已安装的 OpenWrt | SSH | SCP |
| RAM/initramfs OpenWrt | SSH | SCP |
| UrsusBoot Recovery | HTTP API | 分块 HTTP，必要时 TFTP |
| 无法启动 | USB-UART → Airoha BootROM | XMODEM |

普通原厂系统 ONE-CLICK 在第一次 NAND 写入前必须完成并验证 `mtd0..mtd16` 备份。在持续写入 `mtd0` 前，经过备份和预检后会询问一次 `[y/N]`。EXPERT 第 1 项可以仅为本次测试明确跳过耗时的完整备份，但仍必须读取当前 `mtd0`。已经安装的 UrsusBoot 不会被 ONE-CLICK 自动升级。

## EXPERT 菜单

`!` 表示操作可能写入 NAND。被动探测只提供信息；真正的预检由选定操作执行。

| 项目 | 用途 |
|---|---|
| `! 1` | 安装 OpenWrt；遵循 ONE-CLICK 路线 |
| `! 2` | 安装或更新 UrsusBoot |
| `! 3` | 写入自定义 OpenWrt `.bin` / `.itb` 镜像 |
| `! 5` | 通过 USB-UART / BootROM 恢复引导程序 |
| `! 6` | 恢复 Nokia 原厂系统；此版本尚未接入执行后端 |
| `7` | 完整闪存备份 |
| `8` | 在电脑上校验备份 |
| `9` | 组装恢复工具包；此版本尚未接入执行后端 |
| `10` | 查看设备状态和可用操作 |
| `11` | 查看闪存布局及坏块 |
| `12` | 校验工具包文件 |

旧菜单编号 `4` 仍可作为第 2 项的别名。菜单选项的具体限制以[操作说明](INSTRUCTIONS_ZH.md)和运行时预检为准。

## 写入前后与备份

写入前会检查工具包、型号/SoC、布局、目标、备份状态，以及传输后文件的大小和哈希。写入后完整读回引导区或 `fip` 并比对；不匹配时不会自动换一个写入器重试。

第 7 项的备份操作不写 NAND。原厂 Nokia 可保存 `mtd0..mtd16` 和设备元数据；OpenWrt UBI 的精确物理 NAND 备份通过 BootROM/RAM 路线生成完整 256 MiB 的 `mtd0_all_flash.bin.gz`，附 SHA256 及 BL2/UBI 视图。在可写的 OpenWrt 正常运行时取得的拷贝，不应当成完整物理还原镜像。

## 进入 UrsusBoot Recovery

在通电或重启后，等待整机 LED 重新启动，**这时**按住 Reset。经历 **2 次短闪 + 3 次长闪**，红灯常亮时松开，再访问 `http://192.168.1.1`。**通电之前**就按住 Reset 会进入 Airoha BootROM，而不是普通 UrsusBoot Recovery。

USB-UART 只连接 **3.3 V TX、RX、GND**，不要连接 VCC。严重故障时请按[恢复文档（俄语）](EMERGENCY_URSUSBOOT_RU.md)或[操作说明](INSTRUCTIONS_ZH.md)处理。

## 文档与许可

- [中文操作说明](INSTRUCTIONS_ZH.md)
- [英文 README](README_EN.md) / [俄文 README](../README.md)
- [英文更新记录](CHANGELOG_EN.md)
- [UrsusBoot](https://github.com/Medvedolog/airoha-ursusboot) 及其[中文 README](https://github.com/Medvedolog/airoha-ursusboot/blob/main/README.zh-CN.md)

镜像版本、SHA256 和文件清单以工具包内的 `VERSION`、`SHA256SUMS`、`data/MANIFEST.json` 为准。
