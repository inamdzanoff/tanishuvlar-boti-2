import os
import logging
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, CallbackQueryHandler

# Logging sozlamalari
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===== SOZLAMALAR =====
BOT_TOKEN = os.environ.get("BOT_TOKEN", "7846797998:AAEO1vuFnkHKM1rpk6EETlvc87Qx_JoH47U")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:password@localhost:5432/tanishuvlar_bot")

# Conversation states
REGISTER_NAME, REGISTER_AGE, REGISTER_GENDER, REGISTER_REGION = range(4)
BROADCAST_PHOTO, BROADCAST_CAPTION = range(4, 6)

# Viloyatlar ro'yxati
REGIONS = [
    "Toshkent", "Samarqand", "Buxoro", "Andijon", "Farg'ona",
    "Namangan", "Qashqadaryo", "Surxondaryo", "Xorazm", "Navoiy",
    "Jizzax", "Sirdaryo", "Qoraqalpog'iston"
]

# Premium narxlari (so'mda)
PREMIUM_PRICES = {
    "1_day": 3000,
    "3_days": 7000,
    "1_week": 15000,
    "1_month": 55000
}

# Referral yulduzlar bilan premium narxlari
STAR_PRICES = {
    "1_day": 10,
    "1_week": 30,
    "1_month": 60
}

# ===== DATABASE FUNKSIYALARI =====
def get_db_connection():
    """PostgreSQL database ulanishini olish"""
    conn = psycopg2.connect(DATABASE_URL)
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn

def init_database():
    """Databaseni yaratish"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Users jadvali
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT UNIQUE NOT NULL,
            username TEXT,
            full_name TEXT NOT NULL,
            age INTEGER NOT NULL,
            gender TEXT NOT NULL,
            region TEXT NOT NULL,
            is_searching INTEGER DEFAULT 0,
            current_partner_id INTEGER,
            is_premium INTEGER DEFAULT 0,
            premium_expires_at TIMESTAMP,
            stars INTEGER DEFAULT 0,
            referral_code TEXT UNIQUE,
            referred_by INTEGER,
            referral_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Chat sessions jadvali
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id SERIAL PRIMARY KEY,
            user1_id INTEGER NOT NULL,
            user2_id INTEGER NOT NULL,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ended_at TIMESTAMP,
            ended_by INTEGER,
            FOREIGN KEY (user1_id) REFERENCES users(id),
            FOREIGN KEY (user2_id) REFERENCES users(id)
        )
    ''')
    
    # Payments jadvali
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            plan TEXT NOT NULL,
            amount INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            screenshot_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    # Bot settings jadvali
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bot_settings (
            id SERIAL PRIMARY KEY,
            card_number TEXT DEFAULT '9860 0121 1489 8153',
            card_holder_name TEXT DEFAULT 'Admin',
            price_1_day INTEGER DEFAULT 3000,
            price_3_days INTEGER DEFAULT 7000,
            price_1_week INTEGER DEFAULT 15000,
            price_1_month INTEGER DEFAULT 55000
        )
    ''')
    
    # Default settings qo'shish
    cursor.execute('SELECT COUNT(*) FROM bot_settings')
    count = cursor.fetchone()[0]
    if count == 0:
        cursor.execute('''
            INSERT INTO bot_settings (card_number, card_holder_name)
            VALUES (%s, %s)
        ''', ('9860 0121 1489 8153', 'Sarvarbek Inomjonov'))
    
    conn.commit()
    conn.close()
    logger.info("PostgreSQL database initialized successfully")

def generate_referral_code(telegram_id: int) -> str:
    """Foydalanuvchi uchun referral kod yaratish"""
    import hashlib
    hash_object = hashlib.md5(str(telegram_id).encode())
    return hash_object.hexdigest()[:8].upper()

def get_user(telegram_id: int):
    """Foydalanuvchini bazadan olish"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE telegram_id = %s', (telegram_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_user_by_id(user_id: int):
    """Foydalanuvchini ID bo'yicha olish"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE id = %s', (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_user_by_referral_code(referral_code: str):
    """Foydalanuvchini referral kod bo'yicha olish"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE referral_code = %s', (referral_code.upper(),))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def create_user(telegram_id: int, username: str, full_name: str, age: int, gender: str, region: str, referred_by: int = None):
    """Yangi foydalanuvchi yaratish"""
    conn = get_db_connection()
    cursor = conn.cursor()
    referral_code = generate_referral_code(telegram_id)
    cursor.execute('''
        INSERT INTO users (telegram_id, username, full_name, age, gender, region, referral_code, referred_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ''', (telegram_id, username, full_name, age, gender, region, referral_code, referred_by))
    conn.commit()
    conn.close()

def update_user(user_id: int, **kwargs):
    """Foydalanuvchini yangilash"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    set_clause = ', '.join([f'{key} = %s' for key in kwargs.keys()])
    values = list(kwargs.values()) + [user_id]
    
    cursor.execute(f'UPDATE users SET {set_clause} WHERE id = %s', values)
    conn.commit()
    conn.close()

def add_stars(user_id: int, stars: int):
    """Foydalanuvchiga yulduz qo'shish"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET stars = stars + %s WHERE id = %s', (stars, user_id))
    conn.commit()
    conn.close()

def use_stars(user_id: int, stars: int) -> bool:
    """Foydalanuvchidan yulduz ayirish"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT stars FROM users WHERE id = %s', (user_id,))
    row = cursor.fetchone()
    if row and row[0] >= stars:
        cursor.execute('UPDATE users SET stars = stars - %s WHERE id = %s', (stars, user_id))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False

def increment_referral_count(user_id: int):
    """Referral hisoblagichini oshirish"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET referral_count = referral_count + 1 WHERE id = %s', (user_id,))
    conn.commit()
    conn.close()

def get_bot_settings():
    """Bot sozlamalarini olish"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM bot_settings LIMIT 1')
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def find_searching_user(exclude_user_id: int, gender: str = None):
    """Qidirayotgan foydalanuvchini topish"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if gender:
        cursor.execute('''
            SELECT * FROM users 
            WHERE is_searching = 1 AND id != %s AND gender = %s
            LIMIT 1
        ''', (exclude_user_id, gender))
    else:
        cursor.execute('''
            SELECT * FROM users 
            WHERE is_searching = 1 AND id != %s
            LIMIT 1
        ''', (exclude_user_id,))
    
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def create_chat_session(user1_id: int, user2_id: int):
    """Chat sessiyasini yaratish"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO chat_sessions (user1_id, user2_id)
        VALUES (%s, %s)
    ''', (user1_id, user2_id))
    conn.commit()
    conn.close()

def end_chat_session(user1_id: int, user2_id: int, ended_by: int):
    """Chat sessiyasini tugatish"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE chat_sessions 
        SET ended_at = CURRENT_TIMESTAMP, ended_by = %s
        WHERE ((user1_id = %s AND user2_id = %s) OR (user1_id = %s AND user2_id = %s))
        AND ended_at IS NULL
    ''', (ended_by, user1_id, user2_id, user2_id, user1_id))
    conn.commit()
    conn.close()

def create_payment(user_id: int, plan: str, amount: int):
    """To'lov yaratish"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO payments (user_id, plan, amount)
        VALUES (%s, %s, %s)
        RETURNING id
    ''', (user_id, plan, amount))
    payment_id = cursor.fetchone()[0]
    conn.commit()
    conn.close()
    return payment_id

def get_pending_payment(user_id: int):
    """Kutilayotgan to'lovni olish"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM payments 
        WHERE user_id = %s AND status = 'pending'
        ORDER BY created_at DESC
        LIMIT 1
    ''', (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def update_payment(payment_id: int, **kwargs):
    """To'lovni yangilash"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    set_clause = ', '.join([f'{key} = %s' for key in kwargs.keys()])
    values = list(kwargs.values()) + [payment_id]
    
    cursor.execute(f'UPDATE payments SET {set_clause} WHERE id = %s', values)
    conn.commit()
    conn.close()

def check_expired_premiums():
    """Muddati o'tgan premiumlarni tekshirish va o'chirish"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE users 
        SET is_premium = 0, premium_expires_at = NULL
        WHERE is_premium = 1 AND premium_expires_at < CURRENT_TIMESTAMP
    ''')
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    if affected > 0:
        logger.info(f"Expired {affected} premium subscriptions")
    return affected

# ===== YORDAMCHI FUNKSIYALAR =====
def is_premium(user: dict) -> bool:
    """Foydalanuvchi premiummi tekshirish"""
    if not user or not user.get("is_premium"):
        return False
    expires = user.get("premium_expires_at")
    if expires:
        try:
            if expires <= datetime.now():
                update_user(user['id'], is_premium=0, premium_expires_at=None)
                return False
            return True
        except Exception:
            return False
    return False

def get_main_keyboard(user: dict):
    """Asosiy klaviatura"""
    premium = is_premium(user)
    
    keyboard = [
        ["🔍 Suhbatdosh izlash"],
        ["👤 Mening profilim", "💎 Premium"],
        ["🌟 Referral"]
    ]
    
    if premium:
        keyboard.insert(1, ["👦 O'g'il izlash", "👧 Qiz izlash"])
    
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ===== BOT HANDLERLARI =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start komandasi"""
    telegram_id = update.effective_user.id
    user = get_user(telegram_id)
    
    referral_code = None
    if context.args and len(context.args) > 0:
        referral_code = context.args[0]
        context.user_data['referral_code'] = referral_code
    
    if user:
        check_expired_premiums()
        user = get_user(telegram_id)
        
        await update.message.reply_text(
            f"Salom, {user['full_name']}! 👋\n\nSuhbatdosh izlash uchun tugmani bosing.",
            reply_markup=get_main_keyboard(user)
        )
        return ConversationHandler.END
    else:
        await update.message.reply_text(
            "🌟 Tanishuvlar botiga xush kelibsiz!\n\n"
            "Ro'yxatdan o'tish uchun ismingizni kiriting:",
            reply_markup=ReplyKeyboardRemove()
        )
        return REGISTER_NAME

async def register_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ism qabul qilish"""
    context.user_data['full_name'] = update.message.text
    await update.message.reply_text("Yoshingizni kiriting (masalan: 20):")
    return REGISTER_AGE

async def register_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Yosh qabul qilish"""
    try:
        age = int(update.message.text)
        if age < 14 or age > 100:
            await update.message.reply_text("Yosh 14 dan 100 gacha bo'lishi kerak. Qaytadan kiriting:")
            return REGISTER_AGE
        context.user_data['age'] = age
    except ValueError:
        await update.message.reply_text("Iltimos, raqam kiriting:")
        return REGISTER_AGE
    
    keyboard = ReplyKeyboardMarkup([["👦 Erkak", "👧 Ayol"]], resize_keyboard=True)
    await update.message.reply_text("Jinsingizni tanlang:", reply_markup=keyboard)
    return REGISTER_GENDER

async def register_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Jins qabul qilish"""
    text = update.message.text
    if "Erkak" in text:
        context.user_data['gender'] = "male"
    elif "Ayol" in text:
        context.user_data['gender'] = "female"
    else:
        await update.message.reply_text("Iltimos, tugmalardan birini tanlang:")
        return REGISTER_GENDER
    
    keyboard = ReplyKeyboardMarkup(
        [[r] for r in REGIONS[:7]] + [[r] for r in REGIONS[7:]],
        resize_keyboard=True
    )
    await update.message.reply_text("Viloyatingizni tanlang:", reply_markup=keyboard)
    return REGISTER_REGION

async def register_region(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Viloyat qabul qilish va ro'yxatdan o'tkazish"""
    region = update.message.text
    if region not in REGIONS:
        await update.message.reply_text("Iltimos, ro'yxatdan viloyat tanlang:")
        return REGISTER_REGION
    
    telegram_id = update.effective_user.id
    username = update.effective_user.username
    
    referred_by = None
    referral_code = context.user_data.get('referral_code')
    if referral_code:
        referrer = get_user_by_referral_code(referral_code)
        if referrer and referrer['telegram_id'] != telegram_id:
            referred_by = referrer['id']
            add_stars(referrer['id'], 3)
            increment_referral_count(referrer['id'])
            try:
                await context.bot.send_message(
                    chat_id=referrer['telegram_id'],
                    text=f"🎉 Tabriklaymiz! Sizning referral havolangiz orqali yangi foydalanuvchi qo'shildi!\n\n"
                         f"⭐ +3 yulduz qo'shildi!\n"
                         f"💫 Jami yulduzlaringiz: {referrer['stars'] + 3}"
                )
            except:
                pass
    
    try:
        create_user(
            telegram_id=telegram_id,
            username=username,
            full_name=context.user_data['full_name'],
            age=context.user_data['age'],
            gender=context.user_data['gender'],
            region=region,
            referred_by=referred_by
        )
        user = get_user(telegram_id)
        
        welcome_msg = (
            f"✅ Ro'yxatdan o'tdingiz!\n\n"
            f"👤 Ism: {user['full_name']}\n"
            f"🎂 Yosh: {user['age']}\n"
            f"📍 Viloyat: {user['region']}\n\n"
            f"Endi suhbatdosh izlashingiz mumkin!"
        )
        
        if referred_by:
            welcome_msg += "\n\n🎁 Siz referral orqali keldingiz!"
        
        await update.message.reply_text(
            welcome_msg,
            reply_markup=get_main_keyboard(user)
        )
    except Exception as e:
        logger.error(f"Registration error: {e}")
        await update.message.reply_text("Xatolik yuz berdi. Qaytadan urinib ko'ring: /start")
    
    return ConversationHandler.END

# Qolgan handlerlar (referral_menu, star_premium_menu, buy_star_premium, back_to_referral, 
# search_partner, search_by_gender, stop_chat, cancel_search, my_profile, premium_menu, 
# buy_premium, handle_photo, handle_media_in_chat, forward_message, admin_handlers) 
# SQLite sintaksisidan PostgreSQL sintaksisiga o'tkazilgan holda qo'yiladi
# ... (bu yerda barcha handlerlar SQLite -> PostgreSQL o'zgartirilgan holda davom etadi)

# ===== ADMIN SOZLAMALARI =====
ADMIN_IDS = [int(id) for id in os.environ.get("ADMIN_IDS", "1652304805").split(",")]

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# ... (qolgan admin handlerlar)

def main():
    """Botni ishga tushirish"""
    init_database()
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Handlerlarni qo'shish
    # ... (barcha handlerlar qo'shiladi)
    
    logger.info("Bot ishga tushdi! Database: PostgreSQL")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
