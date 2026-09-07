#!/usr/bin/env python3
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
terms = json.loads((ROOT / "data/UI_TERMS.json").read_text(encoding="utf-8"))
a = terms["expert_actions"]
assert a["install_or_repair_bootloader"]["ru"] == "Установить или переустановить загрузчик"
assert a["custom_openwrt"]["ru"] == "Записать пользовательскую прошивку OpenWrt"
assert a["restore_nokia"]["ru"] == "Восстановить заводскую прошивку Nokia"
assert a["full_backup"]["ru"] == "Создать полную копию flash-памяти"
assert a["capabilities"]["ru"] == "Доступные операции для устройства"
expert = (ROOT / "data/expert.py").read_text(encoding="utf-8")
network = (ROOT / "data/network_guidance.py").read_text(encoding="utf-8")
assert "! — операция может выполнять запись во flash-память (NAND)" in expert
assert "Для прошивки рекомендуется использовать порты LAN2 или LAN3" in network
assert "может выполнять запись во flash-память (NAND)" in expert
assert terms["execution_environments"]["PERSISTENT_ROOT"]["ru"] == "установленная OpenWrt во flash-памяти"
assert terms["methods"]["TELNET_NOKIA_STOCK"]["ru"] == "Через Telnet из запущенной заводской прошивки Nokia"
for bad in (
    "Установить или починить загрузчик",
    "Записать свою прошивку OpenWrt",
    "Вернуть заводскую прошивку Nokia",
    "Снять полную копию flash-памяти",
    "Что этот роутер позволяет сделать",
    "Для прошивки лучше использовать LAN2 или LAN3",
):
    assert bad not in expert + network + json.dumps(terms, ensure_ascii=False), bad
print("STATEUI5_RU_TERMS_QA=PASS")
