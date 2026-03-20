"""Service package."""

__all__ = [
    "AuthService",
    "ApiTokenService",
    "ProviderService",
    "ProviderAdminService",
    "ProviderConnectivityService",
    "ProviderModelDiscoveryService",
    "IntegrationTokenService",
    "FileService",
    "AuditService",
    "ExecutionService",
    "MetricsService",
    "UsageService",
]


def __getattr__(name: str):
    if name == "AuthService":
        from app.services.auth_service import AuthService

        return AuthService
    if name == "ApiTokenService":
        from app.services.token_service import ApiTokenService

        return ApiTokenService
    if name == "ProviderService":
        from app.services.provider_service import ProviderService

        return ProviderService
    if name == "ProviderAdminService":
        from app.services.provider_admin_service import ProviderAdminService

        return ProviderAdminService
    if name == "ProviderConnectivityService":
        from app.services.provider_connectivity_service import ProviderConnectivityService

        return ProviderConnectivityService
    if name == "ProviderModelDiscoveryService":
        from app.services.provider_model_discovery_service import ProviderModelDiscoveryService

        return ProviderModelDiscoveryService
    if name == "IntegrationTokenService":
        from app.services.integration_token_service import IntegrationTokenService

        return IntegrationTokenService
    if name == "FileService":
        from app.services.file_service import FileService

        return FileService
    if name == "AuditService":
        from app.services.audit_service import AuditService

        return AuditService
    if name == "ExecutionService":
        from app.services.execution_service import ExecutionService

        return ExecutionService
    if name == "MetricsService":
        from app.services.metrics_service import MetricsService

        return MetricsService
    if name == "UsageService":
        from app.services.usage_service import UsageService

        return UsageService
    raise AttributeError(name)
