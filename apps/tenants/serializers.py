from rest_framework import serializers
from .models import Tenant, TenantSettings


class TenantSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = TenantSettings
        exclude = ["id", "tenant", "created_at", "updated_at", "is_active"]


class TenantSerializer(serializers.ModelSerializer):
    settings = TenantSettingsSerializer(read_only=True)
    is_plan_active = serializers.BooleanField(read_only=True)
    plan_limits = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = [
            "id", "name", "slug", "subdomain", "custom_domain",
            "business_type", "plan", "is_trial", "plan_expires_at",
            "is_plan_active", "plan_limits",
            "logo", "primary_color", "secondary_color",
            "currency", "currency_symbol", "timezone", "country",
            "default_tax_rate",
            "feature_pos", "feature_manufacturing",
            "feature_ecommerce", "feature_multi_currency",
            "onboarding_complete", "onboarding_step",
            "settings", "created_at",
        ]
        read_only_fields = ["id", "slug", "subdomain", "created_at"]

    def get_plan_limits(self, obj):
        return obj.get_plan_limits()


class TenantRegisterSerializer(serializers.ModelSerializer):
    """Used during sign-up / onboarding."""
    owner_email = serializers.EmailField(write_only=True)
    owner_password = serializers.CharField(write_only=True, min_length=8)
    owner_first_name = serializers.CharField(write_only=True)
    owner_last_name = serializers.CharField(write_only=True)

    class Meta:
        model = Tenant
        fields = [
            "name", "business_type", "country", "currency",
            "owner_email", "owner_password",
            "owner_first_name", "owner_last_name",
        ]

    def validate_owner_email(self, value):
        from apps.accounts.models import User
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def create(self, validated_data):
        from apps.tenants.services import TenantService
        return TenantService.create_tenant_with_owner(
            name=validated_data["name"],
            business_type=validated_data.get("business_type", "retail"),
            country=validated_data.get("country", "Nigeria"),
            currency=validated_data.get("currency", "NGN"),
            owner_email=validated_data["owner_email"],
            owner_password=validated_data["owner_password"],
            owner_first_name=validated_data["owner_first_name"],
            owner_last_name=validated_data["owner_last_name"],
        )


class TenantUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = [
            "name", "business_type", "logo", "primary_color", "secondary_color",
            "currency", "currency_symbol", "timezone", "country",
            "default_tax_rate", "registration_number", "tax_number",
        ]
