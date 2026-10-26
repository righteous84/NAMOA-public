"""Secret storage boundary (Sprint 15)."""

import json
import os
import re
import sys
import tempfile
from abc import ABC, abstractmethod


class SecretStoreError(Exception):
    """Base error for secret store failures."""


class SecretStoreUnavailableError(SecretStoreError):
    """A secret store backend cannot be used."""


class SecretStore(ABC):
    """Abstract secret store boundary."""

    source_label = "unknown"

    @abstractmethod
    def store(self, service, account, secret):
        """Persist a secret."""

    @abstractmethod
    def retrieve(self, service, account):
        """Return the secret string or None when absent."""

    @abstractmethod
    def delete(self, service, account):
        """Remove a stored secret when present."""

    @abstractmethod
    def exists(self, service, account):
        """Return True when a secret is stored."""


def _validate_identity(service, account):
    if not isinstance(service, str) or not service.strip():
        raise ValueError("service must be a non-empty string")
    if not isinstance(account, str) or not account.strip():
        raise ValueError("account must be a non-empty string")


class MemorySecretStore(SecretStore):
    """In-memory secret store for tests and local tooling."""

    source_label = "memory"

    def __init__(self):
        self._secrets = {}

    def store(self, service, account, secret):
        _validate_identity(service, account)
        if not isinstance(secret, str) or not secret:
            raise ValueError("secret must be a non-empty string")
        self._secrets[(service, account)] = secret

    def retrieve(self, service, account):
        _validate_identity(service, account)
        return self._secrets.get((service, account))

    def delete(self, service, account):
        _validate_identity(service, account)
        self._secrets.pop((service, account), None)

    def exists(self, service, account):
        _validate_identity(service, account)
        return (service, account) in self._secrets


def env_var_name(prefix, service, account):
    """Map a (service, account) pair to an env var name.

    Example: prefix "NAMOA_", service "namoa/jellyfin" and
    account "api_key" become "NAMOA_JELLYFIN_API_KEY".
    A leading service segment repeating the prefix stem is
    dropped so the prefix is never doubled.
    """

    if not isinstance(prefix, str) or not prefix.strip():
        raise ValueError("prefix must be a non-empty string")
    _validate_identity(service, account)
    stem = re.sub(r"[^A-Z0-9]+", "", prefix.upper())
    service_tokens = [
        token
        for token in re.split(r"[^A-Z0-9]+", service.upper())
        if token
    ]
    while service_tokens and service_tokens[0] == stem:
        service_tokens.pop(0)
    account_tokens = [
        token
        for token in re.split(r"[^A-Z0-9]+", account.upper())
        if token
    ]
    parts = [prefix.rstrip("_")]
    parts.extend(service_tokens)
    parts.extend(account_tokens)
    name = "_".join(part for part in parts if part)
    name = re.sub(r"_+", "_", name)
    return name


class EnvSecretStore(SecretStore):
    """Read-only environment variable secret store.

    The environment is operator managed, so store and delete
    are refused with an explanatory error.
    """

    source_label = "environment"

    def __init__(self, prefix="NAMOA_"):
        if not isinstance(prefix, str) or not prefix.strip():
            raise ValueError("prefix must be a non-empty string")
        self.prefix = prefix

    def _var(self, service, account):
        return env_var_name(self.prefix, service, account)

    def store(self, service, account, secret):
        _validate_identity(service, account)
        raise SecretStoreError(
            "environment secret store is read-only and "
            "operator-managed; set "
            + self._var(service, account)
            + " in the environment instead"
        )

    def retrieve(self, service, account):
        _validate_identity(service, account)
        return os.environ.get(self._var(service, account))

    def delete(self, service, account):
        _validate_identity(service, account)
        raise SecretStoreError(
            "environment secret store is read-only and "
            "operator-managed; unset "
            + self._var(service, account)
            + " in the environment instead"
        )

    def exists(self, service, account):
        _validate_identity(service, account)
        return self._var(service, account) in os.environ


class KeyringSecretStore(SecretStore):
    """OS keyring secret store with a lazily imported backend."""

    source_label = "keyring"

    def __init__(self, store_name="namoa"):
        if (
            not isinstance(store_name, str)
            or not store_name.strip()
        ):
            raise ValueError("store_name must be a non-empty string")
        self.store_name = store_name.strip()

    def _service_name(self, service):
        return self.store_name + "/" + str(service)

    @staticmethod
    def _load_keyring():
        try:
            import keyring
        except ImportError:
            raise SecretStoreUnavailableError(
                "keyring package is not installed; install it "
                "with: python3 -m pip install keyring, or set "
                "the documented NAMOA_<PROVIDER>_API_KEY "
                "environment override instead"
            )
        return keyring

    def store(self, service, account, secret):
        _validate_identity(service, account)
        if not isinstance(secret, str) or not secret:
            raise ValueError("secret must be a non-empty string")
        keyring = self._load_keyring()
        try:
            keyring.set_password(
                self._service_name(service), account, secret
            )
        except SecretStoreUnavailableError:
            raise
        except Exception as error:
            raise SecretStoreUnavailableError(
                "keyring backend failed while storing a secret "
                "for service account"
                ": " + type(error).__name__
            )

    def retrieve(self, service, account):
        _validate_identity(service, account)
        keyring = self._load_keyring()
        try:
            return keyring.get_password(
                self._service_name(service), account
            )
        except SecretStoreUnavailableError:
            raise
        except Exception as error:
            raise SecretStoreUnavailableError(
                "keyring backend failed while retrieving a "
                "secret: " + type(error).__name__
            )

    def delete(self, service, account):
        _validate_identity(service, account)
        keyring = self._load_keyring()
        try:
            try:
                keyring.delete_password(
                    self._service_name(service), account
                )
            except Exception as error:
                if type(error).__name__ in (
                    "PasswordDeleteError",
                    "PasswordNotFoundError",
                ):
                    return
                raise
        except SecretStoreUnavailableError:
            raise
        except Exception as error:
            raise SecretStoreUnavailableError(
                "keyring backend failed while deleting a "
                "secret: " + type(error).__name__
            )

    def exists(self, service, account):
        _validate_identity(service, account)
        value = self.retrieve(service, account)
        return value is not None


def resolve_secret(stores_in_order, service, account):
    """Try stores in order and return (value, source_label).

    Stores that are unavailable are skipped. The source label
    ("environment", "keyring", "memory", ...) is recorded
    without ever exposing the value. Returns (None, "") when
    no store holds the secret.
    """

    if not isinstance(stores_in_order, (list, tuple)):
        raise ValueError("stores_in_order must be a list or tuple")
    _validate_identity(service, account)
    for store in stores_in_order:
        if not isinstance(store, SecretStore):
            raise ValueError("stores must be SecretStore instances")
        try:
            value = store.retrieve(service, account)
        except SecretStoreUnavailableError:
            continue
        if value is not None:
            label = getattr(store, "source_label", "unknown")
            return value, str(label)
    return None, ""


def mask_secret(value):
    """Return a display placeholder that never reveals the secret."""

    if value:
        return "***"
    return ""


class CompositeSecretStore(SecretStore):
    """Ordered composite over multiple secret stores.

    Retrieve tries each store in order, skipping
    unavailable backends; the first held value wins,
    so listing the environment store first gives the
    documented deployment-override semantics. Store
    and delete fall through read-only stores to the
    first writable backend; when none can persist, the
    last error is raised. Exists is true when any
    reachable store holds the secret.
    """

    source_label = "composite"

    def __init__(self, stores):
        stores = list(stores or [])

        if not stores:
            raise ValueError("at least one store is required")

        for store in stores:
            if not isinstance(store, SecretStore):
                raise ValueError(
                    "stores must be SecretStore instances"
                )

        self._stores = stores

    def retrieve(self, service, account):
        _validate_identity(service, account)

        for store in self._stores:
            try:
                value = store.retrieve(service, account)
            except SecretStoreUnavailableError:
                continue

            if value is not None:
                return value

        return None

    def store(self, service, account, secret):
        _validate_identity(service, account)

        error = None

        for store in self._stores:
            try:
                store.store(service, account, secret)
                return
            except SecretStoreUnavailableError as current:
                error = current
                continue
            except SecretStoreError as current:
                error = current
                continue

        raise SecretStoreUnavailableError(
            "no writable secret store backend is "
            f"available: {error}"
        )

    def delete(self, service, account):
        _validate_identity(service, account)

        error = None

        for store in self._stores:
            try:
                store.delete(service, account)
                return
            except SecretStoreUnavailableError as current:
                error = current
                continue
            except SecretStoreError as current:
                error = current
                continue

        raise SecretStoreUnavailableError(
            "no writable secret store backend is "
            f"available: {error}"
        )

    def exists(self, service, account):
        _validate_identity(service, account)

        for store in self._stores:
            try:
                if store.exists(service, account):
                    return True
            except SecretStoreUnavailableError:
                continue

        return False


class LocalAppSecretStore(SecretStore):
    """File-backed local fallback secret store (Sprint 15).

    Used when the OS keyring is unavailable so GUI saves
    work with no extra install steps. Secrets live in a
    JSON object {service: {account: value}} in a file
    named secrets.json under a per-OS app directory:

    - Linux: $XDG_CONFIG_HOME/namoa/ else ~/.config/namoa/
    - Windows: %APPDATA%/NAMOA/
    - macOS: ~/Library/Application Support/NAMOA/
      (best effort via sys.platform detection)

    Writes are atomic (temp file plus os.replace).
    Directories are created with mode 0o700 and the file
    with mode 0o600 where supported; chmod failures never
    fail the operation. Values are never logged.
    """

    source_label = "local-app"

    FILENAME = "secrets.json"

    def __init__(self, directory=None):
        if directory is not None:
            if (
                not isinstance(directory, str)
                or not directory.strip()
            ):
                raise ValueError(
                    "directory must be a non-empty string"
                )
            self.directory = directory.strip()
        else:
            self.directory = self.default_directory()
        self.filename = self.FILENAME

    @staticmethod
    def default_directory():
        """Return the per-OS app directory (no side effects)."""
        platform = sys.platform
        home = os.path.expanduser("~")
        if platform.startswith("win"):
            appdata = os.environ.get("APPDATA")
            if appdata and appdata.strip():
                return os.path.join(
                    appdata.strip(), "NAMOA"
                )
            return os.path.join(home, "NAMOA")
        if platform == "darwin":
            return os.path.join(
                home,
                "Library",
                "Application Support",
                "NAMOA",
            )
        config_home = os.environ.get("XDG_CONFIG_HOME")
        if config_home and config_home.strip():
            return os.path.join(
                config_home.strip(), "namoa"
            )
        return os.path.join(home, ".config", "namoa")

    def _file_path(self):
        return os.path.join(self.directory, self.filename)

    def _read_all(self):
        path = self._file_path()
        try:
            with open(path, "r", encoding="utf-8") as handle:
                raw = handle.read()
        except FileNotFoundError:
            return {}
        except OSError as error:
            raise SecretStoreError(
                "local app secret store is unreadable: "
                + type(error).__name__
            )
        if not raw.strip():
            return {}
        try:
            data = json.loads(raw)
        except ValueError:
            raise SecretStoreError(
                "local app secret file is not valid JSON"
            )
        if not isinstance(data, dict):
            raise SecretStoreError(
                "local app secret file has an invalid shape"
            )
        return data

    def _write_all(self, data):
        try:
            os.makedirs(self.directory, mode=0o700, exist_ok=True)
        except OSError as error:
            raise SecretStoreError(
                "local app secret store directory cannot "
                "be created: " + type(error).__name__
            )
        try:
            os.chmod(self.directory, 0o700)
        except OSError:
            pass
        path = self._file_path()
        fd, tmp_path = tempfile.mkstemp(
            dir=self.directory, prefix=".secrets-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(data, indent=2, sort_keys=True)
                )
                handle.write("\n")
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except OSError:
                    pass
            try:
                os.chmod(tmp_path, 0o600)
            except OSError:
                pass
            os.replace(tmp_path, path)
        except OSError as error:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise SecretStoreError(
                "local app secret store write failed: "
                + type(error).__name__
            )
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def store(self, service, account, secret):
        _validate_identity(service, account)
        if not isinstance(secret, str) or not secret:
            raise ValueError("secret must be a non-empty string")
        data = self._read_all()
        services = data.get(service)
        if not isinstance(services, dict):
            services = {}
            data[service] = services
        services[account] = secret
        self._write_all(data)

    def retrieve(self, service, account):
        _validate_identity(service, account)
        data = self._read_all()
        services = data.get(service)
        if not isinstance(services, dict):
            return None
        value = services.get(account)
        if not isinstance(value, str) or not value:
            return None
        return value

    def delete(self, service, account):
        _validate_identity(service, account)
        data = self._read_all()
        services = data.get(service)
        if not isinstance(services, dict):
            return
        if account in services:
            del services[account]
            if not services:
                del data[service]
            self._write_all(data)

    def exists(self, service, account):
        _validate_identity(service, account)
        return self.retrieve(service, account) is not None
