#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, shutil, subprocess, sys
from pathlib import Path
HERE=Path(__file__).resolve()
ROOT=HERE.parents[2]
MANIFEST=ROOT/"config"/"UNAMEONE_2026-09-16_PAYLOADS.json"
BOOTCHAIN_MANIFEST=ROOT/"config"/"VANILLA_BOOT_CHAIN_PROFILES.json"

def sha256(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""): h.update(chunk)
    return h.hexdigest()

def checked(path:Path, expected_sha:str|None=None, expected_size:int|None=None)->dict:
    if not path.is_file(): raise SystemExit(f"ERROR: missing input: {path}")
    digest=sha256(path); size=path.stat().st_size
    if expected_sha and digest!=expected_sha.lower():
        raise SystemExit(f"ERROR: SHA256 mismatch for {path.name}: {digest} != {expected_sha}")
    if expected_size is not None and size!=expected_size:
        raise SystemExit(f"ERROR: size mismatch for {path.name}: {size} != {expected_size}")
    return {"sha256":digest,"size":size}

def main()->int:
    ap=argparse.ArgumentParser(description="Assemble one exact Ursus Vanilla pregnant payload set")
    ap.add_argument("--family",choices=("md","mf"),required=True)
    ap.add_argument("--runtime",type=Path,required=True)
    ap.add_argument("--production",type=Path,required=True)
    ap.add_argument("--fip",type=Path,required=True)
    ap.add_argument("--preloader",type=Path,required=True)
    ap.add_argument("--output-root",type=Path,required=True)
    ap.add_argument("--source-commit",default="")
    ap.add_argument("--snapshot",default="")
    ns=ap.parse_args()
    manifest=json.loads(MANIFEST.read_text(encoding="utf-8"))
    profile="xg040-"+ns.family
    spec=manifest["profiles"][profile]; prod_spec=spec["ubi_sysupgrade"]
    boot_manifest=json.loads(BOOTCHAIN_MANIFEST.read_text(encoding="utf-8")); boot_spec=boot_manifest["profiles"][profile]
    prod=checked(ns.production,str(prod_spec["sha256"]),int(prod_spec["size"]))
    runtime=checked(ns.runtime)
    fip=checked(ns.fip,str(boot_spec["fip"]["sha256"]),int(boot_spec["fip"]["size"]))
    preloader=checked(ns.preloader,str(boot_spec["preloader"]["sha256"]),int(boot_spec["preloader"]["size"]))
    if not (0<preloader["size"]<=129024): raise SystemExit("ERROR: preloader does not fit BL2 after mandatory 0x800 prefix")
    sys.path.insert(0,str(ROOT/"ursusflasher"/"src"))
    import stock_fit_initramfs as sfi
    rc=sfi.source_fit_contract(ns.runtime.read_bytes())
    if int(rc["fit_total_size"])!=runtime["size"]: raise SystemExit("ERROR: runtime has untracked bytes after FIT")
    out=ns.output_root/ns.family; out.mkdir(parents=True,exist_ok=True)
    names={"runtime":"runtime.itb","production":str(prod_spec["filename"]),"fip":"vanilla-bl31-uboot.fip","preloader":"vanilla-preloader.bin"}
    sources={"runtime":ns.runtime,"production":ns.production,"fip":ns.fip,"preloader":ns.preloader}
    metas={"runtime":runtime,"production":prod,"fip":fip,"preloader":preloader}
    for role,source in sources.items(): shutil.copyfile(source,out/names[role])
    commit=ns.source_commit
    if not commit:
        try: commit=subprocess.check_output(["git","-C",str(ROOT),"rev-parse","HEAD"],text=True).strip()
        except Exception: commit="unknown"
    payload={
      "schema":1,"mode":"VANILLA_PREGNANT_MIGRATION","profile":profile,"family":ns.family,
      "source_commit":commit,"snapshot":ns.snapshot,"unameone_edition":manifest["edition"],
      "unameone_build_date":manifest["build_date"],"unameone_sha256":prod["sha256"],
      "boot_chain":{"repository":boot_manifest["source"]["repository"],"commit":boot_manifest["source"]["commit"],"release_version":boot_manifest["source"]["release_version"],"fip_status":boot_spec["fip"]["status"],"preloader_status":boot_spec["preloader"]["status"]},
      "files":{role:{"filename":names[role],"sha256":metas[role]["sha256"],"size":metas[role]["size"]} for role in ("runtime","production","fip","preloader")},
      "contracts":{"production_child_exact_manifest_bytes":True,"boot_chain_exact_profile_bytes":True,"runtime_fit_has_no_untracked_tail":True,"bl2_written_last_by_stage2":True,"identity_restore_required":True,"single_operator_confirmation":True,"hw_status":"HW_PENDING"}
    }
    (out/"PAYLOAD.json").write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(f"PREGNANT_PAYLOAD_ASSEMBLY=PASS family={ns.family}")
    for role in ("production","runtime","fip","preloader"): print(f"{role.upper()}_SHA256={metas[role]['sha256']}")
    return 0
if __name__=="__main__": raise SystemExit(main())
