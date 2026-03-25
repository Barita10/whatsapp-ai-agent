"""
Conakry Food — Payment Service
Modes : "internal_sandbox" | "mtn_sandbox" | "mtn_production"
"""

import uuid
import httpx
import base64
import logging
from datetime import datetime
from enum import Enum
from typing import Optional

from .config import PaymentConfig
from .models import (
    PaymentRequest,
    PaymentResult,
    PaymentStatus,
    DisbursementRequest,
    DisbursementResult,
)

logger = logging.getLogger(__name__)


class PaymentMode(str, Enum):
    INTERNAL_SANDBOX = "internal_sandbox"   # Niveau 0 — aucun appel réseau
    MTN_SANDBOX      = "mtn_sandbox"        # Niveau 1 — API réelle, fausse monnaie
    MTN_PRODUCTION   = "mtn_production"     # Phase launch


class PaymentService:
    def __init__(self, config: PaymentConfig):
        self.config = config
        self.mode = PaymentMode(config.PAYMENT_MODE)
        logger.info(f"[PaymentService] Mode actif : {self.mode}")

    # ─────────────────────────────────────────────
    # COLLECTE — client paie la commande
    # ─────────────────────────────────────────────

    async def request_payment(self, req: PaymentRequest) -> PaymentResult:
        """
        Demande un paiement Mobile Money au client.
        Le client reçoit un push USSD sur son téléphone.
        """
        if self.mode == PaymentMode.INTERNAL_SANDBOX:
            return self._sandbox_payment(req)

        return await self._mtn_request_payment(req)

    async def get_payment_status(self, payment_id: str) -> PaymentStatus:
        """Vérifie le statut d'un paiement en cours."""
        if self.mode == PaymentMode.INTERNAL_SANDBOX:
            return PaymentStatus.SUCCESSFUL

        return await self._mtn_get_status(payment_id, flow="collection")

    # ─────────────────────────────────────────────
    # DISBURSEMENT — payer restaurant + livreur
    # ─────────────────────────────────────────────

    async def disburse(self, req: DisbursementRequest) -> DisbursementResult:
        """
        Envoie de l'argent vers un numéro Mobile Money.
        Utilisé après confirmation de livraison.
        """
        if self.mode == PaymentMode.INTERNAL_SANDBOX:
            return self._sandbox_disbursement(req)

        return await self._mtn_disburse(req)

    # ─────────────────────────────────────────────
    # UTILITAIRE — répartition de la commande
    # ─────────────────────────────────────────────

    def split_order(
        self,
        order_total: int,        # prix total payé par le client (GNF)
        delivery_fee: int,       # frais de livraison
        commission_rate: float = 0.15,  # ta commission sur le plat
    ) -> dict:
        """
        Calcule la répartition d'une commande.

        Exemple :
          order_total    = 60 000 GNF
          delivery_fee   = 10 000 GNF
          commission     = 15%

          food_amount    = 50 000
          restaurant     = 42 500  (food_amount × 85%)
          livreur        = 8 000   (delivery_fee - ta part livraison)
          marge          = 7 500 + 2 000 = 9 500
        """
        food_amount      = order_total - delivery_fee
        restaurant_share = round(food_amount * (1 - commission_rate))
        platform_food    = food_amount - restaurant_share

        delivery_platform = round(delivery_fee * 0.20)   # 20% des frais de livraison
        driver_share      = delivery_fee - delivery_platform

        total_margin = platform_food + delivery_platform

        return {
            "order_total":      order_total,
            "food_amount":      food_amount,
            "delivery_fee":     delivery_fee,
            "restaurant_share": restaurant_share,
            "driver_share":     driver_share,
            "platform_margin":  total_margin,
        }

    # ─────────────────────────────────────────────
    # NIVEAU 0 — Internal sandbox (aucun appel API)
    # ─────────────────────────────────────────────

    def _sandbox_payment(self, req: PaymentRequest) -> PaymentResult:
        payment_id = f"SANDBOX-{uuid.uuid4().hex[:8].upper()}"
        logger.info(
            f"[SANDBOX] Paiement simulé | id={payment_id} "
            f"montant={req.amount} GNF | client={req.phone_number}"
        )
        return PaymentResult(
            payment_id=payment_id,
            status=PaymentStatus.SUCCESSFUL,
            message="Paiement sandbox confirmé automatiquement",
            raw_response={"sandbox": True},
        )

    def _sandbox_disbursement(self, req: DisbursementRequest) -> DisbursementResult:
        transfer_id = f"SANDBOX-{uuid.uuid4().hex[:8].upper()}"
        logger.info(
            f"[SANDBOX] Versement simulé | id={transfer_id} "
            f"destinataire={req.phone_number} | montant={req.amount} GNF"
        )
        return DisbursementResult(
            transfer_id=transfer_id,
            status=PaymentStatus.SUCCESSFUL,
            message=f"Versement sandbox OK → {req.phone_number}",
        )

    # ─────────────────────────────────────────────
    # NIVEAU 1 — MTN MoMo sandbox / production
    # ─────────────────────────────────────────────

    async def _get_mtn_token(self, product: str) -> str:
        """
        Récupère un token OAuth MTN MoMo.
        product = "collection" | "disbursement"
        """
        base_url = self.config.MTN_BASE_URL
        key      = self.config.MTN_COLLECTION_KEY if product == "collection" \
                   else self.config.MTN_DISBURSEMENT_KEY
        secret   = self.config.MTN_COLLECTION_SECRET if product == "collection" \
                   else self.config.MTN_DISBURSEMENT_SECRET

        credentials = base64.b64encode(f"{key}:{secret}".encode()).decode()

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{base_url}/{product}/token/",
                headers={
                    "Authorization": f"Basic {credentials}",
                    "Ocp-Apim-Subscription-Key": key,
                },
            )
            response.raise_for_status()
            return response.json()["access_token"]

    async def _mtn_request_payment(self, req: PaymentRequest) -> PaymentResult:
        """Initie un paiement MTN MoMo (Collections API)."""
        payment_id = str(uuid.uuid4())
        token      = await self._get_mtn_token("collection")

        payload = {
            "amount":       str(req.amount),
            "currency":     "GNF",
            "externalId":   req.order_id,
            "payer": {
                "partyIdType": "MSISDN",
                "partyId":     req.phone_number,
            },
            "payerMessage": f"Conakry Food - Commande #{req.order_id}",
            "payeeNote":    f"Paiement commande {req.order_id}",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.config.MTN_BASE_URL}/collection/v1_0/requesttopay",
                json=payload,
                headers={
                    "Authorization":              f"Bearer {token}",
                    "X-Reference-Id":             payment_id,
                    "X-Target-Environment":       self.config.MTN_ENVIRONMENT,
                    "Ocp-Apim-Subscription-Key":  self.config.MTN_COLLECTION_KEY,
                    "Content-Type":               "application/json",
                },
            )

            if response.status_code == 202:
                logger.info(f"[MTN] Paiement initié | id={payment_id}")
                return PaymentResult(
                    payment_id=payment_id,
                    status=PaymentStatus.PENDING,
                    message="Push USSD envoyé au client",
                    raw_response={"mtn_ref": payment_id},
                )
            else:
                logger.error(f"[MTN] Erreur paiement : {response.text}")
                return PaymentResult(
                    payment_id=payment_id,
                    status=PaymentStatus.FAILED,
                    message=response.text,
                    raw_response=response.json(),
                )

    async def _mtn_get_status(self, payment_id: str, flow: str) -> PaymentStatus:
        """Vérifie le statut d'un paiement ou disbursement MTN."""
        token    = await self._get_mtn_token(flow)
        endpoint = f"{self.config.MTN_BASE_URL}/{flow}/v1_0/requesttopay/{payment_id}" \
                   if flow == "collection" \
                   else f"{self.config.MTN_BASE_URL}/{flow}/v1_0/transfer/{payment_id}"

        sub_key = self.config.MTN_COLLECTION_KEY if flow == "collection" \
                  else self.config.MTN_DISBURSEMENT_KEY

        async with httpx.AsyncClient() as client:
            response = await client.get(
                endpoint,
                headers={
                    "Authorization":             f"Bearer {token}",
                    "X-Target-Environment":      self.config.MTN_ENVIRONMENT,
                    "Ocp-Apim-Subscription-Key": sub_key,
                },
            )
            data   = response.json()
            status = data.get("status", "FAILED")
            return PaymentStatus(status)

    async def _mtn_disburse(self, req: DisbursementRequest) -> DisbursementResult:
        """Envoie de l'argent vers un numéro MTN MoMo (Disbursements API)."""
        transfer_id = str(uuid.uuid4())
        token       = await self._get_mtn_token("disbursement")

        payload = {
            "amount":     str(req.amount),
            "currency":   "GNF",
            "externalId": req.reference,
            "payee": {
                "partyIdType": "MSISDN",
                "partyId":     req.phone_number,
            },
            "payerMessage": req.note,
            "payeeNote":    req.note,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.config.MTN_BASE_URL}/disbursement/v1_0/transfer",
                json=payload,
                headers={
                    "Authorization":             f"Bearer {token}",
                    "X-Reference-Id":            transfer_id,
                    "X-Target-Environment":      self.config.MTN_ENVIRONMENT,
                    "Ocp-Apim-Subscription-Key": self.config.MTN_DISBURSEMENT_KEY,
                    "Content-Type":              "application/json",
                },
            )

            if response.status_code == 202:
                logger.info(f"[MTN] Versement initié | id={transfer_id} → {req.phone_number}")
                return DisbursementResult(
                    transfer_id=transfer_id,
                    status=PaymentStatus.PENDING,
                    message=f"Versement en cours → {req.phone_number}",
                )
            else:
                logger.error(f"[MTN] Erreur versement : {response.text}")
                return DisbursementResult(
                    transfer_id=transfer_id,
                    status=PaymentStatus.FAILED,
                    message=response.text,
                )
