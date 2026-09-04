from enum import Enum


class OrderStatus(str, Enum):
    created = "created"
    paid = "paid"
    failed = "failed"
    cancelled = "cancelled"


class PaymentStatus(str, Enum):
    success = "success"
    failed = "failed"
    authorized = "authorized"
    captured = "captured"
    refunded = "refunded"


class PaymentMethod(str, Enum):
    upi = "upi"
    card = "card"
    netbanking = "netbanking"
    wallet = "wallet"


class DeviceType(str, Enum):
    mobile = "mobile"
    desktop = "desktop"
    tablet = "tablet"


class Platform(str, Enum):
    android = "android"
    ios = "ios"
    web = "web"


class FailureCategory(str, Enum):
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    BANK_DECLINED = "BANK_DECLINED"
    NETWORK_ERROR = "NETWORK_ERROR"
    TIMEOUT = "TIMEOUT"
    UPI_FAILURE = "UPI_FAILURE"
    CARD_DECLINED = "CARD_DECLINED"
    CARD_LIMIT = "CARD_LIMIT"
    AUTHENTICATION_FAILURE = "AUTHENTICATION_FAILURE"
    INVALID_DETAILS = "INVALID_DETAILS"
    TECHNICAL_ERROR = "TECHNICAL_ERROR"
    UNKNOWN = "UNKNOWN"


class FailureSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Recoverability(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class FailureSource(str, Enum):
    BANK = "BANK"
    NETWORK = "NETWORK"
    CUSTOMER = "CUSTOMER"
    GATEWAY = "GATEWAY"
    UNKNOWN = "UNKNOWN"


class FailureStep(str, Enum):
    AUTHENTICATION = "AUTHENTICATION"
    AUTHORIZATION = "AUTHORIZATION"
    CAPTURE = "CAPTURE"
    OTP_VERIFICATION = "OTP_VERIFICATION"
    PRE_PROCESSING = "PRE_PROCESSING"


class CustomerSegment(str, Enum):
    HIGH_VALUE_LOYAL = "HIGH_VALUE_LOYAL"
    NORMAL = "NORMAL"
    LOW_INTENT = "LOW_INTENT"
    NEW = "NEW"


class RecoverySegment(str, Enum):
    HIGH_RECOVERY = "HIGH_RECOVERY"
    MEDIUM_RECOVERY = "MEDIUM_RECOVERY"
    LOW_RECOVERY = "LOW_RECOVERY"


class RecommendedAction(str, Enum):
    """The investigation agent's (Phase 3) and the opportunity/campaign
    workflow's (Phase 4) shared action vocabulary -- defined once here so a
    DB column and the agent's Pydantic schema can never drift apart."""

    PAYMENT_LINK = "PAYMENT_LINK"
    RETRY = "RETRY"
    ALTERNATIVE_PAYMENT_METHOD = "ALTERNATIVE_PAYMENT_METHOD"
    REMINDER = "REMINDER"
    NO_ACTION = "NO_ACTION"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class OpportunityStatus(str, Enum):
    NEW = "NEW"
    REVIEWED = "REVIEWED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    RECOVERED = "RECOVERED"
    FAILED = "FAILED"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RecoveryActionStatus(str, Enum):
    """Not one of the spec's named enums -- a `RecoveryAction` needs its own
    small lifecycle (distinct from the opportunity/campaign statuses it's
    attached to) to track the provider call itself. RECOVERED is set only
    by a verified inbound Razorpay webhook (Phase 5) -- see
    app/api/webhooks.py -- never by `_execute_campaign`, which only ever
    reaches EXECUTED or FAILED."""

    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"
    RECOVERED = "RECOVERED"


class AuditEventType(str, Enum):
    CAMPAIGN_CREATED = "campaign_created"
    CAMPAIGN_APPROVED = "campaign_approved"
    CAMPAIGN_REJECTED = "campaign_rejected"
    POLICY_CHECKED = "policy_checked"
    RECOVERY_ACTION_AUTHORIZED = "recovery_action_authorized"
    RECOVERY_ACTION_EXECUTED = "recovery_action_executed"
    # Phase 5: written only when a verified inbound Razorpay webhook
    # confirms a payment link was actually paid.
    RECOVERY_CONFIRMED = "recovery_confirmed"
