from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import authenticate
from .models import User, Role, TenantMembership, UserInvitation


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Extends simplejwt's default serializer to embed tenant context in JWT.
    Requires X-Tenant-Slug header to be set.
    """

    def validate(self, attrs):
        # Standard validation (email + password)
        data = super().validate(attrs)

        request = self.context.get("request")
        tenant = getattr(request, "tenant", None)

        if not tenant:
            raise serializers.ValidationError(
                "Tenant not found. Please provide X-Tenant-Slug header."
            )

        # Check membership
        membership = self.user.memberships.filter(
            tenant=tenant, is_active=True
        ).select_related("role").first()

        if not membership:
            raise serializers.ValidationError(
                "You are not a member of this organisation."
            )

        # Inject into token payload
        access = self.get_token(self.user)
        access["tenant_id"] = str(tenant.id)
        access["tenant_slug"] = tenant.slug
        access["tenant_name"] = tenant.name
        access["role"] = membership.role.name
        access["permissions"] = membership.role.permissions

        data["access"] = str(access)
        data["user"] = {
            "id": str(self.user.id),
            "email": self.user.email,
            "name": self.user.get_full_name(),
            "role": membership.role.name,
        }
        data["tenant"] = {
            "id": str(tenant.id),
            "name": tenant.name,
            "slug": tenant.slug,
            "currency": tenant.currency,
            "currency_symbol": tenant.currency_symbol,
            "plan": tenant.plan,
        }
        return data


class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "email", "first_name", "last_name", "full_name",
            "phone", "avatar", "is_email_verified", "created_at",
        ]
        read_only_fields = ["id", "email", "is_email_verified", "created_at"]

    def get_full_name(self, obj):
        return obj.get_full_name()


class UserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "phone", "avatar"]


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True)

    def validate(self, data):
        if data["new_password"] != data["confirm_password"]:
            raise serializers.ValidationError("Passwords do not match.")
        return data

    def validate_old_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = [
            "id", "name", "display_name", "description",
            "permissions", "is_system_role", "created_at",
        ]
        read_only_fields = ["id", "is_system_role", "created_at"]


class TenantMembershipSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    role = RoleSerializer(read_only=True)
    role_id = serializers.UUIDField(write_only=True)

    class Meta:
        model = TenantMembership
        fields = [
            "id", "user", "role", "role_id",
            "branch", "is_active", "joined_at", "created_at",
        ]
        read_only_fields = ["id", "user", "joined_at", "created_at"]


class InviteUserSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role_id = serializers.UUIDField()

    def validate_email(self, value):
        return value.lower().strip()

    def validate_role_id(self, value):
        from apps.accounts.models import Role
        request = self.context.get("request")
        if not Role.objects.filter(id=value, tenant=request.tenant).exists():
            raise serializers.ValidationError("Role not found for this tenant.")
        return value
