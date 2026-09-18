# Патчи для репозитория airoha-ursusboot

Патчи предназначены **не для этого репозитория**, а для
[Medvedolog/airoha-ursusboot](https://github.com/Medvedolog/airoha-ursusboot).
Лежат здесь только потому, что в тот репозиторий нет доступа на запись.

Предыдущий набор (data-driven `build.sh`, упаковка FIP, QA-стражи, README)
**уже вмерджен** в `43fca746` и удалён отсюда за ненадобностью.

## Открытый патч

```text
0003-ping-do-not-remove-borrowed-netif.patch   база: 43fca746
```

## Что он чинит

В `43fca746` netif-баг закрыт правильно: `new_netif()` больше не сносит чужой
netif, а `ping`/`tftp` переиспользуют живой через флаг `borrowed` и не удаляют
его на выходе. Но в `cmd/lwip/ping.c` один путь выхода остался без проверки:

```c
ret = ping_raw_init(&ctx);
if (ret < 0) {
        net_lwip_remove_netif(netif);   /* удаляет netif даже если borrowed */
        return ret;
}
```

Если `raw_new(IP_PROTO_ICMP)` вернёт NULL (пул raw-PCB в lwIP небольшой и
фиксированный, при исчерпании — `-ENOMEM`), `ping`, запущенный при поднятом
WebFailsafe, удалит его netif — то есть ровно исходный баг, доживший в одной
ветке обработки ошибки. В `net/lwip/tftp.c` оба места удаления уже под
`if (!borrowed)`; в `ping.c` защищено только одно из двух.

Патч добавляет ту же проверку:

```c
if (!borrowed)
        net_lwip_remove_netif(netif);
```

## Применение

```bash
cd /path/to/airoha-ursusboot
git apply /path/to/0003-ping-do-not-remove-borrowed-netif.patch
bash scripts/qa.sh
```
