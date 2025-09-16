# main.py - Version Interactive Complète avec GPS et Paiements
# Système de commande restaurant avec géolocalisation et Mobile Money
# WhatsApp Business API + GPS + Orange Money/MTN MoMo

import os
import re
import json
import logging
import unicodedata
from datetime import datetime
from typing import List, Dict, Optional
from math import radians, cos, sin, asin, sqrt

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse
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
        # Pour les tests, utiliser des coordonnées par défaut selon la zone
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
        
        # Si on a une vraie clé Google Maps, faire l'appel API
        if self.google_api_key and self.google_api_key != "your_google_maps_key":
            try:
                url = "https://maps.googleapis.com/maps/api/geocode/json"
                params = {
                    "address": f"{address}, {zone}, Conakry, Guinea",
                    "key": self.google_api_key
                }
                response = requests.get(url, params=params)
                data = response.json()
                
                if data["status"] == "OK" and data["results"]:
                    location = data["results"][0]["geometry"]["location"]
                    return {"lat": location["lat"], "lng": location["lng"]}
            except Exception as e:
                logging.error(f"Geocoding error: {e}")
        
        # Fallback: utiliser les coordonnées de la zone
        return zone_coordinates.get(zone, {"lat": 9.5091, "lng": -13.7122})  # Centre Conakry

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
        """Envoie le menu du restaurant"""
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
            
            # Notifier le restaurant
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
        """Notifie le restaurant avec infos de distance"""
        try:
            restaurant = order.restaurant
            if not restaurant or not restaurant.phone_number:
                return
            
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
                f"💳 {order.payment_method}"
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
# API FastAPI
# -----------------------------------------------------------------------------
app = FastAPI(title="Conakry Food API", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {
        "message": "Conakry Food API",
        "version": "3.0.0",
        "features": ["GPS", "Mobile Money", "Interactive UI"]
    }

@app.get("/health")
async def health_check(db: Session = Depends(get_db)):
    try:
        restaurant_count = db.query(Restaurant).count()
        order_count = db.query(Order).count()
        return {
            "status": "ok",
            "restaurants": restaurant_count,
            "orders": order_count
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}

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
                    phone_number="33755347855",
                    address="Kipé Centre Commercial",
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
                    delivery_zones=json.dumps(["Kaloum", "Dixinn"]),
                    average_prep_time=30
                ),
                Restaurant(
                    name="Le Délice de Ratoma",
                    phone_number="224633445566",
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
                    phone_number="33763524511",
                    zone="Kipé",
                    current_latitude=9.5900,
                    current_longitude=-13.6100
                ),
                DeliveryDriver(
                    name="Alpha Diallo",
                    phone_number="224600000001",
                    zone="Kaloum",
                    current_latitude=9.5380,
                    current_longitude=-13.6773
                )
            ]
            for driver in drivers:
                db.add(driver)
            db.commit()
        
        logging.info("✅ Data initialized with GPS coordinates")
        
    except Exception as e:
        logging.error(f"Init error: {e}")
        db.rollback()
    finally:
        db.close()

@app.on_event("startup")
async def startup_event():
    await init_sample_data()
    logging.info("🚀 Conakry Food v3.0 started with GPS & Mobile Money")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port, reload=True)