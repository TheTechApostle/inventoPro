"""
TenantService — all business logic for tenant creation and management.
"""
import logging
from django.db import transaction
from django.utils import timezone
from datetime import timedelta
from core.exceptions import PlanLimitExceededException

logger = logging.getLogger("inventra.tenants")


class TenantService:

    @classmethod
    @transaction.atomic
    def create_tenant_with_owner(
        cls,
        *,
        name: str,
        business_type: str,
        country: str,
        currency: str,
        owner_email: str,
        owner_password: str,
        owner_first_name: str,
        owner_last_name: str,
    ):
        """
        Full tenant onboarding:
        1. Create User (owner)
        2. Create Tenant
        3. Create default Role (owner)
        4. Create TenantMembership
        5. Create TenantSettings
        6. Create default Warehouse
        Returns (tenant, user)
        """
        from apps.accounts.models import User, Role, TenantMembership
        from apps.tenants.models import Tenant, TenantSettings
        from apps.warehouses.models import Warehouse
        from core.permissions import ROLE_PERMISSIONS

        # 1. Create owner user
        user = User.objects.create_user(
            email=owner_email,
            password=owner_password,
            first_name=owner_first_name,
            last_name=owner_last_name,
        )
        logger.info(f"[TENANT] Created owner user: {owner_email}")

        # 2. Create tenant
        tenant = Tenant.objects.create(
            name=name,
            business_type=business_type,
            country=country,
            currency=currency,
            currency_symbol=cls._get_currency_symbol(currency),
            owner=user,
            plan="free",
            is_trial=True,
            plan_expires_at=timezone.now() + timedelta(days=14),
        )
        logger.info(f"[TENANT] Created tenant: {tenant.slug}")

        # 3. Default roles
        owner_role = Role.objects.create(
            tenant=tenant,
            name="owner",
            permissions=ROLE_PERMISSIONS["owner"],
            is_system_role=True,
        )
        for role_name, perms in ROLE_PERMISSIONS.items():
            if role_name != "owner":
                Role.objects.create(
                    tenant=tenant,
                    name=role_name,
                    permissions=perms,
                    is_system_role=True,
                )

        # 4. Membership
        TenantMembership.objects.create(
            user=user,
            tenant=tenant,
            role=owner_role,
        )

        # 5. Settings
        TenantSettings.objects.create(tenant=tenant)

        # 6. Default warehouse
        Warehouse.objects.create(
            tenant=tenant,
            name="Main Warehouse",
            code="MAIN",
            is_default=True,
        )

        logger.info(f"[TENANT] Onboarding complete for: {tenant.slug}")
        return tenant, user

    @staticmethod
    def _get_currency_symbol(currency: str) -> str:
        symbols = {
            "NGN": "₦", "USD": "$", "GBP": "£", "EUR": "€",
            "GHS": "₵", "KES": "KSh", "ZAR": "R", "EGP": "£E",
        }
        return symbols.get(currency, currency)

    @classmethod
    def check_plan_limit(cls, tenant, resource: str, current_count: int):
        """Raise PlanLimitExceededException if tenant is at limit."""
        limits = {
            "users": tenant.max_users,
            "products": tenant.max_products,
            "warehouses": tenant.max_warehouses,
        }
        limit = limits.get(resource)
        if limit and current_count >= limit:
            raise PlanLimitExceededException(
                f"You have reached the limit of {limit} {resource} on your plan.",
                detail={"resource": resource, "limit": limit, "current": current_count},
            )
