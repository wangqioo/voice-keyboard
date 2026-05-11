"""
Push-to-Talk 录音模块，支持三个热键：
  ptt_key  — 普通听写（dictation），松开后调 on_utterance
  edit_key — 语音编辑（edit），松开后调 on_edit_utterance
  ai_key   — AI 编程指令（ai），松开后调 on_ai_utterance

三个键互斥：一个按下时另两个无效。

dictation 模式支持实时分句：按住说话过程中，检测到句子间停顿即立刻触发 STT，
无需等到松键，适合连续说多句话的场景。
"""

import sys
import threading
import time
from typing import Callable, Optional

import sounddevice as sd
from pynput import keyboard as kb

# ── Windows WH_KEYBOARD_LL 钩子：只拦截 Alt 键，其他全部放行 ──
_ALT_BLOCKER_HOOK = None
_ALT_BLOCKER_MODULE = None
_ALT_BLOCKER_CALLBACK = None  # 防止 GC 回收回调函数

def _install_alt_blocker() -> None:
    global _ALT_BLOCKER_HOOK, _ALT_BLOCKER_MODULE, _ALT_BLOCKER_CALLBACK
    import atexit
    import ctypes
    from ctypes import wintypes

    WINFUNCTYPE = ctypes.WINFUNCTYPE
    LowLevelKeyboardProc = WINFUNCTYPE(wintypes.LPARAM, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
    user32 = ctypes.windll.user32

    @LowLevelKeyboardProc
    def _hook_callback(nCode: int, wParam: int, lParam: int) -> int:
        if nCode >= 0 and wParam in (0x0100, 0x0101, 0x0104, 0x0105):
            vk_code = ctypes.cast(lParam, ctypes.POINTER(ctypes.c_uint32))[0] & 0xFF
            if vk_code in (0x12, 0xA4, 0xA5):  # VK_MENU, VK_LMENU, VK_RMENU
                return 1
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    _ALT_BLOCKER_CALLBACK = _hook_callback
    _ALT_BLOCKER_MODULE = ctypes.WinDLL("kernel32").GetModuleHandleW(None)
    _ALT_BLOCKER_HOOK = user32.SetWindowsHookExW(13, _hook_callback, _ALT_BLOCKER_MODULE, 0)
    if not _ALT_BLOCKER_HOOK:
        print("[ptt] [WARN] 安装 Alt 拦截钩子失败，热键可能与其他应用冲突")
    else:
        print("[ptt] Alt 拦截钩子已安装，微信/浏览器不会收到 Alt 键")
    atexit.register(_uninstall_alt_blocker)

def _uninstall_alt_blocker() -> None:
    global _ALT_BLOCKER_HOOK
    if _ALT_BLOCKER_HOOK:
        import ctypes
        ctypes.windll.user32.UnhookWindowsHookEx(_ALT_BLOCKER_HOOK)
        _ALT_BLOCKER_HOOK = None


# ── Windows 系统音量静音（纯 ctypes，无需 pycaw/comtypes）──────────
# 通过 IMMDeviceEnumerator → IMMDevice → IAudioEndpointVolume COM 接口实现
# 只在 Windows 下生效，其他平台静默跳过

_audio_mute_state: bool = False  # 记录静音前的原始状态，防止误恢复

def _win_set_mute(mute: bool) -> None:
    """设置 Windows 默认音频输出设备的静音状态。"""
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        import ctypes.wintypes

        ole32   = ctypes.windll.ole32
        shell32 = ctypes.windll.shell32

        ole32.CoInitialize(None)

        # CLSID_MMDeviceEnumerator = {BCDE0395-E52F-467C-8E3D-C4579291692E}
        # IID_IMMDeviceEnumerator  = {A95664D2-9614-4F35-A746-DE8DB63617E6}
        # IID_IAudioEndpointVolume = {5CDF2C82-841E-4546-9722-0CF74078229A}
        CLSID_enum = (ctypes.c_byte * 16)(
            0x95, 0x03, 0xDE, 0xBC, 0x2F, 0xE5, 0x7C, 0x46,
            0x8E, 0x3D, 0xC4, 0x57, 0x92, 0x91, 0x69, 0x2E,
        )
        IID_enum = (ctypes.c_byte * 16)(
            0xD2, 0x64, 0x56, 0xA9, 0x14, 0x96, 0x35, 0x4F,
            0xA7, 0x46, 0xDE, 0x8D, 0xB6, 0x36, 0x17, 0xE6,
        )
        IID_vol = (ctypes.c_byte * 16)(
            0x82, 0x2C, 0xDF, 0x5C, 0x1E, 0x84, 0x46, 0x45,
            0x97, 0x22, 0x0C, 0xF7, 0x40, 0x78, 0x22, 0x9A,
        )

        CLSCTX_ALL = 0x17
        eRender = 0
        eConsole = 0

        ole32.CoCreateInstance.restype = ctypes.HRESULT
        pp_enum = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(
            ctypes.byref((ctypes.c_byte * 16)(*CLSID_enum)),
            None, CLSCTX_ALL,
            ctypes.byref((ctypes.c_byte * 16)(*IID_enum)),
            ctypes.byref(pp_enum),
        )
        if hr != 0 or not pp_enum.value:
            return

        # GetDefaultAudioEndpoint(eRender=0, eConsole=0, ppDevice)
        vtbl = ctypes.cast(pp_enum, ctypes.POINTER(ctypes.c_void_p))
        get_default = ctypes.cast(vtbl[0], ctypes.POINTER(ctypes.c_void_p))[4]
        pp_device = ctypes.c_void_p()
        GetDefaultAudioEndpoint = ctypes.WINFUNCTYPE(
            ctypes.HRESULT, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
            ctypes.POINTER(ctypes.c_void_p)
        )(get_default)
        hr = GetDefaultAudioEndpoint(pp_enum.value, eRender, eConsole, ctypes.byref(pp_device))
        if hr != 0 or not pp_device.value:
            return

        # Activate IAudioEndpointVolume
        vtbl2 = ctypes.cast(pp_device, ctypes.POINTER(ctypes.c_void_p))
        activate_fn_ptr = ctypes.cast(vtbl2[0], ctypes.POINTER(ctypes.c_void_p))[3]
        pp_vol = ctypes.c_void_p()
        ActivateFn = ctypes.WINFUNCTYPE(
            ctypes.HRESULT, ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_byte * 16), ctypes.c_uint,
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)
        )(activate_fn_ptr)
        iid_vol_arr = (ctypes.c_byte * 16)(*IID_vol)
        hr = ActivateFn(pp_device.value, ctypes.byref(iid_vol_arr), CLSCTX_ALL, None, ctypes.byref(pp_vol))
        if hr != 0 or not pp_vol.value:
            return

        # SetMute(bMute, pguidEventContext=NULL)  — vtable index 15
        vtbl3 = ctypes.cast(pp_vol, ctypes.POINTER(ctypes.c_void_p))
        set_mute_ptr = ctypes.cast(vtbl3[0], ctypes.POINTER(ctypes.c_void_p))[15]
        SetMute = ctypes.WINFUNCTYPE(
            ctypes.HRESULT, ctypes.c_void_p, ctypes.c_bool, ctypes.c_void_p
        )(set_mute_ptr)
        SetMute(pp_vol.value, mute, None)

        ole32.CoUninitialize()
    except Exception:
        pass


def _mute_output() -> None:
    """录音开始时调用：读取并保存当前静音状态，然后静音。"""
    global _audio_mute_state
    # 直接静音，不判断当前状态（避免 COM 读取复杂度）
    _audio_mute_state = True
    _win_set_mute(True)


def _unmute_output() -> None:
    """录音结束时调用：恢复静音前的状态。"""
    global _audio_mute_state
    if _audio_mute_state:
        _win_set_mute(False)
        _audio_mute_state = False


import agent.typer as _typer
from agent.audio_monitor import find_device, FRAME_BYTES, SILENCE_FRAMES, MIN_SPEECH_FRAMES

SAMPLE_RATE = 16000

try:
    import webrtcvad as _webrtcvad
except ImportError:
    _webrtcvad = None


_ALT_FAMILY  = None
_CTRL_FAMILY = None

def _alt_family():
    global _ALT_FAMILY
    if _ALT_FAMILY is None:
        _ALT_FAMILY = frozenset(filter(None, [
            getattr(kb.Key, 'alt',    None),
            getattr(kb.Key, 'alt_l',  None),
            getattr(kb.Key, 'alt_r',  None),
            getattr(kb.Key, 'alt_gr', None),
        ]))
    return _ALT_FAMILY

def _ctrl_family():
    global _CTRL_FAMILY
    if _CTRL_FAMILY is None:
        _CTRL_FAMILY = frozenset(filter(None, [
            getattr(kb.Key, 'ctrl',   None),
            getattr(kb.Key, 'ctrl_l', None),
            getattr(kb.Key, 'ctrl_r', None),
        ]))
    return _CTRL_FAMILY


def _parse_key(key_str: str):
    try:
        return getattr(kb.Key, key_str)
    except AttributeError:
        return kb.KeyCode.from_char(key_str)

def _key_matches(pressed, target):
    if pressed == target:
        return True
    af = _alt_family()
    if target in af and pressed in af:
        return True
    cf = _ctrl_family()
    if target in cf and pressed in cf:
        return True
    return False


def _parse_keys(key_input) -> list:
    """支持单个字符串或字符串列表，统一返回 pynput key 列表。"""
    if isinstance(key_input, list):
        return [_parse_key(k) for k in key_input]
    return [_parse_key(key_input)]


class PushToTalk:
    # ptt_key 按下后等待此时间才进入听写（防止误触短按）
    _PTT_TAP_GUARD = 0.1
    # 松键后等待此时间确认不是虚假事件再停止录音（Windows 系统键虚假 up/down 对）
    _RELEASE_DEBOUNCE = 0.05

    def __init__(
        self,
        on_utterance:      Callable[[bytes], None],
        on_edit_utterance: Optional[Callable[[bytes], None]] = None,
        on_ai_utterance:   Optional[Callable[[bytes], None]] = None,
        on_ai_key_down:    Optional[Callable[[], None]] = None,
        ptt_key:           str = "right_alt",
        edit_key:          str = "right_ctrl",
        ai_key:            str = "right_shift",
        device:            Optional[str] = "auto",
        status_window=None,
        kbd_monitor=None,
    ):
        self._on_utterance      = on_utterance
        self._on_edit_utterance = on_edit_utterance
        self._on_ai_utterance   = on_ai_utterance
        self._on_ai_key_down    = on_ai_key_down
        self._kbd_monitor       = kbd_monitor
        self._ptt_keys          = _parse_keys(ptt_key)
        self._edit_keys         = _parse_keys(edit_key) if on_edit_utterance else []
        self._ai_keys           = _parse_keys(ai_key)   if on_ai_utterance   else []
        self._device_hint       = device
        self._status            = status_window
        self._device_idx        = None
        self._active_key        = None   # "dictate" / "edit" / "ai" / None
        self._active_trigger    = None   # 触发本次录音的具体按键，用于 release 配对
        self._buf: list[bytes]  = []
        self._stream: Optional[sd.RawInputStream]  = None
        self._listener: Optional[kb.Listener]      = None
        self._chord_timer: Optional[threading.Timer] = None   # 和弦检测计时器
        self._release_timer: Optional[threading.Timer] = None  # 松键防抖计时器

        # 实时分句 VAD 状态（仅 dictate 模式使用）
        self._vad                             = None
        self._vad_raw: bytearray             = bytearray()
        self._vad_speech_frames: list[bytes] = []
        self._vad_in_speech                  = False
        self._vad_silent_count               = 0
        self._vad_sent_count                 = 0

        # 双击 PTT 切换微润色模式
        self._polish_mode             = False
        self._last_ptt_press_time     = 0.0
        self._double_tap_window       = 0.4   # 秒

    def start(self):
        if sys.platform == 'win32':
            _install_alt_blocker()

        self._device_idx = find_device(self._device_hint)
        if self._device_idx is None:
            print("[ptt] 使用系统默认麦克风")
        else:
            info = sd.query_devices(self._device_idx)
            print(f"[ptt] 使用麦克风: {info['name']}")

        if _webrtcvad is not None:
            self._vad = _webrtcvad.Vad(2)
            print("[ptt] 实时分句已启用（说话中停顿可提前输出）")
        else:
            print("[ptt] webrtcvad 未安装，实时分句不可用（pip install webrtcvad）")

        self._listener = kb.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.start()

        hints = [f"{'/'.join(str(k) for k in self._ptt_keys)} 说话（双击切换微润色）"]
        if self._edit_keys:
            hints.append(f"{'/'.join(str(k) for k in self._edit_keys)} 语音编辑")
        if self._ai_keys:
            hints.append(f"{'/'.join(str(k) for k in self._ai_keys)} AI编程")
        print(f"[ptt] 按住 {' | '.join(hints)}")

    def stop(self):
        if self._chord_timer:
            self._chord_timer.cancel()
            self._chord_timer = None
        if self._release_timer:
            self._release_timer.cancel()
            self._release_timer = None
        if self._listener:
            self._listener.stop()
        self._close_stream()

    def _set_status(self, state: str) -> None:
        if self._status is not None:
            self._status.set_state(state)

    # ── 键盘事件 ─────────────────────────────────────────────────

    def _on_press(self, key):
        if _typer.is_simulating():
            return  # 程序自身发出的按键，忽略
        # 顺手把退格/Delete/Enter 同步给 KeyboardMonitor，避免再开一个 CGEventTap
        if self._kbd_monitor is not None:
            try:
                self._kbd_monitor.process_press(key)
            except Exception:
                pass

        # 松键防抖：若对应键重新按下则是 Windows 虚假 up/down，取消挂起的停止
        if self._release_timer is not None:
            ptt_match  = any(_key_matches(key, k) for k in self._ptt_keys)
            edit_match = self._edit_keys and any(_key_matches(key, k) for k in self._edit_keys)
            ai_match   = self._ai_keys   and any(_key_matches(key, k) for k in self._ai_keys)
            if ptt_match or edit_match or ai_match:
                self._release_timer.cancel()
                self._release_timer = None
                return

        if self._active_key is not None:
            return  # 已有键按下，忽略另一个

        if any(_key_matches(key, k) for k in self._ptt_keys):
            now = time.monotonic()
            if (now - self._last_ptt_press_time) < self._double_tap_window:
                # 双击：切换微润色模式，不开新录音
                self._polish_mode = not self._polish_mode
                mode_name = "微润色" if self._polish_mode else "原文"
                print(f"[ptt] 切换为「{mode_name}」模式")
                self._last_ptt_press_time = 0.0
                return
            self._last_ptt_press_time = now
            self._active_key     = "dictate"
            self._active_trigger = key
            self._start_recording()
        elif self._edit_keys and any(_key_matches(key, k) for k in self._edit_keys):
            self._active_key     = "edit"
            self._active_trigger = key
            self._start_recording()
            print("[ptt] 语音编辑模式... ", end="\r", flush=True)
        elif self._ai_keys and any(_key_matches(key, k) for k in self._ai_keys):
            if self._on_ai_key_down:
                self._on_ai_key_down()
            self._active_key     = "ai"
            self._active_trigger = key
            self._start_recording()
            print("[ptt] AI 编辑模式... ", end="\r", flush=True)

    def _on_release(self, key):
        # PTT 松键始终处理，防止打字期间松键导致录音状态卡死
        if _typer.is_simulating():
            return

        if key != self._active_trigger:
            return

        if self._active_key == "dictate":
            self._schedule_stop("dictate")
        elif self._active_key == "edit":
            self._schedule_stop("edit")
        elif self._active_key == "ai":
            self._schedule_stop("ai")
        self._active_trigger = None

    def _schedule_stop(self, mode: str):
        if self._release_timer is not None:
            return
        self._release_timer = threading.Timer(
            self._RELEASE_DEBOUNCE,
            lambda m=mode: self._deferred_stop(m),
        )
        self._release_timer.daemon = True
        self._release_timer.start()

    def _deferred_stop(self, mode: str):
        self._release_timer = None
        if self._active_key == mode:
            self._stop_recording(mode=mode)

    # ── 录音控制 ─────────────────────────────────────────────────

    def _audio_callback(self, indata, frames, time_info, status):
        data = bytes(indata)
        self._buf.append(data)
        if self._active_key == "dictate" and self._vad is not None:
            self._vad_raw.extend(data)
            self._process_vad()

    def _process_vad(self):
        """消费 _vad_raw 中所有完整的 30ms 帧，检测句子边界。"""
        while len(self._vad_raw) >= FRAME_BYTES:
            frame = bytes(self._vad_raw[:FRAME_BYTES])
            del self._vad_raw[:FRAME_BYTES]

            is_speech = self._vad.is_speech(frame, SAMPLE_RATE)

            if is_speech:
                self._vad_in_speech    = True
                self._vad_silent_count = 0
                self._vad_speech_frames.append(frame)
            elif self._vad_in_speech:
                self._vad_speech_frames.append(frame)
                self._vad_silent_count += 1
                if self._vad_silent_count >= SILENCE_FRAMES:
                    self._dispatch_mid_sentence()

    def _dispatch_mid_sentence(self):
        """把当前积累的语音帧作为一句话立刻发出去，重置 VAD 状态。"""
        if len(self._vad_speech_frames) >= MIN_SPEECH_FRAMES:
            pcm = b"".join(self._vad_speech_frames)
            self._vad_sent_count += 1
            n = self._vad_sent_count
            print(f"[ptt] 分句{n} 识别中...    ", end="\r", flush=True)
            threading.Thread(
                target=self._on_utterance,
                args=(pcm, self._polish_mode),
                daemon=True,
                name=f"PTT-mid-{n}",
            ).start()
        self._vad_speech_frames = []
        self._vad_silent_count  = 0
        self._vad_in_speech     = False

    def _open_stream_prebuffer(self):
        """PTT 按下时立即打开主录音流，防误触窗口内捕获用户开口音频。"""
        self._buf               = []
        self._vad_raw           = bytearray()
        self._vad_speech_frames = []
        self._vad_in_speech     = False
        self._vad_silent_count  = 0
        self._vad_sent_count    = 0
        self._stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            device=self._device_idx,
            blocksize=1024,
            callback=self._audio_callback,
        )
        self._stream.start()

    def _start_recording(self):
        _mute_output()  # 静音系统扬声器，防止麦克风收到播放声音
        self._buf               = []
        self._vad_raw           = bytearray()
        self._vad_speech_frames = []
        self._vad_in_speech     = False
        self._vad_silent_count  = 0
        self._vad_sent_count    = 0
        self._stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            device=self._device_idx,
            blocksize=1024,
            callback=self._audio_callback,
        )
        self._stream.start()
        if self._active_key == "dictate":
            if self._polish_mode:
                label = "微润色 录音中"
                self._set_status("polish_recording")
            else:
                label = "录音中"
                self._set_status("recording")
        elif self._active_key == "ai":
            label = "AI 指令录音中"
            self._set_status("ai_recording")
        else:
            label = "编辑指令录音中"
            self._set_status("recording")
        print(f"[ptt] {label}... ", end="\r", flush=True)

    def _stop_recording(self, mode: str):
        self._active_key = None
        self._close_stream()
        _unmute_output()  # 恢复扬声器

        if mode == "dictate" and self._vad is not None:
            self._process_vad()  # 处理流关闭前残留的音频字节

            # 松键时若仍在句子中间，把尾巴也发出去
            if self._vad_in_speech and len(self._vad_speech_frames) >= MIN_SPEECH_FRAMES:
                pcm = b"".join(self._vad_speech_frames)
                self._vad_sent_count += 1
                n = self._vad_sent_count
                print(f"[ptt] 分句{n} 识别中...    ", end="\r", flush=True)
                self._set_status("recognizing")
                threading.Thread(
                    target=self._on_utterance,
                    args=(pcm, self._polish_mode),
                    daemon=True,
                    name=f"PTT-mid-{n}",
                ).start()
            elif self._vad_sent_count == 0:
                # 全程未检测到任何句子（录音极短或全静音），回退到整段发送逻辑
                pcm = b"".join(self._buf)
                if len(pcm) < SAMPLE_RATE * 2 * 0.3:
                    print("[ptt] 录音太短，跳过    ")
                    self._set_status("idle")
                else:
                    print("[ptt] 识别中...    ", end="\r", flush=True)
                    self._set_status("recognizing")
                    threading.Thread(
                        target=self._on_utterance,
                        args=(pcm, self._polish_mode),
                        daemon=True,
                        name="PTT-dictate",
                    ).start()
            else:
                self._set_status("idle")
            self._buf = []
            return

        # edit / ai 模式（VAD 不可用时 dictate 也走这里）
        pcm = b"".join(self._buf)
        self._buf = []
        if len(pcm) < SAMPLE_RATE * 2 * 0.3:
            print("[ptt] 录音太短，跳过    ")
            self._set_status("idle")
            return

        if mode == "dictate":
            label    = "识别中"
            callback = self._on_utterance
            args     = (pcm, self._polish_mode)
            self._set_status("recognizing")
        elif mode == "edit":
            label    = "解析编辑指令"
            callback = self._on_edit_utterance
            args     = (pcm,)
            self._set_status("recognizing")
        else:
            label    = "解析AI指令"
            callback = self._on_ai_utterance
            args     = (pcm,)
            self._set_status("ai_processing")
        print(f"[ptt] {label}...    ", end="\r", flush=True)
        threading.Thread(
            target=callback,
            args=args,
            daemon=True,
            name=f"PTT-{mode}",
        ).start()

    def _close_stream(self):
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
