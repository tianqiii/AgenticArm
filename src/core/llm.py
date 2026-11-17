"""DeepSeek / OpenAI 兼容的 chat 客户端。

沿用 agent-demo 的实现；.env 从项目根目录读取。
"""

import json
import os
import time
from pathlib import Path

import requests


def _project_root() -> Path:
    # src/arm_agent_demo/llm.py -> 项目根目录
    return Path(__file__).resolve().parents[2]


def load_dotenv() -> None:
    """从项目根目录的 .env 读配置，已有环境变量优先。"""
    candidates = (Path.cwd() / ".env", _project_root() / ".env")
    path = next((item for item in candidates if item.exists()), None)
    if path is None:
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


class LLM:
    def __init__(self, base_url=None, model=None, api_key=None, timeout=120):
        load_dotenv()
        self.base_url = (
            base_url or os.getenv("LLM_BASE_URL") or "https://api.deepseek.com"
        )
        # 确认该模型支持 function calling；可用 LLM_MODEL 覆盖
        self.model = model or os.getenv("LLM_MODEL") or "deepseek-flash"
        self.api_key = (
            api_key or os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
        )
        self.timeout = timeout

        if not self.api_key:
            raise RuntimeError("缺少 API Key：请设置 DEEPSEEK_API_KEY 或 LLM_API_KEY")

    def chat(self, messages, tools=None):
        """返回 (assistant_message, usage, latency_ms)。"""
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": 1024,
        }
        if tools:
            payload["tools"] = tools

        retry_status = {429, 500, 502, 503, 504}
        max_retries = 3
        last_error = None

        for attempt in range(max_retries):
            started = time.perf_counter()
            try:
                response = requests.post(
                    f"{self.base_url}/chat/completions",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.api_key}",
                    },
                    timeout=self.timeout,
                )
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
                last_error = exc
                if attempt == max_retries - 1:
                    raise RuntimeError(
                        f"请求失败（已重试 {max_retries} 次）：{exc}"
                    ) from exc
                time.sleep(2**attempt)
                continue

            latency_ms = (time.perf_counter() - started) * 1000
            if response.status_code in retry_status:
                last_error = RuntimeError(
                    f"HTTP {response.status_code}：{response.text[:200]}"
                )
                if attempt == max_retries - 1:
                    raise last_error
                time.sleep(2**attempt)
                continue

            if not response.ok:
                raise RuntimeError(
                    f"HTTP {response.status_code}: {response.text[:200]}"
                )

            try:
                data = response.json()
            except ValueError as exc:
                raise RuntimeError(f"响应不是合法 JSON：{exc}") from exc

            return data["choices"][0]["message"], data.get("usage", {}), latency_ms

        raise RuntimeError(f"重试耗尽：{last_error}")
