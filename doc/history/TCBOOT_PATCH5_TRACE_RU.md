# tcboot MD patch5 TRACE — следующий аппаратный LAB

Patch4 hardware run подтвердил UBI erase/attach, создание volume, saveenv и reset. Два дефекта обнаружены по UART:

1. `flash read` отсутствует в tcboot, поэтому CAL_SAVE не был выполнен, а shell-цепочка всё равно дошла до erase.
2. `$filesize` был изменён промежуточным `ubi read` до `0x40000`, поэтому `fit` был создан и записан только на 256 KiB вместо полного sysupgrade 10518808 bytes. После reset `iminfo` видел заголовок, но kernel CRC32 уже не сходился.

Patch5:

- сохраняет `us=$filesize` и `ua=$fileaddr` сразу после HTTP upload;
- использует `$us/$ua` до конца transaction;
- читает stock bosa/ri через `mtd read ubi` до erase;
- не начинает erase при ошибке CAL_SAVE;
- делает полный FIT readback/cmp на исходный HTTP upload size.

Статус: LAB_WRITE, не HW_VERIFIED.
