"""Import every model so ``Base.metadata`` is complete (Alembic autogenerate, create_all)."""

from app.models.activity import (
    AuditEvent,
    ChangeRequest,
    ChangeRequestComment,
    CommandLog,
    SessionRecording,
    TacacsAuthEvent,
)
from app.models.configs import (
    ComplianceResult,
    ComplianceRule,
    ComplianceRun,
    ConfigBackup,
    ConfigIndexEntry,
    ConfigRestore,
    DeviceComplianceScore,
    DriftEvent,
    GoldenConfig,
    RancidConfig,
)
from app.models.identity import (
    ApiToken,
    Group,
    LoginHistory,
    Permission,
    RefreshToken,
    Role,
    RoleBinding,
    Tenant,
    User,
)
from app.models.inventory import (
    Credential,
    Device,
    DeviceGroup,
    DeviceModel,
    Link,
    Platform,
    Rack,
    Region,
    Site,
    Vendor,
)
from app.models.ops import (
    Alert,
    AlertChannel,
    AlertRule,
    ExternalObject,
    Integration,
    IxpMember,
    ReportSchedule,
    RouteServerClient,
)
from app.models.tacacs import (
    TacacsCommandPolicy,
    TacacsConfigRevision,
    TacacsDevice,
    TacacsPolicy,
    TacacsServer,
    TacacsUserMapping,
)

__all__ = [n for n in dir() if n[0].isupper()]
