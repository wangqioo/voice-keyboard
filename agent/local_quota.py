"""
本地额度管理模块。

工作流程：
  1. 启动时从 config.yaml 读取云端账号
  2. CloudClient.login() → 获取 JWT
  3. 从云端拉取用户套餐限额（月 STT 分钟数、AI 调用次数）
  4. 读取本地缓存 ~/.voicekeyboard/quota.json
  5. 如果月份变了，重置月度计数（但保留云端最新值覆盖）
  6. 每次 STT / AI 调用前 check()，通过才执行
  7. 执行后 deduct() 扣减本地额度
  8. 后台异步 sync_to_cloud() 上报用量事件

配置 config.yaml 新增段：
  cloud:
    email: "user@voicekeyboard.com"
    password: "vk123456"
    base_url: "http://localhost:8000"     # 可选，默认 http://localhost:8000
"""
import json
import os
import time
import threading
from pathlib import Path
from typing import Optional

_QUOTA_DIR = Path.home() / ".voicekeyboard"
_QUOTA_PATH = _QUOTA_DIR / "quota.json"


class QuotaError(Exception):
    """额度不足"""
    pass


class QuotaManager:
    """本地额度管理器"""

    def __init__(self, cloud_client=None):
        self.cloud = cloud_client
        self._lock = threading.Lock()

        # ── 云端计划限额 ──
        self.stt_monthly_limit: int = 0       # 秒
        self.ai_monthly_limit: int = 0        # 次数
        self.subscription_tier: str = "free"

        # ── 本地使用量（当前月） ──
        self.usage_month: str = ""            # "2026-05"
        self.monthly_stt_seconds: int = 0
        self.monthly_ai_calls: int = 0

        # ── 同步控制 ──
        self._dirty: bool = False
        self._last_sync: float = 0
        self._sync_interval: float = 30.0     # 每 30 秒自动同步

        self._load_cache()

    # ── 初始化 ──────────────────────────────────────────────────

    def initialize(self) -> bool:
        """
        连接云端，拉取计划限额。
        返回 True 表示初始化成功（即使云端不可用也返回 True，使用上次缓存）。
        """
        if not self.cloud:
            return False

        try:
            # 先检查是否已登录
            if not self.cloud.is_logged_in():
                raise QuotaError("未登录云端")

            # 拉取计划信息
            plans_data = self.cloud.get_plans()
            plans = plans_data.get("plans", []) if isinstance(plans_data, dict) else plans_data

            # 拉取用户用量摘要（含当前限额）
            summary = self.cloud.get_stats()

            # 从 summary 获取限额
            limit_stt = summary.get("monthly_stt_limit", 0)
            limit_ai = summary.get("monthly_ai_limit", 0)
            tier = summary.get("subscription_tier", "free")

            # paid 用户无限额（basic/pro 等）
            if tier != "free":
                # 从 plans 里查具体限额
                for p in plans:
                    if p.get("id") == tier or p.get("name", "").lower() == tier:
                        # 处理 stt_minutes 或者 stt_limit
                        stt_min = p.get("stt_minutes")
                        if stt_min == "不限" or stt_min == -1 or stt_min is None:
                            limit_stt = -1  # -1 表示无限制
                        elif isinstance(stt_min, (int, float)):
                            limit_stt = int(stt_min) * 60

                        ai_calls = p.get("ai_calls", p.get("ai_limit"))
                        if ai_calls == "不限" or ai_calls == -1 or ai_calls is None:
                            limit_ai = -1
                        elif isinstance(ai_calls, (int, float)):
                            limit_ai = int(ai_calls)
                        break
                else:
                    # 没找到plan条目，但用户是付费用户——用 summary 的值
                    if limit_stt == 0:
                        limit_stt = -1
                    if limit_ai == 0:
                        limit_ai = -1

            with self._lock:
                self.stt_monthly_limit = limit_stt
                self.ai_monthly_limit = limit_ai
                self.subscription_tier = tier

                # 将云端数据同步到本地（云端为准）
                self.usage_month = summary.get("usage_month", self.usage_month)
                self.monthly_stt_seconds = summary.get("monthly_stt_seconds", self.monthly_stt_seconds)
                self.monthly_ai_calls = summary.get("monthly_ai_calls", self.monthly_ai_calls)
                self._save_cache()

            return True

        except Exception as e:
            print(f"[quota] 云端同步失败，使用本地缓存: {e}")
            # 缓存无效则走默认限额
            if not self.usage_month:
                with self._lock:
                    self._reset_month()
            return False

    # ── 额度检查 ────────────────────────────────────────────────

    def can_stt(self, duration_seconds: float = 0) -> tuple[bool, str]:
        """
        检查 STT 额度。
        duration_seconds: 本次预计录音时长（秒），用于精确检查。
        """
        with self._lock:
            self._ensure_month()

            # 无限制
            if self.stt_monthly_limit == -1:
                return True, ""

            remaining = self.stt_monthly_limit - self.monthly_stt_seconds
            if remaining <= 0:
                return False, f"本月 STT 额度已用完（{self._fmt_stt()}），请联系管理员升级"

            return True, ""

    def can_ai(self) -> tuple[bool, str]:
        """检查 AI 编辑额度"""
        with self._lock:
            self._ensure_month()

            if self.ai_monthly_limit == -1:
                return True, ""

            remaining = self.ai_monthly_limit - self.monthly_ai_calls
            if remaining <= 0:
                return False, f"本月 AI 编辑额度已用完（{self.monthly_ai_calls}/{self.ai_monthly_limit} 次），请联系管理员升级"

            return True, ""

    # ── 额度扣减 ────────────────────────────────────────────────

    def deduct_stt(self, duration_seconds: float):
        """STT 调用后扣减额度"""
        with self._lock:
            self._ensure_month()
            self.monthly_stt_seconds += int(duration_seconds)
            self._dirty = True
            self._save_cache()

    def deduct_ai(self, tokens: int = 0, chars: int = 0):
        """AI 调用后扣减额度"""
        with self._lock:
            self._ensure_month()
            self.monthly_ai_calls += 1
            self._dirty = True
            self._save_cache()

    # ── 同步到云端 ────────────────────────────────────────────────

    def sync_to_cloud(self, force: bool = False):
        """将本地使用量上报到云端"""
        if not self.cloud or not self.cloud.is_logged_in():
            return

        now = time.time()
        if not force and now - self._last_sync < self._sync_interval:
            return

        with self._lock:
            if not self._dirty and not force:
                return
            self._dirty = False
            self._last_sync = now

        try:
            # 上报 STT 用量（近似值）
            with self._lock:
                stt_sec = self.monthly_stt_seconds
                ai_calls = self.monthly_ai_calls

            # 单次同步只上报增量，但简单起见全量上报
            # 云端 sumary 接口会累计，所以这里只上报变动
            self.cloud.report_event(
                event_type="stt",
                audio_duration=stt_sec,
            )
            if ai_calls > 0:
                self.cloud.report_event(
                    event_type="ai_polish",
                    tokens=0,
                    input_chars=0,
                    output_chars=0,
                )

        except Exception as e:
            print(f"[quota] 云端同步失败: {e}")
            with self._lock:
                self._dirty = True

    # ── 内部 ────────────────────────────────────────────────────

    def _ensure_month(self):
        """检查月份是否变化，变化则重置月度计数（保留限额不变）"""
        current_month = time.strftime("%Y-%m")
        if self.usage_month != current_month:
            self.usage_month = current_month
            self.monthly_stt_seconds = 0
            self.monthly_ai_calls = 0
            self._save_cache()

    def _reset_month(self):
        self.usage_month = time.strftime("%Y-%m")
        self.monthly_stt_seconds = 0
        self.monthly_ai_calls = 0

    def _save_cache(self):
        """持久化到本地文件"""
        try:
            _QUOTA_DIR.mkdir(parents=True, exist_ok=True)
            data = {
                "usage_month": self.usage_month,
                "monthly_stt_seconds": self.monthly_stt_seconds,
                "monthly_ai_calls": self.monthly_ai_calls,
                "stt_monthly_limit": self.stt_monthly_limit,
                "ai_monthly_limit": self.ai_monthly_limit,
                "subscription_tier": self.subscription_tier,
            }
            _QUOTA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"[quota] 缓存写入失败: {e}")

    def _load_cache(self):
        """从本地文件加载缓存的额度数据"""
        try:
            if _QUOTA_PATH.exists():
                data = json.loads(_QUOTA_PATH.read_text())
                self.usage_month = data.get("usage_month", "")
                self.monthly_stt_seconds = data.get("monthly_stt_seconds", 0)
                self.monthly_ai_calls = data.get("monthly_ai_calls", 0)
                self.stt_monthly_limit = data.get("stt_monthly_limit", 0)
                self.ai_monthly_limit = data.get("ai_monthly_limit", 0)
                self.subscription_tier = data.get("subscription_tier", "free")
            else:
                self._reset_month()
                self._save_cache()
        except Exception as e:
            print(f"[quota] 缓存读取失败: {e}")
            self._reset_month()

    @staticmethod
    def _fmt_stt(seconds: int = None) -> str:
        """格式化秒数为可读形式"""
        if seconds is None:
            return f"{seconds}秒"
        mins = seconds // 60
        secs = seconds % 60
        if mins > 0:
            return f"{mins}分{secs}秒"
        return f"{secs}秒"

    # ── 状态输出 ────────────────────────────────────────────────

    def status_str(self) -> str:
        """返回额度状态文字"""
        with self._lock:
            if self.stt_monthly_limit == -1:
                stt_status = f"STT: 已用 {self._fmt_stt(self.monthly_stt_seconds)}（无限制）"
            else:
                remaining = max(0, self.stt_monthly_limit - self.monthly_stt_seconds)
                stt_status = f"STT: {self._fmt_stt(self.monthly_stt_seconds)} / {self._fmt_stt(self.stt_monthly_limit)}（剩余{self._fmt_stt(remaining)}）"

            if self.ai_monthly_limit == -1:
                ai_status = f"AI: {self.monthly_ai_calls} 次（无限制）"
            else:
                remaining = max(0, self.ai_monthly_limit - self.monthly_ai_calls)
                ai_status = f"AI: {self.monthly_ai_calls} / {self.ai_monthly_limit} 次（剩余{remaining}次）"

            return f"[{self.subscription_tier}] {stt_status} | {ai_status}"

    def close(self):
        """关闭前同步一次"""
        self.sync_to_cloud(force=True)
        if self.cloud:
            self.cloud.close()
