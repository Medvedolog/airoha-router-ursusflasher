# WebFailsafe: сеть падает от `ping`/`tftpboot`/`dhcp`/`wget`, веб перестаёт подниматься

Статус: **root cause найден, патч не готов**. Это анализ, а не исправленный build.

## Симптомы

- Команда `ping`, запущенная с UART-консоли или через Expert-консоль веб-интерфейса, роняет сеть UrsusBoot.
- Веб-интерфейс UrsusBoot Recovery перестаёт отвечать.

## Границы находки

Разделять два разных класса отказа:

- **«Веб поднялся и умер»** — то, что описано ниже. Подтверждено кодом.
- **«Веб вообще не поднялся»** — отказ на старте (`net_lwip_eth_start()` / `netif_add()` / `tcp_bind` → `goto fail_owned` → `CMD_RET_FAILURE` → `ursus_led_fatal_wait()` в `cmd/ursusdispatch.c`). Этот баг его **не объясняет**; нужен отдельный разбор.

Persistent UrsusBoot из `mtd0` штатно поднимает веб (прогоны на MD/MF) — это подтверждает, что путь подъёма веба сам по себе здоров. Место хранения загрузчика (raw `mtd0` против тома `fip` в UBI) на этот баг не влияет вообще: бинарник один, и в `cmd/ursusdispatch.c` все три ветки (`ursus_ubi_boot()`, factory-kernel, `ursusstockboot`) сходятся в один и тот же `ursus_enter_webfailsafe()`.

## Причина

lwIP-glue U-Boot спроектирован так, будто в системе одновременно живёт **не более одного** сетевого netif — каждая сетевая команда (`ping`, `tftpboot`, `dhcp`, `wget`) сама поднимает netif на время своей работы и сама его убирает.

`net/lwip/net-lwip.c:106-117`:
```c
struct netif *net_lwip_get_netif(void)
{
    struct netif *netif, *found = NULL;
    NETIF_FOREACH(netif) {
        if (!found) found = netif;
        else printf("Error: more than one netif in lwIP\n");
    }
    return found;
}
```

`net/lwip/net-lwip.c:226-284` (`new_netif()`, вызывается из `net_lwip_new_netif()`), первым делом безусловно сносит то, что уже есть, и переставляет lwIP-default на только что созданный netif:
```c
static struct netif *new_netif(struct udevice *udev, bool with_ip)
{
    ...
    netif_remove(net_lwip_get_netif());   // net-lwip.c:242 — сносит ЛЮБОЙ текущий netif
    ...
    netif_add(netif, ...);
    netif_set_default(netif);             // net-lwip.c:281
```

WebFailsafe (`cmd/ursusweb.c`) ломает это допущение: поднимает **один** netif при старте и держит его живым до конца сессии, обслуживая HTTP прямо в этом же netif на каждой итерации цикла:

`cmd/ursusweb.c:2459-2487`:
```c
netif = net_lwip_new_netif(ursus_web_udev);   // создаётся один раз при старте
...
while (!ursus_stop) {
    ursus_uart_shell_poll();                   // живой UART-шелл в том же цикле
    ret = net_lwip_rx(ursus_web_udev, netif);   // и каждая итерация читает именно этот netif
    ...
}
```

При этом и UART-шелл, и веб-интерфейс дают полный доступ к произвольным U-Boot командам без ограничений. Expert-консоль веба, `cmd/ursusweb.c:2005-2015` (`POST /api/console`):
```c
/* Expert Web console is deliberately the real U-Boot command line.
 * No allowlist and no write-operation lock are imposed here. */
...
ursus_console_capture(cmd);   // -> run_command(cmd, 0) в ursus_console_capture()
```

## Механизм

1. WebFailsafe поднят, его единственный netif обслуживает и UART-шелл, и HTTP.
2. Оператор выполняет `ping ...` — с UART (`cmd/ursusweb.c:2371`, `run_command(ursus_uart_line, 0)`, без фильтрации) либо через `POST /api/console` (`cmd/ursusweb.c:1949`).
3. `do_ping()` (`cmd/lwip/ping.c`) вызывает `net_lwip_new_netif()` → `new_netif()` → строка 242 сносит текущий (единственный в lwIP) netif — то есть netif самого WebFailsafe.
4. `netif_remove()` память не освобождает, но вырезает netif из `netif_list`, зануляет default (`lib/lwip/lwip/src/core/netif.c:810-812`) и аборчит TCP-pcb, привязанные к адресу.
5. WebFailsafe продолжает крутить `net_lwip_rx(ursus_web_udev, netif)` по указателю на вырезанный netif: входящие пакеты ещё разбираются, но маршрута наружу больше нет (`netif_default == NULL`, список пуст → `ip4_route()` → NULL → `ERR_RTE`). Сервер замолкает намертво.

Это детерминировано, а не гонка: любая сетевая команда (`ping`, `tftpboot`, `dhcp`, `wget`), выполненная, пока WebFailsafe уже поднят, разрушает его netif.

Жёсткий краш при этом возможен, но чтением кода не доказан — подтверждённое последствие именно потеря маршрутизации, а не use-after-free.

## Почему штатный TFTP-перенос пейлоадов при этом работает

`net/lwip/tftp.c:198` вызывает тот же `net_lwip_new_netif()`, то есть `tftpboot` ломает netif ровно так же. Но в штатном потоке пересечения нет:

- TFTP-пути дефолтного env (`boot_tftp`, `boot_tftp_forever`, `boot_tftp_write_fip`, `boot_tftp_production`, `boot_tftp_recovery`) запускаются из `bootcmd`/dispatch **до** WebFailsafe либо **вместо** него.
- Сам WebFailsafe сетевых команд не выполняет: все `run_command()` в `cmd/ursusweb.c` — это только `ubi`/`mtd` (1432-1458), `bootm` и `reset` (2553-2569).

Открытый вопрос: баннер `cmd/ursusweb.c:2426` объявляет `URSUS_FIP_SELFUPDATE_INPUTS=web,tftp,uart,wget`. Если «tftp»/«wget» здесь означают ввод команды в UART-шелле при уже поднятом WebFailsafe — это ровно то самое пересечение, и оно должно убивать веб каждый раз. Требуется уточнение реального сценария.

## Как это выглядит для оператора

- **«ping положил UrsusBoot»** — прямое следствие сценария выше.
- **«веб не отвечает»** — если сетевая команда была выполнена ранее в этой же сессии (например, с UART, пока веб уже поднят), netif WebFailsafe уже тихо оторван от списка lwIP. Устройство формально живо, UART-шелл отвечает, но HTTP наружу не уходит — выглядит как «страница не грузится», без явного крах-сообщения.

Важно: это **не** то же самое, что «веб не поднялся с самого начала». Если `URSUS_WEBFAILSAFE_READY` в UART-логе был, а потом веб замолчал — это описанный баг. Если маркера не было вовсе — причина другая.

## Куда смотреть при подтверждении на железе

По UART до/после `ping`:
- наличие `URSUS_HTTP_LISTEN_OK port=80` / `URSUS_WEBFAILSAFE_READY` до команды — подтверждает, что веб поднимался штатно;
- `Error: more than one netif in lwIP` от `net_lwip_get_netif()` — признак того, что список netif уже в противоречивом состоянии;
- прекращение ответов веб-интерфейса сразу после любой сетевой команды при живом UART-шелле — основной признак.

## Варианты исправления

1. **Быстрый и безопасный**: заблокировать сетевые команды (`ping`, `tftpboot`, `dhcp`, `wget`, `nfs`, …) в `ursus_console_capture()` (`cmd/ursusweb.c`), пока `ursus_web_running` истинен — и на UART-шелле, и на `/api/console`.
2. **Более правильный, но более рискованный**: изменить `new_netif()` в `net-lwip.c` так, чтобы она не сносила чужой netif безусловно — сравнивать с уже существующим для того же `udev`/IP и переиспользовать его, либо дать WebFailsafe собственный API поверх уже поднятого netif вместо вызова `net_lwip_new_netif()` внутри `do_ping()`/аналогичных команд.

Вариант 1 не трогает общий lwIP-glue (наследие апстрима U-Boot) и меньше риска сломать что-то ещё; вариант 2 устраняет причину, а не только один путь её проявления, но требует более широкого регрессионного прогона.

## Связь с MAC/ARP-нестабильностью

Отдельная, но смежная находка: `CONFIG_NET_RANDOM_ETHADDR=y` вместе с хрупким `ethaddr_factory` (single-shot, без диагностики отказа) и `reset_factory`, обнуляющим `ubootenv`/`ubootenv2` после каждой записи FIP, — эта комбинация уже давала нестабильный MAC-адрес UrsusBoot независимо от netif-бага выше. Обе проблемы стоит чинить, они не исключают друг друга.
