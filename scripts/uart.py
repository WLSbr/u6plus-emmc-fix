#!/usr/bin/env python3
"""UART helper for the U6+ u-boot (115200 8N1). Standard library only.

  uart.py break [seconds]            wait for 'Autobooting' and interrupt with Esc (default 150 s)
  uart.py cmd 'cmd' ['cmd' ..]       send commands to the MT7981# prompt and print the output
  uart.py write RAM LBA BLOCKS       write RAM to eMMC in chunks of 1024 blocks (mmc write)
  uart.py log SECONDS FILE           capture the console to a file

Port: env var UART (default /dev/cu.wchusbserial10; on Linux use /dev/ttyUSB0).
PITFALL: right after 'break' the FIRST command is swallowed ("Unknown command").
That is why 'cmd' and 'write' send a throwaway 'version' first. Never send an empty
Enter: u-boot repeats the previous command (e.g. it would run tftpboot again).
"""
import os, select, sys, termios, time

PORT = os.environ.get("UART", "/dev/cu.wchusbserial10")
fd = os.open(PORT, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
a = termios.tcgetattr(fd)
a[0] = 0; a[1] = 0; a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL; a[3] = 0
a[4] = a[5] = termios.B115200
termios.tcsetattr(fd, termios.TCSANOW, a)

def rd(t, stop=None):
    end, o = time.time() + t, b""
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.1)
        if r:
            try: o += os.read(fd, 8192)
            except BlockingIOError: pass
        if stop and stop in o: break
    return o

def cmd(c, t=4, stop=None):
    os.write(fd, c.encode() + b"\r")
    return rd(t, stop).decode("latin1")

def do_break(secs):
    buf, end = b"", time.time() + secs
    while time.time() < end:
        buf += rd(0.05)
        if b"Autobooting" in buf or buf.rstrip().endswith(b"MT7981#"):
            for _ in range(15): os.write(fd, b"\x1b"); time.sleep(0.03)
            buf += rd(2); break
    ok = b"MT7981#" in buf[-30:]
    print("PROMPT" if ok else "NO PROMPT"); return ok

def do_cmd(cmds):
    cmd("version")
    for c in cmds:
        stop = b"Bytes transferred" if c.startswith("tftpboot") else b"blocks read" if c.startswith("mmc read") else None
        print(">", c); print(cmd(c, 60 if stop else 4, stop).strip())

def do_write(ram, lba, total, ch=1024):
    cmd("version"); done = 0
    while done < total:
        n = min(ch, total - done)
        t = cmd("mmc write 0x%x 0x%x 0x%x" % (ram + done * 512, lba + done, n), 10, b"written")
        if "written: OK" not in t:
            print("FAILED at block", done, t[-200:]); sys.exit(1)
        rd(0.3); done += n
        if (done // ch) % 10 == 0: print("ok", done, "/", total, flush=True)
    print("DONE", total)

if __name__ == "__main__":
    m = sys.argv[1] if len(sys.argv) > 1 else ""
    if m == "break": sys.exit(0 if do_break(int(sys.argv[2]) if len(sys.argv) > 2 else 150) else 1)
    elif m == "cmd": do_cmd(sys.argv[2:])
    elif m == "write": do_write(int(sys.argv[2], 0), int(sys.argv[3], 0), int(sys.argv[4], 0))
    elif m == "log": open(sys.argv[3], "wb").write(rd(float(sys.argv[2])))
    else: print(__doc__)
