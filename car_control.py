"""
ESP32-C3 遥控车 - QQ飞车模式
W/↑: 加速(按住)  S/↓: 刹车  A/← D/→: 转向
SHIFT: 漂移  空格: 急停  Q: 退出
"""

import ctypes
import os
import serial
import struct
import time
import sys

# ── Windows ANSI 支持 ─────────────────────────────────
if os.name == 'nt':
    _h = ctypes.windll.kernel32.GetStdHandle(-11)
    _m = ctypes.c_ulong()
    ctypes.windll.kernel32.GetConsoleMode(_h, ctypes.byref(_m))
    ctypes.windll.kernel32.SetConsoleMode(_h, _m.value | 0x0004)

# ── 配置 ──────────────────────────────────────────────
PORT     = "COM10"
BAUD     = 115200
PPR      = 4680
PWM_FREQ = 20000
DEAD_ZONE = 160

# ── 物理参数 ──────────────────────────────────────────
MAX_SPEED    = 255    # 最高速度
ACCEL        = 160    # 加速度 (每秒)
BRAKE_DECEL  = 350    # 刹车减速度 (每秒)
COAST_DECAY  = 0.94   # 松油门后每帧衰减 (30fps 基准)
REVERSE_MAX  = 100    # 倒车最高速
STEER_SPEED  = 3.5    # 转向响应速度
STEER_RETURN = 0.85   # 转向回正速度
TURN_FACTOR  = 90     # 最大内外轮速度差
DRIFT_TURN   = 2.5    # 漂移时转向倍率
DRIFT_BOOST_MAX = 70  # 漂移加速最大值
MIN_SPEED    = 2      # 低于此值归零
RPM_INTERVAL = 0.3

# ── 虚拟键码 ──────────────────────────────────────────
VK_W = 0x57; VK_S = 0x53; VK_A = 0x41; VK_D = 0x44
VK_UP = 0x26; VK_DOWN = 0x28; VK_LEFT = 0x25; VK_RIGHT = 0x27
VK_SHIFT = 0x10; VK_SPACE = 0x20; VK_Q = 0x51

# ── 协议 ──────────────────────────────────────────────
CMD_INIT = 0x01; CMD_CONFIG = 0x02; CMD_SET_SPEED = 0x10
CMD_STOP = 0x11; CMD_GET_RPM = 0x20; CMD_RESET = 0xFF
RSP_RPM_DATA = 0x90

DISPLAY_LINES = 16


def key_down(vk):
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


def build_frame(cmd, payload=b""):
    length = len(payload)
    chk = cmd ^ length
    for b in payload:
        chk ^= b
    return bytes([0xAA, 0x55, cmd, length]) + payload + bytes([chk])


def recv_frame(ser, timeout=0.5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        b = ser.read(1)
        if not b:
            continue
        if b[0] == 0xAA:
            b2 = ser.read(1)
            if b2 and b2[0] == 0x55:
                break
    else:
        return None
    header = ser.read(2)
    if len(header) < 2:
        return None
    cmd, length = header[0], header[1]
    payload = ser.read(length) if length else b""
    chk_b = ser.read(1)
    if not chk_b:
        return None
    chk = cmd ^ length
    for b in payload:
        chk ^= b
    if chk != chk_b[0]:
        return None
    return {"cmd": cmd, "payload": bytes(payload)}


def send_cmd(ser, cmd, payload=b"", timeout=0.2):
    ser.reset_input_buffer()
    ser.write(build_frame(cmd, payload))
    return recv_frame(ser, timeout)


def _map_pwm(speed):
    if speed == 0:
        return 0
    sign = 1 if speed > 0 else -1
    return sign * int(DEAD_ZONE + abs(speed) * (255 - DEAD_ZONE) / 255)


class CarController:
    def __init__(self, port):
        self.ser = serial.Serial(port, BAUD, timeout=0.1)
        time.sleep(0.5)
        self.ser.reset_input_buffer()

        self.speed = 0.0
        self.steer = 0.0
        self.drifting = False
        self.drift_time = 0.0
        self.boost = 0.0
        self.rpm1 = 0
        self.rpm2 = 0
        self.disp_left = 0
        self.disp_right = 0
        self.running = True
        self._displayed = False
        self._last_pwm = (None, None)

        send_cmd(self.ser, CMD_INIT)
        send_cmd(self.ser, CMD_CONFIG, struct.pack(">HH", PPR, PWM_FREQ))
        time.sleep(0.2)

    def update(self, dt):
        fwd   = key_down(VK_W) or key_down(VK_UP)
        bwd   = key_down(VK_S) or key_down(VK_DOWN)
        left  = key_down(VK_A) or key_down(VK_LEFT)
        right = key_down(VK_D) or key_down(VK_RIGHT)
        shift = key_down(VK_SHIFT)
        space = key_down(VK_SPACE)

        if key_down(VK_Q):
            self.running = False
            return

        # ── 速度 ──────────────────────────────────────
        if fwd:
            self.speed = min(MAX_SPEED + self.boost, self.speed + ACCEL * dt)
        elif bwd:
            self.speed -= BRAKE_DECEL * dt
        else:
            self.speed *= COAST_DECAY ** (dt * 30)

        if space:
            self.speed *= 0.82 ** (dt * 30)

        self.speed = max(-REVERSE_MAX, min(MAX_SPEED + self.boost, self.speed))
        if abs(self.speed) < MIN_SPEED and not fwd and not bwd:
            self.speed = 0

        # ── 转向 ──────────────────────────────────────
        if left:
            self.steer = max(-1.0, self.steer - STEER_SPEED * dt)
        elif right:
            self.steer = min(1.0, self.steer + STEER_SPEED * dt)
        else:
            self.steer *= STEER_RETURN ** (dt * 30)
            if abs(self.steer) < 0.05:
                self.steer = 0

        # ── 漂移 ──────────────────────────────────────
        was_drift = self.drifting
        self.drifting = shift and abs(self.steer) > 0.15 and abs(self.speed) > 15

        if self.drifting:
            self.drift_time += dt
        elif was_drift and self.drift_time > 0:
            self.boost = min(DRIFT_BOOST_MAX, self.drift_time * 45)
            self.drift_time = 0

        if self.boost > 0:
            self.boost *= 0.90 ** (dt * 30)
            if self.boost < 1:
                self.boost = 0

        # ── 计算轮速 ─────────────────────────────────
        turn = self.steer * TURN_FACTOR * (DRIFT_TURN if self.drifting else 1.0)
        l = max(-MAX_SPEED, min(MAX_SPEED, self.speed + turn))
        r = max(-MAX_SPEED, min(MAX_SPEED, self.speed - turn))

        self.disp_left = int(l)
        self.disp_right = int(r)

        # 左轮物理反向
        lp = -_map_pwm(int(l))
        rp = _map_pwm(int(r))
        self._send(lp, rp)

    def _send(self, lp, rp):
        if (lp, rp) == self._last_pwm:
            return
        self._last_pwm = (lp, rp)
        if lp == 0 and rp == 0:
            send_cmd(self.ser, CMD_STOP, bytes([0]))
            send_cmd(self.ser, CMD_STOP, bytes([1]))
        else:
            send_cmd(self.ser, CMD_SET_SPEED, struct.pack(">Bh", 0, lp), 0.1)
            send_cmd(self.ser, CMD_SET_SPEED, struct.pack(">Bh", 1, rp), 0.1)

    def query_rpm(self):
        r = send_cmd(self.ser, CMD_GET_RPM, bytes([0]), 0.1)
        if r and r["cmd"] == RSP_RPM_DATA and len(r["payload"]) >= 3:
            self.rpm1 = -struct.unpack(">h", r["payload"][1:3])[0]
        r = send_cmd(self.ser, CMD_GET_RPM, bytes([1]), 0.1)
        if r and r["cmd"] == RSP_RPM_DATA and len(r["payload"]) >= 3:
            self.rpm2 = struct.unpack(">h", r["payload"][1:3])[0]

    def display(self):
        if self._displayed:
            sys.stdout.write(f'\033[{DISPLAY_LINES}A')
        self._displayed = True

        spd = int(self.speed)
        cap = MAX_SPEED + int(self.boost)
        ratio = min(1.0, abs(spd) / max(cap, 1))
        filled = int(ratio * 24)
        gauge = '#' * filled + '-' * (24 - filled)

        # 转向指示
        if self.steer < -0.1:
            arrows = '<' * min(5, int(abs(self.steer) * 5) + 1)
            steer_s = arrows.ljust(10)
        elif self.steer > 0.1:
            arrows = '>' * min(5, int(abs(self.steer) * 5) + 1)
            steer_s = arrows.rjust(10)
        else:
            steer_s = '     |     '

        # 状态
        tag = ""
        if self.drifting:
            tag = " << DRIFT >>"
        elif self.boost > 5:
            tag = " ** BOOST **"

        direction = "FWD" if spd > 0 else "REV" if spd < 0 else "---"

        lines = [
            "=" * 50,
            "    ESP32-C3  << QQ飞车模式 >>",
            "=" * 50,
            "",
            f"  {direction}  {spd:>4d}/{cap:<4d} [{gauge}]{tag}",
            f"  STEER  {steer_s}",
            "",
            f"  L wheel: {self.disp_left:>+4d}  RPM:{self.rpm1:>+4d}",
            f"  R wheel: {self.disp_right:>+4d}  RPM:{self.rpm2:>+4d}",
            "",
            "-" * 50,
            "  W/Up    Accelerate    S/Down  Brake",
            "  A/Left  Turn Left     D/Right Turn Right",
            "  SHIFT   Drift         SPACE   Emergency Stop",
            "  Q       Quit",
            "=" * 50,
        ]
        for line in lines:
            sys.stdout.write('\033[K' + line + '\n')
        sys.stdout.flush()

    def run(self):
        last_rpm = time.time()
        last_t = time.time()

        try:
            while self.running:
                now = time.time()
                dt = min(now - last_t, 0.05)
                last_t = now

                self.update(dt)
                if not self.running:
                    break

                if now - last_rpm >= RPM_INTERVAL:
                    self.query_rpm()
                    last_rpm = now

                self.display()
                time.sleep(0.02)
        except KeyboardInterrupt:
            pass
        finally:
            self._send(0, 0)
            send_cmd(self.ser, CMD_RESET)
            self.ser.close()
            print("\n已断开连接")


if __name__ == "__main__":
    car = CarController(PORT)
    car.run()
