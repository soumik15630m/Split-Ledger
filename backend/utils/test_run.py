#!/usr/bin/env python3
"""
utils/test_run.py — SplitLedger  ·  Pretty Test Runner
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Usage (run from project root):
  python backend/utils/test_run.py                 # full suite
  python backend/utils/test_run.py --unit          # unit tests only
  python backend/utils/test_run.py --integration   # integration tests only
  python backend/utils/test_run.py --coverage      # with coverage report
  python backend/utils/test_run.py -x              # stop on first failure
  python backend/utils/test_run.py -k "balance"    # filter by keyword

Requires:  pip install rich pytest pytest-cov
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# Rich output uses Unicode glyphs; force UTF-8 streams on Windows consoles
# that default to cp1252 to avoid UnicodeEncodeError.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (ValueError, OSError):
            pass

# ── Dependency guard ──────────────────────────────────────────────────────
try:
    import pytest
    from rich import box
    from rich.align import Align
    from rich.columns import Columns
    from rich.console import Console, Group
    from rich.live import Live
    from rich.markup import escape
    from rich.padding import Padding
    from rich.panel import Panel
    from rich.progress import (
        BarColumn,
        MofNCompleteColumn,
        Progress,
        SpinnerColumn,
        TaskProgressColumn,
        TextColumn,
        TimeElapsedColumn,
    )
    from rich.rule import Rule
    from rich.table import Table
    from rich.text import Text
    from rich.theme import Theme
except ImportError as e:
    print(f"\n  Missing dependency: {e}")
    print("  Run:  pip install rich pytest pytest-cov\n")
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════
#  THEME
# ═══════════════════════════════════════════════════════════════════════════

THEME = Theme({
    "pass":    "bold bright_green",
    "fail":    "bold bright_red",
    "skip":    "bold yellow",
    "hdr":     "bold bright_white",
    "dim":     "dim white",
    "muted":   "bright_black",
    "unit":    "cyan",
    "intg":    "magenta",
    "accent":  "bright_cyan",
    "good":    "bright_green",
    "warn":    "bright_yellow",
    "bad":     "bright_red",
    "border":  "bright_black",
    "inv":     "bold bright_cyan",
})

con = Console(theme=THEME, highlight=False)


# ═══════════════════════════════════════════════════════════════════════════
#  DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class TResult:
    nodeid:   str
    outcome:  str      # passed | failed | error | skipped
    duration: float    # seconds
    longrepr: str = ""

    @property
    def tier(self) -> str:
        if "unit"        in self.nodeid: return "unit"
        if "integration" in self.nodeid: return "integration"
        return "other"

    @property
    def module_stem(self) -> str:
        return Path(self.nodeid.split("::")[0]).stem

    @property
    def short_name(self) -> str:
        parts = self.nodeid.split("::")
        return "::".join(parts[1:]) if len(parts) > 1 else self.nodeid

    @property
    def passed(self)  -> bool: return self.outcome == "passed"
    @property
    def failed(self)  -> bool: return self.outcome in ("failed", "error")
    @property
    def skipped(self) -> bool: return self.outcome == "skipped"


@dataclass
class Stats:
    results: list[TResult] = field(default_factory=list)
    elapsed: float = 0.0

    @property
    def total(self)   -> int:   return len(self.results)
    @property
    def passed(self)  -> int:   return sum(1 for r in self.results if r.passed)
    @property
    def failed(self)  -> int:   return sum(1 for r in self.results if r.failed)
    @property
    def skipped(self) -> int:   return sum(1 for r in self.results if r.skipped)
    @property
    def rate(self)    -> float:
        return self.passed / self.total * 100 if self.total else 0.0
    @property
    def ok(self) -> bool:
        return self.failed == 0 and self.total > 0

    def by_tier(self, tier: str) -> list[TResult]:
        return [r for r in self.results if r.tier == tier]


# ═══════════════════════════════════════════════════════════════════════════
#  PYTEST PLUGIN  —  live result collection
# ═══════════════════════════════════════════════════════════════════════════

class Collector:
    """Minimal pytest plugin.  Captures results and drives the Live display."""

    def __init__(self, stream: Text, progress: Progress, task_id):
        self.results:  list[TResult] = []
        self._t0:      dict[str, float] = {}
        self._stream   = stream
        self._progress = progress
        self._task     = task_id
        self._live: Live | None = None     # set just before pytest.main()

    # collection finished → we now know the total
    def pytest_collection_finish(self, session):
        self._progress.update(self._task, total=len(session.items))

    # record start time
    def pytest_runtest_logstart(self, nodeid, location):
        self._t0[nodeid] = time.perf_counter()

    # capture outcome
    def pytest_runtest_logreport(self, report):
        is_call        = report.when == "call"
        is_setup_skip  = report.when == "setup" and report.outcome == "skipped"
        if not (is_call or is_setup_skip):
            return

        nodeid  = report.nodeid
        dur     = time.perf_counter() - self._t0.get(nodeid, time.perf_counter())
        outcome = report.outcome

        longrepr = ""
        if outcome == "failed" and report.longrepr:
            raw   = str(report.longrepr)
            lines = [l.strip() for l in raw.splitlines() if l.strip()]
            for ln in reversed(lines):
                if any(k in ln for k in ("AssertionError", "Error:", "assert ", "FAILED")):
                    longrepr = ln[:160]
                    break
            if not longrepr and lines:
                longrepr = lines[-1][:160]

        r = TResult(nodeid=nodeid, outcome=outcome, duration=dur, longrepr=longrepr)
        self.results.append(r)

        # ── animated dot stream ──────────────────────────────────────────
        dot, style = {
            "passed":  (".", "good"),
            "failed":  ("x", "bad"),
            "skipped": ("o", "warn"),
            "error":   ("!", "bad"),
        }.get(outcome, ("?", "dim"))

        self._stream.append(dot, style=style)

        # line wrap at 60 dots
        if len(self.results) % 60 == 0:
            self._stream.append("\n        ")

        self._progress.advance(self._task)
        if self._live:
            self._live.refresh()


# ═══════════════════════════════════════════════════════════════════════════
#  RENDER HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _fmt_time(s: float) -> str:
    if s < 60:
        return f"{s:.2f}s"
    m, sec = divmod(s, 60)
    return f"{int(m)}m {sec:.1f}s"


def _time_col(s: float) -> str:
    return "good" if s < 0.5 else "warn" if s < 5 else "bad"


def _rate_col(p: float) -> str:
    return "good" if p == 100 else "warn" if p >= 75 else "bad"


def _tier_style(t: str) -> str:
    return {"unit": "unit", "integration": "intg"}.get(t, "dim")


def _tier_label(t: str) -> str:
    return {"unit": "UNIT", "integration": "INTG"}.get(t, "???")


# ─── Header / banner ──────────────────────────────────────────────────────

def render_banner(mode: str, cov: bool) -> None:
    con.print(
        "\n"
        "  [bold bright_cyan]╔══════════════════════════════════════════════════════╗[/]\n"
        "  [bold bright_cyan]║[/]                                                    [bold bright_cyan]║[/]\n"
        "  [bold bright_cyan]║[/]   [bold bright_white]S P L I T L E D G E R[/]   "
        "[dim]·   Test Suite Runner[/]    [bold bright_cyan]║[/]\n"
        "  [bold bright_cyan]║[/]   [dim]Financial correctness, enforced on every run[/]   [bold bright_cyan]║[/]\n"
        "  [bold bright_cyan]║[/]                                                    [bold bright_cyan]║[/]\n"
        "  [bold bright_cyan]╚══════════════════════════════════════════════════════╝[/]\n"
    )
    tags = [f"[dim]Mode[/]  [accent]{mode}[/]"]
    if cov:
        tags.append("[dim]Coverage[/]  [good]enabled[/]")
    con.print("  " + "   [muted]│[/]   ".join(tags))
    con.print()


# ─── Metric cards ─────────────────────────────────────────────────────────

def _card(title: str, value: str, sub: str, border: str) -> Panel:
    body = Align.center(Text.assemble(
        ("\n", ""),
        (f" {value} ", f"bold {border}"),
        ("\n", ""),
        (f" {sub} ", "dim"),
        ("\n", ""),
    ))
    return Panel(body, title=f"[muted]{title}[/]",
                 border_style=border, padding=(0, 1), expand=True)


def render_cards(st: Stats) -> None:
    wall = _fmt_time(st.elapsed)
    rc   = _rate_col(st.rate)
    tc   = "good" if st.elapsed < 30 else "warn" if st.elapsed < 120 else "bad"
    fc   = "bad"  if st.failed  > 0 else "bright_black"
    sc   = "warn" if st.skipped > 0 else "bright_black"

    con.print(Columns([
        _card("COLLECTED", str(st.total),           "tests",          "bright_white"),
        _card("PASSED",    str(st.passed),           f"of {st.total}", "bright_green"),
        _card("FAILED",    str(st.failed),           "failures",       fc),
        _card("SKIPPED",   str(st.skipped),          "skipped",        sc),
        _card("PASS RATE", f"{st.rate:.1f}%",        "of total",       rc),
        _card("WALL TIME", wall,                     "elapsed",        tc),
    ], equal=True, expand=True))


# ─── Tier breakdown ────────────────────────────────────────────────────────

def render_tier_table(st: Stats) -> Table:
    tbl = Table(
        title="[muted]Tier Breakdown[/]", title_justify="left",
        box=box.ROUNDED, border_style="border",
        show_header=True, header_style="bold dim",
        padding=(0, 2), expand=True,
    )
    for col, kw in [
        ("Tier",    dict(width=14, style="bold")),
        ("Tests",   dict(justify="center", width=8)),
        ("Passed",  dict(justify="center", width=8)),
        ("Failed",  dict(justify="center", width=8)),
        ("Skipped", dict(justify="center", width=9)),
        ("Pass %",  dict(justify="center", width=10)),
        ("Avg ms",  dict(justify="right",  width=10)),
    ]:
        tbl.add_column(col, **kw)

    for tier, label in [("unit", "Unit"), ("integration", "Integration")]:
        rs    = st.by_tier(tier)
        tot   = len(rs)
        pas   = sum(1 for r in rs if r.passed)
        fai   = sum(1 for r in rs if r.failed)
        ski   = sum(1 for r in rs if r.skipped)
        rate  = pas / tot * 100 if tot else 0.0
        avgms = sum(r.duration for r in rs) / tot * 1000 if tot else 0.0
        ts    = _tier_style(tier)
        rc    = _rate_col(rate)
        fc    = "bad" if fai else "muted"

        tbl.add_row(
            f"[{ts}]{label}[/]",
            f"[hdr]{tot}[/]",
            f"[good]{pas}[/]",
            f"[{fc}]{fai}[/]",
            f"[warn]{ski}[/]" if ski else "[muted]0[/]",
            f"[{rc}]{rate:.1f}%[/]",
            f"[dim]{avgms:.0f}[/]",
        )
    return tbl


# ─── Per-module table ──────────────────────────────────────────────────────

def render_module_table(st: Stats) -> Table:
    mods: dict[str, dict] = {}
    for r in st.results:
        k = r.module_stem
        if k not in mods:
            mods[k] = dict(tier=r.tier, total=0, passed=0,
                           failed=0, skipped=0, dur=0.0)
        mods[k]["total"]  += 1
        mods[k]["dur"]    += r.duration
        if r.passed:  mods[k]["passed"]  += 1
        if r.failed:  mods[k]["failed"]  += 1
        if r.skipped: mods[k]["skipped"] += 1

    tbl = Table(
        title="[muted]Per-Module[/]", title_justify="left",
        box=box.ROUNDED, border_style="border",
        show_header=True, header_style="bold dim",
        padding=(0, 2), expand=True,
    )
    tbl.add_column("Module",    min_width=26, overflow="fold")
    tbl.add_column("Tier",      width=6,  no_wrap=True)
    tbl.add_column("n",         width=5,  justify="center")
    tbl.add_column("✔",         width=5,  justify="center")
    tbl.add_column("✘",         width=5,  justify="center")
    tbl.add_column("Total ms",  width=10, justify="right")
    tbl.add_column("Status",    width=10, justify="center")

    for name, d in sorted(mods.items()):
        ts  = _tier_style(d["tier"])
        tl  = _tier_label(d["tier"])
        f   = d["failed"]
        fc  = "bad" if f else "muted"
        ok  = "[pass]✔ PASS[/]" if f == 0 else "[fail]✘ FAIL[/]"
        ms  = d["dur"] * 1000
        tbl.add_row(
            f"[hdr]{name}[/]",
            f"[{ts}]{tl}[/]",
            f"[dim]{d['total']}[/]",
            f"[good]{d['passed']}[/]",
            f"[{fc}]{f}[/]",
            f"[dim]{ms:.0f}[/]",
            ok,
        )
    return tbl


# ─── Slowest tests ─────────────────────────────────────────────────────────

def render_slowest(results: list[TResult], n: int = 10) -> Table:
    top = sorted(results, key=lambda r: r.duration, reverse=True)[:n]
    max_d = top[0].duration if top else 1.0

    tbl = Table(
        title=f"[muted]Slowest {n} Tests[/]", title_justify="left",
        box=box.ROUNDED, border_style="border",
        show_header=True, header_style="bold dim",
        padding=(0, 2), expand=True,
    )
    tbl.add_column("#",    width=4,  justify="right", style="muted")
    tbl.add_column("Tier", width=6,  no_wrap=True)
    tbl.add_column("Test", min_width=48, overflow="fold")
    tbl.add_column("Time", width=10, justify="right")
    tbl.add_column("Bar",  width=18, no_wrap=True)

    for i, r in enumerate(top, 1):
        ts    = _tier_style(r.tier)
        tl    = _tier_label(r.tier)
        tc    = _time_col(r.duration)
        fill  = int(r.duration / max_d * 14)
        bar   = f"[{tc}]{'█' * fill}[/][muted]{'░' * (14 - fill)}[/]"
        tbl.add_row(
            str(i),
            f"[{ts}]{tl}[/]",
            f"[dim]{escape(r.short_name[:68])}[/]",
            f"[{tc}]{r.duration:.3f}s[/]",
            bar,
        )
    return tbl


# ─── Failure detail ────────────────────────────────────────────────────────

def render_failures(results: list[TResult]) -> None:
    failures = [r for r in results if r.failed]
    if not failures:
        return

    con.print()
    con.rule(
        f"[bold bad] ✘  {len(failures)} Failure{'s' if len(failures) != 1 else ''} [/]",
        style="bad", align="left",
    )
    con.print()

    tbl = Table(
        box=box.SIMPLE_HEAD, border_style="border",
        show_header=True, header_style="bold dim",
        padding=(0, 1), expand=True,
    )
    tbl.add_column("",       width=3,  no_wrap=True)
    tbl.add_column("Tier",   width=6,  no_wrap=True)
    tbl.add_column("Module", width=22, no_wrap=True, overflow="fold")
    tbl.add_column("Test",   min_width=40, overflow="fold")
    tbl.add_column("ms",     width=8,  justify="right")
    tbl.add_column("Reason", min_width=30, overflow="fold")

    for r in failures:
        ts  = _tier_style(r.tier)
        tl  = _tier_label(r.tier)
        reason = escape(r.longrepr[:90]) if r.longrepr else "—"
        tbl.add_row(
            "[fail]✘[/]",
            f"[{ts}]{tl}[/]",
            f"[dim]{escape(r.module_stem[:22])}[/]",
            f"[fail]{escape(r.short_name[:60])}[/]",
            f"[dim]{r.duration * 1000:.0f}[/]",
            f"[dim]{reason}[/]",
        )
    con.print(tbl)


# ─── Invariant matrix ──────────────────────────────────────────────────────

_INVS = [
    ("INV-1", "split_sum == expense.amount  (zero tolerance, Decimal)",
     "SPLIT_SUM_MISMATCH 422",
     "test_split_sum_invariant · test_expenses · test_expense_edit"),
    ("INV-2", "Σ(member balances) == 0.00 for every group",
     "balance_sum assertion → 500",
     "test_compute_balances · test_balances"),
    ("INV-3", "Overpayment → warn but record  (pre-payment is valid)",
     "OVERPAYMENT warning · 201",
     "test_settlements"),
    ("INV-4", "paid_by_user_id ≠ paid_to_user_id",
     "SELF_SETTLEMENT 422",
     "test_settlements"),
    ("INV-5", "Payer must be a current group member",
     "PAYER_NOT_MEMBER 422",
     "test_expenses"),
    ("INV-6", "Every split user must be a current group member",
     "SPLIT_USER_NOT_MEMBER 422",
     "test_expenses"),
    ("INV-7", "Amounts: Decimal · strictly > 0 · max 2 decimal places",
     "INVALID_AMOUNT_PRECISION 400",
     "test_validation_schemas · test_expenses"),
    ("INV-8", "deleted_at IS NOT NULL → excluded from all balance queries",
     "soft-delete filter (WHERE deleted_at IS NULL)",
     "test_expense_delete · test_balances"),
    ("INV-9", "Only authenticated group members may read/write group data",
     "FORBIDDEN 403  (not 404)",
     "test_expenses · test_balances · test_settlements"),
]


def render_invariant_matrix(st: Stats) -> Table:
    ran = {r.module_stem for r in st.results}

    tbl = Table(
        title="[muted]Invariant Coverage[/]", title_justify="left",
        box=box.ROUNDED, border_style="border",
        show_header=True, header_style="bold dim",
        padding=(0, 2), expand=True,
    )
    tbl.add_column("Inv",   width=7,  no_wrap=True)
    tbl.add_column("Rule",  min_width=44, overflow="fold")
    tbl.add_column("Error", width=30, no_wrap=True)
    tbl.add_column("Files", min_width=36, overflow="fold")
    tbl.add_column("",      width=10, justify="center")

    for inv, rule, code, files in _INVS:
        related = [f.strip() for f in files.split("·")]
        covered = any(f in ran for f in related)
        status  = "[pass]● covered[/]" if covered else "[warn]○ not run[/]"
        tbl.add_row(
            f"[inv]{inv}[/]",
            f"[dim]{rule}[/]",
            f"[accent]{code}[/]",
            f"[muted]{files}[/]",
            status,
        )
    return tbl


# ─── Coverage ─────────────────────────────────────────────────────────────

def render_coverage(raw: str) -> None:
    lines = raw.splitlines()
    rows: list[tuple] = []
    in_table = False

    for line in lines:
        s = line.strip()
        if "Name" in s and "Stmts" in s and "Miss" in s:
            in_table = True
            continue
        if in_table:
            if s.startswith(("-", "=")):
                continue
            if not s:
                in_table = False
                continue
            parts = s.split()
            if len(parts) >= 4:
                try:
                    rows.append((
                        parts[0], int(parts[1]), int(parts[2]),
                        float(parts[3].replace("%", "")),
                        " ".join(parts[4:]),
                    ))
                except (ValueError, IndexError):
                    pass

    if not rows:
        return

    con.print()
    con.rule("[muted]Coverage Report[/]", style="border")
    con.print()

    tbl = Table(
        box=box.ROUNDED, border_style="border",
        show_header=True, header_style="bold dim",
        padding=(0, 2), expand=True,
    )
    tbl.add_column("Module",   min_width=38, overflow="fold")
    tbl.add_column("Stmts",    width=8,  justify="right")
    tbl.add_column("Miss",     width=8,  justify="right")
    tbl.add_column("Coverage", width=14, justify="right")
    tbl.add_column("Bar",      width=24, no_wrap=True)
    tbl.add_column("Missing",  min_width=14, overflow="fold")

    REQUIRED = 90.0
    for name, stmts, miss, pct, missing in rows:
        rc    = "good" if pct >= REQUIRED else "warn" if pct >= 70 else "bad"
        mc    = "bad"  if miss > 0 else "muted"
        fill  = int(pct / 100 * 20)
        bar   = f"[{rc}]{'█' * fill}[/][muted]{'░' * (20 - fill)}[/]"
        note  = ""
        if any(k in name for k in ("service", "schema")) and pct < REQUIRED:
            note = f"  [bad]⚠ <{REQUIRED:.0f}%[/]"
        short = name.replace("app/", "").replace(".py", "")
        tbl.add_row(
            f"[dim]{escape(short)}[/]",
            f"[dim]{stmts}[/]",
            f"[{mc}]{miss}[/]",
            f"[{rc}]{pct:.0f}%[/]" + note,
            bar,
            f"[dim]{escape(missing[:28])}[/]" if missing else "",
            )

    con.print(tbl)

    # Overall summary
    totals = [r for r in rows if r[0].upper() in ("TOTAL", "COVERED")]
    if totals:
        pct = totals[-1][3]
        rc  = _rate_col(pct)
        con.print(
            f"\n  [dim]Overall coverage:[/]  [{rc}]{pct:.1f}%[/]"
            f"  [dim](≥{REQUIRED:.0f}% required on services + schemas — GUIDE §6)[/]"
        )


# ─── Final verdict ─────────────────────────────────────────────────────────

def render_verdict(st: Stats, ok: bool | None = None) -> None:
    con.print()
    passed = st.ok if ok is None else ok
    if passed:
        con.print(Panel(
            Align.center(Text.assemble(
                ("\n", ""),
                ("  ✔  ALL TESTS PASSED  ", "bold bright_green"),
                ("\n\n", ""),
                (f"  {st.total} tests  ·  {_fmt_time(st.elapsed)}  ·  100% pass rate  ", "dim"),
                ("\n", ""),
            )),
            border_style="bright_green", padding=(0, 4),
        ))
    else:
        fc = f"{st.failed} failure{'s' if st.failed != 1 else ''}"
        con.print(Panel(
            Align.center(Text.assemble(
                ("\n", ""),
                ("  ✘  BUILD FAILED  ", "bold bright_red"),
                ("\n\n", ""),
                (f"  {fc}  ·  {st.rate:.1f}% pass rate  ·  {_fmt_time(st.elapsed)}  ", "dim"),
                ("\n", ""),
            )),
            border_style="bright_red", padding=(0, 4),
        ))
    con.print()


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN RUNNER
# ═══════════════════════════════════════════════════════════════════════════

def run(
        unit_only:    bool = False,
        integration_only: bool = False,
        fail_fast:    bool = False,
        with_coverage: bool = False,
        keyword:      str  = "",
        extra:        list[str] | None = None,
) -> int:

    mode = ("Unit only"        if unit_only
            else "Integration" if integration_only
    else "Full suite")

    paths = (["tests/unit"]        if unit_only
             else ["tests/integration"] if integration_only
    else ["tests/unit", "tests/integration"])

    # ── Banner ────────────────────────────────────────────────────────────
    render_banner(mode, with_coverage)

    # ── Build pytest args ─────────────────────────────────────────────────
    pytest_args = [*paths, "--tb=short", "-q"]
    if fail_fast:    pytest_args.append("-x")
    if keyword:      pytest_args += ["-k", keyword]
    if with_coverage:
        pytest_args += [
            "--cov=app.services",
            "--cov=app.schemas",
            "--cov-fail-under=90",
            "--cov-report=",
        ]
    if extra:
        pytest_args += extra

    # ── Live progress + dot stream ────────────────────────────────────────
    stream = Text("        ", overflow="fold", no_wrap=False)

    progress = Progress(
        # Use ASCII spinner to avoid cp1252 encoding crashes on some
        # Windows PowerShell terminals.
        SpinnerColumn("line", style="accent"),
        TextColumn(" [dim]{task.description}[/]"),
        BarColumn(bar_width=32, style="muted", complete_style="accent"),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=con, transient=False, expand=False,
    )
    task_id = progress.add_task("running tests", total=None)

    collector = Collector(stream, progress, task_id)

    layout = Group(
        Rule("[muted]Executing[/]", style="border"),
        Padding(stream, (1, 2)),
        progress,
    )

    con.print()
    t0 = time.perf_counter()

    with Live(layout, console=con, refresh_per_second=20, transient=True) as live:
        collector._live = live
        pytest_exit_code = pytest.main(pytest_args, plugins=[collector])

    elapsed = time.perf_counter() - t0
    st      = Stats(results=collector.results, elapsed=elapsed)

    # ── Render ────────────────────────────────────────────────────────────

    # 1. Dot stream (frozen after run)
    con.print()
    con.rule("[muted]Test Stream[/]", style="border")
    con.print()
    con.print(Padding(stream, (0, 2)))

    # 2. Metric cards
    con.print()
    con.rule("[muted]Metrics[/]", style="border")
    con.print()
    render_cards(st)

    # 3. Failures
    render_failures(st.results)

    # 4. Breakdown tables (tier + module, side-by-side)
    con.print()
    con.rule("[muted]Breakdown[/]", style="border")
    con.print()
    con.print(Columns(
        [render_tier_table(st), render_module_table(st)],
        equal=False, expand=True, padding=(0, 1),
    ))

    # 5. Slowest + invariant matrix (side-by-side)
    con.print()
    con.print(Columns(
        [render_slowest(st.results), render_invariant_matrix(st)],
        equal=False, expand=True, padding=(0, 1),
    ))

    # 6. Coverage (re-run to capture output cleanly)
    if with_coverage:
        cov_args = [
            sys.executable, "-m", "pytest",
            *paths,
            "--cov=app.services", "--cov=app.schemas",
            "--cov-fail-under=90",
            "--cov-report=term-missing",
            "-q", "--tb=no",
        ]
        if keyword:
            cov_args += ["-k", keyword]
        raw = subprocess.run(cov_args, capture_output=True, text=True)
        render_coverage(raw.stdout + raw.stderr)

    run_ok = (st.ok and pytest_exit_code == 0)

    if with_coverage and pytest_exit_code != 0 and st.failed == 0:
        con.print(
            "\n  [warn]Coverage gate failed[/] "
            "[dim](required: --cov-fail-under=90).[/]"
        )

    # 7. Verdict
    render_verdict(st, ok=run_ok)

    return 0 if run_ok else 1


# ═══════════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════════

def _cli() -> None:
    ap = argparse.ArgumentParser(
        prog="python utils/test_run.py",
        description="SplitLedger — pretty test runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python utils/test_run.py
  python utils/test_run.py --unit
  python utils/test_run.py --integration
  python utils/test_run.py --coverage
  python utils/test_run.py --unit --coverage
  python utils/test_run.py -x
  python utils/test_run.py -k balance
        """,
    )
    ap.add_argument("--unit",        action="store_true",
                    help="Unit tests only  (tests/unit/)")
    ap.add_argument("--integration", action="store_true",
                    help="Integration tests only  (tests/integration/)")
    ap.add_argument("--coverage",    action="store_true",
                    help="Show coverage report  (needs pytest-cov)")
    ap.add_argument("-x", "--fail-fast", action="store_true",
                    help="Stop after first failure")
    ap.add_argument("-k", metavar="EXPR", default="",
                    help="Filter tests by expression  (passed to pytest -k)")
    args, remainder = ap.parse_known_args()

    if args.unit and args.integration:
        con.print("[warn]⚠[/]  [dim]--unit and --integration are mutually exclusive — running full suite.[/]\n")
        args.unit = args.integration = False

    # Always run from backend/
    root = Path(__file__).resolve().parent.parent
    os.chdir(root)

    if not (root / "tests").exists():
        con.print(Panel(
            "[bad]Cannot locate tests/ directory.[/]\n"
            "[dim]Place this script at  backend/utils/test_run.py\n"
            "and run it from the repository root.[/]",
            title="[bad]Path Error[/]", border_style="red",
        ))
        sys.exit(1)

    sys.exit(run(
        unit_only=args.unit,
        integration_only=args.integration,
        fail_fast=args.fail_fast,
        with_coverage=args.coverage,
        keyword=args.k,
        extra=remainder,
    ))


if __name__ == "__main__":
    _cli()
