"""
Permission classes for Inventra.

Permission codenames follow the pattern:  module.action
Examples:
    inventory.view, inventory.create, inventory.adjust
    sales.view, sales.create, sales.void
    products.view, products.create, products.delete
    finance.view, finance.create
    purchases.view, purchases.create, purchases.approve
    analytics.view
    users.manage
    settings.manage
"""
from rest_framework.permissions import BasePermission
import logging

logger = logging.getLogger("inventra.permissions")


class TenantPermission(BasePermission):
    """Request must have a resolved, active tenant."""
    message = "Tenant could not be determined. Include X-Tenant-Slug header."

    def has_permission(self, request, view):
        return (
            hasattr(request, "tenant")
            and request.tenant is not None
            and request.tenant.is_active
        )


class IsAuthenticated(BasePermission):
    """Standard auth check (re-exported for clean imports)."""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)


class BaseModulePermission(BasePermission):
    """
    Base for module-level permissions.
    Subclass and set required_permission = "module.action".
    Reads from JWT payload claims — zero DB hits.
    """
    required_permission: str = ""

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True
        perms = self._get_permissions(request)
        return self.required_permission in perms

    def _get_permissions(self, request) -> list:
        if request.auth and hasattr(request.auth, "payload"):
            return request.auth.payload.get("permissions", [])
        return []


# ── Auto-generated permission classes ───────────────────────────────────────

class CanViewInventory(BaseModulePermission):
    required_permission = "inventory.view"

class CanManageInventory(BaseModulePermission):
    required_permission = "inventory.create"

class CanAdjustStock(BaseModulePermission):
    required_permission = "inventory.adjust"

class CanViewProducts(BaseModulePermission):
    required_permission = "products.view"

class CanManageProducts(BaseModulePermission):
    required_permission = "products.create"

class CanViewSales(BaseModulePermission):
    required_permission = "sales.view"

class CanManageSales(BaseModulePermission):
    required_permission = "sales.create"

class CanVoidSales(BaseModulePermission):
    required_permission = "sales.void"

class CanViewPurchases(BaseModulePermission):
    required_permission = "purchases.view"

class CanManagePurchases(BaseModulePermission):
    required_permission = "purchases.create"

class CanApprovePurchases(BaseModulePermission):
    required_permission = "purchases.approve"

class CanViewFinance(BaseModulePermission):
    required_permission = "finance.view"

class CanManageFinance(BaseModulePermission):
    required_permission = "finance.create"

class CanViewAnalytics(BaseModulePermission):
    required_permission = "analytics.view"

class CanManageUsers(BaseModulePermission):
    required_permission = "users.manage"

class CanManageSettings(BaseModulePermission):
    required_permission = "settings.manage"


# ── Default permission sets per role ────────────────────────────────────────

ROLE_PERMISSIONS = {
    "owner": [
        "inventory.view", "inventory.create", "inventory.adjust",
        "products.view", "products.create", "products.delete",
        "sales.view", "sales.create", "sales.void",
        "purchases.view", "purchases.create", "purchases.approve",
        "finance.view", "finance.create",
        "analytics.view",
        "users.manage",
        "settings.manage",
    ],
    "manager": [
        "inventory.view", "inventory.create", "inventory.adjust",
        "products.view", "products.create",
        "sales.view", "sales.create",
        "purchases.view", "purchases.create", "purchases.approve",
        "finance.view",
        "analytics.view",
        "users.manage",
    ],
    "sales_rep": [
        "inventory.view",
        "products.view",
        "sales.view", "sales.create",
    ],
    "storekeeper": [
        "inventory.view", "inventory.create", "inventory.adjust",
        "products.view",
        "purchases.view",
    ],
    "accountant": [
        "finance.view", "finance.create",
        "analytics.view",
        "sales.view",
        "purchases.view",
    ],
    "cashier": [
        "inventory.view",
        "products.view",
        "sales.view", "sales.create",
    ],
    "viewer": [
        "inventory.view",
        "products.view",
        "sales.view",
        "analytics.view",
    ],
}
