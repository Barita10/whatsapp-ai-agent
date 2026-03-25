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

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
class Config:
    WHATSAPP_TOKEN: str = os.getenv("WHATSAPP_TOKEN", "your_whatsapp_token")
    WHATSAPP_PHONE_ID: str = os.getenv("WHATSAPP_PHONE_ID", "your_phone_id")
    WHATSAPP_VERIFY_TOKEN: str = os.getenv("WHATSAPP_VERIFY_TOKEN", "Aminat041197")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./conakry_food.db")
    
    # Mobile Money APIs
    ORANGE_MONEY_API_KEY: str = os.getenv("ORANGE_MONEY_API_KEY", "your_orange_key")
    ORANGE_MONEY_API_SECRET: str = os.getenv("ORANGE_MONEY_API_SECRET", "your_orange_secret")
    MTN_MOMO_API_KEY: str = os.getenv("MTN_MOMO_API_KEY", "your_mtn_key")
    
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
    PENDING = "pending"
    CONFIRMED = "confirmed"
    PREPARING = "preparing"
    READY = "ready"
    DELIVERING = "delivering"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"

class PaymentStatus:
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class Restaurant(Base):
    __tablename__ = "restaurants"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    phone_number = Column(String, unique=True, index=True)
    address = Column(Text)
    zone = Column(String)
    latitude = Column(Float)
    longitude = Column(Float)
    is_active = Column(Boolean, default=True)
    commission_rate = Column(Float, default=0.15)
    delivery_zones = Column(Text)
    average_prep_time = Column(Integer, default=30)
    rating = Column(Float, default=0.0)
    total_orders = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    products = relationship("Product", back_populates="restaurant")
    orders = relationship("Order", back_populates="restaurant")

class Customer(Base):
    __tablename__ = "customers"
    
    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, unique=True, index=True)
    name = Column(String)
    address = Column(Text)
    zone = Column(String)
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
    price = Column(Float)
    category = Column(String)
    image_url = Column(String)
    available = Column(Boolean, default=True)
    
    restaurant = relationship("Restaurant", back_populates="products")

class DeliveryDriver(Base):
    __tablename__ = "delivery_drivers"
    
    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, unique=True, index=True)
    name = Column(String)
    zone = Column(String)
    is_available = Column(Boolean, default=True)
    current_latitude = Column(Float)
    current_longitude = Column(Float)
    rating = Column(Float, default=0.0)
    total_deliveries = Column(Integer, default=0)
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
    payment_method = Column(String)
    payment_phone = Column(String)
    
    items = Column(Text)
    subtotal = Column(Float)
    delivery_fee = Column(Float)
    restaurant_commission = Column(Float)
    total_amount = Column(Float)
    
    delivery_address = Column(Text)
    delivery_latitude = Column(Float)
    delivery_longitude = Column(Float)
    delivery_zone = Column(String)
    distance_km = Column(Float)
    
    notes = Column(Text)
    estimated_delivery_time = Column(Integer)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    delivered_at = Column(DateTime)
    
    customer = relationship("Customer", back_populates="orders")
    restaurant = relationship("Restaurant", back_populates="orders")
    driver = relationship("DeliveryDriver", back_populates="orders")

class Conversation(Base):
    __tablename__ = "conversations"
    
    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, index=True)
    context = Column(Text)
    last_interaction = Column(DateTime, default=datetime.utcnow)

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
        """Génère un lien de connexion sécurisé"""
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
        """Sauvegarde les tokens de connexion"""
        filename = "restaurant_tokens.json"
        
        if os.path.exists(filename):
            with open(filename, 'r') as f:
                tokens = json.load(f)
        else:
            tokens = []
        
        tokens.append(token_data)
        
        # Nettoyer les tokens expirés
        now = datetime.utcnow().isoformat()
        tokens = [t for t in tokens if t.get("expires_at", "") > now]
        
        with open(filename, 'w') as f:
            json.dump(tokens, f, indent=2)
    
    def verify_token(self, token: str) -> Optional[str]:
        """Vérifie un token de connexion"""
        try:
            with open("restaurant_tokens.json", 'r') as f:
                tokens = json.load(f)
            
            now = datetime.utcnow().isoformat()
            
            for token_data in tokens:
                if (token_data.get("token") == token and 
                    not token_data.get("used") and
                    token_data.get("expires_at", "") > now):
                    
                    token_data["used"] = True
                    
                    with open("restaurant_tokens.json", 'w') as f:
                        json.dump(tokens, f, indent=2)
                    
                    return token_data.get("phone")
            
            return None
            
        except FileNotFoundError:
            return None

# -----------------------------------------------------------------------------
# Fonctions utilitaires pour l'enregistrement
# -----------------------------------------------------------------------------
def save_registration_data(data: Dict):
    """Sauvegarde les données d'enregistrement"""
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
    """Retourne les coordonnées d'une zone"""
    zone_coordinates = {
        "Kipé": {"lat": 9.5900, "lng": -13.6100},
        "Kaloum": {"lat": 9.5380, "lng": -13.6773},
        "Ratoma": {"lat": 9.5800, "lng": -13.6300},
        "Matam": {"lat": 9.5600, "lng": -13.6400},
        "Matoto": {"lat": 9.5500, "lng": -13.6200},
        "Dixinn": {"lat": 9.5450, "lng": -13.6850},
        "Camayenne": {"lat": 9.5350, "lng": -13.6900},
        "Hamdallaye": {"lat": 9.5700, "lng": -13.6250},
        "Sonfonia": {"lat": 9.5950, "lng": -13.5900},
        "Nongo": {"lat": 9.6000, "lng": -13.5800}
    }
    return zone_coordinates.get(zone, {"lat": 9.5091, "lng": -13.7122})

# -----------------------------------------------------------------------------
# Service de géolocalisation
# -----------------------------------------------------------------------------
class GeolocationService:
    def __init__(self):
        self.google_api_key = config.GOOGLE_MAPS_API_KEY
    
    def haversine_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calcule la distance en km entre deux points GPS"""
        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        return 2 * asin(sqrt(a)) * 6371  # Rayon terre en km
    
    def calculate_delivery_fee(self, distance_km: float) -> int:
        """Calcule les frais de livraison selon la distance"""
        if distance_km <= 2:
            return config.BASE_DELIVERY_FEE
        elif distance_km <= 5:
            return config.BASE_DELIVERY_FEE + 1000
        elif distance_km <= 10:
            return config.BASE_DELIVERY_FEE + 2000
        else:
            additional_km = distance_km - 10
            return config.BASE_DELIVERY_FEE + 2000 + int(additional_km * config.FEE_PER_KM)
    
    def estimate_delivery_time(self, distance_km: float, prep_time: int = 30) -> int:
        """Estime le temps de livraison en minutes"""
        # Vitesse moyenne en ville: 20 km/h
        travel_time = int((distance_km / 20) * 60)
        return prep_time + travel_time
    
    async def geocode_address(self, address: str, zone: str) -> Dict:
        """Convertit une adresse en coordonnées GPS via Google Maps API"""
        return get_zone_coordinates(zone)

# -----------------------------------------------------------------------------
# Services de paiement Mobile Money
# -----------------------------------------------------------------------------
class OrangeMoneyService:
    def __init__(self):
        self.api_key = config.ORANGE_MONEY_API_KEY
        self.api_secret = config.ORANGE_MONEY_API_SECRET
        self.base_url = "https://api.orange.com/orange-money-webpay/gn/v1"

    async def initiate_payment(self, phone: str, amount: int, order_id: int) -> Dict:
        """Initie un paiement Orange Money"""
        # En mode test, simuler le succès
        if self.api_key == "your_orange_key":
            logging.info(f"🍊 Orange Money TEST: {amount} GNF pour {phone}")
            return {"success": True, "test_mode": True}
        
        try:
            # Implémentation réelle Orange Money API
            payment_data = {
                "merchant_key": "conakry_food",
                "currency": "GNF",
                "order_id": f"ORDER_{order_id}",
                "amount": amount,
                "return_url": f"https://conakryfood.com/payment/success?order={order_id}",
                "cancel_url": f"https://conakryfood.com/payment/cancel?order={order_id}",
                "lang": "fr"
            }
            
            # TODO: Implémenter l'authentification et l'appel API réel
            return {"success": True, "payment_url": f"https://pay.orange.com/order_{order_id}"}
            
        except Exception as e:
            logging.error(f"Orange Money error: {e}")
            return {"success": False, "error": str(e)}

class MTNMoMoService:
    def __init__(self):
        self.api_key = config.MTN_MOMO_API_KEY
        self.base_url = "https://sandbox.momodeveloper.mtn.com"
    
    async def request_payment(self, phone: str, amount: int, order_id: int) -> Dict:
        """Initie un paiement MTN Mobile Money"""
        # En mode test, simuler le succès
        if self.api_key == "your_mtn_key":
            logging.info(f"📱 MTN MoMo TEST: {amount} GNF pour {phone}")
            return {"success": True, "test_mode": True}
        
        try:
            # TODO: Implémenter l'API MTN MoMo réelle
            return {"success": True, "transaction_id": f"MTN_{order_id}"}
        except Exception as e:
            logging.error(f"MTN MoMo error: {e}")
            return {"success": False, "error": str(e)}

# -----------------------------------------------------------------------------
# WhatsApp Service avec Messages Interactifs
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
        """Envoie un message texte simple"""
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
                logging.info(f"✅ Message sent to {to}")
            else:
                logging.error(f"❌ Message failed {r.status_code}: {r.text}")
            return ok
        except Exception as e:
            logging.error(f"❌ Send error: {e}")
            return False

    def send_button_message(self, to: str, body: str, buttons: List[Dict]) -> bool:
        """Envoie un message avec boutons (max 3)"""
        url = f"{self.base_url}/messages"
        data = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body},
                "action": {
                    "buttons": buttons[:3]
                }
            }
        }
        try:
            r = requests.post(url, json=data, headers=self._headers(), timeout=15)
            ok = r.status_code in (200, 201)
            logging.info(f"📱 Button message {'sent' if ok else 'failed'}: {to}")
            if not ok:
                logging.error(f"Button response: {r.text}")
            return ok
        except Exception as e:
            logging.error(f"Button error: {e}")
            return False

    def send_list_message(self, to: str, body: str, button_text: str, sections: List[Dict]) -> bool:
        """Envoie un message avec liste interactive"""
        url = f"{self.base_url}/messages"
        data = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": body},
                "action": {
                    "button": button_text,
                    "sections": sections
                }
            }
        }
        try:
            r = requests.post(url, json=data, headers=self._headers(), timeout=15)
            ok = r.status_code in (200, 201)
            logging.info(f"📋 List message {'sent' if ok else 'failed'}: {to}")
            if not ok:
                logging.error(f"List response: {r.text}")
            return ok
        except Exception as e:
            logging.error(f"List error: {e}")
            return False

    def send_location_request(self, to: str) -> bool:
        """Demande la localisation de l'utilisateur"""
        body = "📍 Partagez votre localisation pour calculer les frais de livraison"
        buttons = [{
            "type": "reply",
            "reply": {
                "id": "share_location",
                "title": "📍 Partager"
            }
        }]
        return self.send_button_message(to, body, buttons)

# -----------------------------------------------------------------------------
# Service de Conversation Interactive avec GPS
# -----------------------------------------------------------------------------
class InteractiveConversationService:
    def __init__(self, db: Session):
        self.db = db
        self.whatsapp = WhatsAppService()
        self.geo_service = GeolocationService()
        self.orange_money = OrangeMoneyService()
        self.mtn_momo = MTNMoMoService()

    def get_conversation_context(self, phone: str) -> Dict:
        conv = self.db.query(Conversation).filter(Conversation.phone_number == phone).first()
        if conv and conv.context:
            return json.loads(conv.context)
        return {
            "state": "new",
            "current_order": [],
            "selected_restaurant": None,
            "selected_zone": None,
            "delivery_address": None,
            "delivery_coords": None
        }

    def update_conversation_context(self, phone: str, context: Dict):
        conv = self.db.query(Conversation).filter(Conversation.phone_number == phone).first()
        if not conv:
            conv = Conversation(phone_number=phone)
            self.db.add(conv)
        conv.context = json.dumps(context)
        conv.last_interaction = datetime.utcnow()
        self.db.commit()

    def handle_text_message(self, phone: str, message: str):
        """Gère les messages texte normaux"""
        context = self.get_conversation_context(phone)
        
        # Vérifier si c'est une demande d'enregistrement restaurant
        registration_keywords = [
            "enregistrer restaurant", "devenir partenaire", 
            "rejoindre plateforme", "inscription restaurant",
            "partenariat", "livraison restaurant"
        ]
        
        if any(keyword in message.lower() for keyword in registration_keywords):
            self.whatsapp.send_message(phone, 
                "🍽️ Pour enregistrer votre restaurant, rendez-vous sur:\n\n"
                "http://localhost:8000/register-restaurant\n\n"
                "Vous pourrez remplir le formulaire et nous examinerons votre demande dans les 24-48h.")
            return
        
        # Si on attend une adresse
        if context.get("state") == "waiting_address":
            context["delivery_address"] = message
            # Geocoder l'adresse
            zone = context.get("selected_zone", "Conakry")
            coords = asyncio.run(self.geo_service.geocode_address(message, zone))
            context["delivery_coords"] = coords
            
            # Calculer la distance et les frais
            restaurant_id = context.get("selected_restaurant", {}).get("id")
            if restaurant_id:
                restaurant = self.db.query(Restaurant).filter(Restaurant.id == restaurant_id).first()
                if restaurant:
                    distance = self.geo_service.haversine_distance(
                        restaurant.latitude, restaurant.longitude,
                        coords["lat"], coords["lng"]
                    )
                    context["distance_km"] = round(distance, 1)
                    context["delivery_fee"] = self.geo_service.calculate_delivery_fee(distance)
                    context["estimated_time"] = self.geo_service.estimate_delivery_time(
                        distance, restaurant.average_prep_time
                    )
            
            self.send_payment_options(phone, context)
            context["state"] = "payment_selection"
        
        # Si on attend un numéro de téléphone pour le paiement
        elif context.get("state") == "waiting_payment_phone":
            payment_phone = re.sub(r'[^\d+]', '', message)
            context["payment_phone"] = payment_phone
            self.finalize_order(phone, context)
            context["state"] = "order_completed"
        
        else:
            # Message de bienvenue
            self.send_welcome_with_zones(phone)
            context["state"] = "zone_selection"
        
        self.update_conversation_context(phone, context)

    def handle_location_message(self, phone: str, latitude: float, longitude: float):
        """Gère la réception d'une localisation GPS"""
        context = self.get_conversation_context(phone)
        
        context["delivery_coords"] = {"lat": latitude, "lng": longitude}
        
        # Calculer la distance et les frais
        restaurant_id = context.get("selected_restaurant", {}).get("id")
        if restaurant_id:
            restaurant = self.db.query(Restaurant).filter(Restaurant.id == restaurant_id).first()
            if restaurant:
                distance = self.geo_service.haversine_distance(
                    restaurant.latitude, restaurant.longitude,
                    latitude, longitude
                )
                context["distance_km"] = round(distance, 1)
                context["delivery_fee"] = self.geo_service.calculate_delivery_fee(distance)
                context["estimated_time"] = self.geo_service.estimate_delivery_time(
                    distance, restaurant.average_prep_time
                )
        
        self.whatsapp.send_message(phone, "📍 Localisation reçue! Maintenant, précisez l'adresse exacte (rue, repère):")
        context["state"] = "waiting_address"
        self.update_conversation_context(phone, context)

    def handle_button_reply(self, phone: str, button_id: str, button_text: str):
        """Gère les réponses des boutons"""
        context = self.get_conversation_context(phone)
        logging.info(f"🔘 Button clicked: {button_id} - {button_text} from {phone}")
        
        if button_id == "add_more":
            restaurant_id = context.get("selected_restaurant", {}).get("id")
            if restaurant_id:
                self.send_product_list(phone, restaurant_id)
            context["state"] = "product_selection"
        
        elif button_id == "confirm_order":
            # Demander la localisation ou l'adresse
            self.whatsapp.send_location_request(phone)
            self.whatsapp.send_message(phone, "📍 Partagez votre localisation WhatsApp ou entrez votre adresse complète:")
            context["state"] = "waiting_address"
        
        elif button_id == "cancel_order":
            context = {"state": "new", "current_order": []}
            self.whatsapp.send_message(phone, "❌ Commande annulée.")
        
        # Sélection du paiement
        elif button_id in ["pay_cash", "pay_om", "pay_mtn"]:
            payment_method = {
                "pay_cash": "cash",
                "pay_om": "orange_money",
                "pay_mtn": "mtn_momo"
            }.get(button_id, "cash")
            
            context["payment_method"] = payment_method
            
            if payment_method != "cash":
                self.whatsapp.send_message(phone, f"📱 Entrez votre numéro {button_text}:")
                context["state"] = "waiting_payment_phone"
            else:
                self.finalize_order(phone, context)
                context["state"] = "order_completed"
        
        self.update_conversation_context(phone, context)

    def handle_list_reply(self, phone: str, item_id: str):
        """Gère les sélections de listes"""
        context = self.get_conversation_context(phone)
        logging.info(f"📋 List item selected: {item_id} from {phone}")
        
        # Sélection de zone
        if item_id.startswith("zone_"):
            zone = item_id.replace("zone_", "")
            context["selected_zone"] = zone
            self.send_restaurant_list(phone, zone)
            context["state"] = "restaurant_selection"
        
        # Sélection de restaurant
        elif item_id.startswith("rest_"):
            restaurant_id = int(item_id.replace("rest_", ""))
            restaurant = self.db.query(Restaurant).filter(Restaurant.id == restaurant_id).first()
            if restaurant:
                context["selected_restaurant"] = {
                    "id": restaurant.id,
                    "name": restaurant.name,
                    "lat": restaurant.latitude,
                    "lng": restaurant.longitude
                }
                self.send_product_list(phone, restaurant_id)
                context["state"] = "product_selection"
        
        # Sélection de produit
        elif item_id.startswith("prod_"):
            parts = item_id.split("_")
            if len(parts) == 3:
                product_id = int(parts[1])
                quantity = int(parts[2])
                
                product = self.db.query(Product).filter(Product.id == product_id).first()
                if product:
                    cart_item = {
                        "product_id": product.id,
                        "name": product.name,
                        "price": product.price,
                        "quantity": quantity
                    }
                    
                    current_order = context.get("current_order", [])
                    
                    # Vérifier si le produit existe déjà
                    found = False
                    for item in current_order:
                        if item["product_id"] == product.id:
                            item["quantity"] += quantity
                            found = True
                            break
                    
                    if not found:
                        current_order.append(cart_item)
                    
                    context["current_order"] = current_order
                    
                    # Afficher le récapitulatif
                    self.send_cart_summary(phone, context)
                    context["state"] = "cart_review"
        
        self.update_conversation_context(phone, context)

    def send_welcome_with_zones(self, phone: str):
        """Envoie le message de bienvenue avec toutes les zones"""
        body = "🍽️ Bienvenue sur Conakry Food!\n\nChoisissez votre zone de livraison:"
        
        sections = [{
            "title": "Zones de livraison",
            "rows": []
        }]
        
        all_zones = ["Kipé", "Kaloum", "Ratoma", "Matam", "Matoto", 
                     "Dixinn", "Camayenne", "Hamdallaye", "Sonfonia", "Nongo"]
        
        for zone in all_zones[:10]:
            sections[0]["rows"].append({
                "id": f"zone_{zone}",
                "title": zone,
                "description": f"Livraison disponible"
            })
        
        self.whatsapp.send_list_message(phone, body, "📍 Sélectionner", sections)

    def send_restaurant_list(self, phone: str, zone: str):
        """Envoie la liste des restaurants avec distance si possible"""
        restaurants = self.db.query(Restaurant).filter(
            Restaurant.is_active == True,
            Restaurant.zone == zone
        ).all()
        
        if not restaurants:
            self.whatsapp.send_message(phone, f"😔 Pas de restaurants à {zone}")
            self.send_welcome_with_zones(phone)
            return
        
        sections = [{
            "title": f"Restaurants à {zone}",
            "rows": []
        }]
        
        for rest in restaurants[:10]:
            prep_time = rest.average_prep_time or 30
            rating = f"⭐{rest.rating:.1f}" if rest.rating > 0 else "Nouveau"
            
            sections[0]["rows"].append({
                "id": f"rest_{rest.id}",
                "title": rest.name[:24],
                "description": f"⏱️{prep_time}min • {rating}"[:72]
            })
        
        body = f"🍽️ Restaurants disponibles à {zone}:"
        self.whatsapp.send_list_message(phone, body, "📋 Voir", sections)

    def send_product_list(self, phone: str, restaurant_id: int):
        """Envoie le menu du restaurant (utilise les vrais produits de la base)"""
        restaurant = self.db.query(Restaurant).filter(Restaurant.id == restaurant_id).first()
        products = self.db.query(Product).filter(
            Product.restaurant_id == restaurant_id,
            Product.available == True
        ).all()
        
        if not products:
            self.whatsapp.send_message(phone, f"😔 Menu non disponible pour {restaurant.name}")
            return
        
        sections = []
        
        # Section principale
        main_section = {
            "title": "Menu",
            "rows": []
        }
        
        for prod in products[:5]:
            main_section["rows"].append({
                "id": f"prod_{prod.id}_1",
                "title": prod.name[:24],
                "description": f"{int(prod.price):,} GNF"
            })
        
        sections.append(main_section)
        
        # Section quantités multiples
        if len(products) > 0:
            qty_section = {
                "title": "Quantités x2 et x3",
                "rows": []
            }
            
            for prod in products[:2]:
                for qty in [2, 3]:
                    qty_section["rows"].append({
                        "id": f"prod_{prod.id}_{qty}",
                        "title": f"{qty}x {prod.name[:18]}",
                        "description": f"{int(prod.price * qty):,} GNF"
                    })
            
            sections.append(qty_section)
        
        body = f"📋 Menu - {restaurant.name}"
        self.whatsapp.send_list_message(phone, body, "🍽️ Choisir", sections)

    def send_cart_summary(self, phone: str, context: Dict):
        """Envoie le récapitulatif du panier"""
        cart = context.get("current_order", [])
        if not cart:
            return
        
        restaurant_name = context.get("selected_restaurant", {}).get("name", "Restaurant")
        subtotal = sum(item["price"] * item["quantity"] for item in cart)
        
        lines = [f"🛒 *Panier - {restaurant_name}*\n"]
        for item in cart:
            total = item["price"] * item["quantity"]
            lines.append(f"• {item['quantity']}× {item['name']}: {int(total):,} GNF")
        
        lines.append(f"\n💰 Sous-total: {int(subtotal):,} GNF")
        lines.append(f"🏍️ Livraison: à calculer selon distance")
        
        body = "\n".join(lines)
        
        buttons = [
            {
                "type": "reply",
                "reply": {
                    "id": "confirm_order",
                    "title": "✅ Confirmer"
                }
            },
            {
                "type": "reply",
                "reply": {
                    "id": "add_more",
                    "title": "➕ Ajouter"
                }
            },
            {
                "type": "reply",
                "reply": {
                    "id": "cancel_order",
                    "title": "❌ Annuler"
                }
            }
        ]
        
        self.whatsapp.send_button_message(phone, body, buttons)

    def send_payment_options(self, phone: str, context: Dict):
        """Envoie les options de paiement avec distance et temps estimé"""
        cart = context.get("current_order", [])
        subtotal = sum(item["price"] * item["quantity"] for item in cart)
        delivery_fee = context.get("delivery_fee", config.BASE_DELIVERY_FEE)
        total = subtotal + delivery_fee
        distance = context.get("distance_km", 0)
        time_estimate = context.get("estimated_time", 45)
        
        body = (
            f"📍 Distance: {distance} km\n"
            f"⏱️ Temps estimé: {time_estimate} min\n"
            f"🏍️ Livraison: {int(delivery_fee):,} GNF\n"
            f"💳 Total: {int(total):,} GNF\n\n"
            f"Mode de paiement:"
        )
        
        buttons = [
            {
                "type": "reply",
                "reply": {
                    "id": "pay_cash",
                    "title": "💵 Espèces"
                }
            },
            {
                "type": "reply",
                "reply": {
                    "id": "pay_om",
                    "title": "🍊 Orange Money"
                }
            },
            {
                "type": "reply",
                "reply": {
                    "id": "pay_mtn",
                    "title": "📱 MTN MoMo"
                }
            }
        ]
        
        self.whatsapp.send_button_message(phone, body, buttons)

    def finalize_order(self, phone: str, context: Dict):
        """Finalise la commande avec toutes les infos GPS"""
        try:
            cart = context.get("current_order", [])
            restaurant_id = context.get("selected_restaurant", {}).get("id")
            delivery_address = context.get("delivery_address")
            payment_method = context.get("payment_method", "cash")
            payment_phone = context.get("payment_phone")
            
            # Créer le client
            customer = self.db.query(Customer).filter(Customer.phone_number == phone).first()
            if not customer:
                customer = Customer(phone_number=phone)
                self.db.add(customer)
                self.db.commit()
            
            # Coordonnées
            coords = context.get("delivery_coords", {})
            distance = context.get("distance_km", 0)
            
            # Totaux
            subtotal = sum(item["price"] * item["quantity"] for item in cart)
            delivery_fee = context.get("delivery_fee", config.BASE_DELIVERY_FEE)
            total_amount = subtotal + delivery_fee
            
            # Créer la commande
            order = Order(
                customer_id=customer.id,
                restaurant_id=restaurant_id,
                items=json.dumps(cart),
                subtotal=subtotal,
                delivery_fee=delivery_fee,
                total_amount=total_amount,
                restaurant_commission=subtotal * 0.15,
                delivery_address=delivery_address,
                delivery_latitude=coords.get("lat"),
                delivery_longitude=coords.get("lng"),
                delivery_zone=context.get("selected_zone"),
                distance_km=distance,
                payment_method=payment_method,
                payment_phone=payment_phone,
                estimated_delivery_time=context.get("estimated_time", 45),
                status=OrderStatus.PENDING
            )
            
            self.db.add(order)
            self.db.commit()
            
            # Initier le paiement si nécessaire
            if payment_method == "orange_money":
                asyncio.run(self.orange_money.initiate_payment(payment_phone, int(total_amount), order.id))
            elif payment_method == "mtn_momo":
                asyncio.run(self.mtn_momo.request_payment(payment_phone, int(total_amount), order.id))
            
            # Notifier le restaurant avec lien dashboard
            self.notify_restaurant(order)
            
            # Assigner un livreur
            self.assign_driver(order)
            
            # Confirmation
            payment_emoji = {
                "cash": "💵 Espèces à la livraison",
                "orange_money": "🍊 Orange Money",
                "mtn_momo": "📱 MTN MoMo"
            }.get(payment_method, "💳")
            
            confirmation = (
                f"🎉 *Commande #{order.id} confirmée!*\n\n"
                f"📍 Distance: {distance} km\n"
                f"⏱️ Livraison: ~{order.estimated_delivery_time} min\n"
                f"💰 Total: {int(total_amount):,} GNF\n"
                f"💳 {payment_emoji}\n\n"
                f"Nous préparons votre commande!"
            )
            
            self.whatsapp.send_message(phone, confirmation)
            
            # Réinitialiser
            new_context = {"state": "new", "current_order": []}
            self.update_conversation_context(phone, new_context)
            
        except Exception as e:
            logging.error(f"Order error: {e}")
            self.whatsapp.send_message(phone, "❌ Erreur. Veuillez réessayer.")

    def notify_restaurant(self, order: Order):
        """Notifie le restaurant avec lien dashboard"""
        try:
            restaurant = order.restaurant
            if not restaurant or not restaurant.phone_number:
                return
            
            # Générer un lien d'accès rapide au dashboard
            auth = RestaurantAuth(self.db)
            dashboard_link = auth.generate_login_link(restaurant.phone_number)
            
            items = json.loads(order.items)
            items_text = "\n".join([f"• {item['quantity']}× {item['name']}" for item in items])
            
            distance_text = f"📍 Distance: {order.distance_km} km\n" if order.distance_km else ""
            
            message = (
                f"🍽️ *NOUVELLE COMMANDE #{order.id}*\n\n"
                f"📱 Client: {order.customer.phone_number}\n"
                f"📍 Adresse: {order.delivery_address}\n"
                f"{distance_text}"
                f"💰 Total: {int(order.total_amount):,} GNF\n"
                f"⏱️ Temps estimé: {order.estimated_delivery_time} min\n\n"
                f"*Articles:*\n{items_text}\n\n"
                f"💳 {order.payment_method}\n\n"
                f"🎛️ Gérer via dashboard:\n{dashboard_link}"
            )
            
            self.whatsapp.send_message(restaurant.phone_number, message)
            
        except Exception as e:
            logging.error(f"Restaurant notification error: {e}")

    def assign_driver(self, order: Order):
        """Assigne le livreur le plus proche"""
        try:
            # Trouver les livreurs disponibles
            drivers = self.db.query(DeliveryDriver).filter(
                DeliveryDriver.is_available == True
            ).all()
            
            if not drivers or not order.restaurant.latitude:
                return
            
            # Calculer distances et trouver le plus proche
            best_driver = None
            min_distance = float('inf')
            
            for driver in drivers:
                if driver.current_latitude and driver.current_longitude:
                    distance = self.geo_service.haversine_distance(
                        order.restaurant.latitude, order.restaurant.longitude,
                        driver.current_latitude, driver.current_longitude
                    )
                    if distance < min_distance:
                        min_distance = distance
                        best_driver = driver
            
            if best_driver:
                order.driver_id = best_driver.id
                self.db.commit()
                
                # Notifier le livreur
                message = (
                    f"🏍️ *NOUVELLE LIVRAISON*\n\n"
                    f"Commande: #{order.id}\n"
                    f"Restaurant: {order.restaurant.name}\n"
                    f"Client: {order.delivery_address}\n"
                    f"Distance totale: {order.distance_km} km\n"
                    f"Commission: {int(order.delivery_fee * 0.7):,} GNF"
                )
                self.whatsapp.send_message(best_driver.phone_number, message)
                
        except Exception as e:
            logging.error(f"Driver assignment error: {e}")

# -----------------------------------------------------------------------------
# API FastAPI avec Routes Restaurant
# -----------------------------------------------------------------------------
app = FastAPI(title="Conakry Food API", version="4.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------------------------------------------------------
# Routes principales existantes
# -----------------------------------------------------------------------------
@app.get("/")
async def root():
    return {
        "message": "Conakry Food API",
        "version": "4.0.0",
        "features": ["GPS", "Mobile Money", "Restaurant Registration", "Menu Management"]
    }

@app.get("/health")
async def health_check(db: Session = Depends(get_db)):
    try:
        restaurant_count = db.query(Restaurant).count()
        order_count = db.query(Order).count()
        product_count = db.query(Product).count()
        return {
            "status": "ok",
            "restaurants": restaurant_count,
            "orders": order_count,
            "products": product_count
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}

# -----------------------------------------------------------------------------
# Routes d'enregistrement restaurant
# -----------------------------------------------------------------------------
@app.get("/register-restaurant", response_class=HTMLResponse)
async def restaurant_registration_form():
    """Formulaire d'enregistrement restaurant"""
    return """
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Rejoignez Conakry Food</title>
        <style>
            body { 
                font-family: Arial, sans-serif; 
                max-width: 600px; 
                margin: 0 auto; 
                padding: 20px;
                background: #f5f5f5;
            }
            .form-container {
                background: white;
                padding: 30px;
                border-radius: 10px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }
            .form-group { 
                margin-bottom: 20px; 
            }
            label { 
                display: block; 
                margin-bottom: 5px; 
                font-weight: bold;
                color: #333;
            }
            input, select, textarea { 
                width: 100%; 
                padding: 12px; 
                border: 1px solid #ddd;
                border-radius: 5px;
                font-size: 16px;
            }
            button { 
                background: #28a745; 
                color: white; 
                padding: 15px 30px; 
                border: none;
                border-radius: 5px;
                font-size: 18px;
                cursor: pointer;
                width: 100%;
            }
            button:hover { background: #218838; }
            .header { text-align: center; margin-bottom: 30px; }
            .required { color: red; }
        </style>
    </head>
    <body>
        <div class="form-container">
            <div class="header">
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
                        <option value="Kipé">Kipé</option>
                        <option value="Kaloum">Kaloum</option>
                        <option value="Ratoma">Ratoma</option>
                        <option value="Matam">Matam</option>
                        <option value="Matoto">Matoto</option>
                        <option value="Dixinn">Dixinn</option>
                        <option value="Camayenne">Camayenne</option>
                        <option value="Hamdallaye">Hamdallaye</option>
                        <option value="Sonfonia">Sonfonia</option>
                        <option value="Nongo">Nongo</option>
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
                    <textarea name="menu_description" rows="4" placeholder="Décrivez vos plats populaires, gamme de prix..."></textarea>
                </div>
                
                <button type="submit">📝 Soumettre ma demande</button>
                
                <p style="font-size: 14px; color: #666; margin-top: 20px; text-align: center;">
                    Nous examinerons votre demande sous 48h et vous contacterons via WhatsApp
                </p>
            </form>
        </div>
    </body>
    </html>
    """

@app.post("/submit-restaurant", response_class=HTMLResponse)
async def submit_restaurant_registration(
    name: str = Form(...),
    phone: str = Form(...),
    address: str = Form(...),
    zone: str = Form(...),
    cuisine_type: str = Form(""),
    menu_description: str = Form(""),
    db: Session = Depends(get_db)
):
    """Traite la soumission d'enregistrement restaurant"""
    try:
        # Nettoyer le numéro de téléphone
        phone_clean = phone.replace(" ", "").replace("-", "")
        if not phone_clean.startswith("+224"):
            phone_clean = "+224" + phone_clean.replace("+", "")
        
        # Créer la demande
        registration_data = {
            "name": name.strip(),
            "phone_number": phone_clean,
            "address": address.strip(),
            "zone": zone,
            "cuisine_type": cuisine_type,
            "menu_description": menu_description.strip(),
            "status": "pending_approval",
            "submitted_at": datetime.utcnow().isoformat(),
            "source": "web_form"
        }
        
        # Sauvegarder dans fichier JSON
        save_registration_data(registration_data)
        
        # Générer numéro de référence
        ref_number = abs(hash(phone_clean)) % 10000
        
        # Notifier le restaurant via WhatsApp
        whatsapp = WhatsAppService()
        confirmation_message = (
            f"✅ Demande d'enregistrement reçue!\n\n"
            f"🏪 Restaurant: {name}\n"
            f"📋 Référence: #{ref_number}\n\n"
            f"Notre équipe examinera votre demande dans les 24-48h.\n"
            f"Gardez ce numéro WhatsApp actif pour le suivi.\n\n"
            f"Merci de votre confiance! 🙏"
        )
        whatsapp.send_message(phone_clean, confirmation_message)
        
        # Notifier l'admin
        admin_message = (
            f"🆕 NOUVELLE DEMANDE RESTAURANT\n\n"
            f"🏪 {name}\n"
            f"📞 {phone_clean}\n"
            f"📍 {address}, {zone}\n"
            f"🍽️ {cuisine_type}\n"
            f"📋 Réf: #{ref_number}\n\n"
            f"Voir: http://localhost:8000/admin/restaurants"
        )
        whatsapp.send_message(config.ADMIN_PHONE, admin_message)
        
        # Page de confirmation
        return f"""
        <!DOCTYPE html>
        <html lang="fr">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Demande envoyée - Conakry Food</title>
            <style>
                body {{ 
                    font-family: Arial, sans-serif; 
                    text-align: center; 
                    padding: 50px;
                    background: #f8f9fa;
                }}
                .success-box {{
                    background: white;
                    padding: 40px;
                    border-radius: 10px;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                    max-width: 500px;
                    margin: 0 auto;
                }}
                .success-icon {{ font-size: 60px; margin-bottom: 20px; }}
                .ref-number {{ 
                    background: #e7f3ff; 
                    padding: 15px; 
                    border-radius: 5px; 
                    margin: 20px 0;
                    font-weight: bold;
                }}
            </style>
        </head>
        <body>
            <div class="success-box">
                <div class="success-icon">🎉</div>
                <h1>Demande envoyée avec succès!</h1>
                <div class="ref-number">
                    Numéro de référence: #{ref_number}
                </div>
                <p>Nous examinerons votre demande dans les <strong>24-48 heures</strong>.</p>
                <p>Vous recevrez une confirmation sur WhatsApp au <strong>{phone_clean}</strong></p>
                <hr>
                <h3>Prochaines étapes:</h3>
                <ul style="text-align: left;">
                    <li>📞 Notre équipe vous contactera</li>
                    <li>📋 Vérification des informations</li>
                    <li>🎓 Formation sur la plateforme</li>
                    <li>🚀 Activation de votre restaurant</li>
                </ul>
                <p style="margin-top: 30px;">
                    <a href="/register-restaurant" style="color: #007bff;">Soumettre une autre demande</a>
                </p>
            </div>
        </body>
        </html>
        """
        
    except Exception as e:
        logging.error(f"Registration submission error: {e}")
        return """
        <html><body style="text-align: center; padding: 50px;">
            <h1>❌ Erreur</h1>
            <p>Une erreur s'est produite. Veuillez réessayer.</p>
            <a href="/register-restaurant">← Retour au formulaire</a>
        </body></html>
        """

# -----------------------------------------------------------------------------
# Dashboard admin pour approuver les restaurants
# -----------------------------------------------------------------------------
@app.get("/admin/restaurants", response_class=HTMLResponse)
async def admin_restaurant_dashboard():
    """Dashboard admin pour gérer les demandes"""
    try:
        with open("pending_registrations.json", 'r', encoding='utf-8') as f:
            registrations = json.load(f)
    except FileNotFoundError:
        registrations = []
    
    pending = [r for r in registrations if r.get("status") == "pending_approval"]
    approved = [r for r in registrations if r.get("status") == "approved"]
    rejected = [r for r in registrations if r.get("status") == "rejected"]
    
    html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <title>Admin - Restaurants Conakry Food</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; }}
            table {{ width: 100%; border-collapse: collapse; margin-bottom: 30px; }}
            th, td {{ border: 1px solid #ddd; padding: 10px; text-align: left; }}
            th {{ background-color: #f8f9fa; }}
            .btn {{ padding: 5px 10px; margin: 2px; text-decoration: none; border-radius: 3px; }}
            .btn-success {{ background: #28a745; color: white; }}
            .btn-danger {{ background: #dc3545; color: white; }}
            .stats {{ display: flex; gap: 20px; margin-bottom: 30px; }}
            .stat-box {{ padding: 20px; background: #f8f9fa; border-radius: 5px; text-align: center; }}
        </style>
    </head>
    <body>
        <h1>🍽️ Administration - Restaurants</h1>
        
        <div class="stats">
            <div class="stat-box">
                <h3>⏳ En attente</h3>
                <h2>{len(pending)}</h2>
            </div>
            <div class="stat-box">
                <h3>✅ Approuvés</h3>
                <h2>{len(approved)}</h2>
            </div>
            <div class="stat-box">
                <h3>❌ Rejetés</h3>
                <h2>{len(rejected)}</h2>
            </div>
        </div>
        
        <h2>📋 Demandes en attente</h2>
        <table>
            <tr>
                <th>Restaurant</th>
                <th>Téléphone</th>
                <th>Zone</th>
                <th>Cuisine</th>
                <th>Date</th>
                <th>Actions</th>
            </tr>
    """
    
    for reg in pending:
        html += f"""
        <tr>
            <td><strong>{reg.get('name', 'N/A')}</strong><br>
                <small>{reg.get('address', '')}</small></td>
            <td>{reg.get('phone_number', '')}</td>
            <td>{reg.get('zone', '')}</td>
            <td>{reg.get('cuisine_type', 'N/A')}</td>
            <td>{reg.get('submitted_at', '')[:10]}</td>
            <td>
                <a href="/admin/approve-restaurant?phone={reg.get('phone_number', '')}" 
                   class="btn btn-success" onclick="return confirm('Approuver ce restaurant?')">✅ Approuver</a>
                <a href="/admin/reject-restaurant?phone={reg.get('phone_number', '')}" 
                   class="btn btn-danger" onclick="return confirm('Rejeter cette demande?')">❌ Rejeter</a>
            </td>
        </tr>
        """
    
    if not pending:
        html += "<tr><td colspan='6'>Aucune demande en attente</td></tr>"
    
    html += """
        </table>
        
        <h2>✅ Restaurants approuvés récemment</h2>
        <table>
            <tr><th>Restaurant</th><th>Téléphone</th><th>Zone</th><th>Approuvé le</th></tr>
    """
    
    for reg in approved[-5:]:  # 5 derniers approuvés
        html += f"""
        <tr>
            <td>{reg.get('name', '')}</td>
            <td>{reg.get('phone_number', '')}</td>
            <td>{reg.get('zone', '')}</td>
            <td>{reg.get('approved_at', '')[:10]}</td>
        </tr>
        """
    
    html += """
        </table>
    </body>
    </html>
    """
    
    return html

@app.get("/admin/approve-restaurant")
async def approve_restaurant_web(phone: str, db: Session = Depends(get_db)):
    """Approuve un restaurant via interface web"""
    try:
        # Charger les demandes
        with open("pending_registrations.json", 'r', encoding='utf-8') as f:
            registrations = json.load(f)
        
        # Trouver et approuver
        registration = None
        for reg in registrations:
            if reg.get("phone_number") == phone and reg.get("status") == "pending_approval":
                reg["status"] = "approved"
                reg["approved_at"] = datetime.utcnow().isoformat()
                registration = reg
                break
        
        if not registration:
            return HTMLResponse("<h1>❌ Demande non trouvée</h1>")
        
        # Sauvegarder
        with open("pending_registrations.json", 'w', encoding='utf-8') as f:
            json.dump(registrations, f, indent=2, ensure_ascii=False)
        
        # Créer le restaurant en base de données
        coords = get_zone_coordinates(registration["zone"])
        restaurant = Restaurant(
            name=registration["name"],
            phone_number=phone,
            address=registration["address"],
            zone=registration["zone"],
            latitude=coords["lat"],
            longitude=coords["lng"],
            is_active=True,
            commission_rate=0.15,
            average_prep_time=30
        )
        
        db.add(restaurant)
        db.commit()
        
        # Notifier le restaurant
        whatsapp = WhatsAppService()
        success_message = (
            f"🎉 FÉLICITATIONS!\n\n"
            f"Votre restaurant '{registration['name']}' a été approuvé et activé sur Conakry Food!\n\n"
            f"📋 Prochaines étapes:\n"
            f"1. Ajoutez votre menu sur: http://localhost:8000/restaurant/request-access\n"
            f"2. Formation rapide sur la plateforme\n"
            f"3. Début des commandes\n\n"
            f"Bienvenue dans l'équipe Conakry Food! 🍽️"
        )
        whatsapp.send_message(phone, success_message)
        
        return HTMLResponse("""
            <html><body style="text-align: center; padding: 50px;">
                <h1>✅ Restaurant approuvé!</h1>
                <p>Le restaurant a été créé en base et notifié par WhatsApp.</p>
                <a href="/admin/restaurants">← Retour au dashboard</a>
            </body></html>
        """)
        
    except Exception as e:
        logging.error(f"Approval error: {e}")
        return HTMLResponse(f"<h1>❌ Erreur: {e}</h1>")

# -----------------------------------------------------------------------------
# Routes de gestion des menus restaurant
# -----------------------------------------------------------------------------
@app.get("/restaurant/request-access", response_class=HTMLResponse)
async def request_restaurant_access():
    """Page pour demander l'accès au dashboard restaurant"""
    return """
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Accès Restaurant - Conakry Food</title>
        <style>
            body { 
                font-family: Arial, sans-serif; 
                max-width: 500px; 
                margin: 50px auto; 
                padding: 20px;
                background: #f8f9fa;
            }
            .login-box {
                background: white;
                padding: 30px;
                border-radius: 10px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                text-align: center;
            }
            input { 
                width: 100%; 
                padding: 12px; 
                margin: 10px 0;
                border: 1px solid #ddd;
                border-radius: 5px;
                font-size: 16px;
            }
            button { 
                background: #007bff; 
                color: white; 
                padding: 12px 30px; 
                border: none;
                border-radius: 5px;
                font-size: 16px;
                cursor: pointer;
                width: 100%;
            }
            button:hover { background: #0056b3; }
        </style>
    </head>
    <body>
        <div class="login-box">
            <h1>🍽️ Accès Restaurant</h1>
            <p>Gérez votre menu sur Conakry Food</p>
            
            <form action="/restaurant/send-login-link" method="post">
                <input type="tel" name="phone" placeholder="Votre numéro WhatsApp (+224...)" required>
                <button type="submit">📱 Recevoir le lien d'accès</button>
            </form>
            
            <p style="font-size: 14px; color: #666; margin-top: 20px;">
                Un lien sécurisé vous sera envoyé par WhatsApp
            </p>
        </div>
    </body>
    </html>
    """

@app.post("/restaurant/send-login-link")
async def send_restaurant_login_link(phone: str = Form(...), db: Session = Depends(get_db)):
    """Envoie un lien de connexion au restaurant"""
    try:
        phone_clean = phone.replace(" ", "").replace("-", "")
        if not phone_clean.startswith("+224"):
            phone_clean = "+224" + phone_clean.replace("+", "")
        
        restaurant = db.query(Restaurant).filter(
            Restaurant.phone_number == phone_clean,
            Restaurant.is_active == True
        ).first()
        
        if not restaurant:
            return HTMLResponse("""
                <html><body style="text-align: center; padding: 50px;">
                    <h1>❌ Restaurant non trouvé</h1>
                    <p>Ce numéro ne correspond à aucun restaurant enregistré.</p>
                    <a href="/restaurant/request-access">← Réessayer</a>
                </body></html>
            """)
        
        auth = RestaurantAuth(db)
        login_link = auth.generate_login_link(phone_clean)
        
        whatsapp = WhatsAppService()
        message = (
            f"🔐 Lien d'accès à votre dashboard restaurant:\n\n"
            f"{login_link}\n\n"
            f"⚠️ Ce lien expire dans 24h et ne peut être utilisé qu'une fois.\n\n"
            f"Gérez votre menu, vos commandes et vos paramètres."
        )
        whatsapp.send_message(phone_clean, message)
        
        return HTMLResponse("""
            <html><body style="text-align: center; padding: 50px;">
                <h1>✅ Lien envoyé!</h1>
                <p>Vérifiez votre WhatsApp et cliquez sur le lien reçu.</p>
                <p>Le lien expire dans 24 heures.</p>
            </body></html>
        """)
        
    except Exception as e:
        logging.error(f"Login link error: {e}")
        return HTMLResponse("""
            <html><body style="text-align: center; padding: 50px;">
                <h1>❌ Erreur</h1>
                <p>Impossible d'envoyer le lien. Réessayez plus tard.</p>
                <a href="/restaurant/request-access">← Réessayer</a>
            </body></html>
        """)

@app.get("/restaurant/login/{token}")
async def restaurant_login(token: str, db: Session = Depends(get_db)):
    """Connexion restaurant via token"""
    auth = RestaurantAuth(db)
    phone = auth.verify_token(token)
    
    if not phone:
        return HTMLResponse("""
            <html><body style="text-align: center; padding: 50px;">
                <h1>❌ Lien invalide</h1>
                <p>Ce lien a expiré ou a déjà été utilisé.</p>
                <a href="/restaurant/request-access">Demander un nouveau lien</a>
            </body></html>
        """)
    
    response = RedirectResponse(url=f"/restaurant/dashboard?phone={phone}")
    response.set_cookie(key="restaurant_phone", value=phone, max_age=3600*8)
    
    return response

@app.get("/restaurant/dashboard", response_class=HTMLResponse)
async def restaurant_dashboard(phone: str = "", db: Session = Depends(get_db)):
    """Dashboard principal du restaurant"""
    
    if not phone:
        return RedirectResponse(url="/restaurant/request-access")
    
    restaurant = db.query(Restaurant).filter(
        Restaurant.phone_number == phone,
        Restaurant.is_active == True
    ).first()
    
    if not restaurant:
        return RedirectResponse(url="/restaurant/request-access")
    
    products = db.query(Product).filter(Product.restaurant_id == restaurant.id).all()
    
    today = datetime.utcnow().date()
    today_orders = db.query(Order).filter(
        Order.restaurant_id == restaurant.id,
        Order.created_at >= today
    ).count()
    
    total_orders = db.query(Order).filter(Order.restaurant_id == restaurant.id).count()
    
    return f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Dashboard - {restaurant.name}</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 0; background: #f8f9fa; }}
            .header {{ background: #007bff; color: white; padding: 20px; text-align: center; }}
            .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
            .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px; }}
            .stat-card {{ background: white; padding: 20px; border-radius: 10px; text-align: center; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }}
            .menu-section {{ background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }}
            .product {{ display: flex; justify-content: space-between; align-items: center; padding: 15px; border-bottom: 1px solid #eee; }}
            .product:last-child {{ border-bottom: none; }}
            .btn {{ padding: 8px 15px; border: none; border-radius: 5px; cursor: pointer; text-decoration: none; display: inline-block; margin: 2px; }}
            .btn-primary {{ background: #007bff; color: white; }}
            .btn-warning {{ background: #ffc107; color: black; }}
            .btn-success {{ background: #28a745; color: white; }}
            .btn-danger {{ background: #dc3545; color: white; }}
            .add-product {{ background: #28a745; color: white; padding: 15px 25px; border: none; border-radius: 5px; font-size: 16px; cursor: pointer; margin-bottom: 20px; width: 100%; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>🍽️ {restaurant.name}</h1>
            <p>Dashboard Restaurant - Conakry Food</p>
        </div>
        
        <div class="container">
            <div class="stats">
                <div class="stat-card">
                    <h3>📊 Commandes aujourd'hui</h3>
                    <h2>{today_orders}</h2>
                </div>
                <div class="stat-card">
                    <h3>📈 Total commandes</h3>
                    <h2>{total_orders}</h2>
                </div>
                <div class="stat-card">
                    <h3>🍽️ Produits au menu</h3>
                    <h2>{len(products)}</h2>
                </div>
                <div class="stat-card">
                    <h3>⭐ Note moyenne</h3>
                    <h2>{restaurant.rating:.1f}/5</h2>
                </div>
            </div>
            
            <div class="menu-section">
                <h2>🍽️ Gestion du Menu</h2>
                
                <button class="add-product" onclick="window.location.href='/restaurant/add-product?phone={phone}'">
                    ➕ Ajouter un nouveau produit
                </button>
                
                {"<p>Aucun produit dans votre menu. Commencez par ajouter vos premiers plats!</p>" if not products else ""}
                
                {"".join([f'''
                <div class="product">
                    <div>
                        <strong>{product.name}</strong><br>
                        <small>{product.description or "Pas de description"}</small><br>
                        <span style="color: #007bff; font-weight: bold;">{int(product.price):,} GNF</span>
                        <span style="color: {'green' if product.available else 'red'}; margin-left: 10px;">
                            {'🟢 Disponible' if product.available else '🔴 Indisponible'}
                        </span>
                    </div>
                    <div>
                        <a href="/restaurant/edit-product/{product.id}?phone={phone}" class="btn btn-warning">✏️ Modifier</a>
                        <a href="/restaurant/toggle-product/{product.id}?phone={phone}" class="btn {'btn-danger' if product.available else 'btn-success'}">
                            {'❌ Désactiver' if product.available else '✅ Activer'}
                        </a>
                    </div>
                </div>
                ''' for product in products])}
            </div>
            
            <div style="text-align: center; margin-top: 30px;">
                <a href="/restaurant/request-access" class="btn btn-primary">🔄 Nouveau lien d'accès</a>
            </div>
        </div>
    </body>
    </html>
    """

@app.get("/restaurant/add-product", response_class=HTMLResponse)
async def add_product_form(phone: str = "", db: Session = Depends(get_db)):
    """Formulaire d'ajout de produit"""
    
    restaurant = db.query(Restaurant).filter(Restaurant.phone_number == phone).first()
    if not restaurant:
        return RedirectResponse(url="/restaurant/request-access")
    
    return f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Ajouter un produit - {restaurant.name}</title>
        <style>
            body {{ 
                font-family: Arial, sans-serif; 
                max-width: 600px; 
                margin: 0 auto; 
                padding: 20px;
                background: #f8f9fa;
            }}
            .form-container {{
                background: white;
                padding: 30px;
                border-radius: 10px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }}
            .form-group {{ margin-bottom: 20px; }}
            label {{ 
                display: block; 
                margin-bottom: 5px; 
                font-weight: bold;
            }}
            input, select, textarea {{ 
                width: 100%; 
                padding: 12px; 
                border: 1px solid #ddd;
                border-radius: 5px;
                font-size: 16px;
            }}
            button {{ 
                background: #28a745; 
                color: white; 
                padding: 15px 30px; 
                border: none;
                border-radius: 5px;
                font-size: 16px;
                cursor: pointer;
                width: 100%;
            }}
            .back-link {{ 
                display: inline-block; 
                margin-bottom: 20px;
                color: #007bff;
                text-decoration: none;
            }}
        </style>
    </head>
    <body>
        <div class="form-container">
            <a href="/restaurant/dashboard?phone={phone}" class="back-link">← Retour au dashboard</a>
            
            <h1>➕ Ajouter un produit</h1>
            <p>Restaurant: <strong>{restaurant.name}</strong></p>
            
            <form action="/restaurant/save-product" method="post">
                <input type="hidden" name="phone" value="{phone}">
                
                <div class="form-group">
                    <label>Nom du produit *</label>
                    <input type="text" name="name" required placeholder="Ex: Riz sauce arachide">
                </div>
                
                <div class="form-group">
                    <label>Description</label>
                    <textarea name="description" rows="3" placeholder="Décrivez votre plat..."></textarea>
                </div>
                
                <div class="form-group">
                    <label>Prix (en GNF) *</label>
                    <input type="number" name="price" required min="500" step="500" placeholder="15000">
                </div>
                
                <div class="form-group">
                    <label>Catégorie</label>
                    <select name="category">
                        <option value="Plats">Plats principaux</option>
                        <option value="Entrées">Entrées</option>
                        <option value="Boissons">Boissons</option>
                        <option value="Desserts">Desserts</option>
                        <option value="Accompagnements">Accompagnements</option>
                    </select>
                </div>
                
                <div class="form-group">
                    <label>
                        <input type="checkbox" name="available" value="true" checked>
                        Produit disponible immédiatement
                    </label>
                </div>
                
                <button type="submit">✅ Ajouter au menu</button>
            </form>
        </div>
    </body>
    </html>
    """

@app.post("/restaurant/save-product")
async def save_product(
    phone: str = Form(...),
    name: str = Form(...),
    description: str = Form(""),
    price: float = Form(...),
    category: str = Form("Plats"),
    available: str = Form("false"),
    db: Session = Depends(get_db)
):
    """Sauvegarde un nouveau produit"""
    try:
        restaurant = db.query(Restaurant).filter(Restaurant.phone_number == phone).first()
        if not restaurant:
            raise HTTPException(status_code=404, detail="Restaurant non trouvé")
        
        product = Product(
            restaurant_id=restaurant.id,
            name=name.strip(),
            description=description.strip(),
            price=price,
            category=category,
            available=(available == "true")
        )
        
        db.add(product)
        db.commit()
        
        # Notifier le succès
        whatsapp = WhatsAppService()
        whatsapp.send_message(phone, f"✅ Produit '{name}' ajouté à votre menu!")
        
        return RedirectResponse(url=f"/restaurant/dashboard?phone={phone}", status_code=303)
        
    except Exception as e:
        logging.error(f"Save product error: {e}")
        raise HTTPException(status_code=500, detail="Erreur lors de la sauvegarde")

@app.get("/restaurant/toggle-product/{product_id}")
async def toggle_product_availability(product_id: int, phone: str = "", db: Session = Depends(get_db)):
    """Active/désactive un produit"""
    try:
        restaurant = db.query(Restaurant).filter(Restaurant.phone_number == phone).first()
        if not restaurant:
            raise HTTPException(status_code=404, detail="Restaurant non trouvé")
        
        product = db.query(Product).filter(
            Product.id == product_id,
            Product.restaurant_id == restaurant.id
        ).first()
        
        if not product:
            raise HTTPException(status_code=404, detail="Produit non trouvé")
        
        product.available = not product.available
        db.commit()
        
        status = "activé" if product.available else "désactivé"
        whatsapp = WhatsAppService()
        whatsapp.send_message(phone, f"🔄 Produit '{product.name}' {status}")
        
        return RedirectResponse(url=f"/restaurant/dashboard?phone={phone}", status_code=303)
        
    except Exception as e:
        logging.error(f"Toggle product error: {e}")
        raise HTTPException(status_code=500, detail="Erreur")

# -----------------------------------------------------------------------------
# Routes webhook WhatsApp
# -----------------------------------------------------------------------------
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
        logging.info(f"📨 Webhook: {json.dumps(body, indent=2)[:500]}")

        entries = body.get("entry", [])
        if not entries:
            return JSONResponse({"status": "no_entries"})

        conv_service = InteractiveConversationService(db)
        processed = False

        for entry in entries:
            for change in entry.get("changes", []):
                value = change.get("value", {})
                messages = value.get("messages", [])

                for msg in messages:
                    from_number = msg.get("from", "")
                    msg_type = msg.get("type", "")
                    
                    if msg_type == "text":
                        text = msg.get("text", {}).get("body", "")
                        if text.strip():
                            conv_service.handle_text_message(from_number, text.strip())
                            processed = True
                    
                    elif msg_type == "location":
                        location = msg.get("location", {})
                        latitude = location.get("latitude")
                        longitude = location.get("longitude")
                        if latitude and longitude:
                            conv_service.handle_location_message(from_number, latitude, longitude)
                            processed = True
                    
                    elif msg_type == "interactive":
                        interactive = msg.get("interactive", {})
                        interactive_type = interactive.get("type", "")
                        
                        if interactive_type == "button_reply":
                            button_reply = interactive.get("button_reply", {})
                            button_id = button_reply.get("id", "")
                            button_title = button_reply.get("title", "")
                            conv_service.handle_button_reply(from_number, button_id, button_title)
                            processed = True
                        
                        elif interactive_type == "list_reply":
                            list_reply = interactive.get("list_reply", {})
                            item_id = list_reply.get("id", "")
                            conv_service.handle_list_reply(from_number, item_id)
                            processed = True

        return JSONResponse({"status": "success" if processed else "no_action"})

    except Exception as e:
        logging.exception(f"Webhook error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

# Debug endpoints
@app.get("/debug-restaurant/{restaurant_id}")
async def debug_restaurant(restaurant_id: int, db: Session = Depends(get_db)):
    restaurant = db.query(Restaurant).filter(Restaurant.id == restaurant_id).first()
    products = db.query(Product).filter(Product.restaurant_id == restaurant_id).all()
    
    return {
        "restaurant": {
            "id": restaurant.id,
            "name": restaurant.name,
            "zone": restaurant.zone,
            "coordinates": {"lat": restaurant.latitude, "lng": restaurant.longitude}
        } if restaurant else None,
        "products_count": len(products),
        "products": [
            {"id": p.id, "name": p.name, "price": p.price, "available": p.available}
            for p in products
        ]
    }

# -----------------------------------------------------------------------------
# Initialisation des données
# -----------------------------------------------------------------------------
async def init_sample_data():
    db = SessionLocal()
    try:
        if db.query(Restaurant).count() == 0:
            restaurants = [
                Restaurant(
                    name="Chez Fatou",
                    phone_number="+224755347855",
                    address="Kipé Centre Commercial",
                    zone="Kipé",
                    latitude=9.5900,
                    longitude=-13.6100,
                    delivery_zones=json.dumps(["Kipé", "Ratoma", "Matam"]),
                    average_prep_time=25
                ),
                Restaurant(
                    name="Restaurant Barita",
                    phone_number="+224622334455",
                    address="Kaloum, Avenue de la République",
                    zone="Kaloum",
                    latitude=9.5380,
                    longitude=-13.6773,
                    delivery_zones=json.dumps(["Kaloum", "Dixinn"]),
                    average_prep_time=30
                ),
                Restaurant(
                    name="Le Délice de Ratoma",
                    phone_number="+224633445566",
                    address="Ratoma Centre",
                    zone="Ratoma",
                    latitude=9.5800,
                    longitude=-13.6300,
                    delivery_zones=json.dumps(["Ratoma", "Kipé"]),
                    average_prep_time=20
                )
            ]
            
            for restaurant in restaurants:
                db.add(restaurant)
            db.commit()
            
            # Produits pour Chez Fatou
            fatou = db.query(Restaurant).filter(Restaurant.name == "Chez Fatou").first()
            if fatou:
                products = [
                    Product(restaurant_id=fatou.id, name="Riz sauce arachide", price=15000, category="Plats", available=True),
                    Product(restaurant_id=fatou.id, name="Riz au gras", price=12000, category="Plats", available=True),
                    Product(restaurant_id=fatou.id, name="Poulet braisé", price=25000, category="Plats", available=True),
                    Product(restaurant_id=fatou.id, name="Poisson grillé", price=20000, category="Plats", available=True),
                    Product(restaurant_id=fatou.id, name="Fonio", price=18000, category="Plats", available=True),
                    Product(restaurant_id=fatou.id, name="Coca-Cola", price=3000, category="Boissons", available=True),
                    Product(restaurant_id=fatou.id, name="Jus d'ananas", price=5000, category="Boissons", available=True),
                ]
                for product in products:
                    db.add(product)
            
            # Produits pour Barita
            barita = db.query(Restaurant).filter(Restaurant.name == "Restaurant Barita").first()
            if barita:
                products_b = [
                    Product(restaurant_id=barita.id, name="Atiéké poisson", price=20000, category="Plats", available=True),
                    Product(restaurant_id=barita.id, name="Poulet yassa", price=22000, category="Plats", available=True),
                    Product(restaurant_id=barita.id, name="Thieboudienne", price=18000, category="Plats", available=True),
                ]
                for product in products_b:
                    db.add(product)
            
            db.commit()
        
        # Livreurs
        if db.query(DeliveryDriver).count() == 0:
            drivers = [
                DeliveryDriver(
                    name="Mamadou Bah",
                    phone_number="+224763524511",
                    zone="Kipé",
                    current_latitude=9.5900,
                    current_longitude=-13.6100
                ),
                DeliveryDriver(
                    name="Alpha Diallo",
                    phone_number="+224600000001",
                    zone="Kaloum",
                    current_latitude=9.5380,
                    current_longitude=-13.6773
                )
            ]
            for driver in drivers:
                db.add(driver)
            db.commit()
        
        logging.info("✅ Data initialized with GPS coordinates and menu management")
        
    except Exception as e:
        logging.error(f"Init error: {e}")
        db.rollback()
    finally:
        db.close()

@app.on_event("startup")
async def startup_event():
    await init_sample_data()
    logging.info("🚀 Conakry Food v4.0 started with Restaurant Registration & Menu Management")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port, reload=True)