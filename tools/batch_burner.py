#!/usr/bin/env python3
import os
import sys
import time
import glob
import argparse
import subprocess

# 确保脚本即使在后台运行也能实时刷新控制台输出
sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

def parse_arguments():
    """解析命令行参数，让脚本具备高通用性"""
    parser = argparse.ArgumentParser(description="ESP32 批量流水线自动化烧录系统")
    
    # 默认寻找脚本同级或上级目录下的 firmware/base_control.ino.merged.bin
    default_fw = os.path.join(os.path.dirname(os.path.abspath(__file__)), "firmware", "base_control.ino.merged.bin")
    
    parser.add_argument("--fw", type=str, default=default_fw, help="合并后的固件 (.bin) 路径")
    parser.add_argument("--chip", type=str, default="esp32c3", help="目标芯片架构 (如 esp32, esp32c3, esp32s3)")
    parser.add_argument("--baud", type=str, default="921600", help="烧录波特率")

    # 🌟 新增这一行：添加自动质检的布尔开关选项
    parser.add_argument("--test", action="store_true", help="启用该选项后，每块板子烧录完成后自动执行 26 项协议质检")
    
    return parser.parse_args()

def check_env(fw_path, run_test):
    """检查固件及依赖环境"""
    # 1. 检查固件
    if not os.path.exists(fw_path):
        print(f"\033[31m[错误] 找不到固件文件，请检查路径：\n{fw_path}\033[0m")
        print("\033[33m提示：请在脚本同级目录下创建 'firmware' 文件夹，并将已编译合并的固件命名为 'base_control.ino.merged.bin' 放入其中。\033[0m")
        sys.exit(1)
        
    # 2. 检查 esptool 依赖
    try:
        import esptool
    except ModuleNotFoundError:
        print("\033[31m[错误] 当前 Python 环境中未安装 esptool 库！\033[0m")
        print(f"\033[33m请在终端执行以下命令安装后重试：\n    {sys.executable} -m pip install esptool\033[0m")
        sys.exit(1)

    print(f"\033[32m[环境就绪] 固件载入成功: {os.path.basename(fw_path)} ({os.path.getsize(fw_path) / 1024 / 1024:.2f} MB)\033[0m")

    # 依赖检查逻辑
    # 如果用户开启了 `--test` 选项，脚本必须在启动时前置检查 `pyserial` 库以及 `test_uart.py` 脚本是否存在，防止烧录完后因找不到测试依赖而崩溃。
    if run_test:
        try:
            import serial
        except ModuleNotFoundError:
            print("\033[31m[错误] 启用了自动质检，但当前环境未安装 pyserial 库！\033[0m")
            print(f"\033[33m请在终端执行以下命令安装后重试：\n    {sys.executable} -m pip install pyserial\033[0m")
            sys.exit(1)
            
        test_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tests", "test_uart.py"))
        if not os.path.exists(test_script):
            print(f"\033[31m[错误] 找不到测试脚本，请检查路径是否正确：\n{test_script}\033[0m")
            sys.exit(1)
        print("\033[35m[联动激活] 已开启“烧录 + 26项高精度功能质检”一体化流水线模式。\033[0m")


def get_current_ports():
    """动态获取 macOS 和 Linux 下的常用串口设备"""
    patterns = [
        "/dev/cu.usbmodem*", 
        "/dev/cu.usbserial*",
        "/dev/ttyUSB*", 
        "/dev/ttyACM*"
    ]
    ports = []
    for pattern in patterns:
        ports.extend(glob.glob(pattern))
    return set(ports)


# 用于在烧录成功后，使用当前 Python 解释器隐式调用test_uart.py 并实时透传 26 项彩色测试日志。
def run_auto_test(port):
    """🌟 新增函数：调用项目的核心质检脚本进行功能核验"""
    print(f"\n\033[35m[正在质检] 正在对端口 {port} 发起 26 项高精度协议全自动质检...\033[0m")
    
    # 动态定位到 tests/test_uart.py 的绝对路径
    test_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tests", "test_uart.py"))
    
    # 组合底层命令：python3 tests/test_uart.py /dev/cu.usbmodemXXXX
    cmd = [sys.executable, test_script, port]
    
    try:
        # 实时透传标准输出与标准错误，使 26 项全绿的瀑布流直接打在当前终端上
        result = subprocess.run(cmd, stdout=sys.stdout, stderr=sys.stderr, text=True)
        return result.returncode == 0
    except Exception as e:
        print(f"\033[31m[质检异常] 执行自动质检时发生进程错误: {e}\033[0m")
        return False


def burn_firmware(port, args):
    """调用当前环境的 esptool 模块执行单次写入"""
    print(f"\n\033[34m[开始烧录] 正在向端口发送固件: {port} ...\033[0m")
    
    # 使用 sys.executable 锁定当前 Python 解释器，使用精确的硬件参数替代 "keep" 以防固件损坏
    cmd = [
        #"python3", "-m", "esptool",
        sys.executable, "-m", "esptool",
        "--chip", args.chip,
        "--port", port,
        "--baud", args.baud,
        "--before", "default-reset",
        "--after", "hard-reset",
        "write-flash",
        "-z",
        "--flash_mode", "dio",
        "--flash_freq", "80m",
        "--flash_size", "4MB",
        "0x0", args.fw
    ]
    
    start_time = time.time()
    try:
        # 执行烧录并实时透传日志到终端
        result = subprocess.run(cmd, stdout=sys.stdout, stderr=sys.stderr, text=True)
        if result.returncode == 0:
            elapsed = time.time() - start_time
            #print(f"\033[32m[成功] ====== 烧录耗时 {elapsed:.1f} 秒。请拔掉当前板子，换下一块 ====== \033[0m")
            print(f"\033[32m[成功] 固件部署完毕，耗时 {elapsed:.1f} 秒。\033[0m")
            
            # 🌟 新增质检联动逻辑
            if args.test:
                time.sleep(1.0)  # 给予芯片足够的冷启动和 USB 重新握手时间
                run_auto_test(port)
                
            print(f"\n\033[32m====== 流程结束。请拔掉当前板子，换下一块 ====== \033[0m")

            return True
        else:
            print("\033[31m[失败] ====== esptool 写入中断，请检查线材供电或重新插拔 ====== \033[0m")
            return False
    except Exception as e:
        print(f"\033[31m[异常] 进程通信失败: {e}\033[0m")
        return False

def main():
    args = parse_arguments()
    
    print("====================================================")
    print("       ESP32 跨平台底盘控制程序流水线烧录系统")
    print("====================================================")
    
    check_env(args.fw, args.test)
    
    # 记录脚本启动时已经插在电脑上的设备，防止误烧录
    last_ports = get_current_ports()
    print("\n[循环监听中] 请插入新的 ESP32 底盘主控板...")
    
    while True:
        time.sleep(0.3)
        current_ports = get_current_ports()
        
        # 捕获新插入的端口
        new_ports = current_ports - last_ports
        
        if new_ports:
            active_port = list(new_ports)[0]
            print(f"\n\033[33m[检测到新硬件] 端口分配: {active_port}\033[0m")
            time.sleep(0.6)  # 给予硬件上电并稳定 USB 握手的时间
            
            # 执行自动化烧录
            burn_firmware(active_port, args)
            
            print("\n[等待断开] 请拔出当前已烧录完毕的设备...")
            # 阻塞，直到用户安全拔出设备
            while True:
                time.sleep(0.3)
                if active_port not in get_current_ports():
                    print("[状态复位] 设备已安全拔出。")
                    break
            
            # 重新捕获当前基准端口状态
            last_ports = get_current_ports()
            print("\n[继续监听] 请插入下一块新板子...")
        else:
            # 如果中途有人拔掉了原本就插着的无效线，实时同步状态
            last_ports = current_ports

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\033[33m[提示] 批量烧录程序已安全退出。\033[0m")
        sys.exit(0)
