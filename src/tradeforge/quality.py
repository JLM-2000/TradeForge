"""Dependency-free quality and safety checks for the initial checkpoint."""

from __future__ import annotations

import ast
import compileall
import sqlite3
import sys
import tempfile
from pathlib import Path

from .config import (
    LIVE_READINESS_APPROVED,
    LIVE_TRADING_ENABLED,
    LIVE_ADAPTER_AVAILABLE,
    MYINVESTOR_LIVE_EXECUTION,
    TRADEFORGE_WITHDRAWALS_ENABLED,
)


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src" / "tradeforge"


def lint() -> list[str]:
    errors: list[str] = []
    if not compileall.compile_dir(str(SOURCE), quiet=1, force=True):
        errors.append("source compilation failed")
    for path in SOURCE.glob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            errors.append(f"{path}: {exc}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in {"selenium", "playwright"}:
                errors.append(f"{path}: prohibited browser automation import")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec"}:
                errors.append(f"{path}: dynamic code execution is prohibited")
    return errors


def typecheck() -> list[str]:
    # The M1 environment intentionally has no external type checker installed.
    # Compilation plus strict typed domain constructors is the reproducible gate
    # until mypy/pyright is added with the production dependency set.
    return [] if compileall.compile_dir(str(SOURCE), quiet=1, force=False) else ["typecheck compilation failed"]


def security() -> list[str]:
    errors: list[str] = []
    if LIVE_TRADING_ENABLED or LIVE_ADAPTER_AVAILABLE or LIVE_READINESS_APPROVED or MYINVESTOR_LIVE_EXECUTION or TRADEFORGE_WITHDRAWALS_ENABLED:
        errors.append("initial live, MyInvestor, or withdrawal capability is enabled")
    prohibited_terms = {"selenium", "playwright", "private endpoint", "session cookie"}
    for path in SOURCE.glob("*.py"):
        if path.name == "quality.py":
            continue
        content = path.read_text(encoding="utf-8").lower()
        for term in prohibited_terms:
            if term in content:
                errors.append(f"{path}: prohibited integration term present in executable source: {term}")
    return errors


def migrations() -> list[str]:
    errors: list[str] = []
    migration = ROOT / "migrations" / "001_initial.sql"
    try:
        with tempfile.NamedTemporaryFile(suffix=".db") as handle:
            connection = sqlite3.connect(handle.name)
            connection.executescript(migration.read_text(encoding="utf-8"))
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            required = {"ledger_events", "control_state", "owner_hard_limits", "orders", "tax_lots"}
            errors.extend(f"migration missing table: {name}" for name in sorted(required - tables))
            connection.close()
    except (OSError, sqlite3.Error) as exc:
        errors.append(f"migration failed: {exc}")
    return errors


def main(argv: list[str] | None = None) -> int:
    command = (argv or sys.argv[1:] or ["all"])[0]
    checks = {"lint": lint, "typecheck": typecheck, "security": security, "migrations": migrations}
    selected = checks if command == "all" else {command: checks[command]} if command in checks else {}
    if not selected:
        print(f"unknown quality check: {command}")
        return 2
    failures: list[str] = []
    for name, check in selected.items():
        result = check()
        if result:
            failures.extend(f"{name}: {message}" for message in result)
            print(f"{name}: FAIL")
        else:
            print(f"{name}: PASS")
    if failures:
        for failure in failures:
            print(f"- {failure}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
