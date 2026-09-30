"""Модель результата проверки требования кейса (чистая логика, без I/O)."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Status(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"


@dataclass
class CheckResult:
    req: str            # ID требования, например "R-06"
    title: str
    command: str        # как эксперт воспроизведёт проверку руками
    status: Status
    evidence: str = ""  # реальный ответ / фрагмент вывода


@dataclass
class Report:
    results: list[CheckResult] = field(default_factory=list)

    def add(self, r: CheckResult) -> CheckResult:
        self.results.append(r)
        return r

    @property
    def failed(self) -> list[CheckResult]:
        return [r for r in self.results if r.status is Status.FAIL]

    @property
    def exit_code(self) -> int:
        """0 — все PASS/SKIP, 1 — есть FAIL."""
        return 1 if self.failed else 0


def check(req: str, title: str, command: str, ok: bool, evidence: str) -> CheckResult:
    return CheckResult(req, title, command, Status.PASS if ok else Status.FAIL, evidence)


def condition_true(conditions: list[dict[str, str]], ctype: str) -> bool:
    """True, если в списке status.conditions ресурса есть condition ctype со status=True."""
    return any(c.get("type") == ctype and c.get("status") == "True" for c in conditions)


def route_accepted(route: dict[str, object]) -> bool:
    """HTTPRoute принят всеми родителями: Accepted=True и ResolvedRefs=True."""
    status = route.get("status")
    parents = status.get("parents", []) if isinstance(status, dict) else []
    if not parents:
        return False
    return all(
        condition_true(p.get("conditions", []), "Accepted")
        and condition_true(p.get("conditions", []), "ResolvedRefs")
        for p in parents
    )


def images_without_pinned_tag(images: list[str]) -> list[str]:
    """Образы без фиксированного тега (latest или без тега/digest)."""
    bad = []
    for img in images:
        name = img.rsplit("/", 1)[-1]
        if "@sha256:" in img:
            continue
        if ":" not in name or name.endswith(":latest"):
            bad.append(img)
    return bad


def render_markdown(report: Report, meta: dict[str, str]) -> str:
    lines = ["# Отчёт-доказательство (make verify)", ""]
    for k, v in meta.items():
        lines.append(f"- **{k}:** {v}")
    total = len(report.results)
    passed = sum(1 for r in report.results if r.status is Status.PASS)
    lines += ["", f"**Итог: {passed}/{total} PASS, {len(report.failed)} FAIL**", ""]
    lines += ["| Требование | Проверка | Статус |", "|---|---|---|"]
    for r in report.results:
        lines.append(f"| {r.req} | {r.title} | {r.status.value} |")
    lines.append("")
    for r in report.results:
        lines += [f"## {r.req} — {r.title}: {r.status.value}", "", f"Команда: `{r.command}`", ""]
        if r.evidence:
            lines += ["```", r.evidence.strip()[:3000], "```", ""]
    return "\n".join(lines)
