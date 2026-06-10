import logging
from django.utils import timezone
from datetime import timedelta
from django.db import transaction

logger = logging.getLogger("inventra.accounts")


class AccountService:

    @classmethod
    @transaction.atomic
    def invite_user(cls, *, tenant, email: str, role_id, invited_by):
        from apps.accounts.models import UserInvitation, Role, TenantMembership, User
        role = Role.objects.get(id=role_id, tenant=tenant)

        # If user already exists and is already a member, raise
        user = User.objects.filter(email=email).first()
        if user and TenantMembership.objects.filter(user=user, tenant=tenant, is_active=True).exists():
            from rest_framework import serializers
            raise serializers.ValidationError("This user is already a member.")

        # Cancel any existing pending invitations
        UserInvitation.objects.filter(
            tenant=tenant, email=email, accepted_at__isnull=True
        ).update(is_active=False)

        invitation = UserInvitation.objects.create(
            tenant=tenant,
            email=email,
            role=role,
            invited_by=invited_by,
            expires_at=timezone.now() + timedelta(days=7),
        )

        # Send invitation email async
        from apps.notifications.tasks import send_invitation_email
        send_invitation_email.delay(str(invitation.id))

        logger.info(f"[ACCOUNTS] Invitation sent: {email} → {tenant.slug}")
        return invitation

    @classmethod
    @transaction.atomic
    def accept_invitation(cls, token: str, password: str, first_name: str, last_name: str):
        from apps.accounts.models import UserInvitation, User, TenantMembership
        invitation = UserInvitation.objects.select_related("tenant", "role").filter(
            token=token, accepted_at__isnull=True, is_active=True
        ).first()

        if not invitation:
            raise ValueError("Invitation not found or already used.")
        if invitation.is_expired:
            raise ValueError("This invitation has expired.")

        # Get or create user
        user, created = User.objects.get_or_create(
            email=invitation.email,
            defaults={
                "first_name": first_name,
                "last_name": last_name,
                "is_email_verified": True,
            },
        )
        if created:
            user.set_password(password)
            user.save()

        # Create membership
        TenantMembership.objects.get_or_create(
            user=user,
            tenant=invitation.tenant,
            defaults={
                "role": invitation.role,
                "invited_by": invitation.invited_by,
                "joined_at": timezone.now(),
            },
        )

        invitation.accepted_at = timezone.now()
        invitation.save(update_fields=["accepted_at"])

        logger.info(f"[ACCOUNTS] Invitation accepted: {invitation.email}")
        return user, invitation.tenant
