"""Разбор PLAY RECAP ansible-playbook для теста идемпотентности (чистая логика, без I/O)."""
from __future__ import annotations

import re

_HOST = re.compile(r"^(?P<host>\S+)\s*:\s*ok=(?P<ok>\d+)\s+changed=(?P<changed>\d+)"
                   r"\s+unreachable=(?P<unreachable>\d+)\s+failed=(?P<failed>\d+)")


def parse_recap(text: str) -> dict[str, int]:
    """Суммирует ok/changed/unreachable/failed по всем хостам PLAY RECAP.

    Пустой словарь-результат с ok=-1 означает, что RECAP в выводе не найден.
    """
    total = {"ok": 0, "changed": 0, "unreachable": 0, "failed": 0}
    found = False
    for line in text.splitlines():
        m = _HOST.match(line.strip())
        if m:
            found = True
            for k in total:
                total[k] += int(m.group(k))
    if not found:
        total["ok"] = -1
    return total


def is_idempotent(recap: dict[str, int]) -> bool:
    return recap["ok"] >= 0 and recap["changed"] == 0 and recap["failed"] == 0 and recap["unreachable"] == 0
