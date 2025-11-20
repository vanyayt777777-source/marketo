import logging
import sqlite3
import json
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Токен бота
BOT_TOKEN = "8365442818:AAG3d8KdGkzqnMfWExcuTQXoPzGQ2Nxx0oY"
ADMIN_CHAT_ID = 7973988177

# База данных
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('marketplace.db', check_same_thread=False)
        self.create_tables()

    def create_tables(self):
        cursor = self.conn.cursor()
        
        # Пользователи
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE,
                username TEXT,
                nickname TEXT UNIQUE,
                password TEXT,
                balance REAL DEFAULT 0,
                rating REAL DEFAULT 0,
                reviews_count INTEGER DEFAULT 0,
                registered_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Товары
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                seller_id INTEGER,
                game_category TEXT,
                game_name TEXT,
                title TEXT,
                description TEXT,
                price REAL,
                product_data TEXT,
                status TEXT DEFAULT 'moderation',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (seller_id) REFERENCES users (id)
            )
        ''')
        
        # Заказы
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER,
                buyer_id INTEGER,
                seller_id INTEGER,
                status TEXT DEFAULT 'paid',
                confirmed BOOLEAN DEFAULT FALSE,
                reviewed BOOLEAN DEFAULT FALSE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (product_id) REFERENCES products (id),
                FOREIGN KEY (buyer_id) REFERENCES users (id),
                FOREIGN KEY (seller_id) REFERENCES users (id)
            )
        ''')
        
        # Отзывы
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                seller_id INTEGER,
                buyer_id INTEGER,
                rating INTEGER,
                comment TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (order_id) REFERENCES orders (id),
                FOREIGN KEY (seller_id) REFERENCES users (id),
                FOREIGN KEY (buyer_id) REFERENCES users (id)
            )
        ''')
        
        # Пополнения
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS deposits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                method TEXT,
                proof_image TEXT,
                status TEXT DEFAULT 'pending',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        self.conn.commit()

    def get_user(self, telegram_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,))
        return cursor.fetchone()

    def get_user_by_id(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
        return cursor.fetchone()

    def register_user(self, telegram_id, username, nickname, password):
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                'INSERT INTO users (telegram_id, username, nickname, password) VALUES (?, ?, ?, ?)',
                (telegram_id, username, nickname, password)
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def login_user(self, nickname, password):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM users WHERE nickname = ? AND password = ?', (nickname, password))
        return cursor.fetchone()

    def update_balance(self, user_id, amount):
        cursor = self.conn.cursor()
        cursor.execute('UPDATE users SET balance = balance + ? WHERE id = ?', (amount, user_id))
        self.conn.commit()

    def get_balance(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT balance FROM users WHERE id = ?', (user_id,))
        result = cursor.fetchone()
        return result[0] if result else 0

    def add_product(self, seller_id, game_category, game_name, title, description, price, product_data):
        cursor = self.conn.cursor()
        cursor.execute(
            '''INSERT INTO products (seller_id, game_category, game_name, title, description, price, product_data) 
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (seller_id, game_category, game_name, title, description, price, product_data)
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_product(self, product_id):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT p.*, u.nickname, u.username, u.rating 
            FROM products p 
            JOIN users u ON p.seller_id = u.id 
            WHERE p.id = ?
        ''', (product_id,))
        return cursor.fetchone()

    def get_products(self, status='active'):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT p.*, u.nickname, u.username, u.rating 
            FROM products p 
            JOIN users u ON p.seller_id = u.id 
            WHERE p.status = ?
        ''', (status,))
        return cursor.fetchall()

    def create_order(self, product_id, buyer_id, seller_id):
        cursor = self.conn.cursor()
        cursor.execute(
            'INSERT INTO orders (product_id, buyer_id, seller_id) VALUES (?, ?, ?)',
            (product_id, buyer_id, seller_id)
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_order(self, order_id):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT o.*, p.title, p.product_data, u.nickname as seller_nickname
            FROM orders o
            JOIN products p ON o.product_id = p.id
            JOIN users u ON o.seller_id = u.id
            WHERE o.id = ?
        ''', (order_id,))
        return cursor.fetchone()

    def get_user_orders(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT o.*, p.title, p.game_name
            FROM orders o
            JOIN products p ON o.product_id = p.id
            WHERE o.buyer_id = ? AND o.status = 'paid'
        ''', (user_id,))
        return cursor.fetchall()

    def confirm_order(self, order_id):
        cursor = self.conn.cursor()
        cursor.execute('UPDATE orders SET confirmed = TRUE WHERE id = ?', (order_id,))
        
        # Получаем информацию о заказе для выплаты продавцу
        order = self.get_order(order_id)
        if order:
            product_price = self.get_product(order[1])[6]  # price
            commission = product_price * 0.05  # 5% комиссия
            seller_amount = product_price - commission
            
            # Выплачиваем продавцу
            cursor.execute('UPDATE users SET balance = balance + ? WHERE id = ?', 
                         (seller_amount, order[3]))
        
        self.conn.commit()

    def add_review(self, order_id, seller_id, buyer_id, rating, comment):
        cursor = self.conn.cursor()
        cursor.execute(
            'INSERT INTO reviews (order_id, seller_id, buyer_id, rating, comment) VALUES (?, ?, ?, ?, ?)',
            (order_id, seller_id, buyer_id, rating, comment)
        )
        
        # Обновляем рейтинг продавца
        cursor.execute('''
            UPDATE users 
            SET rating = (SELECT AVG(rating) FROM reviews WHERE seller_id = ?),
                reviews_count = (SELECT COUNT(*) FROM reviews WHERE seller_id = ?)
            WHERE id = ?
        ''', (seller_id, seller_id, seller_id))
        
        cursor.execute('UPDATE orders SET reviewed = TRUE WHERE id = ?', (order_id,))
        self.conn.commit()

db = Database()

# Списки игр и приложений
GAMES = {
    "Ролевые игры и MMORPG": [
        "Genshin Impact (HoYoverse Account)",
        "Honkai: Star Rail (HoYoverse Account)", 
        "Tower of Fantasy (Учетная запись Level Infinite)",
        "Diablo Immortal (Battle.net Account)",
        "Black Desert Mobile (Pearl Abyss Account)",
        "RuneScape (Jagex Account)",
        "Old School RuneScape (Jagex Account)",
        "Villagers & Heroes (Учетная запись Mad Otter Games)"
    ],
    "Шутеры и Экшн": [
        "Call of Duty: Mobile (Activision Account)",
        "PUBG Mobile (Учетная запись Krafton или социальные сети)",
        "Warframe (Учетная запись Digital Extremes)",
        "War Thunder (Учетная запись Gaijin)",
        "World of Tanks Blitz (Учетная запись Wargaming)", 
        "Apex Legends Mobile (EA Account)",
        "Standoff 2 (Аккаунт в социальных сетях)"
    ],
    "Песочницы и Платформы": [
        "Minecraft (Учетная запись Microsoft/Xbox)",
        "Roblox (Учетная запись Roblox)"
    ],
    "Другие популярные игры": [
        "Fortnite (Учетная запись Epic Games)",
        "Brawlhalla (Учетная запись Ubisoft)",
        "Clash of Clans (Supercell ID)",
        "Clash Royale (Supercell ID)", 
        "Brawl Stars (Supercell ID)",
        "Asphalt 9: Legends (Ubisoft Connect / Gameloft Account)",
        "Hearthstone (Battle.net Account)",
        "Legends of Runeterra (Riot Games Account)",
        "Black Russia"
    ]
}

APPS = {
    "Социальные сети и коммуникации": [
        "Telegram", "Discord", "VK (ВКонтакте)", 
        "WhatsApp (синхронизация через QR-код)", "Skype (Microsoft Account)"
    ],
    "Медиа и развлечения": [
        "YouTube (Аккаунт Google)", "Spotify", "Twitch (Аккаунт Amazon)",
        "Кинопоиск (Аккаунт Яндекс)", "Netflix", "IVI", "More.tv"
    ],
    "Офисные и облачные сервисы": [
        "WPS Office (Cloud Account)", "Google Документы/Таблицы/Презентации (Аккаунт Google)",
        "Microsoft Word, Excel, PowerPoint (Аккаунт Microsoft 365)", "Google Drive (Аккаунт Google)",
        "Яндекс.Диск (Аккаунт Яндекс)", "Dropbox", "Evernote", "Notion"
    ],
    "Фото и графика": [
        "Canva", "Adobe Creative Cloud (Express)", "PicsArt"
    ],
    "Финансы и банкинг": [
        "СберБанк Онлайн", "Тинькофф", "ВТБ", "Альфа-Банк", "Госуслуги"
    ]
}

# Состояния пользователей
user_states = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    telegram_id = user.id
    
    # Проверяем, зарегистрирован ли пользователь
    user_data = db.get_user(telegram_id)
    
    if user_data:
        # Пользователь зарегистрирован - показываем главное меню
        await show_main_menu(update, context)
    else:
        # Пользователь не зарегистрирован - предлагаем регистрацию/вход
        keyboard = [
            [InlineKeyboardButton("📝 Зарегистрироваться", callback_data="register")],
            [InlineKeyboardButton("🔐 Войти", callback_data="login")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"👋 Привет, {user.first_name}!\n\n"
            "Добро пожаловать в маркетплейс игровых товаров! "
            "Для начала работы необходимо зарегистрироваться или войти в аккаунт.",
            reply_markup=reply_markup
        )

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [KeyboardButton("🛒 Купить товар"), KeyboardButton("💰 Продать товар")],
        [KeyboardButton("👤 Профиль"), KeyboardButton("💳 Пополнить баланс")],
        [KeyboardButton("💸 Вывод средств"), KeyboardButton("📦 Мои заказы")],
        [KeyboardButton("📊 Помощь")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    if update.callback_query:
        await update.callback_query.message.reply_text(
            "🏠 Главное меню:",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            "🏠 Главное меню:",
            reply_markup=reply_markup
        )

# Обработчики кнопок
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_text = update.message.text
    user_id = update.effective_user.id
    
    if message_text == "🛒 Купить товар":
        await show_categories(update, context)
    elif message_text == "💰 Продать товар":
        await start_selling(update, context)
    elif message_text == "👤 Профиль":
        await show_profile(update, context)
    elif message_text == "💳 Пополнить баланс":
        await show_deposit_methods(update, context)
    elif message_text == "💸 Вывод средств":
        await show_withdraw(update, context)
    elif message_text == "📦 Мои заказы":
        await show_my_orders(update, context)
    elif message_text == "📊 Помощь":
        await show_help(update, context)
    else:
        # Если это не команда меню, проверяем, не ожидаем ли мы ввода данных
        await handle_text_input(update, context)

async def show_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "💸 Вывод средств\n\n"
        "Для вывода обращаться к @nezeexmoney\n\n"
        "Вывод от 50₽"
    )
    
    await update.message.reply_text(text)

async def show_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🎮 Игры", callback_data="category_games")],
        [InlineKeyboardButton("📱 Приложения", callback_data="category_apps")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "📂 Выберите категорию:",
        reply_markup=reply_markup
    )

async def show_games_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = []
    for category in GAMES.keys():
        keyboard.append([InlineKeyboardButton(category, callback_data=f"games_{category}")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_categories")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    query = update.callback_query
    await query.edit_message_text(
        "🎮 Выберите категорию игр:",
        reply_markup=reply_markup
    )

async def show_apps_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = []
    for category in APPS.keys():
        keyboard.append([InlineKeyboardButton(category, callback_data=f"apps_{category}")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_categories")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    query = update.callback_query
    await query.edit_message_text(
        "📱 Выберите категорию приложений:",
        reply_markup=reply_markup
    )

async def show_games_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    category = query.data.replace("games_", "")
    
    games = GAMES.get(category, [])
    keyboard = []
    
    for game in games:
        keyboard.append([InlineKeyboardButton(game, callback_data=f"game_{game}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="category_games")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"🎮 {category} - выберите игру:",
        reply_markup=reply_markup
    )

async def show_apps_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    category = query.data.replace("apps_", "")
    
    apps = APPS.get(category, [])
    keyboard = []
    
    for app in apps:
        keyboard.append([InlineKeyboardButton(app, callback_data=f"app_{app}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="category_apps")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"📱 {category} - выберите приложение:",
        reply_markup=reply_markup
    )

async def show_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    game_name = query.data.replace("game_", "").replace("app_", "")
    
    products = db.get_products('active')
    filtered_products = [p for p in products if p[3] == game_name]  # p[3] - game_name
    
    if not filtered_products:
        await query.edit_message_text(
            f"😔 Товары для '{game_name}' не найдены.\n"
            "Попробуйте выбрать другую игру или приложение.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_to_categories")]])
        )
        return
    
    # Показываем первый товар
    context.user_data['current_product_index'] = 0
    context.user_data['filtered_products'] = filtered_products
    await show_product_details(update, context)

async def show_product_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    filtered_products = context.user_data.get('filtered_products', [])
    current_index = context.user_data.get('current_product_index', 0)
    
    if not filtered_products or current_index >= len(filtered_products):
        await query.edit_message_text("Товары не найдены.")
        return
    
    product = filtered_products[current_index]
    
    text = (
        f"🛒 Товар: {product[4]}\n"  # title
        f"🎮 Игра: {product[3]}\n"  # game_name
        f"📝 Описание: {product[5]}\n"  # description
        f"💰 Цена: {product[6]}₽\n"  # price
        f"👤 Продавец: {product[9]}\n"  # nickname
        f"⭐ Рейтинг продавца: {product[11] or 'Нет отзывов'}\n"
        f"📞 Контакт: @{product[10] or 'Не указан'}"
    )
    
    keyboard = []
    if current_index > 0:
        keyboard.append(InlineKeyboardButton("⬅️ Предыдущий", callback_data="prev_product"))
    
    keyboard.append(InlineKeyboardButton("💰 Купить", callback_data=f"buy_{product[0]}"))
    
    if current_index < len(filtered_products) - 1:
        keyboard.append(InlineKeyboardButton("Следующий ➡️", callback_data="next_product"))
    
    reply_markup = InlineKeyboardMarkup([keyboard])
    
    if query:
        await query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)

async def handle_buy_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    product_id = int(query.data.replace("buy_", ""))
    
    user_id = update.effective_user.id
    user_data = db.get_user(user_id)
    
    if not user_data:
        await query.answer("❌ Сначала необходимо войти в аккаунт.", show_alert=True)
        return
    
    product = db.get_product(product_id)
    if not product:
        await query.answer("❌ Товар не найден.", show_alert=True)
        return
    
    user_balance = db.get_balance(user_data[0])
    product_price = product[6]
    
    if user_balance < product_price:
        await query.answer(f"❌ Недостаточно средств. Ваш баланс: {user_balance}₽", show_alert=True)
        return
    
    # Создаем заказ
    order_id = db.create_order(product_id, user_data[0], product[1])
    
    # Списываем средства
    db.update_balance(user_data[0], -product_price)
    
    # Получаем обновленные данные
    product = db.get_product(product_id)
    
    # Отправляем данные товара покупателю
    await query.edit_message_text(
        f"✅ Покупка успешна!\n\n"
        f"🛒 Товар: {product[4]}\n"
        f"💰 Цена: {product[6]}₽\n"
        f"👤 Продавец: @{product[10] or 'Не указан'}\n\n"
        f"📦 Данные товара:\n"
        f"```\n{product[7]}\n```\n\n"
        f"⚠️ После получения товара не забудьте подтвердить заказ!",
        parse_mode=ParseMode.MARKDOWN
    )
    
    # Уведомляем продавца
    seller = db.get_user_by_id(product[1])
    if seller and seller[1]:  # seller[1] - telegram_id
        try:
            await context.bot.send_message(
                chat_id=seller[1],
                text=f"🎉 Ваш товар купили!\n\n"
                     f"🛒 Товар: {product[4]}\n"
                     f"💰 Цена: {product[6]}₽\n"
                     f"👤 Покупатель: @{update.effective_user.username or 'Не указан'}\n\n"
                     f"💸 Средства будут зачислены после подтверждения получения."
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить продавца: {e}")
    
    # Показываем кнопку для подтверждения заказа
    keyboard = [
        [InlineKeyboardButton("✅ Подтвердить получение", callback_data=f"confirm_{order_id}")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await context.bot.send_message(
        chat_id=user_id,
        text="После получения товара нажмите кнопку ниже:",
        reply_markup=reply_markup
    )

async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    order_id = int(query.data.replace("confirm_", ""))
    
    order = db.get_order(order_id)
    if not order:
        await query.answer("❌ Заказ не найден.", show_alert=True)
        return
    
    db.confirm_order(order_id)
    
    await query.edit_message_text(
        f"✅ Заказ подтвержден!\n\n"
        f"🛒 Товар: {order[8]}\n"
        f"💰 Сумма: {db.get_product(order[1])[6]}₽\n\n"
        f"💸 Средства переведены продавцу (с учетом комиссии 5%)."
    )
    
    # Предлагаем оставить отзыв
    keyboard = [
        [InlineKeyboardButton("⭐ Оставить отзыв", callback_data=f"review_{order_id}")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await context.bot.send_message(
        chat_id=update.effective_user.id,
        text="Хотите оставить отзыв о продавце?",
        reply_markup=reply_markup
    )

async def start_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    order_id = int(query.data.replace("review_", ""))
    
    context.user_data['review_order_id'] = order_id
    context.user_data['awaiting'] = 'review_rating'
    
    keyboard = []
    for i in range(1, 6):
        keyboard.append(InlineKeyboardButton("⭐" * i, callback_data=f"rating_{i}"))
    
    reply_markup = InlineKeyboardMarkup([keyboard])
    
    await query.edit_message_text(
        "⭐ Оценка продавца\n\n"
        "Выберите оценку от 1 до 5 звезд:",
        reply_markup=reply_markup
    )

async def handle_rating(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    rating = int(query.data.replace("rating_", ""))
    
    context.user_data['review_rating'] = rating
    context.user_data['awaiting'] = 'review_comment'
    
    await query.edit_message_text(
        f"⭐ Вы поставили оценку: {rating}/5\n\n"
        "Напишите комментарий к отзыву (или отправьте '-' чтобы пропустить):"
    )

async def handle_review_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    comment = update.message.text
    
    order_id = context.user_data.get('review_order_id')
    rating = context.user_data.get('review_rating')
    
    if not order_id or not rating:
        await update.message.reply_text("❌ Ошибка при создании отзыва.")
        return
    
    order = db.get_order(order_id)
    if not order:
        await update.message.reply_text("❌ Заказ не найден.")
        return
    
    # Добавляем отзыв
    db.add_review(order_id, order[3], user_id, rating, comment if comment != '-' else '')
    
    await update.message.reply_text(
        f"✅ Отзыв добавлен!\n\n"
        f"⭐ Оценка: {rating}/5\n"
        f"📝 Комментарий: {comment if comment != '-' else 'Без комментария'}\n\n"
        f"Спасибо за ваш отзыв!",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🏠 Главное меню")]], resize_keyboard=True)
    )
    
    # Очищаем состояние
    if 'awaiting' in context.user_data:
        del context.user_data['awaiting']
    if 'review_order_id' in context.user_data:
        del context.user_data['review_order_id']
    if 'review_rating' in context.user_data:
        del context.user_data['review_rating']

async def show_my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = db.get_user(user_id)
    
    if not user_data:
        await update.message.reply_text("❌ Сначала необходимо войти в аккаунт.")
        return
    
    orders = db.get_user_orders(user_data[0])
    
    if not orders:
        await update.message.reply_text("📦 У вас нет активных заказов.")
        return
    
    text = "📦 Ваши заказы:\n\n"
    for order in orders:
        status = "✅ Подтвержден" if order[5] else "⏳ Ожидает подтверждения"
        text += f"🛒 {order[8]} ({order[9]})\n"
        text += f"💰 Сумма: {db.get_product(order[1])[6]}₽\n"
        text += f"📊 Статус: {status}\n"
        text += f"📅 Дата: {order[7]}\n\n"
        
        if not order[5]:  # Если не подтвержден
            text += f"🆔 ID заказа: {order[0]}\n\n"
    
    await update.message.reply_text(text)

async def start_selling(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = db.get_user(user_id)
    
    if not user_data:
        await update.message.reply_text("❌ Сначала необходимо войти в аккаунт.")
        return
    
    keyboard = [
        [InlineKeyboardButton("🎮 Игры", callback_data="sell_category_games")],
        [InlineKeyboardButton("📱 Приложения", callback_data="sell_category_apps")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "💰 Продать товар\n\n"
        "Выберите категорию для вашего товара:",
        reply_markup=reply_markup
    )

# Добавляем обработчики для кнопок продажи
async def handle_sell_category_games(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await show_games_categories(update, context)

async def handle_sell_category_apps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await show_apps_categories(update, context)

# Регистрация и авторизация
async def handle_register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.edit_message_text(
        "📝 Регистрация\n\n"
        "Введите ваш никнейм (будет отображаться другим пользователям):"
    )
    context.user_data['awaiting'] = 'register_nickname'

async def handle_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.edit_message_text(
        "🔐 Вход\n\n"
        "Введите ваш никнейм:"
    )
    context.user_data['awaiting'] = 'login_nickname'

async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    awaiting = context.user_data.get('awaiting')
    
    if awaiting == 'register_nickname':
        context.user_data['register_nickname'] = text
        context.user_data['awaiting'] = 'register_password'
        await update.message.reply_text("Введите пароль:")
        
    elif awaiting == 'register_password':
        nickname = context.user_data['register_nickname']
        password = text
        
        success = db.register_user(user_id, update.effective_user.username, nickname, password)
        
        if success:
            await update.message.reply_text(
                "✅ Регистрация успешна!",
                reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🏠 Главное меню")]], resize_keyboard=True)
            )
            # Очищаем состояние
            if 'awaiting' in context.user_data:
                del context.user_data['awaiting']
            if 'register_nickname' in context.user_data:
                del context.user_data['register_nickname']
        else:
            await update.message.reply_text("❌ Этот никнейм уже занят. Попробуйте другой:")
            context.user_data['awaiting'] = 'register_nickname'
            
    elif awaiting == 'login_nickname':
        context.user_data['login_nickname'] = text
        context.user_data['awaiting'] = 'login_password'
        await update.message.reply_text("Введите пароль:")
        
    elif awaiting == 'login_password':
        nickname = context.user_data['login_nickname']
        password = text
        
        user_data = db.login_user(nickname, password)
        
        if user_data:
            await update.message.reply_text(
                "✅ Вход выполнен успешно!",
                reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🏠 Главное меню")]], resize_keyboard=True)
            )
            # Очищаем состояние
            if 'awaiting' in context.user_data:
                del context.user_data['awaiting']
            if 'login_nickname' in context.user_data:
                del context.user_data['login_nickname']
        else:
            await update.message.reply_text("❌ Неверный никнейм или пароль. Попробуйте снова:")
            context.user_data['awaiting'] = 'login_nickname'
    
    elif awaiting == 'review_comment':
        await handle_review_comment(update, context)

async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = db.get_user(user_id)
    
    if not user_data:
        await update.message.reply_text("❌ Сначала необходимо войти в аккаунт.")
        return
    
    text = (
        f"👤 Профиль\n\n"
        f"📛 Никнейм: {user_data[3]}\n"
        f"💼 Баланс: {user_data[5]}₽\n"
        f"⭐ Рейтинг: {user_data[6] or 'Нет отзывов'}\n"
        f"📊 Отзывов: {user_data[7]}\n"
        f"📅 Регистрация: {user_data[8]}"
    )
    
    await update.message.reply_text(text)

async def show_deposit_methods(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("💎 USDT/TON", callback_data="deposit_crypto")],
        [InlineKeyboardButton("💳 РУБЛИ", callback_data="deposit_rub")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "💳 Пополнение баланса\n\n"
        "Выберите способ пополнения:",
        reply_markup=reply_markup
    )

async def show_deposit_crypto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    text = (
        "💎 Пополнение USDT/TON\n\n"
        "Отправьте сумму пополнения на данный кошелёк по актуальному курсу:\n\n"
        "💰 Курс:\n"
        "1 USDT ≈ 90₽\n"
        "1 TON ≈ 180₽\n\n"
        "🔗 Кошелёк:\n"
        "`UQBKvuF_9yERbdNPJ7e8Mu4fwx9HGuI_nSBwRLLrm8PiJFap`\n\n"
        "После отправки пришлите скриншот подтверждения."
    )
    
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)

async def show_deposit_rub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    text = (
        "💳 Пополнение РУБЛЯМИ\n\n"
        "Отправьте сумму пополнения по этим данным:\n\n"
        "📱 СБП: +79818376180\n"
        "💳 КАРТА: 2204120132703386\n\n"
        "После отправки пришлите скриншот подтверждения."
    )
    
    await query.edit_message_text(text)

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📊 Помощь\n\n"
        "Как купить товар?\n"
        "1. Нажмите '🛒 Купить товар'\n"
        "2. Выберите категорию и игру\n"
        "3. Выберите товар и нажмите 'Купить'\n"
        "4. Подтвердите оплату\n"
        "5. Получите данные товара\n"
        "6. Подтвердите получение\n\n"
        
        "Как продать товар?\n"
        "1. Нажмите '💰 Продать товар'\n"
        "2. Выберите категорию и игру\n"
        "3. Заполните информацию о товаре\n"
        "4. Дождитесь модерации\n\n"
        
        "Как пополнить баланс?\n"
        "1. Нажмите '💳 Пополнить баланс'\n"
        "2. Выберите способ оплаты\n"
        "3. Следуйте инструкциям\n\n"
        
        "Техническая поддержка: @nezeexsupp"
    )
    
    await update.message.reply_text(text)

# Обработчик callback запросов
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    
    if data == "register":
        await handle_register(update, context)
    elif data == "login":
        await handle_login(update, context)
    elif data == "main_menu":
        await show_main_menu(update, context)
    elif data == "category_games":
        await show_games_categories(update, context)
    elif data == "category_apps":
        await show_apps_categories(update, context)
    elif data.startswith("games_"):
        await show_games_list(update, context)
    elif data.startswith("apps_"):
        await show_apps_list(update, context)
    elif data.startswith("game_") or data.startswith("app_"):
        await show_products(update, context)
    elif data == "back_to_categories":
        await show_categories_from_callback(update, context)
    elif data == "deposit_crypto":
        await show_deposit_crypto(update, context)
    elif data == "deposit_rub":
        await show_deposit_rub(update, context)
    elif data == "prev_product":
        context.user_data['current_product_index'] -= 1
        await show_product_details(update, context)
    elif data == "next_product":
        context.user_data['current_product_index'] += 1
        await show_product_details(update, context)
    elif data.startswith("buy_"):
        await handle_buy_product(update, context)
    elif data.startswith("confirm_"):
        await confirm_order(update, context)
    elif data.startswith("review_"):
        await start_review(update, context)
    elif data.startswith("rating_"):
        await handle_rating(update, context)
    elif data == "sell_category_games":
        await handle_sell_category_games(update, context)
    elif data == "sell_category_apps":
        await handle_sell_category_apps(update, context)

async def show_categories_from_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🎮 Игры", callback_data="category_games")],
        [InlineKeyboardButton("📱 Приложения", callback_data="category_apps")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    query = update.callback_query
    await query.edit_message_text(
        "📂 Выберите категорию:",
        reply_markup=reply_markup
    )

# Админ панель
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("❌ Доступ запрещен.")
        return
    
    keyboard = [
        [InlineKeyboardButton("💰 Изменить баланс", callback_data="admin_balance")],
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🛒 Модерация товаров", callback_data="admin_moderation")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text("👨‍💻 Админ панель:", reply_markup=reply_markup)

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_panel))
    
    # Обработчики сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Обработчики callback запросов
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    # Запуск бота
    application.run_polling()
    print("Бот запущен!")

if __name__ == "__main__":
    main()
