"""
Conakry Food — Payment Config
Charge les variables d'environnement depuis .env
"""

from pydantic_settings import BaseSettings


class PaymentConfig(BaseSettings):
    # "internal_sandbox" | "mtn_sandbox" | "mtn_production"
    PAYMENT_MODE: str = "internal_sandbox"

    # MTN MoMo — commun
    MTN_BASE_URL:    str = "https://sandbox.momodeveloper.mtn.com"
    MTN_ENVIRONMENT: str = "sandbox"   # "sandbox" | "mtncameroon" | "mtnguinea" etc.

    # MTN MoMo — Collections (recevoir de l'argent)
    MTN_COLLECTION_KEY:    str = ""
    MTN_COLLECTION_SECRET: str = ""

    # MTN MoMo — Disbursements (envoyer de l'argent)
    MTN_DISBURSEMENT_KEY:    str = ""
    MTN_DISBURSEMENT_SECRET: str = ""

    class Config:
        env_file = ".env"
        extra    = "ignore"
