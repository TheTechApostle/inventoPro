"""
Accounts models.
Custom User, Role, TenantMembership.
"""
import uuid
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.db import models
from django.utils import timezone
from core.models import BaseModel


class UserManager(BaseUserManager):
    def create_user(self, email: str, password: str = None, **extra_fields):
        if not email:
            raise ValueError("Email is required.")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """
    Platform-level user.
    A single user can be a member of multiple tenants.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True, db_index=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=30, blank=True)
    avatar = models.ImageField(upload_to="avatars/%Y/", null=True, blank=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_email_verified = models.BooleanField(default=False)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    objects = UserManager()

    class Meta:
        db_table = "users"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_full_name()} <{self.email}>"

    def get_full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def get_membership(self, tenant):
        return self.memberships.filter(tenant=tenant, is_active=True).first()


class Role(BaseModel):
    """
    Tenant-scoped role.
    Permissions are a list of codenames stored as JSON array.
    Example: ["inventory.view", "sales.create"]
    """
    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        related_name="roles",
    )
    name = models.CharField(max_length=100)
    display_name = models.CharField(max_length=150, blank=True)
    description = models.TextField(blank=True)
    permissions = models.JSONField(default=list)
    is_system_role = models.BooleanField(default=False)

    class Meta:
        db_table = "roles"
        unique_together = [("tenant", "name")]
        ordering = ["name"]

    def __str__(self):
        return f"{self.tenant.slug} / {self.name}"

    def has_permission(self, codename: str) -> bool:
        return codename in self.permissions


class TenantMembership(BaseModel):
    """
    Links a User to a Tenant with a Role.
    A user can have memberships in multiple tenants.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="memberships")
    branch = models.ForeignKey(
        "warehouses.Branch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="If null, user has access to all branches",
    )
    invited_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invited_members",
    )
    joined_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "tenant_memberships"
        unique_together = [("user", "tenant")]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.email} @ {self.tenant.slug} [{self.role.name}]"


class UserInvitation(BaseModel):
    """Pending invitations to join a tenant."""
    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.CASCADE, related_name="invitations"
    )
    email = models.EmailField(db_index=True)
    role = models.ForeignKey(Role, on_delete=models.PROTECT)
    invited_by = models.ForeignKey(User, on_delete=models.CASCADE)
    token = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "user_invitations"

    @property
    def is_expired(self) -> bool:
        return timezone.now() > self.expires_at

    @property
    def is_accepted(self) -> bool:
        return self.accepted_at is not None
