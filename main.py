from keep_alive import keep_alive
import threading
import telebot
import subprocess
import os
import zipfile
import tempfile
import shutil
import requests
import re
import logging
import json
import hashlib
import socket
import psutil
import time
import zlib 
from telebot import types
from datetime import datetime, timedelta
import signal
import sqlite3
import platform
import uuid
import base64

# تهيئة التسجيل (Logging)
# تم تحديثه ليشمل ملفات منفصلة لسجلات الأمان وسجلات الأخطاء العامة
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot_activity.log"), # سجل عام لأنشطة البوت
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("MainBot") # لوجر للأنشطة العامة

security_logger = logging.getLogger("SecurityLog") # لوجر خاص للأمان
security_logger.setLevel(logging.WARNING) # تم تغيير المستوى لتسجيل التحذيرات الأمنية
security_logger.addHandler(logging.FileHandler("security_events.log"))
security_logger.addHandler(logging.StreamHandler())


# --- إعدادات البوت ---
TOKEN = '7574562116:AAGdVrowUpYwlRjEgnVb0rUt0qJg1rEzS7c'  # توكن البوت الخاص بك من BotFather
ADMIN_ID = 7700185632  # ايدي المطور الخاص بك (الـ User ID الخاص بك)
YOUR_USERNAME = '@VR_SX'  # يوزر المطور الخاص بك مع علامة @

bot = telebot.TeleBot(TOKEN)

# أدلة تخزين الملفات والبوتات
uploaded_files_dir = 'uploaded_bots'
quarantined_files_dir = 'quarantined_files' 

# تأكد من وجود المجلدات
os.makedirs(uploaded_files_dir, exist_ok=True)
os.makedirs(quarantined_files_dir, exist_ok=True)


# القوائم والمتغيرات العالمية
# لتخزين العمليات الجارية للبوتات: {process_key: {'process': Popen_object, 'folder_path': 'path/to/bot_folder', 'bot_username': '@botusername', 'file_name': 'script.py', 'owner_id': user_id, 'log_file_stdout': 'path/to/stdout.log', 'log_file_stderr': 'path/to/stderr.log', 'start_time': datetime_object}}
bot_processes = {} 
# لتخزين الملفات التي رفعها كل مستخدم: {user_id: [{'file_name': 'script.py', 'folder_path': 'path/to/bot_folder', 'bot_username': '@botusername'}]}
user_files = {}      
active_users = set() # لتخزين معرفات المستخدمين النشطين
banned_users = set() # لتخزين معرفات المستخدمين المحظورين
user_warnings = {} # لتتبع التحذيرات لكل مستخدم: {user_id: [{'reason': '...', 'timestamp': '...', 'file_name': '...'}]}

bot_locked = False  # حالة قفل البوت
free_mode = True    # وضع مجاني افتراضي (لا يتطلب اشتراك)
block_new_users = False # لمنع المستخدمين الجدد من الانضمام

# --- دوال فحص الحماية (تم تعديلها لتنفيذ الفحص المطلوب) ---
def is_safe_python_code(file_content_bytes, user_id, file_name):
    """
    يفحص محتوى ملف بايثون بحثاً عن أكواد مشبوهة.
    يعيد True إذا كان آمناً، ويعيد False مع السبب إذا كان مشبوهاً.
    """
    file_content = file_content_bytes.decode('utf-8', errors='ignore')

    # قائمة الكلمات المفتاحية/الوحدات المشبوهة
    suspicious_patterns = {
        r'\bos\.system\b': 'استخدام os.system',
        r'\bsubprocess\.(?!run|Popen|check_output|call)': 'استخدام subprocess بطريقة غير مصرح بها', # استثناءات للتشغيل الرسمي
        r'\beval\(': 'استخدام eval()',
        r'\bexec\(': 'استخدام exec()',
        r'\bcompile\(': 'استخدام compile()',
        r'\bsocket\b': 'استخدام socket',
        r'\brequests\.post\b': 'استخدام requests.post',
        r'\bbase64\b': 'استخدام base64',
        r'\bmarshal\b': 'استخدام marshal',
        r'\bzlib\b': 'استخدام zlib',
        r'\btelebot\.TeleBot\(': 'إنشاء كائن TeleBot داخل ملف المستخدم',
        r'while\s+True\s*:': 'حلقة لا نهائية (while True)',
        r'\binput\(': 'استخدام input()',
    }

    found_reasons = []
    for pattern, reason in suspicious_patterns.items():
        if re.search(pattern, file_content):
            found_reasons.append(reason)

    if found_reasons:
        reason_str = ", ".join(found_reasons)
        log_user_warning(user_id, f"تم اكتشاف كود مشبوه: {reason_str}", file_name)
        notify_admins_of_potential_risk(user_id, f"كود مشبوه في الملف {file_name}", file_name, file_content_bytes)
        return False, reason_str

    return True, None

def scan_file_with_api(file_content, file_name, user_id):
    """
    هذه الدالة Dummy - لا تقوم بأي فحص API وتعود بـ True دائمًا.
    (تم الإبقاء عليها كما هي، لا يوجد طلب لتعديلها)
    """
    return True 

def scan_zip_for_malicious_code(zip_file_path, user_id):
    """
    يفحص ملف ZIP بحثاً عن ملفات بايثون مشبوهة.
    يعيد True, None إذا كان آمناً، ويعيد False, السبب إذا تم اكتشاف كود مشبوه.
    """
    try:
        with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
            for file_info in zip_ref.infolist():
                if file_info.filename.endswith('.py'):
                    with zip_ref.open(file_info.filename) as py_file:
                        file_content_bytes = py_file.read()
                        is_safe, reason = is_safe_python_code(file_content_bytes, user_id, file_info.filename)
                        if not is_safe:
                            return False, f"كود مشبوه في الملف {file_info.filename}: {reason}"
        return True, None
    except Exception as e:
        logger.error(f"خطأ أثناء فحص ملف ZIP ({zip_file_path}) لـ user_id {user_id}: {e}")
        log_user_warning(user_id, f"خطأ في فحص ملف ZIP: {e}", zip_file_path.split('/')[-1])
        return False, "فشل في فحص ملف ZIP"

def log_user_warning(user_id, reason, file_name=None):
    """
    يسجل تحذيراً للمستخدم في قاعدة البيانات والمتغيرات العالمية.
    """
    timestamp = datetime.now().isoformat()
    warning_entry = {'reason': reason, 'file_name': file_name, 'timestamp': timestamp}

    if user_id not in user_warnings:
        user_warnings[user_id] = []
    user_warnings[user_id].append(warning_entry)

    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute('INSERT INTO user_warnings (user_id, reason, file_name, timestamp) VALUES (?, ?, ?, ?)', 
              (user_id, reason, file_name, timestamp))
    conn.commit()
    conn.close()
    security_logger.warning(f"تحذير للمستخدم {user_id}: {reason} (الملف: {file_name})")

def notify_admins_of_potential_risk(user_id, activity, file_name, file_content_bytes):
    """
    يرسل تنبيهًا للمطور بشأن نشاط مشبوه، مع تفاصيل الملف والسبب.
    """
    warning_message = f"⚠️ **محاولة مشبوهة!**\n\n"
    warning_message += f"🧪 **السبب**: {activity}\n"
    warning_message += f"👤 **معرف المستخدم**: `{user_id}`\n"
    warning_message += f"📄 **اسم الملف**: `{file_name}`\n"
    warning_message += f"🔗 **رابط الملف**: [انقر هنا لتحميل الملف]({get_file_download_link(file_content_bytes, file_name)})" # يمكن إضافة رابط لتحميل الملف إذا أردت إتاحة مراجعة يدوية

    try:
        bot.send_message(ADMIN_ID, warning_message, parse_mode='Markdown')
        security_logger.critical(f"تم إرسال تحذير للمطور: {activity} من المستخدم {user_id} للملف {file_name}")
    except Exception as e:
        security_logger.error(f"فشل في إرسال تنبيه للمطور بشأن نشاط مشبوه: {e}")

def get_file_download_link(file_content_bytes, file_name):
    """
    دالة Dummy لإنشاء رابط تحميل ملف. في بيئة حقيقية ستحتاج لرفع الملف إلى خدمة تخزين.
    هنا، سنستخدم حلاً بديلاً بسيطًا، أو نوضح أنه يجب أن يكون هناك خدمة تخزين.
    """
    # في بيئة إنتاجية، ستحتاج إلى رفع هذا الملف مؤقتًا إلى خدمة تخزين (مثل Telegram's own file storage if possible
    # or a cloud storage like S3, or simply storing it temporarily on the server and providing a direct link).
    # For now, we'll just indicate it's not directly downloadable via this link.
    # يمكن إرجاع رابط placeholder أو عدم تضمين الرابط إذا لم يكن هناك طريقة لتحميل الملف تلقائيًا.
    return "لا يتوفر رابط تحميل مباشر (يجب مراجعة الملف في مجلد quarantined_files)"

# --- وظائف قاعدة البيانات (تم تحديثها لتشمل حفظ حالة البوتات) ---

def init_db():
    """يهيئ قاعدة البيانات والجداول المطلوبة، ويضيف أعمدة جديدة إذا لم تكن موجودة."""
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()

    # جدول لملفات المستخدمين
    c.execute('''CREATE TABLE IF NOT EXISTS user_files
                 (user_id INTEGER, file_name TEXT, folder_path TEXT, bot_username TEXT, UNIQUE(user_id, file_name, folder_path))''')

    # جدول للمستخدمين النشطين
    c.execute('''CREATE TABLE IF NOT EXISTS active_users
                 (user_id INTEGER PRIMARY KEY)''')
    # جدول للمستخدمين المحظورين
    c.execute('''CREATE TABLE IF NOT EXISTS banned_users
                 (user_id INTEGER PRIMARY KEY, reason TEXT, ban_date TEXT)''')
    # جدول للتحذيرات
    c.execute('''CREATE TABLE IF NOT EXISTS user_warnings
                 (user_id INTEGER, reason TEXT, file_name TEXT, timestamp TEXT)''')

    # جدول لحفظ حالة البوتات قيد التشغيل (جديد)
    c.execute('''CREATE TABLE IF NOT EXISTS bot_processes_state
                 (process_key TEXT PRIMARY KEY, folder_path TEXT, bot_username TEXT, file_name TEXT, owner_id INTEGER, 
                 log_file_stdout TEXT, log_file_stderr TEXT, start_time TEXT)''')

    conn.commit()
    conn.close()

def load_data():
    """يحمل البيانات من قاعدة البيانات عند بدء تشغيل البوت."""
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()

    c.execute('SELECT user_id, file_name, folder_path, bot_username FROM user_files')
    user_files_data = c.fetchall()
    for user_id, file_name, folder_path, bot_username in user_files_data:
        if user_id not in user_files:
            user_files[user_id] = []
        user_files[user_id].append({'file_name': file_name, 'folder_path': folder_path, 'bot_username': bot_username})

    c.execute('SELECT user_id FROM active_users')
    active_users_data = c.fetchall()
    for user_id, in active_users_data:
        active_users.add(user_id)

    c.execute('SELECT user_id, reason FROM banned_users') # تم إضافة reason في الاستعلام
    banned_users_data = c.fetchall()
    for user_id, reason in banned_users_data:
        banned_users.add(user_id) # فقط إضافة الـ ID للمجموعة، السبب يخزن في DB فقط

    c.execute('SELECT user_id, reason, file_name, timestamp FROM user_warnings')
    warnings_data = c.fetchall()
    for user_id, reason, file_name, timestamp in warnings_data:
        if user_id not in user_warnings:
            user_warnings[user_id] = []
        user_warnings[user_id].append({'reason': reason, 'file_name': file_name, 'timestamp': timestamp})

    conn.close()

def save_user_file_db(user_id, file_name, folder_path, bot_username=None):
    """يحفظ معلومات الملف في قاعدة البيانات."""
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO user_files (user_id, file_name, folder_path, bot_username) VALUES (?, ?, ?, ?)', 
              (user_id, file_name, folder_path, bot_username))
    conn.commit()
    conn.close()

def remove_user_file_db(user_id, file_name, folder_path):
    """
    يحذف معلومات الملف من قاعدة البيانات بناءً على user_id و file_name و folder_path
    لضمان التفرد في حال رفع نفس اسم الملف لعدة بوتات.
    """
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute('DELETE FROM user_files WHERE user_id = ? AND file_name = ? AND folder_path = ?', 
              (user_id, file_name, folder_path))
    conn.commit()
    conn.close()

def add_active_user(user_id):
    """يضيف مستخدمًا إلى قائمة المستخدمين النشطين في قاعدة البيانات."""
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO active_users (user_id) VALUES (?)', (user_id,))
    conn.commit()
    conn.close()

def ban_user(user_id, reason):
    """يحظر المستخدم ويسجل السبب في قاعدة البيانات."""
    banned_users.add(user_id)
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO banned_users (user_id, reason, ban_date) VALUES (?, ?, ?)', 
              (user_id, reason, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    logger.warning(f"تم حظر المستخدم {user_id} بسبب: {reason}")

def unban_user(user_id):
    """يلغي حظر المستخدم من قاعدة البيانات."""
    if user_id in banned_users:
        banned_users.remove(user_id)
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute('DELETE FROM banned_users WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
        logger.info(f"تم إلغاء حظر المستخدم {user_id}")
        return True
    return False

def save_bot_process_state(process_key, folder_path, bot_username, file_name, owner_id, log_file_stdout, log_file_stderr, start_time):
    """يحفظ حالة البوت الجاري تشغيله في قاعدة البيانات."""
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO bot_processes_state 
                 (process_key, folder_path, bot_username, file_name, owner_id, log_file_stdout, log_file_stderr, start_time) 
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
              (process_key, folder_path, bot_username, file_name, owner_id, log_file_stdout, log_file_stderr, start_time.isoformat()))
    conn.commit()
    conn.close()

def remove_bot_process_state(process_key):
    """يحذف حالة البوت من قاعدة البيانات."""
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute('DELETE FROM bot_processes_state WHERE process_key = ?', (process_key,))
    conn.commit()
    conn.close()

def load_bot_processes_state():
    """يحمل حالات البوتات من قاعدة البيانات عند بدء التشغيل."""
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute('SELECT process_key, folder_path, bot_username, file_name, owner_id, log_file_stdout, log_file_stderr, start_time FROM bot_processes_state')
    saved_processes = c.fetchall()
    conn.close()
    return saved_processes

# تهيئة وتحميل البيانات عند بدء التشغيل
init_db()
load_data()

# --- استرداد تلقائي للبوتات (وظيفة جديدة) ---
def recover_running_bots():
    """
    يسترد البوتات التي كانت تعمل سابقاً من قاعدة البيانات ويقوم بتشغيلها.
    """
    logger.info("جارٍ استرداد البوتات التي كانت تعمل سابقاً...")
    saved_processes = load_bot_processes_state()
    for process_key, folder_path, bot_username, file_name, owner_id, log_file_stdout, log_file_stderr, start_time_str in saved_processes:
        main_script_path = os.path.join(folder_path, file_name)
        if os.path.exists(main_script_path):
            logger.info(f"إعادة تشغيل البوت: {bot_username} ({file_name}) للمستخدم {owner_id}")
            start_time_dt = datetime.fromisoformat(start_time_str)
            try:
                # التأكد من أن المجلد هو دليل العمل الصحيح
                process = subprocess.Popen(
                    ['python3', main_script_path],
                    cwd=folder_path,  # تعيين مجلد العمل
                    stdout=open(log_file_stdout, 'a'),
                    stderr=open(log_file_stderr, 'a'),
                    preexec_fn=os.setsid # لجعل العملية مستقلة عن البوت الرئيسي
                )
                bot_processes[process_key] = {
                    'process': process,
                    'folder_path': folder_path,
                    'bot_username': bot_username,
                    'file_name': file_name,
                    'owner_id': owner_id,
                    'log_file_stdout': log_file_stdout,
                    'log_file_stderr': log_file_stderr,
                    'start_time': start_time_dt # استخدام الوقت الأصلي للتشغيل
                }
                logger.info(f"تمت إعادة تشغيل البوت {bot_username} بنجاح.")
                # إرسال إشعار للمستخدم إذا كان موجودًا في active_users
                if owner_id in active_users:
                    try:
                        bot.send_message(owner_id, f"✅ **تم استرداد وإعادة تشغيل البوت الخاص بك** `{bot_username if bot_username else file_name}` **تلقائياً.**")
                    except Exception as e:
                        logger.error(f"فشل في إرسال إشعار استرداد للمستخدم {owner_id}: {e}")
            except Exception as e:
                logger.error(f"فشل في إعادة تشغيل البوت {file_name} للمستخدم {owner_id}: {e}")
                # إزالة البوت من قائمة الاسترداد إذا فشل تشغيله
                remove_bot_process_state(process_key)
        else:
            logger.warning(f"ملف البوت {file_name} في المسار {folder_path} غير موجود. إزالة من قائمة الاسترداد.")
            remove_bot_process_state(process_key)
    logger.info("اكتمل استرداد البوتات.")

# --- لوحة التحكم والقوائم ---

def create_main_menu(user_id):
    """ينشئ لوحة المفاتيح الرئيسية للبوت."""
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('📤 رفع ملف بوت', callback_data='upload'))
    markup.add(types.InlineKeyboardButton('🤖 بوتاتي', callback_data='my_bots')) 
    markup.add(types.InlineKeyboardButton('⚡ سرعة البوت', callback_data='speed'))
    markup.add(types.InlineKeyboardButton('📞 تواصل مع المطور', url=f'https://t.me/{YOUR_USERNAME[1:]}'))

    # إضافة زر الإحصائيات هنا للمستخدمين العاديين أيضًا
    markup.add(types.InlineKeyboardButton('📊 إحصائيات عامة', callback_data='stats'))

    if user_id == ADMIN_ID:
        # الأزرار الخاصة بالمطور فقط
        markup.add(types.InlineKeyboardButton('🔐 تقرير الأمان', callback_data='security_report'))
        markup.add(types.InlineKeyboardButton('📢 إذاعة رسالة', callback_data='broadcast'))
        markup.add(types.InlineKeyboardButton('🔒 قفل البوت', callback_data='lock_bot'))
        markup.add(types.InlineKeyboardButton('🔓 فتح البوت', callback_data='unlock_bot'))
        markup.add(types.InlineKeyboardButton('🔨 إدارة المستخدمين', callback_data='manage_users'))
        markup.add(types.InlineKeyboardButton('⚙️ إدارة البوتات المستضافة', callback_data='manage_hosted_bots'))
        markup.add(types.InlineKeyboardButton('🖥️ إحصائيات الخادم', callback_data='server_stats'))
        markup.add(types.InlineKeyboardButton('🛠️ أدوات المطور', callback_data='dev_tools'))
    return markup

# --- معالجات الأوامر والرسائل ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    """يعالج أمر /start ويرسل رسالة الترحيب."""
    user_id = message.from_user.id

    if user_id in banned_users:
        bot.send_message(message.chat.id, "⛔ **أنت محظور من استخدام هذا البوت.** يرجى التواصل مع المطور إذا كنت تعتقد أن هذا خطأ.")
        return

    if bot_locked:
        bot.send_message(message.chat.id, "⚠️ **البوت مقفل حالياً.** الرجاء المحاولة لاحقًا.")
        return

    if block_new_users and user_id != ADMIN_ID:
        bot.send_message(message.chat.id, "🚫 **نأسف، البوت لا يقبل مستخدمين جدد حاليًا.** يرجى التواصل مع المطور @VR_SX.")
        return

    user_name = message.from_user.first_name
    user_username = message.from_user.username

    user_bio = "لا يوجد بايو"
    photo_file_id = None

    if user_id not in active_users:
        active_users.add(user_id)  
        add_active_user(user_id)  # أضف المستخدم إلى قاعدة البيانات كنشط

        try:
            # استخدام bot.get_chat بدلاً من bot.get_user_profile_photos لبعض التفاصيل
            # للحصول على البايو، نحتاج إلى معرفة ما إذا كان المستخدم يملك بايو عام
            # هذا الجزء قد لا يعمل مباشرة بدون صلاحيات خاصة أو إذا لم يكن البايو متاحًا عبر API
            # bot.get_chat() لا يعيد البايو العام للمستخدمين العاديين، فقط للقنوات والمجموعات
            # لذلك، سأتركها كما هي مع ملاحظة أنها قد لا تجلب البايو
            # user_profile = bot.get_chat(user_id)
            # user_bio = user_profile.bio if user_profile.bio else "لا يوجد بايو"

            user_profile_photos = bot.get_user_profile_photos(user_id, limit=1)
            if user_profile_photos.photos:
                photo_file_id = user_profile_photos.photos[0][-1].file_id  
        except Exception as e:
            logger.error(f"فشل في جلب تفاصيل المستخدم الجديد {user_id}: {e}")

        try:
            welcome_message_to_admin = f"🎉 **انضم مستخدم جديد إلى البوت!**\n\n"
            welcome_message_to_admin += f"👤 **الاسم**: {user_name}\n"
            welcome_message_to_admin += f"📌 **اليوزر**: @{user_username if user_username else 'غير متوفر'}\n"
            welcome_message_to_admin += f"🆔 **معرف المستخدم**: `{user_id}`"

            bot.send_message(ADMIN_ID, welcome_message_to_admin, parse_mode='Markdown')
            if photo_file_id:
                bot.send_photo(ADMIN_ID, photo_file_id, caption="صورة الملف الشخصي للمستخدم الجديد")
        except Exception as e:
            logger.error(f"فشل في إرسال رسالة انضمام المستخدم الجديد للمطور: {e}")

    welcome_text = (
        f"👋 **أهلاً بك يا {user_name}!**\n\n"
        "أنا بوت استضافة البوتات الخاص بك. يمكنك رفع بوتات Python هنا وسأقوم بتشغيلها لك على مدار الساعة."
        "تأكد من أن بوتك لا يحتوي على أي أكواد ضارة أو غير مسموح بها."
    )
    bot.send_message(message.chat.id, welcome_text, reply_markup=create_main_menu(user_id), parse_mode='Markdown')
    logger.info(f"المستخدم {user_id} بدأ البوت.")

@bot.message_handler(commands=['panel'])
def send_panel(message):
    """يعالج أمر /panel ويعرض لوحة التحكم الرئيسية."""
    user_id = message.from_user.id
    if user_id in banned_users:
        bot.send_message(message.chat.id, "⛔ **أنت محظور من استخدام هذا البوت.**")
        return
    if bot_locked:
        bot.send_message(message.chat.id, "⚠️ **البوت مقفل حالياً.** الرجاء المحاولة لاحقًا.")
        return
    bot.send_message(message.chat.id, "🚀 **لوحة التحكم الرئيسية:**", reply_markup=create_main_menu(user_id), parse_mode='Markdown')
    logger.info(f"المستخدم {user_id} طلب لوحة التحكم.")

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    """يعالج جميع استدعاءات رد الاتصال (callback queries) من الأزرار المضمنة."""
    user_id = call.from_user.id
    message_id = call.message.message_id
    chat_id = call.message.chat.id

    if user_id in banned_users:
        bot.answer_callback_query(call.id, "⛔ أنت محظور من استخدام هذا البوت.")
        bot.send_message(chat_id, "⛔ **أنت محظور من استخدام هذا البوت.** يرجى التواصل مع المطور إذا كنت تعتقد أن هذا خطأ.")
        return

    if bot_locked and user_id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⚠️ البوت مقفل حالياً.")
        bot.send_message(chat_id, "⚠️ **البوت مقفل حالياً.** الرجاء المحاولة لاحقًا.")
        return

    data = call.data

    # Main Menu Handlers
    if data == 'upload':
        bot.answer_callback_query(call.id, "الرجاء إرسال ملف البوت.")
        bot.send_message(chat_id, "📤 **الرجاء إرسال ملف البوت الخاص بك.**\n\n"
                                  "💡 **ملاحظات هامة:**\n"
                                  "1.  يجب أن يكون الملف بامتداد `.py` أو `.zip`.\n"
                                  "2.  إذا كان ملف `.zip`، يجب أن يحتوي على ملف `.py` رئيسي واحد على الأقل.\n"
                                  "3.  سيتم فحص الملف بحثًا عن أي أكواد ضارة.\n"
                                  "4.  يرجى التأكد من أن بوتك يستخدم `python3`.\n"
                                  "5.  لا ترسل ملفات تحتوي على `pip install` لأكثر من مكتبة أو مكتبات غير موجودة بشكل شائع، الأفضل أن يكون `requirements.txt`.", 
                                  parse_mode='Markdown')
        bot.register_next_step_handler(call.message, handle_document_upload)

    elif data == 'my_bots':
        show_my_bots(chat_id, user_id)

    elif data == 'speed':
        bot.answer_callback_query(call.id, "جارٍ فحص سرعة البوت...")
        check_bot_speed(chat_id)

    elif data == 'stats':
        send_global_stats(chat_id)

    elif data == 'security_report':
        if user_id == ADMIN_ID:
            send_security_report(chat_id)
        else:
            bot.answer_callback_query(call.id, "ليس لديك صلاحية.")
            bot.send_message(chat_id, "⛔ **ليس لديك صلاحية للوصول إلى هذه الميزة.**")

    elif data == 'broadcast':
        if user_id == ADMIN_ID:
            bot.answer_callback_query(call.id, "أرسل رسالة الإذاعة.")
            bot.send_message(chat_id, "📢 **الرجاء إرسال الرسالة التي تود إذاعتها لجميع المستخدمين.**")
            bot.register_next_step_handler(call.message, handle_broadcast_message)
        else:
            bot.answer_callback_query(call.id, "ليس لديك صلاحية.")
            bot.send_message(chat_id, "⛔ **ليس لديك صلاحية للوصول إلى هذه الميزة.**")

    elif data == 'lock_bot':
        if user_id == ADMIN_ID:
            toggle_bot_lock(chat_id, True)
        else:
            bot.answer_callback_query(call.id, "ليس لديك صلاحية.")
            bot.send_message(chat_id, "⛔ **ليس لديك صلاحية للوصول إلى هذه الميزة.**")

    elif data == 'unlock_bot':
        if user_id == ADMIN_ID:
            toggle_bot_lock(chat_id, False)
        else:
            bot.answer_callback_query(call.id, "ليس لديك صلاحية.")
            bot.send_message(chat_id, "⛔ **ليس لديك صلاحية للوصول إلى هذه الميزة.**")

    elif data == 'manage_users':
        if user_id == ADMIN_ID:
            show_manage_users_menu(chat_id)
        else:
            bot.answer_callback_query(call.id, "ليس لديك صلاحية.")
            bot.send_message(chat_id, "⛔ **ليس لديك صلاحية للوصول إلى هذه الميزة.**")

    elif data == 'manage_hosted_bots':
        if user_id == ADMIN_ID:
            show_manage_hosted_bots_menu(chat_id)
        else:
            bot.answer_callback_query(call.id, "ليس لديك صلاحية.")
            bot.send_message(chat_id, "⛔ **ليس لديك صلاحية للوصول إلى هذه الميزة.**")

    elif data == 'server_stats':
        if user_id == ADMIN_ID:
            send_server_stats(chat_id)
        else:
            bot.answer_callback_query(call.id, "ليس لديك صلاحية.")
            bot.send_message(chat_id, "⛔ **ليس لديك صلاحية للوصول إلى هذه الميزة.**")

    elif data == 'dev_tools':
        if user_id == ADMIN_ID:
            show_dev_tools_menu(chat_id)
        else:
            bot.answer_callback_query(call.id, "ليس لديك صلاحية.")
            bot.send_message(chat_id, "⛔ **ليس لديك صلاحية للوصول إلى هذه الميزة.**")

    elif data == 'back_to_main':
        bot.answer_callback_query(call.id, "العودة إلى القائمة الرئيسية.")
        bot.edit_message_text(chat_id=chat_id, message_id=message_id, 
                              text="🚀 **لوحة التحكم الرئيسية:**", 
                              reply_markup=create_main_menu(user_id), 
                              parse_mode='Markdown')

    # Manage Users Menu Handlers
    elif data == 'list_users':
        if user_id == ADMIN_ID:
            list_all_users(chat_id)
        else:
            bot.answer_callback_query(call.id, "ليس لديك صلاحية.")

    elif data == 'ban_user':
        if user_id == ADMIN_ID:
            bot.answer_callback_query(call.id, "أرسل معرف المستخدم للحظر.")
            bot.send_message(chat_id, "🚫 **الرجاء إرسال معرف (ID) المستخدم الذي تود حظره.**")
            bot.register_next_step_handler(call.message, handle_ban_user_id)
        else:
            bot.answer_callback_query(call.id, "ليس لديك صلاحية.")

    elif data == 'unban_user':
        if user_id == ADMIN_ID:
            bot.answer_callback_query(call.id, "أرسل معرف المستخدم لفك الحظر.")
            bot.send_message(chat_id, "✅ **الرجاء إرسال معرف (ID) المستخدم الذي تود فك الحظر عنه.**")
            bot.register_next_step_handler(call.message, handle_unban_user_id)
        else:
            bot.answer_callback_query(call.id, "ليس لديك صلاحية.")

    elif data == 'view_warnings':
        if user_id == ADMIN_ID:
            bot.answer_callback_query(call.id, "أرسل معرف المستخدم لعرض تحذيراته.")
            bot.send_message(chat_id, "⚠️ **الرجاء إرسال معرف (ID) المستخدم لعرض تحذيراته.**")
            bot.register_next_step_handler(call.message, handle_view_user_warnings)
        else:
            bot.answer_callback_query(call.id, "ليس لديك صلاحية.")

    elif data == 'clear_warnings':
        if user_id == ADMIN_ID:
            bot.answer_callback_query(call.id, "أرسل معرف المستخدم لمسح تحذيراته.")
            bot.send_message(chat_id, "🗑️ **الرجاء إرسال معرف (ID) المستخدم لمسح جميع تحذيراته.**")
            bot.register_next_step_handler(call.message, handle_clear_user_warnings)
        else:
            bot.answer_callback_query(call.id, "ليس لديك صلاحية.")

    elif data == 'block_new_users':
        if user_id == ADMIN_ID:
            toggle_block_new_users(chat_id, True)
        else:
            bot.answer_callback_query(call.id, "ليس لديك صلاحية.")

    elif data == 'allow_new_users':
        if user_id == ADMIN_ID:
            toggle_block_new_users(chat_id, False)
        else:
            bot.answer_callback_query(call.id, "ليس لديك صلاحية.")

    # Manage Hosted Bots Menu Handlers
    elif data == 'list_all_hosted_bots':
        if user_id == ADMIN_ID:
            list_all_hosted_bots_admin(chat_id)
        else:
            bot.answer_callback_query(call.id, "ليس لديك صلاحية.")

    elif data == 'stop_bot_admin':
        if user_id == ADMIN_ID:
            bot.answer_callback_query(call.id, "أرسل مفتاح العملية لإيقاف البوت.")
            bot.send_message(chat_id, "⏹️ **الرجاء إرسال مفتاح العملية (Process Key) للبوت الذي تود إيقافه.**\n"
                                      "يمكنك الحصول عليه من قائمة 'إدارة البوتات المستضافة'.")
            bot.register_next_step_handler(call.message, handle_stop_bot_by_key_admin)
        else:
            bot.answer_callback_query(call.id, "ليس لديك صلاحية.")

    elif data == 'delete_bot_admin':
        if user_id == ADMIN_ID:
            bot.answer_callback_query(call.id, "أرسل مفتاح العملية لحذف البوت.")
            bot.send_message(chat_id, "🗑️ **الرجاء إرسال مفتاح العملية (Process Key) للبوت الذي تود حذفه.**\n"
                                      "سيتم إيقاف البوت وحذف جميع ملفاته وسجلاته.")
            bot.register_next_step_handler(call.message, handle_delete_bot_by_key_admin)
        else:
            bot.answer_callback_query(call.id, "ليس لديك صلاحية.")

    elif data == 'view_bot_logs_admin':
        if user_id == ADMIN_ID:
            bot.answer_callback_query(call.id, "أرسل مفتاح العملية لعرض سجلات البوت.")
            bot.send_message(chat_id, "📝 **الرجاء إرسال مفتاح العملية (Process Key) للبوت الذي تود عرض سجلاته.**")
            bot.register_next_step_handler(call.message, handle_view_bot_logs_admin)
        else:
            bot.answer_callback_query(call.id, "ليس لديك صلاحية.")

    # My Bots Menu Handlers
    elif data.startswith('view_log_'):
        process_key = data.replace('view_log_', '')
        view_bot_logs(chat_id, user_id, process_key)

    elif data.startswith('stop_bot_'):
        process_key = data.replace('stop_bot_', '')
        stop_user_bot(chat_id, user_id, process_key)

    elif data.startswith('delete_bot_'):
        process_key = data.replace('delete_bot_', '')
        delete_user_bot(chat_id, user_id, process_key)

    elif data.startswith('restart_bot_'):
        process_key = data.replace('restart_bot_', '')
        restart_user_bot(chat_id, user_id, process_key)

    elif data == 'back_to_my_bots':
        bot.answer_callback_query(call.id, "العودة إلى بوتاتي.")
        show_my_bots(chat_id, user_id, edit_message=True, message_id=message_id)

    elif data == 'back_to_manage_users':
        if user_id == ADMIN_ID:
            bot.answer_callback_query(call.id, "العودة إلى إدارة المستخدمين.")
            show_manage_users_menu(chat_id, edit_message=True, message_id=message_id)
        else:
            bot.answer_callback_query(call.id, "ليس لديك صلاحية.")

    elif data == 'back_to_manage_hosted_bots':
        if user_id == ADMIN_ID:
            bot.answer_callback_query(call.id, "العودة إلى إدارة البوتات المستضافة.")
            show_manage_hosted_bots_menu(chat_id, edit_message=True, message_id=message_id)
        else:
            bot.answer_callback_query(call.id, "ليس لديك صلاحية.")

    # Dev Tools Handlers
    elif data == 'view_all_warnings':
        if user_id == ADMIN_ID:
            view_all_security_warnings(chat_id)
        else:
            bot.answer_callback_query(call.id, "ليس لديك صلاحية.")

    elif data == 'clear_all_warnings':
        if user_id == ADMIN_ID:
            clear_all_security_warnings(chat_id)
        else:
            bot.answer_callback_query(call.id, "ليس لديك صلاحية.")

    elif data == 'check_ram':
        if user_id == ADMIN_ID:
            check_ram_usage(chat_id)
        else:
            bot.answer_callback_query(call.id, "ليس لديك صلاحية.")

    elif data == 'check_disk':
        if user_id == ADMIN_ID:
            check_disk_usage(chat_id)
        else:
            bot.answer_callback_query(call.id, "ليس لديك صلاحية.")

    elif data == 'check_cpu':
        if user_id == ADMIN_ID:
            check_cpu_usage(chat_id)
        else:
            bot.answer_callback_query(call.id, "ليس لديك صلاحية.")

    elif data == 'reboot_server':
        if user_id == ADMIN_ID:
            confirm_reboot(chat_id)
        else:
            bot.answer_callback_query(call.id, "ليس لديك صلاحية.")

    elif data == 'confirm_reboot':
        if user_id == ADMIN_ID:
            perform_reboot(chat_id)
        else:
            bot.answer_callback_query(call.id, "ليس لديك صلاحية.")

    elif data == 'cancel_reboot':
        if user_id == ADMIN_ID:
            bot.answer_callback_query(call.id, "تم إلغاء إعادة التشغيل.")
            bot.edit_message_text(chat_id=chat_id, message_id=message_id, 
                                  text="❌ تم إلغاء عملية إعادة تشغيل الخادم.", 
                                  reply_markup=show_dev_tools_menu(user_id)) # Pass user_id for the menu
        else:
            bot.answer_callback_query(call.id, "ليس لديك صلاحية.")

    bot.answer_callback_query(call.id) # Always answer the callback query

# --- وظائف معالجة الملفات ---

def handle_document_upload(message):
    """
    يتعامل مع رفع ملفات البوت (Python أو ZIP).
    """
    user_id = message.from_user.id
    chat_id = message.chat.id

    if not message.document:
        bot.send_message(chat_id, "⚠️ **الرجاء إرسال ملف، وليس نصًا أو صورة.** يرجى المحاولة مرة أخرى.")
        bot.send_message(chat_id, "🚀 **لوحة التحكم الرئيسية:**", reply_markup=create_main_menu(user_id), parse_mode='Markdown')
        return

    file_name = message.document.file_name
    file_id = message.document.file_id

    # تحديد نوع الملف
    if file_name.endswith('.py'):
        process_python_file(message, file_id, file_name, user_id, chat_id)
    elif file_name.endswith('.zip'):
        process_zip_file(message, file_id, file_name, user_id, chat_id)
    else:
        bot.send_message(chat_id, "🚫 **نوع ملف غير مدعوم.** الرجاء إرسال ملف `.py` أو `.zip` فقط.")
        bot.send_message(chat_id, "🚀 **لوحة التحكم الرئيسية:**", reply_markup=create_main_menu(user_id), parse_mode='Markdown')

def process_python_file(message, file_id, file_name, user_id, chat_id):
    """يعالج ملفات بايثون المرفوعة."""
    try:
        file_info = bot.get_file(file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        # فحص أمان الكود
        is_safe, reason = is_safe_python_code(downloaded_file, user_id, file_name)
        if not is_safe:
            bot.send_message(chat_id, f"⛔ **تم رفض البوت.**\n\n"
                                      f"تم اكتشاف كود مشبوه في ملفك: `{reason}`.\n"
                                      f"تم نقل الملف إلى الحجر الصحي للمراجعة. يرجى مراجعة الكود الخاص بك وتعديله.")
            # نقل الملف إلى مجلد الحجر الصحي
            quarantined_file_path = os.path.join(quarantined_files_dir, f"{user_id}_{file_name}_{datetime.now().strftime('%Y%m%d%H%M%S')}")
            with open(quarantined_file_path, 'wb') as f:
                f.write(downloaded_file)
            logger.warning(f"تم نقل ملف مشبوه ({file_name}) للمستخدم {user_id} إلى الحجر الصحي. السبب: {reason}")
            bot.send_message(chat_id, "🚀 **لوحة التحكم الرئيسية:**", reply_markup=create_main_menu(user_id), parse_mode='Markdown')
            return

        # إنشاء مجلد فريد لكل بوت لتجنب التعارضات
        bot_folder_name = f"bot_{user_id}_{int(time.time())}"
        bot_folder_path = os.path.join(uploaded_files_dir, bot_folder_name)
        os.makedirs(bot_folder_path, exist_ok=True)

        file_path_in_folder = os.path.join(bot_folder_path, file_name)
        with open(file_path_in_folder, 'wb') as f:
            f.write(downloaded_file)

        # طلب اسم البوت/اليوزر
        msg = bot.send_message(chat_id, "✨ **تم استلام ملف البوت الخاص بك بنجاح!**\n\n"
                                          "الرجاء إرسال **اسم مستخدم البوت (@username)** الخاص بك (مثل `@MyAwesomeBot`) أو أي **اسم تعريفي** للبوت إذا لم يكن بوت تيليجرام.\n\n"
                                          "💡 **ملاحظة:** إذا أرسلت اسم المستخدم الخاص بالبوت، فيرجى التأكد من أنه اسم مستخدم صحيح وبادئ بـ `@`.")
        bot.register_next_step_handler(msg, lambda m: start_bot_after_name(m, file_path_in_folder, bot_folder_path, file_name, user_id))

    except Exception as e:
        logger.error(f"خطأ أثناء معالجة ملف Python من المستخدم {user_id}: {e}")
        bot.send_message(chat_id, f"❌ **حدث خطأ أثناء معالجة ملف البوت الخاص بك.** الرجاء المحاولة مرة أخرى لاحقًا.")
        bot.send_message(chat_id, "🚀 **لوحة التحكم الرئيسية:**", reply_markup=create_main_menu(user_id), parse_mode='Markdown')

def process_zip_file(message, file_id, file_name, user_id, chat_id):
    """يعالج ملفات ZIP المرفوعة."""
    try:
        file_info = bot.get_file(file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        # حفظ ملف الـ ZIP مؤقتًا
        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as temp_zip:
            temp_zip.write(downloaded_file)
            temp_zip_path = temp_zip.name

        # فحص أمان محتوى الـ ZIP
        is_safe, reason = scan_zip_for_malicious_code(temp_zip_path, user_id)
        if not is_safe:
            bot.send_message(chat_id, f"⛔ **تم رفض البوت.**\n\n"
                                      f"تم اكتشاف كود مشبوه داخل ملف ZIP الخاص بك: `{reason}`.\n"
                                      f"تم نقل الملف إلى الحجر الصحي للمراجعة. يرجى مراجعة الكود الخاص بك وتعديله.")
            # نقل الملف إلى مجلد الحجر الصحي
            quarantined_file_path = os.path.join(quarantined_files_dir, f"{user_id}_{file_name}_{datetime.now().strftime('%Y%m%d%H%M%S')}")
            shutil.copy(temp_zip_path, quarantined_file_path)
            logger.warning(f"تم نقل ملف ZIP مشبوه ({file_name}) للمستخدم {user_id} إلى الحجر الصحي. السبب: {reason}")
            os.unlink(temp_zip_path) # حذف الملف المؤقت
            bot.send_message(chat_id, "🚀 **لوحة التحكم الرئيسية:**", reply_markup=create_main_menu(user_id), parse_mode='Markdown')
            return

        # إنشاء مجلد فريد لكل بوت
        bot_folder_name = f"bot_{user_id}_{int(time.time())}"
        bot_folder_path = os.path.join(uploaded_files_dir, bot_folder_name)
        os.makedirs(bot_folder_path, exist_ok=True)

        # فك ضغط الملف
        with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
            zip_ref.extractall(bot_folder_path)
        os.unlink(temp_zip_path) # حذف الملف المؤقت بعد فك الضغط

        # البحث عن ملف .py رئيسي
        python_files = [f for f in os.listdir(bot_folder_path) if f.endswith('.py')]
        if not python_files:
            bot.send_message(chat_id, "❌ **ملف ZIP لا يحتوي على أي ملفات Python (.py).** الرجاء التأكد من وجود ملف بوت بايثون واحد على الأقل داخل الـ ZIP.")
            shutil.rmtree(bot_folder_path) # حذف المجلد الفارغ
            bot.send_message(chat_id, "🚀 **لوحة التحكم الرئيسية:**", reply_markup=create_main_menu(user_id), parse_mode='Markdown')
            return

        # إذا كان هناك ملف .py واحد فقط، استخدمه كملف رئيسي
        if len(python_files) == 1:
            main_script_name = python_files[0]
            main_script_path = os.path.join(bot_folder_path, main_script_name)
            msg = bot.send_message(chat_id, f"✨ **تم استلام ملف ZIP الخاص بك بنجاح!**\n\n"
                                              f"تم الكشف عن `{main_script_name}` كملف البوت الرئيسي.\n\n"
                                              "الرجاء إرسال **اسم مستخدم البوت (@username)** الخاص بك (مثل `@MyAwesomeBot`) أو أي **اسم تعريفي** للبوت إذا لم يكن بوت تيليجرام.")
            bot.register_next_step_handler(msg, lambda m: start_bot_after_name(m, main_script_path, bot_folder_path, main_script_name, user_id))
        else:
            # إذا كان هناك عدة ملفات .py، اطلب من المستخدم تحديد الملف الرئيسي
            markup = types.InlineKeyboardMarkup()
            for py_file in python_files:
                markup.add(types.InlineKeyboardButton(py_file, callback_data=f"select_main_py_{bot_folder_name}_{py_file}"))
            bot.send_message(chat_id, "🤔 **تم اكتشاف عدة ملفات Python في ملف ZIP الخاص بك.**\n"
                                      "الرجاء اختيار الملف الرئيسي لبوتك:", reply_markup=markup)

            # تخزين معلومات مؤقتة للمستخدم لتحديد الملف الرئيسي
            bot.current_zip_upload_info = {
                user_id: {
                    'bot_folder_path': bot_folder_path,
                    'original_zip_name': file_name
                }
            }

    except zipfile.BadZipFile:
        bot.send_message(chat_id, "❌ **الملف المرفوع ليس ملف ZIP صالحًا.** الرجاء التأكد من أن الملف سليم وحاول مرة أخرى.")
        bot.send_message(chat_id, "🚀 **لوحة التحكم الرئيسية:**", reply_markup=create_main_menu(user_id), parse_mode='Markdown')
    except Exception as e:
        logger.error(f"خطأ أثناء معالجة ملف ZIP من المستخدم {user_id}: {e}")
        bot.send_message(chat_id, f"❌ **حدث خطأ أثناء معالجة ملف البوت الخاص بك.** الرجاء المحاولة مرة أخرى لاحقًا.")
        # حاول تنظيف المجلد إذا تم إنشاؤه جزئيًا
        if 'bot_folder_path' in locals() and os.path.exists(bot_folder_path):
            shutil.rmtree(bot_folder_path)
        bot.send_message(chat_id, "🚀 **لوحة التحكم الرئيسية:**", reply_markup=create_main_menu(user_id), parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('select_main_py_'))
def handle_main_py_selection(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id

    if user_id in banned_users:
        bot.answer_callback_query(call.id, "⛔ أنت محظور من استخدام هذا البوت.")
        bot.send_message(chat_id, "⛔ **أنت محظور من استخدام هذا البوت.**")
        return

    parts = call.data.split('_')
    # Parts will be: ['select', 'main', 'py', 'bot', 'user_id', 'timestamp', 'filename.py']
    # Reconstruct bot_folder_name from parts[3:6]
    bot_folder_name = f"{parts[3]}_{parts[4]}_{parts[5]}"
    main_script_name = "_".join(parts[6:])

    # Retrieve stored information
    if not hasattr(bot, 'current_zip_upload_info') or user_id not in bot.current_zip_upload_info:
        bot.answer_callback_query(call.id, "خطأ: لم يتم العثور على معلومات التحميل.")
        bot.edit_message_text(chat_id=chat_id, message_id=message_id, 
                              text="❌ **حدث خطأ غير متوقع.** يرجى المحاولة برفع الملف مرة أخرى.",
                              reply_markup=create_main_menu(user_id), parse_mode='Markdown')
        return

    stored_info = bot.current_zip_upload_info.pop(user_id) # Remove info after use
    bot_folder_path = stored_info['bot_folder_path']
    original_zip_name = stored_info['original_zip_name']

    main_script_path = os.path.join(bot_folder_path, main_script_name)

    if not os.path.exists(main_script_path):
        bot.answer_callback_query(call.id, "الملف المحدد غير موجود.")
        bot.edit_message_text(chat_id=chat_id, message_id=message_id, 
                              text="❌ **حدث خطأ:** الملف الرئيسي المحدد غير موجود. يرجى المحاولة برفع الملف مرة أخرى.",
                              reply_markup=create_main_menu(user_id), parse_mode='Markdown')
        shutil.rmtree(bot_folder_path) # Clean up
        return

    bot.answer_callback_query(call.id, f"تم اختيار {main_script_name} كملف رئيسي.")
    bot.edit_message_text(chat_id=chat_id, message_id=message_id, 
                          text=f"✨ **تم اختيار `{main_script_name}` كملف البوت الرئيسي بنجاح!**\n\n"
                                "الرجاء إرسال **اسم مستخدم البوت (@username)** الخاص بك (مثل `@MyAwesomeBot`) أو أي **اسم تعريفي** للبوت إذا لم يكن بوت تيليجرام.",
                          parse_mode='Markdown')
    bot.register_next_step_handler(call.message, lambda m: start_bot_after_name(m, main_script_path, bot_folder_path, main_script_name, user_id))


def start_bot_after_name(message, main_script_path, bot_folder_path, file_name, user_id):
    """يبدأ البوت بعد تلقي اسمه التعريفي أو اسم المستخدم."""
    chat_id = message.chat.id
    bot_username = message.text.strip()

    # التحقق من وجود ملف requirements.txt وتثبيت المكتبات
    requirements_path = os.path.join(bot_folder_path, 'requirements.txt')
    if os.path.exists(requirements_path):
        bot.send_message(chat_id, "📦 **جاري تثبيت مكتبات البوت من `requirements.txt`...** قد يستغرق هذا بعض الوقت.")
        try:
            # استخدام venv لضمان بيئة نظيفة وتجنب تعارضات المكتبات
            venv_path = os.path.join(bot_folder_path, '.venv')
            if not os.path.exists(venv_path):
                subprocess.check_call(['python3', '-m', 'venv', venv_path])

            pip_executable = os.path.join(venv_path, 'bin', 'pip') # For Linux/macOS
            if platform.system() == "Windows":
                pip_executable = os.path.join(venv_path, 'Scripts', 'pip.exe') # For Windows

            subprocess.check_call([pip_executable, 'install', '-r', requirements_path], cwd=bot_folder_path)
            bot.send_message(chat_id, "✅ **تم تثبيت المكتبات بنجاح!**")
        except subprocess.CalledProcessError as e:
            bot.send_message(chat_id, f"❌ **فشل تثبيت المكتبات من `requirements.txt`.**\n\n"
                                      f"يرجى التحقق من الملف والمحاولة مرة أخرى. تفاصيل الخطأ: `{e}`")
            shutil.rmtree(bot_folder_path) # حذف المجلد إذا فشل التثبيت
            remove_user_file_db(user_id, file_name, bot_folder_path) # إزالة من DB
            bot.send_message(chat_id, "🚀 **لوحة التحكم الرئيسية:**", reply_markup=create_main_menu(user_id), parse_mode='Markdown')
            logger.error(f"فشل تثبيت المكتبات للمستخدم {user_id} في {bot_folder_path}: {e}")
            return
        except Exception as e:
            bot.send_message(chat_id, f"❌ **حدث خطأ غير متوقع أثناء تثبيت المكتبات.**\n\n"
                                      f"تفاصيل الخطأ: `{e}`")
            shutil.rmtree(bot_folder_path) # حذف المجلد
            remove_user_file_db(user_id, file_name, bot_folder_path) # إزالة من DB
            bot.send_message(chat_id, "🚀 **لوحة التحكم الرئيسية:**", reply_markup=create_main_menu(user_id), parse_mode='Markdown')
            logger.error(f"خطأ غير متوقع أثناء تثبيت المكتبات للمستخدم {user_id} في {bot_folder_path}: {e}")
            return

    # إنشاء ملفات السجل الخاصة بهذا البوت
    log_file_stdout = os.path.join(bot_folder_path, 'stdout.log')
    log_file_stderr = os.path.join(bot_folder_path, 'stderr.log')

    # التأكد من أن مجلد العمل هو مجلد البوت
    try:
        # استخدام python3 من البيئة الافتراضية إذا كانت موجودة، وإلا استخدم النظام
        python_executable = os.path.join(venv_path, 'bin', 'python3') if 'venv_path' in locals() and os.path.exists(venv_path) else 'python3'
        if platform.system() == "Windows" and 'venv_path' in locals() and os.path.exists(venv_path):
             python_executable = os.path.join(venv_path, 'Scripts', 'python.exe')

        process = subprocess.Popen(
            [python_executable, main_script_path],
            cwd=bot_folder_path, # تعيين مجلد العمل هنا
            stdout=open(log_file_stdout, 'w'),
            stderr=open(log_file_stderr, 'w'),
            preexec_fn=os.setsid # لجعل العملية مستقلة عن البوت الرئيسي
        )
        process_key = str(uuid.uuid4()) # مفتاح فريد لعملية البوت

        bot_processes[process_key] = {
            'process': process,
            'folder_path': bot_folder_path,
            'bot_username': bot_username,
            'file_name': file_name,
            'owner_id': user_id,
            'log_file_stdout': log_file_stdout,
            'log_file_stderr': log_file_stderr,
            'start_time': datetime.now()
        }

        # حفظ حالة البوت في قاعدة البيانات
        save_bot_process_state(process_key, bot_folder_path, bot_username, file_name, user_id, log_file_stdout, log_file_stderr, datetime.now())

        if user_id not in user_files:
            user_files[user_id] = []
        user_files[user_id].append({'file_name': file_name, 'folder_path': bot_folder_path, 'bot_username': bot_username, 'process_key': process_key})
        save_user_file_db(user_id, file_name, bot_folder_path, bot_username)

        bot.send_message(chat_id, f"✅ **تم تشغيل بوتك بنجاح!**\n\n"
                                  f"**اسم البوت**: `{bot_username}`\n"
                                  f"**اسم الملف الرئيسي**: `{file_name}`\n"
                                  f"**مفتاح العملية**: `{process_key}`\n\n"
                                  "يمكنك إدارة بوتاتك من خلال زر **'بوتاتي'** في القائمة الرئيسية.", parse_mode='Markdown')
        logger.info(f"تم تشغيل البوت {bot_username} ({file_name}) للمستخدم {user_id} بـ Process Key: {process_key}")
        bot.send_message(chat_id, "🚀 **لوحة التحكم الرئيسية:**", reply_markup=create_main_menu(user_id), parse_mode='Markdown')

    except Exception as e:
        logger.error(f"خطأ أثناء تشغيل البوت {file_name} للمستخدم {user_id}: {e}")
        bot.send_message(chat_id, f"❌ **حدث خطأ أثناء تشغيل البوت الخاص بك.** يرجى التحقق من الكود والمحاولة مرة أخرى.\n\n"
                                  f"تفاصيل الخطأ: `{e}`")
        # حذف المجلد والملفات في حالة فشل التشغيل
        if os.path.exists(bot_folder_path):
            shutil.rmtree(bot_folder_path)
        # إزالة من user_files إذا كان قد أضيف
        if user_id in user_files:
            user_files[user_id] = [f for f in user_files[user_id] if f['folder_path'] != bot_folder_path]
        bot.send_message(chat_id, "🚀 **لوحة التحكم الرئيسية:**", reply_markup=create_main_menu(user_id), parse_mode='Markdown')

# --- وظائف إدارة البوتات للمستخدمين (My Bots) ---

def show_my_bots(chat_id, user_id, edit_message=False, message_id=None):
    """يعرض قائمة بوتات المستخدم مع خيارات الإدارة."""
    if user_id not in user_files or not user_files[user_id]:
        text = "🤷‍♂️ **ليس لديك أي بوتات مستضافة حالياً.**\n" \
               "يمكنك البدء برفع بوت جديد من خلال زر **'رفع ملف بوت'**."
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton('📤 رفع ملف بوت', callback_data='upload'))
        markup.add(types.InlineKeyboardButton('🔙 العودة للقائمة الرئيسية', callback_data='back_to_main'))

        if edit_message:
            bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=markup, parse_mode='Markdown')
        else:
            bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')
        return

    text = "🤖 **بوتاتك المستضافة:**\n\n"
    markup = types.InlineKeyboardMarkup()

    for file_info in user_files[user_id]:
        bot_username = file_info.get('bot_username', 'غير معروف')
        file_name = file_info['file_name']
        folder_path = file_info['folder_path']

        # البحث عن process_key في bot_processes بناءً على folder_path
        process_key = None
        for key, value in bot_processes.items():
            if value['folder_path'] == folder_path and value['owner_id'] == user_id:
                process_key = key
                break

        status = "🟢 يعمل" if process_key and bot_processes[process_key]['process'].poll() is None else "🔴 متوقف"
        uptime = "N/A"
        if process_key and bot_processes[process_key]['process'].poll() is None:
            start_time = bot_processes[process_key]['start_time']
            time_diff = datetime.now() - start_time
            days = time_diff.days
            hours = time_diff.seconds // 3600
            minutes = (time_diff.seconds % 3600) // 60
            uptime = f"{days} يوم, {hours} ساعة, {minutes} دقيقة"

        text += f"▪️ **اسم البوت**: `{bot_username}`\n"
        text += f"   **الملف**: `{file_name}`\n"
        text += f"   **الحالة**: {status}\n"
        text += f"   **مدة التشغيل**: {uptime}\n"
        text += f"   **مفتاح العملية**: `{process_key if process_key else 'غير متاح (متوقف)'}`\n\n"

        if process_key:
            markup.add(
                types.InlineKeyboardButton(f"📄 سجلات {bot_username}", callback_data=f"view_log_{process_key}"),
                types.InlineKeyboardButton(f"⏹️ إيقاف {bot_username}", callback_data=f"stop_bot_{process_key}"),
            )
            markup.add(
                types.InlineKeyboardButton(f"🔄 إعادة تشغيل {bot_username}", callback_data=f"restart_bot_{process_key}"),
                types.InlineKeyboardButton(f"🗑️ حذف {bot_username}", callback_data=f"delete_bot_{process_key}")
            )
        else:
            # إذا كان البوت متوقفًا (لا يوجد process_key)، فقط عرض خيار الحذف وربما زر "ابدأ" إذا كان الملف لا يزال موجودًا
            # (لم يتم طلب زر "ابدأ" بعد، لكن يمكن إضافته هنا)
            markup.add(types.InlineKeyboardButton(f"🗑️ حذف {bot_username}", callback_data=f"delete_bot_{file_info['folder_path'].split('/')[-1]}")) # هنا نستخدم اسم المجلد كمفتاح مؤقت للحذف
            # يمكن إضافة زر "تشغيل" هنا إذا أردت السماح للمستخدمين بإعادة تشغيل البوتات المتوقفة يدوياً.

    markup.add(types.InlineKeyboardButton('🔙 العودة للقائمة الرئيسية', callback_data='back_to_main'))

    if edit_message:
        bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=markup, parse_mode='Markdown')
    else:
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')

def view_bot_logs(chat_id, user_id, process_key):
    """يعرض سجلات البوت للمستخدم."""
    if process_key not in bot_processes or bot_processes[process_key]['owner_id'] != user_id:
        bot.send_message(chat_id, "⛔ **ليس لديك صلاحية لعرض سجلات هذا البوت أو أن البوت غير موجود/متوقف.**")
        return

    log_file_stdout = bot_processes[process_key]['log_file_stdout']
    log_file_stderr = bot_processes[process_key]['log_file_stderr']
    bot_username = bot_processes[process_key]['bot_username']

    log_content = ""
    try:
        with open(log_file_stdout, 'r', encoding='utf-8', errors='ignore') as f:
            log_content += f.read()
        with open(log_file_stderr, 'r', encoding='utf-8', errors='ignore') as f:
            log_content += f.read()

        if not log_content.strip():
            log_content = "💡 **لا توجد سجلات لعرضها بعد أو أن البوت لم يقم بإخراج أي شيء.**"

        # Telegram message limit is 4096 characters for text, 1024 for caption
        if len(log_content) > 4000:
            # Send as document if too long
            with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix=".txt", encoding='utf-8') as temp_log_file:
                temp_log_file.write(log_content)
                temp_log_file_path = temp_log_file.name

            with open(temp_log_file_path, 'rb') as doc:
                bot.send_document(chat_id, doc, caption=f"📝 **سجلات البوت {bot_username} (كاملة)**", parse_mode='Markdown')
            os.unlink(temp_log_file_path)
            bot.send_message(chat_id, "✅ **تم إرسال سجلات البوت كملف نصي.**")
        else:
            bot.send_message(chat_id, f"📝 **سجلات البوت {bot_username}:**\n\n```\n{log_content}\n```", parse_mode='Markdown')

    except FileNotFoundError:
        bot.send_message(chat_id, "❌ **لم يتم العثور على ملفات السجل لهذا البوت.** قد يكون البوت لم يبدأ بعد أو تم حذفه.")
    except Exception as e:
        logger.error(f"خطأ أثناء قراءة سجلات البوت {process_key} للمستخدم {user_id}: {e}")
        bot.send_message(chat_id, f"❌ **حدث خطأ أثناء محاولة جلب سجلات البوت.**")

    bot.send_message(chat_id, "⚙️ **خيارات البوت:**", reply_markup=create_my_bots_inline_markup(user_id, process_key, bot_username), parse_mode='Markdown')

def stop_user_bot(chat_id, user_id, process_key):
    """يوقف بوت المستخدم."""
    if process_key not in bot_processes or bot_processes[process_key]['owner_id'] != user_id:
        bot.send_message(chat_id, "⛔ **ليس لديك صلاحية لإيقاف هذا البوت أو أن البوت غير موجود/متوقف.**")
        return

    try:
        process_info = bot_processes[process_key]
        process = process_info['process']
        bot_username = process_info['bot_username']

        # إنهاء العملية بgracefully
        if platform.system() == "Windows":
            process.terminate() # SIGTERM for Windows
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM) # Send SIGTERM to the process group

        process.wait(timeout=10) # انتظر حتى يتم إنهاء العملية بحد أقصى 10 ثواني
        if process.poll() is None: # إذا لم يتم إنهاؤه، أرسل SIGKILL
            if platform.system() == "Windows":
                process.kill() # SIGKILL for Windows
            else:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            process.wait()

        del bot_processes[process_key]
        remove_bot_process_state(process_key) # إزالة من قاعدة البيانات
        bot.send_message(chat_id, f"⏹️ **تم إيقاف البوت** `{bot_username}` **بنجاح.**")
        logger.info(f"تم إيقاف البوت {bot_username} (ID: {process_key}) للمستخدم {user_id}.")
        show_my_bots(chat_id, user_id) # تحديث قائمة البوتات
    except ProcessLookupError:
        bot.send_message(chat_id, f"⚠️ **البوت كان متوقفًا بالفعل أو أن العملية لم تعد موجودة.**")
        del bot_processes[process_key] # إزالته من القائمة
        remove_bot_process_state(process_key) # إزالة من قاعدة البيانات
        logger.warning(f"البوت {process_key} للمستخدم {user_id} كان متوقفًا بالفعل. تمت إزالته من قائمة العمليات الجارية.")
        show_my_bots(chat_id, user_id) # تحديث قائمة البوتات
    except Exception as e:
        logger.error(f"خطأ أثناء إيقاف البوت {process_key} للمستخدم {user_id}: {e}")
        bot.send_message(chat_id, f"❌ **حدث خطأ أثناء محاولة إيقاف البوت.**")
        show_my_bots(chat_id, user_id) # تحديث قائمة البوتات

def delete_user_bot(chat_id, user_id, process_key_or_folder_name):
    """يحذف بوت المستخدم وملفاته."""
    process_info = None
    folder_to_delete = None
    file_name_to_remove = None
    bot_username_to_remove = None

    # Try to find by process_key first
    if process_key_or_folder_name in bot_processes and bot_processes[process_key_or_folder_name]['owner_id'] == user_id:
        process_info = bot_processes[process_key_or_folder_name]
        folder_to_delete = process_info['folder_path']
        file_name_to_remove = process_info['file_name']
        bot_username_to_remove = process_info['bot_username']
        # Stop the bot if it's running
        if process_info['process'].poll() is None:
            stop_user_bot(chat_id, user_id, process_key_or_folder_name) # This will also remove from bot_processes and DB
        else:
            del bot_processes[process_key_or_folder_name] # Remove from global dict if already stopped
            remove_bot_process_state(process_key_or_folder_name) # Ensure removal from DB
    else:
        # If not found by process_key, try to find by folder_name (from `show_my_bots` where process_key might not exist)
        found_in_user_files = False
        if user_id in user_files:
            for i, file_data in enumerate(user_files[user_id]):
                if file_data['folder_path'].endswith(process_key_or_folder_name): # process_key_or_folder_name in this context is the folder name
                    folder_to_delete = file_data['folder_path']
                    file_name_to_remove = file_data['file_name']
                    bot_username_to_remove = file_data['bot_username']
                    found_in_user_files = True
                    # Remove from user_files now
                    del user_files[user_id][i]
                    remove_user_file_db(user_id, file_name_to_remove, folder_to_delete)
                    break

        if not found_in_user_files:
            bot.send_message(chat_id, "⛔ **لم يتم العثور على هذا البوت أو ليس لديك صلاحية لحذفه.**")
            return

    if folder_to_delete and os.path.exists(folder_to_delete):
        try:
            shutil.rmtree(folder_to_delete)
            # Remove from user_files if it wasn't already removed by stop_user_bot or the above loop
            if user_id in user_files:
                user_files[user_id] = [f for f in user_files[user_id] if f['folder_path'] != folder_to_delete]

            # Ensure removal from DB as well
            if file_name_to_remove:
                remove_user_file_db(user_id, file_name_to_remove, folder_to_delete)

            bot.send_message(chat_id, f"🗑️ **تم حذف البوت** `{bot_username_to_remove if bot_username_to_remove else file_name_to_remove}` **وجميع ملفاته بنجاح.**")
            logger.info(f"تم حذف البوت {bot_username_to_remove} ({file_name_to_remove}) في المسار {folder_to_delete} للمستخدم {user_id}.")
            show_my_bots(chat_id, user_id) # تحديث قائمة البوتات
        except Exception as e:
            logger.error(f"خطأ أثناء حذف مجلد البوت {folder_to_delete} للمستخدم {user_id}: {e}")
            bot.send_message(chat_id, f"❌ **حدث خطأ أثناء محاولة حذف ملفات البوت.**")
            show_my_bots(chat_id, user_id) # تحديث قائمة البوتات
    else:
        bot.send_message(chat_id, "⚠️ **لم يتم العثور على ملفات البوت المراد حذفها.** قد يكون تم حذفها بالفعل.")
        # Ensure it's removed from user_files and DB even if folder is missing
        if user_id in user_files and file_name_to_remove and folder_to_delete:
            user_files[user_id] = [f for f in user_files[user_id] if f['folder_path'] != folder_to_delete]
            remove_user_file_db(user_id, file_name_to_remove, folder_to_delete)
        show_my_bots(chat_id, user_id) # تحديث قائمة البوتات

def restart_user_bot(chat_id, user_id, process_key):
    """يعيد تشغيل بوت المستخدم."""
    if process_key not in bot_processes or bot_processes[process_key]['owner_id'] != user_id:
        bot.send_message(chat_id, "⛔ **ليس لديك صلاحية لإعادة تشغيل هذا البوت أو أن البوت غير موجود/متوقف.**")
        return

    process_info = bot_processes[process_key]
    bot_username = process_info['bot_username']
    file_name = process_info['file_name']
    folder_path = process_info['folder_path']
    main_script_path = os.path.join(folder_path, file_name)
    log_file_stdout = process_info['log_file_stdout']
    log_file_stderr = process_info['log_file_stderr']

    bot.send_message(chat_id, f"🔄 **جاري إعادة تشغيل البوت** `{bot_username}`...")

    try:
        # إيقاف البوت أولاً
        if process_info['process'].poll() is None: # إذا كان يعمل
            if platform.system() == "Windows":
                process_info['process'].terminate()
            else:
                os.killpg(os.getpgid(process_info['process'].pid), signal.SIGTERM)
            process_info['process'].wait(timeout=10)
            if process_info['process'].poll() is None:
                if platform.system() == "Windows":
                    process_info['process'].kill()
                else:
                    os.killpg(os.getpgid(process_info['process'].pid), signal.SIGKILL)
                process_info['process'].wait()

        del bot_processes[process_key]
        remove_bot_process_state(process_key)

        # إعادة تشغيل البوت
        # استخدام venv لضمان بيئة نظيفة وتجنب تعارضات المكتبات
        venv_path = os.path.join(folder_path, '.venv')
        python_executable = os.path.join(venv_path, 'bin', 'python3') if os.path.exists(venv_path) else 'python3'
        if platform.system() == "Windows" and os.path.exists(venv_path):
             python_executable = os.path.join(venv_path, 'Scripts', 'python.exe')

        new_process = subprocess.Popen(
            [python_executable, main_script_path],
            cwd=folder_path,
            stdout=open(log_file_stdout, 'w'), # مسح السجلات القديمة عند إعادة التشغيل
            stderr=open(log_file_stderr, 'w'),
            preexec_fn=os.setsid
        )

        bot_processes[process_key] = { # إعادة استخدام نفس المفتاح للتبسيط
            'process': new_process,
            'folder_path': folder_path,
            'bot_username': bot_username,
            'file_name': file_name,
            'owner_id': user_id,
            'log_file_stdout': log_file_stdout,
            'log_file_stderr': log_file_stderr,
            'start_time': datetime.now()
        }
        save_bot_process_state(process_key, folder_path, bot_username, file_name, user_id, log_file_stdout, log_file_stderr, datetime.now())

        bot.send_message(chat_id, f"✅ **تمت إعادة تشغيل البوت** `{bot_username}` **بنجاح!**")
        logger.info(f"تمت إعادة تشغيل البوت {bot_username} (ID: {process_key}) للمستخدم {user_id}.")
        show_my_bots(chat_id, user_id) # تحديث قائمة البوتات
    except Exception as e:
        logger.error(f"خطأ أثناء إعادة تشغيل البوت {process_key} للمستخدم {user_id}: {e}")
        bot.send_message(chat_id, f"❌ **حدث خطأ أثناء محاولة إعادة تشغيل البوت.**\n\nتفاصيل الخطأ: `{e}`")
        show_my_bots(chat_id, user_id) # تحديث قائمة البوتات

def create_my_bots_inline_markup(user_id, process_key, bot_username):
    """ينشئ Inline Keyboard للبوتات الفردية."""
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(f"📄 سجلات {bot_username}", callback_data=f"view_log_{process_key}"),
        types.InlineKeyboardButton(f"⏹️ إيقاف {bot_username}", callback_data=f"stop_bot_{process_key}")
    )
    markup.add(
        types.InlineKeyboardButton(f"🔄 إعادة تشغيل {bot_username}", callback_data=f"restart_bot_{process_key}"),
        types.InlineKeyboardButton(f"🗑️ حذف {bot_username}", callback_data=f"delete_bot_{process_key}")
    )
    markup.add(types.InlineKeyboardButton('🔙 العودة إلى بوتاتي', callback_data='back_to_my_bots'))
    return markup


# --- وظائف عامة للبوت ---

def check_bot_speed(chat_id):
    """يفحص سرعة استجابة البوت."""
    start_time = time.time()
    bot.send_chat_action(chat_id, 'typing')
    end_time = time.time()
    ping_time = (end_time - start_time) * 1000  # Convert to milliseconds
    bot.send_message(chat_id, f"⚡ **سرعة استجابة البوت**: `{ping_time:.2f} ms`", parse_mode='Markdown')
    logger.info(f"تم فحص سرعة البوت في الدردشة {chat_id}: {ping_time:.2f} ms.")

def send_global_stats(chat_id):
    """يرسل إحصائيات عامة عن البوت والمستخدمين."""
    total_users = len(active_users)
    total_hosted_bots = len(bot_processes)

    # حساب عدد البوتات لكل مستخدم (مثال، يمكنك تعديلها لتكون أكثر تفصيلاً)
    user_bot_counts = {}
    for user_id in user_files:
        user_bot_counts[user_id] = len(user_files[user_id])

    # حساب إجمالي البوتات المرفوعة (بما في ذلك المتوقفة)
    total_uploaded_bots_count = sum(len(files) for files in user_files.values())

    stats_message = "📊 **إحصائيات عامة:**\n\n"
    stats_message += f"👥 **إجمالي المستخدمين النشطين**: `{total_users}`\n"
    stats_message += f"🤖 **إجمالي البوتات قيد التشغيل**: `{total_hosted_bots}`\n"
    stats_message += f"📁 **إجمالي البوتات المرفوعة (نشطة أو متوقفة)**: `{total_uploaded_bots_count}`\n"

    # يمكنك إضافة المزيد من الإحصائيات هنا، مثل:
    # - عدد البوتات المتوقفة
    # - المستخدمون الأكثر استضافة للبوتات

    bot.send_message(chat_id, stats_message, parse_mode='Markdown')
    logger.info(f"تم إرسال الإحصائيات العامة إلى الدردشة {chat_id}.")

# --- وظائف المطور (Admin Functions) ---

def send_security_report(chat_id):
    """يرسل تقرير الأمان للمطور."""
    report_message = "🔐 **تقرير الأمان:**\n\n"

    # Warnings Summary
    total_warnings = sum(len(warnings) for warnings in user_warnings.values())
    report_message += f"⚠️ **إجمالي التحذيرات المسجلة**: `{total_warnings}`\n"

    if total_warnings > 0:
        report_message += "--- **تفاصيل التحذيرات الأخيرة** ---\n"
        # عرض آخر 5 تحذيرات
        recent_warnings = []
        for user_id, warnings in user_warnings.items():
            for warning in warnings:
                recent_warnings.append((user_id, warning))

        recent_warnings.sort(key=lambda x: datetime.fromisoformat(x[1]['timestamp']), reverse=True)

        for i, (user_id, warning) in enumerate(recent_warnings[:5]):
            report_message += f"▪️ **المستخدم**: `{user_id}`\n"
            report_message += f"   **السبب**: {warning['reason']}\n"
            report_message += f"   **الملف**: `{warning['file_name'] if warning['file_name'] else 'غير محدد'}`\n"
            report_message += f"   **الوقت**: {datetime.fromisoformat(warning['timestamp']).strftime('%Y-%m-%d %H:%M:%S')}\n"
            if i < 4 and i < len(recent_warnings) -1:
                report_message += "-\n"
    else:
        report_message += "✅ **لا توجد تحذيرات أمان مسجلة حالياً.**\n"

    # Quarantined Files Summary
    quarantined_files = os.listdir(quarantined_files_dir)
    report_message += f"\n📦 **الملفات في الحجر الصحي**: `{len(quarantined_files)}`\n"
    if quarantined_files:
        report_message += "--- **أسماء الملفات المعزولة** ---\n"
        for i, f in enumerate(quarantined_files[:5]): # عرض أول 5 ملفات
            report_message += f"▪️ `{f}`\n"
            if i < 4 and i < len(quarantined_files) -1:
                report_message += "-\n"
        if len(quarantined_files) > 5:
            report_message += f"... والمزيد ({len(quarantined_files) - 5} ملفات إضافية).\n"
    else:
        report_message += "✅ **لا توجد ملفات في الحجر الصحي حالياً.**\n"

    bot.send_message(chat_id, report_message, parse_mode='Markdown')
    logger.info(f"تم إرسال تقرير الأمان إلى المطور {chat_id}.")

def handle_broadcast_message(message):
    """يتعامل مع رسالة الإذاعة من المطور."""
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        bot.send_message(message.chat.id, "⛔ **ليس لديك صلاحية لإجراء هذه العملية.**")
        return

    broadcast_text = message.text
    successful_sends = 0
    failed_sends = 0

    bot.send_message(message.chat.id, f"📢 **جاري إرسال رسالة الإذاعة إلى {len(active_users)} مستخدم...**")

    for user in active_users:
        try:
            bot.send_message(user, f"📢 **رسالة من المطور:**\n\n{broadcast_text}", parse_mode='Markdown')
            successful_sends += 1
        except Exception as e:
            logger.error(f"فشل إرسال رسالة الإذاعة للمستخدم {user}: {e}")
            failed_sends += 1
            if "blocked by the user" in str(e).lower() or "user not found" in str(e).lower():
                # إزالة المستخدمين الذين قاموا بحظر البوت من قائمة المستخدمين النشطين وقاعدة البيانات
                active_users.discard(user)
                conn = sqlite3.connect('bot_data.db')
                c = conn.cursor()
                c.execute('DELETE FROM active_users WHERE user_id = ?', (user,))
                conn.commit()
                conn.close()
                logger.info(f"تم إزالة المستخدم {user} من قائمة المستخدمين النشطين (قام بحظر البوت).")

    bot.send_message(message.chat.id, f"✅ **اكتملت عملية الإذاعة!**\n\n"
                                      f"**الرسائل المرسلة بنجاح**: `{successful_sends}`\n"
                                      f"**الرسائل الفاشلة**: `{failed_sends}`", parse_mode='Markdown')
    logger.info(f"اكتملت عملية الإذاعة. نجاح: {successful_sends}, فشل: {failed_sends}.")
    bot.send_message(message.chat.id, "🚀 **لوحة التحكم الرئيسية:**", reply_markup=create_main_menu(user_id), parse_mode='Markdown')

def toggle_bot_lock(chat_id, lock_state):
    """يقوم بقفل/فتح البوت."""
    global bot_locked
    bot_locked = lock_state
    status_text = "مقفل" if lock_state else "مفتوح"
    bot.send_message(chat_id, f"🔒 **تم جعل البوت** `{status_text}` **للمستخدمين العاديين.**", parse_mode='Markdown')
    logger.info(f"المطور {chat_id} قام بجعل البوت {status_text}.")
    bot.send_message(chat_id, "🚀 **لوحة التحكم الرئيسية:**", reply_markup=create_main_menu(ADMIN_ID), parse_mode='Markdown')

def show_manage_users_menu(chat_id, edit_message=False, message_id=None):
    """يعرض قائمة إدارة المستخدمين للمطور."""
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('👥 قائمة المستخدمين', callback_data='list_users'))
    markup.add(types.InlineKeyboardButton('🚫 حظر مستخدم', callback_data='ban_user'))
    markup.add(types.InlineKeyboardButton('✅ فك حظر مستخدم', callback_data='unban_user'))
    markup.add(types.InlineKeyboardButton('⚠️ عرض تحذيرات مستخدم', callback_data='view_warnings'))
    markup.add(types.InlineKeyboardButton('🗑️ مسح تحذيرات مستخدم', callback_data='clear_warnings'))

    current_block_status = "ايقاف قبول مستخدمين جدد" if not block_new_users else "قبول مستخدمين جدد"
    current_block_callback = "block_new_users" if not block_new_users else "allow_new_users"
    markup.add(types.InlineKeyboardButton(current_block_status, callback_data=current_block_callback))

    markup.add(types.InlineKeyboardButton('🔙 العودة للقائمة الرئيسية', callback_data='back_to_main'))

    text = "🔨 **إدارة المستخدمين:**\n\n" \
           f"حالة قبول المستخدمين الجدد: {'🚫 متوقفة' if block_new_users else '✅ مفعلة'}"

    if edit_message:
        bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=markup, parse_mode='Markdown')
    else:
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')

def list_all_users(chat_id):
    """يسرد جميع المستخدمين النشطين والمحظورين للمطور."""
    active_users_list = sorted(list(active_users))
    banned_users_list = sorted(list(banned_users))

    message_text = "👥 **قائمة المستخدمين:**\n\n"

    message_text += "--- **المستخدمون النشطون** ---\n"
    if active_users_list:
        for user_id in active_users_list:
            message_text += f"▪️ `{user_id}`\n"
    else:
        message_text += "لا يوجد مستخدمون نشطون.\n"

    message_text += "\n--- **المستخدمون المحظورون** ---\n"
    if banned_users_list:
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        for user_id in banned_users_list:
            c.execute('SELECT reason FROM banned_users WHERE user_id = ?', (user_id,))
            result = c.fetchone()
            reason = result[0] if result else "غير محدد"
            message_text += f"▪️ `{user_id}` (السبب: {reason})\n"
        conn.close()
    else:
        message_text += "لا يوجد مستخدمون محظورون.\n"

    bot.send_message(chat_id, message_text, parse_mode='Markdown')
    show_manage_users_menu(chat_id)

def handle_ban_user_id(message):
    """يتعامل مع معرف المستخدم المراد حظره."""
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        bot.send_message(message.chat.id, "⛔ **ليس لديك صلاحية.**")
        return

    try:
        user_to_ban_id = int(message.text.strip())
        if user_to_ban_id == ADMIN_ID:
            bot.send_message(message.chat.id, "🚫 **لا يمكنك حظر نفسك يا مطور!**")
            show_manage_users_menu(message.chat.id)
            return

        bot.send_message(message.chat.id, f"📝 **الرجاء إرسال سبب حظر المستخدم** `{user_to_ban_id}`.")
        bot.register_next_step_handler(message, lambda m: confirm_ban_user(m, user_to_ban_id))

    except ValueError:
        bot.send_message(message.chat.id, "❌ **معرف المستخدم غير صالح.** الرجاء إدخال رقم صحيح.")
        show_manage_users_menu(message.chat.id)

def confirm_ban_user(message, user_to_ban_id):
    """يؤكد حظر المستخدم بعد تلقي السبب."""
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        bot.send_message(message.chat.id, "⛔ **ليس لديك صلاحية.**")
        return

    reason = message.text.strip()
    if not reason:
        reason = "لم يتم تحديد سبب"

    if user_to_ban_id in banned_users:
        bot.send_message(message.chat.id, f"⚠️ **المستخدم** `{user_to_ban_id}` **محظور بالفعل.**")
        show_manage_users_menu(message.chat.id)
        return

    ban_user(user_to_ban_id, reason)
    # إيقاف وحذف أي بوتات لهذا المستخدم
    user_bots_to_stop = [k for k, v in bot_processes.items() if v['owner_id'] == user_to_ban_id]
    for key in user_bots_to_stop:
        # Pass chat_id of the admin here, not the banned user's chat_id
        stop_user_bot(message.chat.id, user_to_ban_id, key) # This will stop and remove from bot_processes and DB

    # Remove files from disk
    if user_to_ban_id in user_files:
        for file_info in list(user_files[user_to_ban_id]): # Iterate over a copy
            folder_path = file_info['folder_path']
            if os.path.exists(folder_path):
                shutil.rmtree(folder_path)
                logger.info(f"تم حذف مجلد البوت {folder_path} للمستخدم المحظور {user_to_ban_id}.")
        del user_files[user_to_ban_id] # Clear all user files from memory
        # Remove from DB if any entries remain (stop_user_bot might have removed some)
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute('DELETE FROM user_files WHERE user_id = ?', (user_to_ban_id,))
        conn.commit()
        conn.close()

    # Remove from active users if they were active
    if user_to_ban_id in active_users:
        active_users.remove(user_to_ban_id)
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute('DELETE FROM active_users WHERE user_id = ?', (user_to_ban_id,))
        conn.commit()
        conn.close()

    bot.send_message(message.chat.id, f"✅ **تم حظر المستخدم** `{user_to_ban_id}` **بنجاح!**\n"
                                      f"**السبب**: `{reason}`\n"
                                      f"**تم إيقاف وحذف جميع بوتاتهم تلقائياً.**", parse_mode='Markdown')

    # Try to notify the banned user (if they haven't blocked the bot)
    try:
        bot.send_message(user_to_ban_id, "⛔ **لقد تم حظرك من استخدام هذا البوت.**\n"
                                        f"**السبب**: `{reason}`\n"
                                        "جميع بوتاتك المستضافة تم إيقافها وحذفها.", parse_mode='Markdown')
    except Exception as e:
        logger.warning(f"فشل إرسال إشعار الحظر للمستخدم {user_to_ban_id}: {e}")

    show_manage_users_menu(message.chat.id)


def handle_unban_user_id(message):
    """يتعامل مع معرف المستخدم المراد فك حظره."""
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        bot.send_message(message.chat.id, "⛔ **ليس لديك صلاحية.**")
        return

    try:
        user_to_unban_id = int(message.text.strip())

        if unban_user(user_to_unban_id):
            bot.send_message(message.chat.id, f"✅ **تم فك حظر المستخدم** `{user_to_unban_id}` **بنجاح!**", parse_mode='Markdown')
        else:
            bot.send_message(message.chat.id, f"⚠️ **المستخدم** `{user_to_unban_id}` **ليس محظوراً.**", parse_mode='Markdown')

        show_manage_users_menu(message.chat.id)

    except ValueError:
        bot.send_message(message.chat.id, "❌ **معرف المستخدم غير صالح.** الرجاء إدخال رقم صحيح.")
        show_manage_users_menu(message.chat.id)

def handle_view_user_warnings(message):
    """يتعامل مع معرف المستخدم لعرض تحذيراته."""
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        bot.send_message(message.chat.id, "⛔ **ليس لديك صلاحية.**")
        return

    try:
        target_user_id = int(message.text.strip())

        warnings_for_user = user_warnings.get(target_user_id, [])
        if not warnings_for_user:
            bot.send_message(message.chat.id, f"✅ **المستخدم** `{target_user_id}` **ليس لديه أي تحذيرات مسجلة.**", parse_mode='Markdown')
            show_manage_users_menu(message.chat.id)
            return

        warning_text = f"⚠️ **تحذيرات المستخدم** `{target_user_id}`:\n\n"
        for i, warning in enumerate(warnings_for_user):
            warning_text += f"▪️ **السبب**: {warning['reason']}\n"
            warning_text += f"   **الملف**: `{warning['file_name'] if warning['file_name'] else 'غير محدد'}`\n"
            warning_text += f"   **الوقت**: {datetime.fromisoformat(warning['timestamp']).strftime('%Y-%m-%d %H:%M:%S')}\n"
            if i < len(warnings_for_user) - 1:
                warning_text += "-\n"

        bot.send_message(message.chat.id, warning_text, parse_mode='Markdown')
        show_manage_users_menu(message.chat.id)

    except ValueError:
        bot.send_message(message.chat.id, "❌ **معرف المستخدم غير صالح.** الرجاء إدخال رقم صحيح.")
        show_manage_users_menu(message.chat.id)

def handle_clear_user_warnings(message):
    """يتعامل مع معرف المستخدم لمسح تحذيراته."""
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        bot.send_message(message.chat.id, "⛔ **ليس لديك صلاحية.**")
        return

    try:
        target_user_id = int(message.text.strip())

        if target_user_id in user_warnings:
            del user_warnings[target_user_id]
            conn = sqlite3.connect('bot_data.db')
            c = conn.cursor()
            c.execute('DELETE FROM user_warnings WHERE user_id = ?', (target_user_id,))
            conn.commit()
            conn.close()
            bot.send_message(message.chat.id, f"🗑️ **تم مسح جميع التحذيرات للمستخدم** `{target_user_id}` **بنجاح!**", parse_mode='Markdown')
            logger.info(f"المطور {user_id} مسح تحذيرات المستخدم {target_user_id}.")
        else:
            bot.send_message(message.chat.id, f"⚠️ **المستخدم** `{target_user_id}` **ليس لديه أي تحذيرات لمسحها.**", parse_mode='Markdown')

        show_manage_users_menu(message.chat.id)

    except ValueError:
        bot.send_message(message.chat.id, "❌ **معرف المستخدم غير صالح.** الرجاء إدخال رقم صحيح.")
        show_manage_users_menu(message.chat.id)

def toggle_block_new_users(chat_id, block_state):
    """يتحكم في إمكانية انضمام مستخدمين جدد."""
    global block_new_users
    block_new_users = block_state
    status_text = "متوقفة (لن يتمكن مستخدمون جدد من الانضمام)" if block_state else "مفعلة (يمكن للمستخدمين الجدد الانضمام)"
    bot.send_message(chat_id, f"🌐 **حالة قبول المستخدمين الجدد: {status_text}.**", parse_mode='Markdown')
    logger.info(f"المطور {chat_id} قام بتعيين قبول المستخدمين الجدد إلى: {status_text}.")
    show_manage_users_menu(chat_id)

def show_manage_hosted_bots_menu(chat_id, edit_message=False, message_id=None):
    """يعرض قائمة إدارة البوتات المستضافة للمطور."""
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('🤖 قائمة كل البوتات', callback_data='list_all_hosted_bots'))
    markup.add(types.InlineKeyboardButton('⏹️ إيقاف بوت بالـ Key', callback_data='stop_bot_admin'))
    markup.add(types.InlineKeyboardButton('🗑️ حذف بوت بالـ Key', callback_data='delete_bot_admin'))
    markup.add(types.InlineKeyboardButton('📝 عرض سجلات بوت بالـ Key', callback_data='view_bot_logs_admin'))
    markup.add(types.InlineKeyboardButton('🔙 العودة للقائمة الرئيسية', callback_data='back_to_main'))

    text = "⚙️ **إدارة البوتات المستضافة:**\n\n" \
           "هنا يمكنك التحكم في جميع البوتات التي يستضيفها المستخدمون."

    if edit_message:
        bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=markup, parse_mode='Markdown')
    else:
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')

def list_all_hosted_bots_admin(chat_id):
    """يسرد جميع البوتات المستضافة حالياً (قيد التشغيل) للمطور."""
    if not bot_processes:
        bot.send_message(chat_id, "🤷‍♂️ **لا توجد بوتات قيد التشغيل حالياً.**")
        show_manage_hosted_bots_menu(chat_id)
        return

    message_text = "🤖 **قائمة البوتات المستضافة قيد التشغيل:**\n\n"
    sorted_processes = sorted(bot_processes.items(), key=lambda item: item[1]['start_time'], reverse=True)

    for process_key, info in sorted_processes:
        bot_username = info['bot_username']
        file_name = info['file_name']
        owner_id = info['owner_id']
        start_time = info['start_time']

        time_diff = datetime.now() - start_time
        days = time_diff.days
        hours = time_diff.seconds // 3600
        minutes = (time_diff.seconds % 3600) // 60
        uptime = f"{days} يوم, {hours} ساعة, {minutes} دقيقة"

        status = "🟢 يعمل" if info['process'].poll() is None else "🔴 متوقف (يجب إيقافه يدوياً أو حذفه)"

        message_text += f"▪️ **اسم البوت**: `{bot_username}`\n"
        message_text += f"   **الملف**: `{file_name}`\n"
        message_text += f"   **المستخدم**: `{owner_id}`\n"
        message_text += f"   **الحالة**: {status}\n"
        message_text += f"   **مدة التشغيل**: {uptime}\n"
        message_text += f"   **مفتاح العملية**: `{process_key}`\n\n"

    bot.send_message(chat_id, message_text, parse_mode='Markdown')
    show_manage_hosted_bots_menu(chat_id)

def handle_stop_bot_by_key_admin(message):
    """يتعامل مع مفتاح العملية لإيقاف بوت من قبل المطور."""
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        bot.send_message(message.chat.id, "⛔ **ليس لديك صلاحية.**")
        return

    process_key = message.text.strip()

    if process_key not in bot_processes:
        bot.send_message(message.chat.id, "❌ **مفتاح العملية غير صحيح أو البوت غير موجود/متوقف.**")
        show_manage_hosted_bots_menu(message.chat.id)
        return

    owner_id = bot_processes[process_key]['owner_id']
    stop_user_bot(message.chat.id, owner_id, process_key) # Use owner_id for permissions check in stop_user_bot
    show_manage_hosted_bots_menu(message.chat.id)

def handle_delete_bot_by_key_admin(message):
    """يتعامل مع مفتاح العملية لحذف بوت من قبل المطور."""
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        bot.send_message(message.chat.id, "⛔ **ليس لديك صلاحية.**")
        return

    process_key = message.text.strip()

    # Check if process_key is valid
    if process_key in bot_processes:
        owner_id = bot_processes[process_key]['owner_id']
        delete_user_bot(message.chat.id, owner_id, process_key) # Uses owner_id for permissions logic
    else:
        # If not found in bot_processes, try to find in user_files by folder name or a known identifier
        # This part requires a mapping if process_key is not always equal to folder_name suffix
        # For simplicity, if process_key is not in bot_processes, we assume it might be a folder name suffix
        # as used in delete_user_bot for non-running bots
        found_in_user_files = False
        for u_id, files in user_files.items():
            for i, file_info in enumerate(files):
                # Check if process_key matches any part of the folder_path (like the unique identifier)
                if process_key in file_info['folder_path']:
                    owner_id = u_id
                    delete_user_bot(message.chat.id, owner_id, file_info['folder_path'].split('/')[-1]) # Pass the folder name suffix
                    found_in_user_files = True
                    break
            if found_in_user_files:
                break

        if not found_in_user_files:
            bot.send_message(message.chat.id, "❌ **مفتاح العملية غير صحيح أو البوت غير موجود.**")

    show_manage_hosted_bots_menu(message.chat.id)

def handle_view_bot_logs_admin(message):
    """يتعامل مع مفتاح العملية لعرض سجلات بوت من قبل المطور."""
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        bot.send_message(message.chat.id, "⛔ **ليس لديك صلاحية.**")
        return

    process_key = message.text.strip()

    if process_key not in bot_processes:
        bot.send_message(message.chat.id, "❌ **مفتاح العملية غير صحيح أو البوت غير موجود/متوقف.**")
        show_manage_hosted_bots_menu(message.chat.id)
        return

    owner_id = bot_processes[process_key]['owner_id']
    view_bot_logs(message.chat.id, owner_id, process_key) # Use owner_id for permissions check
    # Don't show manage_hosted_bots_menu immediately after logs, let user click back from log menu.

def send_server_stats(chat_id):
    """يرسل إحصائيات استخدام الخادم للمطور."""
    cpu_percent = psutil.cpu_percent(interval=1)
    ram_info = psutil.virtual_memory()
    disk_info = psutil.disk_usage('/')

    stats_message = "🖥️ **إحصائيات الخادم:**\n\n"
    stats_message += f"📊 **استخدام المعالج (CPU)**: `{cpu_percent}%`\n"
    stats_message += f"🧠 **استخدام الذاكرة (RAM)**:\n"
    stats_message += f"   - الإجمالي: `{ram_info.total / (1024**3):.2f} GB`\n"
    stats_message += f"   - المستخدم: `{ram_info.used / (1024**3):.2f} GB` (`{ram_info.percent}%`)\n"
    stats_message += f"   - المتاح: `{ram_info.available / (1024**3):.2f} GB`\n"
    stats_message += f"💽 **استخدام القرص (Disk)**:\n"
    stats_message += f"   - الإجمالي: `{disk_info.total / (1024**3):.2f} GB`\n"
    stats_message += f"   - المستخدم: `{disk_info.used / (1024**3):.2f} GB` (`{disk_info.percent}%`)\n"
    stats_message += f"   - المتاح: `{disk_info.free / (1024**3):.2f} GB`\n"

    # معلومات عن البوتات قيد التشغيل (من منظور الخادم)
    num_running_bots = len(bot_processes)
    stats_message += f"\n🤖 **عدد البوتات قيد التشغيل**: `{num_running_bots}`\n"

    bot.send_message(chat_id, stats_message, parse_mode='Markdown')
    logger.info(f"تم إرسال إحصائيات الخادم إلى المطور {chat_id}.")

def show_dev_tools_menu(chat_id, edit_message=False, message_id=None):
    """يعرض قائمة أدوات المطور."""
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('⚠️ عرض جميع التحذيرات', callback_data='view_all_warnings'))
    markup.add(types.InlineKeyboardButton('🗑️ مسح جميع التحذيرات', callback_data='clear_all_warnings'))
    markup.add(types.InlineKeyboardButton('📈 فحص استخدام RAM', callback_data='check_ram'))
    markup.add(types.InlineKeyboardButton('📉 فحص استخدام القرص', callback_data='check_disk'))
    markup.add(types.InlineKeyboardButton('📊 فحص استخدام CPU', callback_data='check_cpu'))
    markup.add(types.InlineKeyboardButton('🔄 إعادة تشغيل الخادم', callback_data='reboot_server'))
    markup.add(types.InlineKeyboardButton('🔙 العودة للقائمة الرئيسية', callback_data='back_to_main'))

    text = "🛠️ **أدوات المطور:**\n\n" \
           "هنا يمكنك الوصول إلى أدوات الصيانة والتشخيص المتقدمة."

    if edit_message:
        bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=markup, parse_mode='Markdown')
    else:
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')

def view_all_security_warnings(chat_id):
    """يعرض جميع التحذيرات الأمنية المسجلة للمطور."""
    all_warnings = []
    for user_id, warnings in user_warnings.items():
        for warning in warnings:
            all_warnings.append((user_id, warning))

    if not all_warnings:
        bot.send_message(chat_id, "✅ **لا توجد أي تحذيرات أمان مسجلة.**")
        show_dev_tools_menu(chat_id)
        return

    # Sort by timestamp, newest first
    all_warnings.sort(key=lambda x: datetime.fromisoformat(x[1]['timestamp']), reverse=True)

    message_parts = []
    current_message_part = "⚠️ **جميع التحذيرات الأمنية المسجلة:**\n\n"

    for i, (user_id, warning) in enumerate(all_warnings):
        entry_text = f"--- تحذير #{i+1} ---\n"
        entry_text += f"👤 **المستخدم**: `{user_id}`\n"
        entry_text += f"🧪 **السبب**: {warning['reason']}\n"
        entry_text += f"📄 **الملف**: `{warning['file_name'] if warning['file_name'] else 'غير محدد'}`\n"
        entry_text += f"⏰ **الوقت**: {datetime.fromisoformat(warning['timestamp']).strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        if len(current_message_part) + len(entry_text) > 4000: # Telegram limit
            message_parts.append(current_message_part)
            current_message_part = entry_text
        else:
            current_message_part += entry_text

    if current_message_part:
        message_parts.append(current_message_part)

    for part in message_parts:
        bot.send_message(chat_id, part, parse_mode='Markdown')

    bot.send_message(chat_id, "✅ **تم عرض جميع التحذيرات.**")
    show_dev_tools_menu(chat_id)

def clear_all_security_warnings(chat_id):
    """يمسح جميع التحذيرات الأمنية المسجلة من الذاكرة وقاعدة البيانات."""
    global user_warnings
    user_warnings = {} # Clear from memory

    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute('DELETE FROM user_warnings') # Clear from DB
    conn.commit()
    conn.close()

    bot.send_message(chat_id, "🗑️ **تم مسح جميع التحذيرات الأمنية بنجاح!**")
    security_logger.info(f"المطور {chat_id} مسح جميع التحذيرات الأمنية.")
    show_dev_tools_menu(chat_id)

def check_ram_usage(chat_id):
    """يرسل معلومات استخدام الذاكرة (RAM)."""
    ram_info = psutil.virtual_memory()
    message = "🧠 **استخدام الذاكرة (RAM):**\n"
    message += f"   - الإجمالي: `{ram_info.total / (1024**3):.2f} GB`\n"
    message += f"   - المستخدم: `{ram_info.used / (1024**3):.2f} GB` (`{ram_info.percent}%`)\n"
    message += f"   - المتاح: `{ram_info.available / (1024**3):.2f} GB`"
    bot.send_message(chat_id, message, parse_mode='Markdown')
    show_dev_tools_menu(chat_id)

def check_disk_usage(chat_id):
    """يرسل معلومات استخدام القرص."""
    disk_info = psutil.disk_usage('/')
    message = "💽 **استخدام القرص (Disk):**\n"
    message += f"   - الإجمالي: `{disk_info.total / (1024**3):.2f} GB`\n"
    message += f"   - المستخدم: `{disk_info.used / (1024**3):.2f} GB` (`{disk_info.percent}%`)\n"
    message += f"   - المتاح: `{disk_info.free / (1024**3):.2f} GB`"
    bot.send_message(chat_id, message, parse_mode='Markdown')
    show_dev_tools_menu(chat_id)

def check_cpu_usage(chat_id):
    """يرسل معلومات استخدام المعالج (CPU)."""
    cpu_percent = psutil.cpu_percent(interval=2) # Get CPU usage over 2 seconds
    message = f"📊 **استخدام المعالج (CPU)**: `{cpu_percent}%`"
    bot.send_message(chat_id, message, parse_mode='Markdown')
    show_dev_tools_menu(chat_id)

def confirm_reboot(chat_id):
    """يطلب تأكيد إعادة تشغيل الخادم."""
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('✅ تأكيد إعادة التشغيل', callback_data='confirm_reboot'))
    markup.add(types.InlineKeyboardButton('❌ إلغاء', callback_data='cancel_reboot'))
    bot.send_message(chat_id, "⚠️ **تحذير: أنت على وشك إعادة تشغيل الخادم.**\n"
                              "هذا سيؤدي إلى إيقاف جميع البوتات الجارية مؤقتاً.\n"
                              "**هل أنت متأكد أنك تريد المتابعة؟**", reply_markup=markup, parse_mode='Markdown')

def perform_reboot(chat_id):
    """يقوم بإعادة تشغيل الخادم."""
    bot.send_message(chat_id, "🔄 **جاري إعادة تشغيل الخادم...**\n"
                              "قد يستغرق هذا بضع لحظات. سأكون غير متاح حتى تتم إعادة التشغيل بنجاح.")
    logger.critical(f"المطور {chat_id} بدأ عملية إعادة تشغيل الخادم.")

    # Stop all running bots gracefully before rebooting
    for process_key in list(bot_processes.keys()): # Iterate over a copy
        try:
            process_info = bot_processes[process_key]
            process = process_info['process']
            if process.poll() is None:
                if platform.system() == "Windows":
                    process.terminate()
                else:
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                process.wait(timeout=5)
                if process.poll() is None:
                    if platform.system() == "Windows":
                        process.kill()
                    else:
                        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    process.wait()
            del bot_processes[process_key]
            remove_bot_process_state(process_key)
            logger.info(f"تم إيقاف البوت {process_key} قبل إعادة التشغيل.")
        except Exception as e:
            logger.error(f"فشل إيقاف البوت {process_key} قبل إعادة التشغيل: {e}")

    try:
        if platform.system() == "Windows":
            subprocess.run(["shutdown", "/r", "/t", "0"]) # Windows reboot
        else:
            subprocess.run(["sudo", "reboot"]) # Linux reboot (requires sudo NOPASSWD for this command)
    except Exception as e:
        logger.error(f"فشل في تنفيذ أمر إعادة تشغيل الخادم: {e}")
        bot.send_message(chat_id, f"❌ **فشل في إعادة تشغيل الخادم.** الرجاء التحقق من الصلاحيات أو محاولة يدوية.")
        bot.send_message(chat_id, "🚀 **لوحة التحكم الرئيسية:**", reply_markup=create_main_menu(ADMIN_ID), parse_mode='Markdown')


# Start Keep Alive for web server (if running on platforms like Replit)
keep_alive()

# Run bot polling in a separate thread to ensure keep_alive doesn't block it
def start_bot_polling():
    # Attempt to recover bots that were running before shutdown
    recover_running_bots()
    logger.info("بدء تشغيل البوت...")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)

# Start bot polling in a separate thread
polling_thread = threading.Thread(target=start_bot_polling)
polling_thread.daemon = True # Allow main program to exit if this thread is still running
polling_thread.start()

