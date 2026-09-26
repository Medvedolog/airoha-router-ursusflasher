<div align="center">

<img src="img/ursus-bear.svg" alt="" width="72" height="72">

# UrsusFlasher

### Nokia XG-040G-MD / XG-040G-MF：安装 OpenWrt、备份与恢复

**Airoha AN7581 / AN7583 · 256 MiB SPI-NAND · UrsusBoot · OpenWrt**

[![UrsusFlasher latest prerelease](https://img.shields.io/github/v/release/Medvedolog/airoha-router-ursusflasher?include_prereleases&label=UrsusFlasher&color=6f4b2f)](https://github.com/Medvedolog/airoha-router-ursusflasher/releases)
[![UrsusBoot](https://img.shields.io/badge/UrsusBoot-0.1.0--alpha5--t71-b36b32)](https://github.com/Medvedolog/airoha-ursusboot)
![Target](https://img.shields.io/badge/Nokia-XG--040G--MD_%2F_XG--040G--MF-555)
![OpenWrt](https://img.shields.io/badge/OpenWrt-UnameOne_Edition-00a4ef)

**[📦 下载最新 PUBLIC TEST（发布页最上方的预发布版）](https://github.com/Medvedolog/airoha-router-ursusflasher/releases)** · [操作说明](INSTRUCTIONS_ZH.md) · [英文更新记录](CHANGELOG_EN.md) · [紧急恢复说明（俄语）](EMERGENCY_URSUSBOOT_RU.md)

🇷🇺 [Русский](../README.md) · 🇬🇧 [English](README_EN.md)

</div>

---

## 简介

工具包由两个分工不同、能够配合工作的部分组成。

**UrsusFlasher** 运行在电脑上。它先识别路由器状态，再选用 Nokia 原厂 Web/Telnet、已安装 OpenWrt 的 SSH、UrsusBoot 的 HTTP API；当其他路径都不可用时，还可走 USB-UART / Airoha BootROM。它引导操作者完成安装、备份、验证与恢复。

**[UrsusBoot](https://github.com/Medvedolog/airoha-ursusboot)** 常驻路由器，是基于完整 U-Boot 的恢复环境，内置网页、镜像检查、网络启动、在 RAM 中启动 initramfs、NAND 诊断和恢复操作。它**不依赖**电脑上的 UrsusFlasher，也能自行安装或重装 OpenWrt。正常使用时，UrsusFlasher 提供便于操作的流程，UrsusBoot 执行路由器侧的检查和写入。

刷写时无需联网：所需镜像已在工具包内。

<div align="center">

<img src="img/ursusboot-alpha5-recovery.png" alt="UrsusBoot Recovery 网页：左侧安装，右侧 NAND 与 UBI 状态" width="760">

<sub>UrsusBoot Recovery：左侧是 OpenWrt 安装和不写闪存的单次 initramfs 启动，右侧是布局、`fip`/`fit` 卷、NAND 与坏块状态。</sub>

</div>

上图的路由器已经安装 OpenWrt，布局为 `OPENWRT_UBI`，因此显示“重置 OpenWrt 设置”。Nokia 原厂布局下该位置不会显示同一控件；具体条件见[操作说明](INSTRUCTIONS_ZH.md)。

---

## 当前开发状态

当前已发布的 PUBLIC TEST 是 **UrsusFlasher 0.2.71**，为 MD 和 MF 固定搭配 **UrsusBoot `0.1.0-alpha5-t71`**。UrsusBoot t68–t71 改进了 UBI 迁移后的 WebFailsafe 诊断，可通过“恢复 UrsusBoot”修复缺失或损坏的 UBI `fip`（保留 `fip.old`），并提供 MF 的规范 `ursusboot-update.fip`。

从 0.2.67 起，Nokia 原厂系统上需要 UID 0 权限的**安装**流程，在服务账户不可用时可通过原厂 Web UI 启用 FTP 后重试；**只读备份不会因此启用服务**。版本徽章取自最新 GitHub 预发布版；具体包和校验和以[发布页](https://github.com/Medvedolog/airoha-router-ursusflasher/releases)为准。

> [!IMPORTANT]
> **0.2.71 / t71 的实机状态：** XG-040G-MD 完成了 ONE-KEY 保留 UrsusBoot 的路线，以及 Nokia STOCK → UrsusBoot → OpenWrt UBI → Vanilla U-Boot 的完整 ONE-KEY Vanilla 路线，并保留原厂 MAC。MF 对应路线在 t66 完成。t69–t71 的 UBI `fip` 修复路径**仍未实机验证**。MD/MF 实机测试请参阅 [TEST64 checklist（俄语）](TEST64_TEST_RU.md)，出错时保留完整日志。CI/构建通过不能替代实机验收。

历史 TEST59/TEST60 因版本身份可能误报而被撤回，不应作为新硬件测试的依据。

---

## UrsusBoot 从何而来

早期 UrsusFlasher 使用厂商提供、没有可重现源码的二进制 `tcboot`。后来转向基于 **U-Boot v2026.07**、OpenWrt/Airoha 补丁以及本项目恢复层的 UrsusBoot。`tcboot` 留作历史行为参考，不再作为当前工具包的核心引导程序。

目标 UBI 布局遵循 OpenWrt 对此设备的预期：

```text
0x00000000..0x0001ffff   BL2
0x00020000..NAND 末尾    UBI
                           ubootenv、ubootenv2、bosa、ri
                           fip          ← UrsusBoot
                           fit          ← OpenWrt 内核与根文件系统
                           rootfs_data
```

因此工具包中的 UBI sysupgrade 镜像可按该布局安装，无需临时改写镜像的闪存映射。UrsusBoot 放在 UBI 的 `fip` 卷中，而非额外划出的原始闪存分区。

### 这是完整的 U-Boot

UART 控制台使用熟悉的 U-Boot 命令；WebFailsafe 的“U-Boot 控制台”标签页调用的也是**真实命令行**，并非受限子集。网页按钮的检查和确认**不约束手动输入的命令**，因此仅在明白后果时使用控制台。

构建保留启动、MTD/UBI、环境、网络（`tftpboot`、`ping`、`dhcp`、`wget`、`mii`、`mdio`）以及 `bootm`、`fdt`、`gpio`、`led`、`button`、`hash`、`crc32`、LZMA/gzip 等恢复所需功能；关闭此硬件流程不使用的文件系统、存储总线和调试命令，以适应有限空间。UBIFS 文件系统命令关闭，不代表 UBI 层被关闭。准确的命令和构建配置见 [UrsusBoot 仓库](https://github.com/Medvedolog/airoha-ursusboot)。

---

## UrsusBoot 能做什么

**可以：**

- 经自带网页接收 OpenWrt UBI 或原厂布局镜像；网页不可用时，可使用适合的 TFTP 恢复路线；
- 写入前检查镜像类别、大小、哈希及当前布局是否允许该操作；
- 按需建立 UBI 布局，写入并读回比对；
- 在已安装系统损坏时由 Reset 进入 Recovery；
- 单独通过网页安装或重装 OpenWrt，无需电脑端 UrsusFlasher；
- 从 RAM 单次启动经过验证的 initramfs/FIT，而不因此写 NAND。

正常的 OpenWrt `sysupgrade` 更新 `fit` 和 `rootfs_data`，不会顺带覆盖 UrsusBoot 的 `fip`；UrsusBoot 本身也能执行受支持的更新。

**不能：**

- 从无到有重建丢失的原厂 MAC、序列号或光学标定数据；备份属于本机的身份信息很重要；
- 在普通 OpenWrt 更新时悄悄更新自身：引导程序更新是独立操作；
- 让任意布局之间都能互相转换：镜像和布局检查会拒绝不适用的组合。

### 布局之间的转换

| 当前布局 | 目标布局 | 结果 |
|---|---|---|
| Nokia 原厂 | OpenWrt UBI | 已验证迁移候选且确认后允许 |
| Nokia 原厂 | OpenWrt 原厂布局 | 有相应已验证镜像时允许 |
| OpenWrt 原厂布局 | OpenWrt UBI | 通过 UrsusBoot Recovery 并满足迁移检查后允许 |
| OpenWrt UBI | OpenWrt 原厂布局 | **写入前拒绝** |

从原厂布局迁移到 UBI 是破坏性操作，需要检查 UBI 镜像、过渡 preloader/BL2 和物理布局。**从 UBI 反向回到原厂布局不受支持**。UrsusBoot 判定当前布局与镜像类别，UrsusFlasher 的操作路线再执行相应前置检查。

---

## 开始使用

> [!IMPORTANT]
> 在 **Nokia 原厂系统**上，首次安装和失败后重试之前都要恢复出厂设置：在运行中的路由器上按住 Reset **至少 20 秒**，松开并等它重启。旧设置、服务状态和残留操作会影响识别与访问；状态不明时程序应停止，而非猜测。

下载并解压[最新预发布工具包](https://github.com/Medvedolog/airoha-router-ursusflasher/releases)，在解压目录中运行：

| 用途 | Windows | Linux / macOS |
|---|---|---|
| 普通自动安装 | `START_ONECLICK.cmd` | `./START_ONECLICK.sh` |
| EXPERT 手动操作 | `START_EXPERT.cmd` | `./START_EXPERT.sh` |

需要 **Python 3.12+** 和网线，不需要额外 `pip` 包。只想安装 OpenWrt 就选 **ONE-CLICK**；只安装引导程序、备份或诊断则用 **EXPERT**。

> [!IMPORTANT]
> 操作前关闭电脑上的 VPN、Wi-Fi 和其他 Ethernet 接口，只保留连接路由器的网卡。其他活动路由可能抢占 `192.168.1.1`，也可能干扰 Nokia Stock、UrsusBoot Recovery 和 OpenWrt 间的切换。

电脑与路由器用一根网线**直接连接**。LAN2/LAN3 最合适；LAN4 可用于初始阶段，但工具包的 OpenWrt 启动后它成为 WAN，需将网线移到 LAN2/LAN3 才能继续访问 `192.168.1.1`。LAN1 使用单独的 EN8811H PHY，不推荐用于迁移或恢复。

---

## ONE-CLICK 如何工作

ONE-CLICK **先检查状态，再选择路线**：

1. **Nokia 原厂系统：**登录原厂 Web，通过 Telnet 获得 root，经 TFTP 读取并验证完整闪存备份。之后才准备并写入引导区，完整读回比对，进入 UrsusBoot Recovery 安装 OpenWrt。
2. **已安装 OpenWrt：**通过 root SSH 操作，区分持久闪存系统与 RAM/initramfs 系统。存在 UBI `fip` 时优先针对该卷；仅在物理目标和当前内容明确时才触碰物理引导区。写后读回，再进入 Recovery。
3. **已在 UrsusBoot Recovery：**不必重复安装引导程序；镜像分块传送，由 UrsusBoot 校验并执行受支持的写入。

普通 Nokia Stock ONE-CLICK **必须完成完整备份**。在备份和预检之后、持久写入 `mtd0` 之前只询问一次普通的 `[y/N]`。EXPERT 第 1 项可以明确地仅为本次测试跳过耗时的完整 `mtd0..mtd16` 备份，但保留 ROM 前缀/环境所需的**当前 `mtd0` 读取仍是必需的**。ONE-CLICK 不会自动更新已安装的 UrsusBoot；发现工具包版本更新时只作提示。

### ONE-CLICK 始终使用 UBI

工具包同时提供 UBI 和原厂布局的 OpenWrt 镜像，但 **ONE-CLICK 一律选择 UBI**，不提供布局选择。若确需原厂布局，须手动使用 EXPERT 第 3 项选择工具包内相应的 `.bin`，或在 UrsusBoot Recovery 网页上传同一镜像并选择原厂布局安装。第 3 项接受 `.bin`/`.itb` 并识别镜像类别。从已经安装的 OpenWrt UBI 回到原厂布局会在写入前被拒绝。

### 控制与文件传输

| 路由器状态 | 控制通道 | 文件传输 |
|---|---|---|
| Nokia 原厂系统 | HTTP/Web + Telnet | TFTP |
| 闪存中的 OpenWrt | SSH | SCP |
| RAM 中的 OpenWrt | SSH | SCP |
| UrsusBoot Recovery | HTTP API | 分块 HTTP |
| Recovery 后备路线 | UrsusBoot 控制台 | TFTP |
| 无法启动 | USB-UART → Airoha BootROM | XMODEM |

USB-UART 使用 **3.3 V**，只接 TX、RX、GND，**不要连接 VCC**。

---

## EXPERT 菜单

`!` 表示该项目可能持久写入 NAND。被动探测仅供参考；每个被选中的操作会重新执行自己的预检。

| 项目 | 用途及路线 |
|---|---|
| `! 1` 安装 OpenWrt | ONE-CLICK 对应路线；Nokia Stock 本轮可明确跳过完整备份，但当前 `mtd0` 读取和写入前一次 `[y/N]` 保留。 |
| `! 2` 安装/更新 UrsusBoot | 原厂 Nokia 经 Web/Telnet，OpenWrt 经 SSH，Recovery 经 HTTP，必要时 TFTP。 |
| `! 3` 写入自定义 OpenWrt | OpenWrt 经 SSH 并先执行 `sysupgrade -T`；Recovery 经 HTTP。 |
| `! 4` Nokia Stock → UBI → Vanilla U-Boot | MD/MF 的完整过渡路线；过渡时使用 UrsusBoot，再装固定版本的 Vanilla U-Boot。 |
| `! 5` 恢复引导程序 | USB-UART → Airoha BootROM → RAM 恢复环境 → 检查、写入和读回。 |
| `! 6` 恢复 Nokia 原厂系统 | 从已验证的完整本机备份恢复；可选自动、OpenWrt SSH、UrsusBoot Recovery 或 USB-UART 路线。 |
| `7` 完整闪存备份 | 必要时通过 BootROM/RAM 读取，不写 NAND。 |
| `8` 校验备份 | 在电脑上检查内容、大小、SHA256。 |
| `9` 恢复 Nokia 原厂引导区 | 此项应按当前工具包的运行时说明操作；早期英文 README 将它记为未实现。 |
| `10` 设备状态 | Web/SSH 被动探测，需要时询问密码。 |
| `11` 闪存、布局及坏块 | Web/SSH，必要时 USB-UART；只读。 |
| `12` 校验工具包 | 本地哈希与内容检查。 |

> [!NOTE]
> 菜单随测试版演进。英文 README 的旧 TEST61 菜单曾把第 4 项记作别名、第 6/9 项记作未接入；此处按当前俄文 README 与 0.2.71 发布说明描述。**实际可用操作以所下载工具包的菜单和该操作预检为准。**

---

## 出现故障时

先确认现在仍能运行的是 Nokia Stock、stock `tcboot`、常驻 UrsusBoot、RAM 中的 OpenWrt/initramfs，还是只剩 BootROM/UART。Web/SSH 暂时消失不等于可以盲目再写 NAND。

### 用 Reset 进入 UrsusBoot Recovery

常驻 UrsusBoot 已安装时，在**通电或重启之后**、整机 LED 重新启动时按住 Reset；经过 **2 次短闪 + 3 次长闪**，红灯常亮时松开，电脑接 LAN2/LAN3 并打开 `http://192.168.1.1`。若错过时机，可断电再开，等约一秒后按住。**通电前**就按住 Reset 会进入 Airoha BootROM，而非普通 WebFailsafe。

### 若只剩 UrsusBoot 网页

先查看系统状态、NAND 和 UBI 诊断。需要 Linux 环境时，可在 **Initramfs / FIT** 标签页上传兼容镜像，等校验通过后选择**单次从 RAM 启动**。此操作本身不写闪存；启动后可通过 SSH 检查 `/proc/mtd`、`ubinfo -a`、`dmesg` 和 `logread`。能启动 initramfs **不代表**可以随意写 `/dev/mtdX`。

### Vanilla 过渡卡在破坏性写入之前

Stock → UBI → Vanilla 路线在第一次 `ubiformat` **之前**尽量保留 Nokia 的 A/B 回退：stock `tcboot`、selector 和 `MASTER/SLOT1` 尚在。如果 `SLAVE/SLOT2` 无法启动，且确知尚未越过破坏性边界，可让每次启动运行约 **6 秒**再断电，最多重复 **15 次**以消耗 stock retry counter。过早断电可能不计数；回到 stock 后停止循环并先检查日志。**一旦 stage2 开始第一个 `ubiformat`，就不能再依赖这个回退。**细节见[俄文 README 的应急章节](../README.md#аварийные-состояния-во-время-прошивки-что-делать-без-паники)。

### 只有 UART 或引导程序无法启动

UART 首先用于记录启动日志、观察和从 RAM 启动。若仍能进入常驻 UrsusBoot，应优先使用网页恢复；若只剩 U-Boot 提示符，可先检查实际分区并从 RAM 启动兼容 FIT。遇到 `LZMA: res 1`、`PANIC` 或损坏的 NAND 启动链，使用 EXPERT 第 5 项的 USB-UART/BootROM 路线；在预检和确认之前先读取状态。UART 仅连接 3.3 V TX/RX/GND，**不接 VCC**。完整底层流程见[紧急恢复文档（俄语）](EMERGENCY_URSUSBOOT_RU.md)。

---

## 写入前检查什么

操作分为**识别状态 → 传输文件 → 写入**三个阶段，阶段之间进行检查。验证工具包文件、型号/SoC、布局、具体写入目标、备份状态，并在路由器端核对传入文件的大小和哈希。

EXPERT 的后台诊断不代替选定操作的预检，也不自动批准或禁止写入。需要 root 密码时，由系统 OpenSSH 询问；UrsusFlasher 不保存密码，也不在路由器上安装临时密钥。

## 写入后检查什么

写入命令返回成功并不足以证明闪存内容正确。程序会完整读回 512 KiB 引导区并比较 SHA256，或读回整个已写入的 `fip`；可行时还核对重启后实际响应的环境。比较失败**不会自动切换另一写入器重试**，应先停下查明状态。

---

## 备份

菜单第 **7** 项不写闪存。Nokia 原厂系统的备份包含 `mtd0..mtd16`、布局和证明备份属于本机的元数据；只读备份不会为取文件而启用额外服务。

无法安全地从运行中的系统读取时，使用 Airoha BootROM：恢复环境只在 RAM 中运行，读取期间不修改闪存。OpenWrt UBI 的精确物理备份保存完整 256 MiB NAND 为 `mtd0_all_flash.bin.gz`，复核 SHA256，并附便于查看的 `mtd1_bl2`、`mtd2_ubi` 切片。从可写、正在运行的 OpenWrt 取到的普通拷贝不会被冒充为可精确全盘还原的镜像。

备份验证可在电脑端使用第 **8** 项。丢失的原厂 MAC、序列号及光学校准数据不能由引导程序凭空生成。

---

## 工具包包含什么

工具包包含分别面向原厂布局和 UBI 布局的 OpenWrt 镜像；例如 MD 的文件名为：

```text
fw/openwrt-airoha-an7581-nokia_xg-040g-md-squashfs-sysupgrade.bin       原厂布局
fw/openwrt-airoha-an7581-nokia_xg-040g-md-ubi-squashfs-sysupgrade.itb   UBI 布局
```

英文 README 描述的旧 TEST61 工具包使用 2026-09-06 的 UnameOne 构建 `r36009+75-6c315233aa`、Linux 6.18.44；**不要把该旧清单当作当前 0.2.71 ZIP 的精确内容**。当前公开测试搭配的 UrsusBoot 版本、MD/MF 产物和硬件状态见上文及 [Releases](https://github.com/Medvedolog/airoha-router-ursusflasher/releases)。每个具体压缩包的大小与哈希以其中的 `SHA256SUMS`、`data/MANIFEST.json` 和 `VERSION` 为准。

### 验证工具包

在菜单使用第 **12** 项；若在完整仓库检出中，可运行：

```bash
python3 scripts/verify_repo.py
```

它检查校验和、清单、引导组件、Python 语法及内置自检。Windows 上建议克隆到较短路径；遇到 `Filename too long` 可运行：

```powershell
git config --global core.longpaths true
```

`.gitattributes` 为文本与 `.cmd` 固定换行规则，使 `SHA256SUMS` 不受 `core.autocrlf` 设置影响。

---

## 发布、文档和许可

[Releases](https://github.com/Medvedolog/airoha-router-ursusflasher/releases) 列出用户工具包，最新 PUBLIC TEST 预发布版通常在最上方。发布使用经过验证的精确 MD/MF 工具包；主机 CI 证据与实机验收分别记录。用户压缩包不包含 SDK、编译器、构建树及开发工具。

- [中文操作说明](INSTRUCTIONS_ZH.md) / [英文操作说明](INSTRUCTIONS_EN.md) / [俄文操作说明](INSTRUCTIONS_RU.md)
- [UrsusBoot 中文 README](https://github.com/Medvedolog/airoha-ursusboot/blob/main/README.zh-CN.md)
- [紧急恢复说明（俄语）](EMERGENCY_URSUSBOOT_RU.md)
- [英文更新记录](CHANGELOG_EN.md)
- [仓库文件说明](../FILES.md)

许可及再分发注意事项见 [LICENSE-NOTICE.md](../LICENSE-NOTICE.md)。仓库包含多个外部项目的组件，再分发时应保留其许可与声明。
