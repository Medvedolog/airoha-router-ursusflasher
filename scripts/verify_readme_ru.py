#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
text = (ROOT / 'README.md').read_text(encoding='utf-8')

# The title README is an operating guide, not a development notebook.
forbidden = (
    'production-кандидат',
    'host-side инструмент',
    'persistent-write пункты',
    'initramfs install backend',
    'live writable dump',
    'Restore-grade exact capture',
    'Установить или починить загрузчик',
    'Записать свою прошивку OpenWrt',
    'Вернуть заводскую прошивку Nokia',
    'Снять полную копию flash-памяти',
    'Что этот роутер позволяет сделать',
)
for phrase in forbidden:
    assert phrase not in text, phrase

required = (
    '## Как работает ONE-CLICK',
    '## Каналы управления и передачи файлов',
    '## Что проверяется перед записью',
    '## Что проверяется после записи',
    'HTTP/Web + Telnet',
    'SSH',
    'SCP',
    'HTTP API',
    'TFTP',
    'XMODEM',
    'Для прошивки рекомендуется использовать порты LAN2 или LAN3',
    'Установить или переустановить загрузчик',
    'Записать пользовательскую прошивку OpenWrt',
    'Восстановить заводскую прошивку Nokia',
    'Создать полную копию flash-памяти',
    'Состояние устройства и доступные операции',
)
for phrase in required:
    assert phrase in text, phrase

print('README_RU_OPERATIONS_QA=PASS')
