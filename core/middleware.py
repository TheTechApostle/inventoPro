"""
TenantMiddleware — resolves and binds tenant to every request.
Resolution order:
  1. X-Tenant-Slug request header (API / mobile clients)
  2. Subdomain  e.g. acme.inventra.io → slug=acme
  3. None  (public routes: /admin/, /api/v1/tenants/register/)
"""
import logging
from django.conf import settings
from core.managers import set_current_tenant, clear_current_tenant

logger = logging.getLogger("inventra.middleware")

TENANT_EXEMPT_PATHS = [
    "/admin/",
    "/api/v1/auth/register/",
    "/api/v1/tenants/register/",
    "/api/v1/schema/",
    "/api/v1/docs/",
    "/api/v1/redoc/",
]


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if any(request.path.startswith(p) for p in TENANT_EXEMPT_PATHS):
            request.tenant = None
            response = self.get_response(request)
            return response

        tenant = self._resolve_tenant(request)
        set_current_tenant(tenant)
        request.tenant = tenant

        if tenant is None:
            logger.debug(f"No tenant resolved for path: {request.path}")

        try:
            response = self.get_response(request)
        finally:
            clear_current_tenant()

        return response

    def _resolve_tenant(self, request):
        from apps.tenants.models import Tenant

        # 1. Header
        slug = request.headers.get("X-Tenant-Slug", "").strip().lower()
        if slug:
            tenant = Tenant.objects.filter(slug=slug, is_active=True).first()
            if tenant:
                return tenant
            logger.warning(f"Tenant header '{slug}' not found or inactive")

        # 2. Subdomain
        app_domain = getattr(settings, "APP_DOMAIN", "inventra.io")
        host = request.get_host().split(":")[0].lower()
        parts = host.split(".")
        if len(parts) >= 3 and host.endswith(app_domain):
            subdomain = parts[0]
            if subdomain not in ("www", "api", "app"):
                tenant = Tenant.objects.filter(subdomain=subdomain, is_active=True).first()
                if tenant:
                    return tenant

        return None