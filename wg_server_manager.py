import logging
from typing import Dict, List, Optional
from wg_easy_api import WGEasyAPI
import os
from dotenv import load_dotenv

class WGServerManager:
    def __init__(self):
        self.servers: Dict[str, WGEasyAPI] = {}
        self.current_server_index = 0
        self._load_servers_from_env()
        
    def _load_servers_from_env(self):
        """Загрузка серверов из переменных окружения"""
        load_dotenv()
        
        server_count = int(os.getenv('WG_SERVER_COUNT', '1'))
        
        for i in range(server_count):
            suffix = f"_{i}" if i > 0 else ""
            host = os.getenv(f'WG_HOST{suffix}')
            api_port = os.getenv(f'WG_API_PORT{suffix}')
            api_password = os.getenv(f'WG_API_PASSWORD{suffix}')
            
            if host and api_port and api_password:
                server_id = f"server{i}"
                self.servers[server_id] = WGEasyAPI(host, api_port, api_password)
                logging.info(f"Loaded WireGuard server {server_id} with host {host}")
            else:
                logging.warning(f"Missing configuration for server {i}")
                
    def add_server(self, server_id: str, host: str, port: str, password: str):
        """Добавить новый WireGuard сервер"""
        self.servers[server_id] = WGEasyAPI(host, port, password)
        logging.info(f"Added new WireGuard server: {server_id}")
        
    async def get_next_available_server(self) -> Optional[WGEasyAPI]:
        """Получить следующий доступный сервер для создания клиента"""
        if not self.servers:
            return None
            
        # Простая карусельная балансировка
        server_ids = list(self.servers.keys())
        start_index = self.current_server_index
        
        for _ in range(len(server_ids)):
            server_id = server_ids[self.current_server_index]
            server = self.servers[server_id]
            
            # Проверяем количество клиентов на сервере
            clients = await server.get_clients()
            if clients is not None and len(clients) < 50:  # Максимальное количество клиентов на сервер
                self.current_server_index = (self.current_server_index + 1) % len(server_ids)
                return server
                
            self.current_server_index = (self.current_server_index + 1) % len(server_ids)
            
        logging.warning("No available servers found")
        return None
        
    async def get_all_clients(self) -> List[dict]:
        """Получить список всех клиентов со всех серверов"""
        all_clients = []
        for server_id, server in self.servers.items():
            clients = await server.get_clients()
            if clients:
                for client in clients:
                    client['server_id'] = server_id
                all_clients.extend(clients)
        return all_clients
        
    async def get_client_by_name(self, name: str) -> Optional[tuple]:
        """Найти клиента по имени на всех серверах"""
        for server_id, server in self.servers.items():
            clients = await server.get_clients()
            if clients:
                for client in clients:
                    if client['name'] == name:
                        return server, client
        return None
        
    async def create_client(self, name: str) -> Optional[dict]:
        """Создать нового клиента на наименее загруженном сервере"""
        server = await self.get_next_available_server()
        if server:
            return await server.create_client(name)
        return None
