"""NetworkOps Manager API client.

>>> from networkops import NetworkOpsClient
>>> with NetworkOpsClient("https://nom.example.net", token="nomt_...") as nom:
...     for dev in nom.devices.iter(vendor="juniper"):
...         print(dev.hostname, dev.last_backup_status)
"""

__version__ = "0.1.0"

from networkops.client import NetworkOpsClient  # noqa: E402
from networkops.errors import (  # noqa: E402
    APIError,
    AuthenticationError,
    ConflictError,
    MFARequiredError,
    NetworkOpsError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ServerError,
    ValidationError,
)
from networkops.models import Page  # noqa: E402

__all__ = [
    "NetworkOpsClient",
    "Page",
    "APIError",
    "AuthenticationError",
    "ConflictError",
    "MFARequiredError",
    "NetworkOpsError",
    "NotFoundError",
    "PermissionDeniedError",
    "RateLimitError",
    "ServerError",
    "ValidationError",
    "__version__",
]
