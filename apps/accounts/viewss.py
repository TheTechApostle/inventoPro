"""
Accounts views.
Authentication, user profile, team management, roles.
"""
from django.utils import timezone
from rest_framework import generics, viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken
from drf_spectacular.utils import extend_schema
from core.permissions import TenantPermission, CanManageUsers
from core.mixins import TenantQuerysetMixin
from .models import User, Role, TenantMembership, UserInvitation
from .serializers import (
    CustomTokenObtainPairSerializer,
    UserSerializer,
    UserUpdateSerializer,
    ChangePasswordSerializer,
    RoleSerializer,
    TenantMembershipSerializer,
    InviteUserSerializer,
)


class LoginView(TokenObtainPairView):
    """POST /api/v1/auth/login/ — returns JWT access + refresh tokens."""
    serializer_class = CustomTokenObtainPairSerializer

    @extend_schema(tags=["auth"])
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            response.data = {"success": True, **response.data}
        return response


class LogoutView(generics.GenericAPIView):
    """POST /api/v1/auth/logout/ — blacklist refresh token."""
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["auth"])
    def post(self, request):
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return Response(
                {"success": False, "error": {"message": "Refresh token required."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except Exception:
            pass  # Already blacklisted or invalid — no-op
        return Response({"success": True, "message": "Logged out successfully."})


class MeView(generics.RetrieveUpdateAPIView):
    """GET/PATCH /api/v1/auth/me/ — current user profile."""
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user

    def get_serializer_class(self):
        if self.request.method in ("PUT", "PATCH"):
            return UserUpdateSerializer
        return UserSerializer

    @extend_schema(tags=["auth"])
    def get(self, request, *args, **kwargs):
        return Response({
            "success": True,
            "data": UserSerializer(request.user).data,
        })

    @extend_schema(tags=["auth"])
    def patch(self, request, *args, **kwargs):
        serializer = UserUpdateSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"success": True, "data": UserSerializer(request.user).data})


class ChangePasswordView(generics.GenericAPIView):
    """POST /api/v1/auth/change-password/"""
    permission_classes = [IsAuthenticated]
    serializer_class = ChangePasswordSerializer

    @extend_schema(tags=["auth"])
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save(update_fields=["password"])
        return Response({"success": True, "message": "Password updated successfully."})


class RoleViewSet(TenantQuerysetMixin, viewsets.ModelViewSet):
    """CRUD for tenant roles. GET/POST/PATCH/DELETE /api/v1/auth/roles/"""
    serializer_class = RoleSerializer
    permission_classes = [IsAuthenticated, TenantPermission, CanManageUsers]
    queryset = Role.objects.all()

    def get_queryset(self):
        return Role.objects.filter(tenant=self.request.tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_system_role:
            return Response(
                {"success": False, "error": {"message": "System roles cannot be deleted."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        instance.delete()
        return Response({"success": True, "message": "Role deleted."})

    @extend_schema(tags=["auth"])
    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        return Response({"success": True, "data": RoleSerializer(qs, many=True).data})


class TeamViewSet(viewsets.ViewSet):
    """
    Team management: list members, update roles, invite, remove.
    All under /api/v1/auth/team/
    """
    permission_classes = [IsAuthenticated, TenantPermission]

    @extend_schema(tags=["auth"])
    def list(self, request):
        """GET /api/v1/auth/team/ — list all tenant members."""
        memberships = TenantMembership.objects.filter(
            tenant=request.tenant, is_active=True
        ).select_related("user", "role", "branch")
        return Response({
            "success": True,
            "data": TenantMembershipSerializer(memberships, many=True).data,
        })

    @action(detail=False, methods=["post"], permission_classes=[IsAuthenticated, TenantPermission, CanManageUsers])
    @extend_schema(tags=["auth"])
    def invite(self, request):
        """POST /api/v1/auth/team/invite/ — invite a user by email."""
        serializer = InviteUserSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        from apps.accounts.services import AccountService
        invitation = AccountService.invite_user(
            tenant=request.tenant,
            email=d["email"],
            role_id=d["role_id"],
            invited_by=request.user,
        )
        return Response({
            "success": True,
            "message": f"Invitation sent to {invitation.email}.",
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["patch"], permission_classes=[IsAuthenticated, TenantPermission, CanManageUsers])
    @extend_schema(tags=["auth"])
    def update_role(self, request, pk=None):
        """PATCH /api/v1/auth/team/{id}/update_role/"""
        membership = TenantMembership.objects.filter(
            id=pk, tenant=request.tenant
        ).first()
        if not membership:
            return Response({"success": False, "error": {"message": "Member not found."}}, status=404)

        role_id = request.data.get("role_id")
        role = Role.objects.filter(id=role_id, tenant=request.tenant).first()
        if not role:
            return Response({"success": False, "error": {"message": "Role not found."}}, status=404)

        membership.role = role
        membership.save(update_fields=["role", "updated_at"])
        return Response({"success": True, "message": "Role updated."})

    @action(detail=True, methods=["delete"], permission_classes=[IsAuthenticated, TenantPermission, CanManageUsers])
    @extend_schema(tags=["auth"])
    def remove(self, request, pk=None):
        """DELETE /api/v1/auth/team/{id}/remove/"""
        membership = TenantMembership.objects.filter(
            id=pk, tenant=request.tenant
        ).first()
        if not membership:
            return Response({"success": False, "error": {"message": "Member not found."}}, status=404)

        if membership.user == request.tenant.owner:
            return Response({"success": False, "error": {"message": "Cannot remove the owner."}}, status=400)

        membership.is_active = False
        membership.save(update_fields=["is_active", "updated_at"])
        return Response({"success": True, "message": "Member removed."})
