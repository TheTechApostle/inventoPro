"""
SalesService — all business logic for creating and processing sales orders.
"""
import logging
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from core.exceptions import OrderAlreadyProcessedException, InsufficientStockException
from core.utils import generate_order_number

logger = logging.getLogger("inventra.sales")


class SalesService:

    @classmethod
    @transaction.atomic
    def create_order(cls, *, tenant, warehouse, created_by, items: list[dict],
                     customer=None, sale_channel="walk_in", discount_type="fixed",
                     discount_value=Decimal("0"), shipping_amount=Decimal("0"),
                     due_date=None, notes="", branch=None, pos_session=None) -> "SalesOrder":
        """
        Create a new sales order in DRAFT state.
        items: [{"product": Product, "quantity": 5, "unit_price": 100, "variant": None, ...}]
        """
        from apps.sales.models import SalesOrder, SalesOrderItem

        order = SalesOrder.objects.create(
            tenant=tenant,
            order_number=generate_order_number("INV"),
            warehouse=warehouse,
            branch=branch,
            customer=customer,
            sale_channel=sale_channel,
            discount_type=discount_type,
            discount_value=discount_value,
            shipping_amount=shipping_amount,
            due_date=due_date,
            notes=notes,
            created_by=created_by,
            pos_session=pos_session,
            currency=tenant.currency,
        )

        for item in items:
            SalesOrderItem.objects.create(
                tenant=tenant,
                order=order,
                product=item["product"],
                variant=item.get("variant"),
                quantity=Decimal(str(item["quantity"])),
                unit_price=Decimal(str(item["unit_price"])),
                cost_price=Decimal(str(item.get("cost_price", 0))),
                discount_pct=Decimal(str(item.get("discount_pct", 0))),
                tax_rate=Decimal(str(item.get("tax_rate", 0))),
            )

        order.recalculate_totals()
        logger.info(f"[SALES] Order created: {order.order_number} | Tenant: {tenant.slug}")
        return order

    @classmethod
    @transaction.atomic
    def confirm_order(cls, order, confirmed_by) -> "SalesOrder":
        """
        Confirm an order: deduct stock from warehouse.
        Transitions: DRAFT → CONFIRMED
        """
        if order.status != "draft":
            raise OrderAlreadyProcessedException(
                f"Order {order.order_number} is already {order.status}."
            )

        from apps.inventory.services import StockService
        from apps.inventory.models import StockMovement

        items = [
            {
                "product": item.product,
                "variant": item.variant,
                "quantity": item.quantity,
                "unit_cost": item.cost_price,
            }
            for item in order.items.filter(is_active=True)
        ]

        StockService.process_sale(
            tenant=order.tenant,
            warehouse=order.warehouse,
            performed_by=confirmed_by,
            items=items,
            reference_id=order.id,
            reference_number=order.order_number,
        )

        order.status = "confirmed"
        order.save(update_fields=["status", "updated_at"])
        logger.info(f"[SALES] Order confirmed: {order.order_number}")
        return order

    @classmethod
    @transaction.atomic
    def record_payment(cls, *, order, amount: Decimal, method: str,
                       received_by, reference: str = "", notes: str = "") -> "Payment":
        """Record a payment against an order."""
        from apps.sales.models import Payment

        payment = Payment.objects.create(
            tenant=order.tenant,
            order=order,
            amount=amount,
            method=method,
            received_by=received_by,
            reference=reference,
            notes=notes,
        )

        order.amount_paid += amount
        order.amount_due = max(order.total_amount - order.amount_paid, Decimal("0"))
        order.save(update_fields=["amount_paid", "amount_due", "updated_at"])
        order.update_payment_status()

        # Update customer outstanding balance if on credit
        if order.customer and method == "credit":
            order.customer.outstanding_balance += amount
            order.customer.save(update_fields=["outstanding_balance"])

        logger.info(
            f"[SALES] Payment recorded: {amount} [{method}] for {order.order_number}"
        )
        return payment

    @classmethod
    @transaction.atomic
    def cancel_order(cls, order, cancelled_by, reason: str = "") -> "SalesOrder":
        """Cancel an order. Reverses stock if already confirmed."""
        if order.status in ("delivered", "returned"):
            raise OrderAlreadyProcessedException(
                f"Cannot cancel a {order.status} order."
            )

        if order.status == "confirmed":
            # Reverse the stock deduction
            from apps.inventory.services import StockService
            from apps.inventory.models import StockMovement
            items = [
                {"product": item.product, "variant": item.variant, "quantity": item.quantity}
                for item in order.items.filter(is_active=True)
            ]
            StockService.process_purchase_receipt(
                tenant=order.tenant,
                warehouse=order.warehouse,
                performed_by=cancelled_by,
                items=[{**i, "unit_cost": Decimal("0")} for i in items],
                reference_id=order.id,
                reference_number=f"VOID-{order.order_number}",
            )

        order.status = "cancelled"
        order.notes = f"{order.notes}\nCancelled: {reason}".strip()
        order.save(update_fields=["status", "notes", "updated_at"])
        logger.info(f"[SALES] Order cancelled: {order.order_number}")
        return order

    @classmethod
    @transaction.atomic
    def open_pos_session(cls, *, tenant, warehouse, cashier, opening_float: Decimal) -> "POSSession":
        from apps.sales.models import POSSession
        # Close any stale open session for this cashier
        POSSession.objects.filter(
            tenant=tenant, cashier=cashier, status="open"
        ).update(status="closed", closed_at=timezone.now())

        session = POSSession.objects.create(
            tenant=tenant,
            warehouse=warehouse,
            cashier=cashier,
            opening_float=opening_float,
            status="open",
        )
        logger.info(f"[POS] Session opened: {cashier.email} @ {warehouse.code}")
        return session

    @classmethod
    @transaction.atomic
    def close_pos_session(cls, session, closing_float: Decimal, notes: str = "") -> "POSSession":
        from apps.sales.models import Payment
        cash_sales = Payment.objects.filter(
            tenant=session.tenant,
            order__pos_session=session,
            method="cash",
        ).aggregate(total=__import__("django.db.models", fromlist=["Sum"]).Sum("amount"))["total"] or Decimal("0")

        session.closing_float = closing_float
        session.expected_cash = session.opening_float + cash_sales
        session.status = "closed"
        session.closed_at = timezone.now()
        session.notes = notes
        session.save(update_fields=[
            "closing_float", "expected_cash", "status", "closed_at", "notes", "updated_at"
        ])
        logger.info(f"[POS] Session closed: {session.cashier.email} | Variance: {session.cash_variance}")
        return session
