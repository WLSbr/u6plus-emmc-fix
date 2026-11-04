# UniFi U6+ — eMMC que perde a configuração a cada reinício

**Idiomas / Languages / Idiomas:** [English](README.md) · **Português** · [Español](README.es.md)


> **Aviso — use por sua conta e risco.** Este procedimento grava na eMMC e na flash SPI de um equipamento e foi testado
> em apenas 2 unidades de U6+. Um erro (aparelho trocado, gravação interrompida, fio errado na UART, 5 V no lugar de 3,3 V)
> pode deixar o aparelho sem boot. Faça backup antes, confira cada saída e não use em equipamento em produção sem plano de
> reposição. Projeto independente: **não é afiliado nem endossado pela Ubiquiti**. Nenhum firmware da Ubiquiti é
> distribuído aqui; o `make_payload.py` baixa o arquivo do servidor oficial. Veja também o `LICENSE`.


Procedimento testado em **2 aparelhos U6+ (UAPL6, MT7981, eMMC `MK2704` 3,5 GB)**, ambos defeituosos depois de atualizar para o firmware 6.7.54.
Resultado: os dois passaram a iniciar sozinhos, enxergam as 10 partições da eMMC, **0 erros de I/O**, e a configuração (`/etc/persistent`) sobrevive a reinícios.

## Sintomas
- Perde a adoção e a configuração toda vez que desliga; volta ao padrão (`ubnt/ubnt`, `192.168.1.20`).
- `dmesg` no Linux:
  ```
  mmc0: switch to bus width 8 failed
  mmc0: switch to bus width 4 failed
  blk_update_request: I/O error, dev mmcblk0, sector 0 ...
  ```
- `cat /proc/partitions` mostra só `mmcblk0`, sem `mmcblk0p1..p10`.
- Às vezes: loop de boot com `Kernel panic` em `mt7981_wifi`, ou `fwupdate` com `Invalid Image Layout!`.
- Downgrade **não** resolve (testado na 6.7.31).

## Causa
O **Linux** inicializa a eMMC a **52 MHz** (`max-frequency = 52000000` no DTB) sem configuração de força de sinal, e essa eMMC não aguenta. O **u-boot** usa um modo mais lento e lê tudo sem erro. Ou seja, não é chip morto.

Correção: no DTB, `max-frequency = <26000000>` + `drive-strength = <8>` nos pinos da eMMC.
(Testado: só 8 mA **não** resolve; 8 mA + 26 MHz resolve. Não testei só 26 MHz.)

## Por que não basta alterar o firmware
A imagem FIT do kernel tem **assinatura RSA obrigatória** (`sha1,rsa2048:uap6_mt7981 (required)`); qualquer DTB alterado dentro dela é recusado. Então o boot é feito a partir do u-boot, **sem** verificação de assinatura:

- O autoboot desse u-boot (`bootdelay_process`) faz `env_get("bootcmd_real")` e, se não existir, roda `"bootubnt"`. **`bootcmd` e `preboot` são ignorados.**
- Gravamos o `Image` (kernel já descomprimido, com o ramdisk embutido) e o DTB corrigido numa **área livre da eMMC fora da GPT**, e `bootcmd_real = run ubntfix; bootubnt` (se algo falhar, cai no boot original).
- **Não é preciso alterar a partição `u-boot` (FIP)**; ela não foi tocada.

Layout usado (blocos de 512 B):

| Item | LBA | Blocos |
|---|---|---|
| `Image` (48 789 512 B) | `0x300000` | `0x1743d` (95293) |
| `vB.dtb` (17 272 B) | `0x320000` | `0x22` (34) |

A GPT termina em `0x185483` e o disco tem 7 405 568 blocos, então essa área não é de nenhuma partição.

## Material necessário
- Adaptador USB-serial **3,3 V** (CH340 serviu). No macOS o driver da WCH precisa de aprovação em *Ajustes → Privacidade e Segurança*.
- Cabo de rede do computador direto no injetor PoE do U6+ (o u-boot só fala em `192.168.1.20`).
- Soldar (ou prender bem) 3 fios nos pads de UART.
- `python3`, `curl`, `dtc` (`brew install dtc`).

### UART (4 pads na borda da placa, marcados UART)
| Pad | Função |
|---|---|
| 1 (quadrado) | VCC 3,3 V — **não ligar** |
| 2 | RX do aparelho → TX do adaptador |
| 3 | TX do aparelho → RX do adaptador |
| 4 | GND |

115200 8N1. Fonte: fórum OpenWrt (confira com multímetro). Contato frouxo é a causa nº 1 de "UART muda".

## Passo a passo
```bash
export UART=/dev/cu.wchusbserial10        # Linux: /dev/ttyUSB0
# 0) IP fixo no computador (rede cabeada ligada no injetor do U6+)
sudo ifconfig en0 alias 192.168.1.2 255.255.255.0       # macOS

# 1) Gera os arquivos (baixa o firmware oficial 6.7.31 e confere os CRCs)
python3 scripts/make_payload.py out        # esperado: Image 0b76818f / vB.dtb 4e7fbf99
mkdir -p fw && cp out/Image out/vB.dtb fw/

# 2) Servidor TFTP (porta 69; no macOS funciona sem sudo). Serve a pasta ./fw
python3 scripts/tftpd.py &

# 3) Deixe escutando e ligue o PoE do aparelho -> interrompe o u-boot
python3 scripts/uart.py break 150          # tem que imprimir PROMPT

# 4) Confira QUAL aparelho e carregue os arquivos
python3 scripts/uart.py cmd 'printenv ethaddr' 'setenv ipaddr 192.168.1.20' 'setenv serverip 192.168.1.2' \
  'tftpboot 0x48080000 Image'
python3 scripts/uart.py cmd 'tftpboot 0x4c000000 vB.dtb' \
  'crc32 0x48080000 0x2e87808' 'crc32 0x4c000000 0x4378'   # 0b76818f e 4e7fbf99

# 5) Grava em pedacos de 512 KB (NUNCA em uma escrita so)
python3 scripts/uart.py write 0x48080000 0x300000 95293
python3 scripts/uart.py write 0x4c000000 0x320000 34

# 6) Le de volta e confere (Image primeiro, sozinha; depois o DTB em outro endereco)
python3 scripts/uart.py cmd 'mmc read 0x4a000000 0x300000 0x1743d' 'crc32 0x4a000000 0x2e87808'
python3 scripts/uart.py cmd 'tftpboot 0x4c000000 vB.dtb' 'mmc read 0x4d000000 0x320000 0x22' 'crc32 0x4d000000 0x4378'

# 7) Configura o boot na flash SPI e CONFIRA cada saida
python3 scripts/uart.py cmd \
  "setenv ubntfix 'mmc dev 0; mmc read 0x48080000 0x300000 0x1743d; mmc read 0x4c000000 0x320000 0x22; booti 0x48080000 - 0x4c000000'" \
  "setenv bootcmd_real 'run ubntfix; bootubnt'" \
  'printenv ubntfix bootcmd_real' 'saveenv' 'printenv bootcmd_real'

# 8) Reinicia e deixa subir sozinho
python3 scripts/uart.py cmd 'reset'
```
Depois (SSH `ubnt`/`ubnt` em `192.168.1.20`): `cat /etc/version` → `BZ.6.7.31`; `grep -c mmcblk0p /proc/partitions` → `10`; `dmesg | grep -c "I/O error"` → `0`.
Teste de persistência: `echo x > /etc/persistent/t; cfgmtd -w -p /etc/; sync; reboot` e ver se `t` volta.

## Armadilhas (todas aconteceram)
1. **O primeiro comando depois do `Esc Esc` é engolido** ("Unknown command"). Foi assim que um `setenv bootcmd_real` nunca chegou a ser gravado. `uart.py cmd/write` já manda um `version` antes. **Sempre confira com `printenv`.**
2. **Enter vazio repete o último comando** do u-boot (rebaixava o `tftpboot Image` em vez do DTB).
3. **`urescue` NÃO funciona**: ele tenta gravar o kernel (24139 blocos, ~12 MB) numa escrita só e o u-boot dá `Synchronous Abort`. Reproduzido nos dois aparelhos. Além disso, apaga a `cfg` e deixa o `kernel0` inconsistente. Por isso gravamos em pedaços de 1024 blocos.
4. **Não leia centenas de MB para a RAM no u-boot** (`mmc read` de 128 MB sobrescreveu o próprio u-boot → "Could not initialize timer"). Leituras de conferência não podem se sobrepor ao que você ainda vai usar.
5. **Confira o MAC** (`printenv ethaddr`) antes de gravar; com 2 aparelhos é fácil trocar. Dois aparelhos ligados juntos conflitam em `192.168.1.20`.
6. No Linux com a eMMC quebrada, o `fwupdate`/`syswrapper.sh upgrade2` falham (`Could not open MTD device /dev/mmcblk0p9`). Não adianta insistir por SSH.
7. O cliente `tftp` do macOS não aceita caminho com pasta; use o servidor `tftpd.py`.
8. UART muda = quase sempre contato do fio.

## Limitações
- O `Image` contém o ramdisk: o aparelho sempre roda **6.7.31**, mesmo que o controller "atualize" o firmware. Para outra versão, gere um novo payload (os offsets do FIT mudam) e **retestar**; não testei.
- Desative a atualização automática de firmware no controller.
- Com o `bootcmd_real` definido, a única forma de voltar ao boot oficial é removê-lo (abaixo).
- Não recuperei nada pela partição `u-boot`/BL2; se o problema for `MSDC: CRC error` já no BL2 (aparelho nem chega ao u-boot), este procedimento não se aplica — veja o fórum OpenWrt (U6+ unbrick, `mtk_uartboot`).

## Reverter
```bash
python3 scripts/uart.py break && python3 scripts/uart.py cmd 'setenv bootcmd_real' 'saveenv' 'printenv bootcmd_real'
```

## O que NÃO está no repositório (de propósito)
- Firmware/kernel da Ubiquiti (gerado por `make_payload.py`).
- Backups dos aparelhos (EEPROM, `factory`, env SPI): são específicos de cada unidade. **Faça o seu** antes de gravar qualquer coisa (`dd if=/dev/mmcblk0pN`, com o boot corrigido, via SSH).
