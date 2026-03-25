"""
Conakry Food — Payment Router
Endpoints :
  POST /payment/initiate         → client initie le paiement
  POST /payment/confirm-delivery → livreur confirme, déclenche les versements
  POST /payment/webhook/mtn      → MTN notifie le statut
  GET  /payment/split            → calcul de répartition (debug)
"""

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .config import PaymentConfig
from .service import PaymentService
from .models import PaymentRequest, DisbursementRequest, PaymentStatus

logger = APIRouter()
router = APIRouter(prefix="/payment", tags=["payment"])

# Init service (Railway / Docker injecte les vars d'env)
config  = PaymentConfig()
service = PaymentService(config)


# ─────────────────────────────────────────────
# Schemas de requête
# ─────────────────────────────────────────────

class InitiatePaymentBody(BaseModel):
    order_id:     str
    phone_number: str
    amount:       int           # total payé par le client


class ConfirmDeliveryBody(BaseModel):
    order_id:          str
    restaurant_phone:  str
    driver_phone:      str
    food_amount:       int      # prix du plat
    delivery_fee:      int      # frais de livraison
    commission_rate:   float = 0.15


class MTNWebhookBody(BaseModel):
    referenceId:  str
    status:       str
    financialTransactionId: str | None = None


# ─────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────

@router.post("/initiate")
async def initiate_payment(body: InitiatePaymentBody):
    """
    Étape 1 : le client confirme sa commande sur WhatsApp.
    Le bot appelle cet endpoint → envoie un push USSD au client.
    """
    req    = PaymentRequest(
        order_id=body.order_id,
        phone_number=body.phone_number,
        amount=body.amount,
    )
    result = await service.request_payment(req)

    if result.status == PaymentStatus.FAILED:
        raise HTTPException(status_code=400, detail=result.message)

    return {
        "payment_id": result.payment_id,
        "status":     result.status,
        "message":    result.message,
    }


@router.post("/confirm-delivery")
async def confirm_delivery(body: ConfirmDeliveryBody):
    """
    Étape 2 : le livreur confirme la livraison.
    Déclenche automatiquement les versements restaurant + livreur.
    """
    split = service.split_order(
        order_total=body.food_amount + body.delivery_fee,
        delivery_fee=body.delivery_fee,
        commission_rate=body.commission_rate,
    )

    # Versement restaurant
    restaurant_result = await service.disburse(DisbursementRequest(
        phone_number=body.restaurant_phone,
        amount=split["restaurant_share"],
        reference=f"{body.order_id}-RESTAURANT",
        note=f"Conakry Food - Commande {body.order_id}",
    ))

    # Versement livreur
    driver_result = await service.disburse(DisbursementRequest(
        phone_number=body.driver_phone,
        amount=split["driver_share"],
        reference=f"{body.order_id}-DRIVER",
        note=f"Conakry Food - Livraison {body.order_id}",
    ))

    logger.info(
        f"[confirm-delivery] order={body.order_id} | "
        f"restaurant={split['restaurant_share']} GNF | "
        f"driver={split['driver_share']} GNF | "
        f"marge={split['platform_margin']} GNF"
    )

    return {
        "order_id":         body.order_id,
        "split":            split,
        "restaurant":       {"status": restaurant_result.status, "ref": restaurant_result.transfer_id},
        "driver":           {"status": driver_result.status,     "ref": driver_result.transfer_id},
        "platform_margin":  split["platform_margin"],
    }


@router.post("/webhook/mtn")
async def mtn_webhook(body: MTNWebhookBody):
    """
    MTN MoMo notifie ton backend quand un paiement change de statut.
    À connecter dans le dashboard MTN sandbox.
    URL publique requise → utilise ngrok en local.
    """
    logger.info(
        f"[webhook/mtn] ref={body.referenceId} | "
        f"status={body.status} | txId={body.financialTransactionId}"
    )

    # TODO : mettre à jour le statut de la commande en base
    # await order_service.update_payment_status(body.referenceId, body.status)

    return {"received": True}


@router.get("/split")
def split_preview(order_total: int, delivery_fee: int, commission: float = 0.15):
    """
    Endpoint de debug : calcule et affiche la répartition d'une commande.
    Ex: GET /payment/split?order_total=60000&delivery_fee=10000
    """
    return service.split_order(order_total, delivery_fee, commission)
