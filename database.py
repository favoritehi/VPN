import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict

class Database:
    def __init__(self, db_file):
        """Инициализация соединения с БД"""
        self.db_file = db_file
        self.conn = sqlite3.connect(db_file)
        self.create_tables()

    def create_tables(self):
        """Создание необходимых таблиц"""
        cursor = self.conn.cursor()
        
        try:
            logging.info("Checking database structure...")
            
            # Проверяем существование таблиц
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            existing_tables = [table[0] for table in cursor.fetchall()]
            logging.info(f"Existing tables: {existing_tables}")
            
            # Создаем таблицу пользователей если её нет
            if 'users' not in existing_tables:
                cursor.execute('''
                CREATE TABLE users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                ''')
                logging.info("Created users table")

            # Пересоздаем таблицу подписок
            cursor.execute("DROP TABLE IF EXISTS subscriptions")
            cursor.execute('''
            CREATE TABLE subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                expiration TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
            ''')
            logging.info("Recreated subscriptions table with new structure")

            # Пересоздаем таблицу платежей
            cursor.execute("DROP TABLE IF EXISTS payments")
            cursor.execute('''
            CREATE TABLE payments (
                payment_id TEXT PRIMARY KEY,
                user_id INTEGER,
                amount REAL,
                duration_months INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
            ''')
            logging.info("Recreated payments table with new structure")

            # Пересоздаем таблицу конфигураций
            cursor.execute("DROP TABLE IF EXISTS client_configs")
            cursor.execute('''
            CREATE TABLE client_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE,
                private_key TEXT,
                public_key TEXT,
                pre_shared_key TEXT,
                config_path TEXT,
                qr_path TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
            ''')
            logging.info("Recreated client_configs table with new structure")

            # Создаем таблицу уведомлений если её нет
            if 'notifications' not in existing_tables:
                cursor.execute('''
                CREATE TABLE notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    subscription_id INTEGER,
                    notification_type TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id),
                    FOREIGN KEY (subscription_id) REFERENCES subscriptions(id)
                )
                ''')
                logging.info("Created notifications table")

            # Создаем индексы
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_subscriptions_user_active ON subscriptions(user_id, is_active)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id)')

            self.conn.commit()
            logging.info("Database structure check completed")
        except Exception as e:
            self.conn.rollback()
            logging.error(f"Error checking/creating database structure: {e}")
            raise
        finally:
            cursor.close()

    def add_user(self, user_id, username=None):
        """Добавление нового пользователя"""
        cursor = self.conn.cursor()
        cursor.execute('''
        INSERT OR REPLACE INTO users (user_id, username)
        VALUES (?, ?)
        ''', (user_id, username))
        self.conn.commit()

    def get_user(self, user_id):
        """Получение информации о пользователе"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        return cursor.fetchone()

    def create_payment(self, user_id, amount, status, duration_months=None, payment_method=None, screenshot_file_id=None):
        """Создание нового платежа"""
        cursor = self.conn.cursor()
        cursor.execute('''
        INSERT INTO payments (payment_id, user_id, amount, duration_months, status, created_at)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (str(user_id), user_id, amount, duration_months, status))
        self.conn.commit()
        return cursor.lastrowid

    def verify_payment(self, payment_id, status):
        """Подтверждение или отклонение платежа"""
        cursor = self.conn.cursor()
        cursor.execute('''
        UPDATE payments 
        SET status = ?
        WHERE payment_id = ?
        ''', (status, payment_id))
        self.conn.commit()

    def get_payment(self, payment_id):
        """Получение информации о платеже"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM payments WHERE payment_id = ?', (payment_id,))
        return cursor.fetchone()

    def get_user_payments(self, user_id):
        """Получение всех платежей пользователя"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM payments WHERE user_id = ? ORDER BY created_at DESC', (user_id,))
        return cursor.fetchall()

    def add_subscription(self, user_id, duration_days):
        """Добавление новой подписки или продление существующей"""
        cursor = self.conn.cursor()
        now = datetime.now().replace(microsecond=0)
        logging.info(f"Adding subscription for user {user_id} at {now}, duration: {duration_days} days")
        
        # Проверяем, есть ли активная подписка
        cursor.execute("""
            SELECT expiration, id
            FROM subscriptions 
            WHERE user_id = ? AND is_active = 1
            ORDER BY expiration DESC LIMIT 1
        """, (user_id,))
        current_subscription = cursor.fetchone()
        
        if current_subscription:
            current_expiration = datetime.strptime(str(current_subscription[0]).split('.')[0], '%Y-%m-%d %H:%M:%S')
            logging.info(f"Found existing subscription for user {user_id}, expires at {current_expiration}")
            
            # Если подписка ещё активна, добавляем дни к текущей дате окончания
            if current_expiration > now:
                end_date = current_expiration + timedelta(days=duration_days)
                logging.info(f"Extending active subscription to {end_date}")
            else:
                # Если подписка истекла, начинаем с текущей даты
                end_date = now + timedelta(days=duration_days)
                logging.info(f"Starting new subscription period from now until {end_date}")
            
            # Обновляем существующую подписку
            cursor.execute("""
                UPDATE subscriptions 
                SET expiration = ?, is_active = 1
                WHERE user_id = ? AND is_active = 1
            """, (end_date, user_id))
            logging.info(f"Updated subscription for user {user_id}")
        else:
            # Создаем новую подписку
            end_date = now + timedelta(days=duration_days)
            logging.info(f"Creating new subscription for user {user_id} until {end_date}")
            
            cursor.execute("""
                INSERT INTO subscriptions (user_id, expiration, created_at)
                VALUES (?, ?, ?)
            """, (user_id, end_date, now))
            logging.info(f"Created new subscription for user {user_id}")
        
        self.conn.commit()
        return True

    def get_subscription(self, user_id):
        """Получение информации о текущей подписке пользователя"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT 
                id,
                user_id,
                expiration,
                created_at,
                is_active
            FROM subscriptions 
            WHERE user_id = ? AND is_active = 1
            ORDER BY created_at DESC LIMIT 1
        ''', (user_id,))
        subscription = cursor.fetchone()
        if subscription:
            return {
                'id': subscription[0],
                'user_id': subscription[1],
                'expiration': subscription[2],
                'created_at': subscription[3],
                'is_active': subscription[4]
            }
        return None

    def check_subscription(self, user_id):
        """Проверка активности подписки"""
        subscription = self.get_subscription(user_id)
        if not subscription:
            return False
        try:
            # Обрезаем микросекунды перед парсингом
            end_date_str = subscription['expiration'].split('.')[0]
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d %H:%M:%S')
            return end_date > datetime.now()
        except Exception as e:
            logging.error(f"Error checking subscription: {e}")
            return False

    def get_subscription_end_date(self, user_id):
        """Получение даты окончания подписки"""
        subscription = self.get_subscription(user_id)
        if not subscription:
            return None
        try:
            # Обрезаем микросекунды перед парсингом
            end_date_str = subscription['expiration'].split('.')[0]
            return datetime.strptime(end_date_str, '%Y-%m-%d %H:%M:%S')
        except Exception as e:
            logging.error(f"Error getting subscription end date: {e}")
            return None

    def get_expired_subscriptions(self):
        """Получение истекших подписок"""
        cursor = self.conn.cursor()
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        logging.info(f"Checking for expired subscriptions at {now}")
        
        query = '''
            SELECT 
                id,
                user_id,
                expiration,
                created_at,
                is_active
            FROM subscriptions 
            WHERE expiration <= ? AND is_active = 1
            ORDER BY expiration DESC
        '''
        
        cursor.execute(query, (now,))
        
        raw_subscriptions = cursor.fetchall()
        if raw_subscriptions:
            logging.info(f"Raw expired subscriptions data: {raw_subscriptions}")
        else:
            logging.info("No expired subscriptions found")
            return []
            
        result = []
        for sub in raw_subscriptions:
            try:
                subscription_dict = {
                    'id': sub[0],
                    'user_id': sub[1],
                    'expiration': sub[2],
                    'created_at': sub[3],
                    'is_active': sub[4]
                }
                result.append(subscription_dict)
                logging.info(f"Processed expired subscription: {subscription_dict}")
            except Exception as e:
                logging.error(f"Error processing expired subscription row {sub}: {e}")
                continue
        
        logging.info(f"Total expired subscriptions found: {len(result)}")
        return result

    def deactivate_subscription(self, user_id: int) -> bool:
        """Деактивация подписки пользователя"""
        try:
            with self.conn:
                cursor = self.conn.cursor()
                # Обновляем статус подписки
                cursor.execute(
                    """
                    UPDATE subscriptions 
                    SET is_active = 0 
                    WHERE user_id = ? AND is_active = 1
                    """,
                    (user_id,)
                )
                self.conn.commit()
                logging.info(f"Successfully deactivated subscription for user {user_id}")
                return True
        except Exception as e:
            logging.error(f"Error deactivating subscription for user {user_id}: {e}")
            return False

    def add_payment(self, payment_id: str, user_id: int, amount: float, duration: int, status: str = 'pending'):
        """Добавление нового платежа"""
        cursor = self.conn.cursor()
        try:
            cursor.execute('''
            INSERT INTO payments (payment_id, user_id, amount, duration_months, status, created_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (payment_id, user_id, amount, duration, status))
            self.conn.commit()
            logging.info(f"Added new payment: ID={payment_id}, user_id={user_id}, amount={amount}, duration={duration}")
            return True
        except Exception as e:
            logging.error(f"Error adding payment: {e}")
            self.conn.rollback()
            return False

    def get_payment(self, payment_id: str):
        """Получение информации о платеже"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT payment_id, user_id, amount, duration_months, status, created_at
            FROM payments
            WHERE payment_id = ?
        """, (payment_id,))
        return cursor.fetchone()

    def update_payment_status(self, payment_id: str, status: str):
        """Обновление статуса платежа"""
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                UPDATE payments
                SET status = ?
                WHERE payment_id = ?
            """, (status, payment_id))
            self.conn.commit()
            logging.info(f"Updated payment {payment_id} status to {status}")
        except Exception as e:
            logging.error(f"Error updating payment status: {e}")
            self.conn.rollback()
            raise

    def create_subscription(self, user_id: int, expiration: str):
        """Создание новой подписки"""
        cursor = self.conn.cursor()
        try:
            # Деактивируем все текущие подписки пользователя
            cursor.execute("""
                UPDATE subscriptions 
                SET is_active = 0 
                WHERE user_id = ? AND is_active = 1
            """, (user_id,))
            
            # Создаем новую подписку
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute("""
                INSERT INTO subscriptions 
                (user_id, expiration, created_at, is_active) 
                VALUES (?, ?, ?, 1)
            """, (user_id, expiration, now))
            
            self.conn.commit()
            logging.info(f"Created new subscription for user {user_id} until {expiration}")
            return True
        except Exception as e:
            logging.error(f"Error creating subscription: {e}")
            self.conn.rollback()
            return False

    def get_active_subscriptions(self):
        """Получение активных подписок"""
        cursor = self.conn.cursor()
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute('''
            SELECT 
                id,
                user_id,
                expiration,
                created_at,
                is_active
            FROM subscriptions 
            WHERE is_active = 1 AND expiration > ?
            ORDER BY expiration DESC
        ''', (now,))
        
        result = []
        for sub in cursor.fetchall():
            try:
                subscription_dict = {
                    'id': sub[0],
                    'user_id': sub[1],
                    'expiration': sub[2],
                    'created_at': sub[3],
                    'is_active': sub[4]
                }
                result.append(subscription_dict)
                logging.info(f"Processed active subscription: {subscription_dict}")
            except Exception as e:
                logging.error(f"Error processing active subscription row {sub}: {e}")
                continue
        
        logging.info(f"Total active subscriptions found: {len(result)}")
        return result

    def save_client_config(self, user_id: int, client_data: Dict[str, str]):
        """Сохранение конфигурации клиента"""
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO client_configs 
                (user_id, private_key, public_key, pre_shared_key, config_path, qr_path)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                client_data.get('private_key'),
                client_data.get('public_key'),
                client_data.get('pre_shared_key'),
                client_data.get('config_path'),
                client_data.get('qr_path')
            ))
            self.conn.commit()
            logging.info(f"Saved client config for user {user_id}")
        except Exception as e:
            self.conn.rollback()
            logging.error(f"Error saving client config: {e}")
            raise
        finally:
            cursor.close()

    def get_client_config(self, user_id: int) -> Optional[Dict[str, str]]:
        """Получение конфигурации клиента"""
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                SELECT private_key, public_key, pre_shared_key, config_path, qr_path
                FROM client_configs
                WHERE user_id = ?
            """, (user_id,))
            row = cursor.fetchone()
            if row:
                return {
                    'private_key': row[0],
                    'public_key': row[1],
                    'pre_shared_key': row[2],
                    'config_path': row[3],
                    'qr_path': row[4]
                }
            return None
        except Exception as e:
            logging.error(f"Error getting client config: {e}")
            raise
        finally:
            cursor.close()

    def clear_all_data(self):
        """Очистка всех данных из базы"""
        cursor = self.conn.cursor()
        try:
            # Отключаем внешние ключи
            cursor.execute("PRAGMA foreign_keys = OFF")
            
            # Удаляем данные из всех таблиц
            cursor.execute("DELETE FROM subscriptions")
            cursor.execute("DELETE FROM payments")
            cursor.execute("DELETE FROM client_configs")
            cursor.execute("DELETE FROM users")
            
            # Сбрасываем автоинкремент
            cursor.execute("DELETE FROM sqlite_sequence")
            
            # Включаем внешние ключи обратно
            cursor.execute("PRAGMA foreign_keys = ON")
            
            self.conn.commit()
            logging.info("All data cleared successfully")
        except Exception as e:
            logging.error(f"Error clearing data: {e}")
            self.conn.rollback()
            raise

    def close(self):
        """Закрытие соединения с базой данных"""
        self.conn.close()

    def add_notification(self, user_id, subscription_id, notification_type):
        """Добавление записи об отправленном уведомлении"""
        cursor = self.conn.cursor()
        cursor.execute('''
        INSERT INTO notifications (user_id, subscription_id, notification_type)
        VALUES (?, ?, ?)
        ''', (user_id, subscription_id, notification_type))
        self.conn.commit()

    def check_notification_sent(self, user_id, subscription_id, notification_type):
        """Проверка, было ли отправлено уведомление"""
        cursor = self.conn.cursor()
        cursor.execute('''
        SELECT COUNT(*) FROM notifications 
        WHERE user_id = ? AND subscription_id = ? AND notification_type = ?
        ''', (user_id, subscription_id, notification_type))
        count = cursor.fetchone()[0]
        return count > 0
