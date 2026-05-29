import keyring
import keyring.errors

from pos.config import KEYRING_SERVICE

_USERNAME = "session_token"


class SessionStore:
    """Хранит PIN session_token в системном keyring (Keychain / Credential Manager / SecretService)."""

    @property
    def token(self) -> str | None:
        try:
            return keyring.get_password(KEYRING_SERVICE, _USERNAME)
        except keyring.errors.KeyringError:
            return None

    @token.setter
    def token(self, value: str | None) -> None:
        if value is None:
            try:
                keyring.delete_password(KEYRING_SERVICE, _USERNAME)
            except (keyring.errors.PasswordDeleteError, keyring.errors.KeyringError):
                pass
        else:
            keyring.set_password(KEYRING_SERVICE, _USERNAME, value)

    def clear(self) -> None:
        self.token = None
