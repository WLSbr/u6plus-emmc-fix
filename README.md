# UniFi U6+ — eMMC that loses its configuration on every reboot

**Languages / Idiomas:** **English** · [Português](README.pt-BR.md) · [Español](README.es.md)

> **Warning — use at your own risk.** This procedure writes to the eMMC and SPI flash of a device and was tested on
> only 2 U6+ units. A mistake (wrong unit, interrupted write, wrong UART wire, 5 V instead of 3.3 V) can leave the
> device unable to boot. Back up first, check every output, and do not use it on production equipment without a
> spare. Independent project: **not affiliated with or endorsed by Ubiquiti**. No Ubiquiti firmware is distributed
> here; `make_payload.py` downloads the file from the official server. See also `LICENSE`.

Procedure tested on **2 UniFi U6+ units (UAPL6, MT7981, `MK2704` 3.5 GB eMMC)**, both broken after updating to firmware 6.7.54.
Result: both now boot on their own, see all 10 eMMC partitions, show **0 I/O errors**, and the configuration (`/etc/persistent`) survives reboots.

## Symptoms
- Loses adoption and configuration every time it is powered off; goes back to defaults (`ubnt/ubnt`, `192.168.1.20`).
- `dmesg` under Linux:
  ```
  mmc0: switch to bus width 8 failed
  mmc0: switch to bus width 4 failed
  blk_update_request: I/O error, dev mmcblk0, sector 0 ...
  ```
- `cat /proc/partitions` shows only `mmcblk0`, with no `mmcblk0p1..p10`.
- Sometimes: boot loop with a `Kernel panic` in `mt7981_wifi`, or `fwupdate` failing with `Invalid Image Layout!`.
- Downgrading does **not** help (tested on 6.7.31).

## Cause
**Linux** initialises the eMMC at **52 MHz** (`max-frequency = 52000000` in the DTB) with no pad drive-strength configuration, and this eMMC cannot cope with that. **u-boot** uses a slower mode and reads everything without errors. So the chip is not dead.

Fix: in the DTB set `max-frequency = <26000000>` and `drive-strength = <8>` on the eMMC pins.
(Tested: 8 mA alone does **not** fix it; 8 mA + 26 MHz does. I did not test 26 MHz alone.)

## Why you cannot just patch the firmware
The kernel FIT image has a **mandatory RSA signature** (`sha1,rsa2048:uap6_mt7981 (required)`); any DTB modified inside it is rejected. So the boot is driven from u-boot, **without** signature verification:

- This u-boot's autoboot (`bootdelay_process`) does `env_get("bootcmd_real")` and, if it is unset, runs `"bootubnt"`. **`bootcmd` and `preboot` are ignored.**
- We write the `Image` (decompressed kernel, ramdisk embedded) and the patched DTB to a **free eMMC area outside the GPT**, and set `bootcmd_real = run ubntfix; bootubnt` (if anything fails it falls back to the stock boot).
- **The `u-boot` partition (FIP) does not need to be modified**; it was never touched.

Layout used (512-byte blocks):

| Item | LBA | Blocks |
|---|---|---|
| `Image` (48,789,512 B) | `0x300000` | `0x1743d` (95293) |
| `vB.dtb` (17,272 B) | `0x320000` | `0x22` (34) |

The GPT ends at `0x185483` and the disk has 7,405,568 blocks, so this area belongs to no partition.

## What you need
- A **3.3 V** USB-serial adapter (a CH340 worked). On macOS the WCH driver must be approved in *System Settings → Privacy & Security*.
- A network cable from your computer straight to the U6+ PoE injector (u-boot only speaks on `192.168.1.20`).
- Solder (or firmly hold) 3 wires on the UART pads.
- `python3`, `curl`, `dtc` (`brew install dtc`).

### UART (4 pads on the board edge, labelled UART)
| Pad | Function |
|---|---|
| 1 (square) | VCC 3.3 V — **do not connect** |
| 2 | device RX → adapter TX |
| 3 | device TX → adapter RX |
| 4 | GND |

115200 8N1. Source: OpenWrt forum (verify with a multimeter). A loose wire is the #1 cause of a "silent UART".

## Step by step
```bash
export UART=/dev/cu.wchusbserial10        # Linux: /dev/ttyUSB0
# 0) Static IP on your computer (wired to the U6+ injector)
sudo ifconfig en0 alias 192.168.1.2 255.255.255.0       # macOS

# 1) Build the files (downloads official firmware 6.7.31 and checks CRCs)
python3 scripts/make_payload.py out        # expected: Image 0b76818f / vB.dtb 4e7fbf99
mkdir -p fw && cp out/Image out/vB.dtb fw/

# 2) TFTP server (port 69; works without sudo on macOS). Serves ./fw
python3 scripts/tftpd.py &

# 3) Start listening, then power-cycle the device's PoE -> interrupts u-boot
python3 scripts/uart.py break 150          # must print PROMPT

# 4) Check WHICH unit it is, then load the files
python3 scripts/uart.py cmd 'printenv ethaddr' 'setenv ipaddr 192.168.1.20' 'setenv serverip 192.168.1.2' \
  'tftpboot 0x48080000 Image'
python3 scripts/uart.py cmd 'tftpboot 0x4c000000 vB.dtb' \
  'crc32 0x48080000 0x2e87808' 'crc32 0x4c000000 0x4378'   # 0b76818f and 4e7fbf99

# 5) Write in 512 KB chunks (NEVER as a single write)
python3 scripts/uart.py write 0x48080000 0x300000 95293
python3 scripts/uart.py write 0x4c000000 0x320000 34

# 6) Read back and verify (Image first, alone; then the DTB at another address)
python3 scripts/uart.py cmd 'mmc read 0x4a000000 0x300000 0x1743d' 'crc32 0x4a000000 0x2e87808'
python3 scripts/uart.py cmd 'tftpboot 0x4c000000 vB.dtb' 'mmc read 0x4d000000 0x320000 0x22' 'crc32 0x4d000000 0x4378'

# 7) Configure the boot in SPI flash and CHECK every output
python3 scripts/uart.py cmd \
  "setenv ubntfix 'mmc dev 0; mmc read 0x48080000 0x300000 0x1743d; mmc read 0x4c000000 0x320000 0x22; booti 0x48080000 - 0x4c000000'" \
  "setenv bootcmd_real 'run ubntfix; bootubnt'" \
  'printenv ubntfix bootcmd_real' 'saveenv' 'printenv bootcmd_real'

# 8) Reboot and let it come up by itself
python3 scripts/uart.py cmd 'reset'
```
Then (SSH `ubnt`/`ubnt` on `192.168.1.20`): `cat /etc/version` → `BZ.6.7.31`; `grep -c mmcblk0p /proc/partitions` → `10`; `dmesg | grep -c "I/O error"` → `0`.
Persistence test: `echo x > /etc/persistent/t; cfgmtd -w -p /etc/; sync; reboot` and check that `t` is still there.

## Pitfalls (all of them happened)
1. **The first command after `Esc Esc` is swallowed** ("Unknown command"). That is how a `setenv bootcmd_real` silently never got saved. `uart.py cmd/write` already sends a throwaway `version` first. **Always verify with `printenv`.**
2. **An empty Enter repeats the last u-boot command** (it re-downloaded `tftpboot Image` instead of the DTB).
3. **`urescue` does NOT work**: it tries to write the kernel (24139 blocks, ~12 MB) in a single write and u-boot hits a `Synchronous Abort`. Reproduced on both units. It also erases `cfg` and leaves `kernel0` inconsistent. That is why we write in 1024-block chunks.
4. **Do not read hundreds of MB into RAM in u-boot** (a 128 MB `mmc read` overwrote u-boot itself → "Could not initialize timer"). Verification reads must not overlap what you still need.
5. **Check the MAC** (`printenv ethaddr`) before writing; with two units it is easy to mix them up. Two units powered together clash on `192.168.1.20`.
6. Under Linux with the broken eMMC, `fwupdate`/`syswrapper.sh upgrade2` fail (`Could not open MTD device /dev/mmcblk0p9`). Do not insist over SSH.
7. The macOS `tftp` client does not accept a path with a folder; use the `tftpd.py` server.
8. Silent UART = almost always a wire contact problem.

## Limitations
- The `Image` contains the ramdisk: the device always runs **6.7.31**, even if the controller "upgrades" the firmware. For another version, generate a new payload (the FIT offsets change) and **retest**; I did not.
- Disable automatic firmware upgrades in the controller.
- With `bootcmd_real` set, the only way back to the stock boot is to remove it (below).
- I did not recover anything via the `u-boot`/BL2 partitions; if the problem is an `MSDC: CRC error` already in BL2 (the device never reaches u-boot), this procedure does not apply — see the OpenWrt forum (U6+ unbrick, `mtk_uartboot`).

## Revert
```bash
python3 scripts/uart.py break && python3 scripts/uart.py cmd 'setenv bootcmd_real' 'saveenv' 'printenv bootcmd_real'
```

## What is NOT in this repository (on purpose)
- Ubiquiti firmware/kernel (generated by `make_payload.py`).
- Device backups (EEPROM, `factory`, SPI env): they are unit-specific. **Take your own** before writing anything (`dd if=/dev/mmcblk0pN`, using the patched boot, over SSH).
