"""
ESP32-C3 双电机 PID 速度控制测试
用法: python test_pid.py [/dev/cu.usbmodemXXXX]
"""

import serial, time, struct, sys, threading

PORT    = sys.argv[1] if len(sys.argv) > 1 else "/dev/cu.usbmodem1201"
BAUD    = 115200

# 命令字
INIT, CONFIG, SET_SPEEDS, STOP, GET_RPM, GET_STATUS = 0x01, 0x02, 0x13, 0x11, 0x20, 0x21
SET_PID, GET_PID, AUTO_TUNE = 0x14, 0x15, 0x16
ACK, NACK, RPM_DATA, STATUS, PID_DATA = 0x80, 0x81, 0x90, 0x91, 0x92

# 颜色
G, R, B, Y, C, X = "\033[92m", "\033[91m", "\033[94m", "\033[93m", "\033[96m", "\033[0m"

ser_lock = threading.Lock()


def frame(cmd, payload=b""):
    chk = cmd ^ len(payload)
    for b in payload: chk ^= b
    return bytes([0xAA, 0x55, cmd, len(payload)]) + payload + bytes([chk])


def send(ser, cmd, payload=b""):
    with ser_lock:
        ser.write(frame(cmd, payload))


def recv(ser, timeout=1.0):
    dl = time.time() + timeout
    while time.time() < dl:
        if ser.read(1) == b'\xaa' and ser.read(1) == b'\x55':
            hdr = ser.read(2)
            if len(hdr) < 2: return None
            cmd, ln = hdr[0], hdr[1]
            data = ser.read(ln) if ln > 0 else b""
            if len(data) < ln or not ser.read(1): return None
            return {"cmd": cmd, "data": data}
    return None


def ack(ser, t=1.0):
    dl = time.time() + t
    while time.time() < dl:
        f = recv(ser)
        if f and f["cmd"] == ACK: return True
        if f and f["cmd"] == NACK: print(f"{R}NACK 0x{f['data'][1]:02x}{X}"); return False
    return False


def init(ser):
    send(ser, INIT)
    return ack(ser)


def config(ser, ppr=4680, freq=20000):
    send(ser, CONFIG, struct.pack(">HH", ppr, freq))
    return ack(ser)


def set_spd(ser, s1, s2):
    """s1,s2: -100~100"""
    send(ser, SET_SPEEDS, struct.pack(">hh", s1, s2))
    return ack(ser, 0.3)


def stop(ser):
    send(ser, STOP, b'\x02')
    return ack(ser, 0.3)


def get_rpm(ser):
    send(ser, GET_RPM, b'\x02')
    dl = time.time() + 1
    r = {}
    while time.time() < dl and len(r) < 2:
        f = recv(ser)
        if f and f["cmd"] == RPM_DATA:
            r[f["data"][0]] = struct.unpack(">h", f["data"][1:3])[0]
    return r.get(0, 0), r.get(1, 0)


def get_pid(ser, mid=0):
    send(ser, GET_PID, bytes([mid]))
    f = recv(ser)
    if f and f["cmd"] == PID_DATA:
        d = f["data"]
        return struct.unpack(">h", d[0:2])[0]/100, struct.unpack(">h", d[2:4])[0]/100, struct.unpack(">h", d[4:6])[0]/100
    return None


def set_pid(ser, kp, ki, kd):
    for mid in [0, 1]:
        pi = [(int(v * 100), v) for v in (kp, ki, kd)]
        for _, v in pi:
            if v < 0 or v > 327: return False
        send(ser, SET_PID, bytes([mid]) + struct.pack(">hhh", pi[0][0], pi[1][0], pi[2][0]))
        if not ack(ser, 0.3): return False
    return True


def tune(ser, mid, target_rpm):
    send(ser, AUTO_TUNE, bytes([mid]) + struct.pack(">H", target_rpm))
    if not ack(ser, 0.5): return None
    dl = time.time() + 20
    while time.time() < dl:
        f = recv(ser)
        if f and f["cmd"] == 0x93:
            d = f["data"]
            kp = struct.unpack(">h", d[1:3])[0]/100
            ki = struct.unpack(">h", d[3:5])[0]/100
            kd = struct.unpack(">h", d[5:7])[0]/100
            return {"kp": kp, "ki": ki, "kd": kd}
        time.sleep(0.1)
    return None


# ── 主程序 ──
def main():
    print(f"\n{B}ESP32 双电机 PID 测试{X}  {PORT}\n"
          f"  {G}s <pct>{X}   设速度 (0~100%)  例: s 50\n"
          f"  {G}-<pct>{X}        反转        例: -30\n"
          f"  {G}r{X}             读 RPM\n"
          f"  {G}pid [kp ki kd]{X} 查看/设置 PID  例: pid 5 0.2 1\n"
          f"  {G}tune [rpm]{X}     自动整定两电机  例: tune 75\n"
          f"  {G}mon{X}           切换监控模式\n"
          f"  {G}stop / q{X}      停止 / 退出\n")

    try:
        ser = serial.Serial(PORT, BAUD, timeout=0.3)
        time.sleep(0.3)
        print(f"{G}[串口]{X} {PORT}")
    except Exception as e:
        print(f"{R}串口错误: {e}{X}"); return

    if not init(ser): print(f"{R}INIT 失败{X}"); return
    if not config(ser): print(f"{R}CONFIG 失败{X}"); return

    # 默认 PID
    set_pid(ser, 0.8, 0.005, 0.01)
    print(f"{G}[就绪]{X} PID: Kp=0.8 Ki=0.005 Kd=0.01")

    spd = 0
    mon = False

    def monitor():
        while mon:
            r0, r1 = get_rpm(ser)
            tgt = int(abs(spd) * 150 / 100)
            print(f"\r{C}[监控]{X} 目标:{spd:4d}%({tgt:4d}RPM) | M0:{r0:+4d} M1:{r1:+4d} RPM  ", end="")
            sys.stdout.flush()
            time.sleep(0.4)

    while True:
        try:
            line = input(f"\r{C}[监控中]{X}> " if mon else "> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line: continue

        parts = line.split()
        c = parts[0].lower()

        try:
            if c == 'q': break
            elif c == 'stop':
                stop(ser); spd = 0; print(f"{Y}停止{X}")

            elif c == 'r':
                r0, r1 = get_rpm(ser)
                print(f"  M0: {r0:+4d} RPM  |  M1: {r1:+4d} RPM")

            elif c == 's' or (c.startswith('-') and len(c) > 1 and c[1:].isdigit()) or c.isdigit():
                if c == 's':
                    spd = max(-100, min(100, int(parts[1])))
                elif c.startswith('-'):
                    spd = -int(c[1:])
                else:
                    spd = int(c)
                spd = max(-100, min(100, spd))
                tgt = int(abs(spd) * 150 / 100)
                set_spd(ser, spd, spd)
                print(f"{G}速度{X} → {spd}% ({tgt} RPM)")

            elif c == 'pid':
                if len(parts) >= 4:
                    kp, ki, kd = float(parts[1]), float(parts[2]), float(parts[3])
                    if set_pid(ser, kp, ki, kd):
                        print(f"{G}PID 已更新{X} Kp={kp:.2f} Ki={ki:.2f} Kd={kd:.2f}")
                    else:
                        print(f"{R}PID 设置失败{X}")
                else:
                    for m in [0, 1]:
                        p = get_pid(ser, m)
                        if p: print(f"  M{m}: Kp={p[0]:.2f} Ki={p[1]:.2f} Kd={p[2]:.2f}")

            elif c == 'tune':
                tgt = int(parts[1]) if len(parts) > 1 else 75
                for m in [0, 1]:
                    print(f"{Y}整定 M{m} 目标={tgt}RPM...{X}")
                    r = tune(ser, m, tgt)
                    if r:
                        print(f"  M{m} {G}OK{X} Kp={r['kp']:.2f} Ki={r['ki']:.2f} Kd={r['kd']:.2f}")
                    else:
                        print(f"  M{m} {R}超时{X}")
                # 同步两电机 PID 参数
                p0 = get_pid(ser, 0)
                if p0:
                    set_pid(ser, p0[0], p0[1], p0[2])

            elif c == 'mon':
                mon = not mon
                if mon:
                    t = threading.Thread(target=monitor, daemon=True)
                    t.start()
                    print(f"{G}监控 ON{X}")
                else:
                    print(f"{Y}监控 OFF{X}")

            elif c == 'test':
                mid = int(parts[1]) if len(parts) > 1 else 0
                pwm = int(parts[2]) if len(parts) > 2 else 150
                print(f"{Y}RAW PWM 测试: 电机{mid} forward PWM={pwm}...{X}")
                send(ser, 0x31, bytes([mid, 0, pwm]))
                f = recv(ser, 2)
                if f and f["cmd"] == 0x31:
                    d = f["data"]
                    enc1 = struct.unpack(">i", d[2:6])[0]
                    enc2 = struct.unpack(">i", d[6:10])[0]
                    rpm1 = struct.unpack(">h", d[10:12])[0]
                    print(f"  编码器 M0: {enc1:+6d} 脉冲  |  编码器 M1: {enc2:+6d} 脉冲")
                    print(f"  RPM   M0: {rpm1:+4d} (未取反)")
                else:
                    print(f"{R}超时{X}")

            elif c == 'h':
                print(f"  s <pct> | <pct> | -<pct> | r | pid | pid kp ki kd | tune | test <m> <pwm> | mon | stop | q")

            else:
                print(f"{R}? {c}{X}")

        except Exception as e:
            print(f"{R}{e}{X}")

    mon = False
    stop(ser)
    ser.close()
    print(f"{B}退出{X}")


if __name__ == "__main__":
    main()
