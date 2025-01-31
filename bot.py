import logging

# Настройка логирования
logging.basicConfig(
    level=logging.DEBUG,  # Изменено с INFO на DEBUG
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('bot_debug.log', encoding='utf-8', mode='w'),
        logging.StreamHandler()
    ]
)

import os
import uuid
import json
import qrcode
import asyncio
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import FSInputFile, ReplyKeyboardMarkup, KeyboardButton
from dotenv import load_dotenv
from database import Database
from wg_easy_api import WGEasyAPI
from config_manager import ConfigManager, Config
import fcntl
import atexit

# Загружаем переменные окружения
load_dotenv()

# Инициализация бота и базы данных
bot = Bot(token=os.getenv('BOT_TOKEN'))
db = Database('vpn_bot.db')
wg_api = None

# Инициализация конфигурации
config = Config()
config_manager = ConfigManager(os.path.dirname(os.path.abspath(__file__)), config)

# ID администратора
ADMIN_USER_ID = int(os.getenv('ADMIN_USER_ID'))

# Цены на подписки (в рублях)
PRICE_TEST = 1
PRICE_26_HOURS = 50
PRICE_1_WEEK = 149
PRICE_1_MONTH = 199
PRICE_3_MONTHS = 399
PRICE_6_MONTHS = 1199
PRICE_12_MONTHS = 1999

# Состояния FSM
class PaymentStates(StatesGroup):
    waiting_for_payment_method = State()
    waiting_for_screenshot = State()

# Создаем диспетчер
dp = Dispatcher()

# Глобальная переменная для отслеживания отправленных уведомлений
notification_sent = {}

def ensure_single_instance():
    """Проверка на запуск единственного экземпляра бота"""
    try:
        # Создаем файл блокировки
        lock_file = open("/tmp/vpn_bot.lock", "w")
        fcntl.lockf(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        
        # Регистрируем очистку при выходе
        def cleanup():
            try:
                lock_file.close()
                os.unlink("/tmp/vpn_bot.lock")
            except:
                pass
        atexit.register(cleanup)
        
        return True
    except IOError:
        logging.error("Другой экземпляр бота уже запущен")
        return False

# Хэндлеры
@dp.message(Command("start"))
async def handle_start(message: types.Message, state: FSMContext):
    """Обработка команды /start"""
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(text="💳 Купить подписку", callback_data="buy"),
                types.InlineKeyboardButton(text="📊 Статус подписки", callback_data="status")
            ],
            [
                types.InlineKeyboardButton(text="🔐 Мои данные", callback_data="my_data"),
                types.InlineKeyboardButton(text="❓ Помощь", callback_data="help")
            ]
        ]
    )
    
    await message.answer(
        "👋 Добро пожаловать в SAFEVPN!\n\n"
        "🌐 Мы предоставляем безопасный и быстрый VPN-сервис.\n\n"
        "Выберите действие:",
        reply_markup=keyboard
    )
    await state.clear()

@dp.callback_query(lambda c: c.data == "buy")
async def show_subscription_menu(callback_query: types.CallbackQuery):
    """Показать меню подписок"""
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text=f"26 часов - {PRICE_26_HOURS}₽", callback_data="sub_26h")],
            [types.InlineKeyboardButton(text=f"1 неделя - {PRICE_1_WEEK}₽", callback_data="sub_week")],
            [
                types.InlineKeyboardButton(text=f"1 месяц - {PRICE_1_MONTH}₽", callback_data="sub_1"),
                types.InlineKeyboardButton(text=f"3 месяца - {PRICE_3_MONTHS}₽", callback_data="sub_3")
            ],
            [
                types.InlineKeyboardButton(text=f"6 месяцев - {PRICE_6_MONTHS}₽", callback_data="sub_6"),
                types.InlineKeyboardButton(text=f"12 месяцев - {PRICE_12_MONTHS}₽", callback_data="sub_12")
            ],
            [types.InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main")]
        ]
    )
    
    await callback_query.message.edit_text(
        "💳 Выберите длительность подписки:",
        reply_markup=keyboard
    )

@dp.callback_query(lambda c: c.data == "status")
async def show_subscription_status(callback_query: types.CallbackQuery):
    """Показать статус подписки"""
    user_id = callback_query.from_user.id
    subscription = db.get_subscription(user_id)
    
    if not subscription:
        keyboard = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="Купить подписку",
                        callback_data="buy"
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text="« Назад",
                        callback_data="back_to_main"
                    )
                ]
            ]
        )
        await callback_query.message.edit_text(
            "❌ У вас нет активной подписки.\n"
            "Нажмите кнопку ниже, чтобы приобрести подписку.",
            reply_markup=keyboard
        )
        return
    
    expiration_str = subscription['expiration']
    expiration_time = datetime.strptime(expiration_str.split('.')[0], '%Y-%m-%d %H:%M:%S')
    time_left = expiration_time - datetime.now()
    
    # Получаем конфигурацию клиента
    client_config = db.get_client_config(user_id)
    if not client_config:
        await callback_query.message.edit_text(
            "❌ Ошибка: конфигурация клиента не найдена.\n"
            "Пожалуйста, обратитесь в поддержку.",
            reply_markup=types.InlineKeyboardMarkup(
                inline_keyboard=[[
                    types.InlineKeyboardButton(
                        text="« Назад",
                        callback_data="back_to_main"
                    )
                ]]
            )
        )
        return
    
    # Проверяем статус подключения в WireGuard
    client = await wg_api.get_client(client_config.get('config_name'))
    subscription_status = "✅ Активна" if subscription['is_active'] else "❌ Не активна"
    
    # Создаем клавиатуру
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="Продлить подписку",
                    callback_data="extend_subscription"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="« Назад",
                    callback_data="back_to_main"
                )
            ]
        ]
    )
    
    # Форматируем оставшееся время
    days = time_left.days
    hours = time_left.seconds // 3600
    
    await callback_query.message.edit_text(
        f"📊 Статус вашей подписки:\n\n"
        f"📅 Действует до: {expiration_str.split('.')[0]}\n"
        f"🔐 Статус подписки: {subscription_status}\n"
        f"⏳ Осталось: {days} дней и {hours} часов",
        reply_markup=keyboard
    )

@dp.callback_query(lambda c: c.data == "help")
async def show_help(callback_query: types.CallbackQuery):
    """Показать помощь"""
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[[types.InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main")]]
    )
    
    await callback_query.message.edit_text(
        "❓ Помощь\n\n"
        "🔹 Как купить подписку:\n"
        "1. Нажмите '💳 Купить подписку'\n"
        "2. Выберите длительность\n"
        "3. Оплатите картой\n"
        "4. Отправьте скриншот чека\n\n"
        "🔹 Как подключиться:\n"
        "1. Установите приложение WireGuard\n"
        "2. Импортируйте конфигурационный файл\n"
        "3. Включите VPN\n\n"
        "🔹 Есть вопросы?\n"
        "Напишите в поддержку: @support",
        reply_markup=keyboard
    )

@dp.callback_query(lambda c: c.data == "back_to_main")
async def back_to_main_menu(callback_query: types.CallbackQuery):
    """Вернуться в главное меню"""
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(text="💳 Купить подписку", callback_data="buy"),
                types.InlineKeyboardButton(text="📊 Статус подписки", callback_data="status")
            ],
            [
                types.InlineKeyboardButton(text="🔐 Мои данные", callback_data="my_data"),
                types.InlineKeyboardButton(text="❓ Помощь", callback_data="help")
            ]
        ]
    )
    
    await callback_query.message.edit_text(
        "👋 Добро пожаловать в SAFEVPN!\n\n"
        "🌐 Мы предоставляем безопасный и быстрый VPN-сервис.\n\n"
        "Выберите действие:",
        reply_markup=keyboard
    )

@dp.message(Command("clear_data"))
async def handle_admin_command(message: types.Message):
    """Обработка команды /clear_data"""
    if message.from_user.id != ADMIN_USER_ID:
        await message.answer("⛔️ У вас нет прав для выполнения этой команды")
        return
    
    try:
        db.clear_all_data()
        await message.answer("✅ База данных очищена")
    except Exception as e:
        logging.error(f"Error clearing database: {e}")
        await message.answer("❌ Ошибка при очистке базы данных")

@dp.callback_query(lambda c: c.data == "action_subscribe")
async def process_subscribe_action(callback: types.CallbackQuery, state: FSMContext):
    if db.check_subscription(callback.from_user.id):
        end_date = db.get_subscription_end_date(callback.from_user.id)
        await callback.message.edit_text(
            f"У вас уже есть активная подписка до {end_date.strftime('%d.%m.%Y')}.\n"
            "Хотите продлить подписку?",
            reply_markup=get_subscription_keyboard()
        )
    else:
        await callback.message.edit_text(
            "Выберите длительность подписки:",
            reply_markup=get_subscription_keyboard()
        )
    await state.set_state(PaymentStates.waiting_for_payment_method)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "action_status")
async def process_status_action(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    subscription = db.get_subscription(user_id)
    
    if subscription:
        try:
            # Обрезаем микросекунды из даты
            end_date_str = subscription[4].split('.')[0]  # Используем индекс 4 для end_date
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d %H:%M:%S')
            
            now = datetime.now()
            remaining_time = end_date - now
            remaining_days = remaining_time.days
            
            if remaining_days > 0:
                # Форматируем оставшееся время
                if remaining_days >= 365:
                    years = remaining_days // 365
                    days = remaining_days % 365
                    time_str = f"{years} год(а) и {days} дней"
                elif remaining_days >= 30:
                    months = remaining_days // 30
                    days = remaining_days % 30
                    time_str = f"{months} месяц(ев) и {days} дней"
                else:
                    time_str = f"{remaining_days} дней"
                
                await callback.message.answer(
                    f"🔓 Ваша подписка активна\n\n"
                    f"📅 Осталось: {time_str}\n"
                    f"📆 Дата окончания: {end_date.strftime('%d.%m.%Y %H:%M')}\n"
                    f"🔑 Конфигурация: {subscription[2]}"  # Используем индекс 2 для config_name
                )
            else:
                await callback.message.answer(
                    "❌ Ваша подписка истекла\n\n"
                    "Для продления нажмите кнопку «Купить» в главном меню"
                )
        except Exception as e:
            logging.error(f"Error processing subscription status: {e}")
            await callback.message.answer(
                "⚠️ Произошла ошибка при проверке статуса подписки\n"
                "Пожалуйста, попробуйте позже или обратитесь в поддержку"
            )
    else:
        await callback.message.answer(
            "❌ У вас нет активной подписки\n\n"
            "Для покупки нажмите кнопку «Купить» в главном меню"
        )
    
    await callback.answer()

@dp.callback_query(lambda c: c.data == "action_help")
async def process_help_action(callback: types.CallbackQuery):
    help_text = (
        "🔍 Помощь по использованию бота:\n\n"
        "💳 Купить подписку - Оформить или продлить подписку\n"
        "📊 Статус подписки - Проверить текущий статус\n"
        "❓ Помощь - Показать это сообщение\n\n"
        "При возникновении проблем обратитесь в поддержку: @support"
    )
    await callback.message.edit_text(
        help_text,
        reply_markup=get_main_keyboard()
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("sub_"))
async def process_subscription_duration(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработка выбора длительности подписки"""
    # Пропускаем обработку для sub_menu
    if callback_query.data == 'sub_menu':
        return
        
    try:
        duration_str = callback_query.data.split('_')[1]
        
        # Определяем текст и цену в зависимости от длительности
        if duration_str == '0':
            duration = 0
            duration_text = "5 минут (тест)"
            price = PRICE_TEST
            days = 0  # 5 минут
        elif duration_str == '26h':
            duration = 1.08  # используем 1.08 для обозначения 26 часов
            duration_text = "26 часов"
            price = PRICE_26_HOURS
            days = 1.08
        elif duration_str == 'week':
            duration = 7
            duration_text = "1 неделя"
            price = PRICE_1_WEEK
            days = 7
        elif duration_str == '1':
            duration = 1
            duration_text = "1 месяц"
            price = PRICE_1_MONTH
            days = 30
        elif duration_str == '3':
            duration = 3
            duration_text = "3 месяца"
            price = PRICE_3_MONTHS
            days = 90
        elif duration_str == '6':
            duration = 6
            duration_text = "6 месяцев"
            price = PRICE_6_MONTHS
            days = 180
        elif duration_str == '12':
            duration = 12
            duration_text = "12 месяцев"
            price = PRICE_12_MONTHS
            days = 365
        else:
            await callback_query.answer("❌ Неверная длительность")
            return
        
        logging.info("Processing subscription duration. Callback data: %s", callback_query.data)
        logging.info("Duration: %s days: %s", duration, days)
        logging.info("Duration text: %s, Price: %s", duration_text, price)
        
        # Сохраняем данные в состояние
        await state.update_data(duration=duration, amount=price, days=days)
        logging.info("State after update: %s", await state.get_data())
        
        # Создаем клавиатуру для выбора способа оплаты
        keyboard = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [types.InlineKeyboardButton(text="💳 Банковская карта", callback_data="pay_card")],
                [types.InlineKeyboardButton(text="↩️ Назад", callback_data="sub_menu")]
            ]
        )
        
        await callback_query.message.edit_text(
            f"💰 Стоимость подписки: {price}₽\n"
            f"⏱ Длительность: {duration_text}\n\n"
            "Выберите способ оплаты:",
            reply_markup=keyboard
        )
        
        # Устанавливаем новое состояние
        await state.set_state(PaymentStates.waiting_for_payment_method)
        logging.info("New state: %s", PaymentStates.waiting_for_payment_method)
        
    except ValueError:
        logging.error(f"Invalid subscription duration: {callback_query.data}")
        await callback_query.answer("❌ Ошибка при выборе длительности")

@dp.callback_query(lambda c: c.data.startswith("pay_"))
async def process_payment_method(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработка выбора способа оплаты"""
    logging.info("Processing payment method selection")
    
    # Получаем данные из состояния
    state_data = await state.get_data()
    logging.info("Current state data: %s", state_data)
    
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="↩️ Назад", callback_data="sub_menu")]
        ]
    )
    
    card_info = (
        "💳 Оплата картой\n\n"
        "Для оплаты переведите {amount}₽ на карту:\n"
        "2202 2024 3331 7260\n\n"
        "После оплаты отправьте скриншот чека."
    ).format(amount=state_data['amount'])
    
    await callback_query.message.edit_text(card_info, reply_markup=keyboard)
    
    # Устанавливаем новое состояние
    await state.set_state(PaymentStates.waiting_for_screenshot)
    logging.info("New state: %s", PaymentStates.waiting_for_screenshot)

@dp.message(PaymentStates.waiting_for_screenshot)
async def process_payment_screenshot(message: types.Message, state: FSMContext):
    """Обработка скриншота оплаты"""
    if not message.photo:
        await message.answer(
            "❌ Пожалуйста, отправьте скриншот оплаты.\n"
            "Отправьте /start для отмены."
        )
        return

    try:
        state_data = await state.get_data()
        duration = state_data.get('duration')
        amount = state_data.get('amount')

        if duration is None or amount is None:
            await message.answer(
                "❌ Ошибка: данные платежа не найдены.\n"
                "Начните заново с команды /start"
            )
            await state.clear()
            return

        # Создаем запись о платеже
        payment_id = str(uuid.uuid4())
        duration_months = float(duration)  # Конвертируем в месяцы
        
        try:
            if not db.add_payment(payment_id, message.from_user.id, float(amount), duration_months):
                await message.answer(
                    "❌ Произошла ошибка при создании платежа.\n"
                    "Пожалуйста, попробуйте еще раз или обратитесь к администратору."
                )
                return
        except Exception as e:
            logging.error(f"Failed to add payment to database: {e}")
            await message.answer(
                "❌ Произошла ошибка при создании платежа.\n"
                "Пожалуйста, попробуйте еще раз или обратитесь к администратору."
            )
            return

        # Формируем сообщение для админа
        duration_text = (
            "5 минут (тест)" if duration == 0 else
            f"{duration} {'месяц' if duration == 1 else 'месяца' if duration in [2,3,4] else 'месяцев'}"
        )

        keyboard = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm:{payment_id}"),
                    types.InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{payment_id}")
                ]
            ]
        )

        # Отправляем скриншот и информацию админу
        await bot.send_photo(
            ADMIN_USER_ID,
            message.photo[-1].file_id,
            caption=(
                "🔄 Новый платеж\n\n"
                f"👤 Пользователь: {message.from_user.id}\n"
                f"💰 Сумма: {amount} руб.\n"
                f"⏱ Длительность: {duration_text}\n"
                f"🆔 ID платежа: {payment_id}"
            ),
            reply_markup=keyboard
        )

        # Отправляем подтверждение пользователю
        await message.answer(
            "✅ Скриншот получен!\n\n"
            "Ожидайте подтверждения оплаты администратором.\n"
            "Вы получите уведомление, когда ваш платеж будет обработан."
        )
        
        # Очищаем состояние
        await state.clear()
        
    except Exception as e:
        logging.error(f"Error processing payment screenshot: {e}", exc_info=True)
        await message.answer(
            "❌ Произошла ошибка при обработке платежа.\n"
            "Пожалуйста, попробуйте еще раз или обратитесь к администратору."
        )

@dp.callback_query(lambda c: c.data.startswith(("confirm:", "reject:")))
async def process_payment_verification(callback_query: types.CallbackQuery):
    """Обработка подтверждения оплаты админом"""
    user_id = callback_query.from_user.id
    
    if user_id != ADMIN_USER_ID:
        await callback_query.answer("❌ У вас нет прав для этого действия")
        return
    
    try:
        action, payment_id = callback_query.data.split(':')
        payment_data = db.get_payment(payment_id)
        
        if not payment_data:
            await callback_query.answer("❌ Платёж не найден")
            return
        
        # Распаковываем данные платежа
        payment_id, user_id, amount, duration, status, created_at = payment_data
        
        # Проверяем, не был ли платеж уже обработан
        if status != 'pending':
            await callback_query.answer("❌ Этот платёж уже был обработан")
            return
            
        if action == "confirm":
            try:
                # Обновляем статус платежа
                db.update_payment_status(payment_id, "confirmed")
                logging.info(f"Updated payment {payment_id} status to confirmed")
                
                # Получаем текущую подписку пользователя
                current_subscription = db.get_subscription(user_id)
                client_name = f"user_{user_id}"
                
                # Проверяем существующую конфигурацию клиента
                client_config = db.get_client_config(user_id)
                
                # Если это новая подписка (нет конфигурации), создаем нового клиента
                if not client_config:
                    # Создаем нового клиента в WireGuard
                    client = await wg_api.create_client(client_name)
                    if not client:
                        raise Exception("Failed to create WireGuard client")
                    logging.info(f"Created client: {json.dumps(client, indent=2)}")
                    
                    # Генерируем конфигурацию
                    config = await wg_api.generate_config(client)
                    if not config or 'config' not in config:
                        raise Exception("Failed to generate client config")
                    logging.info("Generated client configuration")
                    
                    # Сохраняем конфигурацию
                    db.save_client_config(user_id, {
                        'config_name': client_name,
                        'config': config['config'],
                        'qr_code': config.get('qr_code')  # qr_code может быть None
                    })
                    logging.info("Saved client configuration to database")
                
                # Добавляем или продлеваем подписку
                duration_days = duration * 30 if duration > 0 else 1  # 1 день для тестового периода
                if not db.add_subscription(user_id, duration_days):
                    raise Exception("Failed to add subscription")
                logging.info(f"Added/extended subscription for {duration_days} days")
                
                # Отправляем уведомление пользователю
                subscription = db.get_subscription(user_id)
                if subscription:
                    expiration_date = datetime.strptime(subscription['expiration'].split('.')[0], '%Y-%m-%d %H:%M:%S')
                    keyboard = types.InlineKeyboardMarkup(
                        inline_keyboard=[
                            [types.InlineKeyboardButton(text="🔑 Получить данные для подключения", callback_data="show_data")]
                        ]
                    )
                    await bot.send_message(
                        user_id,
                        f"✅ Оплата подтверждена!\n\n"
                        f"Ваша подписка активна до: {expiration_date.strftime('%d.%m.%Y %H:%M')}",
                        reply_markup=keyboard
                    )
                    logging.info(f"Sent confirmation message to user {user_id}")
                
                # Отвечаем админу
                await callback_query.message.edit_caption(
                    callback_query.message.caption + "\n\n✅ Платёж подтверждён",
                    reply_markup=None
                )
                logging.info("Updated admin's message")
                
            except Exception as e:
                logging.error(f"Error confirming payment: {e}", exc_info=True)
                await callback_query.message.reply(f"❌ Ошибка при подтверждении платежа: {str(e)}")
                return
                
        elif action == "reject":
            # Обновляем статус платежа
            db.update_payment_status(payment_id, "rejected")
            
            # Отправляем уведомление пользователю
            await bot.send_message(
                user_id,
                "❌ Ваш платёж был отклонён.\n"
                "Пожалуйста, проверьте правильность оплаты и попробуйте снова."
            )
            
            # Отвечаем админу
            await callback_query.message.edit_caption(
                callback_query.message.caption + "\n\n❌ Платёж отклонён",
                reply_markup=None
            )
            
        await callback_query.answer()
        
    except Exception as e:
        logging.error(f"Error processing payment verification: {e}", exc_info=True)
        await callback_query.answer("❌ Произошла ошибка при обработке платежа")

async def check_expired_subscriptions():
    """Проверка и деактивация истекших подписок"""
    while True:
        try:
            logging.info("Checking for expired subscriptions...")
            
            # Получаем истекшие подписки
            expired_subscriptions = db.get_expired_subscriptions()
            
            for sub in expired_subscriptions:
                try:
                    client_name = f"user_{sub['user_id']}"
                    
                    # Добавляем повторные попытки отключения
                    max_retries = 3
                    for attempt in range(max_retries):
                        try:
                            # Получаем актуальный список клиентов
                            clients = await wg_api.get_clients()
                            existing_client = None
                            for client in clients:
                                if client['name'] == client_name:
                                    existing_client = client
                                    break
                            
                            if existing_client:
                                client = existing_client
                                logging.info(f"Using existing client: {json.dumps(client, indent=2)}")
                            else:
                                # Если клиент не найден (был удален), создаем нового
                                client = await wg_api.create_client(client_name)
                                logging.info(f"Created new client: {json.dumps(client, indent=2)}")
                            
                            # Проверяем текущий статус
                            if client.get('enabled', False):
                                # Отключаем клиента
                                response = await wg_api.update_client(client_name, enable=False)
                                logging.info(f"WireGuard API response: {response}")
                                if response:  # проверяем успешность отключения
                                    logging.info(f"Successfully disabled WireGuard client {client_name} on attempt {attempt + 1}")
                                    break
                            else:
                                logging.info(f"Client {client_name} is already disabled")
                                break
                        
                        except Exception as e:
                            if attempt < max_retries - 1:
                                logging.error(f"Error disabling client on attempt {attempt + 1}: {e}")
                                await asyncio.sleep(1)  # пауза перед следующей попыткой
                            else:
                                logging.error(f"Failed to disable client after {max_retries} attempts: {e}")
                    
                    # Деактивируем подписку в базе
                    db.deactivate_subscription(sub['user_id'])
                    logging.info(f"Deactivated subscription in database for user {sub['user_id']}")
                    
                    # Удаляем файлы конфигурации
                    config_manager.cleanup_old_configs(sub['user_id'])
                    
                    # Отправляем уведомление только если оно еще не было отправлено
                    if not notification_sent.get(sub['user_id'], {}).get('expired'):
                        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
                            [types.InlineKeyboardButton(text="Продлить подписку", callback_data="buy")]
                        ])
                        
                        await bot.send_message(
                            sub['user_id'],
                            "❌ Ваша подписка истекла!\n"
                            "Для продолжения использования VPN необходимо продлить подписку.",
                            reply_markup=keyboard
                        )
                        notification_sent[sub['user_id']] = {'expired': True}
                        logging.info(f"- Отправлено уведомление об истечении подписки пользователю {sub['user_id']}")
                    
                except Exception as e:
                    logging.error(f"Error processing expired subscription {sub['id']}: {e}")
                    continue
            
        except Exception as e:
            logging.error(f"Error checking expired subscriptions: {e}")
        
        await asyncio.sleep(60)  # проверяем каждую минуту

async def check_subscriptions():
    """Проверка подписок и отправка уведомлений"""
    global notification_sent
    
    # Флаг для отслеживания запущенной задачи
    if hasattr(check_subscriptions, 'is_running') and check_subscriptions.is_running:
        logging.warning("check_subscriptions уже запущен, пропускаем новый запуск")
        return
        
    check_subscriptions.is_running = True
    logging.info("=== Запуск процесса проверки подписок ===")
    
    CHECK_INTERVAL = 3600  # Проверка каждый час
    
    while True:
        try:
            current_time = datetime.now()
            logging.info(f"=== Новый цикл проверки подписок: {current_time} ===")
            
            # Получаем все активные подписки и клиентов WireGuard
            active_subscriptions = db.get_active_subscriptions()
            clients = await wg_api.get_clients()
            logging.info(f"Найдено активных подписок: {len(active_subscriptions)}")
            
            for sub in active_subscriptions:
                try:
                    user_id = sub['user_id']
                    expiration = datetime.strptime(str(sub['expiration']).split('.')[0], '%Y-%m-%d %H:%M:%S')
                    time_left = expiration - current_time
                    hours_left = time_left.total_seconds() / 3600
                    
                    # Если подписка истекла
                    if time_left.total_seconds() <= 0:
                        await handle_expired_subscription(user_id, sub, clients)
                        continue
                    
                    # Отправляем уведомление только за 24 часа до истечения
                    # и только если оно еще не было отправлено
                    if 23 <= hours_left <= 24 and not notification_sent.get(user_id, {}).get('24h_warning'):
                        await send_warning_notification(user_id, time_left, "24 часа")
                        if user_id not in notification_sent:
                            notification_sent[user_id] = {}
                        notification_sent[user_id]['24h_warning'] = True
                        logging.info(f"Отправлено уведомление за 24 часа пользователю {user_id}")
                    
                except Exception as e:
                    logging.error(f"Ошибка при обработке подписки пользователя {user_id}: {e}")
                    continue
            
            # Ждем следующей проверки
            await asyncio.sleep(CHECK_INTERVAL)
            
        except Exception as e:
            logging.error(f"Ошибка в check_subscriptions: {e}")
            await asyncio.sleep(CHECK_INTERVAL)

async def handle_expired_subscription(user_id: int, sub: dict, clients: list):
    """Обработка истекшей подписки"""
    try:
        client_name = f"user_{user_id}"
        logging.info(f">>> Обработка истекшей подписки для {user_id}")
        
        # Принудительное отключение с повторными попытками
        max_retries = 3
        for attempt in range(max_retries):
            try:
                client_found = False
                for client in clients:
                    if client['name'] == client_name:
                        client_found = True
                        if client.get('enabled', False):
                            response = await wg_api.update_client(client_name, enable=False)
                            logging.info(f"WireGuard API response: {response}")
                            if response:
                                logging.info(f"Successfully disabled WireGuard client {client_name}")
                                break
                        else:
                            logging.info(f"Client {client_name} is already disabled")
                            break
                
                if not client_found:
                    logging.warning(f"Client {client_name} not found in WireGuard")
                break
                
            except Exception as e:
                if attempt < max_retries - 1:
                    logging.error(f"Error disabling client on attempt {attempt + 1}: {e}")
                    await asyncio.sleep(1)
                else:
                    logging.error(f"Failed to disable client after {max_retries} attempts: {e}")
        
        # Деактивируем подписку в базе
        db.deactivate_subscription(user_id)
        logging.info(f"- Деактивирована подписка в базе для пользователя {user_id}")
        
        # Удаляем файлы конфигурации
        config_manager.cleanup_old_configs(user_id)
        
        # Отправляем уведомление об отключении только если оно еще не было отправлено
        if not notification_sent.get(user_id, {}).get('expired'):
            keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="Продлить подписку", callback_data="buy")]
            ])
            
            await bot.send_message(
                user_id,
                "❌ Ваша подписка истекла!\n"
                "Для продолжения использования VPN необходимо продлить подписку.",
                reply_markup=keyboard
            )
            if user_id not in notification_sent:
                notification_sent[user_id] = {}
            notification_sent[user_id]['expired'] = True
            logging.info(f"- Отправлено уведомление об истечении подписки пользователю {user_id}")
            
    except Exception as e:
        logging.error(f"Ошибка при обработке истекшей подписки для {user_id}: {e}")

async def send_warning_notification(user_id: int, time_left: timedelta, time_text: str):
    """Отправка предупреждения о скором истечении подписки"""
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Продлить подписку", callback_data="extend_subscription")]
    ])
    
    await bot.send_message(
        user_id,
        f"⚠️ Внимание! Ваша подписка VPN истекает через {time_text}!\n\n"
        "Рекомендуем продлить подписку заранее, чтобы избежать отключения.",
        reply_markup=keyboard
    )
    logging.info(f"Отправлено предупреждение пользователю {user_id} об истечении через {time_text}")

def update_notification_status(user_id: int, notification_key: str):
    """Обновление статуса отправленных уведомлений"""
    global notification_sent
    if user_id not in notification_sent:
        notification_sent[user_id] = {}
    notification_sent[user_id][notification_key] = True

async def process_subscription_extension(callback_query: types.CallbackQuery):
    """Обработка продления подписки"""
    # Получаем текущую подписку
    subscription = db.get_subscription(callback_query.from_user.id)
    
    if not subscription:
        await callback_query.message.answer(
            "❌ У вас нет активной подписки.\n"
            "Используйте /start для покупки новой подписки."
        )
        return
    
    # Показываем тарифы для продления
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text=f"26 часов - {PRICE_26_HOURS}₽", callback_data="sub_26h")],
            [types.InlineKeyboardButton(text=f"1 неделя - {PRICE_1_WEEK}₽", callback_data="sub_week")],
            [
                types.InlineKeyboardButton(text=f"1 месяц - {PRICE_1_MONTH}₽", callback_data="sub_1"),
                types.InlineKeyboardButton(text=f"3 месяца - {PRICE_3_MONTHS}₽", callback_data="sub_3")
            ],
            [
                types.InlineKeyboardButton(text=f"6 месяцев - {PRICE_6_MONTHS}₽", callback_data="sub_6"),
                types.InlineKeyboardButton(text=f"12 месяцев - {PRICE_12_MONTHS}₽", callback_data="sub_12")
            ],
            [types.InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main")]
        ]
    )
    
    await callback_query.message.edit_text(
        "📅 Выберите период продления подписки:",
        reply_markup=keyboard
    )

@dp.message(Command("status"))
async def status_command(message: types.Message):
    """Обработка команды /status"""
    user_id = message.from_user.id
    subscription = db.get_subscription(user_id)
    
    if not subscription:
        await message.answer(
            "❌ У вас нет активной подписки.\n"
            "Используйте /start для покупки подписки."
        )
        return
    
    sub_id, user_id, config_name, expiration_str, created_at, is_active = subscription
    expiration_time = datetime.strptime(expiration_str.split('.')[0], '%Y-%m-%d %H:%M:%S')
    
    # Проверяем статус подключения в WireGuard
    client = await wg_api.get_client(config_name)
    connection_status = "✅ Подключен" if client and client.get('enabled', False) else "❌ Отключен"
    
    # Создаем клавиатуру для продления
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="Продлить подписку",
                    callback_data="extend_subscription"
                )
            ]
        ]
    )
    
    await message.answer(
        f"📊 Статус вашей подписки:\n\n"
        f"📅 Действует до: {expiration_time.strftime('%d.%m.%Y %H:%M')}\n"
        f"🔌 Статус подключения: {connection_status}\n\n"
        f"Осталось: {(expiration_time - datetime.now()).days} дней",
        reply_markup=keyboard
    )

@dp.message(Command("check_db"))
async def check_database(message: types.Message):
    """Проверка состояния базы данных"""
    if message.from_user.id != ADMIN_USER_ID:
        return
        
    try:
        cursor = db.conn.cursor()
        
        # Проверяем таблицы
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        
        response = "📊 Состояние базы данных:\n\n"
        
        for table in tables:
            table_name = table[0]
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            count = cursor.fetchone()[0]
            response += f"Таблица {table_name}: {count} записей\n"
            
            if table_name == 'subscriptions':
                cursor.execute("""
                    SELECT user_id, expiration, is_active 
                    FROM subscriptions 
                    ORDER BY created_at DESC 
                    LIMIT 5
                """)
                subs = cursor.fetchall()
                if subs:
                    response += "\nПоследние подписки:\n"
                    for sub in subs:
                        response += f"User {sub[0]}: до {sub[1]} (active: {sub[2]})\n"
        
        await message.answer(response)
        
    except Exception as e:
        logging.error(f"Error checking database: {e}")
        await message.answer(f"❌ Ошибка при проверке базы данных: {e}")

async def init_wg_api():
    """Инициализация и проверка подключения к WireGuard API"""
    global wg_api
    
    host = os.getenv('WG_HOST')
    port = os.getenv('WG_API_PORT')
    password = os.getenv('WG_API_PASSWORD')
    
    logging.debug(f"WG API Configuration - Host: {host}, Port: {port}, Password length: {len(password) if password else 0}")
    
    if not all([host, port, password]):
        logging.error("Missing required WireGuard API configuration")
        return False
    
    wg_api = WGEasyAPI(host, port, password)
    
    try:
        # Пробуем выполнить тестовый запрос
        if await wg_api._login():
            logging.info("Successfully connected to WireGuard API")
            return True
        else:
            logging.error("Failed to login to WireGuard API")
            return False
    except Exception as e:
        logging.error(f"Exception during WireGuard API initialization: {str(e)}")
        return False

async def main():
    """Запуск бота"""
    if not ensure_single_instance():
        logging.error("Выход: другой экземпляр бота уже запущен")
        return

    try:
        # Инициализация WireGuard API
        if not await init_wg_api():
            logging.error("Failed to initialize WireGuard API. Exiting...")
            return
            
        # Регистрация хэндлеров команд
        dp.message.register(handle_start, Command("start"))
        dp.message.register(status_command, Command("status"))
        dp.message.register(check_database, Command("check_db"))
        
        # Регистрация хэндлеров состояний
        dp.message.register(process_payment_screenshot, PaymentStates.waiting_for_screenshot)
        
        # Регистрация хэндлеров callback_query
        dp.callback_query.register(show_subscription_menu, lambda c: c.data == "buy")
        dp.callback_query.register(show_subscription_status, lambda c: c.data == "status")
        dp.callback_query.register(show_help, lambda c: c.data == "help")
        dp.callback_query.register(back_to_main_menu, lambda c: c.data == "back_to_main")
        dp.callback_query.register(process_subscription_duration, lambda c: c.data.startswith('sub_') and c.data != 'sub_menu')
        dp.callback_query.register(process_payment_method, lambda c: c.data.startswith('pay_'))
        dp.callback_query.register(process_payment_verification, lambda c: c.data.startswith(("confirm:", "reject:")))
        dp.callback_query.register(process_subscription_extension, lambda c: c.data == "extend_subscription")
        dp.callback_query.register(show_user_data, lambda c: c.data == "my_data")
        dp.callback_query.register(show_connection_data, lambda c: c.data == "show_connection_data")
        
        # Запускаем бота
        await dp.start_polling(bot)
    except Exception as e:
        logging.error(f"Error starting bot: {e}")
        raise

@dp.callback_query(lambda c: c.data == "my_data")
async def show_user_data(callback_query: types.CallbackQuery):
    """Показать данные пользователя для подключения"""
    user_id = callback_query.from_user.id
    
    # Получаем активную подписку пользователя
    subscription = db.get_subscription(user_id)
    if not subscription:
        keyboard = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [types.InlineKeyboardButton(text="💳 Купить подписку", callback_data="buy")],
                [types.InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main")]
            ]
        )
        await callback_query.message.edit_text(
            "❌ У вас нет активной подписки.\n"
            "Для получения данных подключения необходимо приобрести подписку.",
            reply_markup=keyboard
        )
        return

    # Получаем конфигурацию из базы
    config = db.get_client_config(user_id)
    if not config:
        await callback_query.message.edit_text(
            "⚠️ Ошибка: не удалось получить данные подключения.\n"
            "Пожалуйста, обратитесь в поддержку.",
            reply_markup=types.InlineKeyboardMarkup(
                inline_keyboard=[[
                    types.InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main")
                ]]
            )
        )
        return

    # Формируем текст с инструкциями
    message_text = (
        "📱 <b>Данные для подключения</b>\n\n"
        "1️⃣ Установите приложение WireGuard:\n"
        "• <a href='https://apps.apple.com/us/app/wireguard/id1441195209'>iOS</a>\n"
        "• <a href='https://play.google.com/store/apps/details?id=com.wireguard.android'>Android</a>\n"
        "• <a href='https://download.wireguard.com/windows-client/wireguard-installer.exe'>Windows</a>\n\n"
        "2️⃣ Импортируйте конфигурацию одним из способов:\n"
        "• Отсканируйте QR-код\n"
        "• Или скопируйте текст конфигурации в файл .conf"
    )

    # Создаем клавиатуру
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="📋 Показать конфигурацию", callback_data="show_config")],
            [types.InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main")]
        ]
    )

    # Если есть QR-код, отправляем его
    if config.get('qr_code'):
        await callback_query.message.answer_photo(
            photo=types.BufferedInputFile(
                config['qr_code'].encode(),
                filename="config.png"
            ),
            caption=message_text,
            parse_mode="HTML",
            reply_markup=keyboard
        )
        await callback_query.message.delete()
    else:
        # Если QR-кода нет, отправляем только текст
        await callback_query.message.edit_text(
            message_text,
            parse_mode="HTML",
            reply_markup=keyboard
        )

@dp.callback_query(lambda c: c.data == "show_config")
async def show_config(callback_query: types.CallbackQuery):
    """Показать текст конфигурации"""
    user_id = callback_query.from_user.id
    
    # Получаем конфигурацию из базы
    config = db.get_client_config(user_id)
    if not config or 'config' not in config:
        await callback_query.answer("⚠️ Ошибка: конфигурация не найдена")
        return

    # Отправляем конфигурацию в текстовом виде
    await callback_query.message.answer(
        "<code>" + config['config'] + "</code>",
        parse_mode="HTML",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[[
                types.InlineKeyboardButton(text="↩️ Назад", callback_data="show_data")
            ]]
        )
    )
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == "show_connection_data")
async def show_connection_data(callback_query: types.CallbackQuery):
    """Показать данные для подключения"""
    try:
        user_id = callback_query.from_user.id
        
        # Проверяем активную подписку
        subscription = db.get_subscription(user_id)
        if not subscription:
            await callback_query.answer("❌ У вас нет активной подписки")
            return
            
        if not db.check_subscription(user_id):
            await callback_query.answer("❌ Ваша подписка истекла")
            return
        
        # Получаем или создаем клиента
        client_name = f"user_{user_id}"
        try:
            # Сначала проверяем, есть ли сохраненная конфигурация
            client_config = db.get_client_config(user_id)
            if client_config and client_config['config_path'] and client_config['qr_path']:
                logging.info(f"Using saved configuration for user {user_id}")
                config_path = client_config['config_path']
                qr_path = client_config['qr_path']
            else:
                # Если нет сохраненной конфигурации, создаем новую
                clients = await wg_api.get_clients()
                existing_client = None
                for client in clients:
                    if client['name'] == client_name:
                        # Если клиент существует, удаляем его
                        logging.info(f"Removing existing client: {client_name}")
                        await wg_api.remove_client(client['id'])
                        break
                
                # Создаем нового клиента
                client = await wg_api.create_client(client_name)
                logging.info(f"Created new client: {client_name}")
                
                # Генерируем конфигурацию
                config = await wg_api.generate_config(client)
                
                # Сохраняем файлы через ConfigManager
                config_path, qr_path = config_manager.save_config(user_id, config, client_name)
                
                if not config_path or not qr_path:
                    raise Exception("Failed to save configuration files")
                
                # Сохраняем конфигурацию в базу данных
                db.save_client_config(user_id, {
                    'private_key': client['privateKey'],
                    'public_key': client['publicKey'],
                    'pre_shared_key': client['preSharedKey'],
                    'config_path': config_path,
                    'qr_path': qr_path
                })
            
            # Отправляем конфигурацию
            await bot.send_document(
                user_id,
                FSInputFile(config_path),
                caption="📝 Ваш файл конфигурации WireGuard"
            )
            
            await bot.send_photo(
                user_id,
                FSInputFile(qr_path),
                caption="🔐 Ваши данные для подключения"
            )
            
            await callback_query.answer("✅ Данные для подключения отправлены")
            
        except Exception as e:
            logging.error(f"Error generating configuration: {e}")
            await callback_query.answer("❌ Ошибка при генерации конфигурации")
            return
            
    except Exception as e:
        logging.error(f"Error showing connection data: {e}")
        await callback_query.answer("❌ Произошла ошибка")        

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Bot stopped")
    except Exception as e:
        logging.error(f"Fatal error: {e}")
