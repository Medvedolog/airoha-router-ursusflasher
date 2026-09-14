/* SPDX-License-Identifier: GPL-2.0+ */
#ifndef __URSUS_BOARD_POLICY_H__
#define __URSUS_BOARD_POLICY_H__

#define URSUS_BOARD_POLICY_ID              "xg140-md"
#define URSUS_BOARD_MODEL                  "Bell XG-140G-MD"
#define URSUS_BOARD_COMPATIBLE             "bell,xg-140g-md"

/* XG140 keeps the vendor-owned boot-area environment and stock A/B layout. */
#define URSUS_BOARD_ALLOW_UBI_BOOT          0
#define URSUS_BOARD_ALLOW_FACTORY_FIT       0
#define URSUS_BOARD_UBI_PROBE_OFF           0x00020000ULL
#define URSUS_BOARD_FACTORY_KERNEL_OFF      0x000c0000ULL
#define URSUS_BOARD_FACTORY_KERNEL_SIZE     0x00800000ULL

#define URSUS_BOARD_STOCK_MASTER_BASE       0x000c0000ULL
#define URSUS_BOARD_STOCK_SLAVE_BASE        0x02940000ULL
#define URSUS_BOARD_STOCK_SLOT_SIZE         0x02880000ULL
#define URSUS_BOARD_STOCK_ENV_BASE          0x0007c000ULL
#define URSUS_BOARD_STOCK_ENV_SIZE          0x00004000U
#define URSUS_BOARD_STOCK_TRX_HDR_SIZE      0x00000100U
#define URSUS_BOARD_STOCK_HDR_MAGIC         "HDR2"
#define URSUS_BOARD_STOCK_FIT_MAX_SIZE      0x02800000U

/* Same tcboot/Linux ABI family as XG-040G-MD; hardware acceptance remains pending. */
#define URSUS_BOARD_ROOT_MASTER             "/dev/mtdblock3 ro"
#define URSUS_BOARD_ROOT_SLAVE              "/dev/mtdblock5 ro"

/* Do not synthesize MD SerDes overrides on XG140: pass vendor env values through. */
#define URSUS_BOARD_APPEND_SERDES_ARGS(dst, cap) 0
#define URSUS_BOARD_STOCK_ARGS_MARKER \
    "URSUS_STOCKBOOT_TCBOOT_XG140_ARGS source=vendor_env"

/* No XG140 full-backup oracle is baked into common code. */
#define URSUS_BOARD_ORACLE_FIT_SIZE         0U
#define URSUS_BOARD_ORACLE_KERNEL_OFF       0ULL
#define URSUS_BOARD_ORACLE_KERNEL_SIZE      0U
#define URSUS_BOARD_ORACLE_ROOTFS_OFF       0ULL
#define URSUS_BOARD_ORACLE_ROOTFS_SIZE      0U

#endif
