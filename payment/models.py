"""
Conakry Food — Payment Models
"""

from enum import Enum
from typing import Optional, Any
from pydantic import BaseModel


class PaymentStatus(str, Enum):
    PENDING    = "PENDING"
    SUCCESSFUL = "SUCCESSFUL"
    FAILED     = "FAILED"


class PaymentRequest(BaseModel):
    order_id:     str
    phone_number: str          # format MSISDN ex: 224620000000
    amount:       int          # en GNF
    currency:     str = "GNF"


class PaymentResult(BaseModel):
    payment_id:   str
    status:       PaymentStatus
    message:      str
    raw_response: Optional[Any] = None


class DisbursementRequest(BaseModel):
    phone_number: str
    amount:       int
    reference:    str          # ex: "ORDER-42-RESTAURANT"
    note:         str          # ex: "Conakry Food - versement restaurant"


class DisbursementResult(BaseModel):
    transfer_id: str
    status:      PaymentStatus
    message:     str
