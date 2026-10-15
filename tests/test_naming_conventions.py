"""Package functions are named with the repository's fixed verb vocabulary."""

import ast
from pathlib import Path
from typing import Final

PERMITTED_FUNCTION_VERBS: Final = frozenset(
    {"create", "delete", "update", "remove", "select", "insert", "rename"},
)
PACKAGE_SOURCE_DIRECTORY: Final = (
    Path(__file__).resolve().parents[1] / "src" / "safety_judge"
)


def select_module_level_function_names(module_path: Path) -> list[str]:
    syntax_tree = ast.parse(module_path.read_text(encoding="utf-8"))
    return [
        statement.name
        for statement in syntax_tree.body
        if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef)
    ]


def test_every_module_level_function_starts_with_a_permitted_verb() -> None:
    checked_names = 0
    offenders: list[str] = []
    for module_path in sorted(PACKAGE_SOURCE_DIRECTORY.glob("**/*.py")):
        for function_name in select_module_level_function_names(module_path):
            checked_names += 1
            first_word = function_name.lstrip("_").split("_", maxsplit=1)[0]
            if first_word not in PERMITTED_FUNCTION_VERBS:
                offenders.append(f"{module_path.name}: {function_name}")

    assert checked_names > 0, (
        f"no functions found under {PACKAGE_SOURCE_DIRECTORY}; the scan path is wrong"
    )
    assert not offenders, (
        "start these functions with one of "
        f"{sorted(PERMITTED_FUNCTION_VERBS)} (select/insert/delete/update/rename "
        f"for store IO, create/remove for in-memory work): {offenders}"
    )
