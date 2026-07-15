
# ESP32 底盘控制程序 (esp32_base_control)

本项目基于 ESP32-C3（支持 Geekble Mini ESP32-C3 开发板）开发，用于移动机器人底盘的底层核心控制。项目包含完整的 Arduino 源码工程以及面向工厂/团队的高效批量自动烧录工具。

---

## 🛠 场景一：源码开发与环境配置 (开发者适用)

如果你需要修改底层控制逻辑或调试传感器，请使用图形化 IDE 进行开发。

### 1. 环境变量配置 (国内加速)
为避免国内网络环境下下载乐鑫依赖链极易卡死的问题，请在系统环境变量中添加加速源：
- **Windows**: 右键「此电脑」→「属性」→「高级系统设置」→「环境变量」，在用户变量中新建：
  - 变量名：`IDF_GITHUB_ASSETS`
  - 变量值：`dl.espressif.com/github_assets`
- **macOS / Linux**: 在终端配置文件（如 `~/.zshrc` 或 `~/.bash_profile`）中追加：
  ```bash
  export IDF_GITHUB_ASSETS="[dl.espressif.com/github_assets](https://dl.espressif.com/github_assets)"
  ```


### 2. Arduino IDE 配置

1. 打开 Arduino IDE，进入 `Preferences` (偏好设置)。
2. 在 `Additional boards manager URLs` 中填入国内第三方加速索引源：
```text
[https://arduino.me/packages/esp32.json](https://arduino.me/packages/esp32.json)

```

3. 进入 `Boards Manager` (开发板管理器)，搜索 `esp32` 并安装由 **Espressif Systems** 发布的开发板核心库。


### 3. 编译与烧录

1. 用 Arduino IDE 打开工程主文件：`arduino/base_control/base_control.ino`。
2. 在开发板选择中搜索并选中 `Geekble Mini ESP32-C3`。
3. 选择对应的物理 USB 串口（macOS 通常为 `/dev/cu.usbmodemXXXX`，Windows 通常为 `COMX`）。
4. 点击 **Upload (上传)** 开始编译并烧录。

---

## ⚡ 场景二：流水线流水式批量烧录 (生产/量产适用)

当底盘控制程序验证完毕、需要进行多台设备批量固件写入时，**严禁使用 Arduino IDE**。请使用项目内置的自动化量产工具，可实现“插线即烧、拔线即换”的无人值守流水线操作。

### 1. 准备合并固件

在第一次使用 Arduino IDE 成功烧录后，从本地编译缓存中捞出合并好的单体固件 `base_control.ino.merged.bin`，并将其放置到本仓库的 `tools/firmware/` 目录下。

### 2. 安装量产依赖

确保本地安装了 Python 3 环境，在终端执行以下命令安装乐鑫官方烧录核心驱动：

```bash
pip3 install esptool

```

### 3. 启动批量烧录系统

进入工具链目录并启动监听脚本：

```bash
cd tools
python3 batch_burner.py

```

### 4. 流水线实操规程

1. **接入硬件**：使用 USB 数据线将新的底盘主控板接入电脑。
2. **自动闪存**：脚本将自动捕获新端口并以最高稳定波特率（`921600`）执行顺序写入，耗时通常在 5~8 秒。
3. **断开换板**：终端打印出绿色 `[成功]` 提示后，直接拔掉数据线，换下一块板子插入，全程无需触碰键盘鼠标。

