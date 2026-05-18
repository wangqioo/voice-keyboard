"""TypeUp backend credential adapter for Speech Interpretation Providers."""

import json
import pathlib
import time

import requests


class TypeUpBackendAuth:
    def __init__(self, cfg: dict, log_prefix: str = "typeup"):
        self._api_base_url = str(
            cfg.get("api_base_url") or cfg.get("base_url") or "http://localhost:8000"
        ).rstrip("/")
        self._access_token = str(cfg.get("access_token") or cfg.get("api_key") or "").strip()
        self._refresh_token = str(cfg.get("refresh_token") or "").strip()
        self._cloud_bridge_path = str(cfg.get("cloud_bridge_path") or "").strip()
        self._log_prefix = log_prefix
        self.reload_from_bridge()

    @property
    def api_base_url(self) -> str:
        return self._api_base_url

    @property
    def access_token(self) -> str:
        return self._access_token

    @property
    def refresh_token(self) -> str:
        return self._refresh_token

    def require_configured(self) -> None:
        if not self._api_base_url:
            raise RuntimeError("TypeUp 后端地址未配置")
        if not self._access_token:
            raise RuntimeError("请先登录 TypeUp 后端账号")

    def auth_header(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._access_token}"}

    def reload_from_bridge(self) -> bool:
        if not self._cloud_bridge_path:
            return False
        try:
            path = pathlib.Path(self._cloud_bridge_path)
            if not path.exists():
                return False
            payload = json.loads(path.read_text(encoding="utf-8") or "{}")
            changed = False
            api_base_url = str(payload.get("apiBaseUrl") or "").strip().rstrip("/")
            access_token = str(payload.get("accessToken") or "").strip()
            refresh_token = str(payload.get("refreshToken") or "").strip()
            if api_base_url and api_base_url != self._api_base_url:
                self._api_base_url = api_base_url
                changed = True
            if access_token and access_token != self._access_token:
                self._access_token = access_token
                changed = True
            if refresh_token and refresh_token != self._refresh_token:
                self._refresh_token = refresh_token
                changed = True
            if changed:
                print(f"[{self._log_prefix}] 已同步最新后端登录凭证")
            return changed
        except Exception as e:
            print(f"[{self._log_prefix}] 读取后端登录凭证失败: {e}")
            return False

    def refresh_access_token(self) -> None:
        resp = requests.post(
            f"{self._api_base_url}/v1/auth/refresh",
            json={"refresh_token": self._refresh_token},
            timeout=15,
        )
        if not resp.ok:
            raise RuntimeError(self.error_message(resp, "TypeUp 后端登录已过期"))
        data = resp.json()
        self._access_token = data["access_token"]
        self._refresh_token = data["refresh_token"]
        self._persist_tokens()

    def error_message(self, resp, fallback: str) -> str:
        try:
            data = resp.json()
            return data.get("error", {}).get("message") or data.get("detail") or fallback
        except Exception:
            return f"{fallback}: HTTP {resp.status_code} {resp.text}"

    def _persist_tokens(self) -> None:
        if not self._cloud_bridge_path:
            return
        try:
            path = pathlib.Path(self._cloud_bridge_path)
            payload = {}
            if path.exists():
                payload = json.loads(path.read_text(encoding="utf-8") or "{}")
            payload["accessToken"] = self._access_token
            payload["refreshToken"] = self._refresh_token
            payload["updatedAt"] = int(time.time() * 1000)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"[{self._log_prefix}] 同步后端登录凭证失败: {e}")


def is_typeup_backend_configured(cfg: dict) -> bool:
    if cfg.get("provider") != "typeup_backend":
        return bool(cfg.get("api_key"))
    return bool((cfg.get("api_base_url") or cfg.get("base_url")) and cfg.get("access_token"))
