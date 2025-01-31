import asyncio
import logging
from datetime import datetime, timedelta, time
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

class Scheduler:
    def __init__(self, bot, database, wg_api, job_queue):
        self.bot = bot
        self.db = database
        self.wg_api = wg_api
        self.job_queue = job_queue
        self.notification_days = [7, 3, 1]  # За сколько дней уведомлять
        self.notification_sent = {}  # Для отслеживания отправленных уведомлений
        self.last_check = None

    def start(self):
        """Запуск планировщика"""
        logging.info("Starting scheduler...")
        
        # Проверка подписок каждый час
        self.job_queue.run_repeating(
            self.check_subscriptions,
            interval=3600,  # каждый час
            first=0  # запустить сразу
        )
        logging.info("Scheduled hourly subscription check")
        
        logging.info("Scheduler started successfully")

    async def check_subscriptions(self, context):
        """Проверка подписок и отправка уведомлений"""
        current_time = datetime.now()
        
        # Пропускаем проверку если прошло меньше часа с последней проверки
        if self.last_check and (current_time - self.last_check).total_seconds() < 3600:
            logging.info("Пропускаем проверку - прошло меньше часа с последней проверки")
            return
            
        self.last_check = current_time
        logging.info(f"=== Новый цикл проверки подписок: {current_time} ===")
        
        try:
            # Сначала проверяем истекшие подписки
            expired_subscriptions = self.db.get_expired_subscriptions()
            logging.info(f"Checking expired subscriptions: {expired_subscriptions}")
            
            if expired_subscriptions:
                for sub in expired_subscriptions:
                    try:
                        user_id = sub.get('user_id')
                        config_name = sub.get('config_name')
                        is_active = sub.get('is_active')
                        subscription_id = sub.get('id')
                        
                        if not all([user_id, config_name, is_active is not None, subscription_id]):
                            logging.error(f"Missing required fields in subscription: {sub}")
                            continue
                            
                        logging.info(f"Processing expired subscription: user_id={user_id}, config_name={config_name}, is_active={is_active}")
                        
                        # Проверяем, не отправляли ли уже уведомление об истечении
                        notification_key = f"expired_{subscription_id}"
                        if notification_key not in self.notification_sent and is_active == 1:
                            # Отключаем пользователя
                            if await self.wg_api.disable_client(config_name):
                                logging.info(f"Disabled client {config_name}")
                                
                                # Отправляем уведомление об истечении
                                await self.bot.send_message(
                                    chat_id=user_id,
                                    text="❌ Ваша подписка VPN истекла!\n\n"
                                         "Для продолжения использования сервиса необходимо продлить подписку."
                                )
                                
                                # Отмечаем что уведомление отправлено
                                self.notification_sent[notification_key] = True
                                logging.info(f"Sent expiration notification to user {user_id}")
                                
                                # Деактивируем подписку в базе
                                self.db.deactivate_subscription(user_id)
                                logging.info(f"Deactivated subscription for user {user_id}")
                    
                    except Exception as e:
                        logging.error(f"Error processing expired subscription for user {user_id if 'user_id' in locals() else 'unknown'}: {e}")
                        continue
            
            # Затем проверяем активные подписки на скорое истечение
            active_subscriptions = self.db.get_active_subscriptions()
            logging.info(f"Found {len(active_subscriptions)} active subscriptions")
            
            for sub in active_subscriptions:
                try:
                    user_id = sub.get('user_id')
                    expiration = sub.get('expiration')
                    subscription_id = sub.get('id')
                    
                    if not all([user_id, expiration, subscription_id]):
                        logging.error(f"Missing required fields in active subscription: {sub}")
                        continue
                    
                    # Обрезаем микросекунды и преобразуем в datetime
                    expiration = datetime.strptime(str(expiration).split('.')[0], '%Y-%m-%d %H:%M:%S')
                    time_left = expiration - current_time
                    hours_left = time_left.total_seconds() / 3600
                    
                    # Проверяем, находится ли время до истечения в диапазоне 23-24 часов
                    # и не было ли уже отправлено уведомление
                    notification_key = f"24h_warning_{subscription_id}"
                    if 23 <= hours_left <= 24 and notification_key not in self.notification_sent:
                        await self.send_warning(user_id)
                        self.notification_sent[notification_key] = True
                        logging.info(f"Sent 24h warning to user {user_id}")
                
                except Exception as e:
                    logging.error(f"Error processing active subscription for user {user_id if 'user_id' in locals() else 'unknown'}: {e}")
                    continue
                    
        except Exception as e:
            logging.error(f"Error in check_subscriptions: {e}")

    async def send_warning(self, user_id: int):
        """Отправка предупреждения пользователю"""
        try:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Продлить подписку", callback_data="extend_subscription")]
            ])
            
            await self.bot.send_message(
                chat_id=user_id,
                text="⚠️ Внимание! Ваша подписка VPN истекает через 24 часа!\n\n"
                     "Рекомендуем продлить подписку заранее, чтобы избежать отключения.",
                reply_markup=keyboard
            )
            
            logging.info(f"Sent warning to user {user_id}")
            
        except Exception as e:
            logging.error(f"Error sending warning to user {user_id}: {e}")
