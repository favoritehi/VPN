import subprocess
import os
import json
from datetime import datetime, timedelta

class WireGuardManager:
    def __init__(self, config_dir="/etc/wireguard"):
        self.config_dir = config_dir
        self.interface = "wg0"
        self.config_file = os.path.join(config_dir, f"{self.interface}.conf")
        self.clients_dir = os.path.join(config_dir, "clients")
        self.db_file = os.path.join(config_dir, "clients.json")
        
        # Создаем директорию для клиентских конфигураций если её нет
        os.makedirs(self.clients_dir, exist_ok=True)
        
        # Инициализируем базу данных клиентов если её нет
        if not os.path.exists(self.db_file):
            self._save_clients({})

    def _save_clients(self, clients):
        """Сохранить информацию о клиентах в JSON файл"""
        with open(self.db_file, 'w') as f:
            json.dump(clients, f, indent=4)

    def _load_clients(self):
        """Загрузить информацию о клиентах из JSON файла"""
        if os.path.exists(self.db_file):
            with open(self.db_file, 'r') as f:
                return json.load(f)
        return {}

    def generate_keys(self):
        """Генерация пары ключей WireGuard"""
        private_key = subprocess.check_output(["wg", "genkey"]).decode().strip()
        public_key = subprocess.check_output(["wg", "pubkey"], input=private_key.encode()).decode().strip()
        return private_key, public_key

    def add_client(self, client_id, expiration_days):
        """Добавить нового клиента"""
        # Генерируем ключи для клиента
        private_key, public_key = self.generate_keys()
        
        # Получаем текущую конфигурацию сервера
        with open(self.config_file, 'r') as f:
            server_config = f.read()
        
        # Извлекаем публичный ключ и endpoint сервера
        server_public_key = None
        server_endpoint = None
        for line in server_config.split('\n'):
            if "PublicKey" in line:
                server_public_key = line.split('=')[1].strip()
            elif "Endpoint" in line:
                server_endpoint = line.split('=')[1].strip()

        # Создаем конфигурацию клиента
        client_ip = self._get_next_ip()
        client_config = f"""[Interface]
PrivateKey = {private_key}
Address = {client_ip}/32
DNS = 1.1.1.1, 8.8.8.8

[Peer]
PublicKey = {server_public_key}
AllowedIPs = 0.0.0.0/0
Endpoint = {server_endpoint}
PersistentKeepalive = 25"""

        # Сохраняем конфигурацию клиента
        client_config_path = os.path.join(self.clients_dir, f"{client_id}.conf")
        with open(client_config_path, 'w') as f:
            f.write(client_config)

        # Добавляем пир на сервере
        subprocess.run([
            "wg", "set", self.interface,
            "peer", public_key,
            "allowed-ips", client_ip + "/32"
        ])

        # Сохраняем информацию о клиенте
        clients = self._load_clients()
        clients[client_id] = {
            "public_key": public_key,
            "ip": client_ip,
            "created_at": datetime.now().isoformat(),
            "expires_at": (datetime.now() + timedelta(days=expiration_days)).isoformat()
        }
        self._save_clients(clients)

        return client_config

    def remove_client(self, client_id):
        """Удалить клиента"""
        clients = self._load_clients()
        if client_id in clients:
            # Удаляем пир с сервера
            subprocess.run([
                "wg", "set", self.interface,
                "peer", clients[client_id]["public_key"],
                "remove"
            ])
            
            # Удаляем конфигурацию клиента
            config_path = os.path.join(self.clients_dir, f"{client_id}.conf")
            if os.path.exists(config_path):
                os.remove(config_path)
            
            # Удаляем информацию о клиенте из базы
            del clients[client_id]
            self._save_clients(clients)
            return True
        return False

    def _get_next_ip(self):
        """Получить следующий доступный IP адрес"""
        clients = self._load_clients()
        used_ips = [client["ip"] for client in clients.values()]
        
        # Начинаем с 10.0.0.2 (10.0.0.1 обычно используется сервером)
        ip_parts = [10, 0, 0, 2]
        while True:
            current_ip = ".".join(map(str, ip_parts))
            if current_ip not in used_ips:
                return current_ip
            
            # Увеличиваем последний октет
            ip_parts[3] += 1
            if ip_parts[3] > 254:
                ip_parts[3] = 2
                ip_parts[2] += 1
                if ip_parts[2] > 254:
                    raise Exception("No available IP addresses")

    def get_client_config(self, client_id):
        """Получить конфигурацию клиента"""
        config_path = os.path.join(self.clients_dir, f"{client_id}.conf")
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                return f.read()
        return None

    def check_client_expiration(self, client_id):
        """Проверить срок действия подписки клиента"""
        clients = self._load_clients()
        if client_id in clients:
            expires_at = datetime.fromisoformat(clients[client_id]["expires_at"])
            return expires_at > datetime.now()
        return False

    def extend_client_subscription(self, client_id, days):
        """Продлить подписку клиента"""
        clients = self._load_clients()
        if client_id in clients:
            current_expiration = datetime.fromisoformat(clients[client_id]["expires_at"])
            new_expiration = current_expiration + timedelta(days=days)
            clients[client_id]["expires_at"] = new_expiration.isoformat()
            self._save_clients(clients)
            return True
        return False
