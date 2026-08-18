from __future__ import annotations

import ast
from pathlib import Path


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def test_domain_and_application_do_not_depend_on_sqlalchemy_or_infrastructure():
    roots = [Path("src/ctrl_v2/domain"), Path("src/ctrl_v2/application")]
    for root in roots:
        for source in root.rglob("*.py"):
            imports = _imports(source)
            assert not any(
                name == "sqlalchemy" or name.startswith("sqlalchemy.") for name in imports
            )
            assert not any(
                name == "ctrl_v2.infrastructure" or name.startswith("ctrl_v2.infrastructure.")
                for name in imports
            )
