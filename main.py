# main.py
# WhatsApp AI Agent – Commandes Conakry (Adaptation Guinée)
# FastAPI + SQLAlchemy + WhatsApp Business Cloud API v22
# + Mobile Money (Orange Money, MTN) 
# + Gestion Livreurs Taxi-Motos
# + Multi-restaurants
# + Géolocalisation Conakry

import os
import re
import json
import logging
import unicodedata
from datetime import datetime
from typing import List, Dict, Optional, Tuple

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy import create_engine, Column, Integer, String, DateTime, Float, Text, ForeignKey, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship

import requests
import asyncio

# -----------------------------------------------------------------------------
# Config Guinée
# -----------------------------------------------------------------------------
class Config:
    WHATSAPP_TOKEN: str = os.getenv("WHATSAPP_TOKEN", "your_whatsapp_token")
    WHATSAPP_PHONE_ID: str = os.getenv("WHATSAPP_PHONE_ID", "your_phone_id")
    WHATSAPP_VERIFY_TOKEN: str = os.getenv("WHATSAPP_VERIFY_TOKEN", "verify_token_123")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./conakry_food.db")
    
    # APIs Mobile Money Guinée
    ORANGE_MONEY_API_KEY: str = os.getenv("ORANGE_MONEY_API_KEY", "your_orange_key")
    ORANGE_MONEY_API_SECRET: str = os.getenv("ORANGE_MONEY_API_SECRET", "your_orange_secret")
    MTN_MOMO_API_KEY: str = os.getenv("MTN_MOMO_API_KEY", "your_mtn_key")
    
    # Google Maps pour calculs distances/géolocalisation
    GOOGLE_MAPS_API_KEY: str = os.getenv("GOOGLE_MAPS_API_KEY", "your_google_maps_key")
    
    # Numéro admin principal (peut être différent du restaurant)
    ADMIN_PHONE: str = os.getenv("ADMIN_PHONE", "224611223344")
    
    # Prix livraison de base en GNF
    BASE_DELIVERY_FEE: int = int(os.getenv("BASE_DELIVERY_FEE", "2000"))
    FEE_PER_KM: int = int(os.getenv("FEE_PER_KM", "500"))

config = Config()

# -----------------------------------------------------------------------------
# DB Models Étendus
# -----------------------------------------------------------------------------
engine = create_engine(config.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class OrderStatus:
    PENDING = "pending"          # En attente restaurant
    CONFIRMED = "confirmed"      # Confirmé restaurant
    PREPARING = "preparing"      # En préparation
    READY = "ready"             # Prêt pour livraison
    ASSIGNED = "assigned"       # Assigné à un livreur
    DELIVERING = "delivering"   # En cours de livraison
    DELIVERED = "delivered"     # Livré
    CANCELLED = "cancelled"     # Annulé

class PaymentStatus:
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"

# Zones de Conakry
CONAKRY_ZONES = [
    "Kaloum", "Dixinn", "Ratoma", "Matam", "Matoto",
    "Kipé", "Camayenne", "Almamya", "Lambandji", "Sonfonia",
    "Hamdallaye", "Koloma", "Kagbelen", "Nongo", "Simbaya"
]

class Restaurant(Base):
    __tablename__ = "restaurants"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    phone_number = Column(String, unique=True, index=True)
    address = Column(Text)
    zone = Column(String)  # Zone de Conakry
    latitude = Column(Float)
    longitude = Column(Float)
    is_active = Column(Boolean, default=True)
    commission_rate = Column(Float, default=0.15)  # 15% de commission
    delivery_zones = Column(Text)  # JSON des zones desservies
    average_prep_time = Column(Integer, default=30)  # minutes
    rating = Column(Float, default=0.0)
    total_orders = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relations
    products = relationship("Product", back_populates="restaurant")
    orders = relationship("Order", back_populates="restaurant")

class Customer(Base):
    __tablename__ = "customers"
    
    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, unique=True, index=True)
    name = Column(String)
    address = Column(Text)
    zone = Column(String)  # Zone de Conakry
    latitude = Column(Float)
    longitude = Column(Float)
    total_orders = Column(Integer, default=0)
    total_spent = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    orders = relationship("Order", back_populates="customer")

class Product(Base):
    __tablename__ = "products"
    
    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"))
    name = Column(String, index=True)
    description = Column(Text)
    price = Column(Float)  # Prix en GNF
    category = Column(String)
    image_url = Column(String)
    available = Column(Boolean, default=True)
    
    restaurant = relationship("Restaurant", back_populates="products")

class DeliveryDriver(Base):
    __tablename__ = "delivery_drivers"
    
    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, unique=True, index=True)
    name = Column(String)
    zone = Column(String)  # Zone principale
    is_available = Column(Boolean, default=True)
    current_latitude = Column(Float)
    current_longitude = Column(Float)
    rating = Column(Float, default=0.0)
    total_deliveries = Column(Integer, default=0)
    commission_rate = Column(Float, default=0.70)  # 70% des frais de livraison
    created_at = Column(DateTime, default=datetime.utcnow)
    
    orders = relationship("Order", back_populates="driver")

class Order(Base):
    __tablename__ = "orders"
    
    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"))
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"))
    driver_id = Column(Integer, ForeignKey("delivery_drivers.id"), nullable=True)
    
    status = Column(String, default=OrderStatus.PENDING)
    payment_status = Column(String, default=PaymentStatus.PENDING)
    payment_method = Column(String)  # "orange_money", "mtn_momo", "cash"
    payment_phone = Column(String)  # Numéro pour mobile money
    
    items = Column(Text)  # JSON des articles
    subtotal = Column(Float)  # Total articles
    delivery_fee = Column(Float)  # Frais de livraison
    restaurant_commission = Column(Float)  # Commission restaurant
    driver_commission = Column(Float)  # Commission livreur
    total_amount = Column(Float)  # Total final
    
    delivery_address = Column(Text)
    delivery_latitude = Column(Float)
    delivery_longitude = Column(Float)
    delivery_zone = Column(String)
    
    notes = Column(Text)
    estimated_delivery_time = Column(Integer)  # minutes
    
    created_at = Column(DateTime, default=datetime.utcnow)
    confirmed_at = Column(DateTime)
    delivered_at = Column(DateTime)
    
    # Relations
    customer = relationship("Customer", back_populates="orders")
    restaurant = relationship("Restaurant", back_populates="orders")
    driver = relationship("DeliveryDriver", back_populates="orders")

class Conversation(Base):
    __tablename__ = "conversations"
    
    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, index=True)
    context = Column(Text)  # JSON du contexte de conversation
    last_interaction = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# -----------------------------------------------------------------------------
# Services Mobile Money Guinée
# -----------------------------------------------------------------------------
class OrangeMoneyService:
    def __init__(self):
        self.api_key = config.ORANGE_MONEY_API_KEY
        self.api_secret = config.ORANGE_MONEY_API_SECRET
        self.base_url = "https://api.orange.com/orange-money-webpay/gn/v1"
        self.access_token = None

    async def authenticate(self) -> bool:
        """Obtenir le token d'authentification Orange Money"""
        try:
            auth_str = f"{self.api_key}:{self.api_secret}"
            import base64
            encoded_auth = base64.b64encode(auth_str.encode()).decode()
            
            response = requests.post(
                f"{self.base_url}/token",
                headers={
                    "Authorization": f"Basic {encoded_auth}",
                    "Content-Type": "application/x-www-form-urlencoded"
                },
                data={"grant_type": "client_credentials"}
            )
            
            if response.status_code == 200:
                data = response.json()
                self.access_token = data.get("access_token")
                return True
            return False
        except Exception as e:
            logging.error(f"Orange Money auth error: {e}")
            return False

    async def initiate_payment(self, phone: str, amount: int, order_id: int) -> Dict:
        """Initier un paiement Orange Money"""
        if not self.access_token:
            await self.authenticate()
        
        try:
            payment_data = {
                "merchant_key": "your_merchant_key",
                "currency": "GNF",
                "order_id": f"ORDER_{order_id}",
                "amount": amount,
                "return_url": f"https://yourapp.com/payment/success?order={order_id}",
                "cancel_url": f"https://yourapp.com/payment/cancel?order={order_id}",
                "notif_url": f"https://yourapp.com/webhook/orange-money",
                "lang": "fr",
                "reference": f"CONAKRY_FOOD_{order_id}"
            }
            
            response = requests.post(
                f"{self.base_url}/webpayment",
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json"
                },
                json=payment_data
            )
            
            if response.status_code in (200, 201):
                return {"success": True, "data": response.json()}
            else:
                return {"success": False, "error": response.text}
                
        except Exception as e:
            logging.error(f"Orange Money payment error: {e}")
            return {"success": False, "error": str(e)}

class MTNMoMoService:
    def __init__(self):
        self.api_key = config.MTN_MOMO_API_KEY
        self.base_url = "https://sandbox.momodeveloper.mtn.com"  # Prod: https://api.mtn.com
        
    async def request_to_pay(self, phone: str, amount: int, order_id: int) -> Dict:
        """Initier un paiement MTN Mobile Money"""
        try:
            import uuid
            transaction_id = str(uuid.uuid4())
            
            # Conversion GNF vers EUR (approximative pour MTN)
            amount_eur = amount / 12000  # 1 EUR ≈ 12000 GNF
            
            payment_data = {
                "amount": f"{amount_eur:.2f}",
                "currency": "EUR",
                "externalId": f"ORDER_{order_id}",
                "payer": {
                    "partyIdType": "MSISDN",
                    "partyId": phone.replace("+", "")  # Format: 224XXXXXXXXX
                },
                "payerMessage": f"Commande Conakry Food #{order_id}",
                "payeeNote": "Paiement livraison restaurant Conakry"
            }
            
            response = requests.post(
                f"{self.base_url}/collection/v1_0/requesttopay",
                headers={
                    "Authorization": f"Bearer {await self._get_access_token()}",
                    "X-Reference-Id": transaction_id,
                    "X-Target-Environment": "sandbox",  # 'live' en production
                    "Content-Type": "application/json",
                    "Ocp-Apim-Subscription-Key": self.api_key
                },
                json=payment_data
            )
            
            if response.status_code == 202:
                return {"success": True, "transaction_id": transaction_id}
            else:
                return {"success": False, "error": response.text}
                
        except Exception as e:
            logging.error(f"MTN MoMo payment error: {e}")
            return {"success": False, "error": str(e)}
    
    async def _get_access_token(self) -> str:
        # Implémentation simplifiée - à compléter selon la doc MTN
        return "dummy_token"

# -----------------------------------------------------------------------------
# Service de Géolocalisation et Livraison
# -----------------------------------------------------------------------------
class DeliveryService:
    def __init__(self, db: Session):
        self.db = db
        self.google_api_key = config.GOOGLE_MAPS_API_KEY

    def calculate_delivery_fee(self, distance_km: float) -> int:
        """Calcule les frais de livraison selon la distance"""
        if distance_km <= 2:
            return config.BASE_DELIVERY_FEE
        else:
            additional_km = distance_km - 2
            return config.BASE_DELIVERY_FEE + int(additional_km * config.FEE_PER_KM)

    async def get_distance_between_points(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Obtient la distance via Google Maps API"""
        try:
            url = f"https://maps.googleapis.com/maps/api/distancematrix/json"
            params = {
                "origins": f"{lat1},{lon1}",
                "destinations": f"{lat2},{lon2}",
                "key": self.google_api_key,
                "units": "metric"
            }
            
            response = requests.get(url, params=params)
            data = response.json()
            
            if data["status"] == "OK":
                element = data["rows"][0]["elements"][0]
                if element["status"] == "OK":
                    distance_m = element["distance"]["value"]
                    return distance_m / 1000  # Conversion en km
            
            # Fallback: calcul approximatif
            return self._haversine_distance(lat1, lon1, lat2, lon2)
            
        except Exception as e:
            logging.error(f"Distance calculation error: {e}")
            return self._haversine_distance(lat1, lon1, lat2, lon2)

    def _haversine_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calcul de distance approximatif (formule de Haversine)"""
        from math import radians, cos, sin, asin, sqrt
        
        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        return 2 * asin(sqrt(a)) * 6371  # Rayon terre en km

    def find_nearest_available_driver(self, restaurant_lat: float, restaurant_lon: float) -> Optional[DeliveryDriver]:
        """Trouve le livreur disponible le plus proche"""
        drivers = self.db.query(DeliveryDriver).filter(
            DeliveryDriver.is_available == True
        ).all()
        
        if not drivers:
            return None
        
        # Calculer distances et trier
        driver_distances = []
        for driver in drivers:
            if driver.current_latitude and driver.current_longitude:
                distance = self._haversine_distance(
                    restaurant_lat, restaurant_lon,
                    driver.current_latitude, driver.current_longitude
                )
                driver_distances.append((driver, distance))
        
        if driver_distances:
            driver_distances.sort(key=lambda x: x[1])
            return driver_distances[0][0]
        
        return drivers[0]  # Retour du premier si pas de géoloc

# -----------------------------------------------------------------------------
# WhatsApp Service
# -----------------------------------------------------------------------------
class WhatsAppService:
    def __init__(self):
        self.token = config.WHATSAPP_TOKEN
        self.phone_id = config.WHATSAPP_PHONE_ID
        self.base_url = f"https://graph.facebook.com/v22.0/{self.phone_id}"

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def send_message(self, to: str, message: str) -> bool:
        """Envoie un message texte"""
        url = f"{self.base_url}/messages"
        data = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": message},
        }
        try:
            r = requests.post(url, json=data, headers=self._headers(), timeout=15)
            ok = r.status_code in (200, 201)
            if ok:
                logging.info(f"WA message sent to {to}")
            else:
                logging.error(f"WA message failed {r.status_code}: {r.text}")
            return ok
        except Exception as e:
            logging.error(f"WA message error: {e}")
            return False

    def send_template(self, to: str, name: str, lang: str = "fr", variables: Optional[List[str]] = None) -> bool:
        """Envoie un template pour ouvrir la fenêtre 24h"""
        url = f"{self.base_url}/messages"
        components = []
        if variables:
            components = [{
                "type": "body",
                "parameters": [{"type": "text", "text": str(v)} for v in variables]
            }]
        
        data = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": name,
                "language": {"code": lang},
                "components": components
            }
        }
        try:
            r = requests.post(url, json=data, headers=self._headers(), timeout=15)
            ok = r.status_code in (200, 201)
            if ok:
                logging.info(f"WA template sent to {to}")
            else:
                logging.error(f"WA template failed {r.status_code}: {r.text}")
            return ok
        except Exception as e:
            logging.error(f"WA template error: {e}")
            return False

# -----------------------------------------------------------------------------
# Service de Conversation Guinée
# -----------------------------------------------------------------------------
class ConversationServiceConakry:
    def __init__(self, db: Session):
        self.db = db
        self.whatsapp = WhatsAppService()
        self.order_service = OrderServiceConakry(db)
        self.delivery_service = DeliveryService(db)

    def get_conversation_context(self, phone: str) -> Dict:
        conv = self.db.query(Conversation).filter(Conversation.phone_number == phone).first()
        if conv and conv.context:
            return json.loads(conv.context)
        return {
            "state": "new",
            "current_order": [],
            "selected_restaurant": None,
            "delivery_address": None,
            "delivery_zone": None
        }

    def update_conversation_context(self, phone: str, context: Dict):
        conv = self.db.query(Conversation).filter(Conversation.phone_number == phone).first()
        if not conv:
            conv = Conversation(phone_number=phone)
            self.db.add(conv)
        conv.context = json.dumps(context)
        conv.last_interaction = datetime.utcnow()
        self.db.commit()

    def _detect_intent(self, msg: str) -> str:
        m = normalize(msg)
        
        if any(w in m for w in ("bonjour", "bonsoir", "salut", "hello", "salam", "paix")):
            return "greeting"
        
        if any(w in m for w in ("restaurant", "menu", "carte", "manger", "plat")):
            return "show_restaurants"
        
        if any(zone.lower() in m for zone in CONAKRY_ZONES):
            return "select_zone"
        
        if any(w in m for w in ("commander", "prendre", "ajouter", "veux", "je prends")):
            return "order"
        
        if any(w in m for w in ("confirmer", "valider", "ok", "d'accord", "bon")):
            return "confirm"
        
        if any(w in m for w in ("livraison", "adresse", "chez moi", "domicile")):
            return "delivery_address"
        
        if any(w in m for w in ("payer", "orange money", "mtn", "mobile money", "espece")):
            return "payment"
        
        return "other"

    def _get_restaurants_in_zone(self, zone: str) -> List[Restaurant]:
        return self.db.query(Restaurant).filter(
            Restaurant.is_active == True,
            Restaurant.zone.ilike(f"%{zone}%")
        ).all()

    def _get_restaurant_products_with_synonyms(self, restaurant_id: int) -> Dict[str, Product]:
        products = self.db.query(Product).filter(
            Product.restaurant_id == restaurant_id,
            Product.available == True
        ).all()
        
        synonyms = {}
        for p in products:
            name_norm = normalize(p.name)
            synonyms[name_norm] = p
            
            # Synonymes spécifiques cuisine locale guinéenne
            if "riz" in name_norm:
                synonyms["riz"] = p
                if "sauce" in name_norm:
                    synonyms["riz sauce"] = p
                if "arachide" in name_norm:
                    synonyms["riz arachide"] = p
                    synonyms["mafe"] = p
                if "gras" in name_norm:
                    synonyms["riz gras"] = p
                    synonyms["riz au gras"] = p
            
            if "fonio" in name_norm:
                synonyms["fonio"] = p
                synonyms["fouti fonio"] = p
            
            if "poisson" in name_norm:
                synonyms["poisson"] = p
                if "braise" in name_norm:
                    synonyms["poisson braise"] = p
                    synonyms["poisson grille"] = p
            
            if "poulet" in name_norm:
                synonyms["poulet"] = p
                synonyms["chicken"] = p
            
            if "atieke" in name_norm:
                synonyms["atieke"] = p
                synonyms["attieke"] = p
            
            if "coca" in name_norm:
                synonyms["coca"] = p
                synonyms["coca cola"] = p
            
            if "fanta" in name_norm:
                synonyms["fanta"] = p
                synonyms["orange"] = p
            
            if "eau" in name_norm:
                synonyms["eau"] = p
                synonyms["eau minerale"] = p
        
        return synonyms

    def _parse_order_items(self, text: str, restaurant_id: int) -> List[Dict]:
        synonyms = self._get_restaurant_products_with_synonyms(restaurant_id)
        if not synonyms:
            return []
        
        items = []
        text_norm = normalize(text)
        
        quantity_patterns = [
            r"(\d+)\s*x?\s*([^,\n\r]+)",
            r"(un|une|deux|trois|quatre|cinq|six|sept|huit|neuf|dix)\s+([^,\n\r]+)"
        ]
        
        number_words = {
            "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, 
            "cinq": 5, "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10
        }
        
        parts = re.split(r'[,;]\s*|\s+et\s+', text_norm)
        
        for part in parts:
            part = part.strip()
            if not part:
                continue
            
            quantity = 1
            product_text = part
            
            match = re.match(r'(\d+)\s*x?\s*(.*)', part)
            if match:
                quantity = int(match.group(1))
                product_text = match.group(2).strip()
            else:
                for word, num in number_words.items():
                    if part.startswith(word + " "):
                        quantity = num
                        product_text = part[len(word):].strip()
                        break
            
            product = None
            product_text = product_text.strip()
            
            if product_text in synonyms:
                product = synonyms[product_text]
            else:
                for key, prod in synonyms.items():
                    if key in product_text or product_text in key:
                        product = prod
                        break
            
            if product:
                items.append({
                    "product_id": product.id,
                    "name": product.name,
                    "price": product.price,
                    "quantity": max(1, quantity)
                })
        
        return items

    def process_incoming_message(self, phone: str, message: str) -> str:
        context = self.get_conversation_context(phone)
        intent = self._detect_intent(message)
        
        logging.info(f"[Conakry] intent={intent} from={phone} msg={message!r}")
        
        if intent == "greeting":
            response = ("🍽️ Bonjour ! Bienvenue sur Conakry Food Connect !\n\n"
                       "Je vous aide à commander depuis les meilleurs restaurants de Conakry.\n\n"
                       "📍 Dans quelle zone êtes-vous ?\n"
                       "Tapez votre quartier : Kaloum, Kipé, Ratoma, Matam, etc.")
            context["state"] = "waiting_zone"
        
        elif intent == "select_zone" or context["state"] == "waiting_zone":
            zone_detected = None
            msg_norm = normalize(message)
            
            for zone in CONAKRY_ZONES:
                if normalize(zone) in msg_norm:
                    zone_detected = zone
                    break
            
            if zone_detected:
                context["selected_zone"] = zone_detected
                restaurants = self._get_restaurants_in_zone(zone_detected)
                
                if restaurants:
                    response = f"🍽️ Restaurants disponibles à {zone_detected} :\n\n"
                    for i, rest in enumerate(restaurants[:5], 1):
                        prep_time = rest.average_prep_time or 30
                        rating = f"{rest.rating:.1f}⭐" if rest.rating > 0 else "Nouveau"
                        response += f"{i}. *{rest.name}* ({rating})\n"
                        response += f"   ⏱️ {prep_time}min • 📍 {rest.zone}\n\n"
                    
                    response += "Tapez le numéro du restaurant ou son nom !"
                    context["state"] = "selecting_restaurant"
                    context["zone_restaurants"] = [{"id": r.id, "name": r.name} for r in restaurants]
                else:
                    response = f"😔 Pas encore de restaurants à {zone_detected}.\n\nEssayez : Kaloum, Kipé, Ratoma, Matam"
            else:
                response = ("📍 Quelle zone de Conakry ?\n\n"
                           "Zones disponibles : Kaloum, Kipé, Ratoma, Matam, Matoto, "
                           "Dixinn, Camayenne, Hamdallaye, etc.")
        
        elif context["state"] == "selecting_restaurant":
            selected_restaurant = self._find_restaurant_from_input(message, context)
            
            if selected_restaurant:
                context["selected_restaurant"] = {
                    "id": selected_restaurant.id,
                    "name": selected_restaurant.name
                }
                
                products = self.db.query(Product).filter(
                    Product.restaurant_id == selected_restaurant.id,
                    Product.available == True
                ).all()
                
                if products:
                    response = f"🍽️ *Menu {selected_restaurant.name}*\n\n"
                    for prod in products[:10]:
                        response += f"• {prod.name} - {int(prod.price):,} GNF\n"
                    
                    response += ("\n💬 *Comment commander ?*\n"
                                "Exemple : '2 riz sauce arachide et 1 coca'\n"
                                "ou simplement '1 riz gras'")
                    context["state"] = "ordering"
                else:
                    response = "😔 Ce restaurant n'a pas encore de menu disponible."
            else:
                response = "❌ Restaurant non trouvé. Tapez le numéro (1, 2, 3...) ou le nom exact."
        
        elif intent == "order" or context["state"] == "ordering":
            if not context.get("selected_restaurant"):
                response = "⚠️ Choisissez d'abord un restaurant ! Tapez votre zone."
            else:
                restaurant_id = context["selected_restaurant"]["id"]
                items = self._parse_order_items(message, restaurant_id)
                
                if items:
                    context.setdefault("current_order", [])
                    context["current_order"].extend(items)
                    
                    response = self._format_cart_summary(context)
                    context["state"] = "cart_review"
                else:
                    response = ("❌ Je n'ai pas compris votre commande.\n\n"
                               "Essayez : '2 riz sauce arachide' ou '1 poulet braisé'")
        
        elif intent == "confirm" or context["state"] == "cart_review":
            if context.get("current_order"):
                if not context.get("delivery_address"):
                    response = ("📍 *Adresse de livraison ?*\n"
                               "Exemple : 'Chez Amadou, Kipé carrefour, près de l'école'")
                    context["state"] = "need_address"
                else:
                    response = (f"{self._format_final_summary(context)}\n\n"
                               "💳 *Comment voulez-vous payer ?*\n"
                               "1️⃣ Orange Money\n"
                               "2️⃣ MTN Mobile Money\n" 
                               "3️⃣ Espèces à la livraison")
                    context["state"] = "payment_method"
            else:
                response = "🛒 Votre panier est vide ! Ajoutez des plats d'abord."
        
        elif intent == "delivery_address" or context["state"] == "need_address":
            context["delivery_address"] = message.strip()
            context["delivery_zone"] = self._detect_zone_from_address(message)
            
            delivery_fee = self._estimate_delivery_fee(context)
            context["delivery_fee"] = delivery_fee
            
            response = (f"📍 Adresse de livraison : {message.strip()}\n"
                       f"🏍️ Frais de livraison : {delivery_fee:,} GNF\n\n"
                       f"{self._format_final_summary(context)}\n\n"
                       "💳 *Comment voulez-vous payer ?*\n"
                       "1️⃣ Orange Money\n"
                       "2️⃣ MTN Mobile Money\n"
                       "3️⃣ Espèces à la livraison")
            context["state"] = "payment_method"
        
        elif intent == "payment" or context["state"] == "payment_method":
            payment_method = self._detect_payment_method(message)
            if payment_method:
                context["payment_method"] = payment_method
                
                if payment_method in ["orange_money", "mtn_momo"]:
                    response = ("📱 Entrez votre numéro de téléphone pour le paiement mobile :\n"
                               "Format : 224611223344")
                    context["state"] = "payment_phone"
                else:
                    response = asyncio.run(self._finalize_order(phone, context))
                    context["state"] = "order_confirmed"
            else:
                response = ("❌ Mode de paiement non reconnu.\n"
                           "Choisissez : Orange Money, MTN ou Espèces")
        
        elif context["state"] == "payment_phone":
            payment_phone = self._validate_guinea_phone(message)
            if payment_phone:
                context["payment_phone"] = payment_phone
                response = asyncio.run(self._finalize_order(phone, context))
                context["state"] = "order_confirmed"
            else:
                response = ("❌ Numéro invalide. Format guinéen attendu :\n"
                           "Exemple : 224611223344 ou 611223344")
        
        else:
            response = ("🤔 Je n'ai pas compris.\n\n"
                       "💡 *Actions possibles :*\n"
                       "• Tapez votre zone (Kaloum, Kipé...)\n"
                       "• Commandez : '2 riz sauce arachide'\n"
                       "• Tapez 'menu' pour voir les restaurants")

        self.update_conversation_context(phone, context)
        return response

    def _find_restaurant_from_input(self, message: str, context: Dict) -> Optional[Restaurant]:
        msg_norm = normalize(message)
        zone_restaurants = context.get("zone_restaurants", [])
        
        if msg_norm.isdigit():
            idx = int(msg_norm) - 1
            if 0 <= idx < len(zone_restaurants):
                rest_id = zone_restaurants[idx]["id"]
                return self.db.query(Restaurant).filter(Restaurant.id == rest_id).first()
        
        for rest_info in zone_restaurants:
            if normalize(rest_info["name"]) in msg_norm or msg_norm in normalize(rest_info["name"]):
                return self.db.query(Restaurant).filter(Restaurant.id == rest_info["id"]).first()
        
        return None

    def _detect_zone_from_address(self, address: str) -> str:
        addr_norm = normalize(address)
        for zone in CONAKRY_ZONES:
            if normalize(zone) in addr_norm:
                return zone
        return "Non spécifiée"

    def _detect_payment_method(self, message: str) -> Optional[str]:
        msg_norm = normalize(message)
        
        if any(w in msg_norm for w in ["orange", "orange money", "om", "1"]):
            return "orange_money"
        elif any(w in msg_norm for w in ["mtn", "mobile money", "momo", "2"]):
            return "mtn_momo"
        elif any(w in msg_norm for w in ["espece", "cash", "liquide", "3"]):
            return "cash"
        
        return None

    def _validate_guinea_phone(self, phone: str) -> Optional[str]:
        clean = re.sub(r'[^\d+]', '', phone)
        
        patterns = [
            r'^\+224([67]\d{8})$',
            r'^224([67]\d{8})$',
            r'^([67]\d{8})$'
        ]
        
        for pattern in patterns:
            match = re.match(pattern, clean)
            if match:
                number = match.group(1) if len(match.groups()) > 0 else clean
                return f"224{number}" if not clean.startswith('224') else clean
        
        return None

    def _estimate_delivery_fee(self, context: Dict) -> int:
        base_fee = config.BASE_DELIVERY_FEE
        delivery_zone = context.get("delivery_zone", "")
        
        if any(zone in delivery_zone.lower() for zone in ["matoto", "sonfonia", "nongo"]):
            return base_fee + 1000
        elif any(zone in delivery_zone.lower() for zone in ["hamdallaye", "koloma"]):
            return base_fee + 500
        
        return base_fee

    def _format_cart_summary(self, context: Dict) -> str:
        cart = context.get("current_order", [])
        if not cart:
            return "🛒 Panier vide"
        
        restaurant_name = context.get("selected_restaurant", {}).get("name", "Restaurant")
        subtotal = sum(item["price"] * item["quantity"] for item in cart)
        
        lines = [f"🛒 *Panier {restaurant_name}*\n"]
        for item in cart:
            price_total = item["price"] * item["quantity"]
            lines.append(f"• {item['quantity']}× {item['name']} - {int(price_total):,} GNF")
        
        lines.append(f"\n💰 *Sous-total* : {int(subtotal):,} GNF")
        lines.append("\nTapez *confirmer* pour continuer ou ajoutez d'autres plats !")
        
        return "\n".join(lines)

    def _format_final_summary(self, context: Dict) -> str:
        cart = context.get("current_order", [])
        subtotal = sum(item["price"] * item["quantity"] for item in cart)
        delivery_fee = context.get("delivery_fee", config.BASE_DELIVERY_FEE)
        total = subtotal + delivery_fee
        
        restaurant_name = context.get("selected_restaurant", {}).get("name", "Restaurant")
        
        lines = [f"📋 *Récapitulatif final*\n"]
        lines.append(f"🍽️ Restaurant : {restaurant_name}")
        lines.append(f"📍 Livraison : {context.get('delivery_address', 'Non définie')}\n")
        
        for item in cart:
            price_total = item["price"] * item["quantity"]
            lines.append(f"• {item['quantity']}× {item['name']} - {int(price_total):,} GNF")
        
        lines.append(f"\n💰 Sous-total : {int(subtotal):,} GNF")
        lines.append(f"🏍️ Livraison : {int(delivery_fee):,} GNF")
        lines.append(f"💳 *TOTAL : {int(total):,} GNF*")
        
        return "\n".join(lines)

    async def _finalize_order(self, customer_phone: str, context: Dict) -> str:
        try:
            cart = context.get("current_order", [])
            restaurant_id = context.get("selected_restaurant", {}).get("id")
            delivery_address = context.get("delivery_address")
            payment_method = context.get("payment_method", "cash")
            payment_phone = context.get("payment_phone")
            
            if not all([cart, restaurant_id, delivery_address]):
                return "❌ Informations manquantes pour finaliser la commande."
            
            order = await self.order_service.create_order(
                customer_phone=customer_phone,
                restaurant_id=restaurant_id,
                items=cart,
                delivery_address=delivery_address,
                payment_method=payment_method,
                payment_phone=payment_phone,
                delivery_fee=context.get("delivery_fee", config.BASE_DELIVERY_FEE)
            )
            
            if not order:
                return "❌ Erreur lors de la création de la commande."
            
            await self._notify_restaurant_new_order(order)
            
            if payment_method == "orange_money":
                await self._initiate_orange_money_payment(order)
            elif payment_method == "mtn_momo":
                await self._initiate_mtn_payment(order)
            
            payment_text = {
                "orange_money": f"💳 Paiement Orange Money sera demandé au {payment_phone}",
                "mtn_momo": f"💳 Paiement MTN MoMo sera demandé au {payment_phone}",
                "cash": "💵 Paiement en espèces à la livraison"
            }.get(payment_method, "")
            
            return (f"🎉 *Commande #{order.id} confirmée !*\n\n"
                   f"🍽️ Restaurant : {context.get('selected_restaurant', {}).get('name')}\n"
                   f"📍 Livraison : {delivery_address}\n"
                   f"💰 Total : {int(order.total_amount):,} GNF\n"
                   f"{payment_text}\n\n"
                   f"⏱️ Temps estimé : {order.estimated_delivery_time} min\n"
                   f"📞 Support : tapez 'aide' si besoin")
            
        except Exception as e:
            logging.error(f"Order finalization error: {e}")
            return "❌ Erreur lors de la finalisation. Réessayez dans quelques instants."

    async def _notify_restaurant_new_order(self, order: Order):
        try:
            restaurant = self.db.query(Restaurant).filter(Restaurant.id == order.restaurant_id).first()
            if not restaurant or not restaurant.phone_number:
                return
            
            items = json.loads(order.items)
            items_text = "\n".join([f"• {item['quantity']}× {item['name']}" for item in items])
            
            message = (f"🍽️ *NOUVELLE COMMANDE #{order.id}*\n\n"
                      f"📱 Client : {order.customer.phone_number}\n"
                      f"📍 Livraison : {order.delivery_address}\n"
                      f"💰 Total : {int(order.total_amount):,} GNF\n\n"
                      f"*Articles :*\n{items_text}\n\n"
                      f"💳 Paiement : {order.payment_method}\n\n"
                      f"*Actions :* Répondez :\n"
                      f"• *accepter {order.id}* - pour accepter\n"
                      f"• *refuser {order.id}* - pour refuser\n"
                      f"• *temps {order.id} 45* - modifier le temps (45min)")
            
            success = self.whatsapp.send_message(restaurant.phone_number, message)
            
            if not success:
                self.whatsapp.send_template(restaurant.phone_number, "hello_world", "fr")
                simple_msg = f"Nouvelle commande #{order.id} - Total: {int(order.total_amount):,} GNF"
                self.whatsapp.send_message(restaurant.phone_number, simple_msg)
                
        except Exception as e:
            logging.error(f"Restaurant notification error: {e}")

    async def _initiate_orange_money_payment(self, order: Order):
        try:
            om_service = OrangeMoneyService()
            result = await om_service.initiate_payment(
                phone=order.payment_phone,
                amount=int(order.total_amount),
                order_id=order.id
            )
            
            if result["success"]:
                order.payment_status = PaymentStatus.PROCESSING
                self.db.commit()
                
                payment_url = result.get("data", {}).get("payment_url")
                if payment_url:
                    msg = (f"💳 *Paiement Orange Money*\n\n"
                          f"Montant : {int(order.total_amount):,} GNF\n"
                          f"Commande : #{order.id}\n\n"
                          f"👆 Cliquez pour payer :\n{payment_url}")
                    self.whatsapp.send_message(order.customer.phone_number, msg)
            else:
                logging.error(f"Orange Money payment failed: {result}")
                
        except Exception as e:
            logging.error(f"Orange Money initiation error: {e}")

    async def _initiate_mtn_payment(self, order: Order):
        try:
            mtn_service = MTNMoMoService()
            result = await mtn_service.request_to_pay(
                phone=order.payment_phone,
                amount=int(order.total_amount),
                order_id=order.id
            )
            
            if result["success"]:
                order.payment_status = PaymentStatus.PROCESSING
                self.db.commit()
                
                msg = (f"💳 *Paiement MTN MoMo*\n\n"
                      f"Montant : {int(order.total_amount):,} GNF\n"
                      f"Commande : #{order.id}\n\n"
                      f"📱 Vous allez recevoir une demande de paiement sur votre téléphone.\n"
                      f"Composez *#150# puis suivez les instructions.")
                self.whatsapp.send_message(order.customer.phone_number, msg)
            else:
                logging.error(f"MTN MoMo payment failed: {result}")
                
        except Exception as e:
            logging.error(f"MTN MoMo initiation error: {e}")

# -----------------------------------------------------------------------------
# Service de Commande
# -----------------------------------------------------------------------------
class OrderServiceConakry:
    def __init__(self, db: Session):
        self.db = db

    def get_or_create_customer(self, phone_number: str) -> Customer:
        customer = self.db.query(Customer).filter(Customer.phone_number == phone_number).first()
        if not customer:
            customer = Customer(phone_number=phone_number)
            self.db.add(customer)
            self.db.commit()
            self.db.refresh(customer)
        return customer

    async def create_order(self, customer_phone: str, restaurant_id: int, items: List[Dict], 
                          delivery_address: str, payment_method: str, payment_phone: str = None,
                          delivery_fee: int = None) -> Optional[Order]:
        try:
            customer = self.get_or_create_customer(customer_phone)
            restaurant = self.db.query(Restaurant).filter(Restaurant.id == restaurant_id).first()
            
            if not restaurant:
                return None
            
            subtotal = sum(item["price"] * item["quantity"] for item in items)
            delivery_fee = delivery_fee or config.BASE_DELIVERY_FEE
            total_amount = subtotal + delivery_fee
            
            restaurant_commission = subtotal * restaurant.commission_rate
            driver_commission = delivery_fee * 0.70
            
            prep_time = restaurant.average_prep_time or 30
            delivery_time = 15
            estimated_total_time = prep_time + delivery_time
            
            order = Order(
                customer_id=customer.id,
                restaurant_id=restaurant_id,
                items=json.dumps(items),
                subtotal=subtotal,
                delivery_fee=delivery_fee,
                total_amount=total_amount,
                restaurant_commission=restaurant_commission,
                driver_commission=driver_commission,
                delivery_address=delivery_address,
                payment_method=payment_method,
                payment_phone=payment_phone,
                estimated_delivery_time=estimated_total_time,
                status=OrderStatus.PENDING
            )
            
            self.db.add(order)
            self.db.commit()
            self.db.refresh(order)
            
            customer.total_orders += 1
            customer.total_spent += total_amount
            restaurant.total_orders += 1
            self.db.commit()
            
            return order
            
        except Exception as e:
            logging.error(f"Create order error: {e}")
            self.db.rollback()
            return None

# -----------------------------------------------------------------------------
# API FastAPI
# -----------------------------------------------------------------------------
app = FastAPI(title="Conakry Food Connect API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    try:
        await init_guinea_sample_data()
        logging.info("Startup: Guinea sample data initialized")
    except Exception as e:
        logging.error(f"Startup error: {e}")

@app.get("/")
async def root():
    return {
        "message": "Conakry Food Connect API", 
        "status": "running",
        "version": "1.0.0",
        "zones": CONAKRY_ZONES
    }

@app.get("/health")
async def health_check(db: Session = Depends(get_db)):
    try:
        restaurant_count = db.query(Restaurant).count()
        order_count = db.query(Order).count()
        
        return {
            "status": "ok",
            "database": "connected",
            "restaurants": restaurant_count,
            "orders": order_count,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}
from fastapi.responses import PlainTextResponse 
@app.get("/webhook")
async def verify_webhook(request: Request):
    verify_token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    
    if verify_token == config.WHATSAPP_VERIFY_TOKEN:
        return PlainTextResponse(content=challenge)
    
    raise HTTPException(status_code=403, detail="Invalid verification token")

@app.post("/webhook")
async def handle_webhook(request: Request, db: Session = Depends(get_db)):
    try:
        body = await request.json()
        logging.info(f"Webhook received: {json.dumps(body, indent=2)[:1000]}")

        entries = body.get("entry", [])
        if not entries:
            return JSONResponse({"status": "no_entries"})

        wa_service = WhatsAppService()
        processed = False

        for entry in entries:
            for change in entry.get("changes", []):
                value = change.get("value", {})
                messages = value.get("messages", [])

                for msg in messages:
                    from_number = msg.get("from", "")
                    
                    conv_service = ConversationServiceConakry(db)
                    
                    if msg.get("type") == "text":
                        text = msg.get("text", {}).get("body", "")
                        if text.strip():
                            response = conv_service.process_incoming_message(from_number, text.strip())
                            wa_service.send_message(from_number, response)
                            processed = True

        return JSONResponse({"status": "success" if processed else "no_action"})

    except Exception as e:
        logging.exception(f"Webhook error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

# -----------------------------------------------------------------------------
# Initialisation données
# -----------------------------------------------------------------------------
async def init_guinea_sample_data():
    db = SessionLocal()
    try:
        if db.query(Restaurant).count() == 0:
            restaurants = [
                Restaurant(
                    name="Chez Fatou",
                    phone_number="224611223344",
                    address="Kipé, près du rond-point",
                    zone="Kipé",
                    latitude=9.5900,
                    longitude=-13.6100,
                    delivery_zones=json.dumps(["Kipé", "Ratoma", "Matam"]),
                    average_prep_time=25
                ),
                Restaurant(
                    name="Restaurant Barita",
                    phone_number="224622334455",
                    address="Kaloum, Avenue de la République",
                    zone="Kaloum",
                    latitude=9.5380,
                    longitude=-13.6773,
                    delivery_zones=json.dumps(["Kaloum", "Dixinn", "Camayenne"]),
                    average_prep_time=30
                ),
                Restaurant(
                    name="Le Délice de Ratoma",
                    phone_number="224633445566",
                    address="Ratoma Centre",
                    zone="Ratoma",
                    latitude=9.5800,
                    longitude=-13.6300,
                    delivery_zones=json.dumps(["Ratoma", "Kipé", "Hamdallaye"]),
                    average_prep_time=20
                )
            ]
            
            for restaurant in restaurants:
                db.add(restaurant)
            db.commit()
            
            rest_fatou = db.query(Restaurant).filter(Restaurant.name == "Chez Fatou").first()
            if rest_fatou:
                products_fatou = [
                    Product(restaurant_id=rest_fatou.id, name="Riz sauce arachide", description="Riz blanc avec sauce aux arachides", price=15000, category="Plat principal"),
                    Product(restaurant_id=rest_fatou.id, name="Riz au gras", description="Riz cuisiné à l'huile de palme", price=12000, category="Plat principal"),
                    Product(restaurant_id=rest_fatou.id, name="Fouti fonio", description="Fonio aux légumes", price=18000, category="Plat principal"),
                    Product(restaurant_id=rest_fatou.id, name="Poisson braisé", description="Poisson grillé aux épices", price=25000, category="Plat principal"),
                    Product(restaurant_id=rest_fatou.id, name="Coca-Cola", description="Boisson gazeuse 33cl", price=3000, category="Boisson"),
                    Product(restaurant_id=rest_fatou.id, name="Jus d'ananas", description="Jus naturel d'ananas", price=5000, category="Boisson"),
                ]
                
                for product in products_fatou:
                    db.add(product)
            
            rest_barita = db.query(Restaurant).filter(Restaurant.name == "Restaurant Barita").first()
            if rest_barita:
                products_barita = [
                    Product(restaurant_id=rest_barita.id, name="Atiéké poisson", description="Atiéké avec poisson grillé", price=20000, category="Plat principal"),
                    Product(restaurant_id=rest_barita.id, name="Poulet yassa", description="Poulet mariné aux oignons", price=22000, category="Plat principal"),
                    Product(restaurant_id=rest_barita.id, name="Salade de fruits", description="Mélange de fruits frais", price=8000, category="Dessert"),
                    Product(restaurant_id=rest_barita.id, name="Eau minérale", description="Eau minérale 50cl", price=2000, category="Boisson"),
                ]
                
                for product in products_barita:
                    db.add(product)
            
            db.commit()
        
        if db.query(DeliveryDriver).count() == 0:
            drivers = [
                DeliveryDriver(
                    name="Mamadou Diallo",
                    phone_number="224677889900",
                    zone="Kipé",
                    current_latitude=9.5900,
                    current_longitude=-13.6100
                ),
                DeliveryDriver(
                    name="Ibrahima Sow",
                    phone_number="224688990011",
                    zone="Kaloum",
                    current_latitude=9.5380,
                    current_longitude=-13.6773
                ),
                DeliveryDriver(
                    name="Alpha Barry",
                    phone_number="224699001122",
                    zone="Ratoma",
                    current_latitude=9.5800,
                    current_longitude=-13.6300
                )
            ]
            
            for driver in drivers:
                db.add(driver)
            db.commit()
        
        logging.info("✅ Guinea sample data initialized successfully")
        
    except Exception as e:
        logging.error(f"Sample data initialization error: {e}")
        db.rollback()
    finally:
        db.close()

def normalize(s: str) -> str:
    if not s:
        return ""
    s = s.lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = s.replace("-", " ").replace("'", " ").strip()
    return s

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port, reload=True)