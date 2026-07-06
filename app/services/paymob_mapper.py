"""Map Paymob webhook data to PaymentTransaction model fields."""

from app.integrations.base import PaymentWebhookData
from app.models.payment_transaction import PaymentTransaction


def apply_paymob_fields(transaction: PaymentTransaction, data: PaymentWebhookData) -> None:
    transaction.amount_cents = data.amount_cents
    transaction.paymob_created_at = data.paymob_created_at
    transaction.error_occured = data.error_occured
    transaction.has_parent_transaction = data.has_parent_transaction
    transaction.paymob_integration_id = data.paymob_integration_id
    transaction.is_3d_secure = data.is_3d_secure
    transaction.is_auth = data.is_auth
    transaction.is_capture = data.is_capture
    transaction.is_refunded = data.is_refunded
    transaction.is_standalone_payment = data.is_standalone_payment
    transaction.is_voided = data.is_voided
    transaction.paymob_order_id = data.paymob_order_id
    transaction.merchant_order_id = data.merchant_reference
    transaction.owner = data.owner
    transaction.pending = data.pending
    transaction.source_pan = data.source_pan
    transaction.source_sub_type = data.source_sub_type
    transaction.source_type = data.source_type
    transaction.success = data.success
