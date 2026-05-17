"""Headless command-line voice dictation.

Usage:
  python -m agent.cli --list-devices
  python -m agent.cli --once
  python -m agent.cli --loop
"""

from __future__ import annotations

import argparse
import os
import queue
import signal
import sys
import time
from typing import Optional

import sounddevice as sd

from agent.audio_monitor import find_device
from agent.config import load as load_config
from agent.stt import STTClient

SAMPLE_RATE = 16000
BLOCK_SAMPLES = 1024


def list_devices() -> None:
    print("\n可用输入设备：\n")
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            default = " <- default" if i == sd.default.device[0] else ""
            print(f"  [{i:2d}] {d['name']}{default}")
    print()


def _open_stream(device):
    return sd.RawInputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16",
        device=device,
        blocksize=BLOCK_SAMPLES,
        callback=None,
    )


def _resolve_device(device_hint: Optional[str] = "auto"):
    device = find_device(device_hint)
    if device is None:
        print("[cli] 使用系统默认麦克风")
    else:
        info = sd.query_devices(device)
        print(f"[cli] 使用麦克风: {info['name']}")
    return device


def record_for_seconds(seconds: float, device_hint: Optional[str] = "auto") -> bytes:
    device = _resolve_device(device_hint)
    print(f"[rec] 录音 {seconds:.1f}s...", flush=True)
    chunks: list[bytes] = []
    end = time.monotonic() + seconds
    with sd.RawInputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16",
        device=device,
        blocksize=BLOCK_SAMPLES,
    ) as stream:
        while time.monotonic() < end:
            frames = min(BLOCK_SAMPLES, max(1, int((end - time.monotonic()) * SAMPLE_RATE)))
            data, overflowed = stream.read(frames)
            if overflowed:
                print("[audio] input overflow", file=sys.stderr)
            chunks.append(bytes(data))
    pcm = b"".join(chunks)
    print(f"[rec] 完成，时长 {len(pcm) / SAMPLE_RATE / 2:.2f}s")
    return pcm


def record_until_enter(device_hint: Optional[str] = "auto") -> bytes:
    device = _resolve_device(device_hint)

    q: queue.Queue[bytes] = queue.Queue()
    stop = False

    def callback(indata, frames, time_info, status):
        if status:
            print(f"[audio] {status}", file=sys.stderr)
        q.put(bytes(indata))

    print("按 Enter 开始录音，再按 Enter 停止。", flush=True)
    input()
    print("[rec] 录音中...", flush=True)

    chunks: list[bytes] = []
    with sd.RawInputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16",
        device=device,
        blocksize=BLOCK_SAMPLES,
        callback=callback,
    ):
        # Wait for Enter without blocking audio callback.
        import threading

        def wait_stop():
            nonlocal stop
            input()
            stop = True

        t = threading.Thread(target=wait_stop, daemon=True)
        t.start()
        while not stop:
            try:
                chunks.append(q.get(timeout=0.1))
            except queue.Empty:
                pass

    while not q.empty():
        chunks.append(q.get_nowait())
    pcm = b"".join(chunks)
    print(f"[rec] 完成，时长 {len(pcm) / SAMPLE_RATE / 2:.2f}s")
    return pcm


def main() -> int:
    parser = argparse.ArgumentParser(description="Voice Keyboard headless CLI")
    parser.add_argument("--list-devices", action="store_true", help="列出录音设备")
    parser.add_argument("--once", action="store_true", help="录一次并转写")
    parser.add_argument("--loop", action="store_true", help="循环录音转写")
    parser.add_argument("--device", default=None, help="设备序号或名称片段，默认读取配置")
    parser.add_argument("--seconds", type=float, default=None, help="固定录音秒数；设置后不需要按 Enter 停止")
    args = parser.parse_args()

    if args.list_devices:
        list_devices()
        return 0

    cfg = load_config()
    stt_cfg = cfg.get("stt", {})
    if not stt_cfg:
        print("[cli] 未配置 stt。请编辑 config.yaml 或 .env。", file=sys.stderr)
        return 2
    audio_cfg = cfg.get("audio", {})
    device = args.device if args.device is not None else audio_cfg.get("device", "auto")
    stt = STTClient(stt_cfg)

    def run_once() -> None:
        pcm = record_for_seconds(args.seconds, device) if args.seconds else record_until_enter(device)
        if not pcm:
            print("[stt] 没有录到音频")
            return
        print("[stt] 识别中...", flush=True)
        text = stt.transcribe(pcm)
        print("\n--- text ---")
        print(text)
        print("------------\n")

    if args.loop:
        while True:
            run_once()
    else:
        run_once()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
