// SPDX-License-Identifier: GPL-2.0-only
// UrsusFlasher raw boot-block writer for OpenWrt/Airoha AN7581.
// Scope is deliberately narrow: offset 0, fixed user-supplied length, eraseblock-aligned.
#define _FILE_OFFSET_BITS 64
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <mtd/mtd-user.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

static void die(const char *what) {
    fprintf(stderr, "URSUS_MTD_RAW_ERROR=%s errno=%d (%s)\n", what, errno, strerror(errno));
    exit(2);
}

static void usage(const char *p) {
    fprintf(stderr, "usage: %s write /dev/mtdX image.bin length\n", p);
    exit(2);
}

static size_t parse_size(const char *s) {
    char *end = NULL;
    unsigned long long v = strtoull(s, &end, 0);
    if (!s[0] || !end || *end || !v || v > SIZE_MAX) usage("ursus-mtd-raw");
    return (size_t)v;
}

static void read_full(int fd, void *buf, size_t len) {
    size_t pos = 0;
    while (pos < len) {
        ssize_t n = read(fd, (char *)buf + pos, len - pos);
        if (n < 0) { if (errno == EINTR) continue; die("read-image"); }
        if (!n) { errno = EIO; die("short-image"); }
        pos += (size_t)n;
    }
    char extra;
    if (read(fd, &extra, 1) != 0) { errno = EFBIG; die("image-too-large"); }
}

static void pwrite_full(int fd, const void *buf, size_t len, off_t off) {
    size_t pos = 0;
    while (pos < len) {
        ssize_t n = pwrite(fd, (const char *)buf + pos, len - pos, off + (off_t)pos);
        if (n < 0) { if (errno == EINTR) continue; die("mtd-write"); }
        if (!n) { errno = EIO; die("mtd-short-write"); }
        pos += (size_t)n;
    }
}

int main(int argc, char **argv) {
    if (argc != 5 || strcmp(argv[1], "write")) usage(argv[0]);
    const char *dev = argv[2], *image = argv[3];
    size_t len = parse_size(argv[4]);
    int ifd = open(image, O_RDONLY | O_CLOEXEC);
    if (ifd < 0) die("open-image");
    struct stat st;
    if (fstat(ifd, &st) || st.st_size != (off_t)len) { errno = EINVAL; die("image-size"); }
    void *buf = malloc(len);
    if (!buf) die("malloc");
    read_full(ifd, buf, len);
    close(ifd);

    int fd = open(dev, O_RDWR | O_SYNC | O_CLOEXEC);
    if (fd < 0) die("open-mtd-rw");
    struct mtd_info_user info;
    if (ioctl(fd, MEMGETINFO, &info) < 0) die("MEMGETINFO");
    if (!info.erasesize || !info.writesize || len > info.size || len % info.erasesize || len % info.writesize) {
        errno = EINVAL; die("geometry");
    }
    printf("URSUS_MTD_RAW_PREFLIGHT size=%u erase=%u write=%u length=%zu\n",
           info.size, info.erasesize, info.writesize, len);
    fflush(stdout);

    for (uint64_t off = 0; off < len; off += info.erasesize) {
        __kernel_loff_t q = (__kernel_loff_t)off;
        int rc = ioctl(fd, MEMGETBADBLOCK, &q);
        if (rc > 0) { errno = EIO; die("bad-block-in-boot-range"); }
        if (rc < 0 && errno != EOPNOTSUPP && errno != ENOTTY) die("MEMGETBADBLOCK");
    }

    printf("URSUS_MTD_RAW_WRITE_STARTED length=%zu\n", len);
    fflush(stdout);
    for (uint64_t off = 0; off < len; off += info.erasesize) {
        struct erase_info_user ei = { .start = (uint32_t)off, .length = info.erasesize };
        if (ioctl(fd, MEMERASE, &ei) < 0) die("MEMERASE");
    }
    for (size_t off = 0; off < len; off += info.writesize) {
        pwrite_full(fd, (const char *)buf + off, info.writesize, (off_t)off);
    }
    if (fsync(fd) < 0) die("fsync");
    close(fd);
    free(buf);
    printf("URSUS_MTD_RAW_WRITE_FINISHED length=%zu\n", len);
    return 0;
}
