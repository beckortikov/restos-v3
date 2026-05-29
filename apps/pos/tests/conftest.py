"""Общие фикстуры и подмена keyring на in-memory backend."""
import os

# Перед импортом keyring указываем «нет реального бэкенда» —
# это нужно, чтобы тесты на CI/без графики не дёргали системный keychain.
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.fail.Keyring")

import keyring
import pytest
from keyring.backend import KeyringBackend


class _MemKeyring(KeyringBackend):
    """In-memory backend для тестов: ничего не лезет в систему."""

    priority = 1
    _store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self._store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self._store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self._store.pop((service, username), None)


@pytest.fixture(autouse=True)
def _mem_keyring():
    keyring.set_keyring(_MemKeyring())
    _MemKeyring._store.clear()
    yield
    _MemKeyring._store.clear()
