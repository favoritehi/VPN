import os
import qrcode
import logging
from datetime import datetime
from dotenv import load_dotenv

class Config:
    def __init__(self):
        load_dotenv()
        
        # Telegram configuration
        self.BOT_TOKEN = os.getenv('BOT_TOKEN')
        self.ADMIN_IDS = [int(id.strip()) for id in os.getenv('ADMIN_IDS', '').split(',') if id.strip()]
        
        # WireGuard servers configuration
        self.WG_SERVERS = {}
        server_count = int(os.getenv('WG_SERVER_COUNT', '1'))
        
        for i in range(server_count):
            suffix = f"_{i}" if i > 0 else ""
            self.WG_SERVERS[f"server{i}"] = {
                'host': os.getenv(f'WG_HOST{suffix}'),
                'port': os.getenv(f'WG_PORT{suffix}'),
                'password': os.getenv(f'WG_PASSWORD{suffix}')
            }

class ConfigManager:
    def __init__(self, base_path, config: Config):
        """Инициализация менеджера конфигураций"""
        self.base_path = base_path
        self.configs_dir = os.path.join(base_path, "configs")
        self.qr_codes_dir = os.path.join(base_path, "qr_codes")
        self.config = config
        
        # Создаем директории если их нет
        os.makedirs(self.configs_dir, exist_ok=True)
        os.makedirs(self.qr_codes_dir, exist_ok=True)

    def save_config(self, user_id: int, config: str, client_name: str) -> tuple[str, str]:
        """
        Сохраняет конфигурацию WireGuard и QR код
        
        Args:
            user_id: ID пользователя
            config: Строка конфигурации WireGuard
            client_name: Имя клиента
            
        Returns:
            tuple[str, str]: Пути к файлу конфигурации и QR коду
        """
        try:
            # Создаем директории если не существуют
            os.makedirs(self.configs_dir, exist_ok=True)
            os.makedirs(self.qr_codes_dir, exist_ok=True)
            
            # Формируем имена файлов
            config_path = os.path.join(self.configs_dir, f"{client_name}.conf")
            qr_path = os.path.join(self.qr_codes_dir, f"{client_name}.png")
            
            # Сохраняем конфигурацию
            with open(config_path, 'w') as f:
                f.write(config)
                
            # Генерируем QR код
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(config)
            qr.make(fit=True)
            
            # Создаем изображение
            img = qr.make_image(fill_color="black", back_color="white")
            img.save(qr_path)
            
            logging.info(f"Saved config and QR for user {user_id}")
            return config_path, qr_path
            
        except Exception as e:
            logging.error(f"Error saving config: {e}")
            return None, None

    def get_latest_config(self, user_id: int, server_name: str) -> tuple[str, str]:
        """
        Получает пути к последним сохраненным файлам конфигурации
        Возвращает кортеж из путей к файлу конфига и QR коду
        """
        try:
            # Ищем все файлы конфигурации пользователя
            config_files = [f for f in os.listdir(self.configs_dir) if f.startswith(f"wg_{user_id}_{server_name}_")]
            qr_files = [f for f in os.listdir(self.qr_codes_dir) if f.startswith(f"qr_{user_id}_{server_name}_")]
            
            if not config_files or not qr_files:
                return None, None
            
            # Берем самые свежие файлы
            latest_config = sorted(config_files)[-1]
            latest_qr = sorted(qr_files)[-1]
            
            return (
                os.path.join(self.configs_dir, latest_config),
                os.path.join(self.qr_codes_dir, latest_qr)
            )
            
        except Exception as e:
            logging.error(f"Error getting config files for user {user_id} on server {server_name}: {e}")
            return None, None
    
    def cleanup_old_configs(self, user_id: int, server_name: str, keep_latest: int = 3):
        """Удаляет старые конфигурации, оставляя только последние keep_latest штук"""
        try:
            # Получаем все файлы пользователя
            config_files = [f for f in os.listdir(self.configs_dir) if f.startswith(f"wg_{user_id}_{server_name}_")]
            qr_files = [f for f in os.listdir(self.qr_codes_dir) if f.startswith(f"qr_{user_id}_{server_name}_")]
            
            # Сортируем файлы по времени создания
            config_files.sort()
            qr_files.sort()
            
            # Удаляем старые файлы, оставляя только последние keep_latest
            for old_config in config_files[:-keep_latest]:
                os.remove(os.path.join(self.configs_dir, old_config))
            
            for old_qr in qr_files[:-keep_latest]:
                os.remove(os.path.join(self.qr_codes_dir, old_qr))
                
            logging.info(f"Cleaned up old config files for user {user_id} on server {server_name}")
            
        except Exception as e:
            logging.error(f"Error cleaning up old configs for user {user_id} on server {server_name}: {e}")
