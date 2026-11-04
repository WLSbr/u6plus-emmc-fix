# UniFi U6+ — eMMC que pierde la configuración en cada reinicio

**Idiomas / Languages:** [English](README.md) · [Português](README.pt-BR.md) · **Español**

> **Aviso — úsalo bajo tu propia responsabilidad.** Este procedimiento escribe en la eMMC y en la flash SPI de un equipo
> y solo se probó en 2 unidades U6+. Un error (unidad equivocada, escritura interrumpida, cable mal puesto en la UART,
> 5 V en lugar de 3,3 V) puede dejar el equipo sin arrancar. Haz una copia de seguridad antes, comprueba cada salida y
> no lo uses en equipos en producción sin un repuesto. Proyecto independiente: **no está afiliado ni respaldado por
> Ubiquiti**. Aquí no se distribuye ningún firmware de Ubiquiti; `make_payload.py` descarga el archivo del servidor
> oficial. Consulta también `LICENSE`.

Procedimiento probado en **2 UniFi U6+ (UAPL6, MT7981, eMMC `MK2704` de 3,5 GB)**, ambos averiados tras actualizar al firmware 6.7.54.
Resultado: los dos arrancan solos, ven las 10 particiones de la eMMC, tienen **0 errores de I/O** y la configuración (`/etc/persistent`) sobrevive a los reinicios.

## Síntomas
- Pierde la adopción y la configuración cada vez que se apaga; vuelve a los valores de fábrica (`ubnt/ubnt`, `192.168.1.20`).
- `dmesg` en Linux:
  ```
  mmc0: switch to bus width 8 failed
  mmc0: switch to bus width 4 failed
  blk_update_request: I/O error, dev mmcblk0, sector 0 ...
  ```
- `cat /proc/partitions` muestra solo `mmcblk0`, sin `mmcblk0p1..p10`.
- A veces: bucle de arranque con `Kernel panic` en `mt7981_wifi`, o `fwupdate` con `Invalid Image Layout!`.
- Bajar de versión **no** lo soluciona (probado en 6.7.31).

## Causa
**Linux** inicializa la eMMC a **52 MHz** (`max-frequency = 52000000` en el DTB) sin configurar la intensidad de las señales, y esta eMMC no lo soporta. **u-boot** usa un modo más lento y lee todo sin errores. Es decir, el chip no está muerto.

Corrección: en el DTB poner `max-frequency = <26000000>` y `drive-strength = <8>` en los pines de la eMMC.
(Probado: solo 8 mA **no** basta; 8 mA + 26 MHz sí. No probé solo 26 MHz.)

## Por qué no basta con modificar el firmware
La imagen FIT del kernel tiene una **firma RSA obligatoria** (`sha1,rsa2048:uap6_mt7981 (required)`); cualquier DTB modificado dentro de ella se rechaza. Por eso el arranque se hace desde u-boot, **sin** verificar la firma:

- El autoboot de este u-boot (`bootdelay_process`) hace `env_get("bootcmd_real")` y, si no existe, ejecuta `"bootubnt"`. **`bootcmd` y `preboot` se ignoran.**
- Escribimos la `Image` (kernel descomprimido, con el ramdisk incluido) y el DTB corregido en una **zona libre de la eMMC fuera de la GPT**, y definimos `bootcmd_real = run ubntfix; bootubnt` (si algo falla, vuelve al arranque original).
- **No hace falta modificar la partición `u-boot` (FIP)**; nunca se tocó.

Distribución usada (bloques de 512 B):

| Elemento | LBA | Bloques |
|---|---|---|
| `Image` (48 789 512 B) | `0x300000` | `0x1743d` (95293) |
| `vB.dtb` (17 272 B) | `0x320000` | `0x22` (34) |

La GPT termina en `0x185483` y el disco tiene 7 405 568 bloques, así que esa zona no pertenece a ninguna partición.

## Material necesario
- Adaptador USB-serie de **3,3 V** (un CH340 funcionó). En macOS hay que aprobar el driver de WCH en *Ajustes del Sistema → Privacidad y seguridad*.
- Cable de red del ordenador directo al inyector PoE del U6+ (u-boot solo habla en `192.168.1.20`).
- Soldar (o sujetar firmemente) 3 cables en los pads de la UART.
- `python3`, `curl`, `dtc` (`brew install dtc`).

### UART (4 pads en el borde de la placa, marcados UART)
| Pad | Función |
|---|---|
| 1 (cuadrado) | VCC 3,3 V — **no conectar** |
| 2 | RX del equipo → TX del adaptador |
| 3 | TX del equipo → RX del adaptador |
| 4 | GND |

115200 8N1. Fuente: foro de OpenWrt (compruébalo con un polímetro). Un cable flojo es la causa nº 1 de "UART muda".

## Paso a paso
```bash
export UART=/dev/cu.wchusbserial10        # Linux: /dev/ttyUSB0
# 0) IP fija en el ordenador (cableado al inyector del U6+)
sudo ifconfig en0 alias 192.168.1.2 255.255.255.0       # macOS

# 1) Genera los archivos (descarga el firmware oficial 6.7.31 y comprueba los CRC)
python3 scripts/make_payload.py out        # esperado: Image 0b76818f / vB.dtb 4e7fbf99
mkdir -p fw && cp out/Image out/vB.dtb fw/

# 2) Servidor TFTP (puerto 69; en macOS funciona sin sudo). Sirve ./fw
python3 scripts/tftpd.py &

# 3) Empieza a escuchar y apaga/enciende el PoE del equipo -> interrumpe u-boot
python3 scripts/uart.py break 150          # debe imprimir PROMPT

# 4) Comprueba QUÉ unidad es y carga los archivos
python3 scripts/uart.py cmd 'printenv ethaddr' 'setenv ipaddr 192.168.1.20' 'setenv serverip 192.168.1.2' \
  'tftpboot 0x48080000 Image'
python3 scripts/uart.py cmd 'tftpboot 0x4c000000 vB.dtb' \
  'crc32 0x48080000 0x2e87808' 'crc32 0x4c000000 0x4378'   # 0b76818f y 4e7fbf99

# 5) Escribe en bloques de 512 KB (NUNCA en una sola escritura)
python3 scripts/uart.py write 0x48080000 0x300000 95293
python3 scripts/uart.py write 0x4c000000 0x320000 34

# 6) Lee de vuelta y verifica (primero la Image, sola; luego el DTB en otra dirección)
python3 scripts/uart.py cmd 'mmc read 0x4a000000 0x300000 0x1743d' 'crc32 0x4a000000 0x2e87808'
python3 scripts/uart.py cmd 'tftpboot 0x4c000000 vB.dtb' 'mmc read 0x4d000000 0x320000 0x22' 'crc32 0x4d000000 0x4378'

# 7) Configura el arranque en la flash SPI y COMPRUEBA cada salida
python3 scripts/uart.py cmd \
  "setenv ubntfix 'mmc dev 0; mmc read 0x48080000 0x300000 0x1743d; mmc read 0x4c000000 0x320000 0x22; booti 0x48080000 - 0x4c000000'" \
  "setenv bootcmd_real 'run ubntfix; bootubnt'" \
  'printenv ubntfix bootcmd_real' 'saveenv' 'printenv bootcmd_real'

# 8) Reinicia y deja que arranque solo
python3 scripts/uart.py cmd 'reset'
```
Después (SSH `ubnt`/`ubnt` en `192.168.1.20`): `cat /etc/version` → `BZ.6.7.31`; `grep -c mmcblk0p /proc/partitions` → `10`; `dmesg | grep -c "I/O error"` → `0`.
Prueba de persistencia: `echo x > /etc/persistent/t; cfgmtd -w -p /etc/; sync; reboot` y comprobar que `t` sigue ahí.

## Trampas (todas ocurrieron)
1. **El primer comando después de `Esc Esc` se pierde** ("Unknown command"). Así fue como un `setenv bootcmd_real` nunca llegó a guardarse. `uart.py cmd/write` ya envía antes un `version` desechable. **Verifica siempre con `printenv`.**
2. **Un Enter vacío repite el último comando** de u-boot (volvió a descargar `tftpboot Image` en vez del DTB).
3. **`urescue` NO funciona**: intenta escribir el kernel (24139 bloques, ~12 MB) de una sola vez y u-boot da `Synchronous Abort`. Reproducido en las dos unidades. Además borra `cfg` y deja `kernel0` inconsistente. Por eso escribimos en bloques de 1024.
4. **No leas cientos de MB a la RAM en u-boot** (un `mmc read` de 128 MB sobrescribió el propio u-boot → "Could not initialize timer"). Las lecturas de verificación no deben solaparse con lo que aún necesitas.
5. **Comprueba la MAC** (`printenv ethaddr`) antes de escribir; con dos unidades es fácil confundirse. Dos unidades encendidas a la vez chocan en `192.168.1.20`.
6. En Linux con la eMMC averiada, `fwupdate`/`syswrapper.sh upgrade2` fallan (`Could not open MTD device /dev/mmcblk0p9`). No insistas por SSH.
7. El cliente `tftp` de macOS no acepta rutas con carpeta; usa el servidor `tftpd.py`.
8. UART muda = casi siempre un mal contacto del cable.

## Limitaciones
- La `Image` contiene el ramdisk: el equipo siempre ejecuta **6.7.31**, aunque el controlador "actualice" el firmware. Para otra versión hay que generar un nuevo payload (cambian los offsets del FIT) y **volver a probar**; yo no lo hice.
- Desactiva las actualizaciones automáticas de firmware en el controlador.
- Con `bootcmd_real` definido, la única forma de volver al arranque original es eliminarlo (abajo).
- No recuperé nada mediante las particiones `u-boot`/BL2; si el problema es un `MSDC: CRC error` ya en BL2 (el equipo ni llega a u-boot), este procedimiento no aplica — consulta el foro de OpenWrt (U6+ unbrick, `mtk_uartboot`).

## Revertir
```bash
python3 scripts/uart.py break && python3 scripts/uart.py cmd 'setenv bootcmd_real' 'saveenv' 'printenv bootcmd_real'
```

## Lo que NO está en este repositorio (a propósito)
- Firmware/kernel de Ubiquiti (lo genera `make_payload.py`).
- Copias de seguridad de los equipos (EEPROM, `factory`, env de la SPI): son propias de cada unidad. **Haz la tuya** antes de escribir nada (`dd if=/dev/mmcblk0pN`, con el arranque corregido, por SSH).
