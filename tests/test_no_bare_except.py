"""
Tests for Issue #36: eliminate bare ``except:`` clauses.

A bare ``except:`` also swallows ``BaseException`` (KeyboardInterrupt,
SystemExit), which hides bugs and blocks interrupts. Every handler should name
at least ``Exception``. This is enforced statically over the backend sources.
"""

import ast
import pathlib

import pytest

import proctap.backends as backends_pkg

BACKENDS_DIR = pathlib.Path(backends_pkg.__file__).parent
SOURCE_FILES = sorted(p.name for p in BACKENDS_DIR.glob("*.py"))


def _bare_except_lines(path: pathlib.Path) -> list[int]:
    tree = ast.parse(path.read_text())
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.ExceptHandler) and node.type is None
    ]


@pytest.mark.parametrize("filename", SOURCE_FILES)
def test_no_bare_except(filename):
    path = BACKENDS_DIR / filename
    assert _bare_except_lines(path) == [], (
        f"{filename} has bare 'except:' clause(s) at lines "
        f"{_bare_except_lines(path)}"
    )
