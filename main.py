# main.py
# Conakry Food – Flow 100% Listes & Boutons (R5)
# FastAPI + SQLAlchemy + WhatsApp Cloud API v22
# Étapes:
# 1) Zone (liste) -> 2) Restaurant (liste) -> 3) Menu (liste) -> 4) Quantité (boutons)
# 5) Ajouter +/– / Checkout -> 6) Confirmation -> Envoi resto + Accusé client

import os
import json
import logging
from datetime import datetime
from typing import List, Dict, Optional

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy import create_engine, Column, Integer, String, DateTime, Float, Text, ForeignKey, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship

import requests

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
class Config:
    WHATSAPP_TOKEN: str = os.getenv("WHATSAPP_TOKEN", "YOUR_WHATSAPP_TOKEN")
    WHATSAPP_PHONE_ID: str = os.getenv("WHATSAPP_PHONE_ID", "YOUR_PHONE_ID")
    WHATSAPP_VERIFY_TOKEN: str = os.getenv("WHATSAPP_VERIFY_TOKEN", "verify_token_123")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./conakry_food.db")

    # Numéro par défaut si un restaurant n'a pas de numéro (E.164 sans '+')
    DEFAULT_RESTAURANT_PHONE: str = os.getenv("DEFAULT_RESTAURANT_PHONE", "224611223344")

config = Config()

# Zones Conakry (affichées en liste)
CONAKRY_ZONES = [
    "Kaloum", "Dixinn", "Ratoma", "Matam", "Matoto",
    "Kipé", "Camayenne", "Almamya", "Lambandji", "Sonfonia",
    "Hamdallaye", "Koloma", "Kagbelen", "Nongo", "Simbaya"
]

# -----------------------------------------------------------------------------
# DB
# -----------------------------------------------------------------------------
engine = create_engine(config.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class OrderStatus:
    PENDING = "pending"
    CONFIRMED = "confirmed"
    PREPARING = "preparing"
    READY = "ready"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"

class Restaurant(Base):
    __tablename__ = "restaurants"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    phone_number = Column(String)          # numéro WhatsApp pour recevoir la commande
    address = Column(Text)
    zone = Column(String)                  # zone principale (ex: "Kipé")
    is_active = Column(Boolean, default=True)
    average_prep_time = Column(Integer, default=30)
    rating = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    products = relationship("Product", back_populates="restaurant")

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"))
    name = Column(String, index=True)
    description = Column(Text)
    price = Column(Float)                  # GNF
    category = Column(String)
    available = Column(Boolean, default=True)
    restaurant = relationship("Restaurant", back_populates="products")

class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"))
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"))
    items = Column(Text)                   # JSON [{name, price, quantity}]
    total_amount = Column(Float)
    status = Column(String, default=OrderStatus.PENDING)
    created_at = Column(DateTime, default=datetime.utcnow)
    customer = relationship("Customer")
    restaurant = relationship("Restaurant")

class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, index=True)
    context = Column(Text)  # JSON
    last_interaction = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# -----------------------------------------------------------------------------
# WhatsApp Service (v22) – text, list, buttons
# -----------------------------------------------------------------------------
class WhatsAppService:
    def __init__(self):
        self.token = config.WHATSAPP_TOKEN
        self.phone_id = config.WHATSAPP_PHONE_ID
        self.base_url = f"https://graph.facebook.com/v22.0/{self.phone_id}"

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    def send_text(self, to: str, text: str) -> bool:
        data = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text}
        }
        return self._post(data)

    def send_list(self, to: str, header_text: str, body_text: str, button_text: str, rows: List[Dict]) -> bool:
        """
        rows: [{"id":"zone:Kipé","title":"Kipé","description":"Ratoma"}, ...] (max 10 par section)
        """
        if not rows:
            return False
        data = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "header": {"type": "text", "text": header_text[:60]},
                "body": {"text": body_text[:1024]},
                "footer": {"text": "Conakry Food"},
                "action": {
                    "button": button_text[:20],
                    "sections": [{
                        "title": "Options",
                        "rows": rows[:10]
                    }]
                }
            }
        }
        return self._post(data)

    def send_buttons(self, to: str, body_text: str, buttons: List[Dict]) -> bool:
        """
        buttons: [{"type":"reply","reply":{"id":"qty:1","title":"1"}}, ...] (max 3)
        """
        if not buttons:
            return False
        data = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body_text[:1024]},
                "action": {"buttons": buttons[:3]}
            }
        }
        return self._post(data)

    def _post(self, json_body: Dict) -> bool:
        try:
            r = requests.post(f"{self.base_url}/messages", headers=self._headers(), json=json_body, timeout=15)
            ok = r.status_code in (200, 201)
            if ok:
                logging.info(f"WA ok: {r.text}")
            else:
                logging.error(f"WA fail {r.status_code}: {r.text}")
            return ok
        except Exception as e:
            logging.error(f"WA error: {e}")
            return False

# -----------------------------------------------------------------------------
# Conversation Service – 100% sans saisie
# -----------------------------------------------------------------------------
class ConversationService:
    def __init__(self, db: Session):
        self.db = db
        self.wa = WhatsAppService()

    def _get_ctx(self, phone: str) -> Dict:
        conv = self.db.query(Conversation).filter(Conversation.phone_number == phone).first()
        if conv and conv.context:
            return json.loads(conv.context)
        return {"state": "new", "zone": None, "restaurant_id": None, "cart": [], "pending_product_id": None}

    def _save_ctx(self, phone: str, ctx: Dict):
        conv = self.db.query(Conversation).filter(Conversation.phone_number == phone).first()
        if not conv:
            conv = Conversation(phone_number=phone)
            self.db.add(conv)
        conv.context = json.dumps(ctx)
        conv.last_interaction = datetime.utcnow()
        self.db.commit()

    # ---------- Steps
    def send_zone_list(self, phone: str):
        rows = [{"id": f"zone:{z}", "title": z, "description": "Conakry"} for z in CONAKRY_ZONES]
        self.wa.send_list(phone, "📍 Choisissez votre zone", "Sélectionnez votre quartier à Conakry :", "Choisir", rows)

    def send_restaurant_list(self, phone: str, zone: str):
        restos = self.db.query(Restaurant).filter(Restaurant.is_active == True).all()
        # Filtrage simple par sous-chaîne pour matcher ex: "Kipé"
        restos = [r for r in restos if (r.zone or "").lower().find(zone.lower()) >= 0]
        if not restos:
            self.wa.send_text(phone, f"😕 Aucun restaurant à {zone} pour le moment. Choisissez une autre zone.")
            self.send_zone_list(phone)
            return
        rows = []
        for r in restos[:10]:
            rating = f"{r.rating:.1f}⭐" if r.rating and r.rating > 0 else "Nouveau"
            desc = f"{rating} • ⏱ {r.average_prep_time or 30}min"
            rows.append({"id": f"rest:{r.id}", "title": r.name[:24], "description": desc[:72]})
        self.wa.send_list(phone, f"🍽️ Restaurants à {zone}", "Sélectionnez un restaurant :", "Voir", rows)

    def send_menu_list(self, phone: str, restaurant_id: int):
        prods = self.db.query(Product).filter(
            Product.restaurant_id == restaurant_id,
            Product.available == True
        ).all()
        if not prods:
            self.wa.send_text(phone, "😕 Ce restaurant n'a pas encore de menu.")
            return
        rows = []
        for p in prods[:10]:
            price = f"{int(p.price):,} GNF".replace(",", " ")
            desc = f"{price}"
            if p.description:
                desc = f"{price} • {p.description}"
            rows.append({"id": f"prod:{p.id}", "title": p.name[:24], "description": desc[:72]})
        self.wa.send_list(phone, "📋 Menu", "Choisissez un plat :", "Sélectionner", rows)

    def send_quantity_buttons(self, phone: str, product_name: str):
        body = f"Combien de « {product_name} » ?"
        buttons = [
            {"type": "reply", "reply": {"id": "qty:1", "title": "1"}},
            {"type": "reply", "reply": {"id": "qty:2", "title": "2"}},
            {"type": "reply", "reply": {"id": "qty:3", "title": "3"}}
        ]
        self.wa.send_buttons(phone, body, buttons)

    def send_add_more_or_checkout(self, phone: str):
        body = "Souhaitez-vous ajouter un autre plat, ou passer à la confirmation ?"
        buttons = [
            {"type": "reply", "reply": {"id": "more:add", "title": "Ajouter"}},
            {"type": "reply", "reply": {"id": "more:checkout", "title": "Valider"}}
        ]
        self.wa.send_buttons(phone, body, buttons)

    def _cart_lines_and_total(self, cart: List[Dict]) -> (List[str], float):
        lines = []
        total = 0.0
        for it in cart:
            line_total = it["price"] * it["quantity"]
            total += line_total
            lines.append(f"• {it['quantity']}× {it['name']} — {int(line_total):,} GNF".replace(",", " "))
        return lines, total

    def confirm_order(self, phone: str, ctx: Dict):
        cart = ctx.get("cart", [])
        if not cart or not ctx.get("restaurant_id"):
            self.wa.send_text(phone, "🛒 Panier vide. Ajoutez un plat.")
            return

        lines, total = self._cart_lines_and_total(cart)
        resto = self.db.query(Restaurant).filter(Restaurant.id == ctx["restaurant_id"]).first()
        resto_phone = (resto.phone_number or config.DEFAULT_RESTAURANT_PHONE)

        # Envoi au restaurant
        admin_msg = (f"🍽️ *Nouvelle commande*\n"
                     f"Client: {phone}\n"
                     f"Restaurant: {resto.name}\n\n" +
                     "\n".join(lines) + "\n\n" +
                     f"Total: {int(total):,} GNF".replace(",", " "))
        self.wa.send_text(resto_phone, admin_msg)

        # Accusé client
        self.wa.send_text(
            phone,
            f"🎉 Commande envoyée à *{resto.name}*.\n"
            f"Total: {int(total):,} GNF\n"
            f"👨‍🍳 Le restaurant va confirmer et préparer votre commande."
            .replace(",", " ")
        )

        # Reset panier
        ctx["cart"] = []
        self._save_ctx(phone, ctx)

    # ---------- Entry points
    def handle_text(self, phone: str, text: str) -> None:
        ctx = self._get_ctx(phone)
        t = (text or "").strip().lower()

        # Entrées “libres” minimales pour démarrer/revenir en arrière
        if t in ("bonjour", "salut", "hello", "menu", "commencer", "start"):
            ctx["state"] = "pick_zone"
            self._save_ctx(phone, ctx)
            self.wa.send_text(phone, "Bienvenue 👋\nNous allons commander sans écrire. Suivez les étapes.")
            self.send_zone_list(phone)
            return

        # Si l'utilisateur tape du texte imprévu, on lui remontre où il en est
        state = ctx.get("state", "new")
        if state in ("new", "pick_zone"):
            self.wa.send_text(phone, "Choisissez votre *zone* dans la liste ci-dessous.")
            self.send_zone_list(phone)
        elif state == "pick_restaurant":
            self.wa.send_text(phone, "Choisissez un *restaurant* dans la liste ci-dessous.")
            self.send_restaurant_list(phone, ctx.get("zone") or "")
        elif state == "pick_product":
            self.wa.send_text(phone, "Choisissez un *plat* dans le menu ci-dessous.")
            self.send_menu_list(phone, ctx.get("restaurant_id"))
        elif state == "pick_quantity":
            self.wa.send_text(phone, "Choisissez la *quantité* avec les boutons.")
            # on renverra les boutons lors du list_reply précédent
        else:
            self.wa.send_text(phone, "Utilisez les *boutons* et *listes* qui s’affichent 👇")

    def handle_list_reply(self, phone: str, list_reply_id: str, title: str) -> None:
        """
        list_reply_id patterns:
          zone:<ZoneName>
          rest:<RestaurantId>
          prod:<ProductId>
        """
        ctx = self._get_ctx(phone)

        if list_reply_id.startswith("zone:"):
            zone = list_reply_id.split(":", 1)[1]
            ctx["zone"] = zone
            ctx["restaurant_id"] = None
            ctx["cart"] = ctx.get("cart", [])
            ctx["state"] = "pick_restaurant"
            self._save_ctx(phone, ctx)
            self.send_restaurant_list(phone, zone)
            return

        if list_reply_id.startswith("rest:"):
            try:
                rest_id = int(list_reply_id.split(":", 1)[1])
            except Exception:
                self.wa.send_text(phone, "❌ Restaurant invalide.")
                return
            ctx["restaurant_id"] = rest_id
            ctx["state"] = "pick_product"
            self._save_ctx(phone, ctx)
            self.send_menu_list(phone, rest_id)
            return

        if list_reply_id.startswith("prod:"):
            try:
                prod_id = int(list_reply_id.split(":", 1)[1])
            except Exception:
                self.wa.send_text(phone, "❌ Plat invalide.")
                return
            p = self.db.query(Product).filter(Product.id == prod_id).first()
            if not p:
                self.wa.send_text(phone, "❌ Plat introuvable.")
                return
            ctx["pending_product_id"] = prod_id
            ctx["state"] = "pick_quantity"
            self._save_ctx(phone, ctx)
            self.send_quantity_buttons(phone, p.name)
            return

        # fallback
        self.wa.send_text(phone, "Action non reconnue. Utilisez la liste affichée.")

    def handle_button_reply(self, phone: str, button_reply_id: str, title: str) -> None:
        """
        button_reply_id patterns:
          qty:<n>           (ex: qty:1/2/3)
          more:add
          more:checkout
        """
        ctx = self._get_ctx(phone)

        if button_reply_id.startswith("qty:"):
            try:
                q = int(button_reply_id.split(":", 1)[1])
            except Exception:
                self.wa.send_text(phone, "Quantité invalide.")
                return
            prod_id = ctx.get("pending_product_id")
            if not (prod_id and ctx.get("restaurant_id")):
                self.wa.send_text(phone, "Sélectionnez d’abord un plat.")
                return
            p = self.db.query(Product).filter(Product.id == prod_id).first()
            if not p:
                self.wa.send_text(phone, "Plat introuvable.")
                return
            # Ajout au panier
            ctx.setdefault("cart", [])
            # Fusion si même plat déjà présent
            merged = False
            for it in ctx["cart"]:
                if it["product_id"] == p.id:
                    it["quantity"] += q
                    merged = True
                    break
            if not merged:
                ctx["cart"].append({
                    "product_id": p.id,
                    "name": p.name,
                    "price": float(p.price),
                    "quantity": q
                })
            ctx["pending_product_id"] = None
            ctx["state"] = "post_add"
            self._save_ctx(phone, ctx)

            # Récap partiel
            lines, total = self._cart_lines_and_total(ctx["cart"])
            self.wa.send_text(phone, "✅ Ajouté !\n\n" + "\n".join(lines) + f"\n\nTotal: {int(total):,} GNF".replace(",", " "))
            self.send_add_more_or_checkout(phone)
            return

        if button_reply_id == "more:add":
            ctx["state"] = "pick_product"
            self._save_ctx(phone, ctx)
            self.send_menu_list(phone, ctx.get("restaurant_id"))
            return

        if button_reply_id == "more:checkout":
            # Confirmation finale
            self.confirm_order(phone, ctx)
            return

        # fallback
        self.wa.send_text(phone, "Bouton non reconnu.")

# -----------------------------------------------------------------------------
# API
# -----------------------------------------------------------------------------
app = FastAPI(title="Conakry Food – No-Typing Flow", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

@app.on_event("startup")
def seed_on_startup():
    init_sample_data()
    logging.info("✅ Sample data ready")

@app.get("/")
def root():
    return {"status": "running", "version": "1.0.0"}

@app.get("/webhook")
def verify_webhook(request: Request):
    vt = request.query_params.get("hub.verify_token")
    ch = request.query_params.get("hub.challenge")
    if vt == config.WHATSAPP_VERIFY_TOKEN:
        return PlainTextResponse(content=ch or "")
    raise HTTPException(status_code=403, detail="Invalid verification token")

@app.post("/webhook")
def handle_webhook(request: Request, db: Session = Depends(get_db)):
    try:
        body = request.json() if isinstance(request, dict) else None
    except Exception:
        body = None
    # FastAPI sync path: fetch body properly
    if body is None:
        body = {}
    try:
        # When run truly async, use: body = await request.json()
        body = body or {}
    except Exception:
        body = {}

    try:
        body = body or {}
        # If not using the hack above, do the proper await:
        # (works if route async)
        # body = await request.json()
    except Exception:
        pass

    try:
        # Re-do properly for sync route:
        import json as _json
        body = _json.loads(request.scope.get("body", b"{}").decode()) if not body else body
    except Exception:
        pass

    try:
        # Best effort
        body = body or {}
        logging.info(f"INCOMING: {json.dumps(body)[:1200]}")
    except Exception:
        pass

    # Robust parsing
    try:
        entries = body.get("entry", [])
        if not entries:
            return JSONResponse({"status": "ignored"})

        wa = WhatsAppService()
        processed = False

        for entry in entries:
            for change in entry.get("changes", []):
                value = change.get("value", {})
                messages = value.get("messages", [])
                if not messages:
                    continue

                conv = ConversationService(next(get_db()))

                for msg in messages:
                    from_number = msg.get("from")
                    mtype = msg.get("type")

                    if mtype == "text":
                        text = (msg.get("text") or {}).get("body", "") or ""
                        if text.strip():
                            conv.handle_text(from_number, text.strip())
                            processed = True

                    elif mtype == "interactive":
                        interactive = msg.get("interactive", {})
                        # List reply
                        if "list_reply" in interactive:
                            lr = interactive["list_reply"]
                            conv.handle_list_reply(from_number, lr.get("id", ""), lr.get("title", ""))
                            processed = True
                        # Button reply
                        elif "button_reply" in interactive:
                            br = interactive["button_reply"]
                            conv.handle_button_reply(from_number, br.get("id", ""), br.get("title", ""))
                            processed = True

        return JSONResponse({"status": "success" if processed else "ok-empty"})

    except Exception as e:
        logging.exception(f"Webhook error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

# -----------------------------------------------------------------------------
# Sample data
# -----------------------------------------------------------------------------
def init_sample_data():
    db = SessionLocal()
    try:
        if db.query(Restaurant).count() == 0:
            r1 = Restaurant(name="Chez Mizo", phone_number="224622000111", zone="Kipé", average_prep_time=25, rating=4.6)
            r2 = Restaurant(name="Restaurant Barita", phone_number="224633111222", zone="Kaloum", average_prep_time=30, rating=4.4)
            r3 = Restaurant(name="Le Délice de Ratoma", phone_number="224655222333", zone="Ratoma", average_prep_time=20, rating=4.2)
            db.add_all([r1, r2, r3]); db.commit()
            db.refresh(r1); db.refresh(r2); db.refresh(r3)

            db.add_all([
                Product(restaurant_id=r1.id, name="Riz sauce arachide", description="Mafé", price=15000, category="Plat"),
                Product(restaurant_id=r1.id, name="Riz au gras", description="Au bon goût local", price=12000, category="Plat"),
                Product(restaurant_id=r1.id, name="Poisson braisé", description="Grillé aux épices", price=25000, category="Plat"),
                Product(restaurant_id=r1.id, name="Coca-Cola 33cl", description="", price=3000, category="Boisson"),

                Product(restaurant_id=r2.id, name="Poulet yassa", description="", price=22000, category="Plat"),
                Product(restaurant_id=r2.id, name="Atiéké poisson", description="", price=20000, category="Plat"),
                Product(restaurant_id=r2.id, name="Eau minérale 50cl", description="", price=2000, category="Boisson"),

                Product(restaurant_id=r3.id, name="Fouti fonio", description="", price=18000, category="Plat"),
                Product(restaurant_id=r3.id, name="Salade de fruits", description="", price=8000, category="Dessert"),
            ])
            db.commit()
    finally:
        db.close()

# -----------------------------------------------------------------------------
# Run
# -----------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
