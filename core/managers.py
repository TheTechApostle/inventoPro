"""
Tenant-aware manager.
Automatically scopes all querysets to the current tenant
stored in thread-local storage by TenantMiddleware.
"""
import threading
from django.db import models

_thread_locals = threading.local()


def get_current_tenant():
    """Return the tenant bound to the current request thread."""
    return getattr(_thread_locals, "tenant", None)


def set_current_tenant(tenant):
    """Bind a tenant to the current request thread."""
    _thread_locals.tenant = tenant


def clear_current_tenant():
    """Remove tenant binding — called after each request."""
    _thread_locals.tenant = None


class TenantAwareQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def for_tenant(self, tenant):
        return self.filter(tenant=tenant)


class TenantAwareManager(models.Manager):
    """
    Default manager for all TenantAwareModel subclasses.
    Auto-filters by tenant from thread-local context.
    """

    def get_queryset(self):
        qs = TenantAwareQuerySet(self.model, using=self._db)
        tenant = get_current_tenant()
        if tenant is not None:
            return qs.filter(tenant=tenant)
        return qs

    def unscoped(self):
        """
        Bypass tenant filter entirely.
        USE ONLY IN: management commands, migrations, admin, celery tasks.
        NEVER call from views or services unless you explicitly need cross-tenant access.
        """
        return TenantAwareQuerySet(self.model, using=self._db)

    def active(self):
        return self.get_queryset().filter(is_active=True)
