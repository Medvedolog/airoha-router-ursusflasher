from __future__ import annotations

import re

import board_profiles as bp
import proven_backend as pb
import xg140_profile as xp


def stock_identity(host: str) -> tuple[str, str, object]:
    module = pb._load_stock_web_module()
    user = str(getattr(module, "DEFAULT_WEB_USER", "CMCCAdmin") or "CMCCAdmin")
    password = str(getattr(module, "DEFAULT_WEB_PASSWORD", "") or "")
    if not password:
        raise RuntimeError("stock Web default password is unavailable")
    pb._register_log_secret(password)
    client = module.StockWeb(host)
    try:
        try:
            client.login(user, password, allow_plain=False)
        except Exception:
            client = module.StockWeb(host)
            client.login(user, password, allow_plain=True)
        info = module.StockSetup(client).read_device_info()
    finally:
        try:
            client.logout()
        except Exception:
            pass
    model = str(info.get("model") or "")
    chipset = str(info.get("chipset") or "")
    match = bp.match_profile(model=model, soc=chipset)
    if not match or match[0] != xp.FAMILY:
        raise RuntimeError(f"stock device is not XG140/AN7581: model={model!r} chipset={chipset!r}")
    return model, chipset, module


def open_stock_access(host: str) -> pb.StockAccess:
    model, chipset, module = stock_identity(host)
    user = str(getattr(module, "DEFAULT_WEB_USER", "CMCCAdmin") or "CMCCAdmin")
    password = str(getattr(module, "DEFAULT_WEB_PASSWORD", "") or "")
    pb._STARTUP_DEVICE_PROFILE.clear()
    pb._STARTUP_DEVICE_PROFILE.update({
        "family": xp.FAMILY, "model": model or xp.MODEL,
        "chipset": chipset or xp.SOC, "host": host,
        "verified": True, "source": "ursusflasher-xg140-stock-web",
    })
    pb._STARTUP_WEB_AUTH.clear()
    pb._STARTUP_WEB_AUTH.update({"host": host, "user": user, "password": password})
    old_supported = tuple(getattr(module, "SUPPORTED_INSTALL_MODELS", ("XG-040G-MD",)))
    module.SUPPORTED_INSTALL_MODELS = tuple(dict.fromkeys(old_supported + ("XG-140G-MD", "XG140GMC2P5G")))
    try:
        access = pb._automatic_stock_web_access(host, module, offer_interactive_plain_retry=False)
    finally:
        module.SUPPORTED_INSTALL_MODELS = old_supported
    access.family = xp.FAMILY
    access.model_name = model
    access.chipset = chipset
    access.model_verified = True
    access.model_verification_source = "xg140-stock-web-board-profile"
    return access


def uid0_telnet(access: pb.StockAccess):
    # XG140 stock userland is MD-compatible; model authorization happened above.
    telnet = pb.login_root_family(access, "md", allow_service_provisioning=True)
    rc, out = telnet.command_clean("id -u")
    if rc or not re.search(r"(?:^|\n)0(?:\n|$)", out.strip() + "\n"):
        telnet.close()
        raise RuntimeError("XG140 stock Telnet session did not prove UID 0")
    return telnet
