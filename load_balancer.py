import logging
from typing import Dict, Optional
from datetime import datetime
import json
import os

class LoadBalancer:
    def __init__(self, state_file="servers_state.json"):
        self.state_file = state_file
        self.servers = {}
        self.load_state()

    def add_server(self, server_id: str, server_info: dict):
        """Добавить новый сервер"""
        if server_id in self.servers:
            logging.warning(f"Server {server_id} already exists")
            return
        
        server_info['clients_count'] = server_info.get('clients_count', 0)
        server_info['added_at'] = str(datetime.now())
        self.servers[server_id] = server_info
        self.save_state()
        logging.info(f"Added server {server_id}: {server_info}")

    def get_server_info(self, server_id: str) -> Optional[dict]:
        """Получить информацию о сервере"""
        return self.servers.get(server_id)

    def select_server(self) -> str:
        """Выбрать сервер с наименьшей нагрузкой"""
        if not self.servers:
            raise Exception("No servers available")

        # Сортируем серверы по количеству клиентов
        sorted_servers = sorted(
            self.servers.items(),
            key=lambda x: x[1].get('clients_count', 0)
        )

        # Возвращаем ID сервера с наименьшим количеством клиентов
        selected_server_id = sorted_servers[0][0]
        logging.info(f"Selected server {selected_server_id} with {self.servers[selected_server_id].get('clients_count', 0)} clients")
        return selected_server_id

    def update_server_clients_count(self, server_id: str, count: Optional[int] = None):
        """Обновить количество клиентов на сервере"""
        if server_id not in self.servers:
            logging.error(f"Server {server_id} not found")
            return

        if count is None:
            # Если количество не указано, увеличиваем на 1
            self.servers[server_id]['clients_count'] = self.servers[server_id].get('clients_count', 0) + 1
        else:
            self.servers[server_id]['clients_count'] = count

        self.save_state()
        logging.info(f"Updated server {server_id} clients count to {self.servers[server_id]['clients_count']}")

    def load_state(self):
        """Загрузить состояние из файла"""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    self.servers = json.load(f)
                logging.info(f"Loaded {len(self.servers)} servers from state")
        except Exception as e:
            logging.error(f"Error loading state: {e}")
            self.servers = {}

    def save_state(self):
        """Сохранить состояние в файл"""
        try:
            with open(self.state_file, 'w') as f:
                json.dump(self.servers, f, indent=2)
        except Exception as e:
            logging.error(f"Error saving state: {e}")

    def get_all_servers(self) -> dict:
        """Получить информацию о всех серверах"""
        return self.servers
