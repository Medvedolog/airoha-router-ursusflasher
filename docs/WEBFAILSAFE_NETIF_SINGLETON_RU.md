# WebFailsafe: сеть падает от `ping`/`tftpboot`/`dhcp`/`wget`, веб перестаёт подниматься

Статус: **root cause найден, патч не готов**. Это анализ, а не исправленный build.

## Симптомы

- Веб-интерфейс UrsusBoot Recovery иногда не открывается / перестаёт отвечать.
- Команда `ping`, запущенная с UART-консоли или через Expert-консоль веб-интерфейса, приводит к краху UrsusBoot.

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

## Механизм краша

1. WebFailsafe поднят, его единственный netif обслуживает и UART-шелл, и HTTP.
2. Оператор выполняет `ping ...` — с UART либо через `POST /api/console` в вебе.
3. `do_ping()` (`cmd/lwip/ping.c`) вызывает `net_lwip_new_netif()` → `new_netif()` → строка 242 сносит текущий (единственный в lwIP) netif — то есть netif самого WebFailsafe — и `netif_set_default()` переставляет lwIP-default на временный netif команды `ping`.
4. `ping` завершается и освобождает свой временный netif (`net_lwip_remove_netif()`), а lwIP-default остаётся висячим указателем.
5. WebFailsafe пытается отправить ответ (для `/api/console` — прямо из этого же обработчика запроса) через netif, который уже вырезан из списка lwIP/уже освобождён — use-after-free.

Это детерминировано, а не гонка: любая сетевая команда (`ping`, `tftpboot`, `dhcp`, `wget`), выполненная, пока WebFailsafe уже поднят, разрушает его netif.

## Как это выглядит для оператора

- **«ping крашит UrsusBoot»** — прямое следствие сценария выше.
- **«веб не поднимается»** — если сетевая команда была выполнена ранее в этой же сессии (например, с UART, пока веб уже поднят), netif WebFailsafe уже тихо оторван от списка lwIP. Процесс формально жив, но ничего больше не может отправить/принять — выглядит как «страница не грузится», без явного крах-сообщения.

## Куда смотреть при подтверждении на железе

По UART до/после `ping`:
- `Error: more than one netif in lwIP` от `net_lwip_get_netif()` — признак того, что список netif уже в противоречивом состоянии;
- зависание/сброс сразу после ответа на `POST /api/console` с командой `ping`;
- прекращение ответов веб-интерфейса после любой сетевой команды, введённой с UART, без явного краша.

## Варианты исправления

1. **Быстрый и безопасный**: заблокировать сетевые команды (`ping`, `tftpboot`, `dhcp`, `wget`, `nfs`, …) в `ursus_console_capture()` (`cmd/ursusweb.c`), пока `ursus_web_running` истинен — и на UART-шелле, и на `/api/console`.
2. **Более правильный, но более рискованный**: изменить `new_netif()` в `net-lwip.c` так, чтобы она не сносила чужой netif безусловно — сравнивать с уже существующим для того же `udev`/IP и переиспользовать его, либо дать WebFailsafe собственный API поверх уже поднятого netif вместо вызова `net_lwip_new_netif()` внутри `do_ping()`/аналогичных команд.

Вариант 1 не трогает общий lwIP-glue (наследие апстрима U-Boot) и меньше риска сломать что-то ещё; вариант 2 устраняет причину, а не только один путь её проявления, но требует более широкого регрессионного прогона.

## Связь с MAC/ARP-нестабильностью

Отдельная, но смежная находка: `CONFIG_NET_RANDOM_ETHADDR=y` вместе с хрупким `ethaddr_factory` (single-shot, без диагностики отказа) и `reset_factory`, обнуляющим `ubootenv`/`ubootenv2` после каждой записи FIP, — эта комбинация уже давала нестабильный MAC-адрес UrsusBoot независимо от netif-бага выше. Обе проблемы стоит чинить, они не исключают друг друга.
