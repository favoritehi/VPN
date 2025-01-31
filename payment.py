import os
import json
import uuid
import logging
import requests
from datetime import datetime

class YooMoneyAPI:
    def __init__(self):
        self.shop_id = os.getenv('YOOMONEY_SHOP_ID')
        self.secret_key = os.getenv('YOOMONEY_SECRET_KEY')
        self.api_url = "https://api.yookassa.ru/v3"
        self.return_url = os.getenv('PAYMENT_RETURN_URL')

    def create_payment(self, amount, description, user_id):
        """Создать платеж"""
        headers = {
            "Idempotence-Key": str(uuid.uuid4()),
            "Content-Type": "application/json"
        }
        
        auth = (self.shop_id, self.secret_key)
        
        data = {
            "amount": {
                "value": str(amount),
                "currency": "RUB"
            },
            "capture": True,
            "confirmation": {
                "type": "redirect",
                "return_url": self.return_url
            },
            "description": description,
            "metadata": {
                "user_id": user_id
            }
        }
        
        try:
            response = requests.post(
                f"{self.api_url}/payments",
                json=data,
                auth=auth,
                headers=headers
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logging.error(f"Payment creation failed: {response.text}")
                return None
                
        except Exception as e:
            logging.error(f"Payment error: {e}")
            return None

    def check_payment(self, payment_id):
        """Проверить статус платежа"""
        auth = (self.shop_id, self.secret_key)
        
        try:
            response = requests.get(
                f"{self.api_url}/payments/{payment_id}",
                auth=auth
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logging.error(f"Payment check failed: {response.text}")
                return None
                
        except Exception as e:
            logging.error(f"Payment check error: {e}")
            return None

class PaymentManager:
    def __init__(self, database):
        self.db = database
        self.payment_api = YooMoneyAPI()
        
        # Цены на подписки (в рублях)
        self.prices = {
            '1_month': 200,
            '3_months': 500,
            '6_months': 900,
            '1_year': 1500
        }

    async def create_payment(self, user_id, plan):
        """Создать платеж для подписки"""
        amount = self.prices.get(plan)
        if not amount:
            return None, "Invalid plan selected"

        description = f"VPN subscription: {plan}"
        payment = self.payment_api.create_payment(amount, description, user_id)
        
        if payment:
            # Сохраняем информацию о платеже
            self.db.add_transaction(
                user_id=user_id,
                amount=amount,
                type_='payment',
                status='pending',
                payment_data=payment
            )
            
            return payment.get('confirmation', {}).get('confirmation_url'), None
        
        return None, "Failed to create payment"

    async def check_payment(self, payment_id):
        """Проверить статус платежа"""
        payment = self.payment_api.check_payment(payment_id)
        
        if payment and payment.get('status') == 'succeeded':
            # Обновляем статус транзакции
            user_id = payment.get('metadata', {}).get('user_id')
            amount = float(payment.get('amount', {}).get('value', 0))
            
            self.db.add_transaction(
                user_id=user_id,
                amount=amount,
                type_='payment',
                status='completed',
                payment_data=payment
            )
            
            return True
            
        return False
