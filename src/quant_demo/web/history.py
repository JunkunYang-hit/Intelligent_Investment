"""回测结果的本地持久化。

每次回测保存为一个独立 JSON 文件，便于重启后继续查看，也避免单个历史文件
越来越大。文件名只使用服务端生成的编号，读取和删除时会再次校验编号。
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


_SAFE_ID = re.compile(r"^[0-9]{8}T[0-9]{6}-[0-9a-f]{8}$")


class BacktestHistoryStore:
    """在指定目录保存、列出、读取和删除完整回测报告。"""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def save(self, request: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
        created_at = datetime.now().astimezone().isoformat(timespec="seconds")
        history_id = f"{datetime.now():%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}"
        saved = {
            **report,
            "history": {
                "id": history_id,
                "created_at": created_at,
                "request": request,
            },
        }
        destination = self.directory / f"{history_id}.json"
        temporary = self.directory / f".{history_id}.tmp"
        with self._lock:
            temporary.write_text(
                json.dumps(saved, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            temporary.replace(destination)
        return saved

    def list(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        with self._lock:
            paths = list(self.directory.glob("*.json"))
        for path in paths:
            try:
                report = json.loads(path.read_text(encoding="utf-8"))
                rows.append(self._summary(report))
            except (OSError, json.JSONDecodeError, KeyError, TypeError):
                # 单个损坏文件不应导致整个历史页面不可用。
                continue
        return sorted(rows, key=lambda row: row["created_at"], reverse=True)

    def get(self, history_id: str) -> dict[str, Any] | None:
        path = self._path(history_id)
        if not path.exists():
            return None
        with self._lock:
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return None

    def delete(self, history_id: str) -> bool:
        path = self._path(history_id)
        with self._lock:
            if not path.exists():
                return False
            path.unlink()
        return True

    def _path(self, history_id: str) -> Path:
        if not _SAFE_ID.fullmatch(history_id):
            raise ValueError("回测历史编号无效")
        return self.directory / f"{history_id}.json"

    @staticmethod
    def _summary(report: dict[str, Any]) -> dict[str, Any]:
        history = report["history"]
        summary = report["summary"]
        metrics = report["result"]["metrics"]
        request = history.get("request", {})
        return {
            "id": history["id"],
            "created_at": history["created_at"],
            "symbol": summary["symbol"],
            "start": summary["start"],
            "end": summary["end"],
            "strategy": request.get("strategy", "unknown"),
            "total_return": metrics["total_return"],
            "max_drawdown": metrics["max_drawdown"],
            "trade_count": metrics["trade_count"],
        }
