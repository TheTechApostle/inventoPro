from celery import shared_task
import logging

logger = logging.getLogger("inventra.notifications.tasks")


@shared_task(bind=True, max_retries=3)
def send_invitation_email(self, invitation_id: str):
    """Send email invitation to join a tenant."""
    try:
        from apps.accounts.models import UserInvitation
        from django.core.mail import send_mail
        from django.conf import settings

        invitation = UserInvitation.objects.select_related(
            "tenant", "invited_by", "role"
        ).get(id=invitation_id)

        accept_url = (
            f"{settings.FRONTEND_URL}/accept-invitation/{invitation.token}"
        )

        send_mail(
            subject=f"You've been invited to join {invitation.tenant.name} on Inventra",
            message=(
                f"Hi,\n\n"
                f"{invitation.invited_by.get_full_name()} has invited you to join "
                f"{invitation.tenant.name} as a {invitation.role.display_name or invitation.role.name}.\n\n"
                f"Accept your invitation here:\n{accept_url}\n\n"
                f"This invitation expires in 7 days.\n\n"
                f"— The Inventra Team"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[invitation.email],
            fail_silently=False,
        )
        logger.info(f"[EMAIL] Invitation sent to: {invitation.email}")
    except Exception as exc:
        logger.error(f"[EMAIL] Invitation send failed: {exc}")
        raise self.retry(exc=exc, countdown=60)


@shared_task(bind=True, max_retries=3)
def send_low_stock_email(self, tenant_id: str, product_ids: list):
    """Send low stock digest email to tenant owner."""
    try:
        from apps.tenants.models import Tenant
        from apps.products.models import Product
        from django.core.mail import send_mail
        from django.conf import settings

        tenant = Tenant.objects.get(id=tenant_id)
        products = Product.objects.unscoped().filter(
            id__in=product_ids, tenant=tenant
        )

        product_lines = "\n".join(
            f"  - {p.name} (SKU: {p.sku})" for p in products[:20]
        )

        send_mail(
            subject=f"[Inventra] Low Stock Alert — {len(product_ids)} products",
            message=(
                f"Hi {tenant.owner.first_name},\n\n"
                f"The following products are running low in {tenant.name}:\n\n"
                f"{product_lines}\n\n"
                f"Log in to your dashboard to review and reorder.\n\n"
                f"— The Inventra Team"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[tenant.owner.email],
            fail_silently=True,
        )
    except Exception as exc:
        logger.error(f"[EMAIL] Low stock email failed: {exc}")
        raise self.retry(exc=exc, countdown=120)
