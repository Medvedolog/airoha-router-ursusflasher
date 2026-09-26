# UrsusFlasher 0.2.71 / UrsusBoot t71 — 操作说明

适用 Nokia XG-040G-MD / AN7581 与 XG-040G-MF / AN7583。当前 PUBLIC TEST 为 UrsusFlasher 0.2.71，搭配固定的 UrsusBoot t71；最新预发布版见 [Releases](https://github.com/Medvedolog/airoha-router-ursusflasher/releases)。UrsusFlasher 需要 **Python 3.12+**，无需安装 `pip` 包。

[中文 README](README_ZH.md) · [English instructions](INSTRUCTIONS_EN.md) · [Русская инструкция](INSTRUCTIONS_RU.md)

## 首先：将 Nokia 恢复出厂设置

在**每一轮**操作前都要恢复出厂设置，包括第一次安装和失败后的重试。该步骤在 **Nokia 原厂固件**下执行：按住 Reset **至少 20 秒**，松开后等待路由器重启完成。否则先前设置、服务状态或残留操作可能影响识别和登录。

## 网络与串口

刷写请连接 **LAN2 或 LAN3**。LAN1 连接独立的 EN8811H PHY，不是此过程的推荐端口；LAN4 在附带的 OpenWrt 启动后变为 WAN，电脑接在那里可能失去 `192.168.1.1`。

USB-UART 恢复使用 **3.3 V** 转接器，仅连接 TX、RX、GND；**不要连接 VCC**。

## ONE-CLICK

Windows 运行 `START_ONECLICK.cmd`；Linux/macOS 运行 `./START_ONECLICK.sh`。程序先检测设备状态，再选择通道。

**ONE-CLICK 始终安装 UBI 布局**，不会让用户选择原厂布局。若确需原厂布局，可在 EXPERT 第 3 项选用工具包内的 `fw/openwrt-airoha-an7581-nokia_xg-040g-md-squashfs-sysupgrade.bin`，或在 UrsusBoot Recovery 网页上传同一镜像并选择“安装到原厂布局”。第 3 项识别 `.bin` / `.itb` 的镜像类别。从原厂 Nokia 可安装原厂布局，但**已安装的 OpenWrt UBI 不能反向迁移到原厂布局**；程序会在写入前拒绝。

### Nokia 原厂系统

使用原厂 HTTP/Web 和 root Telnet 控制；完整备份和准备好的 `mtd0` 镜像通过 TFTP 传输。普通 ONE-CLICK 在第一次 NAND 写入前必须验证完整的 `mtd0..mtd16` 备份。EXPERT 第 1 项可为当前测试明确跳过这份耗时的完整备份，但当前 `mtd0` 读取仍为必需；持久写入 `mtd0` 之前始终有一次 `[y/N]` 确认。

### 已安装的 OpenWrt 或 RAM/initramfs OpenWrt

通过 root SSH 控制，使用二进制 SSH 流/SCP 传输。程序区分闪存上的持久系统和 RAM 系统。已有 UBI `fip` 时优先使用它；只有在目标和当前内容均明确时才使用物理引导区。

### UrsusBoot Recovery

通过 `192.168.1.1` 的 HTTP API 控制和分块上传。在操作 POST 之前，文件仅位于 RAM，状态为 `NOT_STARTED`。传输中断后客户端保留 75 秒重连窗口；建立全新上传会话前再次询问 `[y/N]`。

## EXPERT

Windows 运行 `START_EXPERT.cmd`；Linux/macOS 运行 `./START_EXPERT.sh`。标 `!` 的项目可能写入持久 NAND。被动探测仅用于显示信息；选定操作会独立执行决定性的预检，并在需要时索取凭据。原厂 Nokia 的第 1 项询问是否仅为本轮跳过完整备份，但不会跳过当前 `mtd0` 的读取，也不会增加额外的破坏性确认；直接写 `mtd0` 仍只询问一次 `[y/N]`。

## 更新引导程序的通道

| 当前环境 | 通道 |
|---|---|
| Nokia 原厂系统 | Telnet + TFTP |
| 已安装 OpenWrt | SSH + SCP |
| RAM/initramfs OpenWrt | SSH + SCP |
| UrsusBoot Recovery | HTTP API；WebFailsafe 上传失败时可通过 TFTP 传 FIP |
| Airoha BootROM | USB-UART + XMODEM，在 RAM 中启动恢复环境 |

ONE-CLICK 不会自动更新已安装的 UrsusBoot。发现工具包版本较新时仅通知用户；须明确选择 WebFailsafe 或 EXPERT 更新。

## 验证与完整备份

写入前检查设备身份、布局、目标对象、文件大小/哈希和备份状态。写入后完整读回引导程序对象并与预期内容或 SHA256 比对；不匹配时不会自动改用另一个写入器重试。

Nokia 原厂完整备份包含 `mtd0..mtd16`、设备元数据和校验和。OpenWrt 下选择第 7 项时，可能要求 root SSH 密码以识别布局；不保存密码，也不在路由器上安装临时密钥。UBI 的精确备份随后使用 Airoha BootROM/RAM，读取完整 256 MiB 物理 NAND 为 `mtd0_all_flash.bin.gz`，生成 SHA256 和 BL2/UBI 视图，而不写 NAND。

## 进入 UrsusBoot Recovery

通电或重启后，在整机 LED 重新启动时立即按住 Reset。保持按住，经过 **2 次短闪 + 3 次长闪**，红灯常亮时松开；随后打开 `http://192.168.1.1`。

**通电前**按住 Reset 进入的是 Airoha BootROM，**不是**普通 UrsusBoot Recovery。

## UrsusBoot 网页：控件何时显示或拒绝操作

页面根据路由器状态与已上传镜像的类别显示控件；控件未出现通常表示条件尚未满足。

| 控件 | 出现条件 |
|---|---|
| 操作进度 | 正在执行操作 |
| 重启到 OpenWrt / 新 UrsusBoot | 操作成功完成 |
| 安装到原厂布局 | 引导程序报告该安装可用 |
| 安装/更新 UBI | 引导程序报告 UBI 更新可用 |
| 保留 OpenWrt 设置 | **已有 UBI 布局**且上传的是 UBI sysupgrade |
| 重置 OpenWrt 设置 | 布局为 `OPENWRT_UBI` 或 `OPENWRT_STOCK_LAYOUT`，且没有操作正在执行 |
| 迁移区域 | 当前属于迁移情境 |

首次安装或从原厂布局迁移时没有可保留的设置，故“保留设置”被强制关闭。安装刚结束时，Recovery 尚未重新检测到运行中的 OpenWrt，“重置设置”也可能不显示。完成保留设置的 UBI 更新后，主机可在重启前明确提供可选的设置重置。

“迁移到 UBI”要求全部迁移预检通过；“更新 UrsusBoot”需要有效 FIP 且无活动操作。已完成或失败的记录仍可查看，但不会自动锁住下一次非活动尝试。

即使按钮可见，写入仍可能被拒绝：

```text
OPERATION_LOCKED     缺少已验证的正确镜像、另一操作进行中、预检失败或未确认
LAYOUT_UNSUPPORTED   当前布局不支持该操作
WRITE_FAILED         写入或重置未完成
```

每个破坏性操作还需要页面发送准确的确认值：`INSTALL-UBI`、`INSTALL-OPENWRT-STOCK-LAYOUT`、`UPDATE-URSUSBOOT`、`RESET-OPENWRT-SETTINGS`、`REBOOT`。

**重启说明：**即使随后网页/重启请求遭遇传输故障，已经成功写入并读回验证的事务仍然算完成。网页会检查重启 HTTP 结果并报告拒绝；写入后的界面故障不可作为自动再次写入的理由。
