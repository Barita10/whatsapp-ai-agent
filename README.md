# Documentation Technique
## Agent WhatsApp Conakry Food Connect

### Version 1.0 | Système de Commandes Multi-Restaurants pour Conakry

---

## Table des Matières

1. [Vue d'ensemble du système](#vue-densemble)
2. [Architecture technique](#architecture)
3. [Fonctionnalités restaurants](#fonctionnalités-restaurants)
4. [Guide d'utilisation restaurant](#guide-restaurant)
5. [APIs et intégrations](#apis-intégrations)
6. [Base de données](#base-de-données)
7. [Configuration et déploiement](#configuration)
8. [Sécurité](#sécurité)
9. [Monitoring et maintenance](#monitoring)
10. [Support et dépannage](#support)

---

## 1. Vue d'ensemble du système {#vue-densemble}

### 1.1 Description générale

Conakry Food Connect est un agent WhatsApp intelligent conçu spécifiquement pour les restaurants de Conakry, Guinée. Le système automatise les commandes de nourriture via WhatsApp Business, intègre les paiements mobile money locaux, et coordonne la livraison par taxi-motos.

### 1.2 Acteurs du système

- **Clients** : Passent commandes via WhatsApp
- **Restaurants** : Reçoivent et gèrent les commandes
- **Livreurs** : Taxi-motos assurant la livraison
- **Administrateur** : Supervise la plateforme

### 1.3 Zones de couverture

Le système couvre 15 zones de Conakry :
- Kaloum, Dixinn, Ratoma, Matam, Matoto
- Kipé, Camayenne, Almamya, Lambandji, Sonfonia
- Hamdallaye, Koloma, Kagbelen, Nongo, Simbaya

### 1.4 Technologies utilisées

- **Backend** : Python 3.11, FastAPI, SQLAlchemy
- **Base de données** : PostgreSQL (Railway)
- **Messaging** : WhatsApp Business Cloud API v22
- **Paiements** : Orange Money API, MTN Mobile Money
- **Géolocalisation** : Google Maps API
- **Déploiement** : Railway, Docker

---

## 2. Architecture technique {#architecture}

### 2.1 Architecture globale du système

```
                                CONAKRY FOOD CONNECT
                                 ARCHITECTURE SYSTÈME
    
    ┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
    │                 │    │                  │    │                 │
    │   CLIENT LAYER  │◄──►│  MESSAGING LAYER │◄──►│ APPLICATION     │
    │                 │    │                  │    │ LAYER           │
    └─────────────────┘    └──────────────────┘    └─────────────────┘
           │                        │                       │
           │                        │                       │
    ┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
    │                 │    │                  │    │                 │
    │ EXTERNAL APIS   │◄──►│   DATA LAYER     │◄──►│ BUSINESS LOGIC  │
    │                 │    │                  │    │ SERVICES        │
    └─────────────────┘    └──────────────────┘    └─────────────────┘
```

### 2.2 Architecture détaillée par couches

#### 2.2.1 Client Layer (Couche Client)
```
┌─────────────────────────────────────────────────────────────────┐
│                         CLIENT LAYER                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │             │  │             │  │             │             │
│  │  CLIENTS    │  │ RESTAURANTS │  │  LIVREURS   │             │
│  │             │  │             │  │             │             │
│  │ WhatsApp    │  │ WhatsApp    │  │ WhatsApp    │             │
│  │ Mobile      │  │ Business    │  │ Mobile      │             │
│  │             │  │             │  │             │             │
│  └─────────────┘  └─────────────┘  └─────────────┘             │
│        │                │                │                     │
│        └────────────────┼────────────────┘                     │
│                         │                                      │
└─────────────────────────┼──────────────────────────────────────┘
                          │
                          ▼
```

#### 2.2.2 Messaging Layer (Couche Messagerie)
```
┌─────────────────────────────────────────────────────────────────┐
│                       MESSAGING LAYER                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │             WhatsApp Business Cloud API v22             │   │
│  │                                                         │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │   │
│  │  │   Webhook   │  │  Messages   │  │  Templates  │     │   │
│  │  │ Validation  │  │   Sending   │  │   Fallback  │     │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘     │   │
│  │                                                         │   │
│  └─────────────────────────────────────────────────────────┘   │
│                         │                                       │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                Rate Limiting                            │   │
│  │          (300 messages/minute par numéro)              │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────┼───────────────────────────────────────┘
                          │
                          ▼
```

#### 2.2.3 Application Layer (Couche Application)
```
┌─────────────────────────────────────────────────────────────────┐
│                     APPLICATION LAYER                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                 FastAPI Framework                       │   │
│  │                                                         │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │   │
│  │  │   Webhook    │  │     API      │  │    Health    │  │   │
│  │  │   Handler    │  │  Endpoints   │  │    Check     │  │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘  │   │
│  │                                                         │   │
│  └─────────────────────────────────────────────────────────┘   │
│                         │                                       │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │               Request Processing                        │   │
│  │                                                         │   │
│  │  Validation → Routing → Business Logic → Response      │   │
│  │                                                         │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────┼───────────────────────────────────────┘
                          │
                          ▼
```

#### 2.2.4 Business Logic Layer (Couche Logique Métier)
```
┌─────────────────────────────────────────────────────────────────┐
│                    BUSINESS LOGIC LAYER                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐ │
│  │                  │  │                  │  │                  │ │
│  │ CONVERSATION     │  │     ORDER        │  │    DELIVERY      │ │
│  │ SERVICE          │  │    SERVICE       │  │    SERVICE       │ │
│  │                  │  │                  │  │                  │ │
│  │ ┌──────────────┐ │  │ ┌──────────────┐ │  │ ┌──────────────┐ │ │
│  │ │Intent        │ │  │ │Order         │ │  │ │Distance      │ │ │
│  │ │Detection     │ │  │ │Creation      │ │  │ │Calculation   │ │ │
│  │ └──────────────┘ │  │ └──────────────┘ │  │ └──────────────┘ │ │
│  │ ┌──────────────┐ │  │ ┌──────────────┐ │  │ ┌──────────────┐ │ │
│  │ │Context       │ │  │ │Status        │ │  │ │Driver        │ │ │
│  │ │Management    │ │  │ │Management    │ │  │ │Assignment    │ │ │
│  │ └──────────────┘ │  │ └──────────────┘ │  │ └──────────────┘ │ │
│  │ ┌──────────────┐ │  │ ┌──────────────┐ │  │ ┌──────────────┐ │ │
│  │ │Text Parsing  │ │  │ │Commission    │ │  │ │Fee           │ │ │
│  │ │(Guinean)     │ │  │ │Calculation   │ │  │ │Calculation   │ │ │
│  │ └──────────────┘ │  │ └──────────────┘ │  │ └──────────────┘ │ │
│  │                  │  │                  │  │                  │ │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘ │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                  WHATSAPP SERVICE                       │   │
│  │                                                         │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │   │
│  │  │   Message    │  │   Template   │  │  Interactive │  │   │
│  │  │   Sending    │  │   Sending    │  │   Messages   │  │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘  │   │
│  │                                                         │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────┼───────────────────────────────────────┘
                          │
                          ▼
```

### 2.3 Data Layer (Couche Données)

#### 2.3.1 Base de données PostgreSQL
```
┌─────────────────────────────────────────────────────────────────┐
│                        DATA LAYER                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                PostgreSQL Database                      │   │
│  │                     (Railway)                           │   │
│  │                                                         │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │   │
│  │  │              │  │              │  │              │  │   │
│  │  │ restaurants  │  │   customers  │  │    orders    │  │   │
│  │  │              │  │              │  │              │  │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘  │   │
│  │                                                         │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │   │
│  │  │              │  │              │  │              │  │   │
│  │  │   products   │  │delivery_     │  │conversations│  │   │
│  │  │              │  │drivers       │  │              │  │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘  │   │
│  │                                                         │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                  SQLAlchemy ORM                         │   │
│  │                                                         │   │
│  │     Models ↔ Database ↔ Migrations ↔ Relationships     │   │
│  │                                                         │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────┼───────────────────────────────────────┘
                          │
                          ▼
```

### 2.4 External APIs Layer (Couche APIs Externes)

```
┌─────────────────────────────────────────────────────────────────┐
│                     EXTERNAL APIS LAYER                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐ │
│  │                  │  │                  │  │                  │ │
│  │  PAYMENT APIS    │  │  GEOLOCATION     │  │  NOTIFICATIONS   │ │
│  │                  │  │                  │  │                  │ │
│  │ ┌──────────────┐ │  │ ┌──────────────┐ │  │ ┌──────────────┐ │ │
│  │ │Orange Money  │ │  │ │Google Maps   │ │  │ │SMS Gateway   │ │ │
│  │ │API (GN)      │ │  │ │Geocoding     │ │  │ │(Backup)      │ │ │
│  │ └──────────────┘ │  │ └──────────────┘ │  │ └──────────────┘ │ │
│  │ ┌──────────────┐ │  │ ┌──────────────┐ │  │ ┌──────────────┐ │ │
│  │ │MTN Mobile    │ │  │ │Distance      │ │  │ │Email         │ │ │
│  │ │Money API     │ │  │ │Matrix        │ │  │ │Notifications │ │ │
│  │ └──────────────┘ │  │ └──────────────┘ │  │ └──────────────┘ │ │
│  │                  │  │ ┌──────────────┐ │  │                  │ │
│  │                  │  │ │Places API    │ │  │                  │ │
│  │                  │  │ │              │ │  │                  │ │
│  │                  │  │ └──────────────┘ │  │                  │ │
│  │                  │  │                  │  │                  │ │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘ │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 2.5 Flux de données détaillé

#### 2.5.1 Flux de commande client
```
CLIENT                 SYSTÈME                RESTAURANT           LIVREUR
  │                      │                       │                   │
  │ 1. "Bonjour"         │                       │                   │
  ├─────────────────────►│                       │                   │
  │                      │ 2. Intent Detection   │                   │
  │                      │    → "greeting"       │                   │
  │                      │                       │                   │
  │ ◄─────────────────────┤ 3. Zone Selection    │                   │
  │ "Quelle zone?"       │                       │                   │
  │                      │                       │                   │
  │ 4. "Kipé"            │                       │                   │
  ├─────────────────────►│                       │                   │
  │                      │ 5. Restaurant Query   │                   │
  │                      │    → Database         │                   │
  │                      │                       │                   │
  │ ◄─────────────────────┤ 6. Restaurant List   │                   │
  │ "Restaurants Kipé"   │                       │                   │
  │                      │                       │                   │
  │ 7. "1"               │                       │                   │
  ├─────────────────────►│                       │                   │
  │                      │ 8. Menu Query         │                   │
  │                      │    → Database         │                   │
  │                      │                       │                   │
  │ ◄─────────────────────┤ 9. Menu Display      │                   │
  │ "Menu Chez Fatou"    │                       │                   │
  │                      │                       │                   │
  │ 10. "2 riz arachide" │                       │                   │
  ├─────────────────────►│                       │                   │
  │                      │ 11. Parse Order       │                   │
  │                      │     → Context Save    │                   │
  │                      │                       │                   │
  │ ◄─────────────────────┤ 12. Cart Summary     │                   │
  │ "Panier: 2×..."      │                       │                   │
  │                      │                       │                   │
  │ 13. "confirmer"      │                       │                   │
  ├─────────────────────►│                       │                   │
  │                      │ 14. Order Creation    │                   │
  │                      │     → Database        │                   │
  │                      │                       │                   │
  │                      │ 15. Restaurant Notif  │                   │
  │                      ├──────────────────────►│                   │
  │                      │                       │ "Nouvelle commande" │
  │                      │                       │                   │
  │                      │ 16. "accepter 123"    │                   │
  │                      │◄──────────────────────┤                   │
  │                      │                       │                   │
  │                      │ 17. Status Update     │                   │
  │                      │     → Database        │                   │
  │                      │                       │                   │
  │ ◄─────────────────────┤ 18. Client Confirm   │                   │
  │ "Commande acceptée"  │                       │                   │
  │                      │                       │                   │
  │                      │                       │ 19. "pret 123"   │
  │                      │◄──────────────────────┤                   │
  │                      │                       │                   │
  │                      │ 20. Driver Search     │                   │
  │                      │     → Algorithm       │                   │
  │                      │                       │                   │
  │                      │ 21. Driver Notif      │                   │
  │                      ├───────────────────────────────────────────►│
  │                      │                       │ "Nouvelle livraison" │
  │                      │                       │                   │
  │                      │                       │ 22. "prendre 123"│
  │                      │◄───────────────────────────────────────────┤
  │                      │                       │                   │
  │ ◄─────────────────────┤ 23. Delivery Notif   │                   │
  │ "Livreur en route"   │                       │                   │
```

#### 2.5.2 Flux de paiement mobile money
```
CLIENT              SYSTÈME           ORANGE MONEY        MTN MOMO
  │                   │                     │                │
  │ Payment Request   │                     │                │
  ├──────────────────►│                     │                │
  │                   │ Auth Request        │                │
  │                   ├────────────────────►│                │
  │                   │ Access Token        │                │
  │                   │◄────────────────────┤                │
  │                   │                     │                │
  │                   │ Payment Init        │                │
  │                   ├────────────────────►│                │
  │                   │ Payment URL         │                │
  │                   │◄────────────────────┤                │
  │                   │                     │                │
  │ Payment URL       │                     │                │
  │◄──────────────────┤                     │                │
  │                   │                     │                │
  │ Complete Payment  │                     │                │
  ├───────────────────┼────────────────────►│                │
  │                   │                     │                │
  │                   │ Webhook Confirm     │                │
  │                   │◄────────────────────┤                │
  │                   │                     │                │
  │ Payment Success   │                     │                │
  │◄──────────────────┤                     │                │
```

---

## 3. Fonctionnalités restaurants {#fonctionnalités-restaurants}

### 3.1 Gestion des commandes

#### 3.1.1 Réception automatique
- Notification instantanée via WhatsApp
- Détails complets de la commande
- Informations client et livraison
- Calcul automatique des commissions

#### 3.1.2 Commandes de gestion
Les restaurants contrôlent leurs commandes via messages WhatsApp :

```
accepter 123     → Accepte la commande #123
refuser 123      → Refuse la commande #123
preparer 123     → Marque en préparation
pret 123         → Prêt pour livraison
temps 123 45     → Modifie le temps (45 min)
```

#### 3.1.3 Statuts de commande
1. `pending` : En attente de validation restaurant
2. `confirmed` : Acceptée par le restaurant
3. `preparing` : En cours de préparation
4. `ready` : Prête pour récupération
5. `assigned` : Livreur assigné
6. `delivering` : En cours de livraison
7. `delivered` : Livrée au client
8. `cancelled` : Annulée

### 3.2 Gestion du catalogue

#### 3.2.1 Structure produit
```python
Product {
    id: int
    restaurant_id: int
    name: string          # Ex: "Riz sauce arachide"
    description: string   # Description détaillée
    price: float         # Prix en GNF
    category: string     # "Plat principal", "Boisson", etc.
    available: boolean   # Disponibilité
}
```

#### 3.2.2 Synonymes locaux
Le système reconnaît automatiquement les termes guinéens :
- "riz sauce arachide" → "mafé" → "riz arachide"
- "fouti fonio" → "fonio"
- "atiéké poisson" → "attieke"
- "poisson braisé" → "poisson grillé"

### 3.3 Configuration restaurant

#### 3.3.1 Paramètres de base
```python
Restaurant {
    name: string                    # Nom du restaurant
    phone_number: string           # Format: 224XXXXXXXXX
    address: string                # Adresse complète
    zone: string                   # Zone de Conakry
    delivery_zones: JSON          # Zones de livraison
    average_prep_time: int         # Temps moyen (minutes)
    commission_rate: float         # 15% par défaut
    is_active: boolean            # Statut actif/inactif
}
```

#### 3.3.2 Zones de livraison
Les restaurants définissent leurs zones de livraison :
```json
{
  "delivery_zones": ["Kipé", "Ratoma", "Matam"]
}
```

---

## 4. Guide d'utilisation restaurant {#guide-restaurant}

### 4.1 Inscription restaurant

#### 4.1.1 Processus automatisé
Un restaurant peut s'inscrire en envoyant "restaurant" au numéro WhatsApp Business. Le bot guide alors à travers 6 étapes :

1. **Nom du restaurant** : "Restaurant Chez Mamadou"
2. **Adresse complète** : "Kipé, près du rond-point, face école"
3. **Nom du responsable** : Contact principal
4. **Zones de livraison** : "Kipé, Ratoma, Matam"
5. **Temps de préparation** : "25" (minutes)
6. **Confirmation** : Récapitulatif et validation

#### 4.1.2 Validation administrative
Après inscription, l'administrateur reçoit une notification et peut :
```
valider 5    → Active le restaurant ID 5
refuser 5    → Rejette l'inscription
```

### 4.2 Gestion quotidienne

#### 4.2.1 Réception de commande type
```
🍽️ NOUVELLE COMMANDE #123

📱 Client : 224611223344
📍 Livraison : Chez Amadou, Kipé carrefour
💰 Total : 35,000 GNF

Articles :
• 2× Riz sauce arachide
• 1× Coca-Cola

💳 Paiement : orange_money

Actions : Répondez :
• accepter 123 - pour accepter
• refuser 123 - pour refuser
• temps 123 45 - modifier le temps (45min)
```

#### 4.2.2 Workflow recommandé
1. **Accepter** la commande rapidement
2. **Préparer** les plats selon qualité habituelle
3. **Notifier** quand prêt (pret 123)
4. **Coordonner** avec le livreur assigné

### 4.3 Optimisation des revenus

#### 4.3.3 Structure financière
- **Commission plateforme** : 15% du sous-total
- **Restaurants gardent** : 85% du montant des plats
- **Frais de livraison** : Entièrement pour livreurs (70%) et plateforme (30%)

#### 4.3.2 Exemple de revenus
```
Commande : 50,000 GNF de plats + 3,000 GNF livraison
Restaurant reçoit : 42,500 GNF (85% de 50,000)
Livreur reçoit : 2,100 GNF (70% de 3,000)
Plateforme : 7,500 + 900 = 8,400 GNF
```

---

## 5. APIs et intégrations {#apis-intégrations}

### 5.1 WhatsApp Business Cloud API

#### 5.1.1 Configuration
```python
WHATSAPP_TOKEN = "EAAxxxxxxxxxxxxxxx"
WHATSAPP_PHONE_ID = "123456789012345"
WHATSAPP_VERIFY_TOKEN = "webhook_secret_key"
```

#### 5.1.2 Endpoints utilisés
- `POST /v22.0/{phone_id}/messages` : Envoi de messages
- `GET /webhook` : Vérification webhook
- `POST /webhook` : Réception des messages

#### 5.1.3 Types de messages
- **Texte simple** : Messages de base
- **Templates** : Pour ouvrir fenêtre 24h
- **Interactifs** : Menus et boutons (futurs)

### 5.2 Intégrations mobile money

#### 5.2.1 Orange Money API
```python
# Configuration
ORANGE_MONEY_API_KEY = "votre_cle_api"
ORANGE_MONEY_API_SECRET = "votre_secret"
ORANGE_BASE_URL = "https://api.orange.com/orange-money-webpay/gn/v1"

# Flux de paiement
1. Authentification → Token d'accès
2. Initiation paiement → URL de paiement
3. Webhook confirmation → Mise à jour statut
```

#### 5.2.2 MTN Mobile Money
```python
# Configuration
MTN_MOMO_API_KEY = "votre_cle_subscription"
MTN_BASE_URL = "https://sandbox.momodeveloper.mtn.com"

# Note : Conversion GNF → EUR nécessaire
# 1 EUR ≈ 12,000 GNF (taux approximatif)
```

### 5.3 Google Maps API

#### 5.3.1 Services utilisés
- **Geocoding** : Conversion adresse → coordonnées
- **Distance Matrix** : Calcul distances de livraison
- **Places** : Validation des adresses

#### 5.3.2 Calcul des frais de livraison
```python
def calculate_delivery_fee(distance_km):
    if distance_km <= 2:
        return 2000  # GNF de base
    else:
        return 2000 + (distance_km - 2) * 500  # +500 GNF/km
```

---

## 6. Base de données {#base-de-données}

### 6.1 Schéma principal

#### 6.1.1 Table restaurants
```sql
CREATE TABLE restaurants (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    phone_number VARCHAR(20) UNIQUE,
    address TEXT,
    zone VARCHAR(100),
    latitude FLOAT,
    longitude FLOAT,
    is_active BOOLEAN DEFAULT true,
    commission_rate FLOAT DEFAULT 0.15,
    delivery_zones JSON,
    average_prep_time INTEGER DEFAULT 30,
    rating FLOAT DEFAULT 0.0,
    total_orders INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### 6.1.2 Table orders
```sql
CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(id),
    restaurant_id INTEGER REFERENCES restaurants(id),
    driver_id INTEGER REFERENCES delivery_drivers(id),
    status VARCHAR(50) DEFAULT 'pending',
    payment_status VARCHAR(50) DEFAULT 'pending',
    payment_method VARCHAR(50),
    payment_phone VARCHAR(20),
    items JSON,
    subtotal FLOAT,
    delivery_fee FLOAT,
    total_amount FLOAT,
    delivery_address TEXT,
    estimated_delivery_time INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    delivered_at TIMESTAMP
);
```

### 6.2 Index de performance

```sql
-- Index pour les requêtes fréquentes
CREATE INDEX idx_orders_restaurant_status ON orders(restaurant_id, status);
CREATE INDEX idx_orders_created_at ON orders(created_at DESC);
CREATE INDEX idx_restaurants_active_zone ON restaurants(is_active, zone);
CREATE INDEX idx_products_restaurant_available ON products(restaurant_id, available);
```

### 6.3 Sauvegarde et maintenance

#### 6.3.1 Stratégie de sauvegarde
- **Sauvegarde quotidienne** automatisée
- **Rétention** : 30 jours
- **Réplication** : Base secondaire pour lecture

#### 6.3.2 Maintenance recommandée
```sql
-- Nettoyage conversations anciennes (hebdomadaire)
DELETE FROM conversations WHERE last_interaction < NOW() - INTERVAL '7 days';

-- Réindexation (mensuelle)
REINDEX TABLE orders;
REINDEX TABLE restaurants;
```

---

## 7. Configuration et déploiement {#configuration}

### 7.1 Variables d'environnement

#### 7.1.1 Configuration production
```bash
# WhatsApp Business API
WHATSAPP_TOKEN=EAAxxxxxxxxxxxxxxx
WHATSAPP_PHONE_ID=123456789012345
WHATSAPP_VERIFY_TOKEN=webhook_secret_key

# Base de données
DATABASE_URL=postgresql://user:pass@host:5432/db

# Mobile Money
ORANGE_MONEY_API_KEY=your_orange_key
ORANGE_MONEY_API_SECRET=your_orange_secret
MTN_MOMO_API_KEY=your_mtn_key

# Google Maps
GOOGLE_MAPS_API_KEY=AIzaxxxxxxxxxxxxxxx

# Configuration app
ADMIN_PHONE=224611223344
BASE_DELIVERY_FEE=2000
FEE_PER_KM=500
ENVIRONMENT=production
PORT=8000
```

### 7.2 Déploiement Railway

#### 7.2.1 Configuration railway.json
```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": {
    "builder": "NIXPACKS"
  },
  "deploy": {
    "startCommand": "python main.py",
    "healthcheckPath": "/health",
    "healthcheckTimeout": 100,
    "restartPolicyType": "ON_FAILURE"
  }
}
```

#### 7.2.2 Processus de déploiement
1. **Push code** vers branche devops
2. **Railway auto-deploy** détecte les changements
3. **Build** avec requirements.txt
4. **Health check** sur /health
5. **Mise en service** automatique

### 7.3 Monitoring de santé

#### 7.3.1 Endpoint de santé
```python
@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "database": "connected",
        "restaurants": restaurant_count,
        "orders": order_count,
        "timestamp": datetime.utcnow().isoformat()
    }
```

#### 7.3.2 Métriques surveillées
- **Temps de réponse** API < 2s
- **Disponibilité** base de données
- **Taux d'erreur** WhatsApp < 5%
- **Nombre de commandes** par heure

---

## 8. Sécurité {#sécurité}

### 8.1 Authentification WhatsApp

#### 8.1.1 Vérification des webhooks
```python
def verify_webhook_signature(payload, signature):
    expected_signature = hmac.new(
        WEBHOOK_SECRET.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    return signature == f"sha256={expected_signature}"
```

#### 8.1.2 Rate limiting
```python
# Limitation par numéro de téléphone
rate_limiter = {
    "window": 60,  # 1 minute
    "max_requests": 10  # 10 messages max
}
```

### 8.2 Protection des données

#### 8.2.1 Chiffrement
- **Données en transit** : HTTPS/TLS 1.3
- **Données sensibles** : Chiffrement AES-256
- **Tokens API** : Variables d'environnement sécurisées

#### 8.2.2 Conformité RGPD
- **Anonymisation** des numéros de téléphone pour analytics
- **Droit à l'effacement** : Suppression sur demande
- **Export des données** : API dédiée

### 8.3 Validation des entrées

#### 8.3.1 Numéros de téléphone
```python
def validate_guinea_phone(phone):
    patterns = [
        r'^\+224([67]\d{8})$',  # +224611223344
        r'^224([67]\d{8})$',    # 224611223344
        r'^([67]\d{8})$'        # 611223344
    ]
    # Validation contre les patterns
```

#### 8.3.2 Sanitisation des données
- **Nettoyage SQL injection** via SQLAlchemy ORM
- **Validation JSON** avec Pydantic
- **Échappement XSS** pour les messages

---

## 9. Monitoring et maintenance {#monitoring}

### 9.1 Logs applicatifs

#### 9.1.1 Niveaux de log
```python
# Configuration logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Types de logs
logger.info("New order created", extra={"order_id": 123})
logger.warning("Payment failed", extra={"phone": "224611223344"})
logger.error("Database connection lost", exc_info=True)
```

#### 9.1.2 Métriques business
- **Commandes par heure** par zone
- **Temps de traitement** moyen par restaurant
- **Taux de conversion** visiteur → commande
- **Revenus** par restaurant et global

### 9.2 Alertes automatiques

#### 9.2.1 Seuils d'alerte
```python
ALERT_THRESHOLDS = {
    "response_time": 5.0,      # secondes
    "error_rate": 0.05,        # 5%
    "order_drop": 0.3,         # 30% de baisse
    "payment_failure": 0.1     # 10% d'échecs
}
```

#### 9.2.2 Notifications admin
```python
async def send_admin_alert(alert_type, details):
    message = f"🚨 ALERTE {alert_type.upper()}\n\n{details}"
    await whatsapp.send_message(ADMIN_PHONE, message)
```

### 9.3 Maintenance préventive

#### 9.3.1 Tâches automatisées
```bash
# Script de maintenance quotidienne
#!/bin/bash
# Nettoyage logs anciens
find /logs -name "*.log" -mtime +7 -delete

# Optimisation base de données
psql $DATABASE_URL -c "VACUUM ANALYZE orders;"

# Vérification santé API
curl -f $APP_URL/health || echo "Health check failed"
```

#### 9.3.2 Mise à jour du système
1. **Tests** en environnement de staging
2. **Déploiement** pendant les heures creuses
3. **Monitoring** accru post-déploiement
4. **Rollback** automatique si erreurs

---

## 10. Support et dépannage {#support}

### 10.1 Problèmes fréquents

#### 10.1.1 Restaurant ne reçoit pas les commandes
**Diagnostic :**
```bash
# Vérifier le statut du restaurant
curl $APP_URL/api/restaurants/123

# Tester l'envoi de message
curl -X POST $APP_URL/test/send-message \
  -d '{"phone": "224611223344", "message": "Test"}'
```

**Solutions :**
- Vérifier que `is_active = true`
- Confirmer le numéro de téléphone
- Tester le token WhatsApp

#### 10.1.2 Paiements échouent
**Diagnostic :**
```python
# Vérifier les logs de paiement
grep "payment.*error" /logs/app.log

# Tester les APIs mobile money
curl -H "Authorization: Bearer $TOKEN" \
  $ORANGE_MONEY_URL/token
```

**Solutions :**
- Renouveler les tokens API
- Vérifier les soldes marchands
- Contacter le support mobile money

#### 10.1.3 Commandes perdues
**Diagnostic :**
```sql
-- Vérifier les commandes sans statut
SELECT * FROM orders 
WHERE status = 'pending' 
AND created_at < NOW() - INTERVAL '1 hour';
```

**Solutions :**
- Relancer les notifications restaurant
- Vérifier les webhooks WhatsApp
- Investiguer les logs d'erreur

### 10.2 Commandes d'administration

#### 10.2.1 Gestion des restaurants
```
# Messages admin vers le bot
valider 123        → Active le restaurant ID 123
refuser 123        → Désactive le restaurant ID 123
stats              → Statistiques globales
restaurants actifs → Liste des restaurants actifs
```

#### 10.2.2 Gestion des commandes
```sql
-- Forcer le statut d'une commande
UPDATE orders SET status = 'delivered' WHERE id = 123;

-- Rembourser une commande
UPDATE orders SET payment_status = 'refunded' WHERE id = 123;
```

### 10.3 Escalade de support

#### 10.3.1 Niveaux de support
1. **Niveau 1** : FAQ et problèmes courants
2. **Niveau 2** : Diagnostic technique avancé
3. **Niveau 3** : Développement et architecture

#### 10.3.2 Contacts d'urgence
- **Administrateur système** : +224611223344
- **Support technique** : Disponible via WhatsApp
- **Escalade critique** : Email + SMS automatique

---

## Annexes

### A. Codes d'erreur

| Code | Description | Action |
|------|-------------|--------|
| WA001 | Webhook signature invalide | Vérifier WEBHOOK_SECRET |
| DB001 | Connexion base de données échouée | Redémarrer service |
| PM001 | Paiement mobile money échoué | Contacter provider |
| GEO001 | Géolocalisation impossible | Utiliser adresse manuelle |

### B. Changelog

**Version 1.0.0** (Décembre 2024)
- Implémentation initiale
- Support multi-restaurants
- Intégration mobile money
- Système de livraison

**Version 1.1.0** (À venir)
- Dashboard web restaurants
- Analytics avancées
- API publique

### C. Contact et support

**Équipe technique** : support@conakryfoodconnect.com
**Documentation** : docs.conakryfoodconnect.com
**Status page** : status.conakryfoodconnect.com

---

*Document généré automatiquement - Version 1.0*
*Dernière mise à jour : Décembre 2024*
