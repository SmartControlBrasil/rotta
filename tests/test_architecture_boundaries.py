import os
import ast
import pytest

def test_domain_imports_isolation():
    """Verify that domain modules in src/freights/domain do not import Django or infra/adapters."""
    domain_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../src/freights/domain"))

    for root, _, files in os.walk(domain_dir):
        for file in files:
            if file.endswith(".py") and file != "__init__.py":
                file_path = os.path.join(root, file)
                with open(file_path, "r", encoding="utf-8") as f:
                    tree = ast.parse(f.read(), filename=file_path)

                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            name = alias.name
                            assert not name.startswith("django"), (
                                f"Forbidden django import found in {file}: {name}"
                            )
                            assert "infrastructure" not in name, (
                                f"Forbidden infrastructure import found in {file}: {name}"
                            )
                            assert "interfaces" not in name, (
                                f"Forbidden interfaces import found in {file}: {name}"
                            )

                    elif isinstance(node, ast.ImportFrom):
                        module = node.module
                        if module:
                            assert not module.startswith("django"), (
                                f"Forbidden django import found in {file}: from {module} import ..."
                            )
                            assert "infrastructure" not in module, (
                                f"Forbidden infrastructure import found in {file}: from {module} import ..."
                            )
                            assert "interfaces" not in module, (
                                f"Forbidden interfaces import found in {file}: from {module} import ..."
                            )


def test_intelligence_domain_imports_isolation():
    """Verify that domain modules in src/intelligence/domain do not import Django or infra/adapters."""
    domain_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../src/intelligence/domain"))

    for root, _, files in os.walk(domain_dir):
        for file in files:
            if file.endswith(".py") and file != "__init__.py":
                file_path = os.path.join(root, file)
                with open(file_path, "r", encoding="utf-8") as f:
                    tree = ast.parse(f.read(), filename=file_path)

                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            name = alias.name
                            assert not name.startswith("django"), (
                                f"Forbidden django import found in {file}: {name}"
                            )
                            assert "infrastructure" not in name, (
                                f"Forbidden infrastructure import found in {file}: {name}"
                            )
                            assert "interfaces" not in name, (
                                f"Forbidden interfaces import found in {file}: {name}"
                            )

                    elif isinstance(node, ast.ImportFrom):
                        module = node.module
                        if module:
                            assert not module.startswith("django"), (
                                f"Forbidden django import found in {file}: from {module} import ..."
                            )
                            assert "infrastructure" not in module, (
                                f"Forbidden infrastructure import found in {file}: from {module} import ..."
                            )
                            assert "interfaces" not in module, (
                                f"Forbidden interfaces import found in {file}: from {module} import ..."
                            )
