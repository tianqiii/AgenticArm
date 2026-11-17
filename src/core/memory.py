"""会话记忆：一个 JSON 文件按 session_id 存消息。"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path


class Memory:
    def __init__(self, path="sessions.json"):
        self.path = Path(path)

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # 文件损坏时先备份，不静默丢数据
            backup = self.path.with_suffix(self.path.suffix + ".bak")
            os.replace(self.path, backup)
            return {}

    def _write(self, data: dict) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)  # 原子替换

    def load(self, session_id: str) -> list[dict]:
        return list(self._read().get(session_id, {}).get("messages", []))

    def save(self, session_id: str, messages: list[dict]) -> None:
        data = self._read()
        data[session_id] = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "messages": messages,
        }
        self._write(data)

    def sessions(self) -> dict:
        return self._read()
