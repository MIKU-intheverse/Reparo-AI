from datetime import datetime
from pydantic import BaseModel, EmailStr


class SignupStart(BaseModel):
    email: EmailStr
    environment: str


class VerifyOtp(BaseModel):
    email: EmailStr
    code: str


class SignupComplete(BaseModel):
    email: EmailStr
    password: str
    environment: str


class SignIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    environment: str
    email: str


class ConnectRazorpay(BaseModel):
    key_id: str
    key_secret: str


class ConnectionStatus(BaseModel):
    connected: bool
    key_id: str | None = None
    environment: str
    status: str
    last_synced_at: datetime | None = None


class Payment(BaseModel):
    id: str
    order_id: str | None = None
    amount: float
    currency: str = "INR"
    status: str
    method: str | None = None
    email: str | None = None
    contact: str | None = None
    created_at: datetime
    captured: bool = False
    refund_status: str | None = None
    failure_reason: str | None = None
    source: str


class Order(BaseModel):
    id: str
    amount: float
    currency: str = "INR"
    status: str
    attempts: int = 0
    created_at: datetime
    source: str


class Refund(BaseModel):
    id: str
    payment_id: str
    amount: float
    status: str
    created_at: datetime
    source: str


class Customer(BaseModel):
    id: str
    name: str | None = None
    email: str | None = None
    contact: str | None = None
    created_at: datetime
    source: str


class Analytics(BaseModel):
    total_revenue: float
    total_payments: int
    success_rate: float
    failed_payments: int
    refunded_amount: float
    revenue_series: list[dict]
    method_breakdown: list[dict]


class Paginated(BaseModel):
    items: list[dict]
    count: int
    has_more: bool
