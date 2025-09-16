# main.py - Version Interactive avec Boutons WhatsApp
# Système de commande restaurant sans saisie de texte
# Utilise les boutons et listes interactives WhatsApp Business API

import os
import re
import json
import logging
import unicodedata
from datetime import datetime
from typing import List, Dict, Optional

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
    
    ADMIN_PHONE: str = os.getenv("ADMIN_PHONE", "224611223344")
    BASE_DELIVERY_FEE: int = int(os.getenv("BASE_DELIVERY_FEE", "2000"))
    FEE_PER_KM: int = int(os.getenv("FEE_PER_KM", "500"))

config = Config()

# -----------------------------------------------------------------------------
# DB Models (inchangés)
# -----------------------------------------------------------------------------
engine = create_engine(config.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class OrderStatus:
    PENDING = "pending"
    CONFIRMED = "confirmed"
    PREPARING = "preparing"
    READY = "ready"
    ASSIGNED = "assigned"
    DELIVERING = "delivering"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"

class PaymentStatus:
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

# Zones de Conakry principales pour les boutons
MAIN_ZONES = ["Kipé", "Kaloum", "Ratoma", "Matam", "Matoto", "Dixinn"]

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

class Order(Base):
    __tablename__ = "orders"
    
    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"))
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"))
    
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
    delivery_zone = Column(String)
    
    notes = Column(Text)
    estimated_delivery_time = Column(Integer)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    delivered_at = Column(DateTime)
    
    customer = relationship("Customer", back_populates="orders")
    restaurant = relationship("Restaurant", back_populates="orders")

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
                    "buttons": buttons[:3]  # Max 3 boutons
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

# -----------------------------------------------------------------------------
# Service de Conversation Interactive
# -----------------------------------------------------------------------------
class InteractiveConversationService:
    def __init__(self, db: Session):
        self.db = db
        self.whatsapp = WhatsAppService()

    def get_conversation_context(self, phone: str) -> Dict:
        conv = self.db.query(Conversation).filter(Conversation.phone_number == phone).first()
        if conv and conv.context:
            return json.loads(conv.context)
        return {
            "state": "new",
            "current_order": [],
            "selected_restaurant": None,
            "selected_zone": None,
            "delivery_address": None
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
            self.send_payment_options(phone, context)
            context["state"] = "payment_selection"
        else:
            # Message de bienvenue avec boutons de zones
            self.send_welcome_with_zones(phone)
            context["state"] = "zone_selection"
        
        self.update_conversation_context(phone, context)

    def handle_button_reply(self, phone: str, button_id: str, button_text: str):
        """Gère les réponses des boutons"""
        context = self.get_conversation_context(phone)
        logging.info(f"🔘 Button clicked: {button_id} - {button_text} from {phone}")
        
        # Sélection de zone
        if button_id.startswith("zone_"):
            zone = button_id.replace("zone_", "")
            context["selected_zone"] = zone
            self.send_restaurant_list(phone, zone)
            context["state"] = "restaurant_selection"
        
        # Actions sur le panier
        elif button_id == "add_more":
            restaurant_id = context.get("selected_restaurant", {}).get("id")
            if restaurant_id:
                self.send_product_list(phone, restaurant_id)
            context["state"] = "product_selection"
        
        elif button_id == "confirm_order":
            self.whatsapp.send_message(phone, "📍 Entrez votre adresse de livraison complète:")
            context["state"] = "waiting_address"
        
        elif button_id == "cancel_order":
            context = {"state": "new", "current_order": []}
            self.whatsapp.send_message(phone, "❌ Commande annulée. Tapez 'menu' pour recommencer.")
        
        # Sélection du paiement
        elif button_id in ["pay_cash", "pay_om", "pay_mtn"]:
            payment_method = {
                "pay_cash": "cash",
                "pay_om": "orange_money",
                "pay_mtn": "mtn_momo"
            }.get(button_id, "cash")
            
            context["payment_method"] = payment_method
            self.finalize_order(phone, context)
            context["state"] = "order_completed"
        
        self.update_conversation_context(phone, context)

    def handle_list_reply(self, phone: str, item_id: str):
        """Gère les sélections de listes"""
        context = self.get_conversation_context(phone)
        logging.info(f"📋 List item selected: {item_id} from {phone}")
        
        # Sélection de restaurant
        if item_id.startswith("rest_"):
            restaurant_id = int(item_id.replace("rest_", ""))
            restaurant = self.db.query(Restaurant).filter(Restaurant.id == restaurant_id).first()
            if restaurant:
                context["selected_restaurant"] = {
                    "id": restaurant.id,
                    "name": restaurant.name
                }
                self.send_product_list(phone, restaurant_id)
                context["state"] = "product_selection"
        
        # Sélection de produit avec quantité
        elif item_id.startswith("prod_"):
            parts = item_id.split("_")
            if len(parts) == 3:
                product_id = int(parts[1])
                quantity = int(parts[2])
                
                product = self.db.query(Product).filter(Product.id == product_id).first()
                if product:
                    # Ajouter au panier
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
                    
                    # Afficher le récapitulatif avec boutons
                    self.send_cart_summary(phone, context)
                    context["state"] = "cart_review"
        
        self.update_conversation_context(phone, context)

    def send_welcome_with_zones(self, phone: str):
        """Envoie le message de bienvenue avec boutons de zones"""
        body = "🍽️ Bienvenue sur Conakry Food!\n\nSélectionnez votre zone:"
        
        buttons = []
        for zone in MAIN_ZONES[:3]:  # Max 3 boutons
            buttons.append({
                "type": "reply",
                "reply": {
                    "id": f"zone_{zone}",
                    "title": zone
                }
            })
        
        self.whatsapp.send_button_message(phone, body, buttons)

    def send_restaurant_list(self, phone: str, zone: str):
        """Envoie la liste des restaurants de la zone"""
        restaurants = self.db.query(Restaurant).filter(
            Restaurant.is_active == True,
            Restaurant.zone == zone
        ).all()
        
        if not restaurants:
            self.whatsapp.send_message(phone, f"😔 Pas de restaurants disponibles à {zone}")
            self.send_welcome_with_zones(phone)
            return
        
        sections = [{
            "title": f"Restaurants à {zone}",
            "rows": []
        }]
        
        for rest in restaurants[:10]:
            prep_time = rest.average_prep_time or 30
            sections[0]["rows"].append({
                "id": f"rest_{rest.id}",
                "title": rest.name[:24],  # Max 24 chars
                "description": f"⏱️ {prep_time}min • 📍 {rest.zone}"[:72]  # Max 72 chars
            })
        
        body = f"🍽️ Choisissez un restaurant à {zone}:"
        self.whatsapp.send_list_message(phone, body, "📋 Voir restaurants", sections)

    def send_product_list(self, phone: str, restaurant_id: int):
        """Envoie la liste des produits avec quantités"""
        restaurant = self.db.query(Restaurant).filter(Restaurant.id == restaurant_id).first()
        products = self.db.query(Product).filter(
            Product.restaurant_id == restaurant_id,
            Product.available == True
        ).all()
        
        if not products:
            self.whatsapp.send_message(phone, "😔 Pas de produits disponibles")
            return
        
        sections = []
        
        # Grouper par catégorie
        categories = {}
        for prod in products:
            cat = prod.category or "Autres"
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(prod)
        
        for cat, prods in categories.items():
            section_rows = []
            for prod in prods[:5]:  # Max 5 par section
                # Créer plusieurs options de quantité pour chaque produit
                for qty in [1, 2, 3]:
                    section_rows.append({
                        "id": f"prod_{prod.id}_{qty}",
                        "title": f"{qty}x {prod.name[:20]}",
                        "description": f"{int(prod.price * qty):,} GNF"
                    })
            
            if section_rows:
                sections.append({
                    "title": cat,
                    "rows": section_rows[:10]  # Max 10 rows par section
                })
        
        body = f"📋 Menu de {restaurant.name}\n\nSélectionnez vos plats:"
        self.whatsapp.send_list_message(phone, body, "🍽️ Voir le menu", sections[:5])

    def send_cart_summary(self, phone: str, context: Dict):
        """Envoie le récapitulatif du panier avec boutons d'action"""
        cart = context.get("current_order", [])
        if not cart:
            self.whatsapp.send_message(phone, "🛒 Votre panier est vide")
            return
        
        restaurant_name = context.get("selected_restaurant", {}).get("name", "Restaurant")
        subtotal = sum(item["price"] * item["quantity"] for item in cart)
        delivery_fee = config.BASE_DELIVERY_FEE
        total = subtotal + delivery_fee
        
        # Construire le message
        lines = [f"🛒 *Panier - {restaurant_name}*\n"]
        for item in cart:
            price_total = item["price"] * item["quantity"]
            lines.append(f"• {item['quantity']}× {item['name']}")
            lines.append(f"  {int(price_total):,} GNF")
        
        lines.append(f"\n💰 Sous-total: {int(subtotal):,} GNF")
        lines.append(f"🏍️ Livraison: {int(delivery_fee):,} GNF")
        lines.append(f"💳 *TOTAL: {int(total):,} GNF*")
        
        body = "\n".join(lines)
        
        # Boutons d'action
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
        """Envoie les options de paiement"""
        cart = context.get("current_order", [])
        subtotal = sum(item["price"] * item["quantity"] for item in cart)
        delivery_fee = config.BASE_DELIVERY_FEE
        total = subtotal + delivery_fee
        
        body = f"💳 Total à payer: {int(total):,} GNF\n\nChoisissez le mode de paiement:"
        
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
                    "title": "📱 Orange Money"
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
        """Finalise la commande"""
        try:
            cart = context.get("current_order", [])
            restaurant_id = context.get("selected_restaurant", {}).get("id")
            delivery_address = context.get("delivery_address")
            payment_method = context.get("payment_method", "cash")
            
            if not all([cart, restaurant_id, delivery_address]):
                self.whatsapp.send_message(phone, "❌ Informations manquantes")
                return
            
            # Créer le client
            customer = self.db.query(Customer).filter(Customer.phone_number == phone).first()
            if not customer:
                customer = Customer(phone_number=phone)
                self.db.add(customer)
                self.db.commit()
            
            # Calculer les totaux
            subtotal = sum(item["price"] * item["quantity"] for item in cart)
            delivery_fee = config.BASE_DELIVERY_FEE
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
                delivery_zone=context.get("selected_zone"),
                payment_method=payment_method,
                estimated_delivery_time=45,
                status=OrderStatus.PENDING
            )
            
            self.db.add(order)
            self.db.commit()
            
            # Notifier le restaurant
            self.notify_restaurant(order)
            
            # Message de confirmation
            confirmation = (
                f"🎉 *Commande #{order.id} confirmée!*\n\n"
                f"🍽️ {context.get('selected_restaurant', {}).get('name')}\n"
                f"📍 {delivery_address}\n"
                f"💰 Total: {int(total_amount):,} GNF\n"
                f"💳 Paiement: {payment_method}\n"
                f"⏱️ Livraison: ~45 min\n\n"
                f"Merci pour votre commande!"
            )
            
            self.whatsapp.send_message(phone, confirmation)
            
            # Réinitialiser le contexte
            context.clear()
            context["state"] = "new"
            self.update_conversation_context(phone, context)
            
        except Exception as e:
            logging.error(f"Order error: {e}")
            self.whatsapp.send_message(phone, "❌ Erreur lors de la commande")

    def notify_restaurant(self, order: Order):
        """Notifie le restaurant de la nouvelle commande"""
        try:
            restaurant = order.restaurant
            if not restaurant or not restaurant.phone_number:
                return
            
            items = json.loads(order.items)
            items_text = "\n".join([f"• {item['quantity']}× {item['name']}" for item in items])
            
            message = (
                f"🍽️ *NOUVELLE COMMANDE #{order.id}*\n\n"
                f"📱 Client: {order.customer.phone_number}\n"
                f"📍 Livraison: {order.delivery_address}\n"
                f"💰 Total: {int(order.total_amount):,} GNF\n\n"
                f"*Articles:*\n{items_text}\n\n"
                f"💳 Paiement: {order.payment_method}"
            )
            
            self.whatsapp.send_message(restaurant.phone_number, message)
            
        except Exception as e:
            logging.error(f"Restaurant notification error: {e}")

# -----------------------------------------------------------------------------
# API FastAPI
# -----------------------------------------------------------------------------
app = FastAPI(title="Conakry Food Interactive API", version="2.0.0")

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
        "message": "Conakry Food Interactive API",
        "version": "2.0.0",
        "features": "Interactive buttons and lists"
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

# -----------------------------------------------------------------------------
# Initialisation des données
# -----------------------------------------------------------------------------
async def init_sample_data():
    db = SessionLocal()
    try:
        if db.query(Restaurant).count() == 0:
            restaurants = [
                Restaurant(
                    name="Chez Mizo",
                    phone_number="33755347855",
                    address="Kipé Centre",
                    zone="Kipé",
                    latitude=9.5900,
                    longitude=-13.6100,
                    delivery_zones=json.dumps(["Kipé", "Ratoma", "Matam"]),
                    average_prep_time=25
                ),
                Restaurant(
                    name="Restaurant Barita",
                    phone_number="224622334455",
                    address="Kaloum, Avenue",
                    zone="Kaloum",
                    latitude=9.5380,
                    longitude=-13.6773,
                    delivery_zones=json.dumps(["Kaloum", "Dixinn"]),
                    average_prep_time=30
                ),
                Restaurant(
                    name="Le Délice",
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
            
            # Produits pour Chez Mizo
            mizo = db.query(Restaurant).filter(Restaurant.name == "Chez Mizo").first()
            if mizo:
                products = [
                    Product(restaurant_id=mizo.id, name="Riz sauce", price=15000, category="Plats", description="Riz sauce arachide"),
                    Product(restaurant_id=mizo.id, name="Riz gras", price=12000, category="Plats", description="Riz au gras"),
                    Product(restaurant_id=mizo.id, name="Poulet", price=25000, category="Plats", description="Poulet braisé"),
                    Product(restaurant_id=mizo.id, name="Poisson", price=20000, category="Plats", description="Poisson grillé"),
                    Product(restaurant_id=mizo.id, name="Coca", price=3000, category="Boissons", description="Coca-Cola"),
                    Product(restaurant_id=mizo.id, name="Eau", price=2000, category="Boissons", description="Eau minérale"),
                ]
                for product in products:
                    db.add(product)
            
            db.commit()
        
        logging.info("✅ Sample data initialized")
        
    except Exception as e:
        logging.error(f"Init error: {e}")
        db.rollback()
    finally:
        db.close()

@app.on_event("startup")
async def startup_event():
    await init_sample_data()
    logging.info("🚀 Conakry Food Interactive started")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port, reload=True)