import logging
from database import Database

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Создаем экземпляр базы данных
db = Database('vpn_bot.db')

# Запускаем тест
active_subs = db.test_subscription()

# Закрываем соединение
db.close()
