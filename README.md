# VPN Bot

Telegram бот для управления VPN на базе WireGuard с системой подписок, платежей и рефералов.

## Возможности

- 🔐 Автоматическая генерация WireGuard конфигураций
- 💳 Интеграция с платежной системой YooMoney
- 📅 Система подписок с разными тарифными планами
- 👥 Реферальная программа с комиссией 10%
- 📊 Статистика использования
- 🔔 Автоматические уведомления об истечении подписки

## Установка

1. Клонируйте репозиторий:
```bash
git clone https://github.com/yourusername/vpn-bot.git
cd vpn-bot
```

2. Установите зависимости:
```bash
pip install -r requirements.txt
```

3. Создайте файл `.env` и заполните его:
```env
TELEGRAM_TOKEN=your_bot_token
WG_HOST=your_wireguard_host
WG_PORT=51820
WG_API_PORT=51821
WG_API_PASSWORD=your_password

# YooMoney API credentials
YOOMONEY_SHOP_ID=your_shop_id
YOOMONEY_SECRET_KEY=your_secret_key
PAYMENT_RETURN_URL=https://t.me/your_bot_username

# Admin settings
ADMIN_USER_ID=your_telegram_id
SUPPORT_USER_ID=your_support_id
```

4. Запустите бота:
```bash
python bot.py
```

## Структура проекта

- `bot.py` - основной файл бота
- `wg_easy_api.py` - API клиент для WireGuard
- `database.py` - работа с базой данных SQLite
- `payment.py` - интеграция с платежной системой
- `scheduler.py` - планировщик задач для уведомлений

## Использование

1. Найдите бота в Telegram
2. Отправьте команду `/start`
3. Выберите тарифный план
4. Оплатите подписку
5. Получите конфигурацию и QR-код
6. Установите WireGuard и импортируйте конфигурацию

## Тарифные планы

- 1 месяц: 200₽
- 3 месяца: 500₽
- 6 месяцев: 900₽
- 1 год: 1500₽

## Реферальная программа

1. Получите реферальную ссылку в боте
2. Поделитесь ей с друзьями
3. Получайте 10% от каждого платежа реферала

## Автор

Илья Коваленко
