"""Static checks for the Django modular-monolith boundaries."""

import ast
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
APPS_ROOT = REPO_ROOT / "apps"


def _application_import_graph():
    graph = {}
    for source in APPS_ROOT.rglob("*.py"):
        if {"tests", "migrations", "__pycache__"}.intersection(source.parts):
            continue
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        source_app = source.relative_to(APPS_ROOT).parts[0]
        targets = graph.setdefault(source_app, set())
        for statement in tree.body:
            if isinstance(statement, ast.Import):
                imports = [item.name for item in statement.names]
            elif isinstance(statement, ast.ImportFrom) and statement.module:
                imports = [statement.module]
            else:
                continue
            for imported in imports:
                if imported.startswith("apps."):
                    target_app = imported.split(".")[1]
                    if target_app != source_app:
                        targets.add(target_app)
    return graph


def _has_cycle(graph):
    visiting = set()
    visited = set()

    def visit(node):
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(visit(child) for child in graph.get(node, ())):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in graph)


class ModuleBoundaryTests(unittest.TestCase):
    def test_top_level_cross_app_imports_are_acyclic(self):
        self.assertFalse(_has_cycle(_application_import_graph()))

    def test_wallet_integration_does_not_import_another_product_app(self):
        wallet_root = APPS_ROOT / "wallet_integration"
        for source in wallet_root.rglob("*.py"):
            if "tests" in source.parts or "__pycache__" in source.parts:
                continue
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
            for statement in ast.walk(tree):
                if isinstance(statement, ast.Import):
                    imports = [item.name for item in statement.names]
                elif isinstance(statement, ast.ImportFrom) and statement.module:
                    imports = [statement.module]
                else:
                    continue
                self.assertFalse(
                    any(name.startswith("apps.") and name.split(".")[1] != "wallet_integration" for name in imports),
                    f"{source.relative_to(REPO_ROOT)} reaches into another app",
                )

    def test_status_reply_service_does_not_depend_on_http_views(self):
        source = APPS_ROOT / "status" / "replies.py"
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        imports = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        self.assertFalse(any((node.module or "").endswith("views") for node in imports))
