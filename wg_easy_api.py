import aiohttp
import logging
import json
import asyncio
import os
from typing import Optional

class WGEasyAPI:
    def __init__(self, host: str, port: str, password: str):
        """Инициализация API WireGuard Easy"""
        self.base_url = f"http://{host}:{port}"
        self.password = password
        self.session = None
        self.cookies = None
        logging.info(f"Initialized WireGuard API with base URL: {self.base_url}")

    async def _ensure_session(self):
        """Убеждаемся, что сессия существует"""
        try:
            if self.session is None:
                self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
                logging.debug("Created new aiohttp session")
        except Exception as e:
            logging.error(f"Error creating session: {str(e)}")
            raise

    async def _login(self):
        """Авторизация в API"""
        try:
            await self._ensure_session()
            
            headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
            data = {'password': self.password}
            
            logging.info(f"Attempting to login to WireGuard API at {self.base_url}/api/session")
            
            try:
                async with self.session.post(
                    f"{self.base_url}/api/session", 
                    json=data,
                    headers=headers,
                    timeout=10  # Таймаут в секундах
                ) as response:
                    response_text = await response.text()
                    logging.debug(f"Response status: {response.status}, headers: {dict(response.headers)}")
                    logging.debug(f"Response body: {response_text}")
                    
                    if response.status == 204:
                        if 'connect.sid' in response.cookies:
                            self.cookies = {'connect.sid': response.cookies['connect.sid'].value}
                            logging.info("Successfully logged in to WireGuard API")
                            return True
                        else:
                            logging.error("Login response OK but no session cookie received")
                            return False
                    else:
                        logging.error(f"Login failed with status {response.status}: {response_text}")
                        return False
                        
            except asyncio.TimeoutError:
                logging.error("Login request timed out after 10 seconds")
                return False
            except aiohttp.ClientError as e:
                logging.error(f"Network error during login: {str(e)}")
                return False
                
        except Exception as e:
            logging.error(f"Unexpected error during login: {str(e)}", exc_info=True)
            return False

    async def get_clients(self):
        """Получение списка клиентов"""
        await self._ensure_session()
        
        if not self.cookies:
            if not await self._login():
                logging.error("Failed to login")
                return None
        
        logging.info("Getting clients with cookies: %s", self.cookies)
        
        try:
            async with self.session.get(
                f"{self.base_url}/api/wireguard/client",
                cookies=self.cookies,
                timeout=10  # Таймаут в секундах
            ) as response:
                logging.debug(f"Response status: {response.status}, headers: {dict(response.headers)}")
                
                if response.status == 200:
                    clients = await response.json()
                    logging.info("Got clients list: %s", json.dumps(clients, indent=2))
                    return clients
                logging.error(f"Failed to get clients, status: {response.status}")
                return None
                
        except asyncio.TimeoutError:
            logging.error("Get clients request timed out after 10 seconds")
            return None
        except aiohttp.ClientError as e:
            logging.error(f"Network error during get clients: {str(e)}")
            return None
            
    async def create_client(self, name: str, enabled: bool = True):
        """Создание нового клиента"""
        await self._ensure_session()
        
        if not self.cookies:
            if not await self._login():
                logging.error("Failed to login")
                return None
        
        logging.info("Creating new client with name: %s", name)
        
        try:
            async with self.session.post(
                f"{self.base_url}/api/wireguard/client",
                json={'name': name},
                cookies=self.cookies,
                timeout=10  # Таймаут в секундах
            ) as response:
                logging.debug(f"Response status: {response.status}, headers: {dict(response.headers)}")
                
                if response.status == 200:
                    client = await response.json()
                    logging.info("Created client: %s", json.dumps(client, indent=2))
                    
                    # Клиент создается включенным по умолчанию
                    # Если нужно отключить, делаем это здесь
                    if not enabled and client:
                        await self.update_client(name, enable=False)
                    
                    return client
                logging.error(f"Failed to create client, status: {response.status}")
                return None
                
        except asyncio.TimeoutError:
            logging.error("Create client request timed out after 10 seconds")
            return None
        except aiohttp.ClientError as e:
            logging.error(f"Network error during create client: {str(e)}")
            return None

    async def get_client(self, name: str):
        """Получение информации о клиенте по имени"""
        clients = await self.get_clients()
        if not clients:
            logging.error("No clients found")
            return None
            
        logging.info("Looking for client '%s' in clients list", name)
        for client in clients:
            if client['name'] == name:
                logging.info("Found client: %s", json.dumps(client, indent=2))
                return client
        logging.warning("Client '%s' not found", name)
        return None

    async def update_client(self, client_name: str, enable: bool = True) -> bool:
        """Update client status"""
        try:
            # Получаем текущий список клиентов
            clients = await self.get_clients()
            logging.info("Looking for client '%s' in clients list", client_name)
            
            # Ищем клиента по имени
            client = next((c for c in clients if c['name'] == client_name), None)
            if client:
                logging.info("Found client: %s", json.dumps(client, indent=2))
                
                # Получаем ID клиента
                client_id = client['id']
                
                # Используем единый endpoint для включения/отключения
                url = f"{self.base_url}/api/wireguard/client/{client_id}/enable"
                method = self.session.post
                data = {"enabled": enable}
                    
                logging.info("Updating client with URL: %s, method: %s, enabled: %s", url, method.__name__, enable)
                
                # Отправляем запрос на обновление
                try:
                    async with method(url, json=data, cookies=self.cookies, timeout=10) as response:
                        response_text = await response.text()
                        # 204 означает успешное выполнение без тела ответа
                        if response.status in [200, 204]:
                            logging.info("Successfully updated client %s status to %s", client_name, enable)
                            
                            # Проверяем, что статус действительно обновился
                            updated_clients = await self.get_clients()
                            updated_client = next((c for c in updated_clients if c['name'] == client_name), None)
                            
                            if updated_client and updated_client.get('enabled') == enable:
                                logging.info("Verified client status update: %s", json.dumps(updated_client, indent=2))
                                return True
                            else:
                                logging.error("Client status verification failed. Expected enabled=%s, got: %s", 
                                            enable, updated_client)
                                return False
                        else:
                            logging.error("Failed to update client '%s', status: %d, response: %s",
                                        client_name, response.status, response_text)
                            return False
                except asyncio.TimeoutError:
                    logging.error("Update client request timed out after 10 seconds")
                    return False
                except aiohttp.ClientError as e:
                    logging.error(f"Network error during update client: {str(e)}")
                    return False
                    
            else:
                logging.error("Client '%s' not found in WireGuard", client_name)
                return False
                
        except Exception as e:
            logging.error(f"Error updating client '%s': %s", client_name, e)
            return False

    async def get_server_config(self) -> dict:
        """Получение конфигурации сервера"""
        try:
            # Сначала пробуем получить список клиентов, чтобы получить публичный ключ сервера
            clients_url = f"{self.base_url}/api/wireguard/client"
            async with self.session.get(clients_url, cookies=self.cookies) as response:
                if response.status == 200:
                    # В ответе должен быть объект с информацией о сервере
                    data = await response.json()
                    if isinstance(data, dict) and 'server' in data:
                        logging.info("Successfully got server config from clients response")
                        return data['server']
            
            # Если не получилось через clients, пробуем прямой endpoint
            url = f"{self.base_url}/api/wireguard/server"
            async with self.session.get(url, cookies=self.cookies) as response:
                if response.status == 200:
                    data = await response.json()
                    logging.info("Successfully got server config")
                    return data
                else:
                    logging.error(f"Failed to get server config. Status: {response.status}")
                    return None
        except Exception as e:
            logging.error(f"Error getting server config: {e}")
            return None

    async def generate_config(self, client: dict) -> dict:
        """Генерация конфигурации для клиента"""
        try:
            # Получаем данные сервера
            server_config = await self.get_server_config()
            if not server_config:
                # Если не удалось получить конфигурацию сервера, используем публичный ключ из окружения
                server_config = {'publicKey': os.getenv('WG_SERVER_PUBLIC_KEY')}
                if not server_config['publicKey']:
                    raise Exception("Failed to get server config and WG_SERVER_PUBLIC_KEY not set")
                logging.info("Using WG_SERVER_PUBLIC_KEY from environment")

            # Формируем endpoint без http:// и с портом 51820
            endpoint = self.base_url.replace('http://', '')
            if ':51821' in endpoint:
                endpoint = endpoint.replace(':51821', ':51820')
            elif not ':' in endpoint:
                endpoint = f"{endpoint}:51820"

            # Формируем конфигурацию
            config = (
                "[Interface]\n"
                f"PrivateKey = {client['privateKey']}\n"
                f"Address = {client['address']}/24\n"
                "DNS = 1.1.1.1\n\n"
                "[Peer]\n"
                f"PublicKey = {server_config['publicKey']}\n"
                f"PresharedKey = {client['preSharedKey']}\n"
                f"Endpoint = {endpoint}\n"
                "AllowedIPs = 0.0.0.0/0\n"
                "PersistentKeepalive = 25"
            )
            
            # Получаем QR-код из API
            url = f"{self.base_url}/api/wireguard/client/{client['name']}/qrcode"
            async with self.session.get(url, cookies=self.cookies) as response:
                if response.status == 200:
                    qr_code = await response.text()
                else:
                    logging.error(f"Failed to get QR code. Status: {response.status}")
                    qr_code = None
            
            return {
                'config': config,
                'qr_code': qr_code
            }
            
        except Exception as e:
            logging.error(f"Error generating config: {e}")
            raise

    async def remove_client(self, client_id: str) -> bool:
        """Удаление клиента WireGuard"""
        try:
            url = f"{self.base_url}/api/wireguard/client/{client_id}"
            async with self.session.delete(url, cookies=self.cookies) as response:
                # 204 означает успешное удаление без контента
                if response.status in [200, 204]:
                    logging.info(f"Successfully removed client {client_id}")
                    return True
                else:
                    logging.error(f"Failed to remove client {client_id}. Status: {response.status}")
                    return False
        except Exception as e:
            logging.error(f"Error removing client {client_id}: {e}")
            return False

    async def close(self):
        """Закрытие сессии"""
        if self.session:
            await self.session.close()
            self.session = None
