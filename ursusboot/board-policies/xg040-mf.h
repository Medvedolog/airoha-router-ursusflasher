/* SPDX-License-Identifier: GPL-2.0+ */
#ifndef __URSUS_BOARD_POLICY_H__
#define __URSUS_BOARD_POLICY_H__

#define URSUS_BOARD_POLICY_ID              "xg040-mf"
#define URSUS_BOARD_PROFILE_MARKER         "URSUS_BOARD_PROFILE=xg040-mf"
#define URSUS_BOARD_MODEL                  "Nokia XG-040G-MF"
#define URSUS_BOARD_COMPATIBLE             "nokia,xg-040g-mf"

#define URSUS_BOARD_ALLOW_UBI_BOOT          1
#define URSUS_BOARD_ALLOW_FACTORY_FIT       1
#define URSUS_BOARD_UBI_PROBE_OFF           0x00020000ULL
#define URSUS_BOARD_FACTORY_KERNEL_OFF      0x000c0000ULL
#define URSUS_BOARD_FACTORY_KERNEL_SIZE     0x00800000ULL

#define URSUS_BOARD_STOCK_MASTER_BASE       0x000c0000ULL
#define URSUS_BOARD_STOCK_SLAVE_BASE        0x02940000ULL
#define URSUS_BOARD_STOCK_SLOT_SIZE         0x02880000ULL
#define URSUS_BOARD_STOCK_ENV_BASE          0x0007c000ULL
#define URSUS_BOARD_STOCK_ENV_SIZE          0x00004000U
#define URSUS_BOARD_STOCK_TRX_HDR_SIZE      0x00000100U
#define URSUS_BOARD_STOCK_HDR_MAGIC         "HDR3"
#define URSUS_BOARD_STOCK_FIT_MAX_SIZE      0x02800000U

#define URSUS_BOARD_ROOT_MASTER             "/dev/mtdblock3 ro"
#define URSUS_BOARD_ROOT_SLAVE              "/dev/mtdblock5 ro"

#define URSUS_BOARD_APPEND_SERDES_ARGS(dst, cap) \
    (append_arg((dst), (cap), "serdes_pon", "00") || \
     append_arg((dst), (cap), "serdes_ethernet", "12") || \
     append_arg((dst), (cap), "serdes_wifi1", "05") || \
     append_arg((dst), (cap), "serdes_wifi2", "05") || \
     append_arg((dst), (cap), "serdes_usb1", "00") || \
     append_arg((dst), (cap), "serdes_usb2", "02"))

#define URSUS_BOARD_STOCK_ARGS_MARKER \
    "URSUS_STOCKBOOT_TCBOOT_MF_ARGS pon=00 ethernet=12 wifi1=05 wifi2=05 usb1=00 usb2=02"

#define URSUS_BOARD_ORACLE_FIT_SIZE         0U
#define URSUS_BOARD_ORACLE_KERNEL_OFF       0ULL
#define URSUS_BOARD_ORACLE_KERNEL_SIZE      0U
#define URSUS_BOARD_ORACLE_ROOTFS_OFF       0ULL
#define URSUS_BOARD_ORACLE_ROOTFS_SIZE      0U

#endif
