#!/usr/bin/env python3
"""Fail when a class defines the same method name twice in pr_agent/ (the later definition silently wins).

A merge can leave a fork method and a newer upstream method of the same name in one class; the fork one,
defined later, shadows upstream's and breaks its callers. Decorated definitions (properties, overloads) are skipped.
"""
import ast
import sys
from pathlib import Path

found = 0
for path in sorted(Path("pr_agent").rglob("*.py")):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        seen = {}
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and not item.decorator_list:
                if item.name in seen:
                    found = 1
                    print(f"{path}:{item.lineno}: {node.name}.{item.name} redefines line {seen[item.name]}")
                seen[item.name] = item.lineno
sys.exit(found)
