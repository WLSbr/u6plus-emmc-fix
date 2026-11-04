#!/usr/bin/env python3
"""Gera o kernel (Image) e o DTB corrigidos para o UniFi U6+ (UAPL6 / MT7981).

Baixa o firmware oficial, extrai o FIT do kernel0, descomprime o kernel (lzma),
extrai o DTB do U6+ e aplica a correcao da eMMC: clock 26 MHz + drive-strength 8 mA.
Requer: python3, curl, dtc (brew install dtc / apt install device-tree-compiler).
Uso: python3 make_payload.py [pasta_de_saida]   (padrao: ./out)
"""
import lzma, os, re, struct, subprocess, sys, zlib

FW_URL = ("https://fw-download.ubnt.com/data/unifi-firmware/"
          "2932-UAPL6-6.7.31-b621c5ba-52ef-4853-b113-e776f276871f.bin")
KERNEL0_OFFSET = 923253          # offset do FIT (magic d00dfeed) dentro do .bin
OUT = sys.argv[1] if len(sys.argv) > 1 else "out"
EXPECT = {"Image": "0b76818f", "vB.dtb": "4e7fbf99"}   # CRC32 validados em 2 aparelhos
PINS = '"PWM0", "SPI0_CLK", "SPI0_MOSI", "SPI0_MISO", "SPI0_CS", "SPI0_HOLD", "SPI0_WP", "SPI1_CLK", "SPI1_MOSI", "SPI1_MISO", "SPI1_CS"'

os.makedirs(OUT, exist_ok=True)
fw = os.path.join(OUT, "U6P_6.7.31.bin")
if not os.path.exists(fw):
    subprocess.run(["curl", "-sL", "-o", fw, FW_URL], check=True)
d = open(fw, "rb").read()
o = KERNEL0_OFFSET
assert d[o:o+4] == b"\xd0\x0d\xfe\xed", "firmware diferente do esperado"
fit = d[o:o+struct.unpack(">I", d[o+4:o+8])[0]]

# percorre o FIT (FDT) e pega os blobs 'data' de kernel-1 e fdt-u6-plus
_, _, off_s, off_str, _, _, _, _, sz_str, sz_s = struct.unpack(">10I", fit[:40])
st = fit[off_str:off_str+sz_str]
p, path, blobs = off_s, [], {}
while p < off_s + sz_s:
    t = struct.unpack(">I", fit[p:p+4])[0]; p += 4
    if t == 1:
        e = fit.index(b"\0", p); path.append(fit[p:e].decode()); p = (e + 4) & ~3
    elif t == 2: path.pop()
    elif t == 3:
        ln, no = struct.unpack(">II", fit[p:p+8]); p += 8
        v = fit[p:p+ln]; p = (p + ln + 3) & ~3
        if st[no:st.index(b"\0", no)] == b"data": blobs["/".join(path)] = v
    elif t == 9: break

image = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE).decompress(blobs["/images/kernel-1"])
stock = blobs["/images/fdt-u6-plus"]
open(os.path.join(OUT, "Image"), "wb").write(image)
open(os.path.join(OUT, "u6plus.dtb"), "wb").write(stock)

dts = subprocess.run(["dtc", "-I", "dtb", "-O", "dts"], input=stock, capture_output=True).stdout.decode()
conf = "\n\t\t\tconf-all {\n\t\t\t\tpins = %s;\n\t\t\t\tdrive-strength = <8>;\n\t\t\t};\n" % PINS
for n in ("mmc0-pins-default", "mmc0-pins-uhs"):
    dts = re.sub(r"(%s \{.*?\n\t\t\t\};\n)" % n, lambda m: m.group(1) + conf, dts, count=1, flags=re.S)
assert "max-frequency = <0x3197500>;" in dts
dts = dts.replace("max-frequency = <0x3197500>;", "max-frequency = <26000000>;")
open(os.path.join(OUT, "vB.dts"), "w").write(dts)
subprocess.run(["dtc", "-I", "dts", "-O", "dtb", "-o", os.path.join(OUT, "vB.dtb"),
                os.path.join(OUT, "vB.dts")], capture_output=True, check=True)

ok = True
for name, want in EXPECT.items():
    b = open(os.path.join(OUT, name), "rb").read()
    got = "%08x" % (zlib.crc32(b) & 0xffffffff)
    blocks = -(-len(b) // 512)
    print("%-8s %9d bytes  %6d blocos (0x%x)  crc32 %s  %s" % (name, len(b), blocks, blocks, got,
          "OK" if got == want else "DIFERENTE (esperado %s)" % want))
    ok &= got == want
sys.exit(0 if ok else 1)
