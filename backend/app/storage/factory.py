"""Select a storage adapter from configuration.

The one place in the codebase that knows which concrete adapter exists. Every
other module depends on the :class:`~app.storage.base.ObjectStorage` protocol,
so adding a provider means adding a file and one branch here — no service,
route, or test changes.
"""

from __future__ import annotations

from app.core.config import StorageSettings
from app.core.exceptions import ConfigurationError
from app.core.logging import get_logger
from app.storage.base import ObjectStorage
from app.storage.local import LocalObjectStorage

log = get_logger(__name__)


def build_object_storage(settings: StorageSettings) -> ObjectStorage:
    """Construct the adapter named by ``STORAGE_BACKEND``.

    Called once at startup rather than per request. Adapters hold connection
    state that is expensive to rebuild, and a per-request factory would quietly
    turn one connection pool into one pool per concurrent request.

    Raises:
        ConfigurationError: If the configured backend has no implementation.
            Raised at startup, where it stops the process, rather than on the
            first upload, where it would be a 500 for a user.
    """
    if settings.backend == "local":
        log.info("storage.adapter_selected", backend="local", root=settings.local_path)
        return LocalObjectStorage(settings.local_path)

    # `StorageSettings.backend` is a Literal, so this is reachable only once
    # "s3" is accepted by config but before its adapter lands. Failing loudly
    # here is what prevents a deployment silently writing customer uploads to a
    # container's ephemeral disk.
    raise ConfigurationError(
        f"Storage backend '{settings.backend}' is configured but not implemented.",
        details={"backend": settings.backend},
    )
