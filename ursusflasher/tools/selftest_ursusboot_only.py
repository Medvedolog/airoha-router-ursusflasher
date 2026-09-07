#!/usr/bin/env python3
from pathlib import Path
import hashlib,json,struct,lzma
D=Path(__file__).resolve().parents[1]; M=json.loads((D/'data/MANIFEST.json').read_text()); u=M['ursusboot']; pd=D/'data/payloads/md/ursusboot'
prod=pd/'ursusboot-md-0.1.0-alpha3-update.fip'; ram=pd/'ursusboot-md-0.1.0-alpha3-ram-installer.fip'; pre=pd/'openwrt-airoha-an7581-nokia_xg-040g-md-ubi-preloader.bin'; bl2=pd/'ursusboot-md-0.1.0-alpha3-bl2.bin'; raw=pd/'ursusboot-md-0.1.0-alpha3-u-boot.bin'; lz=pd/'ursusboot-md-0.1.0-alpha3-u-boot.lzma'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(prod)==u['fip_sha256']; assert sha(ram)==u['ram_installer_fip_sha256']; assert sha(pre)==u['preloader_sha256']; assert sha(bl2)==u['bl2_image_sha256']; assert sha(raw)==u['u_boot_sha256']; assert sha(lz)==u['lzma_sha256']
assert len(bl2.read_bytes())==0x20000 and bl2.read_bytes()[:0x800]==b'\xff'*0x800 and bl2.read_bytes()[0x800:0x800+len(pre.read_bytes())]==pre.read_bytes()
UUID=bytes.fromhex('d6d0eea7fcead54b97829934f234b6e4')
def nt(f):
 d=f.read_bytes(); assert struct.unpack_from('<I',d,0)[0]==0xaa640001; pos=16
 while True:
  uid=d[pos:pos+16]; off,size,flags=struct.unpack_from('<QQQ',d,pos+16)
  if uid==UUID:return d[off:off+size],off,size
  assert uid!=b'\0'*16; pos+=40
def decode(x):
 assert x[0]==0x9b; ds=int.from_bytes(x[1:5],'little'); us=int.from_bytes(x[5:13],'little'); assert ds==0x100000
 dec=lzma.LZMADecompressor(format=lzma.FORMAT_RAW,filters=[{'id':lzma.FILTER_LZMA1,'dict_size':ds,'lc':2,'lp':2,'pb':3}]); out=dec.decompress(x[13:],max_length=us+1); assert len(out)==us; return out
x,off,size=nt(prod); assert off==0x27800 and size==0x3eb0f and decode(x)==raw.read_bytes() and lz.read_bytes()==x
print('URSUSBOOT_ALPHA3_FULL_BOOTCHAIN_QA=PASS')
