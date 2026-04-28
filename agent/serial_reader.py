import threading
import time
import serial
import serial.tools.list_ports

# ESP32-S3 CDC 设备的常见识别特征
_ESP32_HINTS = ["ESP32", "CP210", "CH340", "CH9102", "USB Serial", "UART"]


def find_esp32_port() -> str | None:
    for p in serial.tools.list_ports.comports():
    	desc = (p.description or "") + (p.manufacturer or "")
    	if any(hint.lower() in desc.lower() for hint in _ESP32_HINTS):
    		return p.device
    return None


class SerialReader:
    """
    持续读取串口，解析 TEXT:/CMD: 协议，通过回调通知上层。

    协议格式（每行一条）：
      TEXT:<文字内容>   → 打字输出
      CMD:<指令名称>    → 触发快捷键
    """

    def __init__(self, on_text, on_cmd, port: str | None = None, baudrate: int = 115200):
        self.on_text = on_text
        self.on_cmd = on_cmd
        self.port = port
        self.baudrate = baudrate
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop_event.set()

    def _run(self):
        while not self._stop_event.is_set():
            port = self.port or find_esp32_port()
            if not port:
                print("[serial] 未找到设备，2秒后重试...")
                time.sleep(2)
                continue

            print(f"[serial] 已连接: {port}")
            try:
                with serial.Serial(port, self.baudrate, timeout=1) as ser:
                    while not self._stop_event.is_set():
                        raw = ser.readline()
                        if not raw:
                            continue
                        line = raw.decode("utf-8", errors="ignore").strip()
                        self._dispatch(line)
            except serial.SerialException as e:
                print(f"[serial] 连接断开: {e}，2秒后重连...")
                time.sleep(2)

    def _dispatch(self, line: str):
        if not line:
            return
        if line.startswith("TEXT:"):
            self.on_text(line[5:])
        elif line.startswith("CMD:"):
            self.on_cmd(line[4:])
        else:
            print(f"[serial] 未知消息: {line}")
