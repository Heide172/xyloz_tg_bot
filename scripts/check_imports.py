#!/usr/bin/env python3
"""Статический чек внутренних импортов по именам — БЕЗ запуска и без зависимостей.

Для каждого `from services/handlers/common/worker/api import Name` проверяет, что
`Name` реально определён (def/async def/class/присваивание/импорт) в целевом
модуле или является его подмодулем. Ловит `ImportError: cannot import name ...`,
который `py_compile` НЕ видит (он резолвит только синтаксис), а бот падает на
старте (см. инцидент 2026-07-10 с удалённым is_tag_admin).

Запуск перед push:  python scripts/check_imports.py
Выход 1 при проблемах — годится для pre-push хука / CI.
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# базы поиска пакетов: bot/ (services, handlers) и корень (common, api, worker)
SEARCH = [os.path.join(ROOT, "bot"), ROOT]
INTERNAL = ("services", "handlers", "common", "worker", "api")
SKIP_DIRS = ("__pycache__", ".venv", "node_modules", ".git", "miniapp")


def module_file(mod: str):
    rel = mod.replace(".", "/")
    for base in SEARCH:
        for cand in (os.path.join(base, rel + ".py"), os.path.join(base, rel, "__init__.py")):
            if os.path.isfile(cand):
                return cand
    return None


def exported_names(path: str) -> set[str]:
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), path)
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                names.add(a.asname or a.name.split(".")[0])
    return names


def main() -> int:
    problems: list[str] = []
    for base in SEARCH:
        for dirpath, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                src = os.path.join(dirpath, fn)
                try:
                    with open(src, encoding="utf-8") as f:
                        tree = ast.parse(f.read(), src)
                except SyntaxError as e:
                    problems.append(f"{os.path.relpath(src, ROOT)}: SYNTAX {e}")
                    continue
                for node in ast.walk(tree):
                    if not isinstance(node, ast.ImportFrom) or node.level != 0 or not node.module:
                        continue
                    if node.module.split(".")[0] not in INTERNAL:
                        continue
                    target = module_file(node.module)
                    if target is None:
                        continue  # внешний/неразрешимый — пропускаем
                    exp = exported_names(target)
                    for a in node.names:
                        if a.name == "*":
                            continue
                        if module_file(node.module + "." + a.name) is not None:
                            continue  # submodule-импорт
                        if a.name not in exp:
                            problems.append(
                                f"{os.path.relpath(src, ROOT)}:{node.lineno} "
                                f"импортирует '{a.name}' из '{node.module}' — НЕ НАЙДЕНО"
                            )

    if problems:
        print("НАЙДЕНЫ ПРОБЛЕМЫ ИМПОРТОВ:")
        for p in problems:
            print("  -", p)
        return 1
    print("OK: все внутренние импорты по именам резолвятся")
    return 0


if __name__ == "__main__":
    sys.exit(main())
