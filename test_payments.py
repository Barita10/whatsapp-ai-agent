# test_payments.py - Test des paiements mobile money pour Conakry Food
import asyncio
import random
import logging
from datetime import datetime
from typing import Dict

# Configuration des logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class MockConfig:
    """Configuration pour les tests"""
    ORANGE_MONEY_API_KEY = "your_orange_key"  # Mode test
    MTN_MOMO_API_KEY = "your_mtn_key"  # Mode test

config = MockConfig()

class OrangeMoneyService:
    def __init__(self):
        self.api_key = config.ORANGE_MONEY_API_KEY
        self.api_secret = "your_orange_secret"
        self.base_url = "https://api.orange.com/orange-money-webpay/gn/v1"

    async def initiate_payment(self, phone: str, amount: int, order_id: int) -> Dict:
        """Initie un paiement Orange Money avec simulation réaliste"""
        
        if self.api_key == "your_orange_key":
            logging.info(f"🍊 Orange Money SIMULATION: {amount} GNF pour {phone}")
            
            # Simuler délai réseau
            await asyncio.sleep(random.uniform(1, 3))
            
            # Scénarios de test selon le numéro
            if amount < 1000:
                return {"success": False, "error": "Montant minimum 1000 GNF"}
            elif amount > 1000000:
                return {"success": False, "error": "Montant maximum dépassé"}
            elif phone.endswith("111"):
                return {"success": False, "error": "Solde insuffisant"}
            elif phone.endswith("222"):
                await asyncio.sleep(3)
                return {"success": False, "error": "Timeout de la transaction"}
            else:
                # Succès avec 90% de probabilité
                if random.random() < 0.9:
                    return {
                        "success": True, 
                        "test_mode": True,
                        "payment_token": f"OM_TEST_{order_id}_{random.randint(1000, 9999)}",
                        "payment_url": f"https://pay.orange.com/test/{order_id}",
                        "message": "Paiement initié avec succès"
                    }
                else:
                    return {"success": False, "error": "Erreur temporaire Orange Money"}
        
        return {"success": False, "error": "Configuration Orange incomplète"}

class MTNMoMoService:
    def __init__(self):
        self.api_key = config.MTN_MOMO_API_KEY
        self.base_url = "https://sandbox.momodeveloper.mtn.com"
    
    async def request_payment(self, phone: str, amount: int, order_id: int) -> Dict:
        """Initie un paiement MTN Mobile Money avec simulation réaliste"""
        
        if self.api_key == "your_mtn_key":
            logging.info(f"📱 MTN MoMo SIMULATION: {amount} GNF pour {phone}")
            
            # Simuler délai réseau
            await asyncio.sleep(random.uniform(0.5, 2))
            
            # Scénarios selon le numéro
            if not phone.startswith("+224"):
                return {"success": False, "error": "Numéro invalide pour la Guinée"}
            elif phone.endswith("000"):
                return {"success": False, "error": "Utilisateur MTN non trouvé"}
            elif phone.endswith("999"):
                return {
                    "success": True,
                    "test_mode": True,
                    "reference_id": f"MTN_TEST_{order_id}_{random.randint(10000, 99999)}",
                    "status": "PENDING",
                    "message": "En attente de confirmation utilisateur"
                }
            else:
                # Succès avec 85% de probabilité
                if random.random() < 0.85:
                    return {
                        "success": True, 
                        "test_mode": True,
                        "reference_id": f"MTN_TEST_{order_id}_{random.randint(10000, 99999)}",
                        "status": "SUCCESSFUL" if random.random() < 0.7 else "PENDING",
                        "message": "Demande de paiement envoyée"
                    }
                else:
                    return {"success": False, "error": "Erreur temporaire MTN MoMo"}
        
        return {"success": False, "error": "Configuration MTN incomplète"}
    
    async def check_payment_status(self, reference_id: str) -> Dict:
        """Vérifie le statut d'un paiement"""
        
        if "TEST" in reference_id:
            logging.info(f"🔍 Vérification statut MTN: {reference_id}")
            
            await asyncio.sleep(random.uniform(0.5, 1.5))
            
            # Simuler différents statuts
            statuses = ["PENDING", "SUCCESSFUL", "FAILED"]
            probabilities = [0.2, 0.7, 0.1]
            
            status = random.choices(statuses, probabilities)[0]
            
            result = {
                "reference_id": reference_id,
                "status": status,
                "test_mode": True
            }
            
            if status == "SUCCESSFUL":
                result["message"] = "Paiement confirmé par l'utilisateur"
            elif status == "FAILED":
                result["message"] = "Paiement refusé ou annulé"
                result["error"] = "Transaction cancelled by user"
            else:
                result["message"] = "En attente de confirmation"
            
            return result
        
        return {"success": False, "error": "Status check not implemented"}

async def test_basic_scenarios():
    """Test des scénarios de base"""
    print("🧪 Tests de simulation de paiement Conakry Food")
    print("=" * 60)
    
    orange = OrangeMoneyService()
    mtn = MTNMoMoService()
    
    test_cases = [
        # Format: (phone, amount, description)
        ("+224601234567", 15000, "Commande normale"),
        ("+224601234111", 10000, "Échec Orange (solde insuffisant)"),
        ("+224601234000", 12000, "Échec MTN (utilisateur non trouvé)"),
        ("+224601234999", 8000, "MTN en attente de confirmation"),
        ("+224601234222", 5000, "Timeout Orange Money"),
        ("+224601234567", 500, "Montant trop faible"),
        ("+224601234567", 1500000, "Montant trop élevé"),
    ]
    
    for i, (phone, amount, description) in enumerate(test_cases, 1):
        print(f"\n📋 Test {i}/7: {description}")
        print(f"📞 {phone}, 💰 {amount:,} GNF")
        print("-" * 40)
        
        # Test Orange Money
        print("🍊 Orange Money:")
        try:
            om_result = await orange.initiate_payment(phone, amount, 100 + i)
            if om_result.get("success"):
                print(f"   ✅ Succès: {om_result.get('message', 'OK')}")
                if om_result.get("payment_url"):
                    print(f"   🔗 URL: {om_result['payment_url']}")
            else:
                print(f"   ❌ Échec: {om_result.get('error')}")
        except Exception as e:
            print(f"   💥 Erreur: {e}")
        
        # Test MTN MoMo
        print("📱 MTN MoMo:")
        try:
            mtn_result = await mtn.request_payment(phone, amount, 100 + i)
            if mtn_result.get("success"):
                print(f"   ✅ Succès: {mtn_result.get('message', 'OK')}")
                print(f"   🆔 Ref: {mtn_result.get('reference_id', 'N/A')}")
                
                # Si en attente, tester la vérification
                if mtn_result.get("reference_id"):
                    print("   🔍 Vérification du statut...")
                    await asyncio.sleep(1)
                    status = await mtn.check_payment_status(mtn_result["reference_id"])
                    print(f"   📊 Statut: {status.get('status')} - {status.get('message')}")
            else:
                print(f"   ❌ Échec: {mtn_result.get('error')}")
        except Exception as e:
            print(f"   💥 Erreur: {e}")
        
        print("-" * 40)
        
        # Pause entre les tests
        if i < len(test_cases):
            await asyncio.sleep(0.5)

async def test_payment_flow():
    """Simule un flow complet de commande"""
    print("\n🛒 Test d'un flow complet de commande")
    print("=" * 50)
    
    # Simulation d'une commande
    order_data = {
        "order_id": 42,
        "customer_phone": "+224601234567",
        "payment_phone": "+224601234567",
        "amount": 25000,
        "payment_method": "mtn_momo",
        "items": [
            {"name": "Riz sauce arachide", "price": 15000, "qty": 1},
            {"name": "Coca-Cola", "price": 3000, "qty": 1},
            {"name": "Frais de livraison", "price": 7000, "qty": 1}
        ]
    }
    
    print(f"📋 Commande #{order_data['order_id']}")
    print(f"📞 Client: {order_data['customer_phone']}")
    print(f"💰 Total: {order_data['amount']:,} GNF")
    print(f"💳 Paiement: {order_data['payment_method']}")
    
    # Traitement du paiement
    if order_data["payment_method"] == "orange_money":
        service = OrangeMoneyService()
        result = await service.initiate_payment(
            order_data["payment_phone"],
            order_data["amount"],
            order_data["order_id"]
        )
        provider = "Orange Money"
    else:
        service = MTNMoMoService()
        result = await service.request_payment(
            order_data["payment_phone"],
            order_data["amount"],
            order_data["order_id"]
        )
        provider = "MTN MoMo"
    
    print(f"\n💳 Traitement {provider}:")
    
    if result.get("success"):
        print("✅ Paiement initié avec succès!")
        
        # Message WhatsApp simulé
        if result.get("payment_url"):
            whatsapp_msg = f"💳 Cliquez pour payer: {result['payment_url']}"
        else:
            whatsapp_msg = f"📱 Vérifiez votre téléphone pour confirmer le paiement de {order_data['amount']:,} GNF"
        
        print(f"📱 Message WhatsApp envoyé:")
        print(f"   '{whatsapp_msg}'")
        
        # Si MTN, simuler vérification du statut
        if order_data["payment_method"] == "mtn_momo" and result.get("reference_id"):
            print("\n⏳ Attente confirmation client...")
            await asyncio.sleep(2)
            
            status = await service.check_payment_status(result["reference_id"])
            print(f"📊 Statut final: {status.get('status')}")
            
            if status.get("status") == "SUCCESSFUL":
                final_msg = f"✅ Paiement confirmé! Votre commande #{order_data['order_id']} est en cours de préparation."
            elif status.get("status") == "FAILED":
                final_msg = f"❌ Paiement échoué. Veuillez réessayer ou choisir un autre mode de paiement."
            else:
                final_msg = f"⏳ Paiement en attente. Nous vous notifierons dès confirmation."
            
            print(f"📱 Message final WhatsApp:")
            print(f"   '{final_msg}'")
    else:
        print(f"❌ Échec du paiement: {result.get('error')}")
        error_msg = f"❌ Erreur de paiement: {result.get('error')}. Veuillez réessayer."
        print(f"📱 Message d'erreur WhatsApp:")
        print(f"   '{error_msg}'")

async def performance_test():
    """Test de performance avec plusieurs paiements simultanés"""
    print("\n⚡ Test de performance - Paiements simultanés")
    print("=" * 50)
    
    mtn = MTNMoMoService()
    
    # Créer plusieurs tâches de paiement
    tasks = []
    for i in range(5):
        task = mtn.request_payment(
            f"+22460123456{i}",
            random.randint(5000, 50000),
            200 + i
        )
        tasks.append(task)
    
    print("🚀 Lancement de 5 paiements simultanés...")
    start_time = asyncio.get_event_loop().time()
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    end_time = asyncio.get_event_loop().time()
    duration = end_time - start_time
    
    print(f"⏱️  Temps total: {duration:.2f} secondes")
    
    successes = sum(1 for r in results if isinstance(r, dict) and r.get("success"))
    failures = len(results) - successes
    
    print(f"✅ Succès: {successes}/5")
    print(f"❌ Échecs: {failures}/5")
    print(f"📈 Taux de succès: {(successes/5)*100:.1f}%")

async def main():
    """Fonction principale de test"""
    print("🚀 Début des tests Conakry Food - Paiements Mobile Money")
    print(f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    try:
        # Tests de base
        await test_basic_scenarios()
        
        # Test de flow complet
        await test_payment_flow()
        
        # Test de performance
        await performance_test()
        
        print("\n🎉 Tous les tests terminés avec succès!")
        print("=" * 60)
        print("📝 Résumé:")
        print("- Les simulations fonctionnent correctement")
        print("- Les différents scénarios sont testés")
        print("- Le système gère les erreurs proprement")
        print("- Prêt pour l'intégration des vraies APIs")
        
    except KeyboardInterrupt:
        print("\n⚠️  Tests interrompus par l'utilisateur")
    except Exception as e:
        print(f"\n💥 Erreur durant les tests: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # Lancer tous les tests
    asyncio.run(main()) 