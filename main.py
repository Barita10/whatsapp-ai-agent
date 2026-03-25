# main.py - Version Interactive Complète avec GPS et Paiements
# Système de commande restaurant avec géolocalisation et Mobile Money
# WhatsApp Business API + GPS + Orange Money/MTN MoMo + Enregistrement Restaurants + Gestion Menus

import os
import re
import json
import logging
import unicodedata
import secrets
import hashlib
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from math import radians, cos, sin, asin, sqrt

from fastapi import FastAPI, HTTPException, Depends, Request, Form
from fastapi.responses import JSONResponse, PlainTextResponse, HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy import create_engine, Column, Integer, String, DateTime, Float, Text, ForeignKey, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship

import requests
import asyncio

# ─────────────────────────────────────────────────────────────────────────────
# Import du module Payment (remplace OrangeMoneyService + MTNMoMoService)
# ─────────────────────────────────────────────────────────────────────────────
from payment import (
    PaymentService,
    PaymentConfig,
    PaymentRequest,
    DisbursementRequest,
    PaymentStatus as MoMoStatus,
    router as payment_router,
)

payment_service = PaymentService(PaymentConfig())

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
class Config:
    WHATSAPP_TOKEN: str = os.getenv("WHATSAPP_TOKEN", "your_whatsapp_token")
    WHATSAPP_PHONE_ID: str = os.getenv("WHATSAPP_PHONE_ID", "your_phone_id")
    WHATSAPP_VERIFY_TOKEN: str = os.getenv("WHATSAPP_VERIFY_TOKEN", "Aminat041197")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./conakry_food.db")

    # Google Maps pour géolocalisation
    GOOGLE_MAPS_API_KEY: str = os.getenv("GOOGLE_MAPS_API_KEY", "your_google_maps_key")

    ADMIN_PHONE: str = os.getenv("ADMIN_PHONE", "33600000000")
    BASE_DELIVERY_FEE: int = int(os.getenv("BASE_DELIVERY_FEE", "2000"))
    FEE_PER_KM: int = int(os.getenv("FEE_PER_KM", "500"))

config = Config()

# -----------------------------------------------------------------------------
# DB Models avec géolocalisation
# -----------------------------------------------------------------------------
engine = create_engine(config.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class OrderStatus:
    PENDING    = "pending"
    CONFIRMED  = "confirmed"
    PREPARING  = "preparing"
    READY      = "ready"
    DELIVERING = "delivering"
    DELIVERED  = "delivered"
    CANCELLED  = "cancelled"

class PaymentStatus:
    PENDING    = "pending"
    PROCESSING = "processing"
    COMPLETED  = "completed"
    FAILED     = "failed"

class Restaurant(Base):
    __tablename__ = "restaurants"

    id               = Column(Integer, primary_key=True, index=True)
    name             = Column(String, index=True)
    phone_number     = Column(String, unique=True, index=True)
    address          = Column(Text)
    zone             = Column(String)
    latitude         = Column(Float)
    longitude        = Column(Float)
    is_active        = Column(Boolean, default=True)
    commission_rate  = Column(Float, default=0.15)
    delivery_zones   = Column(Text)
    average_prep_time= Column(Integer, default=30)
    rating           = Column(Float, default=0.0)
    total_orders     = Column(Integer, default=0)
    created_at       = Column(DateTime, default=datetime.utcnow)

    products = relationship("Product", back_populates="restaurant")
    orders   = relationship("Order", back_populates="restaurant")

class Customer(Base):
    __tablename__ = "customers"

    id           = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, unique=True, index=True)
    name         = Column(String)
    address      = Column(Text)
    zone         = Column(String)
    latitude     = Column(Float)
    longitude    = Column(Float)
    total_orders = Column(Integer, default=0)
    total_spent  = Column(Float, default=0.0)
    created_at   = Column(DateTime, default=datetime.utcnow)

    orders = relationship("Order", back_populates="customer")

class Product(Base):
    __tablename__ = "products"

    id            = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"))
    name          = Column(String, index=True)
    description   = Column(Text)
    price         = Column(Float)
    category      = Column(String)
    image_url     = Column(String)
    available     = Column(Boolean, default=True)

    restaurant = relationship("Restaurant", back_populates="products")

class DeliveryDriver(Base):
    __tablename__ = "delivery_drivers"

    id                 = Column(Integer, primary_key=True, index=True)
    phone_number       = Column(String, unique=True, index=True)
    name               = Column(String)
    zone               = Column(String)
    is_available       = Column(Boolean, default=True)
    current_latitude   = Column(Float)
    current_longitude  = Column(Float)
    rating             = Column(Float, default=0.0)
    total_deliveries   = Column(Integer, default=0)
    created_at         = Column(DateTime, default=datetime.utcnow)

    orders = relationship("Order", back_populates="driver")

class Order(Base):
    __tablename__ = "orders"

    id            = Column(Integer, primary_key=True, index=True)
    customer_id   = Column(Integer, ForeignKey("customers.id"))
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"))
    driver_id     = Column(Integer, ForeignKey("delivery_drivers.id"), nullable=True)

    status         = Column(String, default=OrderStatus.PENDING)
    payment_status = Column(String, default=PaymentStatus.PENDING)
    payment_method = Column(String)
    payment_phone  = Column(String)
    payment_id     = Column(String)          # ← ID retourné par MTN / sandbox

    items                  = Column(Text)
    subtotal               = Column(Float)
    delivery_fee           = Column(Float)
    restaurant_commission  = Column(Float)
    platform_margin        = Column(Float)   # ← ta marge calculée
    total_amount           = Column(Float)

    delivery_address   = Column(Text)
    delivery_latitude  = Column(Float)
    delivery_longitude = Column(Float)
    delivery_zone      = Column(String)
    distance_km        = Column(Float)

    notes                  = Column(Text)
    estimated_delivery_time= Column(Integer)

    created_at   = Column(DateTime, default=datetime.utcnow)
    delivered_at = Column(DateTime)

    customer   = relationship("Customer", back_populates="orders")
    restaurant = relationship("Restaurant", back_populates="orders")
    driver     = relationship("DeliveryDriver", back_populates="orders")

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# -----------------------------------------------------------------------------
# Service d'authentification Restaurant
# -----------------------------------------------------------------------------
class RestaurantAuth:
    def __init__(self, db: Session):
        self.db = db

    def generate_login_link(self, restaurant_phone: str) -> str:
        token = secrets.token_urlsafe(32)
        login_token = {
            "phone": restaurant_phone,
            "token": token,
            "expires_at": (datetime.utcnow() + timedelta(hours=24)).isoformat(),
            "used": False
        }
        self.save_login_token(login_token)
        return f"http://localhost:8000/restaurant/login/{token}"

    def save_login_token(self, token_data: Dict):
        filename = "restaurant_tokens.json"
        if os.path.exists(filename):
            with open(filename, 'r') as f:
                tokens = json.load(f)
        else:
            tokens = []
        tokens.append(token_data)
        now = datetime.utcnow().isoformat()
        tokens = [t for t in tokens if t.get("expires_at", "") > now]
        with open(filename, 'w') as f:
            json.dump(tokens, f, indent=2)

    def verify_token(self, token: str) -> Optional[str]:
        try:
            with open("restaurant_tokens.json", 'r') as f:
                tokens = json.load(f)
            now = datetime.utcnow().isoformat()
            for token_data in tokens:
                if (token_data.get("token") == token
                        and not token_data.get("used")
                        and token_data.get("expires_at", "") > now):
                    token_data["used"] = True
                    with open("restaurant_tokens.json", 'w') as f:
                        json.dump(tokens, f, indent=2)
                    return token_data.get("phone")
            return None
        except FileNotFoundError:
            return None

# -----------------------------------------------------------------------------
# Fonctions utilitaires
# -----------------------------------------------------------------------------
def save_registration_data(data: Dict):
    filename = "pending_registrations.json"
    if os.path.exists(filename):
        with open(filename, 'r', encoding='utf-8') as f:
            registrations = json.load(f)
    else:
        registrations = []
    registrations.append(data)
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(registrations, f, indent=2, ensure_ascii=False)

def get_zone_coordinates(zone: str) -> Dict:
    zone_coordinates = {
        "Kipé":       {"lat": 9.5900, "lng": -13.6100},
        "Kaloum":     {"lat": 9.5380, "lng": -13.6773},
        "Ratoma":     {"lat": 9.5800, "lng": -13.6300},
        "Matam":      {"lat": 9.5600, "lng": -13.6400},
        "Matoto":     {"lat": 9.5500, "lng": -13.6200},
        "Dixinn":     {"lat": 9.5450, "lng": -13.6850},
        "Camayenne":  {"lat": 9.5350, "lng": -13.6900},
        "Hamdallaye": {"lat": 9.5700, "lng": -13.6250},
        "Sonfonia":   {"lat": 9.5950, "lng": -13.5900},
        "Nongo":      {"lat": 9.6000, "lng": -13.5800},
    }
    return zone_coordinates.get(zone, {"lat": 9.5091, "lng": -13.7122})

# -----------------------------------------------------------------------------
# Service de géolocalisation
# -----------------------------------------------------------------------------
class GeolocationService:
    def __init__(self):
        self.google_api_key = config.GOOGLE_MAPS_API_KEY

    def haversine_distance(self, lat1, lon1, lat2, lon2) -> float:
        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        return 2 * asin(sqrt(a)) * 6371

    def calculate_delivery_fee(self, distance_km: float) -> int:
        if distance_km <= 2:
            return config.BASE_DELIVERY_FEE
        elif distance_km <= 5:
            return config.BASE_DELIVERY_FEE + 1000
        elif distance_km <= 10:
            return config.BASE_DELIVERY_FEE + 2000
        else:
            return config.BASE_DELIVERY_FEE + 2000 + int((distance_km - 10) * config.FEE_PER_KM)

    def estimate_delivery_time(self, distance_km: float, prep_time: int = 30) -> int:
        travel_time = int((distance_km / 20) * 60)
        return prep_time + travel_time

    async def geocode_address(self, address: str, zone: str) -> Dict:
        return get_zone_coordinates(zone)

# -----------------------------------------------------------------------------
# WhatsApp Service
# -----------------------------------------------------------------------------
class WhatsAppService:
    def __init__(self):
        self.token    = config.WHATSAPP_TOKEN
        self.phone_id = config.WHATSAPP_PHONE_ID
        self.base_url = f"https://graph.facebook.com/v22.0/{self.phone_id}"

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def send_message(self, to: str, message: str) -> bool:
        url  = f"{self.base_url}/messages"
        data = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": message},
        }
        try:
            r  = requests.post(url, json=data, headers=self._headers(), timeout=15)
            ok = r.status_code in (200, 201)
            if ok:
                logging.info(f"✅ Message sent to {to}")
            else:
                logging.error(f"❌ Message failed {r.status_code}: {r.text}")
            return ok
        except Exception as e:
            logging.error(f"❌ Send error: {e}")
            return False

    def send_button_message(self, to: str, body: str, buttons: List[Dict]) -> bool:
        url  = f"{self.base_url}/messages"
        data = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body},
                "action": {"buttons": buttons[:3]},
            },
        }
        try:
            r  = requests.post(url, json=data, headers=self._headers(), timeout=15)
            ok = r.status_code in (200, 201)
            if not ok:
                logging.error(f"Button response: {r.text}")
            return ok
        except Exception as e:
            logging.error(f"Button error: {e}")
            return False

    def send_list_message(self, to: str, body: str, button_text: str, sections: List[Dict]) -> bool:
        url  = f"{self.base_url}/messages"
        data = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": body},
                "action": {"button": button_text, "sections": sections},
            },
        }
        try:
            r  = requests.post(url, json=data, headers=self._headers(), timeout=15)
            ok = r.status_code in (200, 201)
            if not ok:
                logging.error(f"List response: {r.text}")
            return ok
        except Exception as e:
            logging.error(f"List error: {e}")
            return False

    def send_location_request(self, to: str) -> bool:
        body    = "📍 Partagez votre localisation pour calculer les frais de livraison"
        buttons = [{"type": "reply", "reply": {"id": "share_location", "title": "📍 Partager"}}]
        return self.send_button_message(to, body, buttons)

# -----------------------------------------------------------------------------
# Service de Conversation Interactive avec GPS
# -----------------------------------------------------------------------------
class InteractiveConversationService:
    def __init__(self, db: Session):
        self.db          = db
        self.whatsapp    = WhatsAppService()
        self.geo_service = GeolocationService()

    def get_conversation_context(self, phone: str) -> Dict:
        from sqlalchemy.orm import Session as S
        conv = self.db.query(Conversation).filter(Conversation.phone_number == phone).first()
        if conv and conv.context:
            return json.loads(conv.context)
        return {
            "state": "new",
            "current_order": [],
            "selected_restaurant": None,
            "selected_zone": None,
            "delivery_address": None,
            "delivery_coords": None,
        }

    def update_conversation_context(self, phone: str, context: Dict):
        conv = self.db.query(Conversation).filter(Conversation.phone_number == phone).first()
        if not conv:
            conv = Conversation(phone_number=phone)
            self.db.add(conv)
        conv.context          = json.dumps(context)
        conv.last_interaction = datetime.utcnow()
        self.db.commit()

    # ── Handlers messages ────────────────────────────────────────────────────

    def handle_text_message(self, phone: str, message: str):
        context = self.get_conversation_context(phone)

        registration_keywords = [
            "enregistrer restaurant", "devenir partenaire",
            "rejoindre plateforme", "inscription restaurant",
            "partenariat", "livraison restaurant",
        ]
        if any(k in message.lower() for k in registration_keywords):
            self.whatsapp.send_message(phone,
                "🍽️ Pour enregistrer votre restaurant, rendez-vous sur:\n\n"
                "http://localhost:8000/register-restaurant\n\n"
                "Vous pourrez remplir le formulaire et nous examinerons votre demande dans les 24-48h.")
            return

        if context.get("state") == "waiting_address":
            context["delivery_address"] = message
            zone   = context.get("selected_zone", "Conakry")
            coords = asyncio.run(self.geo_service.geocode_address(message, zone))
            context["delivery_coords"] = coords

            restaurant_id = context.get("selected_restaurant", {}).get("id")
            if restaurant_id:
                restaurant = self.db.query(Restaurant).filter(Restaurant.id == restaurant_id).first()
                if restaurant:
                    distance = self.geo_service.haversine_distance(
                        restaurant.latitude, restaurant.longitude,
                        coords["lat"], coords["lng"]
                    )
                    context["distance_km"]    = round(distance, 1)
                    context["delivery_fee"]   = self.geo_service.calculate_delivery_fee(distance)
                    context["estimated_time"] = self.geo_service.estimate_delivery_time(
                        distance, restaurant.average_prep_time
                    )

            self.send_payment_options(phone, context)
            context["state"] = "payment_selection"

        elif context.get("state") == "waiting_payment_phone":
            payment_phone        = re.sub(r'[^\d+]', '', message)
            context["payment_phone"] = payment_phone
            asyncio.run(self.finalize_order(phone, context))
            context["state"] = "order_completed"

        else:
            self.send_welcome_with_zones(phone)
            context["state"] = "zone_selection"

        self.update_conversation_context(phone, context)

    def handle_location_message(self, phone: str, latitude: float, longitude: float):
        context = self.get_conversation_context(phone)
        context["delivery_coords"] = {"lat": latitude, "lng": longitude}

        restaurant_id = context.get("selected_restaurant", {}).get("id")
        if restaurant_id:
            restaurant = self.db.query(Restaurant).filter(Restaurant.id == restaurant_id).first()
            if restaurant:
                distance = self.geo_service.haversine_distance(
                    restaurant.latitude, restaurant.longitude, latitude, longitude
                )
                context["distance_km"]    = round(distance, 1)
                context["delivery_fee"]   = self.geo_service.calculate_delivery_fee(distance)
                context["estimated_time"] = self.geo_service.estimate_delivery_time(
                    distance, restaurant.average_prep_time
                )

        self.whatsapp.send_message(phone, "📍 Localisation reçue! Précisez l'adresse exacte (rue, repère):")
        context["state"] = "waiting_address"
        self.update_conversation_context(phone, context)

    def handle_button_reply(self, phone: str, button_id: str, button_text: str):
        context = self.get_conversation_context(phone)

        if button_id == "add_more":
            restaurant_id = context.get("selected_restaurant", {}).get("id")
            if restaurant_id:
                self.send_product_list(phone, restaurant_id)
            context["state"] = "product_selection"

        elif button_id == "confirm_order":
            self.whatsapp.send_location_request(phone)
            self.whatsapp.send_message(phone, "📍 Partagez votre localisation WhatsApp ou entrez votre adresse complète:")
            context["state"] = "waiting_address"

        elif button_id == "cancel_order":
            context = {"state": "new", "current_order": []}
            self.whatsapp.send_message(phone, "❌ Commande annulée.")

        elif button_id in ("pay_cash", "pay_om", "pay_mtn"):
            payment_method = {
                "pay_cash": "cash",
                "pay_om":   "orange_money",
                "pay_mtn":  "mtn_momo",
            }.get(button_id, "cash")

            context["payment_method"] = payment_method

            if payment_method != "cash":
                self.whatsapp.send_message(phone, f"📱 Entrez votre numéro {button_text}:")
                context["state"] = "waiting_payment_phone"
            else:
                asyncio.run(self.finalize_order(phone, context))
                context["state"] = "order_completed"

        self.update_conversation_context(phone, context)

    def handle_list_reply(self, phone: str, item_id: str):
        context = self.get_conversation_context(phone)

        if item_id.startswith("zone_"):
            zone                   = item_id.replace("zone_", "")
            context["selected_zone"] = zone
            self.send_restaurant_list(phone, zone)
            context["state"] = "restaurant_selection"

        elif item_id.startswith("rest_"):
            restaurant_id = int(item_id.replace("rest_", ""))
            restaurant    = self.db.query(Restaurant).filter(Restaurant.id == restaurant_id).first()
            if restaurant:
                context["selected_restaurant"] = {
                    "id":   restaurant.id,
                    "name": restaurant.name,
                    "lat":  restaurant.latitude,
                    "lng":  restaurant.longitude,
                }
                self.send_product_list(phone, restaurant_id)
                context["state"] = "product_selection"

        elif item_id.startswith("prod_"):
            parts = item_id.split("_")
            if len(parts) == 3:
                product_id = int(parts[1])
                quantity   = int(parts[2])
                product    = self.db.query(Product).filter(Product.id == product_id).first()
                if product:
                    cart_item     = {"product_id": product.id, "name": product.name,
                                     "price": product.price, "quantity": quantity}
                    current_order = context.get("current_order", [])
                    found = False
                    for item in current_order:
                        if item["product_id"] == product.id:
                            item["quantity"] += quantity
                            found = True
                            break
                    if not found:
                        current_order.append(cart_item)
                    context["current_order"] = current_order
                    self.send_cart_summary(phone, context)
                    context["state"] = "cart_review"

        self.update_conversation_context(phone, context)

    # ── UI messages ──────────────────────────────────────────────────────────

    def send_welcome_with_zones(self, phone: str):
        body     = "🍽️ Bienvenue sur Conakry Food!\n\nChoisissez votre zone de livraison:"
        sections = [{"title": "Zones de livraison", "rows": []}]
        all_zones = ["Kipé", "Kaloum", "Ratoma", "Matam", "Matoto",
                     "Dixinn", "Camayenne", "Hamdallaye", "Sonfonia", "Nongo"]
        for zone in all_zones[:10]:
            sections[0]["rows"].append({"id": f"zone_{zone}", "title": zone, "description": "Livraison disponible"})
        self.whatsapp.send_list_message(phone, body, "📍 Sélectionner", sections)

    def send_restaurant_list(self, phone: str, zone: str):
        restaurants = self.db.query(Restaurant).filter(
            Restaurant.is_active == True, Restaurant.zone == zone
        ).all()
        if not restaurants:
            self.whatsapp.send_message(phone, f"😔 Pas de restaurants à {zone}")
            self.send_welcome_with_zones(phone)
            return
        sections = [{"title": f"Restaurants à {zone}", "rows": []}]
        for rest in restaurants[:10]:
            rating = f"⭐{rest.rating:.1f}" if rest.rating > 0 else "Nouveau"
            sections[0]["rows"].append({
                "id":          f"rest_{rest.id}",
                "title":       rest.name[:24],
                "description": f"⏱️{rest.average_prep_time or 30}min • {rating}"[:72],
            })
        self.whatsapp.send_list_message(phone, f"🍽️ Restaurants disponibles à {zone}:", "📋 Voir", sections)

    def send_product_list(self, phone: str, restaurant_id: int):
        restaurant = self.db.query(Restaurant).filter(Restaurant.id == restaurant_id).first()
        products   = self.db.query(Product).filter(
            Product.restaurant_id == restaurant_id, Product.available == True
        ).all()
        if not products:
            self.whatsapp.send_message(phone, f"😔 Menu non disponible pour {restaurant.name}")
            return
        sections    = [{"title": "Menu", "rows": []}]
        for prod in products[:5]:
            sections[0]["rows"].append({
                "id":          f"prod_{prod.id}_1",
                "title":       prod.name[:24],
                "description": f"{int(prod.price):,} GNF",
            })
        if products:
            qty_section = {"title": "Quantités x2 et x3", "rows": []}
            for prod in products[:2]:
                for qty in [2, 3]:
                    qty_section["rows"].append({
                        "id":          f"prod_{prod.id}_{qty}",
                        "title":       f"{qty}x {prod.name[:18]}",
                        "description": f"{int(prod.price * qty):,} GNF",
                    })
            sections.append(qty_section)
        self.whatsapp.send_list_message(phone, f"📋 Menu - {restaurant.name}", "🍽️ Choisir", sections)

    def send_cart_summary(self, phone: str, context: Dict):
        cart = context.get("current_order", [])
        if not cart:
            return
        restaurant_name = context.get("selected_restaurant", {}).get("name", "Restaurant")
        subtotal        = sum(item["price"] * item["quantity"] for item in cart)
        lines           = [f"🛒 *Panier - {restaurant_name}*\n"]
        for item in cart:
            lines.append(f"• {item['quantity']}× {item['name']}: {int(item['price'] * item['quantity']):,} GNF")
        lines.append(f"\n💰 Sous-total: {int(subtotal):,} GNF")
        lines.append("🏍️ Livraison: calculée selon votre distance")
        buttons = [
            {"type": "reply", "reply": {"id": "confirm_order", "title": "✅ Confirmer"}},
            {"type": "reply", "reply": {"id": "add_more",      "title": "➕ Ajouter"}},
            {"type": "reply", "reply": {"id": "cancel_order",  "title": "❌ Annuler"}},
        ]
        self.whatsapp.send_button_message(phone, "\n".join(lines), buttons)

    def send_payment_options(self, phone: str, context: Dict):
        cart         = context.get("current_order", [])
        subtotal     = sum(item["price"] * item["quantity"] for item in cart)
        delivery_fee = context.get("delivery_fee", config.BASE_DELIVERY_FEE)
        total        = subtotal + delivery_fee

        # Afficher la répartition de la marge pour transparence interne (log seulement)
        split = payment_service.split_order(int(total), int(delivery_fee))
        logging.info(f"[split] marge plateforme estimée: {split['platform_margin']} GNF")

        body = (
            f"📍 Distance: {context.get('distance_km', 0)} km\n"
            f"⏱️ Temps estimé: {context.get('estimated_time', 45)} min\n"
            f"🏍️ Livraison: {int(delivery_fee):,} GNF\n"
            f"💳 Total: {int(total):,} GNF\n\n"
            f"Mode de paiement:"
        )
        buttons = [
            {"type": "reply", "reply": {"id": "pay_cash", "title": "💵 Espèces"}},
            {"type": "reply", "reply": {"id": "pay_om",   "title": "🍊 Orange Money"}},
            {"type": "reply", "reply": {"id": "pay_mtn",  "title": "📱 MTN MoMo"}},
        ]
        self.whatsapp.send_button_message(phone, body, buttons)

    # ── Finalisation commande ─────────────────────────────────────────────────

    async def finalize_order(self, phone: str, context: Dict):
        """
        Crée la commande en base et initie le paiement Mobile Money si besoin.
        Le disbursement (restaurant + livreur) est déclenché séparément
        via POST /payment/confirm-delivery quand le livreur confirme.
        """
        try:
            cart            = context.get("current_order", [])
            restaurant_id   = context.get("selected_restaurant", {}).get("id")
            delivery_address= context.get("delivery_address")
            payment_method  = context.get("payment_method", "cash")
            payment_phone   = context.get("payment_phone")

            # Créer / récupérer le client
            customer = self.db.query(Customer).filter(Customer.phone_number == phone).first()
            if not customer:
                customer = Customer(phone_number=phone)
                self.db.add(customer)
                self.db.commit()

            coords       = context.get("delivery_coords", {})
            distance     = context.get("distance_km", 0)
            subtotal     = sum(item["price"] * item["quantity"] for item in cart)
            delivery_fee = context.get("delivery_fee", config.BASE_DELIVERY_FEE)
            total_amount = subtotal + delivery_fee

            # Calcul marge
            split = payment_service.split_order(int(total_amount), int(delivery_fee))

            # Créer la commande
            order = Order(
                customer_id            = customer.id,
                restaurant_id          = restaurant_id,
                items                  = json.dumps(cart),
                subtotal               = subtotal,
                delivery_fee           = delivery_fee,
                total_amount           = total_amount,
                restaurant_commission  = split["restaurant_share"],
                platform_margin        = split["platform_margin"],
                delivery_address       = delivery_address,
                delivery_latitude      = coords.get("lat"),
                delivery_longitude     = coords.get("lng"),
                delivery_zone          = context.get("selected_zone"),
                distance_km            = distance,
                payment_method         = payment_method,
                payment_phone          = payment_phone,
                estimated_delivery_time= context.get("estimated_time", 45),
                status                 = OrderStatus.PENDING,
                payment_status         = PaymentStatus.PENDING,
            )
            self.db.add(order)
            self.db.commit()

            # ── Initier le paiement Mobile Money ──────────────────────────
            pmt_id = None
            if payment_method in ("orange_money", "mtn_momo") and payment_phone:
                result = await payment_service.request_payment(PaymentRequest(
                    order_id     = str(order.id),
                    phone_number = payment_phone,
                    amount       = int(total_amount),
                ))
                pmt_id               = result.payment_id
                order.payment_id     = pmt_id
                order.payment_status = (
                    PaymentStatus.PROCESSING if result.status == MoMoStatus.PENDING
                    else PaymentStatus.COMPLETED if result.status == MoMoStatus.SUCCESSFUL
                    else PaymentStatus.FAILED
                )
                self.db.commit()
                logging.info(f"[payment] order={order.id} | payment_id={pmt_id} | status={result.status}")

            # ── Notifier le restaurant ─────────────────────────────────────
            self.notify_restaurant(order)

            # ── Assigner un livreur ────────────────────────────────────────
            self.assign_driver(order)

            # ── Confirmation client ────────────────────────────────────────
            payment_label = {
                "cash":         "💵 Espèces à la livraison",
                "orange_money": "🍊 Orange Money — push USSD envoyé",
                "mtn_momo":     "📱 MTN MoMo — push USSD envoyé",
            }.get(payment_method, "💳")

            confirmation = (
                f"🎉 *Commande #{order.id} confirmée!*\n\n"
                f"📍 Distance: {distance} km\n"
                f"⏱️ Livraison: ~{order.estimated_delivery_time} min\n"
                f"💰 Total: {int(total_amount):,} GNF\n"
                f"💳 {payment_label}\n\n"
                f"Nous préparons votre commande!"
            )
            self.whatsapp.send_message(phone, confirmation)

            # Réinitialiser le contexte
            self.update_conversation_context(phone, {"state": "new", "current_order": []})

        except Exception as e:
            logging.error(f"Order error: {e}")
            self.whatsapp.send_message(phone, "❌ Erreur. Veuillez réessayer.")

    def notify_restaurant(self, order: Order):
        try:
            restaurant = order.restaurant
            if not restaurant or not restaurant.phone_number:
                return
            auth           = RestaurantAuth(self.db)
            dashboard_link = auth.generate_login_link(restaurant.phone_number)
            items          = json.loads(order.items)
            items_text     = "\n".join([f"• {i['quantity']}× {i['name']}" for i in items])
            message = (
                f"🍽️ *NOUVELLE COMMANDE #{order.id}*\n\n"
                f"📱 Client: {order.customer.phone_number}\n"
                f"📍 Adresse: {order.delivery_address}\n"
                f"📍 Distance: {order.distance_km} km\n"
                f"💰 Total: {int(order.total_amount):,} GNF\n"
                f"💶 Votre part: {int(order.restaurant_commission):,} GNF\n"
                f"⏱️ Temps estimé: {order.estimated_delivery_time} min\n\n"
                f"*Articles:*\n{items_text}\n\n"
                f"💳 {order.payment_method}\n\n"
                f"🎛️ Dashboard:\n{dashboard_link}"
            )
            self.whatsapp.send_message(restaurant.phone_number, message)
        except Exception as e:
            logging.error(f"Restaurant notification error: {e}")

    def assign_driver(self, order: Order):
        try:
            drivers = self.db.query(DeliveryDriver).filter(DeliveryDriver.is_available == True).all()
            if not drivers or not order.restaurant.latitude:
                return
            best_driver  = None
            min_distance = float('inf')
            for driver in drivers:
                if driver.current_latitude and driver.current_longitude:
                    d = GeolocationService().haversine_distance(
                        order.restaurant.latitude, order.restaurant.longitude,
                        driver.current_latitude, driver.current_longitude
                    )
                    if d < min_distance:
                        min_distance = d
                        best_driver  = driver
            if best_driver:
                order.driver_id = best_driver.id
                self.db.commit()

                split        = payment_service.split_order(
                    int(order.total_amount), int(order.delivery_fee)
                )
                driver_share = split["driver_share"]

                message = (
                    f"🏍️ *NOUVELLE LIVRAISON*\n\n"
                    f"Commande: #{order.id}\n"
                    f"Restaurant: {order.restaurant.name}\n"
                    f"Client: {order.delivery_address}\n"
                    f"Distance: {order.distance_km} km\n"
                    f"💰 Votre commission: {int(driver_share):,} GNF\n\n"
                    f"Confirmez la livraison en répondant *LIVRÉ {order.id}*"
                )
                self.whatsapp.send_message(best_driver.phone_number, message)
        except Exception as e:
            logging.error(f"Driver assignment error: {e}")

# -----------------------------------------------------------------------------
# Conversation model (déclaré après InteractiveConversationService pour ordre)
# -----------------------------------------------------------------------------
class Conversation(Base):
    __tablename__ = "conversations"

    id               = Column(Integer, primary_key=True, index=True)
    phone_number     = Column(String, index=True)
    context          = Column(Text)
    last_interaction = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# -----------------------------------------------------------------------------
# API FastAPI
# -----------------------------------------------------------------------------
app = FastAPI(title="Conakry Food API", version="4.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Brancher le router payment ────────────────────────────────────────────────
app.include_router(payment_router)

# -----------------------------------------------------------------------------
# Routes principales
# -----------------------------------------------------------------------------
@app.get("/")
async def root():
    return {
        "message":  "Conakry Food API",
        "version":  "4.1.0",
        "features": ["GPS", "Mobile Money", "Restaurant Registration", "Menu Management", "Payment Split"],
        "payment_mode": PaymentConfig().PAYMENT_MODE,
    }

@app.get("/health")
async def health_check(db: Session = Depends(get_db)):
    try:
        return {
            "status":      "ok",
            "restaurants": db.query(Restaurant).count(),
            "orders":      db.query(Order).count(),
            "products":    db.query(Product).count(),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}

# -----------------------------------------------------------------------------
# Route de confirmation de livraison par le livreur
# Déclenche automatiquement les versements restaurant + livreur
# -----------------------------------------------------------------------------
@app.post("/delivery/confirm/{order_id}")
async def confirm_delivery(order_id: int, db: Session = Depends(get_db)):
    """
    Le livreur appelle cet endpoint (ou répond LIVRÉ via WhatsApp).
    Déclenche les disbursements restaurant + livreur via payment_service.
    """
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Commande non trouvée")

    if order.status == OrderStatus.DELIVERED:
        return {"message": "Commande déjà livrée", "order_id": order_id}

    # Récupérer les numéros de téléphone
    restaurant_phone = order.restaurant.phone_number if order.restaurant else None
    driver           = db.query(DeliveryDriver).filter(DeliveryDriver.id == order.driver_id).first()
    driver_phone     = driver.phone_number if driver else None

    if not restaurant_phone or not driver_phone:
        raise HTTPException(status_code=400, detail="Numéros restaurant/livreur manquants")

    # Versement restaurant
    restaurant_result = await payment_service.disburse(DisbursementRequest(
        phone_number = restaurant_phone,
        amount       = int(order.restaurant_commission),
        reference    = f"ORDER-{order_id}-RESTAURANT",
        note         = f"Conakry Food - Commande #{order_id}",
    ))

    # Versement livreur
    split         = payment_service.split_order(int(order.total_amount), int(order.delivery_fee))
    driver_result = await payment_service.disburse(DisbursementRequest(
        phone_number = driver_phone,
        amount       = split["driver_share"],
        reference    = f"ORDER-{order_id}-DRIVER",
        note         = f"Conakry Food - Livraison #{order_id}",
    ))

    # Mettre à jour le statut
    order.status       = OrderStatus.DELIVERED
    order.delivered_at = datetime.utcnow()
    if order.payment_method != "cash":
        order.payment_status = PaymentStatus.COMPLETED
    db.commit()

    # Notifier le client
    whatsapp = WhatsAppService()
    if order.customer:
        whatsapp.send_message(
            order.customer.phone_number,
            f"✅ Commande #{order_id} livrée!\n\n"
            f"Merci d'avoir commandé sur Conakry Food 🍽️\n"
            f"Notez votre livreur en répondant de 1 à 5 ⭐"
        )

    logging.info(
        f"[confirm-delivery] order={order_id} | "
        f"restaurant={int(order.restaurant_commission):,} GNF | "
        f"driver={split['driver_share']:,} GNF | "
        f"marge={split['platform_margin']:,} GNF"
    )

    return {
        "order_id":        order_id,
        "restaurant":      {"status": restaurant_result.status, "ref": restaurant_result.transfer_id},
        "driver":          {"status": driver_result.status,     "ref": driver_result.transfer_id},
        "platform_margin": split["platform_margin"],
    }

# -----------------------------------------------------------------------------
# Routes d'enregistrement restaurant
# -----------------------------------------------------------------------------
@app.get("/register-restaurant", response_class=HTMLResponse)
async def restaurant_registration_form():
    return """
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Rejoignez Conakry Food</title>
        <style>
            body { font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background: #f5f5f5; }
            .form-container { background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
            .form-group { margin-bottom: 20px; }
            label { display: block; margin-bottom: 5px; font-weight: bold; color: #333; }
            input, select, textarea { width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 5px; font-size: 16px; }
            button { background: #28a745; color: white; padding: 15px 30px; border: none; border-radius: 5px; font-size: 18px; cursor: pointer; width: 100%; }
            .required { color: red; }
        </style>
    </head>
    <body>
        <div class="form-container">
            <div style="text-align:center; margin-bottom:30px;">
                <h1>🍽️ Rejoignez Conakry Food</h1>
                <p>Développez votre business avec la livraison en ligne</p>
            </div>
            <form action="/submit-restaurant" method="post">
                <div class="form-group">
                    <label>Nom du restaurant <span class="required">*</span></label>
                    <input type="text" name="name" required placeholder="Ex: Chez Fatou">
                </div>
                <div class="form-group">
                    <label>Téléphone WhatsApp <span class="required">*</span></label>
                    <input type="tel" name="phone" required placeholder="+224 XXX XX XX XX">
                </div>
                <div class="form-group">
                    <label>Adresse complète <span class="required">*</span></label>
                    <textarea name="address" rows="3" required placeholder="Rue, quartier, repères..."></textarea>
                </div>
                <div class="form-group">
                    <label>Zone de Conakry <span class="required">*</span></label>
                    <select name="zone" required>
                        <option value="">Choisir votre zone...</option>
                        <option value="Kipé">Kipé</option><option value="Kaloum">Kaloum</option>
                        <option value="Ratoma">Ratoma</option><option value="Matam">Matam</option>
                        <option value="Matoto">Matoto</option><option value="Dixinn">Dixinn</option>
                        <option value="Camayenne">Camayenne</option><option value="Hamdallaye">Hamdallaye</option>
                        <option value="Sonfonia">Sonfonia</option><option value="Nongo">Nongo</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>Type de cuisine</label>
                    <select name="cuisine_type">
                        <option value="">Sélectionner...</option>
                        <option value="Guinéenne">Cuisine guinéenne</option>
                        <option value="Africaine">Cuisine africaine</option>
                        <option value="Libanaise">Cuisine libanaise</option>
                        <option value="Fast-food">Fast-food</option>
                        <option value="Mixte">Cuisine mixte</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>Description de vos spécialités</label>
                    <textarea name="menu_description" rows="4" placeholder="Décrivez vos plats populaires..."></textarea>
                </div>
                <button type="submit">📝 Soumettre ma demande</button>
            </form>
        </div>
    </body>
    </html>
    """

@app.post("/submit-restaurant", response_class=HTMLResponse)
async def submit_restaurant_registration(
    name:             str = Form(...),
    phone:            str = Form(...),
    address:          str = Form(...),
    zone:             str = Form(...),
    cuisine_type:     str = Form(""),
    menu_description: str = Form(""),
    db: Session = Depends(get_db)
):
    try:
        phone_clean = phone.replace(" ", "").replace("-", "")
        if not phone_clean.startswith("+224"):
            phone_clean = "+224" + phone_clean.replace("+", "")

        registration_data = {
            "name": name.strip(), "phone_number": phone_clean,
            "address": address.strip(), "zone": zone,
            "cuisine_type": cuisine_type, "menu_description": menu_description.strip(),
            "status": "pending_approval",
            "submitted_at": datetime.utcnow().isoformat(), "source": "web_form",
        }
        save_registration_data(registration_data)
        ref_number = abs(hash(phone_clean)) % 10000
        whatsapp   = WhatsAppService()
        whatsapp.send_message(phone_clean,
            f"✅ Demande d'enregistrement reçue!\n\n🏪 Restaurant: {name}\n"
            f"📋 Référence: #{ref_number}\n\nNotre équipe vous contacte dans 24-48h. 🙏")
        whatsapp.send_message(config.ADMIN_PHONE,
            f"🆕 NOUVELLE DEMANDE\n🏪 {name}\n📞 {phone_clean}\n📍 {address}, {zone}\n📋 Réf: #{ref_number}")
        return f"""
        <html><body style="text-align:center;padding:50px;background:#f8f9fa;">
        <div style="background:white;padding:40px;border-radius:10px;max-width:500px;margin:0 auto;">
            <div style="font-size:60px">🎉</div>
            <h1>Demande envoyée!</h1>
            <div style="background:#e7f3ff;padding:15px;border-radius:5px;margin:20px 0;font-weight:bold;">
                Référence: #{ref_number}
            </div>
            <p>Réponse sous <strong>24-48h</strong> sur WhatsApp au <strong>{phone_clean}</strong></p>
        </div></body></html>"""
    except Exception as e:
        logging.error(f"Registration error: {e}")
        return "<html><body><h1>❌ Erreur. Réessayez.</h1><a href='/register-restaurant'>← Retour</a></body></html>"

# -----------------------------------------------------------------------------
# Dashboard admin
# -----------------------------------------------------------------------------
@app.get("/admin/restaurants", response_class=HTMLResponse)
async def admin_restaurant_dashboard():
    try:
        with open("pending_registrations.json", 'r', encoding='utf-8') as f:
            registrations = json.load(f)
    except FileNotFoundError:
        registrations = []
    pending  = [r for r in registrations if r.get("status") == "pending_approval"]
    approved = [r for r in registrations if r.get("status") == "approved"]
    rejected = [r for r in registrations if r.get("status") == "rejected"]
    rows = "".join([f"""
        <tr>
            <td><strong>{r.get('name','')}</strong><br><small>{r.get('address','')}</small></td>
            <td>{r.get('phone_number','')}</td><td>{r.get('zone','')}</td>
            <td>{r.get('cuisine_type','')}</td><td>{r.get('submitted_at','')[:10]}</td>
            <td>
                <a href="/admin/approve-restaurant?phone={r.get('phone_number','')}"
                   style="background:#28a745;color:white;padding:5px 10px;border-radius:3px;text-decoration:none;margin:2px;"
                   onclick="return confirm('Approuver?')">✅</a>
                <a href="/admin/reject-restaurant?phone={r.get('phone_number','')}"
                   style="background:#dc3545;color:white;padding:5px 10px;border-radius:3px;text-decoration:none;margin:2px;"
                   onclick="return confirm('Rejeter?')">❌</a>
            </td>
        </tr>""" for r in pending]) or "<tr><td colspan='6'>Aucune demande en attente</td></tr>"
    return f"""
    <html><head><meta charset="UTF-8"><title>Admin</title>
    <style>body{{font-family:Arial;margin:20px}}table{{width:100%;border-collapse:collapse}}
    th,td{{border:1px solid #ddd;padding:10px}}th{{background:#f8f9fa}}
    .stats{{display:flex;gap:20px;margin-bottom:30px}}
    .s{{padding:20px;background:#f8f9fa;border-radius:5px;text-align:center}}</style></head>
    <body><h1>🍽️ Administration</h1>
    <div class="stats">
        <div class="s"><h3>⏳ En attente</h3><h2>{len(pending)}</h2></div>
        <div class="s"><h3>✅ Approuvés</h3><h2>{len(approved)}</h2></div>
        <div class="s"><h3>❌ Rejetés</h3><h2>{len(rejected)}</h2></div>
    </div>
    <h2>Demandes en attente</h2>
    <table><tr><th>Restaurant</th><th>Téléphone</th><th>Zone</th><th>Cuisine</th><th>Date</th><th>Actions</th></tr>
    {rows}</table></body></html>"""

@app.get("/admin/approve-restaurant")
async def approve_restaurant_web(phone: str, db: Session = Depends(get_db)):
    try:
        with open("pending_registrations.json", 'r', encoding='utf-8') as f:
            registrations = json.load(f)
        registration = None
        for reg in registrations:
            if reg.get("phone_number") == phone and reg.get("status") == "pending_approval":
                reg["status"]      = "approved"
                reg["approved_at"] = datetime.utcnow().isoformat()
                registration       = reg
                break
        if not registration:
            return HTMLResponse("<h1>❌ Demande non trouvée</h1>")
        with open("pending_registrations.json", 'w', encoding='utf-8') as f:
            json.dump(registrations, f, indent=2, ensure_ascii=False)
        coords     = get_zone_coordinates(registration["zone"])
        restaurant = Restaurant(
            name=registration["name"], phone_number=phone,
            address=registration["address"], zone=registration["zone"],
            latitude=coords["lat"], longitude=coords["lng"],
            is_active=True, commission_rate=0.15, average_prep_time=30
        )
        db.add(restaurant)
        db.commit()
        WhatsAppService().send_message(phone,
            f"🎉 Votre restaurant '{registration['name']}' est activé sur Conakry Food!\n\n"
            f"Ajoutez votre menu: http://localhost:8000/restaurant/request-access")
        return HTMLResponse("<html><body style='text-align:center;padding:50px'>"
                            "<h1>✅ Approuvé!</h1><a href='/admin/restaurants'>← Retour</a></body></html>")
    except Exception as e:
        return HTMLResponse(f"<h1>❌ Erreur: {e}</h1>")

# -----------------------------------------------------------------------------
# Routes dashboard restaurant (inchangées)
# -----------------------------------------------------------------------------
@app.get("/restaurant/request-access", response_class=HTMLResponse)
async def request_restaurant_access():
    return """
    <html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Accès Restaurant</title>
    <style>body{font-family:Arial;max-width:500px;margin:50px auto;padding:20px;background:#f8f9fa}
    .box{background:white;padding:30px;border-radius:10px;box-shadow:0 2px 10px rgba(0,0,0,.1);text-align:center}
    input{width:100%;padding:12px;margin:10px 0;border:1px solid #ddd;border-radius:5px;font-size:16px}
    button{background:#007bff;color:white;padding:12px 30px;border:none;border-radius:5px;font-size:16px;cursor:pointer;width:100%}
    </style></head><body><div class="box">
    <h1>🍽️ Accès Restaurant</h1><p>Gérez votre menu sur Conakry Food</p>
    <form action="/restaurant/send-login-link" method="post">
        <input type="tel" name="phone" placeholder="Votre numéro WhatsApp (+224...)" required>
        <button type="submit">📱 Recevoir le lien d'accès</button>
    </form></div></body></html>"""

@app.post("/restaurant/send-login-link")
async def send_restaurant_login_link(phone: str = Form(...), db: Session = Depends(get_db)):
    try:
        phone_clean = phone.replace(" ", "").replace("-", "")
        if not phone_clean.startswith("+224"):
            phone_clean = "+224" + phone_clean.replace("+", "")
        restaurant = db.query(Restaurant).filter(
            Restaurant.phone_number == phone_clean, Restaurant.is_active == True).first()
        if not restaurant:
            return HTMLResponse("<html><body style='text-align:center;padding:50px'>"
                                "<h1>❌ Restaurant non trouvé</h1>"
                                "<a href='/restaurant/request-access'>← Réessayer</a></body></html>")
        link = RestaurantAuth(db).generate_login_link(phone_clean)
        WhatsAppService().send_message(phone_clean,
            f"🔐 Lien d'accès dashboard:\n\n{link}\n\n⚠️ Expire dans 24h.")
        return HTMLResponse("<html><body style='text-align:center;padding:50px'>"
                            "<h1>✅ Lien envoyé!</h1><p>Vérifiez votre WhatsApp.</p></body></html>")
    except Exception as e:
        return HTMLResponse("<html><body><h1>❌ Erreur</h1></body></html>")

@app.get("/restaurant/login/{token}")
async def restaurant_login(token: str, db: Session = Depends(get_db)):
    phone = RestaurantAuth(db).verify_token(token)
    if not phone:
        return HTMLResponse("<html><body style='text-align:center;padding:50px'>"
                            "<h1>❌ Lien invalide</h1>"
                            "<a href='/restaurant/request-access'>Nouveau lien</a></body></html>")
    response = RedirectResponse(url=f"/restaurant/dashboard?phone={phone}")
    response.set_cookie(key="restaurant_phone", value=phone, max_age=3600*8)
    return response

@app.get("/restaurant/dashboard", response_class=HTMLResponse)
async def restaurant_dashboard(phone: str = "", db: Session = Depends(get_db)):
    if not phone:
        return RedirectResponse(url="/restaurant/request-access")
    restaurant = db.query(Restaurant).filter(
        Restaurant.phone_number == phone, Restaurant.is_active == True).first()
    if not restaurant:
        return RedirectResponse(url="/restaurant/request-access")
    products    = db.query(Product).filter(Product.restaurant_id == restaurant.id).all()
    today       = datetime.utcnow().date()
    today_orders= db.query(Order).filter(Order.restaurant_id == restaurant.id,
                                         Order.created_at >= today).count()
    total_orders= db.query(Order).filter(Order.restaurant_id == restaurant.id).count()
    product_rows= "".join([f"""
        <div style="display:flex;justify-content:space-between;align-items:center;padding:15px;border-bottom:1px solid #eee">
            <div><strong>{p.name}</strong><br><small>{p.description or ''}</small><br>
                 <span style="color:#007bff;font-weight:bold">{int(p.price):,} GNF</span>
                 <span style="color:{'green' if p.available else 'red'};margin-left:10px">
                    {'🟢 Dispo' if p.available else '🔴 Indispo'}</span></div>
            <div>
                <a href="/restaurant/edit-product/{p.id}?phone={phone}"
                   style="background:#ffc107;color:black;padding:8px 15px;border-radius:5px;text-decoration:none;margin:2px">✏️</a>
                <a href="/restaurant/toggle-product/{p.id}?phone={phone}"
                   style="background:{'#dc3545' if p.available else '#28a745'};color:white;padding:8px 15px;border-radius:5px;text-decoration:none;margin:2px">
                   {'❌' if p.available else '✅'}</a>
            </div>
        </div>""" for p in products]) or "<p>Aucun produit. Ajoutez vos premiers plats!</p>"
    return f"""
    <html><head><meta charset="UTF-8"><title>Dashboard - {restaurant.name}</title>
    <style>body{{font-family:Arial;margin:0;background:#f8f9fa}}
    .header{{background:#007bff;color:white;padding:20px;text-align:center}}
    .container{{max-width:1200px;margin:0 auto;padding:20px}}
    .stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:20px;margin-bottom:30px}}
    .card{{background:white;padding:20px;border-radius:10px;text-align:center;box-shadow:0 2px 5px rgba(0,0,0,.1)}}
    .section{{background:white;padding:30px;border-radius:10px;box-shadow:0 2px 5px rgba(0,0,0,.1)}}
    </style></head>
    <body>
    <div class="header"><h1>🍽️ {restaurant.name}</h1><p>Dashboard Conakry Food</p></div>
    <div class="container">
        <div class="stats">
            <div class="card"><h3>📊 Aujourd'hui</h3><h2>{today_orders}</h2></div>
            <div class="card"><h3>📈 Total</h3><h2>{total_orders}</h2></div>
            <div class="card"><h3>🍽️ Produits</h3><h2>{len(products)}</h2></div>
            <div class="card"><h3>⭐ Note</h3><h2>{restaurant.rating:.1f}/5</h2></div>
        </div>
        <div class="section">
            <h2>🍽️ Gestion du Menu</h2>
            <button onclick="window.location.href='/restaurant/add-product?phone={phone}'"
                style="background:#28a745;color:white;padding:15px;border:none;border-radius:5px;font-size:16px;cursor:pointer;width:100%;margin-bottom:20px">
                ➕ Ajouter un produit</button>
            {product_rows}
        </div>
    </div></body></html>"""

@app.get("/restaurant/add-product", response_class=HTMLResponse)
async def add_product_form(phone: str = "", db: Session = Depends(get_db)):
    restaurant = db.query(Restaurant).filter(Restaurant.phone_number == phone).first()
    if not restaurant:
        return RedirectResponse(url="/restaurant/request-access")
    return f"""
    <html><head><meta charset="UTF-8"><title>Ajouter produit</title>
    <style>body{{font-family:Arial;max-width:600px;margin:0 auto;padding:20px;background:#f8f9fa}}
    .box{{background:white;padding:30px;border-radius:10px;box-shadow:0 2px 10px rgba(0,0,0,.1)}}
    .fg{{margin-bottom:20px}}label{{display:block;margin-bottom:5px;font-weight:bold}}
    input,select,textarea{{width:100%;padding:12px;border:1px solid #ddd;border-radius:5px;font-size:16px}}
    button{{background:#28a745;color:white;padding:15px;border:none;border-radius:5px;font-size:16px;cursor:pointer;width:100%}}
    a{{color:#007bff}}</style></head>
    <body><div class="box">
        <a href="/restaurant/dashboard?phone={phone}">← Retour</a>
        <h1>➕ Ajouter un produit</h1><p>Restaurant: <strong>{restaurant.name}</strong></p>
        <form action="/restaurant/save-product" method="post">
            <input type="hidden" name="phone" value="{phone}">
            <div class="fg"><label>Nom *</label><input type="text" name="name" required placeholder="Ex: Riz sauce arachide"></div>
            <div class="fg"><label>Description</label><textarea name="description" rows="3"></textarea></div>
            <div class="fg"><label>Prix (GNF) *</label><input type="number" name="price" required min="500" step="500"></div>
            <div class="fg"><label>Catégorie</label>
                <select name="category">
                    <option value="Plats">Plats principaux</option>
                    <option value="Entrées">Entrées</option>
                    <option value="Boissons">Boissons</option>
                    <option value="Desserts">Desserts</option>
                    <option value="Accompagnements">Accompagnements</option>
                </select></div>
            <div class="fg"><label><input type="checkbox" name="available" value="true" checked> Disponible immédiatement</label></div>
            <button type="submit">✅ Ajouter au menu</button>
        </form>
    </div></body></html>"""

@app.post("/restaurant/save-product")
async def save_product(
    phone: str = Form(...), name: str = Form(...), description: str = Form(""),
    price: float = Form(...), category: str = Form("Plats"), available: str = Form("false"),
    db: Session = Depends(get_db)
):
    restaurant = db.query(Restaurant).filter(Restaurant.phone_number == phone).first()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurant non trouvé")
    product = Product(restaurant_id=restaurant.id, name=name.strip(),
                      description=description.strip(), price=price,
                      category=category, available=(available == "true"))
    db.add(product)
    db.commit()
    WhatsAppService().send_message(phone, f"✅ '{name}' ajouté à votre menu!")
    return RedirectResponse(url=f"/restaurant/dashboard?phone={phone}", status_code=303)

@app.get("/restaurant/toggle-product/{product_id}")
async def toggle_product(product_id: int, phone: str = "", db: Session = Depends(get_db)):
    restaurant = db.query(Restaurant).filter(Restaurant.phone_number == phone).first()
    if not restaurant:
        raise HTTPException(status_code=404)
    product = db.query(Product).filter(Product.id == product_id,
                                       Product.restaurant_id == restaurant.id).first()
    if not product:
        raise HTTPException(status_code=404)
    product.available = not product.available
    db.commit()
    WhatsAppService().send_message(phone,
        f"🔄 '{product.name}' {'activé' if product.available else 'désactivé'}")
    return RedirectResponse(url=f"/restaurant/dashboard?phone={phone}", status_code=303)

# -----------------------------------------------------------------------------
# Webhook WhatsApp
# -----------------------------------------------------------------------------
@app.get("/webhook")
async def verify_webhook(request: Request):
    verify_token = request.query_params.get("hub.verify_token")
    challenge    = request.query_params.get("hub.challenge")
    if verify_token == config.WHATSAPP_VERIFY_TOKEN:
        return PlainTextResponse(content=challenge)
    raise HTTPException(status_code=403, detail="Invalid verification token")

@app.post("/webhook")
async def handle_webhook(request: Request, db: Session = Depends(get_db)):
    try:
        body      = await request.json()
        entries   = body.get("entry", [])
        if not entries:
            return JSONResponse({"status": "no_entries"})

        conv_service = InteractiveConversationService(db)
        processed    = False

        for entry in entries:
            for change in entry.get("changes", []):
                value    = change.get("value", {})
                messages = value.get("messages", [])
                for msg in messages:
                    from_number = msg.get("from", "")
                    msg_type    = msg.get("type", "")

                    if msg_type == "text":
                        text = msg.get("text", {}).get("body", "")
                        # Détecter "LIVRÉ {order_id}" envoyé par le livreur
                        if text.upper().startswith("LIVRÉ"):
                            parts = text.split()
                            if len(parts) >= 2 and parts[1].isdigit():
                                order_id = int(parts[1])
                                await confirm_delivery(order_id, db)
                                conv_service.whatsapp.send_message(from_number,
                                    f"✅ Livraison #{order_id} confirmée. Versements effectués!")
                                processed = True
                                continue
                        if text.strip():
                            conv_service.handle_text_message(from_number, text.strip())
                            processed = True

                    elif msg_type == "location":
                        loc = msg.get("location", {})
                        if loc.get("latitude") and loc.get("longitude"):
                            conv_service.handle_location_message(from_number, loc["latitude"], loc["longitude"])
                            processed = True

                    elif msg_type == "interactive":
                        interactive      = msg.get("interactive", {})
                        interactive_type = interactive.get("type", "")
                        if interactive_type == "button_reply":
                            br = interactive.get("button_reply", {})
                            conv_service.handle_button_reply(from_number, br.get("id",""), br.get("title",""))
                            processed = True
                        elif interactive_type == "list_reply":
                            lr = interactive.get("list_reply", {})
                            conv_service.handle_list_reply(from_number, lr.get("id",""))
                            processed = True

        return JSONResponse({"status": "success" if processed else "no_action"})

    except Exception as e:
        logging.exception(f"Webhook error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

# -----------------------------------------------------------------------------
# Debug endpoints
# -----------------------------------------------------------------------------
@app.get("/debug-restaurant/{restaurant_id}")
async def debug_restaurant(restaurant_id: int, db: Session = Depends(get_db)):
    restaurant = db.query(Restaurant).filter(Restaurant.id == restaurant_id).first()
    products   = db.query(Product).filter(Product.restaurant_id == restaurant_id).all()
    return {
        "restaurant": {"id": restaurant.id, "name": restaurant.name, "zone": restaurant.zone,
                       "coordinates": {"lat": restaurant.latitude, "lng": restaurant.longitude}
                       } if restaurant else None,
        "products": [{"id": p.id, "name": p.name, "price": p.price, "available": p.available} for p in products],
    }

@app.get("/debug-order/{order_id}")
async def debug_order(order_id: int, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404)
    return {
        "id":             order.id,
        "status":         order.status,
        "payment_status": order.payment_status,
        "payment_id":     order.payment_id,
        "total_amount":   order.total_amount,
        "restaurant_commission": order.restaurant_commission,
        "platform_margin":       order.platform_margin,
        "delivery_fee":          order.delivery_fee,
    }

# -----------------------------------------------------------------------------
# Initialisation des données de test
# -----------------------------------------------------------------------------
async def init_sample_data():
    db = SessionLocal()
    try:
        if db.query(Restaurant).count() == 0:
            restaurants = [
                Restaurant(name="Chez Fatou", phone_number="+224755347855",
                           address="Kipé Centre Commercial", zone="Kipé",
                           latitude=9.5900, longitude=-13.6100,
                           delivery_zones=json.dumps(["Kipé","Ratoma","Matam"]), average_prep_time=25),
                Restaurant(name="Restaurant Barita", phone_number="+224622334455",
                           address="Kaloum, Avenue de la République", zone="Kaloum",
                           latitude=9.5380, longitude=-13.6773,
                           delivery_zones=json.dumps(["Kaloum","Dixinn"]), average_prep_time=30),
                Restaurant(name="Le Délice de Ratoma", phone_number="+224633445566",
                           address="Ratoma Centre", zone="Ratoma",
                           latitude=9.5800, longitude=-13.6300,
                           delivery_zones=json.dumps(["Ratoma","Kipé"]), average_prep_time=20),
            ]
            for r in restaurants:
                db.add(r)
            db.commit()

            fatou = db.query(Restaurant).filter(Restaurant.name == "Chez Fatou").first()
            if fatou:
                for p in [
                    Product(restaurant_id=fatou.id, name="Riz sauce arachide", price=15000, category="Plats"),
                    Product(restaurant_id=fatou.id, name="Riz au gras",        price=12000, category="Plats"),
                    Product(restaurant_id=fatou.id, name="Poulet braisé",      price=25000, category="Plats"),
                    Product(restaurant_id=fatou.id, name="Poisson grillé",     price=20000, category="Plats"),
                    Product(restaurant_id=fatou.id, name="Fonio",              price=18000, category="Plats"),
                    Product(restaurant_id=fatou.id, name="Coca-Cola",          price=3000,  category="Boissons"),
                    Product(restaurant_id=fatou.id, name="Jus d'ananas",       price=5000,  category="Boissons"),
                ]: db.add(p)

            barita = db.query(Restaurant).filter(Restaurant.name == "Restaurant Barita").first()
            if barita:
                for p in [
                    Product(restaurant_id=barita.id, name="Atiéké poisson",  price=20000, category="Plats"),
                    Product(restaurant_id=barita.id, name="Poulet yassa",    price=22000, category="Plats"),
                    Product(restaurant_id=barita.id, name="Thieboudienne",   price=18000, category="Plats"),
                ]: db.add(p)

            db.commit()

        if db.query(DeliveryDriver).count() == 0:
            for d in [
                DeliveryDriver(name="Mamadou Bah",  phone_number="+224763524511", zone="Kipé",
                               current_latitude=9.5900, current_longitude=-13.6100),
                DeliveryDriver(name="Alpha Diallo", phone_number="+224600000001", zone="Kaloum",
                               current_latitude=9.5380, current_longitude=-13.6773),
            ]: db.add(d)
            db.commit()

        logging.info("✅ Data initialized")
    except Exception as e:
        logging.error(f"Init error: {e}")
        db.rollback()
    finally:
        db.close()

@app.on_event("startup")
async def startup_event():
    await init_sample_data()
    logging.info(f"🚀 Conakry Food v4.1 | Payment mode: {PaymentConfig().PAYMENT_MODE}")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=True)

@app.get("/debug-create-order")
async def debug_create_order(db: Session = Depends(get_db)):
    restaurant = db.query(Restaurant).first()
    driver     = db.query(DeliveryDriver).first()
    customer   = Customer(phone_number="+224620000000")
    db.add(customer)
    db.commit()
    order = Order(
        customer_id=customer.id,
        restaurant_id=restaurant.id,
        driver_id=driver.id,
        items='[{"name": "Riz sauce arachide", "price": 15000, "quantity": 2}]',
        subtotal=30000,
        delivery_fee=10000,
        total_amount=40000,
        restaurant_commission=25500,
        platform_margin=4500,
        payment_method="mtn_momo",
        payment_phone="+224620000000",
        delivery_address="Kipé, en face du marché",
        delivery_zone="Kipé",
        distance_km=2.5,
        estimated_delivery_time=35,
        status=OrderStatus.DELIVERING,
        payment_status=PaymentStatus.COMPLETED,
    )
    db.add(order)
    db.commit()
    return {"message": "Commande test créée", "order_id": order.id}
