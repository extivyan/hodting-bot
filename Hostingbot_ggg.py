import asyncio
import time as _time_module
import os
import re
import sqlite3
import logging
import secrets
import aiofiles
import subprocess
import shutil

import json
import uuid
import html as html_module
import hashlib
from asyncio.subprocess import Process
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputFile, LabeledPrice
from aiogram.utils.exceptions import (
    TelegramAPIError,
    MessageNotModified,
    MessageToDeleteNotFound,
    MessageCantBeDeleted,
    BadRequest,
    RetryAfter,
    NetworkError,
)

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
# ضع توكن البوت هنا مباشرة (من BotFather):
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

if not BOT_TOKEN:
    raise RuntimeError(
        "لم تضع توكن البوت. افتح هذا الملف وضع توكنك الحقيقي بدل النص 'ضع_التوكن_هنا' بسطر BOT_TOKEN."
    )
OWNER_ID = int(os.environ.get("OWNER_ID", "8564534699"))
ADMIN_IDS = []
DEVELOPER_USERNAME = "E_ryx1"
DEVELOPER_CHANNEL = "Eyrx_c"
POINTS_PER_BOT = 0
POINTS_PER_SITE = 0
POINTS_PER_REFERRAL = 1
VIP_REQUIRED_REFERRALS = 6

# ─────────────────────────────────────────────
# أسعار شحن الرصيد عبر نجوم تيليغرام
# ─────────────────────────────────────────────
STARS_PACKAGES = {
    15: 6,
    25: 12,
    50: 21,
    100: 50,
}
UPLOADS_DIR = Path("uploads")
BOTS_DIR = UPLOADS_DIR / "bots"
SITES_DIR = UPLOADS_DIR / "sites"

# ─────────────────────────────────────────────
# استضافة المواقع (سيرفر ملفات ستاتيك حقيقي)
# ─────────────────────────────────────────────
# بدل الرابط الوهمي القديم، نقدّم ملفات SITES_DIR فعلياً عبر aiohttp.web على
# نفس السيرفر تبع البوت. رابط الاستضافة الفعلي (IP/دومين) يُضبط الآن عبر دالة
# get_site_host_url() أدناه: الأولوية لمتغيّر البيئة SITE_HOST_PUBLIC_URL إن
# وُجد، وإلا يُقرأ من قاعدة البيانات (زر 'ربط IP/دومين المواقع' بلوحة الأدمن).
# SITE_SERVER_PORT هو البورت المحلي الذي يستمع عليه سيرفر الملفات (لازم يكون
# مفتوحاً بالجدار الناري لو استُخدم IP مباشر بدون تونيل).
SITE_SERVER_PORT = int(os.environ.get("SITE_SERVER_PORT", "8082"))

# ─────────────────────────────────────────────
# الاشتراك الإجباري + انستغرام
# ─────────────────────────────────────────────
# القناة التي يجب على كل مستخدم الاشتراك فيها قبل استخدام البوت.
# افتراضياً نفس قناة المطور؛ يمكن تغييرها هنا فقط دون المساس بأي منطق آخر.
FORCE_SUB_CHANNEL_USERNAME = "Eyrx_c"
FORCE_SUB_CHANNEL_ID = f"@{FORCE_SUB_CHANNEL_USERNAME}"

# حساب انستغرام يظهر كخطوة إضافية ضمن شاشة الاشتراك الإجباري نفسها (رابط
# فقط يفتحه المستخدم، بدون أي إدخال أو تصريح من طرفه). الأدمن هو من يحدد
# هذا اليوزر هون فقط، تماماً متل قناة تليغرام؛ لا يوجد تحقق آلي من
# المتابعة لأنه غير متاح عبر أي API مجاني، فهو يُعرض فقط كخطوة مطلوبة
# بجانب الاشتراك بالقناة.
INSTAGRAM_ACCOUNT_USERNAME = "ward_host"  # عدّلها لليوزر الفعلي لحسابكم
INSTAGRAM_ACCOUNT_URL = f"https://instagram.com/{INSTAGRAM_ACCOUNT_USERNAME}"

RUNNING_BOT_PROCESSES: Dict[int, Process] = {}
BOT_PROCESS_START_TIME = _time_module.time()


@asynccontextmanager
async def animated_loading_indicator(chat_id: int, label: str = " جاري التحميل"):
    """مؤشر تحميل متحرك عام يظهر بالمحادثة قبل عرض أي نتيجة (سرعة، وقت تشغيل،
    إلخ)، ويُحذف تلقائياً فور انتهاء العملية داخل الـ with block."""
    msg = await bot.send_message(chat_id, f"{label} ")

    async def _animate():
        frames = [
            f"{label}\n▰▱▱▱▱▱▱▱",
            f"{label}\n▰▰▰▱▱▱▱▱",
            f"{label}\n▰▰▰▰▰▱▱▱",
            f"{label}\n▰▰▰▰▰▰▰▱",
            f"{label}\n▰▰▰▰▰▰▰▰",
        ]
        i = 0
        try:
            while True:
                await asyncio.sleep(0.6)
                i = (i + 1) % len(frames)
                try:
                    await bot.edit_message_text(frames[i], chat_id, msg.message_id)
                except Exception:
                    pass
        except asyncio.CancelledError:
            pass

    task = asyncio.create_task(_animate())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except Exception:
            pass
        try:
            await msg.delete()
        except Exception:
            pass


def format_uptime_duration(seconds: float) -> str:
    """يحوّل عدد الثواني لصيغة نصية مقروءة: أيام/ساعات/دقائق/ثواني."""
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days} يوم")
    if hours:
        parts.append(f"{hours} ساعة")
    if minutes:
        parts.append(f"{minutes} دقيقة")
    if secs or not parts:
        parts.append(f"{secs} ثانية")
    return " و ".join(parts)

for d in [UPLOADS_DIR, BOTS_DIR, SITES_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────
DB_PATH = "host_aras.db"


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@asynccontextmanager
async def db_cursor():
    conn = get_db()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


async def init_db():
    async with db_cursor() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                points INTEGER DEFAULT 0,
                referral_code TEXT UNIQUE,
                referred_by INTEGER,
                referrals_count INTEGER DEFAULT 0,
                is_banned INTEGER DEFAULT 0,
                is_admin INTEGER DEFAULT 0,
                is_owner INTEGER DEFAULT 0,
                is_vip INTEGER DEFAULT 0,
                notified_admin INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                last_active TEXT DEFAULT (datetime('now')),
                welcome_sent INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                file_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_type TEXT DEFAULT 'python',
                status TEXT DEFAULT 'pending',
                admin_note TEXT,
                bot_token TEXT,
                run_file TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                approved_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                file_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                site_url TEXT,
                status TEXT DEFAULT 'pending',
                admin_note TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                approved_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER NOT NULL,
                referred_id INTEGER NOT NULL UNIQUE,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (referrer_id) REFERENCES users(user_id),
                FOREIGN KEY (referred_id) REFERENCES users(user_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS coupons (
                code TEXT PRIMARY KEY,
                points INTEGER NOT NULL,
                max_uses INTEGER DEFAULT 1,
                used_count INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_by INTEGER,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS coupon_uses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                coupon_code TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                used_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (coupon_code) REFERENCES coupons(code),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS file_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                file_name TEXT,
                action TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS media_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                media_type TEXT,
                file_id TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS charge_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT (datetime('now')),
                admin_message_id INTEGER,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        # ─────────────────────────────────────────────
        # ترحيل تلقائي للأعمدة الناقصة (auto-migration)
        # ─────────────────────────────────────────────
        expected_columns = {
            "users": {
                "points": "INTEGER DEFAULT 0",
                "referral_code": "TEXT",
                "referred_by": "INTEGER",
                "referrals_count": "INTEGER DEFAULT 0",
                "is_banned": "INTEGER DEFAULT 0",
                "is_admin": "INTEGER DEFAULT 0",
                "is_owner": "INTEGER DEFAULT 0",
                "is_vip": "INTEGER DEFAULT 0",
                "notified_admin": "INTEGER DEFAULT 0",
                "created_at": "TEXT DEFAULT (datetime('now'))",
                "last_active": "TEXT DEFAULT (datetime('now'))",
                "max_files": "INTEGER DEFAULT 10",
                "max_concurrent_bots": "INTEGER DEFAULT 1",
                "upgrade_tier": "TEXT DEFAULT 'none'",
                "language": "TEXT DEFAULT NULL",
                "welcome_sent": "INTEGER DEFAULT 0",
                "gift_claimed": "INTEGER DEFAULT 0",
            },
            "bots": {
                "file_type": "TEXT DEFAULT 'python'",
                "status": "TEXT DEFAULT 'pending'",
                "admin_note": "TEXT",
                "bot_token": "TEXT",
                "run_file": "TEXT",
                "created_at": "TEXT DEFAULT (datetime('now'))",
                "approved_at": "TEXT",
            },
            "sites": {
                "site_url": "TEXT",
                "status": "TEXT DEFAULT 'pending'",
                "admin_note": "TEXT",
                "created_at": "TEXT DEFAULT (datetime('now'))",
                "approved_at": "TEXT",
            },
            "coupons": {
                "points": "INTEGER NOT NULL DEFAULT 0",
                "max_uses": "INTEGER DEFAULT 1",
                "used_count": "INTEGER DEFAULT 0",
                "is_active": "INTEGER DEFAULT 1",
                "created_by": "INTEGER",
                "created_at": "TEXT DEFAULT (datetime('now'))",
            },
            "section_media": {
                "mode": "TEXT DEFAULT 'static'",
            },
        }

        for table_name, columns in expected_columns.items():
            try:
                existing_cols = [row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()]
            except Exception as e:
                logger.warning(f"Could not read schema for table {table_name}: {e}")
                continue
            if not existing_cols:
                continue
            for col_name, col_def in columns.items():
                if col_name not in existing_cols:
                    try:
                        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_def}")
                        logger.info(f"Auto-migrated: added column '{col_name}' to table '{table_name}'")
                    except Exception as e:
                        logger.error(f"Failed to add column '{col_name}' to '{table_name}': {e}")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_config (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS section_media (
                section TEXT PRIMARY KEY,
                media_type TEXT,
                file_id TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS section_media_pool (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                section TEXT NOT NULL,
                media_type TEXT,
                file_id TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS folder_permissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                folder_path TEXT NOT NULL,
                granted_by INTEGER,
                created_at TEXT DEFAULT (datetime('now')),
                UNIQUE(user_id, folder_path),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS force_sub_targets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_type TEXT NOT NULL,
                display_name TEXT NOT NULL,
                identifier TEXT NOT NULL,
                url TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ai_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ai_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                bot_id INTEGER NOT NULL,
                questions_used INTEGER DEFAULT 0,
                window_started_at TEXT,
                UNIQUE(user_id, bot_id)
            )
        """)
        # ─────────────────────────────────────────
        # رصيد قسائم الذكاء الاصطناعي (منفصل تماماً عن نقاط الاستضافة العادية)
        # ─────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ai_wallet (
                user_id INTEGER PRIMARY KEY,
                ai_questions_balance INTEGER DEFAULT 0,
                can_read_files INTEGER DEFAULT 0,
                can_read_logs INTEGER DEFAULT 0,
                can_edit_files INTEGER DEFAULT 0,
                can_send_files INTEGER DEFAULT 0,
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ai_wallet_purchases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                package_key TEXT NOT NULL,
                stars INTEGER NOT NULL,
                questions_added INTEGER NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        # ─────────────────────────────────────────
        # إحصاءات استخدام كل نموذج AI لكل ملف/بوت (لإشعار الأدمن بالتفصيل عند كل تعديل)
        # ─────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ai_model_usage_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model_key TEXT NOT NULL,
                bot_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                usage_count INTEGER DEFAULT 0,
                edits_applied_count INTEGER DEFAULT 0,
                last_used_at TEXT DEFAULT (datetime('now')),
                UNIQUE(model_key, bot_id)
            )
        """)

        # أي بوت كانت حالته 'running' من تشغيلة سابقة مؤكد متوقف فعلياً
        # بعد إعادة التشغيل لأن RUNNING_BOT_PROCESSES قاموس بالذاكرة يبدأ فاضي.
        conn.execute("UPDATE bots SET status = 'stopped' WHERE status = 'running'")

        logger.info("Database initialized successfully")


async def get_or_create_user(user_id: int, username: str = None, first_name: str = None,
                               referral_code: str = None) -> sqlite3.Row:
    async with db_cursor() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        if not row:
            ref_code = referral_code or secrets.token_hex(4)
            is_owner_flag = 1 if user_id == OWNER_ID else 0
            conn.execute(
                """INSERT INTO users (user_id, username, first_name, referral_code, is_owner)
                   VALUES (?, ?, ?, ?, ?)""",
                (user_id, username, first_name, ref_code, is_owner_flag),
            )
            row = conn.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
        else:
            is_owner_flag = 1 if user_id == OWNER_ID else row["is_owner"]
            conn.execute(
                """UPDATE users SET username=?, first_name=?, last_active=datetime('now'), is_owner=?
                   WHERE user_id=?""",
                (username, first_name, is_owner_flag, user_id),
            )
        return row


async def get_user(user_id: int) -> Optional[sqlite3.Row]:
    async with db_cursor() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()


async def get_user_by_referral_code(referral_code: str) -> Optional[sqlite3.Row]:
    async with db_cursor() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE referral_code = ?", (referral_code,)
        ).fetchone()


async def mark_admin_notified(user_id: int):
    async with db_cursor() as conn:
        conn.execute("UPDATE users SET notified_admin = 1 WHERE user_id = ?", (user_id,))


async def send_welcome_once(chat_id: int, user_id: int, lang: str):
    """أرسل رسالة ترحيب مرتبة وكبيرة لمستخدم جديد — مرة واحدة فقط."""
    try:
        user = await get_user(user_id)
        if not user:
            return
        try:
            already_sent = user["welcome_sent"]
        except (KeyError, IndexError):
            already_sent = 0
        if already_sent:
            return

        welcome_text = t("welcome_title", lang) + t("welcome_body", lang)
        await bot.send_message(chat_id, welcome_text)

        async with db_cursor() as conn:
            conn.execute("UPDATE users SET welcome_sent = 1 WHERE user_id = ?", (user_id,))
    except Exception as e:
        logger.error(f"send_welcome_once failed for {user_id}: {e}", exc_info=True)


async def update_user_points(user_id: int, delta: int):
    async with db_cursor() as conn:
        conn.execute(
            "UPDATE users SET points = points + ? WHERE user_id = ?",
            (delta, user_id),
        )


async def is_user_already_referred(user_id: int) -> bool:
    """مصدر الحقيقة الوحيد لسؤال 'هل هذا المستخدم أُحيل من قبل؟'.
    يعتمد فقط على جدول referrals (عمود referred_id، محمي بقيد UNIQUE)،
    وليس على وجود صف بجدول users، لتجنب استغلال الإحالة ولتجنب خسارة
    إحالات شرعية لمستخدمين قدامى لم يُحالوا من قبل."""
    async with db_cursor() as conn:
        row = conn.execute(
            "SELECT id FROM referrals WHERE referred_id = ?", (user_id,)
        ).fetchone()
        return row is not None


async def add_referral(referrer_id: int, referred_id: int) -> bool:
    """يسجل إحالة جديدة بشكل آمن تماماً من التزامن (race-condition safe):
    الحماية الأساسية هي قيد UNIQUE على referred_id بمستوى قاعدة البيانات نفسها
    (referrals.referred_id UNIQUE)، فحتى لو صارت محاولتان متزامنتان فعلياً،
    قاعدة البيانات نفسها ترفض ثانيهما بشكل ذري. الفحص البرمجي هنا (SELECT) هو
    فقط لتوفير مسار سريع وتفادي استثناء غير ضروري، وIntegrityError محاط بمعالجة
    صريحة كخط دفاع أخير."""
    async with db_cursor() as conn:
        existing = conn.execute(
            "SELECT id FROM referrals WHERE referred_id = ?", (referred_id,)
        ).fetchone()
        if existing:
            return False

        try:
            conn.execute(
                "INSERT INTO referrals (referrer_id, referred_id) VALUES (?, ?)",
                (referrer_id, referred_id),
            )
        except sqlite3.IntegrityError:
            # صار تزامن فعلي وسجّلها استدعاء آخر أسرع بجزء من الثانية؛ قاعدة البيانات
            # منعت التكرار بنجاح، فنعتبر هذه المحاولة فاشلة بأمان بدون منح نقاط مضاعفة.
            logger.warning(f"add_referral: race condition detected for referred_id={referred_id}, rejected by UNIQUE constraint.")
            return False

        conn.execute(
            "UPDATE users SET referrals_count = referrals_count + 1 WHERE user_id = ?",
            (referrer_id,),
        )
        # ملاحظة حرجة: لا نستدعي update_user_points() هنا، لأنها تفتح اتصال قاعدة بيانات
        # مستقل خاص بها (db_cursor جديد) بينما هذا الاتصال (conn) لا يزال مفتوحاً ولم
        # ينفذ commit بعد. استدعاء دالة تفتح اتصالاً متداخلاً من داخل معاملة مفتوحة
        # كان يسبب تعارض قفل بقاعدة SQLite ويمنع إضافة النقطة فعلياً بشكل صامت (كانت
        # الأخطاء تُبتلع بصمت بمكان الاستدعاء الأعلى). الحل: تنفيذ نفس عملية التحديث
        # مباشرة بهذا الاتصال المفتوح أصلاً.
        conn.execute(
            "UPDATE users SET points = points + ? WHERE user_id = ?",
            (POINTS_PER_REFERRAL, referrer_id),
        )
        # Auto-grant VIP at 6 referrals
        row = conn.execute("SELECT referrals_count, is_vip FROM users WHERE user_id = ?", (referrer_id,)).fetchone()
        if row and row["referrals_count"] >= VIP_REQUIRED_REFERRALS and not row["is_vip"]:
            conn.execute("UPDATE users SET is_vip = 1 WHERE user_id = ?", (referrer_id,))
            try:
                await bot.send_message(
                    referrer_id,
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    "◆ تهنئة! ◆\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f" حصلت على عضوية VIP بعد دعوة {VIP_REQUIRED_REFERRALS} أشخاص!\n"
                    "استمتع بجميع المميزات الحصرية الآن ",
                    parse_mode=types.ParseMode.HTML,
                )
            except Exception:
                pass
        return True


async def add_bot(user_id: int, file_name: str, file_path: str, file_type: str = "python", bot_token: str = None) -> int:
    async with db_cursor() as conn:
        cursor = conn.execute(
            """INSERT INTO bots (user_id, file_name, file_path, file_type, status, bot_token)
               VALUES (?, ?, ?, ?, 'pending', ?)""",
            (user_id, file_name, file_path, file_type, bot_token),
        )
        return cursor.lastrowid


async def add_site(user_id: int, file_name: str, file_path: str, site_url: str = None) -> int:
    async with db_cursor() as conn:
        cursor = conn.execute(
            """INSERT INTO sites (user_id, file_name, file_path, site_url, status)
               VALUES (?, ?, ?, ?, 'pending')""",
            (user_id, file_name, file_path, site_url),
        )
        return cursor.lastrowid


async def get_site_host_url() -> str:
    """يرجع رابط استضافة المواقع الفعلي الحالي: الأولوية لمتغيّر البيئة
    SITE_HOST_PUBLIC_URL إن كان مضبوطاً (للتوافق مع الطريقة القديمة)، وإلا
    يُقرأ من قاعدة البيانات (اللي يضبطها الأدمن بزر 'ربط IP/دومين المواقع'
    من داخل تيليجرام مباشرة)، وإلا localhost كقيمة افتراضية غير صالحة للنشر."""
    env_value = os.environ.get("SITE_HOST_PUBLIC_URL")
    if env_value:
        return env_value
    db_value = await get_config_value("site_host_public_url")
    if db_value:
        return db_value
    return f"http://localhost:{SITE_SERVER_PORT}"


async def build_site_url(dest_path: Path) -> str:
    """يبني رابط الموقع الحقيقي اعتماداً على مسار الملف الفعلي داخل SITES_DIR،
    بحيث يُقدَّم فعلياً عبر سيرفر الملفات الستاتيك (aiohttp) وليس رابطاً وهمياً."""
    host_url = await get_site_host_url()
    try:
        relative = dest_path.resolve().relative_to(SITES_DIR.resolve())
    except ValueError:
        relative = Path(dest_path.name)
    return f"{host_url.rstrip('/')}/{relative.as_posix()}"


async def update_all_site_urls_to_real_hosting() -> int:
    """يحدّث روابط كل المواقع الموجودة مسبقاً بقاعدة البيانات (approved أو pending)
    لتستخدم رابط الاستضافة الحقيقي الجديد بدل الرابط الوهمي القديم."""
    updated = 0
    async with db_cursor() as conn:
        rows = conn.execute("SELECT id, file_path FROM sites").fetchall()
        for row in rows:
            file_path = Path(row["file_path"])
            new_url = await build_site_url(file_path)
            conn.execute("UPDATE sites SET site_url = ? WHERE id = ?", (new_url, row["id"]))
            updated += 1
    return updated


async def get_user_bots(user_id: int) -> List[sqlite3.Row]:
    async with db_cursor() as conn:
        return conn.execute(
            "SELECT * FROM bots WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()


async def get_user_sites(user_id: int) -> List[sqlite3.Row]:
    async with db_cursor() as conn:
        return conn.execute(
            "SELECT * FROM sites WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()


async def get_pending_bots() -> List[sqlite3.Row]:
    async with db_cursor() as conn:
        return conn.execute(
            "SELECT * FROM bots WHERE status = 'pending' ORDER BY created_at ASC"
        ).fetchall()


async def get_pending_sites() -> List[sqlite3.Row]:
    async with db_cursor() as conn:
        return conn.execute(
            "SELECT * FROM sites WHERE status = 'pending' ORDER BY created_at ASC"
        ).fetchall()


async def get_all_bots() -> List[sqlite3.Row]:
    async with db_cursor() as conn:
        return conn.execute("SELECT * FROM bots ORDER BY created_at DESC").fetchall()


async def get_bot_by_id(bot_id: int) -> Optional[sqlite3.Row]:
    async with db_cursor() as conn:
        return conn.execute("SELECT * FROM bots WHERE id = ?", (bot_id,)).fetchone()


async def get_site_by_id(site_id: int) -> Optional[sqlite3.Row]:
    async with db_cursor() as conn:
        return conn.execute("SELECT * FROM sites WHERE id = ?", (site_id,)).fetchone()


async def grant_folder_permission(user_id: int, folder_path: str, granted_by: int) -> bool:
    try:
        async with db_cursor() as conn:
            conn.execute(
                """INSERT INTO folder_permissions (user_id, folder_path, granted_by)
                   VALUES (?, ?, ?)
                   ON CONFLICT(user_id, folder_path) DO UPDATE SET granted_by=excluded.granted_by, created_at=datetime('now')""",
                (user_id, folder_path, granted_by),
            )
        return True
    except Exception as e:
        logger.error(f"grant_folder_permission failed: {e}", exc_info=True)
        return False


async def revoke_folder_permission(user_id: int, folder_path: str) -> bool:
    async with db_cursor() as conn:
        conn.execute(
            "DELETE FROM folder_permissions WHERE user_id = ? AND folder_path = ?",
            (user_id, folder_path),
        )
    return True


async def user_has_folder_permission(user_id: int, folder_path: str) -> bool:
    async with db_cursor() as conn:
        row = conn.execute(
            "SELECT 1 FROM folder_permissions WHERE user_id = ? AND folder_path = ?",
            (user_id, folder_path),
        ).fetchone()
        return row is not None


async def get_user_folder_permissions(user_id: int) -> List[sqlite3.Row]:
    async with db_cursor() as conn:
        return conn.execute(
            "SELECT * FROM folder_permissions WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()


# ─────────────────────────────────────────────
# نظام الاشتراك الإجباري متعدد القنوات
# ─────────────────────────────────────────────
FORCE_SUB_TYPE_CHANNEL = "channel"
FORCE_SUB_TYPE_TG_BOT = "tg_bot"
FORCE_SUB_TYPE_INSTAGRAM = "instagram"

FORCE_SUB_TYPE_LABELS = {
    FORCE_SUB_TYPE_CHANNEL: " قناة تيليجرام",
    FORCE_SUB_TYPE_TG_BOT: " بوت تيليجرام",
    FORCE_SUB_TYPE_INSTAGRAM: " حساب انستغرام",
}


async def get_all_force_sub_targets(active_only: bool = False) -> List[sqlite3.Row]:
    async with db_cursor() as conn:
        if active_only:
            return conn.execute(
                "SELECT * FROM force_sub_targets WHERE is_active = 1 ORDER BY id ASC"
            ).fetchall()
        return conn.execute("SELECT * FROM force_sub_targets ORDER BY id ASC").fetchall()


async def get_force_sub_target_by_id(target_id: int) -> Optional[sqlite3.Row]:
    async with db_cursor() as conn:
        return conn.execute(
            "SELECT * FROM force_sub_targets WHERE id = ?", (target_id,)
        ).fetchone()


async def add_force_sub_target(target_type: str, display_name: str, identifier: str, url: str) -> int:
    async with db_cursor() as conn:
        cursor = conn.execute(
            """INSERT INTO force_sub_targets (target_type, display_name, identifier, url)
               VALUES (?, ?, ?, ?)""",
            (target_type, display_name, identifier, url),
        )
        return cursor.lastrowid


async def delete_force_sub_target(target_id: int):
    async with db_cursor() as conn:
        conn.execute("DELETE FROM force_sub_targets WHERE id = ?", (target_id,))


async def toggle_force_sub_target(target_id: int):
    async with db_cursor() as conn:
        conn.execute(
            "UPDATE force_sub_targets SET is_active = 1 - is_active WHERE id = ?",
            (target_id,),
        )


async def is_user_subscribed_to_all_targets(bot_instance: Bot, user_id: int, force_fresh: bool = False) -> tuple:
    """يفحص اشتراك المستخدم بكل قنوات تيليجرام النشطة (target_type='channel') فقط،
    لأنها الوحيدة القابلة للتحقق الآلي عبر Telegram API (get_chat_member، ويتطلب أن
    يكون البوت أدمن بالقناة). بوتات تيليجرام وحسابات انستغرام لا يوجد API رسمي
    للتحقق من متابعتها، فتُعرض كروابط تشجيعية فقط بدون حظر فعلي.

    فحص حقيقي مباشر عند تيليجرام (get_chat_member) في كل مرة تُستدعى فيها هذه
    الدالة — بدون أي تخزين مؤقت (cache). هذا مقصود: أي كاش زمني (حتى لو دقائق
    قليلة) يعني وجود نافذة زمنية يقدر فيها مستخدم خرج من القناة أن يستمر
    باستخدام البوت وكأنه لسا مشترك، وهذا الاستخدام يتطلب دقة فورية عند كل تفاعل
    (رسالة أو ضغطة زر) بدل الاعتماد على نتيجة قديمة. البارامتر force_fresh باقٍ
    فقط لتوافقية الاستدعاءات الحالية ولا أثر عملياً لعدم وجود كاش أصلاً.

    يرجع (كل_القنوات_محقّقة: bool, أول_قناة_غير_محقّقة_أو_None)."""
    channels = [t for t in await get_all_force_sub_targets(active_only=True) if t["target_type"] == FORCE_SUB_TYPE_CHANNEL]
    result, missing_channel = True, None
    for channel in channels:
        try:
            member = await bot_instance.get_chat_member(channel["identifier"], user_id)
            if member.status in ("left", "kicked"):
                result, missing_channel = False, channel
                break
        except Exception as e:
            logger.warning(f"is_user_subscribed_to_all_targets: check failed for channel {channel['identifier']}: {e}")
            # تعذّر الفحص (مثلاً البوت مش أدمن بهذي القناة) — لا نمنع المستخدم بسبب
            # إعداد ناقص من طرف الأدمن، حتى لا يتعطل البوت بالكامل.
            continue

    return result, missing_channel


def invalidate_force_sub_cache(user_id: int):
    """توافقية للخلف فقط: لا يوجد كاش حالياً (كل فحص اشتراك مباشر وفوري)، فهذه
    الدالة أصبحت بلا تأثير فعلي. أُبقيت لتفادي كسر أي استدعاء قديم لها."""
    return


# ─────────────────────────────────────────────
# نظام مساعد AI لتشخيص أخطاء البوتات
# ─────────────────────────────────────────────
AI_QUESTIONS_LIMIT = 2
AI_COOLDOWN_HOURS = 3

# ─────────────────────────────────────────────
# النماذج الرسمية المتاحة لمساعد AI (مفاتيح/روابط API رسمية يضبطها الأدمن بنفسه
# من لوحة التحكم — كل نموذج يقبل حتى 5 مفاتيح/روابط مخزَّنة كـ JSON array تحت
# مفتاح ai_official_key_<model_key> بجدول ai_settings. عند فشل مفتاح (خطأ HTTP
# أو استثناء اتصال) يُجرَّب تلقائياً المفتاح التالي بالترتيب دون أي تدخل يدوي،
# ويُرسَل إشعار فوري للأدمن (OWNER_ID) بأن ذلك المفتاح تحديداً تم تعطيله.
# ─────────────────────────────────────────────
AI_MAX_KEYS_PER_MODEL = 5

AI_MODELS_CATALOG = {
    "gemini": {
        "label": " Gemini",
        "provider": "google",
        "setting_key": "ai_official_key_gemini",
    },
    "chatgpt": {
        "label": " ChatGPT (OpenAI)",
        "provider": "openai",
        "setting_key": "ai_official_key_chatgpt",
    },
}
AI_MODEL_DEFAULT = "gemini"


async def get_ai_model_choice(user_id: int) -> str:
    """يرجع اختيار المستخدم/الأدمن الحالي لنموذج AI، أو الافتراضي لو لم يختر أحداً."""
    raw = await get_ai_setting(f"ai_model_choice_{user_id}")
    if raw and raw in AI_MODELS_CATALOG:
        return raw
    return AI_MODEL_DEFAULT


async def get_official_ai_credentials(model_key: str) -> List[str]:
    """يرجع قائمة كل المفاتيح/الروابط المضبوطة لهذا النموذج بترتيب الأولوية
    (المفتاح الأول يُجرَّب أولاً، ثم الثاني عند فشله... إلخ). قائمة فارغة إذا لم
    يُضبط أي مفتاح بعد. مخزّنة كـ JSON array بنفس setting_key القديم، فأي مفتاح
    قديم كان مخزّناً كنص خام (قبل دعم تعدد المفاتيح) يُقرأ تلقائياً كقائمة من عنصر واحد."""
    cfg = AI_MODELS_CATALOG.get(model_key)
    if not cfg:
        return []
    raw = await get_ai_setting(cfg["setting_key"])
    if not raw or not raw.strip():
        return []
    raw = raw.strip()
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(v).strip() for v in parsed if str(v).strip()]
    except json.JSONDecodeError:
        pass
    # قيمة قديمة مخزّنة كنص خام قبل دعم تعدد المفاتيح — نعاملها كمفتاح وحيد
    return [raw]


async def _save_ai_credentials_list(model_key: str, credentials: List[str]):
    cfg = AI_MODELS_CATALOG.get(model_key)
    if not cfg:
        return
    cleaned = [c.strip() for c in credentials if c and c.strip()][:AI_MAX_KEYS_PER_MODEL]
    await set_ai_setting(cfg["setting_key"], json.dumps(cleaned, ensure_ascii=False))


async def add_official_ai_credential(model_key: str, value: str) -> tuple:
    """يضيف مفتاحاً/رابطاً جديداً لآخر القائمة (يُجرَّب بعد كل المفاتيح الحالية).
    يرجع (نجاح: bool, رسالة). يرفض الإضافة إذا وصلت القائمة الحد الأقصى (5)."""
    cfg = AI_MODELS_CATALOG.get(model_key)
    if not cfg:
        return False, "نموذج غير معروف."
    value = value.strip()
    if not value:
        return False, "قيمة فارغة."
    current = await get_official_ai_credentials(model_key)
    if value in current:
        return False, "هذا المفتاح مضاف مسبقاً لنفس النموذج."
    if len(current) >= AI_MAX_KEYS_PER_MODEL:
        return False, f"وصلت الحد الأقصى ({AI_MAX_KEYS_PER_MODEL} مفاتيح) لهذا النموذج. احذف مفتاحاً أولاً."
    current.append(value)
    await _save_ai_credentials_list(model_key, current)
    return True, "تمت الإضافة."


async def remove_official_ai_credential_at(model_key: str, index: int) -> bool:
    """يحذف مفتاحاً واحداً بالترتيب (index يبدأ من 0) من قائمة هذا النموذج."""
    current = await get_official_ai_credentials(model_key)
    if index < 0 or index >= len(current):
        return False
    current.pop(index)
    await _save_ai_credentials_list(model_key, current)
    return True


async def remove_all_official_ai_credentials(model_key: str):
    await _save_ai_credentials_list(model_key, [])


async def get_configured_ai_models() -> list:
    """يرجع قائمة مفاتيح النماذج (من AI_MODELS_CATALOG) التي ضبط الأدمن مفتاحاً
    واحداً على الأقل لها فعلياً."""
    result = []
    for key in AI_MODELS_CATALOG:
        creds = await get_official_ai_credentials(key)
        if creds:
            result.append(key)
    return result


async def set_ai_model_choice(user_id: int, model_key: str):
    if model_key in AI_MODELS_CATALOG:
        await set_ai_setting(f"ai_model_choice_{user_id}", model_key)

# ─────────────────────────────────────────────
# قسائم شحن الذكاء الاصطناعي (Telegram Stars) — رصيد أسئلة منفصل عن نقاط الاستضافة
# ─────────────────────────────────────────────
AI_PACKAGES = {
    "ai_pkg_1": {
        "stars": 35,
        "questions": 20,
        "can_read_files": False,
        "can_read_logs": False,
        "can_edit_files": False,
        "can_send_files": False,
        "label": " 35 — 20 سؤال",
    },
    "ai_pkg_2": {
        "stars": 70,
        "questions": 50,
        "can_read_files": False,
        "can_read_logs": False,
        "can_edit_files": False,
        "can_send_files": False,
        "label": " 70 — 50 سؤال",
    },
    "ai_pkg_3": {
        "stars": 200,
        "questions": 120,
        "can_read_files": True,
        "can_read_logs": True,
        "can_edit_files": True,
        "can_send_files": True,
        "label": " 200 — 120 سؤال + قراءة/تعديل الملفات والسجل + إرسال ملفات",
    },
}


async def get_ai_setting(key: str) -> Optional[str]:
    async with db_cursor() as conn:
        row = conn.execute("SELECT value FROM ai_settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None


async def set_ai_setting(key: str, value: str):
    async with db_cursor() as conn:
        conn.execute(
            """INSERT INTO ai_settings (key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (key, value),
        )


async def get_ai_api_key() -> Optional[str]:
    """يقرأ مفتاح OpenRouter من متغير بيئة أولاً (الأولوية والأفضل أمنياً)، وإذا لم
    يكن موجوداً يقرأه من قاعدة البيانات (لو الأدمن ضبطه من زر 'تغيير المفتاح').
    المفتاح لا يُكتب أبداً بالكود مباشرة.

    ملاحظة توافقية: هذي الدالة ترجع أول مفتاح فقط (للكود القديم الذي قد يستدعيها
    مباشرة). الاستخدام الفعلي بـask_ai_chat يمر عبر get_ai_api_keys() التي ترجع
    كل المفاتيح المضبوطة للتناوب بينها."""
    keys = await get_ai_api_keys()
    return keys[0] if keys else None


async def get_ai_api_keys() -> list:
    """يرجع كل مفاتيح OpenRouter المضبوطة، بترتيب الأولوية:
    1) متغير البيئة OPENROUTER_API_KEY (لو موجود، يوضع أولاً دائماً لأنه الأكثر أماناً).
    2) قائمة المفاتيح المخزّنة بقاعدة البيانات تحت المفتاح 'openrouter_api_keys' (JSON list).
    3) توافقية للخلف: المفتاح القديم المفرد 'openrouter_api_key' لو كان موجوداً من نسخة سابقة
       ولم يُهاجَر بعد لقائمة (نادراً ما يصير، فقط لو قاعدة بيانات قديمة جداً).

    يُزال أي تكرار مع الحفاظ على الترتيب."""
    result = []

    env_key = os.environ.get("OPENROUTER_API_KEY")
    if env_key:
        result.append(env_key)

    raw_list = await get_ai_setting("openrouter_api_keys")
    if raw_list:
        try:
            parsed = json.loads(raw_list)
            if isinstance(parsed, list):
                result.extend([k for k in parsed if isinstance(k, str) and k.strip()])
        except (json.JSONDecodeError, TypeError):
            logger.warning("get_ai_api_keys: تعذّر فك ترميز openrouter_api_keys، يُتجاهل.")

    legacy_single = await get_ai_setting("openrouter_api_key")
    if legacy_single and legacy_single not in result:
        result.append(legacy_single)

    # إزالة التكرار مع الحفاظ على الترتيب
    seen = set()
    deduped = []
    for k in result:
        if k not in seen:
            seen.add(k)
            deduped.append(k)
    return deduped


async def add_ai_api_key(new_key: str) -> int:
    """يضيف مفتاحاً جديداً لقائمة مفاتيح قاعدة البيانات (بدون حذف الموجودين).
    يرجع عدد المفاتيح الإجمالي بقاعدة البيانات بعد الإضافة (لا يشمل مفتاح البيئة)."""
    raw_list = await get_ai_setting("openrouter_api_keys")
    keys = []
    if raw_list:
        try:
            parsed = json.loads(raw_list)
            if isinstance(parsed, list):
                keys = [k for k in parsed if isinstance(k, str) and k.strip()]
        except (json.JSONDecodeError, TypeError):
            keys = []

    if new_key not in keys:
        keys.append(new_key)

    await set_ai_setting("openrouter_api_keys", json.dumps(keys))
    return len(keys)


async def remove_ai_api_key(index: int) -> bool:
    """يحذف مفتاحاً من قائمة قاعدة البيانات حسب فهرسه (0-indexed ضمن القائمة
    المخزّنة بقاعدة البيانات فقط، لا يشمل مفتاح البيئة الذي لا يُحذف من هنا).
    يرجع True لو نجح الحذف."""
    raw_list = await get_ai_setting("openrouter_api_keys")
    if not raw_list:
        return False
    try:
        keys = json.loads(raw_list)
        if not isinstance(keys, list):
            return False
    except (json.JSONDecodeError, TypeError):
        return False

    if index < 0 or index >= len(keys):
        return False

    keys.pop(index)
    await set_ai_setting("openrouter_api_keys", json.dumps(keys))
    return True


async def is_ai_enabled_globally() -> bool:
    val = await get_ai_setting("ai_enabled")
    return val != "0"  # مفعّل افتراضياً إلا لو الأدمن عطّله صراحة


async def is_ai_disabled_for_user(user_id: int) -> bool:
    val = await get_ai_setting(f"ai_disabled_user_{user_id}")
    return val == "1"


async def get_ai_usage(user_id: int, bot_id: int) -> Optional[sqlite3.Row]:
    async with db_cursor() as conn:
        return conn.execute(
            "SELECT * FROM ai_usage WHERE user_id = ? AND bot_id = ?", (user_id, bot_id)
        ).fetchone()


async def can_user_ask_ai(user_id: int, bot_id: int) -> tuple:
    """يرجع (يقدر_يسأل: bool, دقائق_متبقية_أو_None). الحد سؤالان لكل بوت، وبعدها
    قفل 3 ساعات يُحسب من وقت أول سؤال بالنافذة الحالية."""
    usage = await get_ai_usage(user_id, bot_id)
    if not usage or not usage["window_started_at"]:
        return True, None

    window_start = datetime.fromisoformat(usage["window_started_at"])
    elapsed = (datetime.now() - window_start).total_seconds() / 3600.0

    if elapsed >= AI_COOLDOWN_HOURS:
        # انتهت فترة القفل، نصفّر العداد تلقائياً
        async with db_cursor() as conn:
            conn.execute(
                "UPDATE ai_usage SET questions_used = 0, window_started_at = NULL WHERE user_id = ? AND bot_id = ?",
                (user_id, bot_id),
            )
        return True, None

    if usage["questions_used"] >= AI_QUESTIONS_LIMIT:
        remaining_minutes = int((AI_COOLDOWN_HOURS - elapsed) * 60)
        return False, remaining_minutes

    return True, None


async def record_ai_question_used(user_id: int, bot_id: int):
    usage = await get_ai_usage(user_id, bot_id)
    async with db_cursor() as conn:
        if not usage or not usage["window_started_at"]:
            conn.execute(
                """INSERT INTO ai_usage (user_id, bot_id, questions_used, window_started_at)
                   VALUES (?, ?, 1, ?)
                   ON CONFLICT(user_id, bot_id) DO UPDATE SET questions_used = 1, window_started_at = excluded.window_started_at""",
                (user_id, bot_id, datetime.now().isoformat()),
            )
        else:
            conn.execute(
                "UPDATE ai_usage SET questions_used = questions_used + 1 WHERE user_id = ? AND bot_id = ?",
                (user_id, bot_id),
            )


async def reset_all_ai_usage():
    async with db_cursor() as conn:
        conn.execute("DELETE FROM ai_usage")


# ─────────────────────────────────────────────
# دوال محفظة قسائم الذكاء الاصطناعي
# ─────────────────────────────────────────────
async def get_ai_wallet(user_id: int) -> sqlite3.Row:
    async with db_cursor() as conn:
        row = conn.execute("SELECT * FROM ai_wallet WHERE user_id = ?", (user_id,)).fetchone()
        if not row:
            conn.execute("INSERT INTO ai_wallet (user_id) VALUES (?)", (user_id,))
            row = conn.execute("SELECT * FROM ai_wallet WHERE user_id = ?", (user_id,)).fetchone()
        return row


async def add_ai_package_to_user(user_id: int, package_key: str):
    """يضيف رصيد أسئلة الباقة، ويرفع الصلاحيات (لا تُخفض أبداً — فقط تُفعَّل)."""
    pkg = AI_PACKAGES[package_key]
    await get_ai_wallet(user_id)  # تضمن وجود صف
    async with db_cursor() as conn:
        conn.execute(
            """UPDATE ai_wallet SET
                   ai_questions_balance = ai_questions_balance + ?,
                   can_read_files = MAX(can_read_files, ?),
                   can_read_logs = MAX(can_read_logs, ?),
                   can_edit_files = MAX(can_edit_files, ?),
                   can_send_files = MAX(can_send_files, ?),
                   updated_at = datetime('now')
               WHERE user_id = ?""",
            (
                pkg["questions"],
                1 if pkg["can_read_files"] else 0,
                1 if pkg["can_read_logs"] else 0,
                1 if pkg["can_edit_files"] else 0,
                1 if pkg["can_send_files"] else 0,
                user_id,
            ),
        )
        conn.execute(
            """INSERT INTO ai_wallet_purchases (user_id, package_key, stars, questions_added)
               VALUES (?, ?, ?, ?)""",
            (user_id, package_key, pkg["stars"], pkg["questions"]),
        )


async def consume_ai_wallet_question(user_id: int) -> bool:
    """يخصم سؤال واحد من رصيد المحفظة إذا كان متوفراً. يرجع True لو تم الخصم بنجاح."""
    wallet = await get_ai_wallet(user_id)
    if wallet["ai_questions_balance"] <= 0:
        return False
    async with db_cursor() as conn:
        conn.execute(
            "UPDATE ai_wallet SET ai_questions_balance = ai_questions_balance - 1, updated_at = datetime('now') WHERE user_id = ?",
            (user_id,),
        )
    return True


EYRX_AI_DIAGNOSTIC_SYSTEM_PROMPT = (
    "أنت EYRX-AI، مساعد تقني متخصص بتشخيص أخطاء بوتات تيليجرام المبنية بلغة Python أو PHP. "
    "لديك سجل الخطأ الكامل للبوت. اشرح المشكلة بوضوح ودقة بالعربية، وقدّم مثالاً "
    "عملياً على الحل إن أمكن. إذا كان الحل يتطلب تعديل كود، ضع الكود المقترح دائماً "
    "داخل code block منسّق (```python ...``` أو ```php ...``` حسب اللغة). "
    "كن مختصراً ومباشراً، لا تتجاوز 400 كلمة."
)

EYRX_AI_OPEN_SYSTEM_PROMPT = (
    "أنت EYRX-AI، مساعد ذكاء اصطناعي عام مدمج بلوحة تحكم أدمن منصّة استضافة بوتات تيليجرام. "
    "أنت غير مقيّد بموضوع أو مجال معيّن؛ أجب على أي سؤال يطرحه الأدمن -تقنياً كان أو عاماً- "
    "بأفضل ما تستطيع، بدون رفض الإجابة لمجرد أنه خارج نطاق البوتات. إذا زوّدك الأدمن بسجلات "
    "أخطاء أو سجل تشغيل بوت، حلّلها بدقة واشرح السبب الجذري. أي تعديل أو إصلاح كود يجب أن "
    "يوضع دائماً داخل code block منسّق بشكل صحيح (```python ...``` أو المناسب للغة). "
    "كن مباشراً ومفيداً، وأجب بالعربية إلا إذا طلب الأدمن لغة أخرى."
)


def _looks_like_url(value: str) -> bool:
    return value.strip().lower().startswith(("http://", "https://"))


async def _call_gemini_official(credential: str, full_text: str, timeout) -> tuple:
    """يتصل بـGemini API الرسمي (Google AI Studio / generativelanguage.googleapis.com).
    يقبل 3 أشكال اعتماد مختلفة:
    1) رابط اتصال جاهز كامل زوّدته Google للأدمن مباشرة (يُستخدم كما هو).
    2) مفتاح API كلاسيكي بصيغة AIza... يُرسل كبارامتر ?key= بالرابط (الطريقة القديمة).
    3) رمز وصول (access token) من نوع OAuth يبدأ عادة بـAQ. — هذا النوع لا يُقبل عبر
       ?key=، بل يجب إرساله عبر ترويسة X-goog-api-key، وإلا ترجع Google خطأ HTTP 404
       (لأن طلب المصادقة يفشل فتُعامل نقطة النهاية وكأنها غير موجودة). هذا بالضبط ما
       كان يسبب ' Gemini رجع خطأ HTTP 404' رغم أن المفتاح صحيح فعلياً."""
    from aiohttp import ClientSession

    if _looks_like_url(credential):
        url = credential
        headers = {"Content-Type": "application/json"}
    elif credential.startswith("AIza"):
        # مفتاح API كلاسيكي — يُرسل بالرابط كما كان
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-flash-latest:generateContent?key={credential}"
        )
        headers = {"Content-Type": "application/json"}
    else:
        # رمز وصول OAuth (مثل AQ....) — يُرسل حصراً عبر ترويسة X-goog-api-key
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-flash-latest:generateContent"
        )
        headers = {"Content-Type": "application/json", "X-goog-api-key": credential}

    payload = {"contents": [{"parts": [{"text": full_text}]}]}
    async with ClientSession(timeout=timeout) as session:
        async with session.post(url, json=payload, headers=headers) as resp:
            body_text = await resp.text()
            if resp.status != 200:
                logger.error(f"Gemini API رجع {resp.status}: {body_text[:500]}")
                return False, f" Gemini رجع خطأ HTTP {resp.status}: {body_text[:300]}"
            try:
                data = json.loads(body_text)
                reply = data["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError, json.JSONDecodeError):
                logger.error(f"Gemini API رد غير متوقع: {body_text[:500]}")
                return False, " رد غير متوقع من Gemini."
            if not reply:
                return False, " رد فارغ من Gemini."
            return True, reply


async def _call_openai_compatible(credential: str, full_text: str, timeout,
                                   default_url: str, model_name: str, label: str) -> tuple:
    """يتصل بأي API متوافق مع صيغة OpenAI Chat Completions الرسمية (يغطي
    OpenAI/ChatGPT وDeepSeek، لأن DeepSeek الرسمي متوافق فعلياً مع نفس الصيغة).
    يقبل إما مفتاح API خام (Bearer token على الرابط الرسمي الافتراضي) أو رابط
    اتصال جاهز كامل زوّدته الشركة للأدمن مباشرة."""
    from aiohttp import ClientSession

    if _looks_like_url(credential):
        url = credential
        headers = {"Content-Type": "application/json"}
    else:
        url = default_url
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {credential}"}

    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": full_text}],
    }
    async with ClientSession(timeout=timeout) as session:
        async with session.post(url, json=payload, headers=headers) as resp:
            body_text = await resp.text()
            if resp.status != 200:
                logger.error(f"{label} API رجع {resp.status}: {body_text[:500]}")
                if resp.status == 402:
                    return False, (
                        f" {label} رجع خطأ HTTP 402 (Payment Required): "
                        f"رصيد الحساب عند {label} خلص أو الفوترة غير مفعّلة. "
                        f"هذا ليس خطأً بالبوت — لازم شحن الرصيد/تفعيل الفوترة من "
                        f"لوحة تحكم {label} مباشرة."
                    )
                if resp.status in (401, 403):
                    return False, (
                        f" {label} رجع خطأ HTTP {resp.status}: المفتاح غير صالح أو منتهي "
                        f"الصلاحية أو لا يملك صلاحية الوصول. تأكد من نسخ مفتاح API صحيح "
                        f"وفعّال من لوحة تحكم {label}."
                    )
                return False, f" {label} رجع خطأ HTTP {resp.status}: {body_text[:300]}"
            try:
                data = json.loads(body_text)
                reply = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, json.JSONDecodeError):
                logger.error(f"{label} API رد غير متوقع: {body_text[:500]}")
                return False, f" رد غير متوقع من {label}."
            if not reply:
                return False, f" رد فارغ من {label}."
            return True, reply


def _stable_uid_for(user_id: Optional[int], url: str) -> str:
    """يبني uid مستقر (نفس الرقم دائماً لنفس المستخدم) لخدمات kilwa التي تدعم
    'ذاكرة محادثة لكل uid' (kilwa-deepseek/kilwa-chat). لو تجاهلنا uid أو أرسلنا
    قيمة ثابتة واحدة لكل المستخدمين (كما كان يفعل الكود القديم)، فكل مستخدمي
    البوت كانوا يتشاركون نفس ذاكرة المحادثة عند kilwa — ما يفسّر خلط الردود.
    نشتق رقماً ثابتاً من user_id نفسه (وليس من رابط الأدمن) حتى تبقى ذاكرة كل
    مستخدم منفصلة تماماً عن غيره."""
    base = str(user_id) if user_id is not None else "anon"
    digest = hashlib.sha256(base.encode("utf-8")).hexdigest()
    return str(int(digest[:12], 16) % 10_000_000)


async def _call_custom_relay_url(url: str, full_text: str, timeout, label: str,
                                  user_id: Optional[int] = None) -> tuple:
    """يتصل برابط اتصال جاهز (غير API رسمي بصيغة OpenAI/Gemini) حسب التوثيق الرسمي
    الفعلي لكل خدمة معروفة (kilwa-chat / kilwa-deepseek / kilwa-chatgpt على
    bot-hosting.net، وzecora deepseek.php)، بدل تخمين أسماء بارامترات عشوائية.

    لماذا كان الرد يخرج عاماً ("مرحباً! كيف يمكنني مساعدتك؟") رغم وصول الطلب فعلياً:
    الكود القديم كان يدمج system_prompt + سجل الخطأ + المحادثة كاملة بنص واحد طويل
    ويرسله بأول بارامتر ناجح (غالباً ?text=...)، وهذا النص الطويل المصاغ كتعليمات
    نظام يصل لموديل دردشة بسيط (Gemini Flash / GPT-5 Nano) لا يميّز system prompt
    عن رسالة عادية، فيتعامل معه أحياناً كرسالة غير مفهومة ويرجع رداً ترحيبياً
    افتراضياً بدل الإجابة الفعلية. الحل: نطابق كل رابط مع صيغته الموثّقة بالضبط
    (GET+uid+text لـkilwa، POST form/JSON بـmodel+message لـzecora)، ونحافظ على
    uid ثابت خاص بكل مستخدم كي لا تختلط ذاكرة المحادثات بين المستخدمين."""
    from aiohttp import ClientSession

    host = url.split("//", 1)[-1].split("/", 1)[0].lower()
    path = url.split("//", 1)[-1].split("/", 1)[1] if "/" in url.split("//", 1)[-1] else ""
    path = path.split("?", 1)[0].lower()

    def _extract_reply(body_text: str):
        body_text = (body_text or "").strip()
        if not body_text:
            return None
        try:
            data = json.loads(body_text)
        except json.JSONDecodeError:
            return body_text  # رد نصي خام
        if isinstance(data, str) and data.strip():
            return data
        if isinstance(data, dict):
            # صيغ الرد الموثّقة فعلياً لهذه الخدمات بالتحديد (وليس تخمين عام)
            for key in ("reply", "response"):
                val = data.get(key)
                if isinstance(val, str) and val.strip():
                    return val
            try:
                content = data["choices"][0]["message"]["content"]
                if content:
                    return content
            except (KeyError, IndexError, TypeError):
                pass
        return None

    last_error = "لا توجد محاولات"
    async with ClientSession(timeout=timeout) as session:
        # ── حالة 1: روابط kilwa (bot-hosting.net) — GET صرف بصيغة موثّقة ──
        # kilwa-chatgpt: ?text=...   |   kilwa-chat / kilwa-deepseek: ?uid=...&text=...
        if "bot-hosting.net" in host and "kilwa" in path:
            params = {"text": full_text}
            if "kilwa-deepseek" in path or path.rstrip("/").endswith("kilwa-chat"):
                params["uid"] = _stable_uid_for(user_id, url)
            try:
                async with session.get(url, params=params) as resp:
                    body_text = await resp.text()
                    if resp.status == 200:
                        reply = _extract_reply(body_text)
                        if reply:
                            return True, reply
                        last_error = f"GET kilwa → HTTP 200 لكن بلا حقل reply صالح: {body_text[:300]}"
                    else:
                        last_error = f"GET kilwa → HTTP {resp.status}: {body_text[:300]}"
            except asyncio.TimeoutError:
                raise
            except Exception as e:
                last_error = f"GET kilwa استثناء: {type(e).__name__}: {e}"

            logger.error(f"{label}: فشل الاتصال برابط kilwa {url}. آخر خطأ: {last_error}")
            return False, f" تعذر الاتصال بخدمة {label} (kilwa). آخر خطأ: {last_error}"

        # ── حالة 2: زيكورا deepseek.php — POST بصيغة model + message ──
        if "zecora" in host or path.endswith("deepseek.php"):
            payload = {"model": "1", "message": full_text}
            attempts = [
                ("POST_FORM", lambda: session.post(url, data=payload)),
                ("POST_JSON", lambda: session.post(url, json=payload, headers={"Content-Type": "application/json"})),
            ]
            for name, make_request in attempts:
                try:
                    async with make_request() as resp:
                        body_text = await resp.text()
                        if resp.status == 200:
                            reply = _extract_reply(body_text)
                            if reply:
                                return True, reply
                            last_error = f"{name} zecora → HTTP 200 لكن بلا حقل response صالح: {body_text[:300]}"
                        else:
                            last_error = f"{name} zecora → HTTP {resp.status}: {body_text[:300]}"
                except asyncio.TimeoutError:
                    raise
                except Exception as e:
                    last_error = f"{name} zecora استثناء: {type(e).__name__}: {e}"
                    continue

            logger.error(f"{label}: فشل الاتصال برابط zecora {url}. آخر خطأ: {last_error}")
            return False, f" تعذر الاتصال بخدمة {label} (zecora). آخر خطأ: {last_error}"

        # ── حالة 3: رابط غير معروف — نجرّب الطرق الشائعة كاحتياط عام فقط ──
        param_names = ("text", "q", "query", "message", "prompt", "content")
        attempts = [("GET", {p: full_text}) for p in param_names]
        attempts += [("POST_FORM", {p: full_text}) for p in param_names[:2]]
        attempts += [("POST_JSON_OPENAI", None)]
        for method, params in attempts:
            try:
                if method == "GET":
                    async with session.get(url, params=params) as resp:
                        body_text = await resp.text()
                        if resp.status == 200:
                            reply = _extract_reply(body_text)
                            if reply:
                                return True, reply
                        last_error = f"GET?{next(iter(params))}=… → HTTP {resp.status}"
                elif method == "POST_FORM":
                    async with session.post(url, data=params) as resp:
                        body_text = await resp.text()
                        if resp.status == 200:
                            reply = _extract_reply(body_text)
                            if reply:
                                return True, reply
                        last_error = f"POST form({next(iter(params))}) → HTTP {resp.status}"
                else:
                    payload = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": full_text}]}
                    async with session.post(url, json=payload, headers={"Content-Type": "application/json"}) as resp:
                        body_text = await resp.text()
                        if resp.status == 200:
                            reply = _extract_reply(body_text)
                            if reply:
                                return True, reply
                        last_error = f"POST JSON(OpenAI) → HTTP {resp.status}"
            except asyncio.TimeoutError:
                raise
            except Exception as e:
                last_error = f"{method} استثناء: {type(e).__name__}: {e}"
                continue

    logger.error(f"{label}: كل محاولات الاتصال بالرابط الجاهز {url} فشلت. آخر خطأ: {last_error}")
    return False, f" تعذر الاتصال بخدمة {label} عبر الرابط المضبوط رغم تجربة كل الطرق الشائعة (GET/POST). آخر خطأ: {last_error}"


async def ask_ai_chat(messages: list, system_prompt: str, user_id: Optional[int] = None) -> tuple:
    """نواة موحّدة لإرسال محادثة (رسائل بصيغة OpenAI: [{role, content}, ...]) لنموذج AI رسمي
    واحد: النموذج الذي اختاره المستخدم صراحةً (get_ai_model_choice). كل نموذج قد يملك حتى
    5 مفاتيح/روابط مضبوطة من لوحة التحكم — تُجرَّب بالترتيب، وعند فشل مفتاح (خطأ HTTP أو
    استثناء اتصال) يُنتقل تلقائياً للمفتاح التالي دون أي تدخل يدوي، مع إشعار فوري للأدمن
    بأن ذلك المفتاح تحديداً فشل وتم تجاوزه. فقط إذا فشلت كل المفاتيح المضبوطة يُعاد خطأ
    نهائي للمستخدم. ترجع (نجاح: bool, نص الرد أو رسالة خطأ تفصيلية)."""
    try:
        from aiohttp import ClientTimeout
    except ImportError:
        return False, " مكتبة aiohttp غير متوفرة على السيرفر، لا يمكن استخدام مساعد AI حالياً. ثبّتها بأمر: pip install aiohttp"

    model_key = await get_ai_model_choice(user_id) if user_id else AI_MODEL_DEFAULT
    cfg = AI_MODELS_CATALOG.get(model_key)
    if not cfg:
        return False, " نموذج AI غير معروف."

    credentials = await get_official_ai_credentials(model_key)
    if not credentials:
        return False, f" لم يضبط الأدمن بعد أي مفتاح/رابط لـ{cfg['label']} من لوحة التحكم."

    # دمج system_prompt + كامل السياق برسالة نصية واحدة (صيغة موحّدة تناسب كل المزودين)
    history_text = ""
    for m in messages[:-1]:
        role_label = "المستخدم" if m.get("role") == "user" else "المساعد"
        history_text += f"\n[{role_label}]: {m.get('content', '')}"
    last_user_text = messages[-1]["content"] if messages else ""
    full_text = f"{system_prompt}\n{history_text}\n\nالسؤال الحالي:\n{last_user_text}"
    full_text = full_text[:12000]

    # صيغة أبسط وأقصر مخصّصة لروابط "الاتصال الجاهز" (kilwa/zecora وأمثالها): هذه
    # خدمات دردشة عامة بسيطة لا تميّز "تعليمات نظام" عن "رسالة محادثة عادية"، فإرسال
    # نص طويل بصيغة [المستخدم]/[المساعد] يجعلها أحياناً ترجع رداً ترحيبياً افتراضياً
    # بدل الإجابة الفعلية. هنا ندمج التعليمة والسياق بأسلوب مباشر أقصر بكثير.
    relay_history = ""
    for m in messages[:-1]:
        role_label = "أنا" if m.get("role") == "user" else "أنت"
        relay_history += f"\n{role_label}: {m.get('content', '')}"
    relay_text = f"{system_prompt}\n{relay_history}\n\nسؤالي الآن: {last_user_text}".strip()
    relay_text = relay_text[:6000]

    timeout_obj = None
    try:
        from aiohttp import ClientTimeout as _CT
        timeout_obj = _CT(total=60)
    except ImportError:
        pass

    last_error_msg = " لا توجد مفاتيح مضبوطة."
    for key_index, credential in enumerate(credentials):
        try:
            if _looks_like_url(credential):
                # رابط اتصال جاهز غير رسمي (مثل روابط bot-hosting.net: kilwa-chatgpt/
                # kilwa-chat/kilwa-deepseek، أو zecora) — نستخدم الدالة المخصّصة التي
                # تطابق صيغة كل خدمة بالضبط بدل الصيغة الرسمية الموحّدة.
                ok, reply = await _call_custom_relay_url(credential, relay_text, timeout_obj, label=cfg["label"], user_id=user_id)
            elif model_key == "gemini":
                ok, reply = await _call_gemini_official(credential, full_text, timeout_obj)
            elif model_key == "chatgpt":
                ok, reply = await _call_openai_compatible(
                    credential, full_text, timeout_obj,
                    default_url="https://api.openai.com/v1/chat/completions",
                    model_name="gpt-4o-mini", label="ChatGPT",
                )
            else:
                return False, " نموذج AI غير مدعوم."

            if ok:
                return True, reply

            # هذا المفتاح تحديداً فشل — نسجّل ونُعلم الأدمن، وننتقل للمفتاح التالي تلقائياً
            last_error_msg = reply
            logger.warning(f"ask_ai_chat: مفتاح رقم {key_index + 1}/{len(credentials)} لـ{cfg['label']} فشل: {reply}")
            await _notify_admin_ai_key_disabled(model_key, key_index, credential, str(reply))
            continue

        except asyncio.TimeoutError:
            last_error_msg = f" مفتاح رقم {key_index + 1} لـ{cfg['label']} استغرق وقتاً طويلاً جداً (أكثر من 60 ثانية)."
            logger.warning(f"ask_ai_chat: {model_key} مفتاح رقم {key_index + 1} timeout.")
            await _notify_admin_ai_key_disabled(model_key, key_index, credential, "انتهت المهلة (timeout)")
            continue
        except Exception as e:
            last_error_msg = f" خطأ غير متوقع مع مفتاح رقم {key_index + 1} لـ{cfg['label']}: {type(e).__name__}."
            logger.error(f"ask_ai_chat: {model_key} مفتاح رقم {key_index + 1} فشل: {e}", exc_info=True)
            await _notify_admin_ai_key_disabled(model_key, key_index, credential, f"{type(e).__name__}: {e}")
            continue

    # كل المفاتيح المضبوطة لهذا النموذج فشلت
    return False, (
        f" تعذر الاتصال بـ{cfg['label']}: كل المفاتيح المضبوطة ({len(credentials)}) فشلت.\n"
        f"آخر خطأ: {last_error_msg}"
    )


async def _notify_admin_ai_key_disabled(model_key: str, key_index: int, credential: str, error_detail: str):
    """يرسل إشعاراً فورياً للأدمن (OWNER_ID) أن مفتاحاً معيّناً بموديل معيّن فشل وتم
    تجاوزه تلقائياً (الانتقال للمفتاح التالي بالترتيب). مغلَّف بحماية كاملة من الانهيار
    حتى لا يعطّل تدفق التبديل التلقائي نفسه لو فشل إرسال الإشعار لأي سبب."""
    try:
        cfg = AI_MODELS_CATALOG.get(model_key, {})
        label = cfg.get("label", model_key)
        masked = _mask_ai_key(credential)
        text = (
            " تعطيل تلقائي لمفتاح AI\n"
            f"النموذج: {label}\n"
            f"المفتاح رقم: {key_index + 1}\n"
            f"القيمة: <code>{masked}</code>\n"
            f"السبب: {sanitize_html_for_telegram(error_detail, max_len=300)}\n\n"
            "تم تجاوز هذا المفتاح تلقائياً والانتقال للمفتاح التالي إن وُجد."
        )
        if OWNER_ID:
            await bot.send_message(OWNER_ID, text)
    except Exception as e:
        logger.error(f"_notify_admin_ai_key_disabled: تعذر إرسال إشعار الأدمن: {e}")


async def ask_ai_about_error(error_log: str, user_question: str, user_id: Optional[int] = None) -> str:
    """توافقية للخلف: يشخّص خطأ بوت معيّن بشخصية EYRX-AI التشخيصية المحدودة بالموضوع
    (تُستخدم بمحادثة المستخدم العادي المرتبطة ببوت معيّن)."""
    user_content = f"سجل الخطأ:\n```\n{error_log[:3000]}\n```\n\nسؤال المستخدم: {user_question}"
    ok, reply = await ask_ai_chat([{"role": "user", "content": user_content}], EYRX_AI_DIAGNOSTIC_SYSTEM_PROMPT, user_id=user_id)
    if not ok:
        logger.error(f"ask_ai_about_error failed: {reply}")
        return " تعذر التواصل مع الذكاء الاصطناعي حالياً. حاول لاحقاً، أو تواصل مع الأدمن إذا استمرت المشكلة."
    return reply


AI_HISTORY_LIMIT = 3  # آخر 3 رسائل بالمحادثة تُحفظ كذاكرة سياق قصيرة للذكاء الاصطناعي

# قفل لكل مستخدم يمنع إرسال أكثر من سؤال AI بنفس اللحظة (سبب شائع لتعليق/تهنيق
# البوت: ضغط متكرر سريع يفتح عدة طلبات + عدة مؤشرات تحميل متحركة بالتوازي).
_AI_USER_LOCKS: Dict[int, asyncio.Lock] = {}


def _get_ai_user_lock(user_id: int) -> asyncio.Lock:
    lock = _AI_USER_LOCKS.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _AI_USER_LOCKS[user_id] = lock
    return lock


def _trim_ai_history(history: list) -> list:
    return history[-AI_HISTORY_LIMIT:] if history else []


async def _run_ai_with_thinking_indicator(chat_id: int, messages: list, system_prompt: str, user_id: Optional[int] = None) -> tuple:
    """يعرض مؤشر تحميل متحرك ( EYRX-AI يفكّر بعمق...) بالمحادثة أثناء انتظار رد
    الذكاء الاصطناعي، ثم يحذفه فور وصول الرد. ترجع (نجاح: bool, نص الرد أو الخطأ).
    محمي بقفل لكل مستخدم (chat_id) لمنع تراكم عدة طلبات AI متزامنة من نفس
    المستخدم — هذا التراكم (ضغط متكرر سريع) هو السبب الشائع لتجمّد/تهنيق البوت."""
    lock = _get_ai_user_lock(chat_id)
    async with lock:
        thinking_msg = await bot.send_message(chat_id, " EYRX-AI يفكّر بعمق\n▰▱▱▱▱▱▱▱")

        async def _animate():
            frames = [
                " EYRX-AI يفكّر بعمق\n▰▱▱▱▱▱▱▱",
                " EYRX-AI يفكّر بعمق\n▰▰▰▱▱▱▱▱",
                " EYRX-AI يفكّر بعمق\n▰▰▰▰▰▱▱▱",
                " EYRX-AI يفكّر بعمق\n▰▰▰▰▰▰▰▱",
                " EYRX-AI يفكّر بعمق\n▰▰▰▰▰▰▰▰",
            ]
            i = 0
            try:
                while True:
                    await asyncio.sleep(1.3)
                    i = (i + 1) % len(frames)
                    try:
                        await bot.edit_message_text(frames[i], chat_id, thinking_msg.message_id)
                    except Exception:
                        pass
            except asyncio.CancelledError:
                pass

        animator = asyncio.create_task(_animate())
        try:
            try:
                await bot.send_chat_action(chat_id, "typing")
            except Exception:
                pass
            try:
                ok, reply = await asyncio.wait_for(ask_ai_chat(messages, system_prompt, user_id=user_id or chat_id), timeout=55)
            except asyncio.TimeoutError:
                ok, reply = False, " استغرق الرد وقتاً طويلاً جداً، حاول مرة أخرى."
        finally:
            animator.cancel()
            try:
                await animator
            except Exception:
                pass
        try:
            await thinking_msg.delete()
        except Exception:
            pass
        return ok, reply


async def _bump_ai_model_usage_stat(model_key: str, bot_id: int, user_id: int, edit_applied: bool = False):
    """يسجّل استخدام نموذج AI معيّن على ملف/بوت معيّن، لعرض إحصاء دقيق للأدمن
    (كم مرة استُخدم هذا النموذج بالذات على هذا الملف بالذات، وكم تعديل طُبّق فعلياً)."""
    try:
        async with db_cursor() as conn:
            conn.execute(
                """INSERT INTO ai_model_usage_stats (model_key, bot_id, user_id, usage_count, edits_applied_count, last_used_at)
                   VALUES (?, ?, ?, 1, ?, datetime('now'))
                   ON CONFLICT(model_key, bot_id) DO UPDATE SET
                       usage_count = usage_count + 1,
                       edits_applied_count = edits_applied_count + excluded.edits_applied_count,
                       last_used_at = datetime('now')""",
                (model_key, bot_id, user_id, 1 if edit_applied else 0),
            )
    except Exception as e:
        logger.error(f"_bump_ai_model_usage_stat failed: {e}", exc_info=True)


async def _get_ai_model_usage_stat(model_key: str, bot_id: int) -> tuple:
    """يرجع (عدد مرات الاستخدام, عدد التعديلات المطبَّقة فعلياً) لهذا النموذج على هذا الملف."""
    try:
        async with db_cursor() as conn:
            row = conn.execute(
                "SELECT usage_count, edits_applied_count FROM ai_model_usage_stats WHERE model_key = ? AND bot_id = ?",
                (model_key, bot_id),
            ).fetchone()
            if row:
                return row["usage_count"], row["edits_applied_count"]
    except Exception as e:
        logger.error(f"_get_ai_model_usage_stat failed: {e}", exc_info=True)
    return 0, 0


async def notify_admin_ai_file_edit(bot_id: int, user_id: int, model_key: str, file_name: str):
    """يبلّغ الأدمن فوراً بالشات أنه تم تعديل ملف معيّن عبر الذكاء الاصطناعي، مع
    اسم النموذج المستخدم وعدد مرات استخدام هذا النموذج تحديداً على هذا الملف تحديداً."""
    try:
        cfg = AI_MODELS_CATALOG.get(model_key, {})
        label = cfg.get("label", model_key)
        usage_count, edits_count = await _get_ai_model_usage_stat(model_key, bot_id)
        text = (
            "━━━━━━━━━━━━━━━━━━━\n"
            "◆ تعديل ملف عبر الذكاء الاصطناعي ◆\n"
            "━━━━━━━━━━━━━━━━━━━\n\n"
            f" الملف/البوت: #{bot_id} ({html_module.escape(str(file_name))})\n"
            f" المستخدم: <code>{user_id}</code>\n"
            f" النموذج المستخدم: {label}\n\n"
            f" هذا النموذج استُخدم <b>{usage_count}</b> مرة على هذا الملف بالذات، "
            f"وطُبّق منها <b>{edits_count}</b> تعديل فعلي على الكود."
        )
        await bot.send_message(OWNER_ID, text)
    except Exception as e:
        logger.error(f"notify_admin_ai_file_edit failed: {e}", exc_info=True)


async def approve_bot(bot_id: int, admin_note: str = ""):
    async with db_cursor() as conn:
        conn.execute(
            """UPDATE bots SET status = 'approved', admin_note = ?,
               approved_at = datetime('now') WHERE id = ?""",
            (admin_note, bot_id),
        )


async def reject_bot(bot_id: int, admin_note: str = ""):
    async with db_cursor() as conn:
        conn.execute(
            """UPDATE bots SET status = 'rejected', admin_note = ?
               WHERE id = ?""",
            (admin_note, bot_id),
        )


async def approve_site(site_id: int, admin_note: str = ""):
    async with db_cursor() as conn:
        conn.execute(
            """UPDATE sites SET status = 'approved', admin_note = ?,
               approved_at = datetime('now') WHERE id = ?""",
            (admin_note, site_id),
        )


async def reject_site(site_id: int, admin_note: str = ""):
    async with db_cursor() as conn:
        conn.execute(
            """UPDATE sites SET status = 'rejected', admin_note = ?
               WHERE id = ?""",
            (admin_note, site_id),
        )


async def get_all_users() -> List[sqlite3.Row]:
    async with db_cursor() as conn:
        return conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()


async def get_stats() -> Dict[str, int]:
    async with db_cursor() as conn:
        total_users = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
        total_bots = conn.execute("SELECT COUNT(*) as c FROM bots").fetchone()["c"]
        total_sites = conn.execute("SELECT COUNT(*) as c FROM sites").fetchone()["c"]
        active_bots = conn.execute(
            "SELECT COUNT(*) as c FROM bots WHERE status='approved' OR status='running'"
        ).fetchone()["c"]
        return {
            "total_users": total_users,
            "total_bots": total_bots,
            "total_sites": total_sites,
            "active_bots": active_bots,
        }


async def add_coupon(code: str, points: int, max_uses: int, created_by: int):
    async with db_cursor() as conn:
        conn.execute(
            """INSERT INTO coupons (code, points, max_uses, created_by)
               VALUES (?, ?, ?, ?)""",
            (code, points, max_uses, created_by),
        )


async def use_coupon(code: str, user_id: int) -> bool:
    async with db_cursor() as conn:
        coupon = conn.execute(
            "SELECT * FROM coupons WHERE code = ? AND is_active = 1", (code,)
        ).fetchone()
        if not coupon:
            return False
        if coupon["used_count"] >= coupon["max_uses"]:
            return False
        already = conn.execute(
            "SELECT id FROM coupon_uses WHERE coupon_code = ? AND user_id = ?",
            (code, user_id),
        ).fetchone()
        if already:
            return False
        conn.execute(
            "INSERT INTO coupon_uses (coupon_code, user_id) VALUES (?, ?)",
            (code, user_id),
        )
        conn.execute(
            "UPDATE coupons SET used_count = used_count + 1 WHERE code = ?", (code,)
        )
        # لا نستدعي update_user_points() هنا لنفس السبب الجذري المُصلَح بـ add_referral:
        # استدعاء دالة تفتح اتصال قاعدة بيانات مستقل من داخل معاملة مفتوحة أصلاً
        # يسبب تعارض قفل صامت بـ SQLite ويمنع إضافة النقطة فعلياً. التحديث هنا بنفس
        # الاتصال المفتوح مباشرة.
        conn.execute(
            "UPDATE users SET points = points + ? WHERE user_id = ?",
            (coupon["points"], user_id),
        )
        return True


async def add_file_log(user_id: int, file_name: str, action: str):
    async with db_cursor() as conn:
        conn.execute(
            "INSERT INTO file_logs (user_id, file_name, action) VALUES (?, ?, ?)",
            (user_id, file_name, action),
        )


async def get_file_logs() -> List[sqlite3.Row]:
    async with db_cursor() as conn:
        return conn.execute(
            "SELECT * FROM file_logs ORDER BY created_at DESC LIMIT 50"
        ).fetchall()

async def get_random_media() -> Optional[sqlite3.Row]:
    async with db_cursor() as conn:
        return conn.execute("SELECT * FROM media_messages ORDER BY RANDOM() LIMIT 1").fetchone()


async def ban_user(user_id: int):
    async with db_cursor() as conn:
        conn.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (user_id,))


async def unban_user(user_id: int):
    async with db_cursor() as conn:
        conn.execute("UPDATE users SET is_banned = 0 WHERE user_id = ?", (user_id,))


async def set_vip(user_id: int, status: int = 1):
    async with db_cursor() as conn:
        conn.execute("UPDATE users SET is_vip = ? WHERE user_id = ?", (status, user_id))


async def set_admin(user_id: int, status: int = 1):
    async with db_cursor() as conn:
        conn.execute("UPDATE users SET is_admin = ? WHERE user_id = ?", (status, user_id))

async def is_vip_user(user_id: int) -> bool:
    user = await get_user(user_id)
    return bool(user and (user["is_vip"] or user["is_admin"] or user["is_owner"]))


def unicode_bold(text: str) -> str:
    result = ""
    for ch in text:
        if 'A' <= ch <= 'Z':
            result += chr(0x1D400 + ord(ch) - ord('A'))
        elif 'a' <= ch <= 'z':
            result += chr(0x1D41A + ord(ch) - ord('a'))
        else:
            result += ch
    return result




# ─────────────────────────────────────────────
# نظام اللغة (عربي/إنكليزي) — تخزين اختيار كل مستخدم فقط، بدون أي تعديل
# على منطق أو أزرار أو حالات موجودة أصلاً.
# ─────────────────────────────────────────────
async def get_user_language(user_id: int) -> Optional[str]:
    user = await get_user(user_id)
    if not user:
        return None
    try:
        return user["language"]
    except (KeyError, IndexError):
        return None


async def set_user_language(user_id: int, lang: str):
    async with db_cursor() as conn:
        conn.execute("UPDATE users SET language = ? WHERE user_id = ?", (lang, user_id))


# ─────────────────────────────────────────────
# نظام الاشتراك الإجباري
# ─────────────────────────────────────────────
async def is_user_subscribed(bot_instance: Bot, user_id: int) -> bool:
    try:
        member = await bot_instance.get_chat_member(FORCE_SUB_CHANNEL_ID, user_id)
        return member.status not in ("left", "kicked")
    except Exception as e:
        logger.warning(f"is_user_subscribed check failed for {user_id}: {e}")
        # في حال تعذّر التحقق (مثلاً البوت مش أدمن بالقناة)، لا نمنع المستخدم
        # حتى لا نعطّل البوت بالكامل بسبب إعداد ناقص من طرف الأدمن.
        return True


# ─────────────────────────────────────────────
# BOT SETUP
# ─────────────────────────────────────────────
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN, parse_mode=types.ParseMode.HTML)
dp = Dispatcher(bot, storage=storage)

# ─────────────────────────────────────────────
# GLOBAL CRASH-PROOFING
# ─────────────────────────────────────────────
@dp.errors_handler()
async def global_error_handler(update: types.Update, exception: Exception):
    try:
        logger.error(f"Unhandled exception while processing update {update}: {exception}", exc_info=True)
    except Exception:
        logger.error("Unhandled exception (failed to log update details)", exc_info=True)

    try:
        chat_id = None
        if update.callback_query and update.callback_query.message:
            chat_id = update.callback_query.message.chat.id
            try:
                await update.callback_query.answer(" صار خطأ، حاول مرة ثانية.", show_alert=True)
            except Exception:
                pass
        elif update.message:
            chat_id = update.message.chat.id

        if chat_id:
            try:
                await bot.send_message(
                    chat_id,
                    " صار خطأ غير متوقع.\nجرب /start أو ارجع للقائمة الرئيسية.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="القائمة الرئيسية ◆", callback_data="main_menu")],
                    ])
                )
            except Exception:
                pass
    except Exception:
        pass

    return True



def sanitize_html_for_telegram(text: str, max_len: int = 4000) -> str:
    if text is None:
        return ""
    safe = html_module.escape(str(text), quote=False)
    if len(safe) > max_len:
        safe = safe[:max_len] + "\n\n… (تم اقتصاص النص لأنه طويل جداً)"
    return safe


async def _safe_bot_send(chat_id: int, text: str, reply_markup=None) -> bool:
    """إرسال رسالة عادية مع إعادة محاولة واحدة تلقائياً عند أي عطل اتصال مؤقت بسيرفرات
    تيليجرام (شائع على شبكات الموبايل/الاستضافة عبر Termux)، بدل ما يفشل الرد بالكامل
    على أول عطل شبكة لحظي."""
    for attempt in (1, 2):
        try:
            await bot.send_message(chat_id, text, reply_markup=reply_markup)
            return True
        except Exception as e:
            logger.warning(f"_safe_bot_send: محاولة {attempt} فشلت: {type(e).__name__}: {e}")
            if attempt == 1:
                await asyncio.sleep(1.5)
    try:
        await bot.send_message(chat_id, " صار خطأ مؤقت بالاتصال، حاول مرة أخرى.")
    except Exception:
        pass
    return False


async def _safe_ai_reply_send(chat_id: int, reply: str, kb, ai_code: Optional[str] = None) -> bool:
    """يرسل رد الذكاء الاصطناعي بأمان، ويحل مشكلتين شائعتين كانتا تسبب توقف الرد على
    الأدمن بالكامل:
    1) رد ضخم (مثال: كود بوت تيليجرام كامل بمئات الأسطر) — تيليجرام يرفض أي رسالة
       أطول من 4096 محرف، فكان الكود القديم يقتصّه بصمت (format_ai_reply_for_telegram)
       ويفقد جزءاً كبيراً منه. الآن: أي رد أطول من العتبة يُرسل تلقائياً كملف كامل غير
       منقوص (بجانب معاينة قصيرة بالمحادثة)، بدل انتظار أن يضغط الأدمن زر "إرسال كملف" يدوياً.
    2) عطل اتصال مؤقت بسيرفرات تيليجرام (شائع على شبكات الموبايل/الاستضافة عبر Termux،
       ويظهر بالسجل كـ ClientOSError / Unclosed session) قد يُسقط طلب الإرسال لحظياً.
       بدل ما ينهار على الأدمن بخطأ غامض ويوقف معالجة رسالته، نعيد المحاولة تلقائياً،
       ثم نتراجع لرد نصي خام بدون تنسيق، ثم كملف كحل أخير مضمون الوصول دائماً."""
    AUTO_FILE_THRESHOLD = 3500

    # رد ضخم → يُرسل كملف كامل مباشرة (بدل الاقتصاص) + معاينة قصيرة بالمحادثة
    if len(reply) > AUTO_FILE_THRESHOLD:
        preview = reply[:500].strip() + "\n\n… (الرد كامل غير منقوص مُرفق كملف بالأسفل لأنه طويل جداً على رسالة تيليجرام)"
        try:
            await bot.send_message(chat_id, f" {html_module.escape(preview)}", reply_markup=kb)
        except Exception as e:
            logger.warning(f"_safe_ai_reply_send: فشلت معاينة الرد الضخم: {type(e).__name__}: {e}")
        filename = "ward_ai_fix.py" if ai_code else "ward_ai_reply.txt"
        content = ai_code if ai_code else reply
        return await send_text_as_file(chat_id, content, filename)

    # رد عادي: محاولة إرسال طبيعية، مع إعادة محاولة واحدة عند أي عطل مؤقت
    text_to_send = f" {format_ai_reply_for_telegram(reply)}"
    for attempt in (1, 2):
        try:
            await bot.send_message(chat_id, text_to_send, reply_markup=kb)
            return True
        except Exception as e:
            logger.warning(f"_safe_ai_reply_send: محاولة الإرسال رقم {attempt} فشلت: {type(e).__name__}: {e}")
            if attempt == 1:
                await asyncio.sleep(1.5)  # مهلة قصيرة قبل إعادة المحاولة (عطل اتصال مؤقت غالباً)
                continue

    # فشلت المحاولتان بصيغة HTML+كيبورد → نص خام بدون تنسيق كحل احتياطي
    try:
        await bot.send_message(chat_id, reply[:4000], parse_mode=None)
        return True
    except Exception as e:
        logger.error(f"_safe_ai_reply_send: فشل حتى النص الخام: {type(e).__name__}: {e}", exc_info=True)

    # آخر حل مضمون: إرساله كملف
    return await send_text_as_file(chat_id, reply, "ward_ai_reply.txt")


def format_ai_reply_for_telegram(reply: str, max_len: int = 3800) -> str:
    """يحوّل رد الذكاء الاصطناعي (نص عادي قد يحتوي ```code blocks```) إلى HTML آمن
    ومنسّق لتيليجرام: أي كود بين ```...``` يُعرض داخل <pre><code> بشكل واضح ومقروء،
    وباقي النص العادي يُهرَّب بأمان. هذا يمنع خطأ 'can't parse entities' الذي كان
    يوقف إرسال رد الذكاء الاصطناعي بصمت كلما احتوى الرد على رمز مثل < أو > أو &
    (شائع جداً بأمثلة الكود)، لأن البوت مضبوط افتراضياً بـ parse_mode=HTML."""
    if not reply:
        return ""
    if len(reply) > max_len:
        reply = reply[:max_len] + "\n…"

    segments = re.split(r"```(?:[a-zA-Z0-9_+-]*\n)?(.*?)```", reply, flags=re.S)
    out = []
    for i, chunk in enumerate(segments):
        if i % 2 == 1:
            code = html_module.escape(chunk.strip("\n"))
            out.append(f"<pre><code>{code}</code></pre>")
        elif chunk:
            out.append(html_module.escape(chunk))
    return "".join(out)


def extract_ai_code_block(text: str) -> Optional[str]:
    """يستخرج أكبر code block (```...```) من رد الذكاء الاصطناعي — عادةً هو الملف
    الكامل المُصحَّح المطلوب تطبيقه مباشرة. يرجع None إذا لم يوجد أي code block."""
    if not text:
        return None
    blocks = re.findall(r"```(?:[a-zA-Z0-9_+-]*\n)?(.*?)```", text, flags=re.S)
    blocks = [b.strip("\n") for b in blocks if b.strip()]
    if not blocks:
        return None
    return max(blocks, key=len)


def resolve_bot_target_file(bot_data) -> Path:
    """يحدد مسار الملف الفعلي الذي يجب قراءته أو تعديله لهذا البوت: ملف التشغيل
    المخصص إن وُجد وكان اسمه آمناً، وإلا الملف الرئيسي المرفوع."""
    run_file = bot_data["run_file"]
    file_path = bot_data["file_path"]
    if run_file and is_safe_run_file(run_file):
        return Path(file_path).parent / run_file
    return Path(file_path)


async def apply_ai_code_to_bot_file(bot_id: int, new_code: str) -> tuple:
    """يكتب كود الذكاء الاصطناعي مباشرة على ملف البوت الحقيقي، بعد أخذ نسخة
    احتياطية قابلة للاسترجاع بجانب الملف الأصلي، ثم يعيد تشغيل البوت تلقائياً
    إذا كان شغّالاً وقت التعديل. يرجع (نجاح: bool, رسالة تفصيلية للمستخدم)."""
    bot_data = await get_bot_by_id(bot_id)
    if not bot_data:
        return False, " البوت غير موجود."
    target_file = resolve_bot_target_file(bot_data)
    if not target_file.exists():
        return False, " ملف البوت غير موجود على السيرفر."
    try:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        backup_path = target_file.parent / f"{target_file.stem}.ai_bak_{timestamp}{target_file.suffix}"
        shutil.copy2(target_file, backup_path)

        async with aiofiles.open(target_file, mode='w', encoding='utf-8') as f:
            await f.write(new_code)

        metadata_block = generate_pixel_encoding_block(
            bot_data["user_id"], bot_id,
            "javascript" if target_file.suffix.lower() == ".js" else "python_bot"
        )
        await prepend_metadata_to_file(target_file, metadata_block)

        restart_result = await restart_bot_if_running(bot_id, bot_data["file_path"])
        msg = (
            f" تم تطبيق تعديل الذكاء الاصطناعي على <code>{target_file.name}</code> بنجاح.\n"
            f" نسخة احتياطية من قبل التعديل محفوظة باسم: <code>{backup_path.name}</code>\n"
            f"(احتفظ بهذا الاسم لو احتجت الرجوع للنسخة القديمة يدوياً من السيرفر)."
        )
        if restart_result is not None:
            started, reason = restart_result
            msg += f"\n إعادة التشغيل التلقائية: {' نجحت' if started else ' فشلت - ' + sanitize_html_for_telegram(str(reason), max_len=200)}"
        return True, msg
    except Exception as e:
        logger.error(f"apply_ai_code_to_bot_file failed for bot {bot_id}: {e}", exc_info=True)
        return False, f" فشل تطبيق التعديل: {sanitize_html_for_telegram(str(e), max_len=300)}"


async def send_text_as_file(chat_id: int, content: str, filename: str = "ward_ai_file.py") -> bool:
    """يرسل أي نص (رد ذكاء اصطناعي، كود مُصحَّح، إلخ) كملف قابل للتنزيل بالمحادثة."""
    try:
        dest_dir = Path("ai_uploads")
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / f"{uuid.uuid4().hex[:8]}_{filename}"
        async with aiofiles.open(dest_path, mode='w', encoding='utf-8') as f:
            await f.write(content)
        await bot.send_document(chat_id, InputFile(str(dest_path)))
        try:
            os.remove(dest_path)
        except Exception:
            pass
        return True
    except Exception as e:
        logger.error(f"send_text_as_file failed: {e}", exc_info=True)
        return False


def mask_token_display(token: Optional[str], not_set_label: str) -> str:
    """يعرض التوكن مختصراً جزئياً لأسباب أمان (أول 8 وآخر 4 محارف فقط)."""
    if not token:
        return not_set_label
    if len(token) <= 14:
        return token
    return f"{token[:8]}…{token[-4:]}"


async def safe_send_message(chat_id: int, text: str, reply_markup=None, escape: bool = True):
    try:
        payload = sanitize_html_for_telegram(text) if escape else text[:4000]
        await bot.send_message(chat_id, payload, reply_markup=reply_markup)
        return True
    except TelegramAPIError as e:
        logger.warning(f"safe_send_message failed for {chat_id}: {e}")
        return False
    except Exception as e:
        logger.warning(f"safe_send_message unexpected failure for {chat_id}: {e}")
        return False


async def safe_answer_callback(callback: types.CallbackQuery, text: str = None, show_alert: bool = False):
    try:
        await callback.answer(text, show_alert=show_alert)
    except Exception as e:
        logger.debug(f"safe_answer_callback ignored error: {e}")

# ─────────────────────────────────────────────
# STATES
# ─────────────────────────────────────────────
class UploadBotState(StatesGroup):
    waiting_file = State()
    waiting_token = State()
    waiting_run_file = State()


class UploadSiteState(StatesGroup):
    waiting_file = State()


class AdminCreateCouponState(StatesGroup):
    waiting_code = State()
    waiting_points = State()
    waiting_max_uses = State()


class AdminAddPointsState(StatesGroup):
    waiting_user_id = State()
    waiting_points = State()


class AdminDeductPointsState(StatesGroup):
    waiting_user_id = State()
    waiting_points = State()


class AdminVIPState(StatesGroup):
    waiting_user_id = State()


class AdminBanUserState(StatesGroup):
    waiting_user_id = State()


class AdminUnbanUserState(StatesGroup):
    waiting_user_id = State()


class BroadcastState(StatesGroup):
    waiting_message = State()


class AdminAddMediaState(StatesGroup):
    waiting_media = State()


class AdminAddAdminState(StatesGroup):
    waiting_user_id = State()


class AdminRemoveAdminState(StatesGroup):
    waiting_user_id = State()


class AdminTerminalState(StatesGroup):
    waiting_command = State()


class AdminChangeTokenState(StatesGroup):
    waiting_token = State()


class UserChangeTokenState(StatesGroup):
    waiting_token = State()


class AdminChangeRunFileState(StatesGroup):
    waiting_run_file = State()


class UserChangeRunFileState(StatesGroup):
    waiting_run_file = State()


class AdminUseCouponState(StatesGroup):
    waiting_user_id = State()
    waiting_coupon_code = State()


class DeveloperContactState(StatesGroup):
    waiting_message = State()


class AdminUpgradeUserState(StatesGroup):
    waiting_user_id = State()
    waiting_tier = State()


class AdminChangeOwnerState(StatesGroup):
    waiting_new_owner_id = State()


class AdminSectionMediaState(StatesGroup):
    waiting_media = State()


class VipInstallLibsState(StatesGroup):
    waiting_lib_name = State()


class VipEditCodeState(StatesGroup):
    waiting_code = State()


class VipEditFileState(StatesGroup):
    waiting_file = State()


class UserFindReplaceState(StatesGroup):
    waiting_old_text = State()
    waiting_new_text = State()


class GrantFolderPermissionState(StatesGroup):
    waiting_user_id = State()
    waiting_folder_path = State()


class AddForceSubTargetState(StatesGroup):
    waiting_display_name = State()
    waiting_identifier_or_url = State()


class AskAIState(StatesGroup):
    waiting_question = State()
    waiting_add_feature_request = State()  # انتظار طلب حر لإضافة ميزة/تعديل بالبوت


class AdminAIChatState(StatesGroup):
    waiting_message = State()


class AdminSetAIKeyState(StatesGroup):
    waiting_key = State()
    waiting_official_credential = State()  # إضافة مفتاح/رابط رسمي جديد لنموذج محدد (gemini/chatgpt)


class AdminToggleAIForUserState(StatesGroup):
    waiting_user_id = State()


class AdminGrantAIFullAccessState(StatesGroup):
    waiting_user_id = State()


class AdminSetSiteIPState(StatesGroup):
    waiting_url = State()


class AdminSearchUserState(StatesGroup):
    waiting_user_id = State()


class AdminMassBanState(StatesGroup):
    waiting_user_ids = State()


class VipShareBotState(StatesGroup):
    waiting_target_user = State()


class AdminAddFolderState(StatesGroup):
    waiting_user_id = State()
    waiting_section = State()
    waiting_size = State()
    waiting_name = State()


class AdminDeleteUserFilesState(StatesGroup):
    waiting_user_id = State()
    waiting_section = State()



# ─────────────────────────────────────────────
# نظام الترجمة (عربي / إنكليزي)
# ─────────────────────────────────────────────
# كل نص ثابت بالبوت موجود هون بمفتاح واحد، بنسختين (ar/en). الدالة t()
# بترجع النص المناسب حسب لغة المستخدم المخزنة، وإذا ما عنده لغة محفوظة
# (مستخدم قديم لسا ما اختار)، بترجع العربي كافتراضي حتى ما ينكسر شي.
# هاد الملف الترجمي منفصل تماماً عن باقي الكود ولا يغيّر أي منطق أو أي
# callback_data أو أي زر موجود أصلاً.
TRANSLATIONS = {
    'choose_language': {
        "ar": ' مرحباً! اختر لغتك المفضلة:',
        "en": ' Welcome! Please choose your preferred language:',
        "fr": ' Bienvenue ! Veuillez choisir votre langue préférée :',
    },
    'language_set_ar': {
        "ar": ' تم اختيار اللغة العربية.',
        "en": ' Arabic language selected.',
        "fr": ' La langue arabe a été sélectionnée.',
    },
    'language_set_en': {
        "ar": ' تم اختيار اللغة الإنكليزية.',
        "en": ' English language selected.',
        "fr": ' La langue anglaise a été sélectionnée.',
    },
    'language_set_fr': {
        "ar": ' تم اختيار اللغة الفرنسية.',
        "en": ' French language selected.',
        "fr": ' La langue française a été sélectionnée.',
    },
    'change_language_btn': {
        "ar": ' تغيير اللغة',
        "en": ' Change Language',
        "fr": ' Changer de langue',
    },
    'change_language_prompt': {
        "ar": ' اختر لغتك المفضلة:',
        "en": ' Choose your preferred language:',
        "fr": ' Choisissez votre langue préférée :',
    },
    'force_sub_required': {
        "ar": ' لازم تشترك بالقناة وتتابعنا على انستغرام قبل ما تقدر تستخدم البوت.\n\n1 اضغط زر الاشتراك بالقناة بالأسفل.\n2 اضغط زر متابعتنا على انستغرام.\n3 بعد كذا، اضغط زر «تحقق من الاشتراك ».',
        "en": ' You must join our channel and follow us on Instagram before using this bot.\n\n1 Tap the channel subscribe button below.\n2 Tap the Instagram follow button.\n3 Then tap “Verify Subscription ”.',
        "fr": " Vous devez rejoindre notre chaîne et nous suivre sur Instagram avant d'utiliser ce bot.\n\n1 Appuyez sur le bouton d'abonnement à la chaîne ci-dessous.\n2 Appuyez sur le bouton pour nous suivre sur Instagram.\n3 Ensuite, appuyez sur « Vérifier l'abonnement  ».",
    },
    'force_sub_channel_btn': {
        "ar": ' اشترك بالقناة',
        "en": ' Join Channel',
        "fr": ' Rejoindre la chaîne',
    },
    'force_sub_verify_btn': {
        "ar": ' تحقق من الاشتراك',
        "en": ' Verify Subscription',
        "fr": " Vérifier l'abonnement",
    },
    'force_sub_still_not_joined': {
        "ar": ' لسا ما اشتركت بالقناة. اشترك أولاً ثم اضغط تحقق.',
        "en": " You haven't joined the channel yet. Join first, then tap verify.",
        "fr": " Vous n'avez pas encore rejoint la chaîne. Rejoignez-la d'abord, puis appuyez sur vérifier.",
    },
    'force_sub_success': {
        "ar": ' تم التحقق من اشتراكك، أهلاً فيك!',
        "en": ' Subscription verified, welcome!',
        "fr": ' Abonnement vérifié, bienvenue !',
    },
    'force_sub_instagram_btn': {
        "ar": ' تابعنا على انستغرام',
        "en": ' Follow us on Instagram',
        "fr": ' Suivez-nous sur Instagram',
    },
    'main_menu_title': {
        "ar": ' أهلاً بك في بوت رفع استضافه EYRX ',
        "en": ' Welcome to EYRX Hosting Bot ',
        "fr": " Bienvenue sur le bot d'hébergement EYRX ",
    },
    'points_label': {
        "ar": 'نقاطك',
        "en": 'Your Points',
        "fr": 'Vos points',
    },
    'upgrade_status': {
        "ar": 'حالة الترقية',
        "en": 'Upgrade Status',
        "fr": 'Statut de mise à niveau',
    },
    'max_files': {
        "ar": 'الحد الأقصى للملفات',
        "en": 'Max Files',
        "fr": 'Fichiers max',
    },
    'concurrent_run': {
        "ar": 'تشغيل متزامن',
        "en": 'Concurrent Runs',
        "fr": 'Exécutions simultanées',
    },
    'points_system': {
        "ar": 'نظام النقاط',
        "en": 'Points System',
        "fr": 'Système de points',
    },
    'per_bot_upload': {
        "ar": 'كل رفع بوت يكلف {pts} نقاط',
        "en": 'Each bot upload costs {pts} points',
        "fr": 'Chaque envoi de bot coûte {pts} points',
    },
    'per_site_upload': {
        "ar": 'كل رفع موقع يكلف {pts} نقاط',
        "en": 'Each site upload costs {pts} points',
        "fr": 'Chaque envoi de site coûte {pts} points',
    },
    'per_referral': {
        "ar": 'كل دعوة تمنحك {pts} نقطة',
        "en": 'Each referral gives you {pts} point(s)',
        "fr": 'Chaque parrainage vous donne {pts} point(s)',
    },
    'choose_below': {
        "ar": 'اختر من القائمة',
        "en": 'Choose from the menu below',
        "fr": 'Choisissez dans le menu ci-dessous',
    },
    'upload_bot_btn': {
        "ar": 'رفع بوت',
        "en": 'Upload Bot',
        "fr": 'Envoyer un bot',
    },
    'my_bots_btn': {
        "ar": 'بوتاتي',
        "en": 'My Bots',
        "fr": 'Mes bots',
    },
    'upload_site_btn': {
        "ar": 'رفع موقع',
        "en": 'Upload Site',
        "fr": 'Envoyer un site',
    },
    'my_sites_btn': {
        "ar": 'مواقعي المرفوعه',
        "en": 'My Sites',
        "fr": 'Mes sites',
    },
    'my_points_btn': {
        "ar": 'نقاطي',
        "en": 'My Points',
        "fr": 'Mes points',
    },
    'referral_btn': {
        "ar": 'رابط الدعوة',
        "en": 'Referral Link',
        "fr": 'Lien de parrainage',
    },
    'change_language_btn2': {
        "ar": 'تغيير اللغة',
        "en": 'Change Language',
        "fr": 'Changer de langue',
    },
    'developer_btn': {
        "ar": 'المطور',
        "en": 'Developer',
        "fr": 'Développeur',
    },
    'channel_btn': {
        "ar": 'القناة',
        "en": 'Channel',
        "fr": 'Chaîne',
    },
    'how_it_works_btn': {
        "ar": 'كيف يعمل؟',
        "en": 'How It Works?',
        "fr": 'Comment ça marche ?',
    },
    'no_bots': {
        "ar": 'لا توجد بوتات.',
        "en": 'No bots found.',
        "fr": 'Aucun bot trouvé.',
    },
    'manage_bot': {
        "ar": 'إدارة {name}',
        "en": 'Manage {name}',
        "fr": 'Gérer {name}',
    },
    'back': {
        "ar": 'رجوع',
        "en": 'Back',
        "fr": 'Retour',
    },
    'back_to_main': {
        "ar": 'القائمة الرئيسية',
        "en": 'Main Menu',
        "fr": 'Menu principal',
    },
    'start_bot': {
        "ar": 'تشغيل البوت',
        "en": 'Start Bot',
        "fr": 'Démarrer le bot',
    },
    'stop_bot': {
        "ar": 'إيقاف البوت',
        "en": 'Stop Bot',
        "fr": 'Arrêter le bot',
    },
    'restart_bot': {
        "ar": 'إعادة التشغيل',
        "en": 'Restart',
        "fr": 'Redémarrer',
    },
    'error_log': {
        "ar": 'سجل الأخطاء',
        "en": 'Error Log',
        "fr": 'Journal des erreurs',
    },
    'log_menu_btn': {
        "ar": ' سجل',
        "en": ' Log',
        "fr": ' Journal',
    },
    'full_run_log': {
        "ar": ' سجل التشغيل الكامل',
        "en": ' Full Run Log',
        "fr": " Journal complet d'exécution",
    },
    'change_token': {
        "ar": 'تغيير التوكن',
        "en": 'Change Token',
        "fr": 'Changer le jeton',
    },
    'change_run_file': {
        "ar": 'تغيير ملف التشغيل',
        "en": 'Change Run File',
        "fr": "Changer le fichier d'exécution",
    },
    'bot_log': {
        "ar": 'سجل البوت',
        "en": 'Bot Log',
        "fr": 'Journal du bot',
    },
    'bot_link': {
        "ar": 'البوت العام',
        "en": 'Bot Link',
        "fr": 'Lien du bot',
    },
    'change_owner_id': {
        "ar": 'تغيير الايدي',
        "en": 'Change ID',
        "fr": "Changer l'ID",
    },
    'install_libs': {
        "ar": 'تثبيت مكاتب',
        "en": 'Install Libs',
        "fr": 'Installer des bibliothèques',
    },
    'edit_file': {
        "ar": 'تعديل الملف',
        "en": 'Edit File',
        "fr": 'Modifier le fichier',
    },
    'find_replace_edit': {
        "ar": ' تحرير',
        "en": ' Edit',
        "fr": ' Modifier',
    },
    'owner_id_label': {
        "ar": 'معرّف المالك (Owner ID)',
        "en": 'Owner ID',
        "fr": 'ID du propriétaire',
    },
    'show_full_token': {
        "ar": ' إظهار التوكن كاملاً',
        "en": ' Show Full Token',
        "fr": ' Afficher le jeton complet',
    },
    'full_token_alert': {
        "ar": 'التوكن الكامل:\n{token}',
        "en": 'Full token:\n{token}',
        "fr": 'Jeton complet :\n{token}',
    },
    'bot_stats': {
        "ar": 'إحصائيات البوت',
        "en": 'Bot Stats',
        "fr": 'Statistiques du bot',
    },
    'share_bot': {
        "ar": 'مشاركة البوت',
        "en": 'Share Bot',
        "fr": 'Partager le bot',
    },
    'advanced_settings': {
        "ar": 'إعدادات متقدمة',
        "en": 'Advanced',
        "fr": 'Avancé',
    },
    'delete_file': {
        "ar": 'حذف الملف',
        "en": 'Delete File',
        "fr": 'Supprimer le fichier',
    },
    'download_file': {
        "ar": 'تحميل الملف',
        "en": 'Download File',
        "fr": 'Télécharger le fichier',
    },
    'change_file_owner': {
        "ar": 'تغيير مالك الملف',
        "en": 'Change Owner',
        "fr": 'Changer le propriétaire',
    },
    'back_to_bots': {
        "ar": 'رجوع للبوتات',
        "en": 'Back to Bots',
        "fr": 'Retour aux bots',
    },
    'view_code': {
        "ar": 'رؤية الكود',
        "en": 'View Code',
        "fr": 'Voir le code',
    },
    'file_contents': {
        "ar": 'محتوى الملف',
        "en": 'File Contents',
        "fr": 'Contenu du fichier',
    },
    'refresh': {
        "ar": 'تحديث',
        "en": 'Refresh',
        "fr": 'Actualiser',
    },
    'update': {
        "ar": 'تحديث',
        "en": 'Update',
        "fr": 'Mettre à jour',
    },
    'no_errors': {
        "ar": 'لا توجد أخطاء',
        "en": 'No errors found',
        "fr": 'Aucune erreur trouvée',
    },
    'response_speed': {
        "ar": 'سرعة الاستجابة',
        "en": 'Response Speed',
        "fr": 'Vitesse de réponse',
    },
    'ms_unit': {
        "ar": 'ms',
        "en": 'ms',
        "fr": 'ms',
    },
    'send_new_code': {
        "ar": 'أرسل الكود الجديد كاملاً وسيتم استبدال ملف البوت.',
        "en": 'Send the new complete code and it will replace the bot file.',
        "fr": 'Envoyez le nouveau code complet et il remplacera le fichier du bot.',
    },
    'file_label': {
        "ar": 'الملف',
        "en": 'File',
        "fr": 'Fichier',
    },
    'status_label': {
        "ar": 'الحالة',
        "en": 'Status',
        "fr": 'Statut',
    },
    'type_label': {
        "ar": 'النوع',
        "en": 'Type',
        "fr": 'Type',
    },
    'token_label': {
        "ar": 'التوكن',
        "en": 'Token',
        "fr": 'Jeton',
    },
    'run_file_label': {
        "ar": 'ملف التشغيل',
        "en": 'Run File',
        "fr": "Fichier d'exécution",
    },
    'code_preview': {
        "ar": 'مقتطف من الكود',
        "en": 'Code Preview',
        "fr": 'Aperçu du code',
    },
    'manage_bot_title': {
        "ar": 'إدارة البوت',
        "en": 'Manage Bot',
        "fr": 'Gérer le bot',
    },
    'vip_required': {
        "ar": ' هذه الميزة متاحة فقط لأعضاء VIP. ادعو 6 أشخاص للحصول على VIP.',
        "en": ' VIP only feature. Invite 6 people to get VIP.',
        "fr": ' Fonctionnalité réservée aux VIP. Invitez 6 personnes pour obtenir le VIP.',
    },
    'install_libs_title': {
        "ar": 'تثبيت مكاتب',
        "en": 'Install Libraries',
        "fr": 'Installer des bibliothèques',
    },
    'install_libs_desc': {
        "ar": 'أرسل اسم المكتبة التي تريد تثبيتها:\n(مثال: aiogram, requests, bs4)',
        "en": 'Send the library name to install:\n(e.g. aiogram, requests, bs4)',
        "fr": 'Envoyez le nom de la bibliothèque à installer :\n(ex. aiogram, requests, bs4)',
    },
    'view_code_title': {
        "ar": 'رؤية الكود',
        "en": 'View Code',
        "fr": 'Voir le code',
    },
    'view_code_desc': {
        "ar": 'هنا يمكنك رؤية شقفة كبيرة من كود البوت الخاص بك.',
        "en": 'Here you can view a large portion of your bot code.',
        "fr": 'Ici vous pouvez voir une grande partie du code de votre bot.',
    },
    'file_contents_title': {
        "ar": 'محتوى الملف',
        "en": 'File Contents',
        "fr": 'Contenu du fichier',
    },
    'file_contents_desc': {
        "ar": 'محتوى الملف الكامل سيتم إرساله كملف.',
        "en": 'The full file contents will be sent as a file.',
        "fr": 'Le contenu complet du fichier sera envoyé sous forme de fichier.',
    },
    'bot_link_title': {
        "ar": 'البوت العام',
        "en": 'Bot Link',
        "fr": 'Lien du bot',
    },
    'edit_file_title': {
        "ar": 'تعديل الملف',
        "en": 'Edit File',
        "fr": 'Modifier le fichier',
    },
    'edit_file_desc': {
        "ar": 'أرسل ملف .py جديد وسيتم استبدال الملف الحالي.',
        "en": 'Send a new .py file and it will replace the current one.',
        "fr": "Envoyez un nouveau fichier .py et il remplacera l'actuel.",
    },
    'send_file_py': {
        "ar": 'أرسل ملف بلغة (.py) أو (.php) أو (.js) فقط\n(ملفات .js تعمل تلقائياً عبر Node.js)',
        "en": 'Send a Python (.py), PHP (.php), or JavaScript (.js) file only\n(.js files run automatically via Node.js)',
        "fr": 'Envoyez uniquement un fichier Python (.py), PHP (.php) ou JavaScript (.js)\n(les fichiers .js sont exécutés automatiquement via Node.js)',
    },
    'send_file_html': {
        "ar": 'أرسل ملف بلغة HTML أو PHP فقط',
        "en": 'Send an HTML or PHP file only',
        "fr": 'Envoyez uniquement un fichier HTML ou PHP',
    },
    'notes': {
        "ar": 'ملاحظات',
        "en": 'Notes',
        "fr": 'Remarques',
    },
    'points_deducted_after_approval': {
        "ar": '',
        "en": '',
        "fr": 'Les points seront déduits après approbation',
    },
    'admin_approval_required': {
        "ar": 'جاهز للاستخدام',
        "en": 'Ready to use',
        "fr": "Approbation de l'administrateur requise d'abord",
    },
    'ensure_bot_works': {
        "ar": 'تأكد من أن بوتك يعمل',
        "en": 'Make sure your bot works',
        "fr": 'Assurez-vous que votre bot fonctionne',
    },
    'cost': {
        "ar": 'التكلفة',
        "en": 'Cost',
        "fr": 'Coût',
    },
    'points_word': {
        "ar": 'نقاط',
        "en": 'points',
        "fr": 'points',
    },
    'insufficient_points': {
        "ar": 'رصيد نقاطك غير كافٍ',
        "en": 'Insufficient points balance',
        "fr": 'Solde de points insuffisant',
    },
    'current_balance': {
        "ar": 'رصيدك الحالي',
        "en": 'Current balance',
        "fr": 'Solde actuel',
    },
    'get_points_via_referral': {
        "ar": 'احصل على نقاط إضافية عبر رابط الدعوة',
        "en": 'Get extra points via referral link',
        "fr": 'Obtenez des points supplémentaires via le lien de parrainage',
    },
    'max_files_reached': {
        "ar": 'وصلت للحد الأقصى للملفات المسموحة',
        "en": 'Maximum allowed files reached',
        "fr": 'Nombre maximum de fichiers autorisé atteint',
    },
    'your_files': {
        "ar": 'ملفاتك الحالية',
        "en": 'Your current files',
        "fr": 'Vos fichiers actuels',
    },
    'max_allowed': {
        "ar": 'الحد الأقصى المسموح',
        "en": 'Max allowed',
        "fr": 'Maximum autorisé',
    },
    'request_upgrade': {
        "ar": 'اطبق ترقية من الأدمن لرفع المزيد',
        "en": 'Request upgrade from admin for more',
        "fr": "Demandez une mise à niveau à l'administrateur pour en avoir plus",
    },
    'file_too_large': {
        "ar": 'حجم الملف كبير جداً (الحد 20MB)',
        "en": 'File too large (max 20MB)',
        "fr": 'Fichier trop volumineux (20 Mo max)',
    },
    'bot_uploaded': {
        "ar": 'تم رفع البوت',
        "en": 'Bot Uploaded',
        "fr": 'Bot envoyé',
    },
    'will_be_reviewed': {
        "ar": 'يمكنك تشغيله الآن من «بوتاتي»',
        "en": 'It will be reviewed and activated soon.',
        "fr": 'Il sera examiné et activé bientôt.',
    },
    'upload_number': {
        "ar": 'رقم الرفع',
        "en": 'Upload #',
        "fr": 'Envoi n°',
    },
    'site_uploaded': {
        "ar": 'تم رفع الموقع',
        "en": 'Site Uploaded',
        "fr": 'Site envoyé',
    },
    'my_bots_title': {
        "ar": 'بوتاتك',
        "en": 'Your Bots',
        "fr": 'Vos bots',
    },
    'my_sites_title': {
        "ar": 'مواقعك',
        "en": 'Your Sites',
        "fr": 'Vos sites',
    },
    'no_sites': {
        "ar": 'لا توجد مواقع.',
        "en": 'No sites found.',
        "fr": 'Aucun site trouvé.',
    },
    'open_site': {
        "ar": 'فتح الموقع {i}',
        "en": 'Open Site {i}',
        "fr": 'Ouvrir le site {i}',
    },
    'delete_site': {
        "ar": ' حذف الموقع',
        "en": ' Delete Site',
        "fr": ' Supprimer le site',
    },
    'download_site': {
        "ar": ' تحميل الموقع',
        "en": ' Download Site',
        "fr": ' Télécharger le site',
    },
    'confirm_delete_title': {
        "ar": ' تأكيد الحذف',
        "en": ' Confirm Delete',
        "fr": ' Confirmer la suppression',
    },
    'confirm_delete_bot_body': {
        "ar": 'هل أنت متأكد من حذف هذا البوت؟\nلا يمكن التراجع عن هذا الإجراء.',
        "en": 'Are you sure you want to delete this bot?\nThis action cannot be undone.',
        "fr": 'Êtes-vous sûr de vouloir supprimer ce bot ?\nCette action est irréversible.',
    },
    'confirm_delete_site_body': {
        "ar": 'هل أنت متأكد من حذف هذا الموقع؟\nلا يمكن التراجع عن هذا الإجراء.',
        "en": 'Are you sure you want to delete this site?\nThis action cannot be undone.',
        "fr": 'Êtes-vous sûr de vouloir supprimer ce site ?\nCette action est irréversible.',
    },
    'confirm_yes_delete': {
        "ar": ' نعم، احذف',
        "en": ' Yes, delete',
        "fr": ' Oui, supprimer',
    },
    'confirm_no_cancel': {
        "ar": ' إلغاء',
        "en": ' Cancel',
        "fr": ' Annuler',
    },
    'site_deleted': {
        "ar": ' تم حذف الموقع.',
        "en": ' Site deleted.',
        "fr": ' Site supprimé.',
    },
    'site_not_found': {
        "ar": ' الموقع غير موجود.',
        "en": ' Site not found.',
        "fr": ' Site introuvable.',
    },
    'referral_title': {
        "ar": 'رابط الدعوة',
        "en": 'Referral Link',
        "fr": 'Lien de parrainage',
    },
    'share_for_points': {
        "ar": 'شارك الرابط للحصول على {pts} نقطة',
        "en": 'Share the link to get {pts} point(s)',
        "fr": 'Partagez le lien pour obtenir {pts} point(s)',
    },
    'ward_info_text': {
        "ar": 'بوت رفع استضافه EYRX .',
        "en": 'EYRX Hosting Bot.',
        "fr": "Bot d'hébergement EYRX.",
    },
    'points_title': {
        "ar": 'نقاطي',
        "en": 'My Points',
        "fr": 'Mes points',
    },
    'balance': {
        "ar": 'رصيدك',
        "en": 'Balance',
        "fr": 'Solde',
    },
    'referrals': {
        "ar": 'الإحالات',
        "en": 'Referrals',
        "fr": 'Parrainages',
    },
    'upgrade': {
        "ar": 'الترقية',
        "en": 'Upgrade',
        "fr": 'Mise à niveau',
    },
    'admin_panel_title': {
        "ar": 'لوحة تحكم الأدمن',
        "en": 'Admin Control Panel',
        "fr": "Panneau d'administration",
    },
    'choose_action': {
        "ar": 'اختر ما تريد القيام به:',
        "en": 'Choose what you want to do:',
        "fr": 'Choisissez ce que vous voulez faire :',
    },
    'bot_not_found': {
        "ar": 'البوت غير موجود.',
        "en": 'Bot not found.',
        "fr": 'Bot introuvable.',
    },
    'not_allowed': {
        "ar": 'غير مسموح',
        "en": 'Not allowed.',
        "fr": 'Non autorisé.',
    },
    'invalid_request': {
        "ar": 'طلب غير صالح.',
        "en": 'Invalid request.',
        "fr": 'Requête invalide.',
    },
    'already_running': {
        "ar": 'البوت يعمل بالفعل.',
        "en": 'Bot is already running.',
        "fr": "Le bot est déjà en cours d'exécution.",
    },
    'cannot_run_in_state': {
        "ar": 'لا يمكن تشغيل البوت في حالته الحالية.',
        "en": 'Cannot start bot in current state.',
        "fr": "Impossible de démarrer le bot dans l'état actuel.",
    },
    'starting_bot': {
        "ar": 'جاري تشغيل البوت الآن، الرجاء الانتظار...',
        "en": 'Starting the bot now, please wait...',
        "fr": 'Démarrage du bot en cours, veuillez patienter...',
    },
    'may_take_seconds': {
        "ar": '(قد يستغرق بضع ثوانٍ للتأكد أن البوت اشتغل فعلاً ولم يتوقف)',
        "en": '(May take a few seconds to verify the bot started successfully)',
        "fr": '(La vérification du démarrage peut prendre quelques secondes)',
    },
    'start_success': {
        "ar": 'تم تشغيل البوت بنجاح.',
        "en": 'Bot started successfully.',
        "fr": 'Bot démarré avec succès.',
    },
    'start_failed': {
        "ar": 'فشل التشغيل',
        "en": 'Start failed',
        "fr": 'Échec du démarrage',
    },
    'stopping_bot': {
        "ar": 'جاري إيقاف البوت الآن...',
        "en": 'Stopping the bot now...',
        "fr": 'Arrêt du bot en cours...',
    },
    'bot_stopped': {
        "ar": 'تم إيقاف البوت.',
        "en": 'Bot stopped.',
        "fr": 'Bot arrêté.',
    },
    'restarting': {
        "ar": 'جاري إعادة التشغيل...',
        "en": 'Restarting...',
        "fr": 'Redémarrage en cours...',
    },
    'restart_success': {
        "ar": 'تم إعادة التشغيل بنجاح.',
        "en": 'Restart successful.',
        "fr": 'Redémarrage réussi.',
    },
    'restart_failed': {
        "ar": 'فشلت إعادة التشغيل',
        "en": 'Restart failed',
        "fr": 'Échec du redémarrage',
    },
    'bot_not_running': {
        "ar": 'البوت لا يعمل حالياً.',
        "en": 'Bot is not running.',
        "fr": "Le bot n'est pas en cours d'exécution.",
    },
    'deleted': {
        "ar": 'تم الحذف.',
        "en": 'Deleted.',
        "fr": 'Supprimé.',
    },
    'file_sent': {
        "ar": 'تم إرسال الملف.',
        "en": 'File sent.',
        "fr": 'Fichier envoyé.',
    },
    'error_occurred': {
        "ar": 'حدث خطأ',
        "en": 'An error occurred',
        "fr": "Une erreur s'est produite",
    },
    'no_operation': {
        "ar": 'لا يوجد عملية جارية.',
        "en": 'No operation in progress.',
        "fr": 'Aucune opération en cours.',
    },
    'vip_only': {
        "ar": 'هذه الميزة متاحة فقط لأعضاء VIP.',
        "en": 'This feature is available for VIP members only.',
        "fr": 'Cette fonctionnalité est réservée aux membres VIP.',
    },
    'how_it_works_text': {
        "ar": ' بوت EYRX للاستضافة هو نظام متكامل لرفع وتشغيل بوتاتك ومواقعك بسهولة.\n\n◆ رفع بوت: ارفع ملف .py ويتم مراجعته من الإدارة ثم تشغيله مباشرة.\n◆ رفع موقع: ارفع ملف HTML ويحصل على رابط مباشر.\n◆ النقاط: كل رفع بوت يكلف 3 نقاط، وكل رفع موقع يكلف 2 نقاط.\n◆ الدعوات: شارك رابط الدعوة واحصل على نقطة لكل شخص يدخل.\n◆ VIP: ادعو 6 أشخاص واحصل على عضوية VIP مجاناً مع مميزات حصرية!',
        "en": ' EYRX Hosting Bot is a complete system for uploading and running your bots and websites easily.\n\n◆ Upload Bot: Upload a .py file, it gets reviewed by admin then run directly.\n◆ Upload Site: Upload an HTML file and get a direct link.\n◆ Points: Each bot upload costs 3 points, each site upload costs 2 points.\n◆ Referrals: Share your referral link and get 1 point per person.\n◆ VIP: Invite 6 people and get free VIP with exclusive features!',
        "fr": " Le bot d'hébergement EYRX est un système complet pour envoyer et exécuter vos bots et sites web facilement.\n\n◆ Envoyer un bot : envoyez un fichier .py, il est examiné par l'administrateur puis exécuté directement.\n◆ Envoyer un site : envoyez un fichier HTML et obtenez un lien direct.\n◆ Points : chaque envoi de bot coûte 3 points, chaque envoi de site coûte 2 points.\n◆ Parrainages : partagez votre lien de parrainage et obtenez 1 point par personne.\n◆ VIP : invitez 6 personnes et obtenez le VIP gratuit avec des fonctionnalités exclusives !",
    },
    'maintenance_msg': {
        "ar": 'البوت تحت الصيانة حالياً.\nيعود قريباً مع تحديثات جديدة!',
        "en": 'Bot is currently under maintenance.\nIt will be back soon with new updates!',
        "fr": 'Le bot est actuellement en maintenance.\nIl reviendra bientôt avec de nouvelles mises à jour !',
    },
    'admin_back': {
        "ar": 'رجوع للوحة التحكم',
        "en": 'Back to Panel',
        "fr": 'Retour au panneau',
    },
    'back_to_bot': {
        "ar": 'رجوع لهذا البوت',
        "en": 'Back to Bot',
        "fr": 'Retour au bot',
    },
    'home': {
        "ar": 'القائمة الرئيسية',
        "en": 'Main Menu',
        "fr": 'Menu principal',
    },
    'owner_only': {
        "ar": 'للمالك فقط.',
        "en": 'Owner only.',
        "fr": 'Réservé au propriétaire.',
    },
    'send_user_id': {
        "ar": 'أرسل معرف المستخدم:',
        "en": 'Send user ID:',
        "fr": "Envoyez l'ID de l'utilisateur :",
    },
    'send_points_count': {
        "ar": 'أرسل عدد النقاط:',
        "en": 'Send points count:',
        "fr": 'Envoyez le nombre de points :',
    },
    'send_coupon_code': {
        "ar": 'أرسل كود الكوبون:',
        "en": 'Send coupon code:',
        "fr": 'Envoyez le code du coupon :',
    },
    'send_max_uses': {
        "ar": 'أرسل الحد الأقصى للاستخدام:',
        "en": 'Send max uses:',
        "fr": "Envoyez le nombre maximum d'utilisations :",
    },
    'send_new_token': {
        "ar": 'أرسل التوكن الجديد:',
        "en": 'Send new token:',
        "fr": 'Envoyez le nouveau jeton :',
    },
    'send_run_filename': {
        "ar": 'أرسل اسم ملف التشغيل (اسم ملف فقط، بدون مسارات أو رموز):',
        "en": 'Send run filename (filename only, no paths or symbols):',
        "fr": "Envoyez le nom du fichier d'exécution (nom de fichier uniquement, sans chemins ni symboles) :",
    },
    'invalid_id': {
        "ar": 'معرف غير صالح.',
        "en": 'Invalid ID.',
        "fr": 'ID invalide.',
    },
    'invalid_number': {
        "ar": 'يجب إرسال رقم.',
        "en": 'Must send a number.',
        "fr": 'Vous devez envoyer un nombre.',
    },
    'invalid_filename': {
        "ar": 'اسم غير صالح. استخدم حروف/أرقام/نقطة/شرطة فقط، بدون مسافات أو مسارات.',
        "en": 'Invalid name. Use letters/numbers/dot/dash only, no spaces or paths.',
        "fr": 'Nom invalide. Utilisez uniquement lettres/chiffres/point/tiret, sans espaces ni chemins.',
    },
    'points_added': {
        "ar": 'تم إضافة {n} نقطة للمستخدم {uid}',
        "en": 'Added {n} points to user {uid}',
        "fr": "{n} points ajoutés à l'utilisateur {uid}",
    },
    'points_deducted': {
        "ar": 'تم خصم {n} نقطة من المستخدم {uid}',
        "en": 'Deducted {n} points from user {uid}',
        "fr": "{n} points déduits de l'utilisateur {uid}",
    },
    'coupon_created': {
        "ar": 'تم إنشاء الكوبون',
        "en": 'Coupon created',
        "fr": 'Coupon créé',
    },
    'user_banned': {
        "ar": 'تم حظر المستخدم',
        "en": 'User banned',
        "fr": 'Utilisateur banni',
    },
    'user_unbanned': {
        "ar": 'تم فك حظر المستخدم',
        "en": 'User unbanned',
        "fr": 'Utilisateur débanni',
    },
    'broadcast_sent': {
        "ar": 'تم الإرسال لـ {n} مستخدم.',
        "en": 'Sent to {n} users.',
        "fr": 'Envoyé à {n} utilisateurs.',
    },
    'send_broadcast_msg': {
        "ar": 'أرسل الرسالة للإذاعة:',
        "en": 'Send the broadcast message:',
        "fr": 'Envoyez le message de diffusion :',
    },
    'send_media_msg': {
        "ar": 'أرسل صورة أو فيديو (يمكنك إرسال أكثر من واحدة متتالية، أرسل /cancel للإنهاء):',
        "en": 'Send a photo or video (you can send multiple, send /cancel to finish):',
        "fr": 'Envoyez une photo ou une vidéo (vous pouvez en envoyer plusieurs, envoyez /cancel pour terminer) :',
    },
    'media_added': {
        "ar": 'تم إضافة الوسائط. أرسل وسائط أخرى أو /cancel للإنهاء.',
        "en": 'Media added. Send more or /cancel to finish.',
        "fr": "Média ajouté. Envoyez-en d'autres ou /cancel pour terminer.",
    },
    'invalid_media': {
        "ar": 'وسائط غير صالحة.',
        "en": 'Invalid media.',
        "fr": 'Média invalide.',
    },
    'section_media_title': {
        "ar": 'وسائط الأقسام',
        "en": 'Section Media',
        "fr": 'Média de section',
    },
    'section_media_desc': {
        "ar": 'اختر القسم الذي تريد تخصيص صورة/فيديو له عند كل تنقل إليه:',
        "en": 'Choose a section to customize its photo/video:',
        "fr": 'Choisissez une section pour personnaliser sa photo/vidéo :',
    },
    'send_section_media': {
        "ar": 'أرسل صورة أو فيديو ليظهر مع قسم:',
        "en": 'Send a photo or video for the section:',
        "fr": 'Envoyez une photo ou une vidéo pour la section :',
    },
    'media_set_for_section': {
        "ar": 'تم تعيين الوسائط لقسم',
        "en": 'Media set for section',
        "fr": 'Média défini pour la section',
    },
    'all_media_deleted': {
        "ar": 'تم حذف جميع الوسائط بنجاح.',
        "en": 'All media deleted successfully.',
        "fr": 'Tous les médias ont été supprimés avec succès.',
    },
    'vip_granted_msg': {
        "ar": 'لقد حصلت على عضوية VIP بعد دعوة {n} أشخاص!\nاستمتع بالمميزات الحصرية الآن.',
        "en": 'You earned VIP membership after inviting {n} people!\nEnjoy exclusive features now.',
        "fr": 'Vous avez obtenu le statut VIP après avoir invité {n} personnes !\nProfitez des fonctionnalités exclusives dès maintenant.',
    },
    'new_referral_notif': {
        "ar": 'تم تسجيل إحالة جديدة\nحصلت على {pts} نقطة\nإجمالي نقاطك: {total}',
        "en": 'New referral registered\nYou earned {pts} point(s)\nTotal points: {total}',
        "fr": 'Nouveau parrainage enregistré\nVous avez gagné {pts} point(s)\nTotal des points : {total}',
    },
    'add_folder_btn': {
        "ar": ' إضافة مجلد',
        "en": ' Add Folder',
        "fr": ' Ajouter un dossier',
    },
    'delete_user_files_btn': {
        "ar": ' حذف ملفات مستخدم',
        "en": ' Delete User Files',
        "fr": ' Supprimer les fichiers utilisateur',
    },
    'add_folder_title': {
        "ar": ' إضافة مجلد',
        "en": ' Add Folder',
        "fr": ' Ajouter un dossier',
    },
    'add_folder_prompt_user_id': {
        "ar": ' أرسل أيدي المستخدم الذي تريد إنشاء مجلد له:',
        "en": ' Send the ID of the user to create a folder for:',
        "fr": " Envoyez l'ID de l'utilisateur pour lequel créer un dossier :",
    },
    'add_folder_prompt_section': {
        "ar": ' أين تريد إضافة المجلد؟',
        "en": ' Where do you want to add the folder?',
        "fr": ' Où voulez-vous ajouter le dossier ?',
    },
    'add_folder_section_bots': {
        "ar": ' قسم البوتات',
        "en": ' Bots Section',
        "fr": ' Section Bots',
    },
    'add_folder_section_sites': {
        "ar": ' قسم المواقع',
        "en": ' Sites Section',
        "fr": ' Section Sites',
    },
    'add_folder_section_both': {
        "ar": ' كلا القسمين',
        "en": ' Both Sections',
        "fr": ' Les deux sections',
    },
    'add_folder_prompt_size': {
        "ar": ' أرسل الحجم الأقصى للمجلد بالميجابايت (مثال: 100):\nأو أرسل 0 لحجم غير محدود.',
        "en": ' Send the max folder size in MB (e.g. 100):\nOr send 0 for unlimited.',
        "fr": ' Envoyez la taille maximale du dossier en Mo (ex. 100) :\nOu envoyez 0 pour illimité.',
    },
    'add_folder_prompt_name': {
        "ar": ' أرسل اسم المجلد (حروف وأرقام فقط):\nأو أرسل /auto لاستخدام اسم تلقائي.',
        "en": ' Send the folder name (letters and numbers only):\nOr send /auto for an auto-generated name.',
        "fr": ' Envoyez le nom du dossier (lettres et chiffres uniquement) :\nOu envoyez /auto pour un nom généré automatiquement.',
    },
    'add_folder_created': {
        "ar": ' تم إنشاء المجلد بنجاح.\n\n المسار: <code>{path}</code>\n الحجم الأقصى: {size}\n المستخدم: <code>{user_id}</code>',
        "en": ' Folder created successfully.\n\n Path: <code>{path}</code>\n Max size: {size}\n User: <code>{user_id}</code>',
        "fr": ' Dossier créé avec succès.\n\n Chemin : <code>{path}</code>\n Taille max : {size}\n Utilisateur : <code>{user_id}</code>',
    },
    'add_folder_failed': {
        "ar": ' فشل إنشاء المجلد: {reason}',
        "en": ' Failed to create folder: {reason}',
        "fr": ' Échec de la création du dossier : {reason}',
    },
    'add_folder_invalid_id': {
        "ar": ' معرف غير صالح.',
        "en": ' Invalid ID.',
        "fr": ' ID invalide.',
    },
    'add_folder_invalid_size': {
        "ar": ' أرسل رقماً صحيحاً (0 أو أكبر).',
        "en": ' Send a valid number (0 or greater).',
        "fr": ' Envoyez un nombre valide (0 ou plus).',
    },
    'add_folder_invalid_name': {
        "ar": ' اسم غير صالح. استخدم حروف وأرقام و _ فقط.',
        "en": ' Invalid name. Use letters, numbers, and _ only.',
        "fr": ' Nom invalide. Utilisez uniquement lettres, chiffres et _.',
    },
    'delete_user_files_title': {
        "ar": ' حذف ملفات مستخدم',
        "en": ' Delete User Files',
        "fr": ' Supprimer les fichiers utilisateur',
    },
    'delete_user_files_prompt_user_id': {
        "ar": ' أرسل أيدي المستخدم الذي تريد حذف ملفاته:',
        "en": ' Send the ID of the user whose files you want to delete:',
        "fr": " Envoyez l'ID de l'utilisateur dont vous voulez supprimer les fichiers :",
    },
    'delete_user_files_prompt_section': {
        "ar": ' أي قسم تريد حذف ملفاته؟',
        "en": ' Which section do you want to delete files from?',
        "fr": ' De quelle section voulez-vous supprimer des fichiers ?',
    },
    'delete_user_files_confirm_bots': {
        "ar": ' تم حذف <b>{n}</b> ملف بوت للمستخدم <code>{user_id}</code>.',
        "en": ' Deleted <b>{n}</b> bot file(s) for user <code>{user_id}</code>.',
        "fr": " <b>{n}</b> fichier(s) bot supprimé(s) pour l'utilisateur <code>{user_id}</code>.",
    },
    'delete_user_files_confirm_sites': {
        "ar": ' تم حذف <b>{n}</b> ملف موقع للمستخدم <code>{user_id}</code>.',
        "en": ' Deleted <b>{n}</b> site file(s) for user <code>{user_id}</code>.',
        "fr": " <b>{n}</b> fichier(s) site supprimé(s) pour l'utilisateur <code>{user_id}</code>.",
    },
    'delete_user_files_confirm_both': {
        "ar": ' تم الحذف:\n• بوتات: <b>{bots}</b>\n• مواقع: <b>{sites}</b>\nللمستخدم <code>{user_id}</code>.',
        "en": ' Deleted:\n• Bots: <b>{bots}</b>\n• Sites: <b>{sites}</b>\nFor user <code>{user_id}</code>.',
        "fr": " Supprimé :\n• Bots : <b>{bots}</b>\n• Sites : <b>{sites}</b>\nPour l'utilisateur <code>{user_id}</code>.",
    },
    'delete_user_files_none': {
        "ar": ' لا توجد ملفات لهذا المستخدم في القسم المحدد.',
        "en": ' No files found for this user in the selected section.',
        "fr": ' Aucun fichier trouvé pour cet utilisateur dans la section sélectionnée.',
    },
    'send_new_owner_id': {
        "ar": 'أرسل الايدي (OWNER_ID) الجديد (أرقام فقط):',
        "en": 'Send the new OWNER_ID (numbers only):',
        "fr": 'Envoyez le nouvel OWNER_ID (chiffres uniquement) :',
    },
    'owner_id_updated': {
        "ar": ' تم تحديث OWNER_ID داخل كود الملف بنجاح.',
        "en": ' OWNER_ID has been updated inside the file code successfully.',
        "fr": " L'OWNER_ID a été mis à jour dans le code du fichier avec succès.",
    },
    'owner_id_added': {
        "ar": ' لم يتم العثور على متغير OWNER_ID، تمت إضافته تلقائياً.',
        "en": ' OWNER_ID variable not found, it was added automatically.',
        "fr": ' Variable OWNER_ID introuvable, elle a été ajoutée automatiquement.',
    },
    'restart_failed_with_reason': {
        "ar": ' فشل إعادة التشغيل - {reason}',
        "en": ' Restart failed - {reason}',
        "fr": ' Échec du redémarrage - {reason}',
    },
    'invalid_id_msg': {
        "ar": ' الايدي يجب أن يكون أرقام فقط.',
        "en": ' The ID must be numbers only.',
        "fr": " L'ID doit contenir uniquement des chiffres.",
    },
    'bot_word': {
        "ar": 'بوت',
        "en": 'Bot',
        "fr": 'Bot',
    },
    'manage_bot_word': {
        "ar": 'إدارة البوت',
        "en": 'Manage Bot',
        "fr": 'Gérer le bot',
    },
    'main_menu_admin_label': {
        "ar": 'القائمة الرئيسية',
        "en": 'Main Menu',
        "fr": 'Menu principal',
    },
    'adm_stats': {
        "ar": ' إحصائيات',
        "en": ' Stats',
        "fr": ' Statistiques',
    },
    'adm_advanced_stats': {
        "ar": ' إحصائيات متقدمة',
        "en": ' Advanced Stats',
        "fr": ' Statistiques avancées',
    },
    'adm_users': {
        "ar": ' المستخدمون',
        "en": ' Users',
        "fr": ' Utilisateurs',
    },
    'adm_search_user': {
        "ar": ' بحث بالايدي',
        "en": ' Search by ID',
        "fr": ' Rechercher par ID',
    },
    'adm_pending_files': {
        "ar": ' الملفات المعلقة',
        "en": ' Pending Files',
        "fr": ' Fichiers en attente',
    },
    'adm_all_bots': {
        "ar": ' كل البوتات',
        "en": ' All Bots',
        "fr": ' Tous les bots',
    },
    'adm_ward_files': {
        "ar": ' ملفات ورد',
        "en": ' Ward Files',
        "fr": ' Fichiers Ward',
    },
    'adm_folders': {
        "ar": ' إدارة المجلدات',
        "en": ' Folders',
        "fr": ' Dossiers',
    },
    'adm_file_logs': {
        "ar": ' سجل الملفات',
        "en": ' File Logs',
        "fr": ' Journaux de fichiers',
    },
    'adm_terminal': {
        "ar": ' ترمينال',
        "en": ' Terminal',
        "fr": ' Terminal',
    },
    'adm_cpu_usage': {
        "ar": ' استهلاك المعالج',
        "en": ' CPU Usage',
        "fr": ' Utilisation CPU',
    },
    'adm_maintenance': {
        "ar": ' وضع الصيانة',
        "en": ' Maintenance',
        "fr": ' Maintenance',
    },
    'adm_db_backup': {
        "ar": ' نسخ احتياطي',
        "en": ' Backup',
        "fr": ' Sauvegarde',
    },
    'adm_live_monitor': {
        "ar": ' مراقبة مباشرة',
        "en": ' Live Monitor',
        "fr": ' Surveillance en direct',
    },
    'adm_auto_approve': {
        "ar": ' قبول تلقائي',
        "en": ' Auto Approve',
        "fr": ' Approbation automatique',
    },
    'adm_auto_charge': {
        "ar": ' قبول تلقائي 2',
        "en": ' Auto Approve 2',
        "fr": ' Approbation automatique 2',
    },
    'adm_auto_charge_desc': {
        "ar": 'عند التفعيل: كل طلب شحن يظهر فوراً للمستخدم بدون موافقة يدوية',
        "en": 'When enabled: all charge requests appear instantly without manual approval',
        "fr": 'Si activé : toutes les demandes de recharge apparaissent instantanément sans approbation manuelle',
    },
    'charge_waiting_title': {
        "ar": '━━━━━━━━━━━━━━━━━━━━━━\n◆ طلب شحن رصيد ◆\n━━━━━━━━━━━━━━━━━━━━━━',
        "en": '━━━━━━━━━━━━━━━━━━━━━━\n◆ Charge Request ◆\n━━━━━━━━━━━━━━━━━━━━━━',
        "fr": '━━━━━━━━━━━━━━━━━━━━━━\n◆ Demande de recharge ◆\n━━━━━━━━━━━━━━━━━━━━━━',
    },
    'charge_waiting_msg': {
        "ar": 'تم إرسال طلبك للأدمن بنجاح \n\n انتظر الموافقة حتى يظهر لك زر الدفع الفوري.\nسيتم إشعارك فور قبول الطلب.',
        "en": 'Your request has been sent to admin successfully \n\n Wait for approval to see the instant payment button.\nYou will be notified once the request is approved.',
        "fr": "Votre demande a été envoyée à l'administrateur avec succès \n\n Attendez l'approbation pour voir le bouton de paiement instantané.\nVous serez averti une fois la demande approuvée.",
    },
    'charge_approved_notif': {
        "ar": '━━━━━━━━━━━━━━━━━━━━━━\n◆ تم قبول طلب الشحن ◆\n━━━━━━━━━━━━━━━━━━━━━━\n\n تمت الموافقة على طلب شحن رصيدك!\n\nاضغط الزر بالأسفل لاختيار الباقة والدفع فوري ',
        "en": '━━━━━━━━━━━━━━━━━━━━━━\n◆ Charge Request Approved ◆\n━━━━━━━━━━━━━━━━━━━━━━\n\n Your charge request has been approved!\n\nTap the button below to choose a package and pay instantly ',
        "fr": '━━━━━━━━━━━━━━━━━━━━━━\n◆ Demande de recharge approuvée ◆\n━━━━━━━━━━━━━━━━━━━━━━\n\n Votre demande de recharge a été approuvée !\n\nAppuyez sur le bouton ci-dessous pour choisir un forfait et payer instantanément ',
    },
    'charge_rejected_notif': {
        "ar": ' تم رفض طلب شحن الرصيد من قبل الإدارة.',
        "en": ' Your balance charge request has been rejected by admin.',
        "fr": " Votre demande de recharge de solde a été rejetée par l'administrateur.",
    },
    'admin_charge_request': {
        "ar": '━━━━━━━━━━━━━━━━━━━━━━\n◆ طلب شحن رصيد جديد ◆\n━━━━━━━━━━━━━━━━━━━━━━\n\n المستخدم: <code>{user_id}</code>\n اليوزر: @{username}\n الاسم: {first_name}\n\n اضغط «موافقة» لإرسال زر الدفع الفوري\n اضغط «رفض» لرفض الطلب',
        "en": '━━━━━━━━━━━━━━━━━━━━━━\n◆ New Charge Request ◆\n━━━━━━━━━━━━━━━━━━━━━━\n\n User: <code>{user_id}</code>\n Username: @{username}\n Name: {first_name}\n\n Tap «Approve» to send instant payment button\n Tap «Reject» to reject the request',
        "fr": "━━━━━━━━━━━━━━━━━━━━━━\n◆  Nouvelle demande de recharge ◆\n━━━━━━━━━━━━━━━━━━━━━━\n\n Utilisateur : <code>{user_id}</code>\n Nom d'utilisateur : @{username}\n Nom : {first_name}\n\n Appuyez sur « Approuver » pour envoyer le bouton de paiement instantané\n Appuyez sur « Rejeter » pour rejeter la demande",
    },
    'charge_approved_to_user_btn': {
        "ar": ' شحن الرصيد الآن',
        "en": ' Charge Balance Now',
        "fr": ' Recharger le solde maintenant',
    },
    'adm_create_coupon': {
        "ar": ' كوبون جديد',
        "en": ' New Coupon',
        "fr": ' Nouveau coupon',
    },
    'adm_coupons': {
        "ar": ' الكوبونات',
        "en": ' Coupons',
        "fr": ' Coupons',
    },
    'adm_add_points': {
        "ar": ' إضافة نقاط',
        "en": ' Add Points',
        "fr": ' Ajouter des points',
    },
    'adm_deduct_points': {
        "ar": ' خصم نقاط',
        "en": ' Deduct Points',
        "fr": ' Déduire des points',
    },
    'adm_upgrade_user': {
        "ar": ' ترقية مستخدم',
        "en": ' Upgrade User',
        "fr": " Mettre à niveau l'utilisateur",
    },
    'adm_vip': {
        "ar": ' منح VIP',
        "en": ' Grant VIP',
        "fr": ' Accorder le VIP',
    },
    'adm_ban_user': {
        "ar": ' حظر مستخدم',
        "en": ' Ban User',
        "fr": " Bannir l'utilisateur",
    },
    'adm_unban_user': {
        "ar": ' رفع حظر',
        "en": ' Unban User',
        "fr": " Débannir l'utilisateur",
    },
    'adm_mass_ban': {
        "ar": ' حظر جماعي',
        "en": ' Mass Ban',
        "fr": ' Bannissement massif',
    },
    'adm_broadcast': {
        "ar": ' إذاعة',
        "en": ' Broadcast',
        "fr": ' Diffusion',
    },
    'adm_add_media': {
        "ar": ' إضافة وسائط',
        "en": ' Add Media',
        "fr": ' Ajouter un média',
    },
    'adm_section_media': {
        "ar": ' وسائط الأقسام',
        "en": ' Section Media',
        "fr": ' Média de section',
    },
    'adm_delete_all_media': {
        "ar": ' حذف كل الوسائط',
        "en": ' Delete All Media',
        "fr": ' Supprimer tous les médias',
    },
    'adm_manage_admins': {
        "ar": ' إدارة الأدمن',
        "en": ' Manage Admins',
        "fr": ' Gérer les administrateurs',
    },
    'adm_panel_title': {
        "ar": 'لوحة تحكم الأدمن',
        "en": 'Admin Control Panel',
        "fr": "Panneau d'administration",
    },
    'active_bots_word': {
        "ar": 'البوتات النشطة',
        "en": 'Active Bots',
        "fr": 'Bots actifs',
    },
    'not_set': {
        "ar": 'غير محدد',
        "en": 'not set',
        "fr": 'non défini',
    },
    'user_word': {
        "ar": 'المستخدم',
        "en": 'User',
        "fr": 'Utilisateur',
    },
    'charge_balance_btn': {
        "ar": ' شحن الرصيد',
        "en": ' Charge Balance',
        "fr": ' Recharger le solde',
    },
    'charge_balance_title': {
        "ar": '━━━━━━━━━━━━━━━━━━━━━━\n◆ شحن الرصيد ◆\n━━━━━━━━━━━━━━━━━━━━━━',
        "en": '━━━━━━━━━━━━━━━━━━━━━━\n◆ Charge Balance ◆\n━━━━━━━━━━━━━━━━━━━━━━',
        "fr": '━━━━━━━━━━━━━━━━━━━━━━\n◆ Recharger le solde ◆\n━━━━━━━━━━━━━━━━━━━━━━',
    },
    'charge_balance_desc': {
        "ar": 'اختر باقة الشحن المناسبة لك:\n الدفع فوري عبر نجوم تيليغرام',
        "en": 'Choose the package that suits you:\n Instant payment via Telegram Stars',
        "fr": 'Choisissez le forfait qui vous convient :\n Paiement instantané via Telegram Stars',
    },
    'charge_pkg_15': {
        "ar": ' 15 نجمة ← 6 نقاط',
        "en": ' 15 Stars → 6 Points',
        "fr": ' 15 Stars → 6 Points',
    },
    'charge_pkg_25': {
        "ar": ' 25 نجمة ← 12 نقطة',
        "en": ' 25 Stars → 12 Points',
        "fr": ' 25 Stars → 12 Points',
    },
    'charge_pkg_50': {
        "ar": ' 50 نجمة ← 21 نقطة',
        "en": ' 50 Stars → 21 Points',
        "fr": ' 50 Stars → 21 Points',
    },
    'charge_pkg_100': {
        "ar": ' 100 نجمة ← 50 نقطة',
        "en": ' 100 Stars → 50 Points',
        "fr": ' 100 Stars → 50 Points',
    },
    'payment_success_title': {
        "ar": '━━━━━━━━━━━━━━━━━━━━━━\n◆ تمت عملية الدفع بنجاح ◆\n━━━━━━━━━━━━━━━━━━━━━━',
        "en": '━━━━━━━━━━━━━━━━━━━━━━\n◆ Payment Successful ◆\n━━━━━━━━━━━━━━━━━━━━━━',
        "fr": '━━━━━━━━━━━━━━━━━━━━━━\n◆ Paiement réussi ◆\n━━━━━━━━━━━━━━━━━━━━━━',
    },
    'payment_success_msg': {
        "ar": ' تم شحن رصيدك بنجاح!\n\n النقاط المضافة: <b>{pts}</b>\n المبلغ المدفوع: <b>{stars}</b> نجمة\n رصيدك الجديد: <b>{total}</b> نقطة\n\nشكراً لثقتك بـ EYRX Hosting ',
        "en": ' Your balance has been charged successfully!\n\n Points added: <b>{pts}</b>\n Amount paid: <b>{stars}</b> Stars\n New balance: <b>{total}</b> points\n\nThank you for trusting EYRX Hosting ',
        "fr": ' Votre solde a été rechargé avec succès !\n\n Points ajoutés : <b>{pts}</b>\n Montant payé : <b>{stars}</b> Stars\n Nouveau solde : <b>{total}</b> points\n\nMerci de faire confiance à EYRX Hosting ',
    },
    'error_with_back': {
        "ar": ' صار خطأ أثناء عرض الرسالة، جرب /start',
        "en": ' An error occurred while displaying the message, try /start',
        "fr": " Une erreur s'est produite lors de l'affichage du message, essayez /start",
    },
    'error_global_with_back': {
        "ar": ' صار خطأ غير متوقع أثناء تنفيذ العملية.\nجرب تاني أو ارجع للقائمة الرئيسية.',
        "en": ' An unexpected error occurred during the operation.\nTry again or go back to the main menu.',
        "fr": " Une erreur inattendue s'est produite pendant l'opération.\nRéessayez ou retournez au menu principal.",
    },
    'main_menu_btn': {
        "ar": ' القائمة الرئيسية',
        "en": ' Main Menu',
        "fr": ' Menu principal',
    },
    'welcome_title': {
        "ar": '━━━━━━━━━━━━━━━━━━━\n◆ EYRX Hosting ◆\n━━━━━━━━━━━━━━━━━━━',
        "en": '━━━━━━━━━━━━━━━━━━━\n◆ EYRX Hosting ◆\n━━━━━━━━━━━━━━━━━━━',
        "fr": '━━━━━━━━━━━━━━━━━━━\n◆ EYRX Hosting ◆\n━━━━━━━━━━━━━━━━━━━',
    },
    'welcome_body': {
        "ar": "\n\n◆ أهلاً وسهلاً بك في بوت EYRX للاستضافة ◆\n\n━ بوت متكامل لرفع وتشغيل بوتاتك ومواقعك بسهولة تامة ━\n\n◆ ما يمكنك فعله هنا:\n رفع بوتات بايثون وتشغيلها مباشرة\n رفع مواقع HTML والحصول على روابط مباشرة\n كسب نقاط عبر دعوة أصدقائك للبوت\n ترقية حسابك للحصول على مميزات أكثر\n\n◆ نظام النقاط:\n رفع بوت = 3 نقاط\n رفع موقع = 2 نقاط\n كل دعوة = 1 نقطة\n رصيدك الحالي: 0 نقطة\n\n◆ كيف تحصل على نقاط؟\n شارك رابط الدعوة مع أصدقائك\n كل شخص يدخل عبر رابطك = نقطة مجانية\n ادعو 6 أشخاص واحصل على عضوية VIP مجاناً\n\n━━━━━━━━━━━━━━━━━━━\n◆ ننصحك بمراجعة قسم 'كيف يعمل؟' لمعرفة كل التفاصيل ◆\n━━━━━━━━━━━━━━━━━━━",
        "en": "\n\n◆ Welcome to EYRX Hosting Bot ◆\n\n━ A complete system for uploading and running your bots and websites ━\n\n◆ What you can do here:\n Upload Python bots and run them instantly\n Upload HTML websites and get direct links\n Earn points by inviting your friends\n Upgrade your account for more features\n\n◆ Points System:\n Upload a bot = 3 points\n Upload a site = 2 points\n Each referral = 1 point\n Your current balance: 0 points\n\n◆ How to earn points?\n Share your referral link with friends\n Each person who joins via your link = 1 free point\n Invite 6 people and get free VIP membership\n\n━━━━━━━━━━━━━━━━━━━\n◆ We recommend checking 'How It Works?' for all the details ◆\n━━━━━━━━━━━━━━━━━━━",
        "fr": "\n\n◆ Bienvenue sur le bot d'hébergement EYRX ◆\n\n━ Un système complet pour envoyer et exécuter vos bots et sites web ━\n\n◆ Ce que vous pouvez faire ici :\n Envoyer des bots Python et les exécuter instantanément\n Envoyer des sites HTML et obtenir des liens directs\n Gagner des points en invitant vos amis\n Mettre à niveau votre compte pour plus de fonctionnalités\n\n◆ Système de points :\n Envoyer un bot = 3 points\n Envoyer un site = 2 points\n Chaque parrainage = 1 point\n Votre solde actuel : 0 points\n\n◆ Comment gagner des points ?\n Partagez votre lien de parrainage avec vos amis\n Chaque personne qui rejoint via votre lien = 1 point gratuit\n Invitez 6 personnes et obtenez le VIP gratuit\n\n━━━━━━━━━━━━━━━━━━━\n◆ Nous recommandons de consulter « Comment ça marche ? » pour tous les détails ◆\n━━━━━━━━━━━━━━━━━━━",
    },
}




def unicode_italic(text: str) -> str:
    """Unicode italic font for English text."""
    result = ""
    for ch in text:
        if 'A' <= ch <= 'Z':
            result += chr(0x1D434 + ord(ch) - ord('A'))
        elif 'a' <= ch <= 'z':
            result += chr(0x1D44E + ord(ch) - ord('a'))
        else:
            result += ch
    return result


def unicode_script(text: str) -> str:
    """Unicode script/cursive font for English text."""
    result = ""
    for ch in text:
        if 'A' <= ch <= 'Z':
            result += chr(0x1D49C + ord(ch) - ord('A'))
        elif 'a' <= ch <= 'z':
            result += chr(0x1D4B6 + ord(ch) - ord('a'))
        else:
            result += ch
    return result


def unicode_monospace(text: str) -> str:
    result = ""
    for ch in text:
        if 'A' <= ch <= 'Z':
            result += chr(0x1D670 + ord(ch) - ord('A'))
        elif 'a' <= ch <= 'z':
            result += chr(0x1D68A + ord(ch) - ord('a'))
        else:
            result += ch
    return result


def en(text: str) -> str:
    """Apply fancy Unicode bold font to English text. No-op for Arabic."""
    if not text:
        return text
    # If text contains any Arabic char, return as-is
    if any('\u0600' <= c <= '\u06FF' for c in text):
        return text
    return unicode_bold(text)

def t(key: str, lang: Optional[str], **kwargs) -> str:
    entry = TRANSLATIONS.get(key)
    if not entry:
        return key
    lang = lang if lang in ("ar", "en", "fr") else "ar"
    text = entry.get(lang, entry.get("ar", key))
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError):
            pass
    return text


def language_selection_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="العربية", callback_data="set_lang_ar", style="success")],
        [InlineKeyboardButton(text=unicode_bold("English"), callback_data="set_lang_en", style="danger")],
        [InlineKeyboardButton(text=unicode_bold("Français"), callback_data="set_lang_fr", style="primary")],
    ])



# ─────────────────────────────────────────────
# زخرفة الأزرار: لكل زر رمز زخرفي أنيق ومختلف عن البقية (وليس إيموجي)
# ─────────────────────────────────────────────
BUTTON_ORNAMENTS = {
    # تشغيل/إيقاف/إعادة تشغيل
    "start_bot": "",
    "stop_bot": "",
    "restart_bot": "↻",
    # سجل وتوكن
    "log_menu_btn": "≡",
    "change_token": "",
    # ملف التشغيل ورابط البوت
    "change_run_file": "",
    "bot_link": "⁘",
    # الآيدي والمكاتب
    "change_owner_id": "",
    "install_libs": "",
    # الكود والملف
    "view_code": "",
    "edit_file": "",
    "find_replace_edit": "",
    # محتوى ملف وإحصائيات
    "file_contents": "",
    "bot_stats": "",
    # مشاركة وإعدادات متقدمة
    "share_bot": "⇢",
    "advanced_settings": "",
    # حذف وتحميل
    "delete_file": "",
    "download_file": "⇣",
    # سرعة ووقت تشغيل
    "resp_speed": "≋",
    "uptime": "◷",
    # رجوع (مختلفة عن بعضها حسب الوجهة)
    "back": "‹",
    "back_to_bots": "«",
    # القائمة الرئيسية
    "home": "◆",
}


def deco(key: str, label: str) -> str:
    """يضيف رمزاً زخرفياً أنيقاً وفريداً بعد نص الزر (بدون إيموجي)، بحيث لا يتكرر
    نفس الشكل بين زرّين مختلفين."""
    sym = BUTTON_ORNAMENTS.get(key)
    if not sym or not label:
        return label
    return f"{label} {sym}"


# ─────────────────────────────────────────────
# KEYBOARD BUILDERS
# ─────────────────────────────────────────────
def main_menu_keyboard(lang: str = "ar") -> InlineKeyboardMarkup:
    is_latin = lang in ("en", "fr")
    buttons = [
        [InlineKeyboardButton(text=en(t("upload_bot_btn", lang)), callback_data="upload_bot", style="danger")],
        [InlineKeyboardButton(text=en(t("my_bots_btn", lang)), callback_data="my_bots", style="primary")],
        [
            InlineKeyboardButton(text=en(t("upload_site_btn", lang)), callback_data="upload_site", style="danger"),
            InlineKeyboardButton(text=en(t("my_sites_btn", lang)), callback_data="my_sites", style="primary")
        ],
        [
            InlineKeyboardButton(text=en(t("my_points_btn", lang)), callback_data="my_points", style="primary"),
            InlineKeyboardButton(text=en(t("referral_btn", lang)), callback_data="referral", style="success")
        ],
        [InlineKeyboardButton(text=unicode_script("EYRX") if is_latin else "⟡ EYRX", callback_data="ward_info", style="primary")],
        [
            InlineKeyboardButton(text=unicode_italic(t("developer_btn", lang)), url=f"https://t.me/{DEVELOPER_USERNAME}", style="primary"),
            InlineKeyboardButton(text=unicode_italic(t("channel_btn", lang)), url=f"https://t.me/{DEVELOPER_CHANNEL}", style="primary")
        ],
        [InlineKeyboardButton(text=en(t("change_language_btn2", lang)), callback_data="change_language", style="primary")],
        [InlineKeyboardButton(text=en(t("how_it_works_btn", lang)), callback_data="how_it_works", style="success")],
    ]

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_control_panel_keyboard(lang: str = "ar") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=t("adm_stats", lang), callback_data="admin_stats", style="success"),
            InlineKeyboardButton(text=t("adm_advanced_stats", lang), callback_data="admin_advanced_stats", style="primary")
        ],
        [
            InlineKeyboardButton(text=t("adm_users", lang), callback_data="admin_users", style="success"),
            InlineKeyboardButton(text=t("adm_search_user", lang), callback_data="admin_search_user", style="primary")
        ],
        [
            InlineKeyboardButton(text=t("adm_pending_files", lang), callback_data="admin_files", style="success"),
            InlineKeyboardButton(text=t("adm_all_bots", lang), callback_data="admin_bots_list", style="success")
        ],
        [InlineKeyboardButton(text=t("adm_ward_files", lang), callback_data="ward_files_0", style="primary")],
        [
            InlineKeyboardButton(text=t("adm_folders", lang), callback_data="admin_folders", style="primary"),
            InlineKeyboardButton(text=t("adm_file_logs", lang), callback_data="admin_file_logs", style="primary")
        ],
        [
            InlineKeyboardButton(text=t("adm_terminal", lang), callback_data="admin_terminal", style="success"),
            InlineKeyboardButton(text=t("adm_cpu_usage", lang), callback_data="admin_cpu_usage", style="primary")
        ],
        [
            InlineKeyboardButton(text=t("adm_maintenance", lang), callback_data="admin_maintenance", style="danger"),
            InlineKeyboardButton(text=t("adm_db_backup", lang), callback_data="admin_db_backup", style="primary")
        ],
        [
            InlineKeyboardButton(text=t("adm_live_monitor", lang), callback_data="admin_live_monitor", style="success"),
        ],
        [
            InlineKeyboardButton(text=t("adm_auto_approve", lang), callback_data="admin_auto_approve", style="primary"),
            InlineKeyboardButton(text=t("adm_auto_charge", lang), callback_data="admin_auto_charge", style="danger")
        ],
        [
            InlineKeyboardButton(text=t("adm_create_coupon", lang), callback_data="admin_create_coupon", style="success"),
            InlineKeyboardButton(text=t("adm_coupons", lang), callback_data="admin_coupons", style="success")
        ],
        [
            InlineKeyboardButton(text=t("adm_add_points", lang), callback_data="admin_add_points", style="success"),
            InlineKeyboardButton(text=t("adm_deduct_points", lang), callback_data="admin_deduct_points", style="danger")
        ],
        [
            InlineKeyboardButton(text=t("adm_upgrade_user", lang), callback_data="admin_upgrade_user", style="success"),
            InlineKeyboardButton(text=t("adm_vip", lang), callback_data="admin_vip", style="success")
        ],
        [
            InlineKeyboardButton(text=t("adm_ban_user", lang), callback_data="admin_ban_user", style="danger"),
            InlineKeyboardButton(text=t("adm_unban_user", lang), callback_data="admin_unban_user", style="success")
        ],
        [InlineKeyboardButton(text=t("adm_mass_ban", lang), callback_data="admin_mass_ban", style="danger")],
        [InlineKeyboardButton(text=t("adm_broadcast", lang), callback_data="admin_broadcast", style="success")],
        [
            InlineKeyboardButton(text=t("adm_add_media", lang), callback_data="admin_add_media", style="success"),
            InlineKeyboardButton(text=t("adm_section_media", lang), callback_data="admin_section_media", style="primary")
        ],
        [InlineKeyboardButton(text=t("adm_delete_all_media", lang), callback_data="admin_delete_all_media", style="danger")],
        [
            InlineKeyboardButton(text=t("add_folder_btn", lang), callback_data="admin_add_folder", style="success"),
            InlineKeyboardButton(text=t("delete_user_files_btn", lang), callback_data="admin_delete_user_files", style="danger")
        ],
        [InlineKeyboardButton(text=t("adm_manage_admins", lang), callback_data="admin_manage_admins", style="success")],
        [InlineKeyboardButton(text="إدارة الاشتراك الإجباري ⟢", callback_data="admin_force_sub_list", style="primary")],
        [InlineKeyboardButton(text="إدارة الذكاء الاصطناعي (AI) ", callback_data="admin_ai_panel", style="danger")],
        [InlineKeyboardButton(text="ربط IP/دومين المواقع ", callback_data="admin_set_site_ip", style="primary")],
        [
            InlineKeyboardButton(text="سرعة السيرفر ≋", callback_data="admin_panel_speed", style="primary"),
            InlineKeyboardButton(text="وقت التشغيل ◷", callback_data="admin_panel_uptime", style="primary")
        ],
        [InlineKeyboardButton(text=en(t("home", lang)), callback_data="main_menu", style="success")],
    ])



def bot_control_keyboard(bot_id: int, status: str, lang: str = "ar") -> InlineKeyboardMarkup:
    is_en = lang == "en"
    buttons = []

    if status == "running":
        buttons.append([InlineKeyboardButton(text=deco("stop_bot", en(t("stop_bot", lang))), callback_data=f"bot_stop_{bot_id}", style="danger")])
        buttons.append([InlineKeyboardButton(text=deco("restart_bot", en(t("restart_bot", lang))), callback_data=f"bot_restart_{bot_id}", style="primary")])
    else:
        buttons.append([InlineKeyboardButton(text=deco("start_bot", en(t("start_bot", lang))), callback_data=f"bot_run_{bot_id}", style="success")])

    buttons.extend([
        [
            InlineKeyboardButton(text=deco("log_menu_btn", en(t("log_menu_btn", lang))), callback_data=f"bot_log_menu_{bot_id}", style="danger"),
            InlineKeyboardButton(text=deco("change_token", en(t("change_token", lang))), callback_data=f"bot_token_{bot_id}", style="primary")
        ],
        [
            InlineKeyboardButton(text=deco("change_run_file", en(t("change_run_file", lang))), callback_data=f"bot_id_{bot_id}", style="success"),
            InlineKeyboardButton(text=deco("bot_link", en(t("bot_link", lang))), callback_data=f"bot_main_link_{bot_id}", style="success")
        ],
        [
            InlineKeyboardButton(text=deco("change_owner_id", en(t("change_owner_id", lang))), callback_data=f"bot_change_owner2_{bot_id}", style="primary"),
            InlineKeyboardButton(text=deco("install_libs", en(t("install_libs", lang))), callback_data=f"vip_install_libs_{bot_id}_admin", style="primary")
        ],
        [
            InlineKeyboardButton(text=deco("view_code", en(t("view_code", lang))), callback_data=f"vip_view_code_{bot_id}_admin", style="primary"),
            InlineKeyboardButton(text=deco("edit_file", en(t("edit_file", lang))), callback_data=f"vip_edit_file_{bot_id}_admin", style="primary")
        ],
        [
            InlineKeyboardButton(text=deco("file_contents", en(t("file_contents", lang))), callback_data=f"vip_file_contents_{bot_id}_admin", style="primary"),
            InlineKeyboardButton(text=deco("bot_stats", en(t("bot_stats", lang))), callback_data=f"vip_bot_stats_{bot_id}_admin", style="primary")
        ],
        [
            InlineKeyboardButton(text=deco("share_bot", en(t("share_bot", lang))), callback_data=f"vip_share_bot_{bot_id}_admin", style="primary"),
            InlineKeyboardButton(text=deco("advanced_settings", en(t("advanced_settings", lang))), callback_data=f"bot_advanced_{bot_id}", style="primary")
        ],
        [
            InlineKeyboardButton(text=deco("delete_file", en(t("delete_file", lang))), callback_data=f"bot_delete_{bot_id}", style="danger"),
            InlineKeyboardButton(text=deco("download_file", en(t("download_file", lang))), callback_data=f"bot_download_{bot_id}", style="success")
        ],
    ])

    # أزرار السرعة/الوقت تظهر فقط إذا كان البوت شغّالاً فعلياً (قياسها على بوت متوقف غير منطقي)
    if status == "running":
        buttons.append([
            InlineKeyboardButton(text=deco("resp_speed", "سرعة الاستجابة"), callback_data=f"bot_speed_{bot_id}", style="primary"),
            InlineKeyboardButton(text=deco("uptime", "وقت التشغيل"), callback_data=f"bot_uptime_{bot_id}", style="primary")
        ])

    buttons.append([InlineKeyboardButton(text=deco("back_to_bots", en(t("back_to_bots", lang))), callback_data="admin_bots_list", style="danger")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def user_bot_control_keyboard(bot_id: int, status: str, lang: str = "ar") -> InlineKeyboardMarkup:
    is_en = lang == "en"
    buttons = []

    if status == "running":
        buttons.append([InlineKeyboardButton(text=deco("stop_bot", en(t("stop_bot", lang))), callback_data=f"user_bot_stop_{bot_id}", style="danger")])
        buttons.append([InlineKeyboardButton(text=deco("restart_bot", en(t("restart_bot", lang))), callback_data=f"user_bot_restart_{bot_id}", style="primary")])
    else:
        buttons.append([InlineKeyboardButton(text=deco("start_bot", en(t("start_bot", lang))), callback_data=f"user_bot_run_{bot_id}", style="success")])

    buttons.extend([
        [
            InlineKeyboardButton(text=deco("log_menu_btn", en(t("log_menu_btn", lang))), callback_data=f"user_bot_log_menu_{bot_id}", style="success"),
            InlineKeyboardButton(text=deco("change_token", en(t("change_token", lang))), callback_data=f"user_bot_token_{bot_id}", style="primary")
        ],
        [
            InlineKeyboardButton(text=deco("change_run_file", en(t("change_run_file", lang))), callback_data=f"user_bot_id_{bot_id}", style="success"),
            InlineKeyboardButton(text=deco("bot_link", en(t("bot_link", lang))), callback_data=f"user_bot_main_link_{bot_id}", style="success")
        ],
        [
            InlineKeyboardButton(text=deco("change_owner_id", en(t("change_owner_id", lang))), callback_data=f"user_bot_change_owner_{bot_id}", style="primary"),
            InlineKeyboardButton(text=deco("install_libs", en(t("install_libs", lang))), callback_data=f"vip_install_libs_{bot_id}_user", style="primary")
        ],
        [
            InlineKeyboardButton(text=deco("view_code", en(t("view_code", lang))), callback_data=f"vip_view_code_{bot_id}_user", style="primary"),
            InlineKeyboardButton(text=deco("edit_file", en(t("edit_file", lang))), callback_data=f"vip_edit_file_{bot_id}_user", style="primary")
        ],
        [
            InlineKeyboardButton(text=deco("find_replace_edit", en(t("find_replace_edit", lang))), callback_data=f"user_bot_findreplace_{bot_id}", style="primary"),
            InlineKeyboardButton(text=deco("file_contents", en(t("file_contents", lang))), callback_data=f"vip_file_contents_{bot_id}_user", style="primary")
        ],
        [
            InlineKeyboardButton(text=deco("bot_stats", en(t("bot_stats", lang))), callback_data=f"vip_bot_stats_{bot_id}_user", style="primary"),
            InlineKeyboardButton(text=deco("share_bot", en(t("share_bot", lang))), callback_data=f"vip_share_bot_{bot_id}_user", style="primary")
        ],
        [
            InlineKeyboardButton(text=deco("delete_file", en(t("delete_file", lang))), callback_data=f"user_bot_delete_{bot_id}", style="danger"),
            InlineKeyboardButton(text=deco("download_file", en(t("download_file", lang))), callback_data=f"user_bot_download_{bot_id}", style="success")
        ],
    ])

    # أزرار السرعة/الوقت تظهر فقط إذا كان البوت شغّالاً فعلياً (قياسها على بوت متوقف غير منطقي)
    if status == "running":
        buttons.append([
            InlineKeyboardButton(text=deco("resp_speed", "سرعة الاستجابة"), callback_data=f"user_bot_speed_{bot_id}", style="primary"),
            InlineKeyboardButton(text=deco("uptime", "وقت التشغيل"), callback_data=f"user_bot_uptime_{bot_id}", style="primary")
        ])

    buttons.append([InlineKeyboardButton(text=deco("back", en(t("back", lang))), callback_data="my_bots", style="danger")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def back_keyboard(lang: str = "ar") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=deco("back", en(t("back", lang))), callback_data="main_menu", style="danger")],
    ])


def admin_back_keyboard(lang: str = "ar") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{t('admin_back', lang)} »", callback_data="admin_panel", style="danger")],
    ])


def bot_settings_back_keyboard(bot_id: int, admin_view: bool) -> InlineKeyboardMarkup:
    target = f"admin_select_bot_{bot_id}" if admin_view else f"select_bot_{bot_id}"
    fallback = "admin_panel" if admin_view else "main_menu"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="رجوع لهذا البوت ‹", callback_data=target, style="danger")],
        [InlineKeyboardButton(text="القائمة الرئيسية ◆", callback_data=fallback, style="success")],
    ])


def refresh_back_keyboard(refresh_cb: str, back_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="تحديث ↻", callback_data=refresh_cb, style="primary")],
        [InlineKeyboardButton(text="رجوع ‹", callback_data=back_cb, style="danger")],
    ])


def logs_keyboard(refresh_cb: str, back_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="تحديث ↻", callback_data=refresh_cb, style="success")],
        [InlineKeyboardButton(text="رجوع ‹", callback_data=back_cb, style="danger")],
    ])


def terminal_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="تثبيت مكاتب Python ", callback_data="terminal_install_pip", style="success"),
            InlineKeyboardButton(text="تحديث النظام ↻↻", callback_data="terminal_update_system", style="success")
        ],
        [
            InlineKeyboardButton(text="عرض العمليات ", callback_data="terminal_show_processes", style="success"),
            InlineKeyboardButton(text="تنظيف الملفات ", callback_data="terminal_cleanup", style="success")
        ],
        [
            InlineKeyboardButton(text="معلومات النظام ", callback_data="terminal_system_info", style="success"),
            InlineKeyboardButton(text="فحص الاتصال ", callback_data="terminal_check_internet", style="success")
        ],
        [
            InlineKeyboardButton(text="عرض المجلدات ", callback_data="terminal_list_dirs", style="success"),
            InlineKeyboardButton(text="بحث عن ملف ", callback_data="terminal_search_file", style="success")
        ],
        [
            InlineKeyboardButton(text="تثبيت Git ", callback_data="terminal_install_git", style="success"),
            InlineKeyboardButton(text="تثبيت SQLite ", callback_data="terminal_install_sqlite", style="success")
        ],
        [
            InlineKeyboardButton(text="تثبيت FFmpeg ", callback_data="terminal_install_ffmpeg", style="success"),
            InlineKeyboardButton(text="مراقبة الموارد ", callback_data="terminal_monitor", style="success")
        ],
        [InlineKeyboardButton(text="إرسال أمر مخصص ", callback_data="terminal_custom_command", style="success")],
        [InlineKeyboardButton(text="رجوع للوحة التحكم «", callback_data="admin_panel", style="success")],
    ])


def pending_bot_review_keyboard(bot_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="قبول ", callback_data=f"approve_bot_{bot_id}", style="success"),
            InlineKeyboardButton(text="رفض ", callback_data=f"reject_bot_{bot_id}", style="success"),
        ],
        [InlineKeyboardButton(text="رجوع ‹", callback_data="admin_files", style="danger")],
    ])


def pending_site_review_keyboard(site_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="قبول ", callback_data=f"approve_site_{site_id}", style="success"),
            InlineKeyboardButton(text="رفض ", callback_data=f"reject_site_{site_id}", style="success"),
        ],
        [InlineKeyboardButton(text="رجوع ‹", callback_data="admin_files", style="danger")],
    ])


def loading_keyboard(label: str = " جاري التنفيذ...") -> InlineKeyboardMarkup:
    """لوحة مؤقتة تُعرض فوراً أثناء تنفيذ عملية تا وقت (تشغيل/إيقاف بوت)."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data="noop", style="success")],
    ])


def ward_files_keyboard(current_index: int, total_count: int) -> InlineKeyboardMarkup:
    """لوحة تصفح ملفات ورد (بوتات + مواقع) صفحة بصفحة عبر سهم واحد للتنقل."""
    buttons = []
    nav_row = []
    if current_index > 0:
        nav_row.append(InlineKeyboardButton(text="السابق ‹", callback_data=f"ward_files_{current_index - 1}", style="success"))
    if current_index < total_count - 1:
        nav_row.append(InlineKeyboardButton(text="التالي ›", callback_data=f"ward_files_{current_index + 1}", style="success"))
    if nav_row:
        buttons.append(nav_row)
    buttons.append([InlineKeyboardButton(text="رجوع للوحة التحكم «", callback_data="admin_panel", style="danger")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ─────────────────────────────────────────────
# كيبورد الاشتراك الإجباري (ديناميكي: يدعم عدد غير محدود من القنوات/الروابط)
# ─────────────────────────────────────────────
FORCE_SUB_BUTTON_COLOR_CYCLE = ["primary", "danger", "success"]


async def force_sub_keyboard(lang: Optional[str]) -> InlineKeyboardMarkup:
    """يبني لوحة الاشتراك الإجباري ديناميكياً من جدول force_sub_targets، بحيث كل
    زر رابط (قناة/بوت/انستغرام) يتلون بالتناوب على نفس ألوان الأزرار الأساسية
    المستخدمة بباقي البوت (primary → danger → success → تكرار)، وزر التحقق
    النهائي يبقى ثابتاً بلون success دائماً."""
    targets = await get_all_force_sub_targets(active_only=True)
    buttons = []
    for idx, target in enumerate(targets):
        color = FORCE_SUB_BUTTON_COLOR_CYCLE[idx % len(FORCE_SUB_BUTTON_COLOR_CYCLE)]
        buttons.append([InlineKeyboardButton(text=target["display_name"], url=target["url"], style=color)])
    buttons.append([InlineKeyboardButton(text=t("force_sub_verify_btn", lang), callback_data="verify_force_sub", style="success")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)



# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
async def is_admin(user_id: int) -> bool:
    user = await get_user(user_id)
    return bool(user and (user["is_admin"] or user["is_owner"]))


async def is_owner(user_id: int) -> bool:
    user = await get_user(user_id)
    return bool(user and user["is_owner"])


def status_text(status: str) -> str:
    mapping = {
        "pending": " قيد المراجعة",
        "approved": " مقبول",
        "rejected": " مرفوض",
        "running": " يعمل",
        "stopped": " متوقف",
    }
    return mapping.get(status, status)


_SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")


def is_safe_run_file(name: str) -> bool:
    if not name:
        return False
    if not _SAFE_FILENAME_RE.match(name):
        return False
    if ".." in name or name.startswith("/"):
        return False
    return True


def interpreter_for_file(file_path) -> str:
    """يرجع اسم المفسّر المناسب لتشغيل ملف بوت حسب امتداده: node لملفات .js،
    php لملفات .php، وpython3 لباقي الحالات (الافتراضي)."""
    suffix = Path(file_path).suffix.lower()
    if suffix == ".js":
        return shutil.which("node") or "node"
    if suffix == ".php":
        return shutil.which("php") or "php"
    return "python3"


def parse_vip_callback(data: str) -> tuple:
    """يفكّ بيانات كولباك من نوع vip_xxx_{bot_id}_admin أو vip_xxx_{bot_id}_user
    (وأيضاً القديمة بدون لاحقة كتوافق رجعي) ويرجع (bot_id, is_admin_view).
    هذا يمنع اختلاط زر الرجوع بين لوحة الأدمن ولوحة المستخدم مهما كانت شاشة VIP
    المشتركة التي فُتحت منها (تعديل/عرض كود/محتوى ملف/إحصائيات/مشاركة...)."""
    parts = data.rstrip("/").split("_")
    if parts[-1] in ("admin", "user"):
        is_admin_view = parts[-1] == "admin"
        bot_id = int(parts[-2])
    else:
        # توافق رجعي: بيانات قديمة بدون لاحقة — نحدد السياق بصلاحية المستخدم الحالية
        bot_id = int(parts[-1])
        is_admin_view = None  # يُحسم لاحقاً بواسطة is_admin() في نقطة الاستدعاء
    return bot_id, is_admin_view


def vip_back_target(bot_id: int, is_admin_view: bool) -> str:
    """الوجهة الصحيحة لزر الرجوع من أي شاشة VIP مشتركة، بحسب مصدر الفتح الفعلي
    (لوحة الأدمن أو قائمة بوتات المستخدم) دون خلط بينهما."""
    return f"admin_select_bot_{bot_id}" if is_admin_view else f"select_bot_{bot_id}"


def parse_view_code_callback(data: str) -> tuple:
    """يفكّ كولباك شاشة رؤية الكود بصيغة vip_view_code_{bot_id}_{admin|user}_{page}
    (وأيضاً الصيغة القديمة بدون صفحة كتوافق رجعي) ويرجع (bot_id, is_admin_view, page)."""
    parts = data.rstrip("/").split("_")
    if parts[-2] in ("admin", "user") and parts[-1].isdigit():
        # الصيغة الجديدة: ..._{admin|user}_{page}
        page = int(parts[-1])
        is_admin_view = parts[-2] == "admin"
        bot_id = int(parts[-3])
    elif parts[-1] in ("admin", "user"):
        # صيغة بدون رقم صفحة (أول فتح للشاشة)
        page = 0
        is_admin_view = parts[-1] == "admin"
        bot_id = int(parts[-2])
    else:
        # توافق رجعي كامل: بيانات قديمة بدون أي لاحقة
        page = 0
        bot_id = int(parts[-1])
        is_admin_view = None
    return bot_id, is_admin_view, page


def view_code_callback(bot_id: int, is_admin_view: bool, page: int) -> str:
    origin = "admin" if is_admin_view else "user"
    return f"vip_view_code_{bot_id}_{origin}_{page}"


# ─────────────────────────────────────────────
# نظام الترقيات (يدوي بالكامل من الأدمن، بالايدي فقط)
# ─────────────────────────────────────────────
UPGRADE_TIERS = {
    "none": {"label": "بدون ترقية", "max_files": 10, "max_concurrent_bots": 1},
    "standard": {"label": "ترقية عادية", "max_files": 5, "max_concurrent_bots": 2},
    "lifetime": {"label": "ترقية مدى الحياة", "max_files": 5000, "max_concurrent_bots": 5},
}


async def set_user_upgrade(user_id: int, tier: str) -> bool:
    if tier not in UPGRADE_TIERS:
        return False
    cfg = UPGRADE_TIERS[tier]
    async with db_cursor() as conn:
        conn.execute(
            "UPDATE users SET upgrade_tier = ?, max_files = ?, max_concurrent_bots = ? WHERE user_id = ?",
            (tier, cfg["max_files"], cfg["max_concurrent_bots"], user_id),
        )
    return True


async def get_user_limits(user_id: int) -> Dict[str, int]:
    user = await get_user(user_id)
    if not user:
        return UPGRADE_TIERS["none"]
    max_files = user["max_files"] if user["max_files"] is not None else UPGRADE_TIERS["none"]["max_files"]
    max_conc = user["max_concurrent_bots"] if user["max_concurrent_bots"] is not None else UPGRADE_TIERS["none"]["max_concurrent_bots"]
    return {"max_files": max_files, "max_concurrent_bots": max_conc}


async def count_user_files(user_id: int) -> int:
    async with db_cursor() as conn:
        bots_count = conn.execute("SELECT COUNT(*) as c FROM bots WHERE user_id = ?", (user_id,)).fetchone()["c"]
        sites_count = conn.execute("SELECT COUNT(*) as c FROM sites WHERE user_id = ?", (user_id,)).fetchone()["c"]
    return bots_count + sites_count


async def count_user_running_bots(user_id: int) -> int:
    async with db_cursor() as conn:
        rows = conn.execute("SELECT id FROM bots WHERE user_id = ? AND status = 'running'", (user_id,)).fetchall()
    return len(rows)


# ─────────────────────────────────────────────
# إعدادات البوت العامة (bot_config key/value) - لتغيير الايدي (OWNER_ID) وقت التشغيل
# ─────────────────────────────────────────────
async def get_config_value(key: str) -> Optional[str]:
    async with db_cursor() as conn:
        row = conn.execute("SELECT value FROM bot_config WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None


async def set_config_value(key: str, value: str):
    async with db_cursor() as conn:
        conn.execute(
            "INSERT INTO bot_config (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


# ─────────────────────────────────────────────
# وسائط الأقسام (صورة/فيديو مختلف يظهر مع كل شاشة/قسم بالبوت)
# ─────────────────────────────────────────────
SECTION_KEYS = {
    "main_menu": " القائمة الرئيسية",
    "upload_bot": " رفع بوت",
    "bot_uploaded": " رسالة بعد رفع بوت",
    "my_bots": " بوتاتي",
    "upload_site": " رفع موقع",
    "site_uploaded": " رسالة بعد رفع موقع",
    "my_sites": " مواقعي المرفوعة",
    "my_points": " نقاطي",
    "referral": " رابط الدعوة",
    "ward_info": " EYRX",
    "admin_panel": " لوحة الأدمن",
}


async def get_section_media(section: str) -> Optional[sqlite3.Row]:
    async with db_cursor() as conn:
        return conn.execute(
            "SELECT * FROM section_media WHERE section = ?", (section,)
        ).fetchone()


async def set_section_media(section: str, media_type: str, file_id: str, mode: str = "static"):
    async with db_cursor() as conn:
        conn.execute(
            """INSERT INTO section_media (section, media_type, file_id, mode) VALUES (?, ?, ?, ?)
               ON CONFLICT(section) DO UPDATE SET media_type = excluded.media_type, file_id = excluded.file_id, mode = excluded.mode""",
            (section, media_type, file_id, mode),
        )


async def add_section_media_pool_item(section: str, media_type: str, file_id: str) -> int:
    async with db_cursor() as conn:
        cursor = conn.execute(
            "INSERT INTO section_media_pool (section, media_type, file_id) VALUES (?, ?, ?)",
            (section, media_type, file_id),
        )
        return cursor.lastrowid


async def get_random_section_media_from_pool(section: str) -> Optional[sqlite3.Row]:
    async with db_cursor() as conn:
        return conn.execute(
            "SELECT * FROM section_media_pool WHERE section = ? ORDER BY RANDOM() LIMIT 1",
            (section,),
        ).fetchone()


async def count_section_media_pool(section: str) -> int:
    async with db_cursor() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM section_media_pool WHERE section = ?", (section,)
        ).fetchone()
        return row["c"] if row else 0


async def set_section_mode(section: str, mode: str):
    """يضبط وضع القسم (static/random) بدون التأثير على media_type/file_id الحاليين إن وُجدوا."""
    async with db_cursor() as conn:
        existing = conn.execute("SELECT * FROM section_media WHERE section = ?", (section,)).fetchone()
        if existing:
            conn.execute("UPDATE section_media SET mode = ? WHERE section = ?", (mode, section))
        else:
            conn.execute(
                "INSERT INTO section_media (section, media_type, file_id, mode) VALUES (?, NULL, NULL, ?)",
                (section, mode),
            )


SECTIONS_WITH_MEDIA_ENABLED = {"main_menu", "upload_bot", "bot_uploaded", "my_bots", "upload_site", "site_uploaded", "my_sites"}


async def resolve_section_media(section: str) -> Optional[Dict]:
    """يرجع الميديا الفعلية الواجب عرضها لقسم معيّن، حسب وضعه المحفوظ:
    - 'random': يسحب صورة/فيديو عشوائي من مجموعة القسم الخاصة (section_media_pool).
    - 'static' (افتراضي): يرجع الميديا الثابتة المحفوظة بجدول section_media إن وُجدت.
    يرجع None إذا لا توجد ميديا مضبوطة أصلاً لهذا القسم (لا تُعرض أي صورة حينها)."""
    config = await get_section_media(section)
    mode = config["mode"] if config and "mode" in config.keys() else "static"

    if mode == "random":
        item = await get_random_section_media_from_pool(section)
        if item:
            return {"media_type": item["media_type"], "file_id": item["file_id"]}
        return None

    if config and config["file_id"]:
        return {"media_type": config["media_type"], "file_id": config["file_id"]}
    return None


async def send_section_media_followup(chat_id: int, section: str):
    """يرسل صورة/فيديو القسم (إن وُجدت) كرسالة منفصلة بعد رسالة أساسية تحمل مرفقاً آخر
    (مثل ملف بوت/موقع)، لأن رسالة تيليجرام واحدة لا تحمل مستنداً وصورة رئيسيين معاً."""
    if section not in SECTIONS_WITH_MEDIA_ENABLED:
        return
    try:
        media = await resolve_section_media(section)
        if not media:
            return
        if media["media_type"] == "photo":
            await bot.send_photo(chat_id, photo=media["file_id"])
        elif media["media_type"] == "video":
            await bot.send_video(chat_id, video=media["file_id"])
    except Exception as e:
        logger.error(f"send_section_media_followup failed for section {section}: {e}", exc_info=True)


# ─────────────────────────────────────────────
# TOKEN PATCHING داخل كود البوت المرفوع
# ─────────────────────────────────────────────
_TOKEN_PATTERNS = [
    re.compile(r'(?P<prefix>\bBOT_TOKEN\s*=\s*)(["\'])(?:(?!\2).)*\2', re.IGNORECASE),
    re.compile(r'(?P<prefix>\bTOKEN\s*=\s*)(["\'])(?:(?!\2).)*\2', re.IGNORECASE),
    re.compile(r'(?P<prefix>\bAPI_TOKEN\s*=\s*)(["\'])(?:(?!\2).)*\2', re.IGNORECASE),
    re.compile(r'(?P<prefix>Bot\(\s*token\s*=\s*)(["\'])(?:(?!\2).)*\2', re.IGNORECASE),
    re.compile(r'(?P<prefix>\.run\(\s*token\s*=\s*)(["\'])(?:(?!\2).)*\2', re.IGNORECASE),
]


def patch_token_in_source(content: str, new_token: str) -> tuple:
    found = False

    def _sub(match):
        nonlocal found
        found = True
        quote = match.group(2)
        return f"{match.group('prefix')}{quote}{new_token}{quote}"

    new_content = content
    for pattern in _TOKEN_PATTERNS:
        new_content, n = pattern.subn(_sub, new_content, count=1)
        if n:
            break

    return new_content, found


async def apply_token_to_file(file_path: Path, new_token: str):
    if not file_path.exists():
        return
    try:
        async with aiofiles.open(file_path, mode='r', encoding='utf-8', errors='ignore') as f:
            content = await f.read()
    except Exception as e:
        logger.warning(f"Failed to read {file_path} for token patch: {e}")
        return

    try:
        new_content, found = patch_token_in_source(content, new_token)
    except Exception as e:
        logger.warning(f"Failed to patch token pattern for {file_path}: {e}")
        return

    if not found:
        end_tag = "# --- END EYRX FILE METADATA ---"
        insertion = f'BOT_TOKEN = "{new_token}"  # تمت الإضافة تلقائياً من لوحة الاستضافة\n'
        end_index = new_content.find(end_tag)
        if end_index != -1:
            end_of_block = new_content.find('\n', end_index + len(end_tag))
            if end_of_block != -1:
                new_content = new_content[:end_of_block + 1] + insertion + new_content[end_of_block + 1:]
            else:
                new_content = new_content + "\n" + insertion
        else:
            new_content = insertion + new_content

    try:
        async with aiofiles.open(file_path, mode='w', encoding='utf-8') as f:
            await f.write(new_content)
    except Exception as e:
        logger.warning(f"Failed to write token patch to {file_path}: {e}")


_OWNER_ID_PATTERN = re.compile(r'(?P<prefix>\bOWNER_ID\s*=\s*)(?:int\(\s*)?(["\']?)(?:(?!\2).)*\2(\s*\))?', re.IGNORECASE)


def patch_owner_id_in_source(content: str, new_owner_id: str) -> tuple:
    """يبدّل قيمة OWNER_ID داخل كود بوت مرفوع (لزر تغيير الايدي لكل ملف)."""
    found = False

    def _sub(match):
        nonlocal found
        found = True
        return f"OWNER_ID = {new_owner_id}"

    new_content, n = _OWNER_ID_PATTERN.subn(_sub, content, count=1)
    return new_content, found


async def apply_owner_id_to_file(file_path: Path, new_owner_id: str) -> bool:
    """يطبّق تغيير OWNER_ID داخل كود بوت مستخدم مرفوع (زر تغيير الايدي لكل ملف)."""
    if not file_path.exists():
        return False
    try:
        async with aiofiles.open(file_path, mode='r', encoding='utf-8', errors='ignore') as f:
            content = await f.read()
    except Exception as e:
        logger.warning(f"Failed to read {file_path} for owner id patch: {e}")
        return False

    try:
        new_content, found = patch_owner_id_in_source(content, new_owner_id)
    except Exception as e:
        logger.warning(f"Failed to patch owner id pattern for {file_path}: {e}")
        return False

    if not found:
        end_tag = "# --- END EYRX FILE METADATA ---"
        insertion = f'OWNER_ID = {new_owner_id} # تمت الإضافة تلقائياً من لوحة الاستضافة\n'
        end_index = new_content.find(end_tag)
        if end_index != -1:
            end_of_block = new_content.find('\n', end_index + len(end_tag))
            if end_of_block != -1:
                new_content = new_content[:end_of_block + 1] + insertion + new_content[end_of_block + 1:]
            else:
                new_content = new_content + "\n" + insertion
        else:
            new_content = insertion + new_content

    try:
        async with aiofiles.open(file_path, mode='w', encoding='utf-8') as f:
            await f.write(new_content)
        return True
    except Exception as e:
        logger.warning(f"Failed to write owner id patch to {file_path}: {e}")
        return False


# ─────────────────────────────────────────────
# تثبيت تلقائي للمكتبات الناقصة (يُستخدم فقط كجزء من محاولة التشغيل)
# ─────────────────────────────────────────────
_MODULE_NOT_FOUND_RE = re.compile(r"ModuleNotFoundError: No module named ['\"]([A-Za-z0-9_\.\-]+)['\"]")

_IMPORT_TO_PIP = {
    "telebot": "pyTelegramBotAPI",
    "cv2": "opencv-python",
    "PIL": "Pillow",
    "yaml": "PyYAML",
    "bs4": "beautifulsoup4",
    "dotenv": "python-dotenv",
    "Crypto": "pycryptodome",
    "jwt": "PyJWT",
}


def extract_missing_module(log_text: str) -> Optional[str]:
    match = _MODULE_NOT_FOUND_RE.search(log_text)
    if not match:
        return None
    module_name = match.group(1).split(".")[0]
    return _IMPORT_TO_PIP.get(module_name, module_name)


async def verify_telegram_token_live(token: str, timeout_seconds: float = 5.0) -> tuple:
    """فحص فعلي (pre-flight) للتوكن عبر استدعاء getMe الحقيقي على تيليجرام.
    يرجع (صالح: bool, سبب/رسالة: str)."""
    try:
        from aiohttp import ClientSession, ClientTimeout
    except ImportError:
        # aiohttp غير متوفرة لأي سبب؛ لا نمنع التشغيل، نكتفي بفحص الصيغة فقط.
        return True, ""
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        timeout = ClientTimeout(total=timeout_seconds)
        async with ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status == 401:
                    return False, "التوكن غير صحيح أو ملغى (401 Unauthorized من تيليجرام)."
                if resp.status != 200:
                    return False, f"تعذر التحقق من التوكن (رمز استجابة تيليجرام: {resp.status})."
                return True, ""
    except asyncio.TimeoutError:
        # فشل الاتصال بتيليجرام (شبكة بطيئة/مشكلة مؤقتة) لا يعني بالضرورة توكن خاطئ،
        # لذلك نسمح بالمتابعة للتشغيل الفعلي بدل حجب المستخدم بسبب مشكلة شبكة عابرة.
        return True, ""
    except Exception:
        return True, ""


def classify_bot_failure_reason(log_text: str) -> tuple:
    """يحلل سجل اللوغ ليحدد سبب فشل تشغيل البوت بدقة أكبر.
    يرجع (admin_note مختصر, رسالة تفصيلية للمستخدم)."""
    missing_pkg = extract_missing_module(log_text)
    if missing_pkg:
        return (
            f"مكتبة ناقصة ({missing_pkg}). ثبّتها يدوياً من الترمينال ثم أعد التشغيل.",
            f"البوت يحتاج مكتبة '{missing_pkg}' غير مثبّتة. ثبّتها من قسم الترمينال ثم أعد المحاولة.",
        )
    if "Unauthorized" in log_text:
        return (
            "توكن غير صحيح أو ملغى (Unauthorized).",
            "التوكن غير صحيح أو تم إلغاؤه من BotFather. تحقق من التوكن وحاول مرة أخرى.",
        )
    if "Conflict: terminated by other getUpdates" in log_text:
        return (
            "نفس التوكن مستخدم بمكان آخر بنفس الوقت (Conflict).",
            "هذا التوكن مستخدم حالياً ببوت آخر شغّال بمكان آخر بنفس اللحظة. أوقف التشغيل الآخر أو استخدم توكن مختلف.",
        )
    return (
        "الملف توقف فور التشغيل، راجع سجل الأخطاء",
        "الملف توقف فور التشغيل. راجع سجل الأخطاء لمعرفة السبب، أو حالة غير معروفة يلزم مراجعة السجل الكامل لها.",
    )



# ─────────────────────────────────────────────
# تشغيل / إيقاف البوتات
# ─────────────────────────────────────────────
BOT_STARTUP_CHECK_INTERVAL = 1.0
BOT_STARTUP_CHECK_ROUNDS = 5  # إجمالي ~5 ثواني انتظار، مقسّمة لفحوصات متتالية


BOT_EARLY_LIFE_MONITOR_SECONDS = 600  # 10 دقائق
BOT_EARLY_LIFE_MONITOR_INTERVAL = 15  # يفحص كل 15 ثانية


async def monitor_bot_process_early_life(bot_id: int, process, log_file: Path):
    """يراقب العملية بشكل خفيف لأول 10 دقائق من عمرها (وليس فقط عند بدء التشغيل)،
    ويحدّث حالة البوت وسبب التوقف تلقائياً إذا انهارت بعد الفحص الأولي مباشرة."""
    elapsed = 0
    try:
        while elapsed < BOT_EARLY_LIFE_MONITOR_SECONDS:
            await asyncio.sleep(BOT_EARLY_LIFE_MONITOR_INTERVAL)
            elapsed += BOT_EARLY_LIFE_MONITOR_INTERVAL
            if process.returncode is not None:
                RUNNING_BOT_PROCESSES.pop(bot_id, None)
                log_text = ""
                try:
                    log_text = log_file.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    pass
                note, _reason = classify_bot_failure_reason(log_text)
                async with db_cursor() as conn:
                    conn.execute(
                        "UPDATE bots SET status = 'stopped', admin_note = ? WHERE id = ?",
                        (note, bot_id),
                    )
                logger.info(f"Bot {bot_id} detected stopped during early-life monitoring: {note}")
                return
            # تأكد إنه لسا نفس العملية المطلوب مراقبتها (ما تغيّرت بسبب إعادة تشغيل يدوي بالأثناء)
            if RUNNING_BOT_PROCESSES.get(bot_id) is not process:
                return
    except Exception as e:
        logger.error(f"monitor_bot_process_early_life failed for bot {bot_id}: {e}", exc_info=True)


async def run_bot_process(bot_id: int, file_path: str, _retry: int = 0) -> tuple:
    """
    يحاول تشغيل بوت معيّن كعملية منفصلة.
    يرجع (نجاح: bool, سبب الفشل إن وجد: str)
    """
    try:
        if bot_id in RUNNING_BOT_PROCESSES and RUNNING_BOT_PROCESSES[bot_id].returncode is None:
            async with db_cursor() as conn:
                conn.execute("UPDATE bots SET status = 'running' WHERE id = ?", (bot_id,))
            return False, "البوت شغال أصلاً."

        async with db_cursor() as conn:
            bot_data = conn.execute("SELECT bot_token, run_file, user_id FROM bots WHERE id = ?", (bot_id,)).fetchone()

        if not bot_data:
            return False, "البوت غير موجود بقاعدة البيانات."

        # فرض حد التشغيل المتزامن حسب ترقية المستخدم (limits تُحسب فقط لملفات نوع بوت)
        limits = await get_user_limits(bot_data["user_id"])
        running_count = await count_user_running_bots(bot_data["user_id"])
        if running_count >= limits["max_concurrent_bots"]:
            return False, f"وصلت للحد الأقصى للتشغيل المتزامن ({limits['max_concurrent_bots']} بوت بنفس الوقت). أوقف بوت آخر أو اطلب ترقية من الأدمن."

        if not bot_data["bot_token"] or not re.match(r"^\d+:[A-Za-z0-9_-]+$", bot_data["bot_token"]):
            async with db_cursor() as conn:
                conn.execute("UPDATE bots SET status = 'stopped', admin_note = 'توكن غير صالح' WHERE id = ?", (bot_id,))
            return False, "توكن غير صالح. تأكد إنه بصيغة أرقام:حروف مثل 123456789:ABCDEFGhi."

        token_valid, token_error = await verify_telegram_token_live(bot_data["bot_token"])
        if not token_valid:
            async with db_cursor() as conn:
                conn.execute(
                    "UPDATE bots SET status = 'stopped', admin_note = 'التوكن غير صحيح أو ملغى' WHERE id = ?",
                    (bot_id,),
                )
            return False, token_error

        await apply_token_to_file(Path(file_path), bot_data["bot_token"])

        file_to_run = Path(file_path)
        if bot_data["run_file"]:
            if not is_safe_run_file(bot_data["run_file"]):
                async with db_cursor() as conn:
                    conn.execute(
                        "UPDATE bots SET status = 'stopped', admin_note = 'اسم ملف تشغيل غير صالح' WHERE id = ?",
                        (bot_id,),
                    )
                return False, "اسم ملف التشغيل غير صالح."
            candidate = Path(file_path).parent / bot_data["run_file"]
            file_to_run = candidate

        if not file_to_run.exists():
            async with db_cursor() as conn:
                conn.execute(
                    "UPDATE bots SET status = 'stopped', admin_note = 'ملف التشغيل غير موجود' WHERE id = ?",
                    (bot_id,),
                )
            return False, f"ملف التشغيل غير موجود: {file_to_run.name}"

        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / f"bot_{bot_id}.log"

        try:
            with open(log_file, "w") as f:
                process = await asyncio.create_subprocess_exec(
                    interpreter_for_file(file_to_run), str(file_to_run),
                    env={**os.environ, "BOT_TOKEN": bot_data["bot_token"]},
                    stdout=f,
                    stderr=f,
                    start_new_session=True,
                )
        except Exception as e:
            async with db_cursor() as conn:
                conn.execute(
                    "UPDATE bots SET status = 'stopped', admin_note = ? WHERE id = ?",
                    (f"تعذر بدء العملية: {e}"[:200], bot_id),
                )
            return False, f"تعذر بدء العملية: {e}"

        RUNNING_BOT_PROCESSES[bot_id] = process

        for _ in range(BOT_STARTUP_CHECK_ROUNDS):
            await asyncio.sleep(BOT_STARTUP_CHECK_INTERVAL)
            if process.returncode is not None:
                break

        if process.returncode is not None:
            RUNNING_BOT_PROCESSES.pop(bot_id, None)

            log_text = ""
            try:
                log_text = log_file.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                pass

            note, reason = classify_bot_failure_reason(log_text)
            async with db_cursor() as conn:
                conn.execute(
                    "UPDATE bots SET status = 'stopped', admin_note = ? WHERE id = ?",
                    (note, bot_id),
                )
            return False, reason

        async with db_cursor() as conn:
            conn.execute("UPDATE bots SET status = 'running', admin_note = '' WHERE id = ?", (bot_id,))
        logger.info(f"Bot {bot_id} started: {file_path}")
        asyncio.create_task(monitor_bot_process_early_life(bot_id, process, log_file))
        return True, ""
    except Exception as e:
        logger.error(f"Failed to start bot {bot_id}: {e}", exc_info=True)
        try:
            async with db_cursor() as conn:
                conn.execute("UPDATE bots SET status = 'stopped', admin_note = ? WHERE id = ?", (str(e)[:200], bot_id))
        except Exception:
            pass
        RUNNING_BOT_PROCESSES.pop(bot_id, None)
        return False, str(e)


async def stop_bot_process(bot_id: int):
    try:
        if bot_id in RUNNING_BOT_PROCESSES:
            process = RUNNING_BOT_PROCESSES[bot_id]
            if process.returncode is None:
                try:
                    process.terminate()
                    await asyncio.wait_for(process.wait(), timeout=10)
                    logger.info(f"Bot {bot_id} terminated.")
                except asyncio.TimeoutError:
                    try:
                        process.kill()
                        await process.wait()
                    except Exception as e:
                        logger.error(f"Failed to kill bot {bot_id}: {e}")
                except Exception as e:
                    logger.error(f"Failed to terminate bot {bot_id}: {e}")
                finally:
                    RUNNING_BOT_PROCESSES.pop(bot_id, None)
            else:
                RUNNING_BOT_PROCESSES.pop(bot_id, None)

        async with db_cursor() as conn:
            conn.execute("UPDATE bots SET status = 'stopped' WHERE id = ?", (bot_id,))
    except Exception as e:
        logger.error(f"stop_bot_process error for bot {bot_id}: {e}", exc_info=True)
        RUNNING_BOT_PROCESSES.pop(bot_id, None)


async def restart_bot_if_running(bot_id: int, file_path: str) -> Optional[tuple]:
    try:
        was_running = bot_id in RUNNING_BOT_PROCESSES and RUNNING_BOT_PROCESSES[bot_id].returncode is None
        if not was_running:
            return None
        await stop_bot_process(bot_id)
        return await run_bot_process(bot_id, file_path)
    except Exception as e:
        logger.error(f"restart_bot_if_running error for bot {bot_id}: {e}", exc_info=True)
        return False, str(e)


async def try_run_candidate_code(bot_id: int, bot_data, candidate_code: str) -> tuple:
    """يختبر كوداً مرشّحاً (من الذكاء الاصطناعي) بتشغيل حقيقي فعلي ومعزول تماماً عن
    الملف الحقيقي، دون أي أثر دائم على حالة البوت الحقيقية مهما كانت نتيجة التجربة:

    1) يوقف مؤقتاً العملية الحقيقية إن كانت شغّالة (لتفادي تعارض Conflict على نفس
       توكن تيليجرام لو شغّلنا نسختين بنفس الوقت).
    2) يكتب الكود المرشّح بملف مؤقت منفصل بنفس مجلد البوت (حتى تعمل المسارات
       النسبية إن وُجدت)، ويطبّق عليه نفس التوكن الحقيقي.
    3) يشغّله كعملية فعلية ويراقبه لنفس مدة فحص الإقلاع المعتادة (BOT_STARTUP_CHECK_ROUNDS).
    4) يوقف عملية التجربة فوراً بعد الفحص (نجحت أو فشلت) ويعيد العملية الحقيقية
       الأصلية لحالتها كما كانت قبل التجربة تماماً (شغّالة إن كانت شغّالة، متوقفة
       إن كانت متوقفة) — هذا يضمن ألا تتأثر خدمة المستخدم الحالية أثناء التجربة.

    يرجع (نجح: bool, نص_اللوغ: str)."""
    target_file = resolve_bot_target_file(bot_data)
    trial_file = target_file.parent / f".ai_trial_{bot_id}_{uuid.uuid4().hex[:8]}.py"
    trial_log = Path("logs") / f"ai_trial_{bot_id}.log"
    trial_log.parent.mkdir(exist_ok=True)

    was_running = bot_id in RUNNING_BOT_PROCESSES and RUNNING_BOT_PROCESSES[bot_id].returncode is None
    process = None
    try:
        if was_running:
            await stop_bot_process(bot_id)

        async with aiofiles.open(trial_file, mode='w', encoding='utf-8') as f:
            await f.write(candidate_code)
        await apply_token_to_file(trial_file, bot_data["bot_token"])

        try:
            with open(trial_log, "w") as f:
                process = await asyncio.create_subprocess_exec(
                    "python3", str(trial_file),
                    env={**os.environ, "BOT_TOKEN": bot_data["bot_token"]},
                    stdout=f,
                    stderr=f,
                    start_new_session=True,
                )
        except Exception as e:
            return False, f"تعذر بدء عملية التجربة: {e}"

        for _ in range(BOT_STARTUP_CHECK_ROUNDS):
            await asyncio.sleep(BOT_STARTUP_CHECK_INTERVAL)
            if process.returncode is not None:
                break

        crashed = process.returncode is not None
        log_text = ""
        try:
            log_text = trial_log.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            pass

        return (not crashed), log_text

    except Exception as e:
        logger.error(f"try_run_candidate_code: خطأ غير متوقع لبوت {bot_id}: {e}", exc_info=True)
        return False, f"خطأ غير متوقع أثناء التجربة: {e}"

    finally:
        # إيقاف عملية التجربة دوماً (نجحت أو فشلت) — لا نترك عملية تجريبية شغّالة بالخلفية
        if process is not None and process.returncode is None:
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=10)
            except Exception:
                try:
                    process.kill()
                    await process.wait()
                except Exception:
                    pass
        try:
            trial_file.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            trial_log.unlink(missing_ok=True)
        except Exception:
            pass
        # إعادة العملية الحقيقية لحالتها كما كانت قبل التجربة بالضبط
        if was_running:
            try:
                await run_bot_process(bot_id, bot_data["file_path"])
            except Exception as e:
                logger.error(f"try_run_candidate_code: فشل استرجاع تشغيل البوت الحقيقي {bot_id} بعد التجربة: {e}", exc_info=True)


def get_cpu_usage() -> float:
    try:
        return psutil.cpu_percent(interval=1)
    except Exception:
        return 0.0


def get_ram_usage() -> Dict[str, float]:
    try:
        ram = None
        return {
            "total": round(ram.total / (1024**3), 2),
            "used": round(ram.used / (1024**3), 2),
            "percent": ram.percent
        }
    except Exception:
        return {"total": 0, "used": 0, "percent": 0}


def get_disk_usage() -> Dict[str, float]:
    try:
        disk = psutil.disk_usage('/')
        return {
            "total": round(disk.total / (1024**3), 2),
            "used": round(disk.used / (1024**3), 2),
            "percent": disk.percent
        }
    except Exception:
        return {"total": 0, "used": 0, "percent": 0}


async def notify_admin_upload(user_id: int, file_name: str, file_type: str, upload_type: str, file_path: str = None,
                                entity_id: int = None, entity_kind: str = None):
    """
    إشعار الأدمن عند رفع ملف جديد.
    يبقى بنفس الشكل الحالي بالضبط: إرسال الملف (document) + كابشن فيه تفاصيل الرفع
    + أزرار قبول/رفض. عند الضغط "قبول" تُعدَّل هذه نفس الرسالة (بالكابشن) لتضيف
    تأكيد " تم قبول الملف" فوق نفس التفاصيل، بدل استبدال الرسالة بالكامل،
    لأن هذا كان نوع رسالة وسائط (document) وليس نص.
    """
    try:
        user = await get_user(user_id)
        username = user["username"] if user and user["username"] else "لا يوجد"
        first_name = user["first_name"] if user and user["first_name"] else "لا يوجد"

        text = (
            f" ملف جديد تم رفعه\n\n"
            f" المستخدم: {first_name}\n"
            f" المعرف: <code>{user_id}</code>\n"
            f" اليوزر: @{username}\n"
            f" الملف: <code>{file_name}</code>\n"
            f" النوع: {file_type.upper()}\n"
            f" نوع الرفع: {upload_type}"
        )

        review_kb = None
        if entity_id is not None and entity_kind == "bot":
            review_kb = pending_bot_review_keyboard(entity_id)
        elif entity_id is not None and entity_kind == "site":
            review_kb = pending_site_review_keyboard(entity_id)

        async def send_to(chat_id):
            try:
                if file_path and os.path.exists(file_path):
                    await bot.send_document(chat_id, document=InputFile(file_path), caption=text, reply_markup=review_kb)
                else:
                    await bot.send_message(chat_id, text, reply_markup=review_kb)
            except Exception as e:
                logger.error(f"Failed to notify admin {chat_id}: {e}")

        if OWNER_ID:
            await send_to(OWNER_ID)

        for admin_id in ADMIN_IDS:
            await send_to(admin_id)
    except Exception as e:
        logger.error(f"notify_admin_upload failed: {e}", exc_info=True)


async def notify_admin_new_user_once(user_id: int, username: Optional[str], first_name: Optional[str]):
    try:
        user = await get_user(user_id)
        if user and user["notified_admin"]:
            return

        admin_msg = (
            f" مستخدم جديد دخل البوت:\n"
            f" الايدي: <code>{user_id}</code>\n"
            f" اليوزر: @{username or 'لا يوجد'}\n"
            f" الاسم: {first_name or 'لا يوجد'}"
        )
        try:
            await bot.send_message(OWNER_ID, admin_msg)
        except Exception as e:
            logger.error(f"Failed to notify owner about new user {user_id}: {e}")

        await mark_admin_notified(user_id)
    except Exception as e:
        logger.error(f"notify_admin_new_user_once failed: {e}", exc_info=True)


def generate_pixel_encoding_block(user_id: int, file_id: int, file_type: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    unique_hash = secrets.token_hex(8)
    is_js = file_type == "javascript"
    c = "//" if is_js else "#"
    block = f"""
{c} --- START EYRX FILE METADATA ---
{c} User ID: {user_id}
{c} File ID: {file_id}
{c} File Type: {file_type}
{c} Upload Timestamp: {timestamp}
{c} Unique Hash: {unique_hash}
{c} --- END EYRX FILE METADATA ---

"""
    return block


async def prepend_metadata_to_file(file_path: Path, metadata_block: str):
    async with aiofiles.open(file_path, mode='r+') as f:
        content = await f.read()
        await f.seek(0)
        await f.write(metadata_block + content)


async def remove_metadata_from_file(file_path: Path) -> str:
    async with aiofiles.open(file_path, mode='r') as f:
        content = await f.read()

    for c in ("#", "//"):
        start_tag = f"{c} --- START EYRX FILE METADATA ---"
        end_tag = f"{c} --- END EYRX FILE METADATA ---"

        start_index = content.find(start_tag)
        end_index = content.find(end_tag)

        if start_index != -1 and end_index != -1:
            end_of_block = content.find('\n', end_index + len(end_tag))
            if end_of_block != -1:
                return content[end_of_block + 1:]
            else:
                return content[:start_index]
    return content


def generate_upload_explanation(upload_type: str, entity_id: int, file_type: str = "python") -> str:
    if upload_type == "بوت":
        type_line = {
            "python": "رفعت ملف بايثون (.py)",
            "php": "رفعت ملف PHP (.php)",
            "javascript": "رفعت ملف JavaScript (.js) — يتم تشغيله تلقائياً عبر Node.js (node)",
        }.get(file_type, "رفعت ملف بوت")
        return (
            " <b>شو صار فعلياً؟</b>\n"
            f"{type_line} وتم حفظه بسجل خاص فيك برقم "
            f"<b>#{entity_id}</b>، وجاهز للاستخدام.\n\n"
            " <b>الأزرار يلي رح تشوفها بعد القبول (من 'بوتاتي'):</b>\n"
            " / تشغيل أو إيقاف البوت\n"
            " سجل الأخطاء (آخر مخرجات البوت)\n"
            " تغيير التوكن (يتحدث بالكود وبالتشغيل تلقائياً)\n"
            " تغيير ملف التشغيل (لو مشروعك متعدد الملفات)\n"
            " تحميل / حذف / نقل للاستضافة\n\n"
            " الاستضافة صارت تدعم بوتات بايثون (.py)، PHP (.php)، وأيضاً JavaScript (.js) مع تشغيل تلقائي عبر Node.js."
        )
    else:
        return (
            " <b>شو صار فعلياً؟</b>\n"
            "رفعت ملف HTML وتم حفظه بسجل خاص فيك برقم "
            f"<b>#{entity_id}</b>، وجاهز للاستخدام.\n\n"
            " بعد القبول رح يظهر رابط موقعك من قسم 'مواقعي المرفوعه' مباشرة."
        )


async def get_file_preview(file_path: str, lines: int = 45, skip_metadata: bool = True) -> str:
    try:
        if not os.path.exists(file_path):
            return "الملف غير موجود."

        async with aiofiles.open(file_path, mode='r', encoding='utf-8', errors='ignore') as f:
            content = await f.read()

        if skip_metadata:
            end_index = -1
            end_tag = ""
            for c in ("#", "//"):
                candidate_tag = f"{c} --- END EYRX FILE METADATA ---"
                idx = content.find(candidate_tag)
                if idx != -1:
                    end_index = idx
                    end_tag = candidate_tag
                    break
            if end_index != -1:
                end_of_block = content.find('\n', end_index + len(end_tag))
                if end_of_block != -1:
                    content = content[end_of_block + 1:]
            content = content.lstrip('\n')

        preview_lines = content.splitlines()[:lines]
        preview = "\n".join(preview_lines)

        return f"<pre>{sanitize_html_for_telegram(preview, max_len=3500)}</pre>"
    except Exception as e:
        return f"خطأ في قراءة الملف: {e}"


async def get_file_preview_page(file_path: str, page: int = 0, lines_per_page: int = 80, skip_metadata: bool = True) -> dict:
    """مثل get_file_preview لكن بدعم تصفح صفحات (لرؤية باقي الكود عبر زر التالي/السابق).
    يرجع dict فيها: preview (نص جاهز للعرض), page, total_pages, has_next, has_prev."""
    try:
        if not os.path.exists(file_path):
            return {"preview": "الملف غير موجود.", "page": 0, "total_pages": 1, "has_next": False, "has_prev": False}

        async with aiofiles.open(file_path, mode='r', encoding='utf-8', errors='ignore') as f:
            content = await f.read()

        if skip_metadata:
            end_index = -1
            end_tag = ""
            for c in ("#", "//"):
                candidate_tag = f"{c} --- END EYRX FILE METADATA ---"
                idx = content.find(candidate_tag)
                if idx != -1:
                    end_index = idx
                    end_tag = candidate_tag
                    break
            if end_index != -1:
                end_of_block = content.find('\n', end_index + len(end_tag))
                if end_of_block != -1:
                    content = content[end_of_block + 1:]
            content = content.lstrip('\n')

        all_lines = content.splitlines()
        total_pages = max(1, (len(all_lines) + lines_per_page - 1) // lines_per_page)
        page = max(0, min(page, total_pages - 1))
        start = page * lines_per_page
        end = start + lines_per_page
        preview_lines = all_lines[start:end]
        preview = "\n".join(preview_lines)

        return {
            "preview": f"<pre>{sanitize_html_for_telegram(preview, max_len=3500)}</pre>",
            "page": page,
            "total_pages": total_pages,
            "has_next": page < total_pages - 1,
            "has_prev": page > 0,
        }
    except Exception as e:
        return {"preview": f"خطأ في قراءة الملف: {e}", "page": 0, "total_pages": 1, "has_next": False, "has_prev": False}


async def get_bot_log_content(bot_id: int, max_chars: int = 3500) -> str:
    log_file = Path(f"logs/bot_{bot_id}.log")
    if not log_file.exists():
        return "لا توجد سجلات لهذا البوت بعد."
    try:
        async with aiofiles.open(log_file, mode='r', encoding='utf-8', errors='ignore') as f:
            content = await f.read()
        if not content.strip():
            return "السجل فارغ حتى الآن (لم يطبع البوت أي شيء)."
        if len(content) > max_chars:
            content = "...\n" + content[-max_chars:]
        return sanitize_html_for_telegram(content, max_len=max_chars + 50)
    except Exception as e:
        return f"تعذر قراءة السجل: {e}"


async def safe_execute_terminal(command: str, timeout: int = 60) -> tuple:
    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True
        )

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return False, "", f"انتهت مهلة التنفيذ ({timeout} ثانية)"

        output = stdout.decode(errors='ignore').strip()
        error_output = stderr.decode(errors='ignore').strip()

        success = process.returncode == 0
        return success, output, error_output

    except Exception as e:
        return False, "", str(e)



# ─────────────────────────────────────────────
# MESSAGE SENDING
# ─────────────────────────────────────────────
TELEGRAM_CAPTION_SAFE_LIMIT = 1000  # الحد الفعلي 1024، نترك هامش أمان


async def delete_and_send(chat_id: int, user_id: int, text: str, reply_markup=None,
                           old_message_id=None, media=None, section=None):
    """Always delete old message and send a new one. Returns the new message_id (or None on failure).

    ملاحظة: الصور/الفيديو تظهر فقط بالأقسام المحددة صراحة بـ SECTIONS_WITH_MEDIA_ENABLED،
    وبس إذا كان الأدمن ضبط ميديا فعلياً لهذا القسم (ثابتة أو عشوائية من مجموعته الخاصة).
    أي قسم آخر يبقى نصياً فقط بدون أي صورة، حفاظاً على تجربة هادئة بدون ضوضاء بصرية.

    حل جذري لمشكلة كانت تُسقِط الصورة بصمت: caption بتيليجرام محدود بـ1024 حرف، وبعض
    الأقسام (مثل my_sites أو my_bots) نصها يكبر حسب عدد ملفات المستخدم. لذلك إذا كان
    النص أطول من الحد الآمن، تُرسَل الصورة كرسالة مستقلة بدون caption أولاً، ثم يُرسَل
    النص الكامل برسالة نصية عادية بعدها (بدل محاولة دمجهما بنجاح غير مضمون)."""
    try:
        if old_message_id:
            try:
                await bot.delete_message(chat_id, old_message_id)
            except Exception:
                pass
    except Exception:
        pass

    if media is None and section and section in SECTIONS_WITH_MEDIA_ENABLED:
        try:
            media = await resolve_section_media(section)
        except Exception:
            media = None

    new_message_id = None
    text_too_long_for_caption = len(text) > TELEGRAM_CAPTION_SAFE_LIMIT

    if media and not text_too_long_for_caption:
        try:
            if media["media_type"] == "photo":
                sent = await bot.send_photo(chat_id, photo=media["file_id"], caption=text, reply_markup=reply_markup)
                return sent.message_id if sent else None
            elif media["media_type"] == "video":
                sent = await bot.send_video(chat_id, video=media["file_id"], caption=text, reply_markup=reply_markup)
                return sent.message_id if sent else None
            elif media["media_type"] == "document":
                sent = await bot.send_document(chat_id, document=media["file_id"], caption=text, reply_markup=reply_markup)
                return sent.message_id if sent else None
        except Exception:
            pass
    elif media and text_too_long_for_caption:
        # النص طويل جداً على caption؛ نرسل الصورة كرسالة مستقلة بدون caption أولاً،
        # ثم نرسل النص الكامل والأزرار برسالة نصية منفصلة بعدها.
        try:
            if media["media_type"] == "photo":
                await bot.send_photo(chat_id, photo=media["file_id"])
            elif media["media_type"] == "video":
                await bot.send_video(chat_id, video=media["file_id"])
            elif media["media_type"] == "document":
                await bot.send_document(chat_id, document=media["file_id"])
        except Exception as e:
            logger.warning(f"delete_and_send: failed to send standalone media for section={section}: {e}")

    try:
        sent = await bot.send_message(chat_id, text=text, reply_markup=reply_markup)
        new_message_id = sent.message_id if sent else None
    except Exception as e:
        logger.error(f"delete_and_send failed for chat {chat_id}: {e}", exc_info=True)
        try:
            fallback = await bot.send_message(
                chat_id,
                " صار خطأ أثناء عرض الرسالة، جرب /start",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="القائمة الرئيسية ◆", callback_data="main_menu", style="danger")],
                ])
            )
            new_message_id = fallback.message_id if fallback else None
        except Exception:
            pass
    return new_message_id


async def edit_or_send_message(chat_id: int, user_id: int, text: str, reply_markup=None,
                                 message_id=None, media=None, force_new=False, section=None):
    """Legacy wrapper - now always deletes and sends new. Returns the new message_id."""
    return await delete_and_send(chat_id, user_id, text, reply_markup, old_message_id=message_id, media=media, section=section)


async def send_main_menu(chat_id: int, user_id: int, message_id: Optional[int] = None):
    try:
        user = await get_user(user_id)
        if not user:
            user = await get_or_create_user(user_id)

        lang = await get_user_language(user_id) or "ar"
        limits = await get_user_limits(user_id)
        tier_label = UPGRADE_TIERS.get(user["upgrade_tier"] or "none", UPGRADE_TIERS["none"])["label"]

        welcome_text = (
            f"{t('main_menu_title', lang)}\n\n"
            f" {t('points_label', lang)}: <b>{user['points']}</b> {t('points_word', lang)}\n"
            f" {t('upgrade_status', lang)}: <b>{tier_label}</b>\n"
            f" {t('max_files', lang)}: <b>{limits['max_files']}</b> | {t('concurrent_run', lang)}: <b>{limits['max_concurrent_bots']}</b>\n\n"
            f" {t('points_system', lang)}:\n"
            f" {t('per_bot_upload', lang, pts=POINTS_PER_BOT)}\n"
            f" {t('per_site_upload', lang, pts=POINTS_PER_SITE)}\n"
            f" {t('per_referral', lang, pts=POINTS_PER_REFERRAL)}\n\n"
            f" {t('choose_below', lang)}"
        )

        keyboard = main_menu_keyboard(lang)

        await edit_or_send_message(chat_id, user_id, welcome_text, keyboard, message_id, force_new=(message_id is None), section="main_menu")
    except Exception as e:
        logger.error(f"send_main_menu failed for user {user_id}: {e}", exc_info=True)
        try:
            await bot.send_message(
                chat_id,
                " صار خطأ، جرب /start مرة ثانية.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="القائمة الرئيسية ◆", callback_data="main_menu", style="danger")],
                ])
            )
        except Exception:
            pass



# ─────────────────────────────────────────────
# البوابة الإجبارية: اختيار اللغة ثم الاشتراك الإجباري
# ─────────────────────────────────────────────
# نفّذنا هذا كـ Middleware بدل تعديل كل هاندلر قديم على حدة، حتى لا نلمس
# أي منطق موجود أصلاً بالبوت. الـ Middleware يفحص outer قبل توجيه أي
# تحديث (رسالة أو ضغطة زر) إلى الهاندلرز الأصلية:
#   1) هل عند المستخدم لغة محفوظة؟ إذا لا، نعرض شاشة اختيار اللغة ونوقف
#      التحديث هون (ما ينوصل لأي هاندلر تاني).
#   2) هل المستخدم مشترك بالقناة؟ إذا لا، نعرض شاشة الاشتراك الإجباري
#      ونوقف التحديث هون.
# الأزرار المسؤولة عن اختيار اللغة والتحقق من الاشتراك نفسها (set_lang_*,
# verify_force_sub) مستثناة من هذا الفحص حتى تقدر تشتغل بحرية.
from aiogram import types as _aiogram_types
from aiogram.dispatcher.middlewares import BaseMiddleware


_GATE_EXEMPT_CALLBACKS = {"set_lang_ar", "set_lang_en", "set_lang_fr", "verify_force_sub", "admin_maintenance"}


class DuplicateUpdateGuardMiddleware(BaseMiddleware):
    """يمنع معالجة نفس التحديث (ضغطة زر أو رسالة) مرتين بفترة قصيرة، بغض النظر
    عن السبب الجذري (عملية بايثون مكررة شغالة بالخلفية، إعادة تشغيل polling
    الداخلية عند صار استثناء، أو أي تكرار آخر من طرف تيليجرام). يعتمد على
    معرّف فريد ثابت لكل تحديث (callback.id لضغطات الأزرار، أو (chat_id, message_id)
    لرسائل الأوامر)، ويتجاهل أي تكرار لنفس المعرّف خلال نافذة زمنية قصيرة."""

    def __init__(self, ttl_seconds: float = 5.0, max_cache_size: int = 2000):
        super().__init__()
        self._seen = {}
        self._ttl = ttl_seconds
        self._max_cache_size = max_cache_size

    def _is_duplicate(self, key) -> bool:
        now = _time_module.monotonic()
        # تنظيف دوري بسيط عند تضخم الكاش، بدل تتبّع كل مفتاح بمؤقّت منفصل
        if len(self._seen) > self._max_cache_size:
            cutoff = now - self._ttl
            self._seen = {k: v for k, v in self._seen.items() if v > cutoff}

        last_seen = self._seen.get(key)
        self._seen[key] = now
        if last_seen is not None and (now - last_seen) < self._ttl:
            return True
        return False

    async def on_pre_process_callback_query(self, callback: types.CallbackQuery, data: dict):
        if self._is_duplicate(("cb", callback.id)):
            logger.warning(f"DuplicateUpdateGuard: تكرار مكتشف لضغطة زر callback.id={callback.id}, تم تجاهلها.")
            raise CancelHandler()

    async def on_pre_process_message(self, message: types.Message, data: dict):
        if self._is_duplicate(("msg", message.chat.id, message.message_id)):
            logger.warning(f"DuplicateUpdateGuard: تكرار مكتشف لرسالة message_id={message.message_id}, تم تجاهلها.")
            raise CancelHandler()


class MandatoryGateMiddleware(BaseMiddleware):
    def __init__(self):
        super().__init__()

    async def on_pre_process_message(self, message: types.Message, data: dict):
        # فحص حقيقي (بدون كاش) فقط عند /start أو /erc: لو المستخدم طلع من القناة
        # ورجع اشترك وحط /start مباشرة، لازم ينكشف هذا فوراً، مش بعد 5 دقائق كاش.
        text = (message.text or "").strip().lower()
        is_start_cmd = text.startswith("/start") or text.startswith("/erc")
        await self._check_gate(message.from_user.id, message.chat.id, is_callback=False, raw_update=message, force_fresh=is_start_cmd)

    async def on_pre_process_callback_query(self, callback: types.CallbackQuery, data: dict):
        if callback.data in _GATE_EXEMPT_CALLBACKS:
            return
        await self._check_gate(callback.from_user.id, callback.message.chat.id, is_callback=True, raw_update=callback)

    async def _check_gate(self, user_id: int, chat_id: int, is_callback: bool, raw_update, force_fresh: bool = False):
        # تأكد المستخدم موجود بقاعدة البيانات (بدون كسر أي منطق لاحق تبع /start)
        user = await get_user(user_id)
        if not user:
            # مستخدم جديد كلياً — منعطيه فرصة للـ /start الأصلي يشتغل أولاً
            # لينشئ سجله، وبعدها بأول تفاعل تاني رح تنفحص البوابة عادي.
            # هيك ما نكسر منطق get_or_create_user وnotify_admin_new_user_once.
            return

        lang = None
        try:
            lang = user["language"]
        except (KeyError, IndexError):
            lang = None

        if not lang:
            if is_callback:
                await safe_answer_callback(raw_update)
            await bot.send_message(chat_id, t("choose_language", None), reply_markup=language_selection_keyboard())
            raise _StopPropagation()

        # Maintenance mode check
        maintenance = await get_config_value("maintenance_mode")
        if maintenance == "1":
            is_admin_user = user["is_admin"] or user["is_owner"]
            if not is_admin_user:
                if is_callback:
                    await safe_answer_callback(raw_update)
                await bot.send_message(chat_id, "━━━━━━━━━━━━━━━━━━━\n◆ وضع الصيانة ◆\n━━━━━━━━━━━━━━━━━━━\n\nالبوت تحت الصيانة حالياً.\nيعود قريباً مع تحديثات جديدة!")
                raise _StopPropagation()

        subscribed, _missing_channel = await is_user_subscribed_to_all_targets(bot, user_id, force_fresh=force_fresh)
        # الأدمن والمالك معفيين من الاشتراك الإجباري
        is_admin_user = user["is_admin"] or user["is_owner"]
        if not subscribed and not is_admin_user:
            if is_callback:
                await safe_answer_callback(raw_update)
            await bot.send_message(chat_id, t("force_sub_required", lang), reply_markup=await force_sub_keyboard(lang))
            raise _StopPropagation()


class _StopPropagation(Exception):
    """استثناء داخلي لوقف تمرير التحديث لبقية الهاندلرز عند فشل البوابة."""
    pass


# aiogram (النسخة القديمة المستخدمة هون) بترفع CancelHandler لوقف
# المعالجة، فنغلف رفع الاستثناء الداخلي بمعالج يحوّله لـ CancelHandler
# الرسمي تبع aiogram حتى ما ينكسر باقي نظام المعالجة. (مستورد أعلى الملف)


class MandatoryGateMiddlewareSafe(MandatoryGateMiddleware):
    async def on_pre_process_message(self, message: types.Message, data: dict):
        try:
            await super().on_pre_process_message(message, data)
        except _StopPropagation:
            raise CancelHandler()

    async def on_pre_process_callback_query(self, callback: types.CallbackQuery, data: dict):
        try:
            await super().on_pre_process_callback_query(callback, data)
        except _StopPropagation:
            raise CancelHandler()



# ─────────────────────────────────────────────
# هاندلرز اللغة
# ─────────────────────────────────────────────
@dp.callback_query_handler(text='set_lang_ar', state='*')
async def cb_set_lang_ar(callback: types.CallbackQuery, state: FSMContext):
    await set_user_language(callback.from_user.id, "ar")
    await safe_answer_callback(callback)
    # Delete the language-selection message (which might be a media message) and send the confirmation
    await delete_and_send(
        callback.message.chat.id, callback.from_user.id,
        t("language_set_ar", "ar"), None,
        old_message_id=callback.message.message_id
    )

    # بعد اختيار اللغة، نكمل بنفس تدفق البوابة: نتحقق من الاشتراك
    subscribed, _missing = await is_user_subscribed_to_all_targets(bot, callback.from_user.id)
    if not subscribed:
        await bot.send_message(callback.message.chat.id, t("force_sub_required", "ar"), reply_markup=await force_sub_keyboard("ar"))
        return

    await notify_admin_new_user_once(callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
    await send_welcome_once(callback.message.chat.id, callback.from_user.id, "ar")
    await send_main_menu(callback.message.chat.id, callback.from_user.id)


@dp.callback_query_handler(text='set_lang_en', state='*')
async def cb_set_lang_en(callback: types.CallbackQuery, state: FSMContext):
    await set_user_language(callback.from_user.id, "en")
    await safe_answer_callback(callback)
    await delete_and_send(
        callback.message.chat.id, callback.from_user.id,
        t("language_set_en", "en"), None,
        old_message_id=callback.message.message_id
    )

    subscribed, _missing = await is_user_subscribed_to_all_targets(bot, callback.from_user.id)
    if not subscribed:
        await bot.send_message(callback.message.chat.id, t("force_sub_required", "en"), reply_markup=await force_sub_keyboard("en"))
        return

    await notify_admin_new_user_once(callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
    await send_welcome_once(callback.message.chat.id, callback.from_user.id, "en")
    await send_main_menu(callback.message.chat.id, callback.from_user.id)


@dp.callback_query_handler(text='set_lang_fr', state='*')
async def cb_set_lang_fr(callback: types.CallbackQuery, state: FSMContext):
    await set_user_language(callback.from_user.id, "fr")
    await safe_answer_callback(callback)
    await delete_and_send(
        callback.message.chat.id, callback.from_user.id,
        t("language_set_fr", "fr"), None,
        old_message_id=callback.message.message_id
    )

    subscribed, _missing = await is_user_subscribed_to_all_targets(bot, callback.from_user.id)
    if not subscribed:
        await bot.send_message(callback.message.chat.id, t("force_sub_required", "fr"), reply_markup=await force_sub_keyboard("fr"))
        return

    await notify_admin_new_user_once(callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
    await send_welcome_once(callback.message.chat.id, callback.from_user.id, "fr")
    await send_main_menu(callback.message.chat.id, callback.from_user.id)


@dp.callback_query_handler(text='change_language', state='*')
async def cb_change_language(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    lang = await get_user_language(callback.from_user.id)
    await edit_or_send_message(
        callback.message.chat.id, callback.from_user.id,
        t("change_language_prompt", lang), language_selection_keyboard(), callback.message.message_id
    )


# ─────────────────────────────────────────────
# هاندلرز الاشتراك الإجباري
# ─────────────────────────────────────────────
@dp.callback_query_handler(text='verify_force_sub', state='*')
async def cb_verify_force_sub(callback: types.CallbackQuery, state: FSMContext):
    lang = await get_user_language(callback.from_user.id)
    invalidate_force_sub_cache(callback.from_user.id)
    subscribed, _missing = await is_user_subscribed_to_all_targets(bot, callback.from_user.id)
    if not subscribed:
        await safe_answer_callback(callback, t("force_sub_still_not_joined", lang), show_alert=True)
        return

    await safe_answer_callback(callback, t("force_sub_success", lang), show_alert=True)
    await notify_admin_new_user_once(callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
    await send_welcome_once(callback.message.chat.id, callback.from_user.id, lang)
    await send_main_menu(callback.message.chat.id, callback.from_user.id, callback.message.message_id)


# ─────────────────────────────────────────────
# CANCEL HANDLER
# ─────────────────────────────────────────────
@dp.message_handler(commands=['cancel'], state='*')
async def cmd_cancel(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    lang = await get_user_language(message.from_user.id) or "ar"
    if current_state is None:
        await message.answer(f" {t('no_operation', lang)}")
        return

    await state.finish()
    await notify_admin_new_user_once(message.from_user.id, message.from_user.username, message.from_user.first_name)
    await send_welcome_once(message.chat.id, message.from_user.id, lang)
    await send_main_menu(message.chat.id, message.from_user.id)


# ─────────────────────────────────────────────
# COMMAND HANDLERS
# ─────────────────────────────────────────────
@dp.message_handler(commands=['start', 'erc'], state='*')
async def cmd_start(message: types.Message, state: FSMContext):
    await state.finish()

    args = message.get_args()
    referral_code = None
    if args:
        referral_code = args

    # الحل الجذري: مصدر الحقيقة الوحيد لسؤال "هل هذا المستخدم أُحيل من قبل؟" هو
    # جدول referrals نفسه (عمود referred_id، المحمي بقيد UNIQUE)، وليس مجرد وجود
    # صف للمستخدم بجدول users. هذا يمنع الاستغلال (مستخدم قديم أُحيل من قبل يحاول
    # يستفيد من رابط ثانٍ) ويمنع بنفس الوقت خسارة إحالات شرعية (مستخدم قديم عنده
    # حساب بالبوت من قبل، بس لم يُحَل من أي شخص أبداً، ويستخدم رابط إحالة لأول مرة).
    already_referred = await is_user_already_referred(message.from_user.id)

    user = await get_or_create_user(
        message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )

    if not already_referred and referral_code and referral_code != user["referral_code"]:
        try:
            referrer = await get_user_by_referral_code(referral_code)
            if referrer and referrer["user_id"] != message.from_user.id:
                success = await add_referral(referrer["user_id"], message.from_user.id)
                if success:
                    try:
                        referrer_user = await get_user(referrer["user_id"])
                        total_pts = (referrer_user['points'] or 0)
                        await bot.send_message(
                            referrer["user_id"],
                            "━━━━━━━━━━━━━━━━━━━━━━\n"
                            "◆ إحالة جديدة! ◆\n"
                            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                            f" حصلت على <b>{POINTS_PER_REFERRAL}</b> نقطة\n"
                            f" إجمالي نقاطك: <b>{total_pts}</b>",
                            parse_mode=types.ParseMode.HTML,
                        )
                    except Exception as e:
                        logger.warning(f"cmd_start: failed to notify referrer {referrer['user_id']}: {e}")
                else:
                    logger.info(f"cmd_start: add_referral returned False for referrer={referrer['user_id']}, referred={message.from_user.id} (likely already referred or race condition).")
            elif not referrer:
                logger.info(f"cmd_start: referral_code '{referral_code}' does not match any user.")
        except Exception as e:
            logger.error(f"cmd_start: referral processing failed for user {message.from_user.id} with code '{referral_code}': {e}", exc_info=True)

    # بوابة اللغة: مستخدم جديد كلياً (تم إنشاؤه للتو) لازم يختار لغته أولاً
    lang = None
    try:
        lang = user["language"]
    except (KeyError, IndexError):
        lang = None

    if not lang:
        await bot.send_message(message.chat.id, t("choose_language", None), reply_markup=language_selection_keyboard())
        return

    subscribed, _missing = await is_user_subscribed_to_all_targets(bot, message.from_user.id)
    if not subscribed:
        await bot.send_message(message.chat.id, t("force_sub_required", lang), reply_markup=await force_sub_keyboard(lang))
        return

    await notify_admin_new_user_once(message.from_user.id, message.from_user.username, message.from_user.first_name)
    await send_welcome_once(message.chat.id, message.from_user.id, lang)
    await send_main_menu(message.chat.id, message.from_user.id)


@dp.message_handler(commands=['admin', 'ecr'], state='*')
async def cmd_admin(message: types.Message, state: FSMContext):
    await state.finish()
    if not await is_admin(message.from_user.id):
        return
    lang = await get_user_language(message.from_user.id) or "ar"
    text = (
        f"╔═══════════════════════╗\n"
        f"║  {t('adm_panel_title', lang)}  ║\n"
        f"╚═══════════════════════╝\n\n"
        f"{t('choose_action', lang)}"
    )
    await message.answer(text, reply_markup=admin_control_panel_keyboard(lang))


@dp.callback_query_handler(text='admin_panel', state='*')
async def cb_admin_panel(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    lang = await get_user_language(callback.from_user.id) or "ar"
    text = (
        f"╔═══════════════════════╗\n"
        f"║  {t('adm_panel_title', lang)}  ║\n"
        f"╚═══════════════════════╝\n\n"
        f"{t('choose_action', lang)}"
    )
    await edit_or_send_message(callback.message.chat.id, callback.from_user.id, text, admin_control_panel_keyboard(lang), callback.message.message_id, section="admin_panel")


@dp.callback_query_handler(text='main_menu', state='*')
async def cb_main_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    await send_main_menu(callback.message.chat.id, callback.from_user.id, callback.message.message_id)


@dp.callback_query_handler(text='noop', state='*')
async def cb_noop(callback: types.CallbackQuery, state: FSMContext):
    await safe_answer_callback(callback)


@dp.callback_query_handler(text='upload_bot', state='*')
async def cb_upload_bot(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    lang = await get_user_language(callback.from_user.id) or "ar"
    user = await get_user(callback.from_user.id)
    if user["points"] < POINTS_PER_BOT:
        text = (
            f" {t('insufficient_points', lang)}\n\n"
            f"{t('current_balance', lang)}: <b>{user['points']}</b> {t('points_word', lang)}\n"
            f"{t('cost', lang)}: <b>{POINTS_PER_BOT}</b> {t('points_word', lang)}\n\n"
            f" {t('get_points_via_referral', lang)}"
        )
        # No refresh button — points don't change without an explicit user action elsewhere.
        kb = back_keyboard(lang)
        await edit_or_send_message(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id, section="upload_bot")
        return

    limits = await get_user_limits(callback.from_user.id)
    current_files = await count_user_files(callback.from_user.id)
    if current_files >= limits["max_files"]:
        text = (
            f" {t('max_files_reached', lang)}\n\n"
            f"{t('your_files', lang)}: <b>{current_files}</b>\n"
            f"{t('max_allowed', lang)}: <b>{limits['max_files']}</b>\n\n"
            f" {t('request_upgrade', lang)}"
        )
        kb = back_keyboard(lang)
        await edit_or_send_message(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id, section="upload_bot")
        return

    text = (
        f" {t('send_file_py', lang)}\n\n"
        f" {t('notes', lang)}:\n"
        f" {t('points_deducted_after_approval', lang)}\n"
        f" {t('admin_approval_required', lang)}\n"
        f" {t('ensure_bot_works', lang)}\n\n"
        f" {t('cost', lang)}: {POINTS_PER_BOT} {t('points_word', lang)}"
    )
    kb = back_keyboard(lang)
    await edit_or_send_message(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id, section="upload_bot")
    await UploadBotState.waiting_file.set()


@dp.message_handler(content_types=types.ContentType.DOCUMENT, state=UploadBotState.waiting_file)
async def handle_bot_file(message: types.Message, state: FSMContext):
    doc = message.document
    if not doc.file_name.endswith((".py", ".php", ".js")):
        await message.answer(" الملف يجب أن يكون بصيغة .py أو .php أو .js فقط")
        return

    if doc.file_size > 20 * 1024 * 1024:
        return await message.answer(" حجم الملف كبير جداً (الحد 20MB)")

    limits = await get_user_limits(message.from_user.id)
    current_files = await count_user_files(message.from_user.id)
    if current_files >= limits["max_files"]:
        await message.answer(f" وصلت للحد الأقصى للملفات المسموحة ({limits['max_files']}). اطلب ترقية من الأدمن.")
        await state.finish()
        return

    file_info = await bot.get_file(doc.file_id)
    safe_name = f"{uuid.uuid4().hex}_{doc.file_name}"
    dest = BOTS_DIR / safe_name
    if doc.file_name.endswith(".php"):
        bot_file_type = "php"
    elif doc.file_name.endswith(".js"):
        bot_file_type = "javascript"
    else:
        bot_file_type = "python"

    try:
        await bot.download_file(file_info.file_path, destination=dest)
        bot_id = await add_bot(message.from_user.id, doc.file_name, str(dest), file_type=bot_file_type)
        metadata_block = generate_pixel_encoding_block(message.from_user.id, bot_id, bot_file_type)
        await prepend_metadata_to_file(dest, metadata_block)
        await add_file_log(message.from_user.id, doc.file_name, "upload_bot")

        await approve_bot(bot_id)

        explanation = generate_upload_explanation("بوت", bot_id, bot_file_type)
        text = (
            f"تم رفع البوت\n الملف: <code>{sanitize_html_for_telegram(doc.file_name, max_len=200)}</code>\n"
            f" رقم الرفع: <b>{bot_id}</b>\n\nيمكنك تشغيله الآن من «بوتاتي»\n\n{explanation}"
        )
        await message.answer_document(document=InputFile(str(dest)), caption=text, reply_markup=back_keyboard())
        await send_section_media_followup(message.chat.id, "bot_uploaded")
        await state.finish()
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        await message.answer(f" حدث خطأ: {e}")
        await state.finish()


@dp.callback_query_handler(text_startswith='approve_bot_', state='*')
async def cb_approve_bot(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    bot_id = int(callback.data.split("_")[2])
    b = await get_bot_by_id(bot_id)
    if not b:
        await safe_answer_callback(callback, " غير موجود.", show_alert=True)
        return

    await approve_bot(bot_id)
    await update_user_points(b["user_id"], -POINTS_PER_BOT)

    try:
        await bot.send_message(
            b["user_id"],
            f" تم قبول بوتك\n\n الملف: <code>{b['file_name']}</code>\n تم خصم {POINTS_PER_BOT} نقاط من رصيدك.\n يمكنك الآن تشغيله من قسم 'بوتاتي'.",
        )
    except Exception:
        pass

    await safe_answer_callback(callback, " تم قبول البوت", show_alert=True)

    try:
        original_caption = callback.message.caption or ""
        new_caption = f" تم قبول الملف\n\n{original_caption}"
        if len(new_caption) > 1024:
            new_caption = new_caption[:1024]
        await bot.edit_message_caption(
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            caption=new_caption,
        )
    except Exception as e:
        logger.warning(f"Failed to update approval caption for bot {bot_id}: {e}")


@dp.callback_query_handler(text_startswith='reject_bot_', state='*')
async def cb_reject_bot(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    bot_id = int(callback.data.split("_")[2])
    b = await get_bot_by_id(bot_id)
    if not b:
        await safe_answer_callback(callback, " غير موجود.", show_alert=True)
        return

    await reject_bot(bot_id)

    try:
        await bot.send_message(
            b["user_id"],
            f" تم رفض بوتك\n\n الملف: <code>{b['file_name']}</code>",
        )
    except Exception:
        pass

    await safe_answer_callback(callback, " تم رفض البوت", show_alert=True)

    try:
        original_caption = callback.message.caption or ""
        new_caption = f" تم رفض الملف\n\n{original_caption}"
        if len(new_caption) > 1024:
            new_caption = new_caption[:1024]
        await bot.edit_message_caption(
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            caption=new_caption,
        )
    except Exception as e:
        logger.warning(f"Failed to update rejection caption for bot {bot_id}: {e}")


@dp.callback_query_handler(text='approve_all_bots', state='*')
async def cb_approve_all_bots(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback, " جاري قبول كل البوتات المعلقة...", show_alert=False)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return

    pending = await get_pending_bots()
    if not pending:
        await safe_answer_callback(callback, " لا توجد بوتات معلقة حالياً.", show_alert=True)
        return

    approved_count = 0
    failed_count = 0

    for b in pending:
        try:
            await approve_bot(b["id"])
            await update_user_points(b["user_id"], -POINTS_PER_BOT)
            approved_count += 1
            try:
                await bot.send_message(b["user_id"], " تم قبول ملفك بنجاح.")
            except Exception as e:
                logger.warning(f"Could not notify user {b['user_id']} after bulk bot approval: {e}")
        except Exception as e:
            failed_count += 1
            logger.error(f"Failed to bulk-approve bot #{b['id']}: {e}", exc_info=True)

    summary = f" تم قبول {approved_count} بوت بنجاح."
    if failed_count:
        summary += f"\n فشل قبول {failed_count} عنصر (راجع سجل الأخطاء)."

    await edit_or_send_message(callback.message.chat.id, callback.from_user.id, summary, admin_back_keyboard(), callback.message.message_id)


@dp.callback_query_handler(text='approve_all_sites', state='*')
async def cb_approve_all_sites(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback, " جاري قبول كل المواقع المعلقة...", show_alert=False)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return

    pending = await get_pending_sites()
    if not pending:
        await safe_answer_callback(callback, " لا توجد مواقع معلقة حالياً.", show_alert=True)
        return

    approved_count = 0
    failed_count = 0

    for s in pending:
        try:
            await approve_site(s["id"])
            await update_user_points(s["user_id"], -POINTS_PER_SITE)
            approved_count += 1
            try:
                await bot.send_message(s["user_id"], " تم قبول ملفك بنجاح.")
            except Exception as e:
                logger.warning(f"Could not notify user {s['user_id']} after bulk site approval: {e}")
        except Exception as e:
            failed_count += 1
            logger.error(f"Failed to bulk-approve site #{s['id']}: {e}", exc_info=True)

    summary = f" تم قبول {approved_count} موقع بنجاح."
    if failed_count:
        summary += f"\n فشل قبول {failed_count} عنصر (راجع سجل الأخطاء)."

    await edit_or_send_message(callback.message.chat.id, callback.from_user.id, summary, admin_back_keyboard(), callback.message.message_id)


@dp.callback_query_handler(text_startswith='approve_site_', state='*')
async def cb_approve_site(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    site_id = int(callback.data.split("_")[2])
    async with db_cursor() as conn:
        s = conn.execute("SELECT * FROM sites WHERE id = ?", (site_id,)).fetchone()
    if not s:
        await safe_answer_callback(callback, " غير موجود.", show_alert=True)
        return

    await approve_site(site_id)
    await update_user_points(s["user_id"], -POINTS_PER_SITE)

    file_name_safe = sanitize_html_for_telegram(s["file_name"], max_len=150)
    updated_site = await get_site_by_id(site_id)
    notify_text = f" تم قبول موقعك\n\n الملف: <code>{file_name_safe}</code>\n تم خصم {POINTS_PER_SITE} نقاط من رصيدك."
    notify_kb = None
    if updated_site and is_valid_public_url(updated_site["site_url"]):
        notify_text += f"\n\n موقعك متاح الآن على الرابط التالي (شغّال طول ما البوت يعمل):"
        notify_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="فتح الموقع الآن ⇢", url=updated_site["site_url"], style="success")]
        ])

    try:
        await bot.send_message(s["user_id"], notify_text, reply_markup=notify_kb)
    except Exception:
        pass

    await safe_answer_callback(callback, " تم قبول الموقع", show_alert=True)

    try:
        original_caption = callback.message.caption or ""
        new_caption = f" تم قبول الملف\n\n{original_caption}"
        if len(new_caption) > 1024:
            new_caption = new_caption[:1024]
        await bot.edit_message_caption(
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            caption=new_caption,
        )
    except Exception as e:
        logger.warning(f"Failed to update approval caption for site {site_id}: {e}")


@dp.callback_query_handler(text_startswith='reject_site_', state='*')
async def cb_reject_site(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    site_id = int(callback.data.split("_")[2])
    async with db_cursor() as conn:
        s = conn.execute("SELECT * FROM sites WHERE id = ?", (site_id,)).fetchone()
    if not s:
        await safe_answer_callback(callback, " غير موجود.", show_alert=True)
        return

    await reject_site(site_id)

    try:
        await bot.send_message(
            s["user_id"],
            f" تم رفض موقعك\n\n الملف: <code>{s['file_name']}</code>",
        )
    except Exception:
        pass

    await safe_answer_callback(callback, " تم رفض الموقع", show_alert=True)

    try:
        original_caption = callback.message.caption or ""
        new_caption = f" تم رفض الملف\n\n{original_caption}"
        if len(new_caption) > 1024:
            new_caption = new_caption[:1024]
        await bot.edit_message_caption(
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            caption=new_caption,
        )
    except Exception as e:
        logger.warning(f"Failed to update rejection caption for site {site_id}: {e}")


BOTS_PAGE_SIZE = 8


@dp.callback_query_handler(text='my_bots', state='*')
async def cb_my_bots(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    await render_my_bots_page(callback, page=0)


@dp.callback_query_handler(text_startswith='my_bots_page_', state='*')
async def cb_my_bots_page(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    try:
        page = int(callback.data.split("_")[3])
    except (ValueError, IndexError):
        page = 0
    await render_my_bots_page(callback, page=page)


async def render_my_bots_page(callback: types.CallbackQuery, page: int):
    """نفس حل pagination الجذري المطبَّق على مواقعي، يمنع نفس فئة العطل هنا:
    مستخدم برقم بوتات كبير (حتى 5000 بترقية 'مدى الحياة') كان يكسر هذا الزر
    بالكامل لأن تيليجرام يرفض كيبورد بعدد أزرار كبير جداً."""
    bots = await get_user_bots(callback.from_user.id)
    lang = await get_user_language(callback.from_user.id) or "ar"

    if not bots:
        await edit_or_send_message(callback.message.chat.id, callback.from_user.id, f"{t('my_bots_title', lang)}:\n\n{t('no_bots', lang)}", back_keyboard(lang), callback.message.message_id, section="my_bots")
        return

    total = len(bots)
    total_pages = max(1, (total + BOTS_PAGE_SIZE - 1) // BOTS_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * BOTS_PAGE_SIZE
    page_bots = bots[start:start + BOTS_PAGE_SIZE]

    # File names intentionally hidden from the public button list — only show a generic
    # "Bot #ID" label so the user can pick a slot without leaking filenames to onlookers.
    text = f"{t('my_bots_title', lang)} ({page + 1}/{total_pages}):\n\n"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for offset, b in enumerate(page_bots, 1):
        try:
            i = start + offset
            text += f"{i}. {t('bot_word', lang)} #{b['id']} ({status_text(b['status'])})\n"
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(
                    text=f"{t('manage_bot_word', lang)} #{b['id']}",
                    callback_data=f"select_bot_{b['id']}",
                    style="success"
                )
            ])
        except Exception as e:
            logger.error(f"render_my_bots_page: failed to render bot row (id={b['id'] if b else '?'}): {e}", exc_info=True)
            continue

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="السابق ‹", callback_data=f"my_bots_page_{page - 1}", style="primary"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(text="التالي ›", callback_data=f"my_bots_page_{page + 1}", style="primary"))
    if nav_row:
        keyboard.inline_keyboard.append(nav_row)

    keyboard.inline_keyboard.append([InlineKeyboardButton(text=en(t('back', lang)), callback_data="main_menu", style="danger")])
    await edit_or_send_message(callback.message.chat.id, callback.from_user.id, text, keyboard, callback.message.message_id, section="my_bots")


async def render_user_bot_panel(chat_id: int, user_id: int, bot_id: int, message_id: Optional[int] = None):
    bot_data = await get_bot_by_id(bot_id)
    if not bot_data or bot_data["user_id"] != user_id:
        return False

    lang = await get_user_language(user_id) or "ar"
    preview = await get_file_preview(bot_data["file_path"], lines=5)
    not_set = t("not_set", lang)
    token_display = mask_token_display(bot_data["bot_token"], not_set)
    text = (
        f" {t('manage_bot_title', lang)}: <code>{bot_data['file_name']}</code>\n\n"
        f" {t('status_label', lang)}: {status_text(bot_data['status'])}\n"
        f" {t('type_label', lang)}: {bot_data['file_type'].upper()}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f" {t('token_label', lang)}: <code>{token_display}</code>\n"
        f" {t('run_file_label', lang)}: <code>{bot_data['run_file'] or not_set}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f" {t('code_preview', lang)}:\n{preview}"
    )
    kb = user_bot_control_keyboard(bot_id, bot_data["status"], lang)
    if bot_data["bot_token"]:
        kb.inline_keyboard.insert(0, [InlineKeyboardButton(text=en(t('show_full_token', lang)), callback_data=f"user_bot_showtoken_{bot_id}", style="primary")])
    await edit_or_send_message(chat_id, user_id, text, kb, message_id)
    return True


@dp.callback_query_handler(text_startswith="user_bot_showtoken_", state='*')
async def cb_user_bot_showtoken(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    bot_id = int(callback.data.split("_")[3])
    bot_data = await get_bot_by_id(bot_id)
    lang = await get_user_language(callback.from_user.id) or "ar"
    if not bot_data or bot_data["user_id"] != callback.from_user.id or not bot_data["bot_token"]:
        await safe_answer_callback(callback, " لا يوجد توكن.", show_alert=True)
        return
    await safe_answer_callback(callback, t("full_token_alert", lang, token=bot_data["bot_token"]), show_alert=True)


@dp.callback_query_handler(text_startswith='select_bot_', state='*')
async def cb_select_bot(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    bot_id = int(callback.data.split("_")[2])
    ok = await render_user_bot_panel(callback.message.chat.id, callback.from_user.id, bot_id, callback.message.message_id)
    if not ok:
        await safe_answer_callback(callback, " البوت غير موجود.", show_alert=True)


@dp.callback_query_handler(text_startswith="user_bot_run_", state='*')
async def cb_user_bot_run(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback, " جاري التشغيل...", show_alert=False)
    try:
        bot_id = int(callback.data.split('_')[3])
    except (IndexError, ValueError):
        await safe_answer_callback(callback, " طلب غير صالح.", show_alert=True)
        return

    bot_data = await get_bot_by_id(bot_id)
    if not bot_data or bot_data["user_id"] != callback.from_user.id:
        await safe_answer_callback(callback, " البوت غير موجود.", show_alert=True)
        return
    if bot_data["status"] == "running":
        await safe_answer_callback(callback, " البوت يعمل بالفعل.", show_alert=True)
        return
    if bot_data["status"] not in ("approved", "stopped", "rejected"):
        await safe_answer_callback(callback, " لا يمكن تشغيل البوت في حالته الحالية.", show_alert=True)
        return

    lang = await get_user_language(callback.from_user.id) or "ar"
    loading_text = (
        f" {t('manage_bot_title', lang)}: <code>{bot_data['file_name']}</code>\n\n"
        f" {t('starting_bot', lang)}\n"
        f"{t('may_take_seconds', lang)}"
    )
    # Show loading message (deletes the old panel), capture the new message_id so we can delete it next
    current_msg_id = await edit_or_send_message(
        callback.message.chat.id, callback.from_user.id,
        loading_text, loading_keyboard(f" {t('starting_bot', lang)}"), callback.message.message_id
    )

    started, reason = await run_bot_process(bot_id, bot_data["file_path"])

    # Render the final panel — delete the loading message (current_msg_id) and send a fresh one
    await render_user_bot_panel(callback.message.chat.id, callback.from_user.id, bot_id, current_msg_id)

    if started:
        await safe_answer_callback(callback, t("start_success", lang), show_alert=True)
    else:
        await safe_answer_callback(callback, f"{t('start_failed', lang)}: {reason}", show_alert=True)
        await send_run_failure_log(callback.message.chat.id, callback.from_user.id, bot_id, is_admin_view=False, reason=reason)


@dp.callback_query_handler(text_startswith="user_bot_stop_", state='*')
async def cb_user_bot_stop(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback, " جاري الإيقاف...", show_alert=False)
    try:
        bot_id = int(callback.data.split('_')[3])
    except (IndexError, ValueError):
        await safe_answer_callback(callback, " طلب غير صالح.", show_alert=True)
        return
    bot_data = await get_bot_by_id(bot_id)
    if not bot_data or bot_data["user_id"] != callback.from_user.id:
        await safe_answer_callback(callback, " البوت غير موجود.", show_alert=True)
        return

    lang = await get_user_language(callback.from_user.id) or "ar"
    loading_text = (
        f" {t('manage_bot_title', lang)}: <code>{bot_data['file_name']}</code>\n\n"
        f" {t('stopping_bot', lang)}"
    )
    current_msg_id = await edit_or_send_message(
        callback.message.chat.id, callback.from_user.id,
        loading_text, loading_keyboard(f" {t('stopping_bot', lang)}"), callback.message.message_id
    )

    await stop_bot_process(bot_id)
    await render_user_bot_panel(callback.message.chat.id, callback.from_user.id, bot_id, current_msg_id)
    await safe_answer_callback(callback, t("bot_stopped", lang), show_alert=True)


# NOTE: the user_bot_logs_ handler is registered later in the file (cb_user_bot_logs_new),
# which filters to show only error lines. Don't register an early override here.


@dp.callback_query_handler(text='upload_site', state='*')
async def cb_upload_site(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    lang = await get_user_language(callback.from_user.id) or "ar"
    user = await get_user(callback.from_user.id)
    if user["points"] < POINTS_PER_SITE:
        text = (
            f" {t('insufficient_points', lang)}\n"
            f"{t('current_balance', lang)}: <b>{user['points']}</b>\n"
            f"{t('cost', lang)}: <b>{POINTS_PER_SITE}</b>"
        )
        kb = back_keyboard(lang)
        await edit_or_send_message(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id, section="upload_site")
        return

    limits = await get_user_limits(callback.from_user.id)
    current_files = await count_user_files(callback.from_user.id)
    if current_files >= limits["max_files"]:
        text = (
            f" {t('max_files_reached', lang)}\n\n"
            f"{t('your_files', lang)}: <b>{current_files}</b>\n"
            f"{t('max_allowed', lang)}: <b>{limits['max_files']}</b>\n\n"
            f" {t('request_upgrade', lang)}"
        )
        kb = back_keyboard(lang)
        await edit_or_send_message(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id, section="upload_site")
        return

    text = (
        f" {t('send_file_html', lang)}\n\n"
        f" {t('notes', lang)}:\n"
        f" {t('points_deducted_after_approval', lang)}\n"
        f" {t('admin_approval_required', lang)}\n\n"
        f" {t('cost', lang)}: {POINTS_PER_SITE} {t('points_word', lang)}"
    )
    kb = back_keyboard(lang)
    await edit_or_send_message(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id, section="upload_site")
    await UploadSiteState.waiting_file.set()


@dp.message_handler(content_types=types.ContentType.DOCUMENT, state=UploadSiteState.waiting_file)
async def handle_site_file(message: types.Message, state: FSMContext):
    doc = message.document
    if not doc.file_name.endswith((".html", ".htm", ".php")):
        await message.answer(" الملف يجب أن يكون بصيغة HTML أو PHP فقط")
        return
    if doc.file_size > 20 * 1024 * 1024:
        return await message.answer(" حجم الملف كبير جداً (الحد 20MB)")

    limits = await get_user_limits(message.from_user.id)
    current_files = await count_user_files(message.from_user.id)
    if current_files >= limits["max_files"]:
        await message.answer(f" وصلت للحد الأقصى للملفات المسموحة ({limits['max_files']}). اطلب ترقية من الأدمن.")
        await state.finish()
        return

    site_file_type = "php" if doc.file_name.endswith(".php") else "html"

    file_info = await bot.get_file(doc.file_id)
    safe_name = f"{uuid.uuid4().hex}_{doc.file_name}"
    dest = SITES_DIR / safe_name
    try:
        await bot.download_file(file_info.file_path, destination=dest)
        site_url = await build_site_url(dest)
        site_id = await add_site(message.from_user.id, doc.file_name, str(dest), site_url)
        metadata_block = generate_pixel_encoding_block(message.from_user.id, site_id, "html_site")
        await prepend_metadata_to_file(dest, metadata_block)
        await add_file_log(message.from_user.id, doc.file_name, "upload_site")

        await approve_site(site_id)

        explanation = generate_upload_explanation("موقع", site_id)
        text = f"تم رفع الموقع\n الملف: <code>{sanitize_html_for_telegram(doc.file_name, max_len=200)}</code>\n رقم الرفع: <b>{site_id}</b>\n\n{explanation}"
        await message.answer_document(document=InputFile(str(dest)), caption=text, reply_markup=back_keyboard())
        await send_section_media_followup(message.chat.id, "site_uploaded")
        await state.finish()
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        await message.answer(f" حدث خطأ: {e}")
        await state.finish()


SITES_PAGE_SIZE = 8


@dp.callback_query_handler(text='my_sites', state='*')
async def cb_my_sites(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    await render_my_sites_page(callback, page=0)


@dp.callback_query_handler(text_startswith='my_sites_page_', state='*')
async def cb_my_sites_page(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    try:
        page = int(callback.data.split("_")[3])
    except (ValueError, IndexError):
        page = 0
    await render_my_sites_page(callback, page=page)


def is_valid_public_url(url: Optional[str]) -> bool:
    """يتحقق أن الرابط صالح فعلياً كزر URL بتيليجرام: يجب أن يبدأ بـ http/https
    وألا يكون عنوان محلي (localhost أو 127.0.0.1) لأن تيليجرام يرفض أو يفشل
    بفتح مثل هذه الروابط من جهاز المستخدم."""
    if not url:
        return False
    url_lower = url.lower()
    if not (url_lower.startswith("http://") or url_lower.startswith("https://")):
        return False
    if "localhost" in url_lower or "127.0.0.1" in url_lower or "0.0.0.0" in url_lower:
        return False
    return True


async def render_my_sites_page(callback: types.CallbackQuery, page: int):
    """يعرض صفحة مواقع محدودة العدد (SITES_PAGE_SIZE) بدل كل مواقع المستخدم دفعة
    واحدة. هذا حل جذري لمشكلة كانت تُفشل الزر بالكامل لمستخدمين رفعوا عدداً كبيراً
    من المواقع (مثل مستخدمي الترقية 'مدى الحياة' بحد 5000 ملف)، لأن تيليجرام يرفض
    أي رسالة تحتوي كيبورد بعدد أزرار يتجاوز حده الداخلي، وكانت هذه الحالة تكسر
    الزر نهائياً بدون أي رسالة خطأ واضحة للمستخدم."""
    try:
        sites = await get_user_sites(callback.from_user.id)
    except Exception as e:
        logger.error(f"render_my_sites_page: get_user_sites failed for {callback.from_user.id}: {e}", exc_info=True)
        sites = []

    lang = await get_user_language(callback.from_user.id) or "ar"

    if not sites:
        await edit_or_send_message(callback.message.chat.id, callback.from_user.id, f"{t('my_sites_title', lang)}:\n\n{t('no_sites', lang)}", back_keyboard(lang), callback.message.message_id, section="my_sites")
        return

    total = len(sites)
    total_pages = max(1, (total + SITES_PAGE_SIZE - 1) // SITES_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * SITES_PAGE_SIZE
    page_sites = sites[start:start + SITES_PAGE_SIZE]

    text = f"{t('my_sites_title', lang)} ({page + 1}/{total_pages}):\n\n"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for offset, s in enumerate(page_sites, 1):
        try:
            i = start + offset
            file_name_safe = sanitize_html_for_telegram(s["file_name"] or "بدون اسم", max_len=100)
            text += f"{i}. {file_name_safe} ({status_text(s['status'])})\n"
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(text=f"إعدادات الموقع #{i} ", callback_data=f"site_settings_{s['id']}", style="primary"),
            ])
        except Exception as e:
            logger.error(f"render_my_sites_page: failed to render site row (id={s['id'] if s else '?'}): {e}", exc_info=True)
            continue

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="السابق ‹", callback_data=f"my_sites_page_{page - 1}", style="primary"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(text="التالي ›", callback_data=f"my_sites_page_{page + 1}", style="primary"))
    if nav_row:
        keyboard.inline_keyboard.append(nav_row)

    keyboard.inline_keyboard.append([InlineKeyboardButton(text="مسح جميع المواقع ", callback_data="user_site_delete_all_confirm", style="danger")])
    keyboard.inline_keyboard.append([InlineKeyboardButton(text=en(t('back', lang)), callback_data="main_menu", style="danger")])
    await edit_or_send_message(callback.message.chat.id, callback.from_user.id, text, keyboard, callback.message.message_id, section="my_sites")


@dp.callback_query_handler(text_startswith="site_settings_", state='*')
async def cb_site_settings(callback: types.CallbackQuery, state: FSMContext):
    """شاشة إعدادات موقع واحد: زر فتح الموقع بالأعلى، وزر حذف تحته، بدل عرض
    كل الأزرار متلاصقة بقائمة مواقعي الرئيسية."""
    await state.finish()
    await safe_answer_callback(callback)
    site_id = int(callback.data.split("_")[2])
    site_data = await get_site_by_id(site_id)
    lang = await get_user_language(callback.from_user.id) or "ar"
    if not site_data or site_data["user_id"] != callback.from_user.id:
        await safe_answer_callback(callback, t('site_not_found', lang), show_alert=True)
        return

    file_name_safe = sanitize_html_for_telegram(site_data["file_name"] or "بدون اسم", max_len=150)
    text = (
        f" إعدادات الموقع\n\n"
        f" الملف: <code>{file_name_safe}</code>\n"
        f" الحالة: {status_text(site_data['status'])}\n"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[])
    if site_data["status"] == "approved" and is_valid_public_url(site_data["site_url"]):
        kb.inline_keyboard.append([InlineKeyboardButton(text="فتح الموقع ⇢", url=site_data["site_url"], style="success")])
    elif site_data["status"] == "approved":
        text += "\n رابط الموقع غير متوفر حالياً (يحتاج تحديث من الأدمن)\n"

    kb.inline_keyboard.append([InlineKeyboardButton(text=en(t('download_site', lang)), callback_data=f"user_site_download_{site_id}", style="primary")])
    kb.inline_keyboard.append([InlineKeyboardButton(text=en(t('delete_site', lang)), callback_data=f"user_site_delete_confirm_{site_id}", style="danger")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="رجوع ‹", callback_data="my_sites", style="danger")])

    await edit_or_send_message(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)


@dp.callback_query_handler(text='my_points', state='*')
async def cb_my_points(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    lang = await get_user_language(callback.from_user.id) or "ar"
    user = await get_user(callback.from_user.id)
    limits = await get_user_limits(callback.from_user.id)
    tier_label = UPGRADE_TIERS.get(user["upgrade_tier"] or "none", UPGRADE_TIERS["none"])["label"]
    text = (
        f" {t('points_title', lang)}\n\n"
        f"{t('balance', lang)}: <b>{user['points']}</b>\n"
        f"{t('referrals', lang)}: <b>{user['referrals_count']}</b>\n"
        f" {t('upgrade', lang)}: <b>{tier_label}</b>\n"
        f" {t('max_files', lang)}: <b>{limits['max_files']}</b>\n"
        f" {t('concurrent_run', lang)}: <b>{limits['max_concurrent_bots']}</b>"
    )
    kb = back_keyboard(lang)
    await edit_or_send_message(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id, section="my_points")


@dp.callback_query_handler(text='referral', state='*')
async def cb_referral(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    user = await get_user(callback.from_user.id)
    lang = await get_user_language(callback.from_user.id) or "ar"
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user['referral_code']}"
    text = (
        f" {t('referral_title', lang)}:\n\n"
        f"<code>{ref_link}</code>\n\n"
        f" {t('share_for_points', lang, pts=POINTS_PER_REFERRAL)}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t("charge_balance_btn", lang), callback_data="charge_balance", style="success")],
        [InlineKeyboardButton(text=en(t('back', lang)), callback_data="main_menu", style="danger")],
    ])
    await edit_or_send_message(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id, section="referral")


@dp.callback_query_handler(text='ward_info', state='*')
async def cb_ward_info(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    lang = await get_user_language(callback.from_user.id) or "ar"
    text = (
        f" EYRX\n\n"
        f"{t('ward_info_text', lang)}\n"
        f" {t('developer_btn', lang)}: @{DEVELOPER_USERNAME}\n"
        f" {t('channel_btn', lang)}: @{DEVELOPER_CHANNEL}"
    )
    # Static info screen — no refresh button.
    kb = back_keyboard(lang)
    await edit_or_send_message(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id, section="ward_info")



# ─────────────────────────────────────────────
# ADMIN PANEL HANDLERS
# ─────────────────────────────────────────────
@dp.callback_query_handler(text='admin_stats', state='*')
async def cb_admin_stats(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    lang = await get_user_language(callback.from_user.id) or "ar"
    stats = await get_stats()
    text = (
        f" {t('adm_stats', lang)}:\n\n"
        f" {t('adm_users', lang)}: <b>{stats['total_users']}</b>\n"
        f" {t('adm_all_bots', lang)}: <b>{stats['total_bots']}</b>\n"
        f" {t('active_bots_word', lang)}: <b>{stats['active_bots']}</b>\n"
        f" {t('my_sites_btn', lang)}: <b>{stats['total_sites']}</b>\n"
    )
    await edit_or_send_message(callback.message.chat.id, callback.from_user.id, text, admin_back_keyboard(lang), callback.message.message_id)


@dp.callback_query_handler(text='admin_cpu_usage', state='*')
async def cb_admin_cpu_usage(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    cpu = get_cpu_usage()
    ram = get_ram_usage()
    disk = get_disk_usage()
    text = (
        f" استهلاك الموارد:\n\n"
        f" CPU: <b>{cpu:.2f}%</b>\n"
        f" RAM: <b>{ram['used']:.2f}GB / {ram['total']:.2f}GB ({ram['percent']:.2f}%)</b>\n"
        f" Disk: <b>{disk['used']:.2f}GB / {disk['total']:.2f}GB ({disk['percent']:.2f}%)</b>\n"
    )
    await edit_or_send_message(callback.message.chat.id, callback.from_user.id, text, admin_back_keyboard(), callback.message.message_id)


@dp.callback_query_handler(text='admin_users', state='*')
async def cb_admin_users(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    users = await get_all_users()
    text = " المستخدمون:\n\n"
    for user in users[:50]:
        tier_label = UPGRADE_TIERS.get(user["upgrade_tier"] or "none", UPGRADE_TIERS["none"])["label"]
        text += f"<code>{user['user_id']}</code> | @{user['username'] or 'N/A'} | {user['points']} نقطة | {tier_label}\n"
    await edit_or_send_message(callback.message.chat.id, callback.from_user.id, text, admin_back_keyboard(), callback.message.message_id)


@dp.callback_query_handler(text='admin_files', state='*')
async def cb_admin_files(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    pending_bots = await get_pending_bots()
    pending_sites = await get_pending_sites()

    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    text = " الملفات المعلقة:\n\n"
    if pending_bots:
        text += " بوتات:\n"
        for b in pending_bots:
            text += f"{b['id']} | <code>{b['file_name']}</code> | <code>{b['user_id']}</code>\n"
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(text=f"مراجعة بوت #{b['id']} ", callback_data=f"review_bot_{b['id']}", style="success")
            ])
        keyboard.inline_keyboard.append([InlineKeyboardButton(text="قبول كل البوتات المعلقة ", callback_data="approve_all_bots", style="success")])
    else:
        text += "لا توجد بوتات معلقة.\n"
    text += "\n"
    if pending_sites:
        text += " مواقع:\n"
        for s in pending_sites:
            text += f"{s['id']} | <code>{sanitize_html_for_telegram(s['file_name'], max_len=100)}</code> | <code>{s['user_id']}</code>\n"
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(text=f"نقل فوري #{s['id']} ≋", callback_data=f"quick_approve_site_{s['id']}", style="success"),
                InlineKeyboardButton(text=f"مراجعة #{s['id']} ", callback_data=f"review_site_{s['id']}", style="primary"),
            ])
        keyboard.inline_keyboard.append([InlineKeyboardButton(text="قبول كل المواقع المعلقة ", callback_data="approve_all_sites", style="success")])
    else:
        text += "لا توجد مواقع معلقة.\n"

    keyboard.inline_keyboard.append([InlineKeyboardButton(text="رجوع للوحة التحكم «", callback_data="admin_panel", style="danger")])
    await edit_or_send_message(callback.message.chat.id, callback.from_user.id, text, keyboard, callback.message.message_id)


@dp.callback_query_handler(text_startswith='quick_approve_site_', state='*')
async def cb_quick_approve_site(callback: types.CallbackQuery, state: FSMContext):
    """موافقة فورية على موقع مباشرة من قائمة الملفات المعلقة، بدون الحاجة للدخول
    لشاشة 'مراجعة' منفصلة أولاً. نفس منطق cb_approve_site لكن يرجّع لقائمة
    الملفات المعلقة المحدَّثة بدل تعديل caption رسالة مراجعة مستقلة."""
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    site_id = int(callback.data.split("_")[3])
    async with db_cursor() as conn:
        s = conn.execute("SELECT * FROM sites WHERE id = ?", (site_id,)).fetchone()
    if not s:
        await safe_answer_callback(callback, " غير موجود.", show_alert=True)
        return

    await approve_site(site_id)
    await update_user_points(s["user_id"], -POINTS_PER_SITE)

    file_name_safe = sanitize_html_for_telegram(s["file_name"], max_len=150)
    updated_site = await get_site_by_id(site_id)
    notify_text = f" تم قبول موقعك\n\n الملف: <code>{file_name_safe}</code>\n تم خصم {POINTS_PER_SITE} نقاط من رصيدك."
    notify_kb = None
    if updated_site and is_valid_public_url(updated_site["site_url"]):
        notify_text += f"\n\n موقعك متاح الآن على الرابط التالي (شغّال طول ما البوت يعمل):"
        notify_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="فتح الموقع الآن ⇢", url=updated_site["site_url"], style="success")]
        ])

    try:
        await bot.send_message(s["user_id"], notify_text, reply_markup=notify_kb)
    except Exception:
        pass

    await safe_answer_callback(callback, f" تم قبول الموقع #{site_id} فورياً", show_alert=True)
    await cb_admin_files(callback, state)


@dp.callback_query_handler(text_startswith='review_bot_', state='*')
async def cb_review_bot(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    bot_id = int(callback.data.split("_")[2])
    b = await get_bot_by_id(bot_id)
    if not b:
        await safe_answer_callback(callback, " غير موجود.", show_alert=True)
        return
    preview = await get_file_preview(b["file_path"], lines=15)
    text = (
        f" مراجعة البوت #{b['id']}\n\n"
        f" الملف: <code>{b['file_name']}</code>\n"
        f" المستخدم: <code>{b['user_id']}</code>\n\n"
        f" معاينة:\n{preview}"
    )
    await edit_or_send_message(callback.message.chat.id, callback.from_user.id, text, pending_bot_review_keyboard(bot_id), callback.message.message_id)


@dp.callback_query_handler(text_startswith='review_site_', state='*')
async def cb_review_site(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    site_id = int(callback.data.split("_")[2])
    async with db_cursor() as conn:
        s = conn.execute("SELECT * FROM sites WHERE id = ?", (site_id,)).fetchone()
    if not s:
        await safe_answer_callback(callback, " غير موجود.", show_alert=True)
        return
    preview = await get_file_preview(s["file_path"], lines=15)
    text = (
        f" مراجعة الموقع #{s['id']}\n\n"
        f" الملف: <code>{s['file_name']}</code>\n"
        f" المستخدم: <code>{s['user_id']}</code>\n\n"
        f" معاينة:\n{preview}"
    )
    await edit_or_send_message(callback.message.chat.id, callback.from_user.id, text, pending_site_review_keyboard(site_id), callback.message.message_id)


@dp.callback_query_handler(text='admin_bots_list', state='*')
async def cb_admin_bots_list(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    all_bots = await get_all_bots()
    if not all_bots:
        await edit_or_send_message(callback.message.chat.id, callback.from_user.id, " لا توجد بوتات.", admin_back_keyboard(), callback.message.message_id)
        return
    text = " كل البوتات:\n\n"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for b in all_bots[:50]:
        text += f"{b['id']} | {b['file_name']} ({status_text(b['status'])})\n"
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text=f"إدارة #{b['id']} - {b['file_name']} ", callback_data=f"admin_select_bot_{b['id']}", style="success")
        ])
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="رجوع للوحة التحكم «", callback_data="admin_panel", style="danger")])
    await edit_or_send_message(callback.message.chat.id, callback.from_user.id, text, keyboard, callback.message.message_id)


async def render_admin_bot_panel(chat_id: int, user_id: int, bot_id: int, message_id: Optional[int] = None):
    bot_data = await get_bot_by_id(bot_id)
    if not bot_data:
        return False
    lang = await get_user_language(user_id) or "ar"
    preview = await get_file_preview(bot_data["file_path"], lines=10)
    not_set = t("not_set", lang)
    token_display = mask_token_display(bot_data["bot_token"], not_set)
    text = (
        f" {t('manage_bot_title', lang)} (admin) #{bot_id}:\n\n"
        f" {t('file_label', lang)}: <code>{bot_data['file_name']}</code>\n"
        f" {t('status_label', lang)}: {status_text(bot_data['status'])}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f" {t('owner_id_label', lang)}: <code>{bot_data['user_id']}</code>\n"
        f" {t('token_label', lang)}: <code>{token_display}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f" {t('code_preview', lang)}:\n{preview}"
    )
    kb = bot_control_keyboard(bot_id, bot_data["status"], lang)
    if bot_data["bot_token"]:
        kb.inline_keyboard.insert(0, [InlineKeyboardButton(text=en(t('show_full_token', lang)), callback_data=f"admin_bot_showtoken_{bot_id}", style="primary")])
    await edit_or_send_message(chat_id, user_id, text, kb, message_id)
    return True


@dp.callback_query_handler(text_startswith="admin_bot_showtoken_", state='*')
async def cb_admin_bot_showtoken(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    bot_id = int(callback.data.split("_")[3])
    bot_data = await get_bot_by_id(bot_id)
    lang = await get_user_language(callback.from_user.id) or "ar"
    if not bot_data or not bot_data["bot_token"]:
        await safe_answer_callback(callback, " لا يوجد توكن.", show_alert=True)
        return
    await safe_answer_callback(callback, t("full_token_alert", lang, token=bot_data["bot_token"]), show_alert=True)


@dp.callback_query_handler(text_startswith='admin_select_bot_', state='*')
async def cb_admin_select_bot(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    bot_id = int(callback.data.split("_")[3])
    ok = await render_admin_bot_panel(callback.message.chat.id, callback.from_user.id, bot_id, callback.message.message_id)
    if not ok:
        await safe_answer_callback(callback, " البوت غير موجود.", show_alert=True)


@dp.callback_query_handler(text_startswith="bot_run_", state='*')
async def cb_admin_bot_run(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback, " جاري التشغيل...", show_alert=False)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    try:
        bot_id = int(callback.data.split('_')[2])
    except (IndexError, ValueError):
        await safe_answer_callback(callback, " طلب غير صالح.", show_alert=True)
        return
    bot_data = await get_bot_by_id(bot_id)
    if not bot_data:
        await safe_answer_callback(callback, " البوت غير موجود.", show_alert=True)
        return
    if bot_data["status"] == "running":
        await safe_answer_callback(callback, " البوت يعمل بالفعل.", show_alert=True)
        return

    lang = await get_user_language(callback.from_user.id) or "ar"
    loading_text = (
        f" {t('manage_bot_title', lang)} (admin) #{bot_id}:\n\n"
        f" {t('starting_bot', lang)}"
    )
    current_msg_id = await edit_or_send_message(
        callback.message.chat.id, callback.from_user.id,
        loading_text, loading_keyboard(f" {t('starting_bot', lang)}"), callback.message.message_id
    )

    started, reason = await run_bot_process(bot_id, bot_data["file_path"])
    await render_admin_bot_panel(callback.message.chat.id, callback.from_user.id, bot_id, current_msg_id)

    if started:
        await safe_answer_callback(callback, t("start_success", lang), show_alert=True)
    else:
        await safe_answer_callback(callback, f"{t('start_failed', lang)}: {reason}", show_alert=True)
        await send_run_failure_log(callback.message.chat.id, callback.from_user.id, bot_id, is_admin_view=True, reason=reason)


@dp.callback_query_handler(text_startswith="bot_stop_", state='*')
async def cb_admin_bot_stop(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback, " جاري الإيقاف...", show_alert=False)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    try:
        bot_id = int(callback.data.split('_')[2])
    except (IndexError, ValueError):
        await safe_answer_callback(callback, " طلب غير صالح.", show_alert=True)
        return

    bot_data = await get_bot_by_id(bot_id)
    lang = await get_user_language(callback.from_user.id) or "ar"
    if bot_data:
        loading_text = (
            f" {t('manage_bot_title', lang)} (admin) #{bot_id}:\n\n"
            f" {t('stopping_bot', lang)}"
        )
        current_msg_id = await edit_or_send_message(
            callback.message.chat.id, callback.from_user.id,
            loading_text, loading_keyboard(f" {t('stopping_bot', lang)}"), callback.message.message_id
        )
    else:
        current_msg_id = callback.message.message_id

    await stop_bot_process(bot_id)
    ok = await render_admin_bot_panel(callback.message.chat.id, callback.from_user.id, bot_id, current_msg_id)
    if not ok:
        await safe_answer_callback(callback, " البوت غير موجود.", show_alert=True)
        return
    await safe_answer_callback(callback, t("bot_stopped", lang), show_alert=True)


@dp.callback_query_handler(text='admin_add_media', state='*')
async def cb_admin_add_media(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    await callback.message.answer(" أرسل صورة أو فيديو (يمكنك إرسال أكثر من واحدة متتالية، أرسل /cancel للإنهاء):")
    await AdminAddMediaState.waiting_media.set()


@dp.message_handler(content_types=[types.ContentType.PHOTO, types.ContentType.VIDEO, types.ContentType.DOCUMENT], state=AdminAddMediaState.waiting_media)
async def msg_admin_add_media(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await state.finish()
        return
    try:
        file_id = None
        media_type = None
        if message.photo:
            file_id = message.photo[-1].file_id
            media_type = "photo"
        elif message.video:
            file_id = message.video.file_id
            media_type = "video"
        elif message.document:
            file_id = message.document.file_id
            media_type = "document"

        if file_id:
            async with db_cursor() as conn:
                conn.execute("INSERT INTO media_messages (media_type, file_id) VALUES (?, ?)", (media_type, file_id))
            await message.answer(" تم إضافة الوسائط. أرسل وسائط أخرى أو /cancel للإنهاء.")
        else:
            await message.answer(" وسائط غير صالحة.")
    except Exception as e:
        await message.answer(f" خطأ: {e}")


@dp.callback_query_handler(text='admin_section_media', state='*')
async def cb_admin_section_media(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for key, label in SECTION_KEYS.items():
        keyboard.inline_keyboard.append([InlineKeyboardButton(text=label, callback_data=f"set_section_media_{key}", style="success")])
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="رجوع للوحة التحكم «", callback_data="admin_panel", style="danger")])

    text = " وسائط الأقسام:\n\nاختر القسم الذي تريد تخصيص صورة/فيديو له عند كل تنقل إليه:"
    await edit_or_send_message(callback.message.chat.id, callback.from_user.id, text, keyboard, callback.message.message_id)


@dp.callback_query_handler(text_startswith='set_section_media_', state='*')
async def cb_set_section_media(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    section_key = callback.data.replace("set_section_media_", "")
    if section_key not in SECTION_KEYS:
        await safe_answer_callback(callback, " قسم غير معروف.", show_alert=True)
        return
    await state.update_data(section_key=section_key)
    label = SECTION_KEYS[section_key]
    await callback.message.answer(f" أرسل صورة أو فيديو ليظهر مع قسم: {label}")
    await AdminSectionMediaState.waiting_media.set()


@dp.message_handler(content_types=[types.ContentType.PHOTO, types.ContentType.VIDEO], state=AdminSectionMediaState.waiting_media)
async def msg_admin_section_media(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await state.finish()
        return
    data = await state.get_data()
    section_key = data.get("section_key")
    if not section_key or section_key not in SECTION_KEYS:
        await message.answer(" حدث خطأ، حاول من جديد من قائمة وسائط الأقسام.")
        await state.finish()
        return

    file_id = None
    media_type = None
    if message.photo:
        file_id = message.photo[-1].file_id
        media_type = "photo"
    elif message.video:
        file_id = message.video.file_id
        media_type = "video"

    if not file_id:
        await message.answer(" وسائط غير صالحة.")
        return

    await set_section_media(section_key, media_type, file_id)
    await message.answer(f" تم تعيين الوسائط لقسم: {SECTION_KEYS[section_key]}", reply_markup=admin_back_keyboard())
    await state.finish()



@dp.callback_query_handler(text='admin_create_coupon', state='*')
async def cb_admin_create_coupon(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    await callback.message.answer(" أرسل كود الكوبون:")
    await AdminCreateCouponState.waiting_code.set()


@dp.message_handler(state=AdminCreateCouponState.waiting_code)
async def msg_coupon_code(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await state.finish()
        return
    await state.update_data(code=message.text.strip())
    await message.answer(" أرسل عدد النقاط:")
    await AdminCreateCouponState.waiting_points.set()


@dp.message_handler(state=AdminCreateCouponState.waiting_points)
async def msg_coupon_points(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await state.finish()
        return
    try:
        points = int(message.text.strip())
        await state.update_data(points=points)
        await message.answer(" أرسل الحد الأقصى للاستخدام:")
        await AdminCreateCouponState.waiting_max_uses.set()
    except ValueError:
        await message.answer(" يجب إرسال رقم.")


@dp.message_handler(state=AdminCreateCouponState.waiting_max_uses)
async def msg_coupon_max_uses(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await state.finish()
        return
    try:
        max_uses = int(message.text.strip())
        data = await state.get_data()
        await add_coupon(data["code"], data["points"], max_uses, message.from_user.id)
        await message.answer(f" تم إنشاء الكوبون: <code>{data['code']}</code>", reply_markup=admin_back_keyboard())
        await state.finish()
    except ValueError:
        await message.answer(" يجب إرسال رقم.")


@dp.callback_query_handler(text='admin_add_points', state='*')
async def cb_admin_add_points(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    await callback.message.answer(" أرسل معرف المستخدم:")
    await AdminAddPointsState.waiting_user_id.set()


@dp.message_handler(state=AdminAddPointsState.waiting_user_id)
async def msg_add_points_uid(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await state.finish()
        return
    try:
        uid = int(message.text.strip())
        await state.update_data(target_uid=uid)
        await message.answer(" أرسل عدد النقاط لإضافتها:")
        await AdminAddPointsState.waiting_points.set()
    except ValueError:
        await message.answer(" معرف غير صالح.")


@dp.message_handler(state=AdminAddPointsState.waiting_points)
async def msg_add_points_val(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await state.finish()
        return
    try:
        points = int(message.text.strip())
        data = await state.get_data()
        target_uid = data["target_uid"]
        await update_user_points(target_uid, points)
        await message.answer(f" تم إضافة {points} نقطة للمستخدم {target_uid}", reply_markup=admin_back_keyboard())
        await state.finish()
        # إشعار المستخدم
        try:
            target_user = await get_user(target_uid)
            total = (target_user['points'] or 0) if target_user else points
            await bot.send_message(
                target_uid,
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "◆ إضافة رصيد ◆\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f" تمت إضافة <b>{points}</b> نقطة لحسابك\n"
                f" رصيدك الجديد: <b>{total}</b> نقطة",
                parse_mode=types.ParseMode.HTML,
            )
        except Exception:
            pass
    except ValueError:
        await message.answer(" يجب إرسال رقم.")


@dp.callback_query_handler(text='admin_deduct_points', state='*')
async def cb_admin_deduct_points(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    await callback.message.answer(" أرسل معرف المستخدم:")
    await AdminDeductPointsState.waiting_user_id.set()


@dp.message_handler(state=AdminDeductPointsState.waiting_user_id)
async def msg_deduct_points_uid(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await state.finish()
        return
    try:
        uid = int(message.text.strip())
        await state.update_data(target_uid=uid)
        await message.answer(" أرسل عدد النقاط لخصمها:")
        await AdminDeductPointsState.waiting_points.set()
    except ValueError:
        await message.answer(" معرف غير صالح.")


@dp.message_handler(state=AdminDeductPointsState.waiting_points)
async def msg_deduct_points_val(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await state.finish()
        return
    try:
        points = int(message.text.strip())
        data = await state.get_data()
        target_uid = data["target_uid"]
        await update_user_points(target_uid, -points)
        await message.answer(f" تم خصم {points} نقطة من المستخدم {target_uid}", reply_markup=admin_back_keyboard())
        await state.finish()
        # إشعار المستخدم
        try:
            target_user = await get_user(target_uid)
            total = (target_user['points'] or 0) if target_user else 0
            await bot.send_message(
                target_uid,
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "◆ خصم رصيد ◆\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f" تم خصم <b>{points}</b> نقطة من حسابك\n"
                f" رصيدك المتبقي: <b>{total}</b> نقطة",
                parse_mode=types.ParseMode.HTML,
            )
        except Exception:
            pass
    except ValueError:
        await message.answer(" يجب إرسال رقم.")


@dp.callback_query_handler(text='admin_upgrade_user', state='*')
async def cb_admin_upgrade_user(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    await callback.message.answer(" أرسل ايدي المستخدم المطلوب ترقيته:")
    await AdminUpgradeUserState.waiting_user_id.set()


@dp.message_handler(state=AdminUpgradeUserState.waiting_user_id)
async def msg_admin_upgrade_uid(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await state.finish()
        return
    try:
        uid = int(message.text.strip())
    except ValueError:
        await message.answer(" ايدي غير صالح.")
        return
    await state.update_data(target_uid=uid)
    kb = InlineKeyboardMarkup(inline_keyboard=[
[InlineKeyboardButton(text="ترقية عادية (5 ملفات / تشغيل ملفين) ⟐", callback_data="apply_upgrade_standard", style="success")],
[InlineKeyboardButton(text="ترقية مدى الحياة (5000 ملف / تشغيل 5) ⟡", callback_data="apply_upgrade_lifetime", style="success")],
    ])
    await message.answer(f" المستخدم: <code>{uid}</code>\nاختر نوع الترقية:", reply_markup=kb)
    await AdminUpgradeUserState.waiting_tier.set()


@dp.callback_query_handler(text_startswith='apply_upgrade_', state=AdminUpgradeUserState.waiting_tier)
async def cb_apply_upgrade(callback: types.CallbackQuery, state: FSMContext):
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await state.finish()
        return
    tier = callback.data.replace("apply_upgrade_", "")
    data = await state.get_data()
    uid = data.get("target_uid")
    if uid is None or tier not in UPGRADE_TIERS:
        await callback.message.answer(" حدث خطأ، حاول من جديد.")
        await state.finish()
        return

    ok = await set_user_upgrade(uid, tier)
    await state.finish()
    if not ok:
        await callback.message.answer(" فشلت الترقية.")
        return

    cfg = UPGRADE_TIERS[tier]
    text = (
        f" تم تفعيل {cfg['label']} للمستخدم <code>{uid}</code>\n\n"
        f" الحد الأقصى للملفات: <b>{cfg['max_files']}</b>\n"
        f" تشغيل متزامن: <b>{cfg['max_concurrent_bots']}</b>"
    )
    await callback.message.answer(text, reply_markup=admin_back_keyboard())

    try:
        await bot.send_message(
            uid,
            f" تمت ترقيتك بواسطة الإدارة!\n\n"
            f" نوع الترقية: <b>{cfg['label']}</b>\n"
            f" يمكنك الآن رفع حتى <b>{cfg['max_files']}</b> ملف\n"
            f" ويمكنك تشغيل حتى <b>{cfg['max_concurrent_bots']}</b> بوت بنفس الوقت",
        )
    except Exception:
        pass


@dp.callback_query_handler(text='admin_vip', state='*')
async def cb_admin_vip(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    await callback.message.answer(" أرسل معرف المستخدم لمنحه VIP:")
    await AdminVIPState.waiting_user_id.set()


@dp.message_handler(state=AdminVIPState.waiting_user_id)
async def msg_admin_vip_uid(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await state.finish()
        return
    try:
        uid = int(message.text.strip())
        await set_vip(uid, 1)
        await message.answer(f" تم منح VIP للمستخدم {uid}", reply_markup=admin_back_keyboard())
        await state.finish()
        # إشعار المستخدم
        try:
            await bot.send_message(
                uid,
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "◆ منح VIP ◆\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                " تم منحك عضوية VIP!\n"
                "استمتع بجميع المميزات الحصرية الآن ",
                parse_mode=types.ParseMode.HTML,
            )
        except Exception:
            pass
    except ValueError:
        await message.answer(" معرف غير صالح.")


@dp.callback_query_handler(text='admin_ban_user', state='*')
async def cb_admin_ban(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    await callback.message.answer(" أرسل معرف المستخدم لحظره:")
    await AdminBanUserState.waiting_user_id.set()


@dp.message_handler(state=AdminBanUserState.waiting_user_id)
async def msg_admin_ban_uid(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await state.finish()
        return
    try:
        uid = int(message.text.strip())
        await ban_user(uid)
        await message.answer(f" تم حظر المستخدم {uid}", reply_markup=admin_back_keyboard())
        await state.finish()
        # إشعار المستخدم
        try:
            await bot.send_message(
                uid,
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "◆ حظر ◆\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                " تم حظر حسابك من قبل الإدارة.\n"
                "للتواصل والدعم، تواصل مع المطور.",
                parse_mode=types.ParseMode.HTML,
            )
        except Exception:
            pass
    except ValueError:
        await message.answer(" معرف غير صالح.")


@dp.callback_query_handler(text='admin_unban_user', state='*')
async def cb_admin_unban(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    await callback.message.answer(" أرسل معرف المستخدم لفك حظره:")
    await AdminUnbanUserState.waiting_user_id.set()


@dp.message_handler(state=AdminUnbanUserState.waiting_user_id)
async def msg_admin_unban_uid(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await state.finish()
        return
    try:
        uid = int(message.text.strip())
        await unban_user(uid)
        await message.answer(f" تم فك حظر المستخدم {uid}", reply_markup=admin_back_keyboard())
        await state.finish()
        # إشعار المستخدم
        try:
            await bot.send_message(
                uid,
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "◆ فك الحظر ◆\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                " تم فك حظر حسابك!\n"
                "يمكنك استخدام البوت بشكل طبيعي الآن ",
                parse_mode=types.ParseMode.HTML,
            )
        except Exception:
            pass
    except ValueError:
        await message.answer(" معرف غير صالح.")


@dp.callback_query_handler(text='admin_broadcast', state='*')
async def cb_admin_broadcast(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    await callback.message.answer(" أرسل الرسالة للإذاعة:")
    await BroadcastState.waiting_message.set()


@dp.message_handler(state=BroadcastState.waiting_message)
async def msg_admin_broadcast(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await state.finish()
        return
    users = await get_all_users()
    count = 0
    for user in users:
        try:
            await message.copy_to(user["user_id"])
            count += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass
    await message.answer(f" تم الإرسال لـ {count} مستخدم.", reply_markup=admin_back_keyboard())
    await state.finish()


@dp.callback_query_handler(text='admin_terminal', state='*')
async def cb_admin_terminal(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    await edit_or_send_message(callback.message.chat.id, callback.from_user.id, " لوحة التحكم في الترمينال:", terminal_keyboard(), callback.message.message_id)


@dp.callback_query_handler(text_startswith='terminal_', state='*')
async def cb_terminal_actions(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return

    if not await is_owner(callback.from_user.id):
        await safe_answer_callback(callback, " هذه الميزة للمالك فقط.", show_alert=True)
        return

    action = callback.data.replace("terminal_", "")

    commands_map = {
        "install_pip": ("تثبيت مكاتب Python", "pip install aiogram aiofiles psutil"),
        "update_system": ("تحديث النظام", "apt update && apt upgrade -y"),
        "show_processes": ("عرض العمليات", "ps aux"),
        "cleanup": ("تنظيف الملفات", "rm -rf logs/*"),
        "system_info": ("معلومات النظام", "uname -a && lscpu"),
        "check_internet": ("فحص الاتصال", "ping -c 4 google.com"),
        "list_dirs": ("عرض المجلدات", "ls -R"),
        "search_file": ("بحث عن ملف", "find . -name '*.py'"),
        "install_git": ("تثبيت Git", "apt install git -y"),
        "install_sqlite": ("تثبيت SQLite", "apt install sqlite3 -y"),
        "install_ffmpeg": ("تثبيت FFmpeg", "apt install ffmpeg -y"),
        "monitor": ("مراقبة الموارد", "top -b -n 1"),
    }

    if action == "custom_command":
        await callback.message.answer(" أرسل الأمر المخصص:")
        await AdminTerminalState.waiting_command.set()
        return

    if action not in commands_map:
        await safe_answer_callback(callback, " إجراء غير معروف.", show_alert=True)
        return

    title, command = commands_map[action]
    await safe_answer_callback(callback, f" جاري: {title}", show_alert=True)

    try:
        await callback.message.edit_text(f" جاري: {title}\n\nقد يستغرق بعض الوقت...")
    except Exception:
        pass

    success, output, error = await safe_execute_terminal(command, timeout=300)

    if success:
        text = f" تم: {title}\n\n<pre>{sanitize_html_for_telegram(output[:3500] if output else '(تم)')}</pre>"
    else:
        text = f" فشل: {title}\n\n<pre>{sanitize_html_for_telegram(error[:2000])}\n{sanitize_html_for_telegram(output[:1500])}</pre>"

    await edit_or_send_message(callback.message.chat.id, callback.from_user.id, text, terminal_keyboard(), callback.message.message_id)


@dp.message_handler(state=AdminTerminalState.waiting_command)
async def msg_admin_terminal_custom(message: types.Message, state: FSMContext):
    if not await is_owner(message.from_user.id):
        await state.finish()
        return
    command = message.text.strip()
    await message.answer(f" جاري تنفيذ: <code>{sanitize_html_for_telegram(command)}</code>")
    success, output, error = await safe_execute_terminal(command, timeout=120)
    if success:
        text = f" تم التنفيذ:\n\n<pre>{sanitize_html_for_telegram(output[:3500] if output else '(تم)')}</pre>"
    else:
        text = f" فشل التنفيذ:\n\n<pre>{sanitize_html_for_telegram(error[:2000])}\n{sanitize_html_for_telegram(output[:1500])}</pre>"
    await message.answer(text, reply_markup=terminal_keyboard())
    await state.finish()



# ─────────────────────────────────────────────
# BOT CONTROL HANDLERS (أدمن)
# ─────────────────────────────────────────────
# (bot_logs handler replaced by VIP version above)


@dp.callback_query_handler(text_startswith="bot_token_", state='*')
async def cb_bot_token(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    bot_id = int(callback.data.split("_")[2])
    prompt_msg_id = await edit_or_send_message(callback.message.chat.id, callback.from_user.id, " أرسل التوكن الجديد:", bot_settings_back_keyboard(bot_id, admin_view=True), callback.message.message_id)
    await state.update_data(edit_bot_id=bot_id, prompt_msg_id=prompt_msg_id)
    await AdminChangeTokenState.waiting_token.set()


@dp.message_handler(state=AdminChangeTokenState.waiting_token)
async def msg_admin_change_token(message: types.Message, state: FSMContext):
    data = await state.get_data()
    bot_id = data["edit_bot_id"]
    prompt_msg_id = data.get("prompt_msg_id")
    new_token = message.text.strip()
    async with db_cursor() as conn:
        conn.execute("UPDATE bots SET bot_token = ? WHERE id = ?", (new_token, bot_id))
    try:
        await message.delete()
    except Exception:
        pass

    bot_data = await get_bot_by_id(bot_id)
    await apply_token_to_file(Path(bot_data["file_path"]), new_token)
    restart_result = await restart_bot_if_running(bot_id, bot_data["file_path"])

    updated_bot_data = await get_bot_by_id(bot_id)
    preview = await get_file_preview(updated_bot_data["file_path"], 90)
    text = (
        f" إعدادات البوت {bot_id}:\n\n"
        f" الملف: <code>{updated_bot_data['file_name']}</code>\n"
        f" التوكن: <code>{updated_bot_data['bot_token'] or 'غير محدد'}</code>\n"
        f" ملف التشغيل: <code>{updated_bot_data['run_file'] or 'غير محدد'}</code>\n"
        f" المسار: <code>{updated_bot_data['file_path']}</code>\n\n"
        f" معاينة الملف:\n{preview}"
    )
    if restart_result is not None:
        started, reason = restart_result
        text += f"\n\n تم تحديث التوكن (بالكود وبالتشغيل) وإعادة تشغيل البوت: {' نجح' if started else ' فشل - ' + reason}"
    else:
        text += "\n\n تم تحديث التوكن داخل كود البوت. البوت لم يكن يعمل، شغّله من القائمة."

    await edit_or_send_message(message.chat.id, message.from_user.id, text, bot_settings_back_keyboard(bot_id, admin_view=True), prompt_msg_id)
    await state.finish()


@dp.callback_query_handler(text_startswith="user_bot_token_", state='*')
async def cb_user_bot_token(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    bot_id = int(callback.data.split("_")[3])
    bot_data = await get_bot_by_id(bot_id)
    if not bot_data or bot_data["user_id"] != callback.from_user.id:
        await safe_answer_callback(callback, " البوت غير موجود.", show_alert=True)
        return
    prompt_msg_id = await edit_or_send_message(callback.message.chat.id, callback.from_user.id, " أرسل التوكن الجديد:", bot_settings_back_keyboard(bot_id, admin_view=False), callback.message.message_id)
    await state.update_data(edit_bot_id=bot_id, prompt_msg_id=prompt_msg_id)
    await UserChangeTokenState.waiting_token.set()


@dp.message_handler(state=UserChangeTokenState.waiting_token)
async def msg_user_change_token(message: types.Message, state: FSMContext):
    data = await state.get_data()
    bot_id = data["edit_bot_id"]
    prompt_msg_id = data.get("prompt_msg_id")
    new_token = message.text.strip()

    bot_data = await get_bot_by_id(bot_id)
    if not bot_data or bot_data["user_id"] != message.from_user.id:
        await message.answer(" البوت غير موجود.")
        await state.finish()
        return

    async with db_cursor() as conn:
        conn.execute("UPDATE bots SET bot_token = ? WHERE id = ?", (new_token, bot_id))
    try:
        await message.delete()
    except Exception:
        pass

    await apply_token_to_file(Path(bot_data["file_path"]), new_token)
    restart_result = await restart_bot_if_running(bot_id, bot_data["file_path"])

    updated_bot_data = await get_bot_by_id(bot_id)
    preview = await get_file_preview(updated_bot_data["file_path"], 90)
    text = (
        f" إعدادات البوت:\n\n"
        f" الملف: <code>{updated_bot_data['file_name']}</code>\n"
        f" الحالة: {status_text(updated_bot_data['status'])}\n"
        f" التوكن: <code>{updated_bot_data['bot_token'] or 'غير محدد'}</code>\n"
        f" ملف التشغيل: <code>{updated_bot_data['run_file'] or 'غير محدد'}</code>\n\n"
        f" معاينة الملف:\n{preview}"
    )
    if restart_result is not None:
        started, reason = restart_result
        if started:
            text += "\n\n تم تحديث التوكن (بالكود وبالتشغيل) وإعادة تشغيل البوت تلقائياً بنجاح."
        else:
            text += f"\n\n تم تحديث التوكن لكن فشلت إعادة التشغيل: {reason}"
    else:
        text += "\n\n تم تحديث التوكن داخل كود البوت. البوت لم يكن يعمل، اضغط تشغيل البوت لتشغيله."

    await edit_or_send_message(message.chat.id, message.from_user.id, text, bot_settings_back_keyboard(bot_id, admin_view=False), prompt_msg_id)
    await state.finish()


@dp.callback_query_handler(text_startswith="bot_id_", state='*')
async def cb_bot_id(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    bot_id = int(callback.data.split("_")[2])
    prompt_msg_id = await edit_or_send_message(callback.message.chat.id, callback.from_user.id, " أرسل اسم ملف التشغيل (اسم ملف فقط، بدون مسارات أو رموز):", bot_settings_back_keyboard(bot_id, admin_view=True), callback.message.message_id)
    await state.update_data(edit_bot_id=bot_id, prompt_msg_id=prompt_msg_id)
    await AdminChangeRunFileState.waiting_run_file.set()


@dp.message_handler(state=AdminChangeRunFileState.waiting_run_file)
async def msg_admin_change_run_file(message: types.Message, state: FSMContext):
    data = await state.get_data()
    bot_id = data["edit_bot_id"]
    prompt_msg_id = data.get("prompt_msg_id")
    new_run_file = message.text.strip()
    if not is_safe_run_file(new_run_file):
        await message.answer(" اسم غير صالح. استخدم حروف/أرقام/نقطة/شرطة فقط، بدون مسافات أو مسارات.")
        return
    async with db_cursor() as conn:
        conn.execute("UPDATE bots SET run_file = ? WHERE id = ?", (new_run_file, bot_id))
    try:
        await message.delete()
    except Exception:
        pass

    bot_data = await get_bot_by_id(bot_id)
    restart_result = await restart_bot_if_running(bot_id, bot_data["file_path"])

    updated_bot_data = await get_bot_by_id(bot_id)
    preview = await get_file_preview(updated_bot_data["file_path"], 90)
    text = (
        f" إعدادات البوت {bot_id}:\n\n"
        f" : <code>{updated_bot_data['file_name']}</code>\n"
        f" التوكن: <code>{updated_bot_data['bot_token'] or 'غير محدد'}</code>\n"
        f" ملف التشغيل: <code>{updated_bot_data['run_file'] or 'غير محدد'}</code>\n"
        f" المسار: <code>{updated_bot_data['file_path']}</code>\n\n"
        f" معاينة الملف:\n{preview}"
    )
    if restart_result is not None:
        started, reason = restart_result
        text += f"\n\n تم تحديث ملف التشغيل وإعادة التشغيل: {' نجح' if started else ' فشل - ' + reason}"

    await edit_or_send_message(message.chat.id, message.from_user.id, text, bot_settings_back_keyboard(bot_id, admin_view=True), prompt_msg_id)
    await state.finish()


@dp.callback_query_handler(text_startswith="user_bot_id_", state='*')
async def cb_user_bot_id(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    bot_id = int(callback.data.split("_")[3])
    bot_data = await get_bot_by_id(bot_id)
    if not bot_data or bot_data["user_id"] != callback.from_user.id:
        await safe_answer_callback(callback, " البوت غير موجود.", show_alert=True)
        return
    prompt_msg_id = await edit_or_send_message(callback.message.chat.id, callback.from_user.id, " أرسل اسم ملف التشغيل (اسم ملف فقط، بدون مسارات أو رموز):", bot_settings_back_keyboard(bot_id, admin_view=False), callback.message.message_id)
    await state.update_data(edit_bot_id=bot_id, prompt_msg_id=prompt_msg_id)
    await UserChangeRunFileState.waiting_run_file.set()


@dp.message_handler(state=UserChangeRunFileState.waiting_run_file)
async def msg_user_change_run_file(message: types.Message, state: FSMContext):
    data = await state.get_data()
    bot_id = data["edit_bot_id"]
    prompt_msg_id = data.get("prompt_msg_id")
    new_run_file = message.text.strip()
    if not is_safe_run_file(new_run_file):
        await message.answer(" اسم غير صالح. استخدم حروف/أرقام/نقطة/شرطة فقط، بدون مسافات أو مسارات.")
        return

    bot_data = await get_bot_by_id(bot_id)
    if not bot_data or bot_data["user_id"] != message.from_user.id:
        await message.answer(" البوت غير موجود.")
        await state.finish()
        return

    async with db_cursor() as conn:
        conn.execute("UPDATE bots SET run_file = ? WHERE id = ?", (new_run_file, bot_id))
    try:
        await message.delete()
    except Exception:
        pass

    restart_result = await restart_bot_if_running(bot_id, bot_data["file_path"])

    updated_bot_data = await get_bot_by_id(bot_id)
    preview = await get_file_preview(updated_bot_data["file_path"], 90)
    text = (
        f" إعدادات البوت:\n\n"
        f" الملف: <code>{updated_bot_data['file_name']}</code>\n"
        f" الحالة: {status_text(updated_bot_data['status'])}\n"
        f" التوكن: <code>{updated_bot_data['bot_token'] or 'غير محدد'}</code>\n"
        f" ملف التشغيل: <code>{updated_bot_data['run_file'] or 'غير محدد'}</code>\n\n"
        f" معاينة الملف:\n{preview}"
    )
    if restart_result is not None:
        started, reason = restart_result
        text += f"\n\n تم تحديث ملف التشغيل وإعادة التشغيل: {' نجح' if started else ' فشل - ' + reason}"

    await edit_or_send_message(message.chat.id, message.from_user.id, text, bot_settings_back_keyboard(bot_id, admin_view=False), prompt_msg_id)
    await state.finish()


# (bot_transfer handler replaced by bot_log_view above)


@dp.callback_query_handler(text_startswith="bot_delete_", state='*')
async def cb_bot_delete(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    bot_id = int(callback.data.split("_")[2])
    bot_data = await get_bot_by_id(bot_id)
    if not bot_data:
        await safe_answer_callback(callback, " البوت غير موجود.", show_alert=True)
        return
    await stop_bot_process(bot_id)
    file_path = Path(bot_data["file_path"])
    if file_path.exists():
        try:
            os.remove(file_path)
        except Exception as e:
            logger.warning(f"Failed to remove file {file_path}: {e}")
    async with db_cursor() as conn:
        conn.execute("DELETE FROM bots WHERE id = ?", (bot_id,))
    await safe_answer_callback(callback, " تم الحذف.", show_alert=True)
    await edit_or_send_message(callback.message.chat.id, callback.from_user.id, " تم الحذف.", admin_back_keyboard(), callback.message.message_id)


@dp.callback_query_handler(text_startswith="bot_advanced_", state='*')
async def cb_bot_advanced(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    bot_id = int(callback.data.split("_")[2])
    bot_data = await get_bot_by_id(bot_id)
    if not bot_data:
        await safe_answer_callback(callback, " البوت غير موجود.", show_alert=True)
        return

    preview = await get_file_preview(bot_data["file_path"], lines=45)

    text = (
        f" إعدادات البوت {bot_id}:\n\n"
        f" الملف: <code>{bot_data['file_name']}</code>\n"
        f" التوكن: <code>{bot_data['bot_token'] or 'غير محدد'}</code>\n"
        f" ملف التشغيل: <code>{bot_data['run_file'] or 'غير محدد'}</code>\n"
        f" المسار: <code>{bot_data['file_path']}</code>\n\n"
        f" معاينة الملف:\n{preview}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="تحديث ↻", callback_data=f"bot_advanced_{bot_id}", style="success")],
        [InlineKeyboardButton(text="رجوع لهذا البوت ‹", callback_data=f"admin_select_bot_{bot_id}", style="danger")],
    ])
    await edit_or_send_message(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)


@dp.callback_query_handler(text_startswith="user_bot_download_", state='*')
async def cb_user_bot_download(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    bot_id = int(callback.data.split('_')[3])
    bot_data = await get_bot_by_id(bot_id)
    if not bot_data or bot_data["user_id"] != callback.from_user.id:
        await safe_answer_callback(callback, " البوت غير موجود.", show_alert=True)
        return
    file_path = Path(bot_data["file_path"])
    if not file_path.exists():
        await safe_answer_callback(callback, " الملف غير موجود.", show_alert=True)
        return
    try:
        original_content = await remove_metadata_from_file(file_path)
        temp_file_path = file_path.parent / f"temp_{file_path.name}"
        async with aiofiles.open(temp_file_path, mode='w') as f:
            await f.write(original_content)
        await bot.send_document(callback.from_user.id, InputFile(str(temp_file_path)))
        os.remove(temp_file_path)
        await safe_answer_callback(callback, " تم إرسال الملف.", show_alert=True)
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        await safe_answer_callback(callback, " حدث خطأ.", show_alert=True)


# (bot_change_owner replaced by bot_change_owner2 above)


@dp.message_handler(state=AdminChangeOwnerState.waiting_new_owner_id)
async def msg_admin_change_owner(message: types.Message, state: FSMContext):
    data = await state.get_data()
    bot_id = data.get("owner_edit_bot_id")
    is_admin_view = data.get("is_admin_view", True)

    # Authorization: admin-view requires admin, user-view requires ownership of the bot
    if is_admin_view:
        if not await is_admin(message.from_user.id):
            await state.finish()
            return
    else:
        bot_data_check = await get_bot_by_id(bot_id) if bot_id else None
        if not bot_data_check or bot_data_check["user_id"] != message.from_user.id:
            await state.finish()
            return

    lang = await get_user_language(message.from_user.id) or "ar"
    new_owner_id = message.text.strip()
    if not new_owner_id.isdigit():
        await message.answer(t("invalid_id_msg", lang))
        return

    bot_data = await get_bot_by_id(bot_id)
    if not bot_data:
        await message.answer(t("bot_not_found", lang))
        await state.finish()
        return

    try:
        await message.delete()
    except Exception:
        pass

    ok = await apply_owner_id_to_file(Path(bot_data["file_path"]), new_owner_id)
    restart_result = await restart_bot_if_running(bot_id, bot_data["file_path"])

    if ok:
        text = t("owner_id_updated", lang)
    else:
        text = t("owner_id_added", lang)
    if restart_result is not None:
        started, reason = restart_result
        if started:
            text += "\n" + t("restart_success", lang)
        else:
            text += "\n" + t("restart_failed_with_reason", lang, reason=reason)

    await message.answer(text, reply_markup=bot_settings_back_keyboard(bot_id, admin_view=is_admin_view))
    await state.finish()



@dp.callback_query_handler(text='admin_coupons', state='*')
async def cb_admin_coupons(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    async with db_cursor() as conn:
        coupons = conn.execute("SELECT * FROM coupons ORDER BY created_at DESC").fetchall()
    text = " الكوبونات:\n\n"
    if not coupons:
        text += "لا توجد كوبونات."
    else:
        for coupon in coupons:
            text += f"<code>{coupon['code']}</code> | {coupon['points']} نقطة | {coupon['used_count']}/{coupon['max_uses']}\n"
    await edit_or_send_message(callback.message.chat.id, callback.from_user.id, text, admin_back_keyboard(), callback.message.message_id)


@dp.callback_query_handler(text='admin_file_logs', state='*')
async def cb_admin_file_logs(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    logs = await get_file_logs()
    if not logs:
        text = "لا توجد سجلات."
    else:
        text = " آخر العمليات:\n\n<pre>"
        for log in logs:
            text += f"[{log['created_at']}] {sanitize_html_for_telegram(log['file_name'] or '')} - {log['action']}\n"
        text += "</pre>"
    await edit_or_send_message(callback.message.chat.id, callback.from_user.id, text, admin_back_keyboard(), callback.message.message_id)


@dp.callback_query_handler(text='admin_manage_admins', state='*')
async def cb_admin_manage_admins(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_owner(callback.from_user.id):
        await safe_answer_callback(callback, " للمالك فقط.", show_alert=True)
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="إضافة أدمن ", callback_data="admin_add_admin", style="success")],
        [InlineKeyboardButton(text="إزالة أدمن ⁻", callback_data="admin_remove_admin", style="success")],
        [InlineKeyboardButton(text="رجوع ‹", callback_data="admin_panel", style="danger")]
    ])
    await edit_or_send_message(callback.message.chat.id, callback.from_user.id, " إدارة الأدمن:", keyboard, callback.message.message_id)


@dp.callback_query_handler(text='admin_add_admin', state='*')
async def cb_admin_add_admin(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_owner(callback.from_user.id):
        return
    await callback.message.answer(" أرسل معرف المستخدم لجعله أدمن:")
    await AdminAddAdminState.waiting_user_id.set()


@dp.message_handler(state=AdminAddAdminState.waiting_user_id)
async def msg_admin_add_admin(message: types.Message, state: FSMContext):
    if not await is_owner(message.from_user.id):
        await state.finish()
        return
    try:
        uid = int(message.text.strip())
        await set_admin(uid, 1)
        await message.answer(f" تم إضافة الأدمن {uid}", reply_markup=admin_back_keyboard())
        await state.finish()
    except ValueError:
        await message.answer(" معرف غير صالح.")


@dp.callback_query_handler(text='admin_remove_admin', state='*')
async def cb_admin_remove_admin(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_owner(callback.from_user.id):
        return
    await callback.message.answer(" أرسل معرف المستخدم لإزالته من الأدمن:")
    await AdminRemoveAdminState.waiting_user_id.set()


@dp.message_handler(state=AdminRemoveAdminState.waiting_user_id)
async def msg_admin_remove_admin(message: types.Message, state: FSMContext):
    if not await is_owner(message.from_user.id):
        await state.finish()
        return
    try:
        uid = int(message.text.strip())
        await set_admin(uid, 0)
        await message.answer(f" تم إزالة الأدمن {uid}", reply_markup=admin_back_keyboard())
        await state.finish()
    except ValueError:
        await message.answer(" معرف غير صالح.")




# ─────────────────────────────────────────────
# HOW IT WORKS HANDLERS
# ─────────────────────────────────────────────
@dp.callback_query_handler(text='how_it_works', state='*')
async def cb_how_it_works(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    lang = await get_user_language(callback.from_user.id) or "ar"
    text = (
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"◆ {t('how_it_works_btn', lang)} ◆\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"{t('how_it_works_text', lang)}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=en(t("back", lang)), callback_data="main_menu", style="danger")]
    ])
    await delete_and_send(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)


@dp.callback_query_handler(text='how_upload_works', state='*')
async def cb_how_upload_works(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    text = (
        "━━━━━━━━━━━━━━━━━━━\n"
        "◆ كيف يعمل الرفع؟ ◆\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        " رفع بوت:\n"
        " 1) اضغط «رفع بوت» من القائمة الرئيسية\n"
        " 2) ارسل ملف .py (الحد 20MB)\n"
        " 3) يتم خصم النقاط بعد موافقة الإدارة\n"
        " 4) بعد القبول شغّل بوتك من «بوتاتي»\n\n"
        " رفع موقع:\n"
        " 1) اضغط «رفع موقع»\n"
        " 2) ارسل ملف HTML\n"
        " 3) بعد القبول يحصل على رابط مباشر\n\n"
        "━━━━━━━━━━━━━━━━━━━"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="رجوع", callback_data="main_menu", style="danger")]
    ])
    await delete_and_send(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)


@dp.callback_query_handler(text='how_points_works', state='*')
async def cb_how_points_works(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    text = (
        "━━━━━━━━━━━━━━━━━━━\n"
        "◆ كيف يعمل نظام النقاط؟ ◆\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        " تبدأ بـ 10 نقاط مجاناً عند التسجيل\n"
        " رفع بوت يكلف 3 نقاط\n"
        " رفع موقع يكلف 2 نقاط\n"
        " كل دعوة ناجحة تمنحك نقطة واحدة\n"
        " استخدم الكوبونات للحصول على نقاط إضافية\n"
        " اطلب ترقية من الأدمن لزيادة حدودك\n\n"
        "━━━━━━━━━━━━━━━━━━━"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="رجوع", callback_data="my_points", style="danger")]
    ])
    await delete_and_send(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)


@dp.callback_query_handler(text='how_referral_works', state='*')
async def cb_how_referral_works(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    text = (
        "━━━━━━━━━━━━━━━━━━━\n"
        "◆ كيف يعمل نظام الدعوات؟ ◆\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        " شارك رابط الدعوة الخاص بك مع أصدقائك\n"
        " كل شخص يدخل البوت عبر رابطك يمنحك نقطة\n"
        f" ادعو {VIP_REQUIRED_REFERRALS} أشخاص واحصل على VIP مجاناً!\n"
        " VIP يفتح لك مميزات حصرية مثل تعديل الكود وتثبيت المكاتب\n\n"
        "━━━━━━━━━━━━━━━━━━━"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="رجوع", callback_data="referral", style="danger")]
    ])
    await delete_and_send(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)


@dp.callback_query_handler(text='how_bots_works', state='*')
async def cb_how_bots_works(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    text = (
        "━━━━━━━━━━━━━━━━━━━\n"
        "◆ كيف يعمل إدارة البوتات؟ ◆\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        " من «بوتاتي» اختر البوت الذي تريد إدارته\n"
        " تشغيل/إيقاف البوت بضغطة زر\n"
        " سجل الأخطاء يعرض لك الأخطاء فقط\n"
        " حساب السرعة يعرض سرعة استجابة البوت\n"
        " تغيير التوكن يحدّث الكود تلقائياً\n"
        " VIP: تعديل الكود، تثبيت مكاتب، تعديل الملف\n\n"
        "━━━━━━━━━━━━━━━━━━━"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="رجوع", callback_data="my_bots", style="danger")]
    ])
    await delete_and_send(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)


# ─────────────────────────────────────────────
# LOG VIEW (renamed from نقل استضافة)
# ─────────────────────────────────────────────
@dp.callback_query_handler(text_startswith="bot_log_view_", state='*')
async def cb_bot_log_view(callback: types.CallbackQuery, state: FSMContext):
    """تم دمج هذا الزر مع سجل الأخطاء؛ أي استدعاء قديم يُوجَّه لنفس منطق سجل الأخطاء."""
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    bot_id = int(callback.data.split("_")[3])
    await render_bot_error_log_admin(callback, bot_id)


@dp.callback_query_handler(text_startswith="user_bot_log_view_", state='*')
async def cb_user_bot_log_view(callback: types.CallbackQuery, state: FSMContext):
    """تم دمج هذا الزر مع سجل الأخطاء؛ أي استدعاء قديم يُوجَّه لنفس منطق سجل الأخطاء."""
    await state.finish()
    await safe_answer_callback(callback)
    bot_id = int(callback.data.split("_")[4])
    await render_bot_error_log_user(callback, bot_id)


@dp.callback_query_handler(text='how_log_works', state='*')
async def cb_how_log_works(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    text = (
        "━━━━━━━━━━━━━━━━━━━\n"
        "◆ كيف يعمل السجل؟ ◆\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        " هذا السجل يعرض كل مخرجات البوت منذ بدء تشغيله\n"
        " يمكنك رؤية الرسائل والأوامر والأخطاء\n"
        " اضغط تحديث لرؤية أحدث المخرجات\n"
        " إذا كان البوت متوقف، السجل يعرض آخر تشغيل\n\n"
        "━━━━━━━━━━━━━━━━━━━"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="رجوع", callback_data="my_bots", style="danger")]
    ])
    await delete_and_send(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)


# ─────────────────────────────────────────────
# BOT RESTART HANDLERS
# ─────────────────────────────────────────────
@dp.callback_query_handler(text_startswith="bot_restart_", state='*')
async def cb_bot_restart(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback, " جاري إعادة التشغيل...", show_alert=False)
    if not await is_admin(callback.from_user.id):
        return
    bot_id = int(callback.data.split("_")[2])
    bot_data = await get_bot_by_id(bot_id)
    lang = await get_user_language(callback.from_user.id) or "ar"
    if not bot_data or bot_data["status"] != "running":
        await safe_answer_callback(callback, t("bot_not_running", lang), show_alert=True)
        return
    loading_text = f" {t('restarting', lang)} #{bot_id}..."
    current_msg_id = await delete_and_send(callback.message.chat.id, callback.from_user.id, loading_text, loading_keyboard(f" {t('restarting', lang)}"), callback.message.message_id)
    await stop_bot_process(bot_id)
    started, reason = await run_bot_process(bot_id, bot_data["file_path"])
    await render_admin_bot_panel(callback.message.chat.id, callback.from_user.id, bot_id, current_msg_id)
    if started:
        await safe_answer_callback(callback, t("restart_success", lang), show_alert=True)
    else:
        await safe_answer_callback(callback, f"{t('restart_failed', lang)}: {reason}", show_alert=True)


@dp.callback_query_handler(text_startswith="user_bot_restart_", state='*')
async def cb_user_bot_restart(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback, " جاري إعادة التشغيل...", show_alert=False)
    bot_id = int(callback.data.split("_")[3])
    bot_data = await get_bot_by_id(bot_id)
    lang = await get_user_language(callback.from_user.id) or "ar"
    if not bot_data or bot_data["user_id"] != callback.from_user.id:
        await safe_answer_callback(callback, " البوت غير موجود.", show_alert=True)
        return
    if bot_data["status"] != "running":
        await safe_answer_callback(callback, t("bot_not_running", lang), show_alert=True)
        return
    loading_text = f" {t('restarting', lang)}..."
    current_msg_id = await delete_and_send(callback.message.chat.id, callback.from_user.id, loading_text, loading_keyboard(f" {t('restarting', lang)}"), callback.message.message_id)
    await stop_bot_process(bot_id)
    started, reason = await run_bot_process(bot_id, bot_data["file_path"])
    await render_user_bot_panel(callback.message.chat.id, callback.from_user.id, bot_id, current_msg_id)
    if started:
        await safe_answer_callback(callback, t("restart_success", lang), show_alert=True)
    else:
        await safe_answer_callback(callback, f"{t('restart_failed', lang)}: {reason}", show_alert=True)


# ─────────────────────────────────────────────
# BOT SPEED TEST
# ─────────────────────────────────────────────
@dp.callback_query_handler(text_startswith="bot_speed_", state='*')
async def cb_bot_speed(callback: types.CallbackQuery, state: FSMContext):
    try:
        await state.finish()
        await safe_answer_callback(callback)
        if not await is_admin(callback.from_user.id):
            return
        bot_id = int(callback.data.split("_")[2])
        bot_data = await get_bot_by_id(bot_id)
        lang = await get_user_language(callback.from_user.id) or "ar"
        if not bot_data or bot_data["status"] != "running":
            await safe_answer_callback(callback, t("bot_not_running", lang), show_alert=True)
            return
        import time
        async with animated_loading_indicator(callback.message.chat.id, " جاري قياس سرعة الاستجابة"):
            start = time.time()
            bot_data = await get_bot_by_id(bot_id)
            elapsed = (time.time() - start) * 1000
        text = (
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"◆ سرعة الاستجابة ◆\n"
            f"━━━━━━━━━━━━━━━━━━━\n\n"
            f"سرعة الاستجابة: <b>{elapsed:.2f} ms</b>"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="رجوع", callback_data=f"admin_select_bot_{bot_id}", style="danger")]
        ])
        await bot.send_message(callback.message.chat.id, text, reply_markup=kb)
    except Exception as e:
        logger.error(f"cb_bot_speed error: {e}", exc_info=True)
        try:
            await bot.send_message(callback.message.chat.id, f" خطأ أثناء قياس السرعة: {e}")
        except Exception:
            pass


@dp.callback_query_handler(text_startswith="user_bot_speed_", state='*')
async def cb_user_bot_speed(callback: types.CallbackQuery, state: FSMContext):
    try:
        await state.finish()
        await safe_answer_callback(callback)
        bot_id = int(callback.data.split("_")[3])
        bot_data = await get_bot_by_id(bot_id)
        lang = await get_user_language(callback.from_user.id) or "ar"
        if not bot_data or bot_data["user_id"] != callback.from_user.id:
            await safe_answer_callback(callback, " البوت غير موجود.", show_alert=True)
            return
        if bot_data["status"] != "running":
            await safe_answer_callback(callback, t("bot_not_running", lang), show_alert=True)
            return
        import time
        async with animated_loading_indicator(callback.message.chat.id, " جاري قياس سرعة الاستجابة"):
            start = time.time()
            bot_data = await get_bot_by_id(bot_id)
            elapsed = (time.time() - start) * 1000
        text = (
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"◆ سرعة الاستجابة ◆\n"
            f"━━━━━━━━━━━━━━━━━━━\n\n"
            f"سرعة الاستجابة: <b>{elapsed:.2f} ms</b>"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="رجوع", callback_data=f"select_bot_{bot_id}", style="danger")]
        ])
        await bot.send_message(callback.message.chat.id, text, reply_markup=kb)
    except Exception as e:
        logger.error(f"cb_user_bot_speed error: {e}", exc_info=True)
        try:
            await bot.send_message(callback.message.chat.id, f" خطأ أثناء قياس السرعة: {e}")
        except Exception:
            pass


# ─────────────────────────────────────────────
# BOT / PANEL UPTIME (وقت التشغيل)
# ─────────────────────────────────────────────
@dp.callback_query_handler(text_startswith="bot_uptime_", state='*')
async def cb_bot_uptime(callback: types.CallbackQuery, state: FSMContext):
    try:
        await state.finish()
        await safe_answer_callback(callback)
        if not await is_admin(callback.from_user.id):
            return
        bot_id = int(callback.data.split("_")[2])
        bot_data = await get_bot_by_id(bot_id)
        lang = await get_user_language(callback.from_user.id) or "ar"
        if not bot_data or bot_data["status"] != "running":
            await safe_answer_callback(callback, t("bot_not_running", lang), show_alert=True)
            return
        async with animated_loading_indicator(callback.message.chat.id, " جاري حساب وقت التشغيل"):
            panel_uptime = _time_module.time() - BOT_PROCESS_START_TIME
        text = (
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"◆ وقت التشغيل ◆\n"
            f"━━━━━━━━━━━━━━━━━━━\n\n"
            f"مدة تشغيل السيرفر الرئيسي بدون توقف:\n"
            f"<b>{format_uptime_duration(panel_uptime)}</b>"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="رجوع", callback_data=f"admin_select_bot_{bot_id}", style="danger")]
        ])
        await bot.send_message(callback.message.chat.id, text, reply_markup=kb)
    except Exception as e:
        logger.error(f"cb_bot_uptime error: {e}", exc_info=True)
        try:
            await bot.send_message(callback.message.chat.id, f" خطأ أثناء حساب وقت التشغيل: {e}")
        except Exception:
            pass


@dp.callback_query_handler(text_startswith="user_bot_uptime_", state='*')
async def cb_user_bot_uptime(callback: types.CallbackQuery, state: FSMContext):
    try:
        await state.finish()
        await safe_answer_callback(callback)
        bot_id = int(callback.data.split("_")[3])
        bot_data = await get_bot_by_id(bot_id)
        lang = await get_user_language(callback.from_user.id) or "ar"
        if not bot_data or bot_data["user_id"] != callback.from_user.id:
            await safe_answer_callback(callback, " البوت غير موجود.", show_alert=True)
            return
        if bot_data["status"] != "running":
            await safe_answer_callback(callback, t("bot_not_running", lang), show_alert=True)
            return
        async with animated_loading_indicator(callback.message.chat.id, " جاري حساب وقت التشغيل"):
            panel_uptime = _time_module.time() - BOT_PROCESS_START_TIME
        text = (
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"◆ وقت التشغيل ◆\n"
            f"━━━━━━━━━━━━━━━━━━━\n\n"
            f"مدة تشغيل السيرفر الرئيسي بدون توقف:\n"
            f"<b>{format_uptime_duration(panel_uptime)}</b>"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="رجوع", callback_data=f"select_bot_{bot_id}", style="danger")]
        ])
        await bot.send_message(callback.message.chat.id, text, reply_markup=kb)
    except Exception as e:
        logger.error(f"cb_user_bot_uptime error: {e}", exc_info=True)
        try:
            await bot.send_message(callback.message.chat.id, f" خطأ أثناء حساب وقت التشغيل: {e}")
        except Exception:
            pass


@dp.callback_query_handler(text="admin_panel_uptime", state='*')
async def cb_admin_panel_uptime(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    async with animated_loading_indicator(callback.message.chat.id, " جاري حساب وقت التشغيل"):
        panel_uptime = _time_module.time() - BOT_PROCESS_START_TIME
    text = (
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"◆ وقت تشغيل البوت ◆\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"شغّال بدون توقف منذ:\n<b>{format_uptime_duration(panel_uptime)}</b>"
    )
    await edit_or_send_message(callback.message.chat.id, callback.from_user.id, text, admin_back_keyboard(), callback.message.message_id)


@dp.callback_query_handler(text="admin_panel_speed", state='*')
async def cb_admin_panel_speed(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    import time
    async with animated_loading_indicator(callback.message.chat.id, " جاري قياس سرعة الاستجابة"):
        start = time.time()
        await get_config_value("auto_charge_approve")
        elapsed = (time.time() - start) * 1000
    text = (
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"◆ سرعة استجابة السيرفر ◆\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"سرعة الاستجابة: <b>{elapsed:.2f} ms</b>"
    )
    await edit_or_send_message(callback.message.chat.id, callback.from_user.id, text, admin_back_keyboard(), callback.message.message_id)


# ─────────────────────────────────────────────
# السجلات: سجل الأخطاء (مُفلتر) + سجل التشغيل الكامل (خام)
# ─────────────────────────────────────────────
async def get_bot_error_log(bot_id: int, max_chars: int = 3500) -> str:
    log_file = Path(f"logs/bot_{bot_id}.log")
    if not log_file.exists():
        return "لا توجد أخطاء"
    try:
        async with aiofiles.open(log_file, mode='r', encoding='utf-8', errors='ignore') as f:
            content = await f.read()
        if not content.strip():
            return "لا توجد أخطاء"
        error_lines = []
        for line in content.splitlines():
            lower = line.lower()
            if any(kw in lower for kw in ["error", "exception", "traceback", "failed", "errno"]):
                error_lines.append(line)
        if not error_lines:
            return "لا توجد أخطاء"
        error_text = "\n".join(error_lines)
        if len(error_text) > max_chars:
            error_text = "...\n" + error_text[-max_chars:]
        return sanitize_html_for_telegram(error_text, max_len=max_chars + 50)
    except Exception as e:
        return f"تعذر قراءة السجل: {e}"


async def get_bot_full_log(bot_id: int, max_chars: int = 3500) -> str:
    """يرجع سجل التشغيل الكامل الخام (كل المخرجات، مو الأخطاء فقط) — آخر جزء منه
    إذا كان طويلاً، لأن هذا هو الأحدث والأهم للتشخيص."""
    log_file = Path(f"logs/bot_{bot_id}.log")
    if not log_file.exists():
        return "لا يوجد سجل تشغيل بعد. شغّل البوت أولاً."
    try:
        async with aiofiles.open(log_file, mode='r', encoding='utf-8', errors='ignore') as f:
            content = await f.read()
        if not content.strip():
            return "السجل فارغ حالياً."
        if len(content) > max_chars:
            content = "...\n" + content[-max_chars:]
        return sanitize_html_for_telegram(content, max_len=max_chars + 50)
    except Exception as e:
        return f"تعذر قراءة السجل: {e}"


def _log_view_keyboard(bot_id: int, is_admin_view: bool, log_kind: str) -> InlineKeyboardMarkup:
    """يبني نفس مجموعة الأزرار (تحديث / كيف يعمل؟ / اسأل EYRX-AI / رجوع) لأي من
    شاشتي السجل (أخطاء أو تشغيل كامل)، للأدمن أو للمستخدم."""
    prefix = "bot" if is_admin_view else "user_bot"
    refresh_cb = f"{prefix}_logs_{bot_id}" if log_kind == "error" else f"{prefix}_full_log_{bot_id}"
    ask_ai_cb = f"admin_ai_ask_log_{bot_id}" if is_admin_view else f"ai_ask_{bot_id}"
    model_select_cb = "admin_ai_model_select" if is_admin_view else "user_ai_model_select"
    back_cb = f"{prefix}_log_menu_{bot_id}"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="تحديث ↻", callback_data=refresh_cb, style="success")],
        [InlineKeyboardButton(text="كيف يعمل؟ ", callback_data="how_log_works", style="primary")],
    ])
    kb.inline_keyboard.append([
        InlineKeyboardButton(text="اسأل EYRX-AI ", callback_data=ask_ai_cb, style="primary"),
    ])
    kb.inline_keyboard.append([
        InlineKeyboardButton(text="اختيار نموذج AI ", callback_data=model_select_cb, style="primary"),
    ])
    kb.inline_keyboard.append([
        InlineKeyboardButton(text="شحن AI ", callback_data="ai_charge_menu", style="success"),
    ])
    kb.inline_keyboard.append([InlineKeyboardButton(text="رجوع ‹", callback_data=back_cb, style="danger")])
    return kb


async def send_run_failure_log(chat_id: int, user_id: int, bot_id: int, is_admin_view: bool, reason: str = ""):
    """يرسل فوراً سجل الأخطاء + آخر جزء من سجل التشغيل الكامل لما يفشل تشغيل بوت،
    حتى يعرف المستخدم/الأدمن سبب الفشل فوراً بدون فتح شاشة السجل يدوياً."""
    error_content = await get_bot_error_log(bot_id, max_chars=1500)
    full_content = await get_bot_full_log(bot_id, max_chars=1000)
    reason_line = f" السبب: {html_module.escape(reason)}\n\n" if reason else ""
    text = (
        f" فشل تشغيل البوت #{bot_id}\n\n"
        f"{reason_line}"
        f" سجل الأخطاء:\n<pre>{error_content}</pre>\n\n"
        f" آخر جزء من سجل التشغيل الكامل:\n<pre>{full_content}</pre>"
    )
    if len(text) > 4000:
        text = text[:4000] + "\n…"
    menu_cb = f"bot_log_menu_{bot_id}" if is_admin_view else f"user_bot_log_menu_{bot_id}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="فتح شاشة السجل الكاملة ⁛⇢", callback_data=menu_cb, style="primary")]
    ])
    try:
        await bot.send_message(chat_id, text, reply_markup=kb)
    except Exception as e:
        logger.warning(f"send_run_failure_log failed to send as HTML: {e}")
        try:
            await bot.send_message(chat_id, text, reply_markup=kb, parse_mode=None)
        except Exception as e2:
            logger.error(f"send_run_failure_log failed entirely: {e2}")


async def render_bot_error_log_admin(callback: types.CallbackQuery, bot_id: int):
    error_content = await get_bot_error_log(bot_id)
    text = (
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"◆ سجل الأخطاء - بوت #{bot_id} ◆\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"<pre>{error_content}</pre>"
    )
    kb = _log_view_keyboard(bot_id, is_admin_view=True, log_kind="error")
    await delete_and_send(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)


async def render_bot_full_log_admin(callback: types.CallbackQuery, bot_id: int):
    full_content = await get_bot_full_log(bot_id)
    text = (
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"◆ سجل التشغيل الكامل - بوت #{bot_id} ◆\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"<pre>{full_content}</pre>"
    )
    kb = _log_view_keyboard(bot_id, is_admin_view=True, log_kind="full")
    await delete_and_send(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)


async def render_bot_error_log_user(callback: types.CallbackQuery, bot_id: int):
    bot_data = await get_bot_by_id(bot_id)
    if not bot_data or bot_data["user_id"] != callback.from_user.id:
        await safe_answer_callback(callback, " البوت غير موجود.", show_alert=True)
        return
    error_content = await get_bot_error_log(bot_id)
    text = (
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"◆ سجل الأخطاء - بوت #{bot_id} ◆\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"<pre>{error_content}</pre>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="تحديث ↻", callback_data=f"user_bot_logs_{bot_id}", style="success")],
        [InlineKeyboardButton(text="كيف يعمل؟ ", callback_data="how_log_works", style="primary")],
    ])

    ai_globally_on = await is_ai_enabled_globally()
    ai_disabled_for_user = await is_ai_disabled_for_user(callback.from_user.id)
    if ai_globally_on and not ai_disabled_for_user:
        kb.inline_keyboard.append([
            InlineKeyboardButton(text="اسأل EYRX-AI عن المشكلة ", callback_data=f"ai_ask_{bot_id}", style="primary"),
        ])
        kb.inline_keyboard.append([
            InlineKeyboardButton(text="شحن AI ", callback_data="ai_charge_menu", style="success"),
        ])

    kb.inline_keyboard.append([InlineKeyboardButton(text="رجوع ‹", callback_data=f"user_bot_log_menu_{bot_id}", style="danger")])
    await delete_and_send(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)


async def render_bot_full_log_user(callback: types.CallbackQuery, bot_id: int):
    bot_data = await get_bot_by_id(bot_id)
    if not bot_data or bot_data["user_id"] != callback.from_user.id:
        await safe_answer_callback(callback, " البوت غير موجود.", show_alert=True)
        return
    full_content = await get_bot_full_log(bot_id)
    text = (
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"◆ سجل التشغيل الكامل - بوت #{bot_id} ◆\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"<pre>{full_content}</pre>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="تحديث ↻", callback_data=f"user_bot_full_log_{bot_id}", style="success")],
        [InlineKeyboardButton(text="كيف يعمل؟ ", callback_data="how_log_works", style="primary")],
    ])

    ai_globally_on = await is_ai_enabled_globally()
    ai_disabled_for_user = await is_ai_disabled_for_user(callback.from_user.id)
    if ai_globally_on and not ai_disabled_for_user:
        kb.inline_keyboard.append([
            InlineKeyboardButton(text="اسأل EYRX-AI عن المشكلة ", callback_data=f"ai_ask_{bot_id}", style="primary"),
        ])
        kb.inline_keyboard.append([
            InlineKeyboardButton(text="شحن AI ", callback_data="ai_charge_menu", style="success"),
        ])

    kb.inline_keyboard.append([InlineKeyboardButton(text="رجوع ‹", callback_data=f"user_bot_log_menu_{bot_id}", style="danger")])
    await delete_and_send(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)


@dp.callback_query_handler(text_startswith="bot_log_menu_", state='*')
async def cb_bot_log_menu(callback: types.CallbackQuery, state: FSMContext):
    """قائمة السجل الموحّدة (أدمن): زر لسجل الأخطاء وزر لسجل التشغيل الكامل."""
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    bot_id = int(callback.data.split("_")[3])
    text = (
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"◆ سجل بوت #{bot_id} ◆\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"اختر نوع السجل الذي تريد عرضه:\n"
        f" سجل الأخطاء: يعرض فقط الأسطر التي فيها خطأ أو Exception.\n"
        f" سجل التشغيل الكامل: يعرض كل مخرجات البوت (طباعة، رسائل، أخطاء)."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="سجل الأخطاء ≡", callback_data=f"bot_logs_{bot_id}", style="danger")],
        [InlineKeyboardButton(text="سجل التشغيل الكامل ⁛", callback_data=f"bot_full_log_{bot_id}", style="primary")],
        [InlineKeyboardButton(text="رجوع ‹", callback_data=f"admin_select_bot_{bot_id}", style="danger")],
    ])
    await delete_and_send(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)


@dp.callback_query_handler(text_startswith="user_bot_log_menu_", state='*')
async def cb_user_bot_log_menu(callback: types.CallbackQuery, state: FSMContext):
    """قائمة السجل الموحّدة (مستخدم): زر لسجل الأخطاء وزر لسجل التشغيل الكامل."""
    await state.finish()
    await safe_answer_callback(callback)
    bot_id = int(callback.data.split("_")[4])
    bot_data = await get_bot_by_id(bot_id)
    if not bot_data or bot_data["user_id"] != callback.from_user.id:
        await safe_answer_callback(callback, " البوت غير موجود.", show_alert=True)
        return
    text = (
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"◆ سجل بوتك #{bot_id} ◆\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"اختر نوع السجل الذي تريد عرضه:\n"
        f" سجل الأخطاء: يعرض فقط الأسطر التي فيها خطأ أو Exception.\n"
        f" سجل التشغيل الكامل: يعرض كل مخرجات البوت (طباعة، رسائل، أخطاء)."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="سجل الأخطاء ≡", callback_data=f"user_bot_logs_{bot_id}", style="success")],
        [InlineKeyboardButton(text="سجل التشغيل الكامل ⁛", callback_data=f"user_bot_full_log_{bot_id}", style="primary")],
        [InlineKeyboardButton(text="رجوع ‹", callback_data=f"select_bot_{bot_id}", style="danger")],
    ])
    await delete_and_send(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)


@dp.callback_query_handler(text_startswith="bot_logs_", state='*')
async def cb_bot_logs_new(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    bot_id = int(callback.data.split("_")[2])
    await render_bot_error_log_admin(callback, bot_id)


@dp.callback_query_handler(text_startswith="bot_full_log_", state='*')
async def cb_bot_full_log_new(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    bot_id = int(callback.data.split("_")[3])
    await render_bot_full_log_admin(callback, bot_id)


@dp.callback_query_handler(text_startswith="user_bot_logs_", state='*')
async def cb_user_bot_logs_new(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    bot_id = int(callback.data.split("_")[3])
    await render_bot_error_log_user(callback, bot_id)


@dp.callback_query_handler(text_startswith="user_bot_full_log_", state='*')
async def cb_user_bot_full_log_new(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    bot_id = int(callback.data.split("_")[4])
    await render_bot_full_log_user(callback, bot_id)


@dp.callback_query_handler(text_startswith="admin_ai_ask_log_", state='*')
async def cb_admin_ai_ask_log(callback: types.CallbackQuery, state: FSMContext):
    """يبدأ محادثة EYRX-AI المفتوحة (أدمن) مع إرفاق سجلَي هذا البوت تلقائياً كسياق
    أول رسالة، بدون أي حد على عدد الأسئلة وبدون تقييد الموضوع."""
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    bot_id = int(callback.data.split("_")[4])


    await state.update_data(ai_history=[], ai_bot_id=bot_id)
    text = (
        f" EYRX-AI — بوت #{bot_id}\n\n"
        f"اكتب سؤالك، ورح يرفق تلقائياً سجل الأخطاء وسجل التشغيل الكامل لهذا البوت "
        f"مع أول رسالة. إذا في إصلاح كود، رح يرسله بصيغة كود منسّقة. اضغط 'إنهاء المحادثة' للخروج."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="إنهاء المحادثة ", callback_data=f"bot_log_menu_{bot_id}", style="danger")]
    ])
    await delete_and_send(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)
    await AdminAIChatState.waiting_message.set()


@dp.callback_query_handler(text_startswith="ai_ask_", state='*')
async def cb_ai_ask_start(callback: types.CallbackQuery, state: FSMContext):
    """يبدأ محادثة AI لتشخيص خطأ بوت معيّن، بعد التحقق من تفعيل الخدمة وحد الأسئلة."""
    await state.finish()
    await safe_answer_callback(callback)
    bot_id = int(callback.data.split("_")[2])
    bot_data = await get_bot_by_id(bot_id)
    if not bot_data or bot_data["user_id"] != callback.from_user.id:
        await safe_answer_callback(callback, " البوت غير موجود.", show_alert=True)
        return

    if not await is_ai_enabled_globally():
        await safe_answer_callback(callback, " خدمة الذكاء الاصطناعي معطّلة حالياً.", show_alert=True)
        return
    if await is_ai_disabled_for_user(callback.from_user.id):
        await safe_answer_callback(callback, " الذكاء الاصطناعي معطّل لحسابك من طرف الأدمن.", show_alert=True)
        return

    wallet = await get_ai_wallet(callback.from_user.id)
    has_wallet_credit = wallet["ai_questions_balance"] > 0

    if not has_wallet_credit:
        can_ask, remaining_minutes = await can_user_ask_ai(callback.from_user.id, bot_id)
        if not can_ask:
            hours = remaining_minutes // 60
            minutes = remaining_minutes % 60
            await safe_answer_callback(
                callback,
                f" استهلكت حد الأسئلة المسموح ({AI_QUESTIONS_LIMIT} سؤال). "
                f"يفتح مجدداً بعد {hours} ساعة و{minutes} دقيقة تقريباً.\n"
                f" يمكنك شحن رصيد AI لتجاوز هذا الحد فوراً.",
                show_alert=True,
            )
            return

    await state.update_data(ai_bot_id=bot_id)

    configured_models = await get_configured_ai_models()
    if not configured_models:
        await safe_answer_callback(
            callback,
            " لم يضبط الأدمن بعد أي مفتاح ذكاء اصطناعي. تواصل معه لتفعيل الخدمة.",
            show_alert=True,
        )
        return

    credit_line = (
        f" رصيدك: <b>{wallet['ai_questions_balance']}</b> سؤال متبقي من قسيمتك."
        if has_wallet_credit else
        f" مسموح لك بـ{AI_QUESTIONS_LIMIT} سؤال فقط كل {AI_COOLDOWN_HOURS} ساعات لهذا البوت."
    )
    text = (
        " مساعد تشخيص الأخطاء (AI)\n\n"
        "اختر النموذج الذي تريد الاستعانة به الآن:\n\n"
        f"{credit_line}"
    )
    kb_rows = []
    for key in configured_models:
        cfg = AI_MODELS_CATALOG[key]
        kb_rows.append([InlineKeyboardButton(text=cfg["label"], callback_data=f"ai_pickmodel_{key}_{bot_id}", style="primary")])
    kb_rows.append([InlineKeyboardButton(text="شحن AI ", callback_data="ai_charge_menu", style="success")])
    kb_rows.append([InlineKeyboardButton(text="إلغاء", callback_data=f"select_bot_{bot_id}", style="danger")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    await delete_and_send(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)


@dp.callback_query_handler(text_startswith="ai_pickmodel_", state='*')
async def cb_ai_pick_model(callback: types.CallbackQuery, state: FSMContext):
    """يُنفَّذ بعد اختيار المستخدم أحد أزرار النماذج الثلاثة مباشرة تحت زر 'اسأل':
    يثبّت اختيار النموذج لهذا المستخدم، ثم يقرأ تلقائياً كود ملف هذا البوت بالكامل
    مع سجل الأخطاء وسجل التشغيل، ويطلب من الذكاء تشخيصاً فورياً للمشكلة (إن وُجدت)
    قبل حتى ما يكتب المستخدم أي سؤال، فيوفّر له وقتاً ولا يطلب منه إرسال السجل يدوياً.
    مغلَّفة بالكامل بحماية من الانهيار حتى لا يتوقف باقي البوت عند أي خطأ شبكة."""
    try:
        await _cb_ai_pick_model_inner(callback, state)
    except Exception as e:
        logger.error(f"cb_ai_pick_model: خطأ غير متوقع: {e}", exc_info=True)
        try:
            await state.finish()
        except Exception:
            pass
        try:
            await bot.send_message(
                callback.message.chat.id,
                " صار خطأ غير متوقع أثناء قراءة الملف/السجلات. جرّب مرة أخرى من زر 'اسأل EYRX-AI'.",
            )
        except Exception:
            pass


async def _cb_ai_pick_model_inner(callback: types.CallbackQuery, state: FSMContext):
    await safe_answer_callback(callback, " جاري قراءة الملف والسجلات...", show_alert=False)
    try:
        rest = callback.data[len("ai_pickmodel_"):]
        model_key, bot_id_str = rest.rsplit("_", 1)
        bot_id = int(bot_id_str)
    except (ValueError, IndexError):
        await safe_answer_callback(callback, " خطأ بالبيانات.", show_alert=True)
        return
    if model_key not in AI_MODELS_CATALOG:
        await safe_answer_callback(callback, " نموذج غير معروف.", show_alert=True)
        return

    bot_data = await get_bot_by_id(bot_id)
    if not bot_data or bot_data["user_id"] != callback.from_user.id:
        await safe_answer_callback(callback, " البوت غير موجود.", show_alert=True)
        return

    await set_ai_model_choice(callback.from_user.id, model_key)
    await state.update_data(ai_bot_id=bot_id, ai_active_model=model_key)

    # قراءة تلقائية فورية لكل السياق المتاح (كود الملف + سجل الأخطاء + سجل التشغيل)
    # بدون انتظار أي طلب يدوي من المستخدم — هذا هو الفرق الأساسي المطلوب.
    wallet = await get_ai_wallet(callback.from_user.id)
    error_log = await get_bot_error_log(bot_id, max_chars=3000)
    context_parts = [f"سجل الأخطاء:\n```\n{error_log}\n```"]
    try:
        full_log = await get_bot_full_log(bot_id, max_chars=2000)
        context_parts.append(f"سجل التشغيل الكامل:\n```\n{full_log}\n```")
    except Exception as e:
        logger.warning(f"cb_ai_pick_model: تعذرت قراءة سجل التشغيل الكامل: {e}")

    file_read_ok = True
    try:
        target_file = resolve_bot_target_file(bot_data)
        if target_file.exists():
            async with aiofiles.open(target_file, mode='r', encoding='utf-8', errors='ignore') as f:
                file_content = await f.read()
            context_parts.append(f"محتوى ملف البوت الكامل ({target_file.name}):\n```python\n{file_content[:8000]}\n```")
        else:
            file_read_ok = False
    except Exception as e:
        logger.error(f"cb_ai_pick_model: تعذرت قراءة ملف البوت: {e}", exc_info=True)
        file_read_ok = False

    diagnostic_prompt = (
        "حلّل السجلات وكود الملف المرفقين وحدد فوراً: هل يوجد خطأ حالياً؟ إذا نعم، "
        "اشرح السبب الجذري بجملتين إلى ثلاث فقط، بدون كود مفصّل بهذا الرد الأول. "
        "إذا لم يوجد خطأ واضح، قل ذلك بوضوح."
    )
    full_context = "\n\n".join(context_parts) + f"\n\n{diagnostic_prompt}"

    ok, raw_reply = await _run_ai_with_thinking_indicator(
        callback.message.chat.id,
        [{"role": "user", "content": full_context}],
        EYRX_AI_DIAGNOSTIC_SYSTEM_PROMPT,
        user_id=callback.from_user.id,
    )
    await _bump_ai_model_usage_stat(model_key, bot_id, callback.from_user.id)

    cfg = AI_MODELS_CATALOG[model_key]
    if ok:
        reply_text = f" {cfg['label']} — تشخيص أولي:\n\n{format_ai_reply_for_telegram(raw_reply)}"
    else:
        reply_text = (
            f" تعذر التواصل مع {cfg['label']} حالياً.\n"
            f"{sanitize_html_for_telegram(str(raw_reply), max_len=500)}"
        )
    if not file_read_ok:
        reply_text += "\n\n ملاحظة: تعذّرت قراءة ملف البوت مباشرة، الرد أعلاه مبني على السجلات فقط."

    kb_rows = [
        [InlineKeyboardButton(text="صحّح المشكلة تلقائياً ", callback_data=f"ai_autofix_{bot_id}", style="success")],
        [InlineKeyboardButton(text="أضف ميزة ", callback_data=f"ai_addfeature_{bot_id}", style="primary")],
        [InlineKeyboardButton(text="اسأل سؤالاً إضافياً ", callback_data=f"ai_followup_{bot_id}", style="primary")],
        [InlineKeyboardButton(text="شحن AI ", callback_data="ai_charge_menu", style="success")],
        [InlineKeyboardButton(text="رجوع", callback_data=f"select_bot_{bot_id}", style="danger")],
    ]
    if not wallet["can_edit_files"]:
        kb_rows[0] = [InlineKeyboardButton(text="صحّح المشكلة (يتطلب باقة ذهبية) ", callback_data="ai_charge_menu", style="danger")]
        kb_rows[1] = [InlineKeyboardButton(text="أضف ميزة (يتطلب باقة ذهبية) ", callback_data="ai_charge_menu", style="danger")]

    await _safe_bot_send(callback.message.chat.id, reply_text, InlineKeyboardMarkup(inline_keyboard=kb_rows))


@dp.callback_query_handler(text_startswith="ai_followup_", state='*')
async def cb_ai_followup(callback: types.CallbackQuery, state: FSMContext):
    """يفتح باب كتابة سؤال حر إضافي بنفس النموذج المختار مسبقاً، بدل إعادة سؤال
    النموذج من جديد لكل سؤال (النموذج يبقى ثابتاً طول الجلسة لحتى يغيّره المستخدم)."""
    await safe_answer_callback(callback)
    bot_id = int(callback.data[len("ai_followup_"):])
    bot_data = await get_bot_by_id(bot_id)
    if not bot_data or bot_data["user_id"] != callback.from_user.id:
        await safe_answer_callback(callback, " البوت غير موجود.", show_alert=True)
        return
    data = await state.get_data()
    model_key = data.get("ai_active_model") or await get_ai_model_choice(callback.from_user.id)
    cfg = AI_MODELS_CATALOG.get(model_key, {})
    await state.update_data(ai_bot_id=bot_id, ai_active_model=model_key)
    text = (
        f" اكتب سؤالك الإضافي الآن (النموذج الحالي: {cfg.get('label', model_key)}).\n"
        "رح يبقى معه سياق الملف والسجل تلقائياً."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="إلغاء", callback_data=f"select_bot_{bot_id}", style="danger")]
    ])
    await bot.send_message(callback.message.chat.id, text, reply_markup=kb)
    await AskAIState.waiting_question.set()


AI_FIX_MAX_ATTEMPTS = 5  # أقصى عدد محاولات تصحيح تلقائي قبل الاستسلام والإبلاغ بالفشل


@dp.callback_query_handler(text_startswith="ai_autofix_", state='*')
async def cb_ai_autofix(callback: types.CallbackQuery, state: FSMContext):
    """يشغّل حلقة تصحيح تلقائية كاملة: الذكاء يقرأ ملف البوت كاملاً وسجل الأخطاء،
    يفكّر ويعدّل، نجرّب تشغيل النسخة المعدَّلة فعلياً على السيرفر، وإن فشلت نعيد
    السجل الجديد للذكاء ليصحح من جديد — كل هذا تلقائياً دون أي تأكيد يدوي بالمنتصف.
    فقط عند نجاح التشغيل الفعلي يُطبَّق التعديل على ملف البوت الحقيقي ويعاد تشغيله.
    مغلَّفة بالكامل بحماية من الانهيار حتى لا يتوقف باقي البوت عند أي خطأ غير متوقع."""
    try:
        await _cb_ai_autofix_inner(callback, state)
    except Exception as e:
        logger.error(f"cb_ai_autofix: خطأ غير متوقع: {e}", exc_info=True)
        try:
            await bot.send_message(
                callback.message.chat.id,
                " صار خطأ غير متوقع أثناء التصحيح التلقائي. لم يُعدَّل أي شيء بالملف الحقيقي.",
            )
        except Exception:
            pass


async def _cb_ai_autofix_inner(callback: types.CallbackQuery, state: FSMContext):
    await safe_answer_callback(callback, " جاري التحليل والتصحيح التلقائي...", show_alert=False)
    bot_id = int(callback.data[len("ai_autofix_"):])
    bot_data = await get_bot_by_id(bot_id)
    if not bot_data or bot_data["user_id"] != callback.from_user.id:
        await safe_answer_callback(callback, " البوت غير موجود.", show_alert=True)
        return

    wallet = await get_ai_wallet(callback.from_user.id)
    if not wallet["can_edit_files"]:
        await safe_answer_callback(
            callback,
            " تصحيح الملف تلقائياً متاح فقط مع باقة AI الذهبية (200 ).",
            show_alert=True,
        )
        return

    data = await state.get_data()
    model_key = data.get("ai_active_model") or await get_ai_model_choice(callback.from_user.id)
    if model_key not in AI_MODELS_CATALOG:
        model_key = AI_MODEL_DEFAULT

    error_log = await get_bot_error_log(bot_id, max_chars=3000)
    user_request = (
        "أصلح كل المشاكل الظاهرة بسجل الأخطاء وكود الملف، حتى يعمل البوت بشكل صحيح فوراً."
    )
    await _run_ai_fix_loop(
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
        bot_id=bot_id,
        bot_data=bot_data,
        model_key=model_key,
        user_request=user_request,
        initial_error_log=error_log,
    )


@dp.callback_query_handler(text_startswith="ai_addfeature_", state='*')
async def cb_ai_add_feature_start(callback: types.CallbackQuery, state: FSMContext):
    """يفتح باب كتابة طلب حر لإضافة أي ميزة/تعديل على البوت (وليس فقط تصحيح خطأ):
    مثلاً 'ضيفلي زر كذا' أو 'خلي البوت يرسل كذا عند كذا'. بعد إرسال الطلب تُشغَّل
    نفس حلقة التفكير-التعديل-التجربة-التصحيح التلقائية بالكامل."""
    await safe_answer_callback(callback)
    bot_id = int(callback.data[len("ai_addfeature_"):])
    bot_data = await get_bot_by_id(bot_id)
    if not bot_data or bot_data["user_id"] != callback.from_user.id:
        await safe_answer_callback(callback, " البوت غير موجود.", show_alert=True)
        return

    wallet = await get_ai_wallet(callback.from_user.id)
    if not wallet["can_edit_files"]:
        await safe_answer_callback(
            callback,
            " إضافة الميزات تلقائياً متاحة فقط مع باقة AI الذهبية (200 ).",
            show_alert=True,
        )
        return

    await state.update_data(ai_bot_id=bot_id)
    text = (
        " إضافة ميزة جديدة للبوت\n\n"
        "اكتب الآن أي شيء تريد إضافته أو تغييره بالبوت (مثال: 'ضيف زر يرسل رسالة "
        "ترحيب'، أو 'خلي البوت يحذف رسالة المستخدم بعد الرد'، أو أي طلب آخر).\n\n"
        "رح يقرأ الذكاء ملف بوتك كاملاً، ينفّذ طلبك، يجرّب تشغيله فعلياً، ويصلح أي "
        "مشكلة تظهر تلقائياً — كل هذا بدون أي خطوة إضافية منك."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="إلغاء", callback_data=f"select_bot_{bot_id}", style="danger")]
    ])
    await bot.send_message(callback.message.chat.id, text, reply_markup=kb)
    await AskAIState.waiting_add_feature_request.set()


@dp.message_handler(state=AskAIState.waiting_add_feature_request, content_types=types.ContentType.TEXT)
async def msg_ai_add_feature_request(message: types.Message, state: FSMContext):
    try:
        await _msg_ai_add_feature_request_inner(message, state)
    except Exception as e:
        logger.error(f"msg_ai_add_feature_request: خطأ غير متوقع: {e}", exc_info=True)
        try:
            await state.finish()
        except Exception:
            pass
        try:
            await message.answer(" صار خطأ غير متوقع. لم يُعدَّل أي شيء بالملف الحقيقي.")
        except Exception:
            pass


async def _msg_ai_add_feature_request_inner(message: types.Message, state: FSMContext):
    data = await state.get_data()
    bot_id = data.get("ai_bot_id")
    await state.finish()
    if not bot_id:
        await message.answer(" حدث خطأ، ابدأ من جديد من زر 'اسأل EYRX-AI'.")
        return

    bot_data = await get_bot_by_id(bot_id)
    if not bot_data or bot_data["user_id"] != message.from_user.id:
        await message.answer(" البوت غير موجود.")
        return

    user_text = (message.text or "").strip()
    if not user_text:
        await message.answer(" اكتب طلبك كنص.")
        return

    model_key = await get_ai_model_choice(message.from_user.id)
    if model_key not in AI_MODELS_CATALOG:
        model_key = AI_MODEL_DEFAULT

    error_log = await get_bot_error_log(bot_id, max_chars=1500)
    user_request = f"طلب المستخدم بالضبط: {user_text}"
    await _run_ai_fix_loop(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        bot_id=bot_id,
        bot_data=bot_data,
        model_key=model_key,
        user_request=user_request,
        initial_error_log=error_log,
    )


async def _run_ai_fix_loop(chat_id: int, user_id: int, bot_id: int, bot_data,
                            model_key: str, user_request: str, initial_error_log: str):
    """النواة المشتركة لكل من 'صحّح المشكلة' و'أضف ميزة': تقرأ ملف البوت كاملاً،
    تطلب من الذكاء تنفيذ الطلب (تصحيح أو إضافة ميزة) وإعادة كتابة الملف كاملاً،
    ثم تجرّب الكود الناتج بتشغيل فعلي معزول (try_run_candidate_code). إن فشلت
    التجربة، تُعاد المحاولة تلقائياً مع تزويد الذكاء بسجل فشل التجربة الفعلي —
    حتى AI_FIX_MAX_ATTEMPTS مرات. فقط عند نجاح تشغيل حقيقي فعلي يُطبَّق التعديل
    على الملف الحقيقي الموجود (بنسخة احتياطية تلقائية) ويُعاد تشغيل البوت، ويُبلَّغ
    المستخدم برسالة نهائية واحدة بسيطة أن البوت أصبح شغّالاً."""
    cfg = AI_MODELS_CATALOG.get(model_key, {})
    label = cfg.get("label", model_key)

    try:
        target_file = resolve_bot_target_file(bot_data)
        if not target_file.exists():
            await bot.send_message(chat_id, " ملف البوت غير موجود على السيرفر.")
            return
        async with aiofiles.open(target_file, mode='r', encoding='utf-8', errors='ignore') as f:
            file_content = await f.read()
    except Exception as e:
        logger.error(f"_run_ai_fix_loop: تعذرت قراءة الملف: {e}", exc_info=True)
        await bot.send_message(chat_id, " تعذّرت قراءة ملف البوت.")
        return

    fix_system_prompt = (
        EYRX_AI_DIAGNOSTIC_SYSTEM_PROMPT
        + " هذا المستخدم لديه صلاحية تعديل مباشر وفوري على ملف بوته. نفّذ طلبه بدقة "
          "وأعد كتابة الملف بالكامل (كل الأسطر، وليس فقط الجزء المعدَّل) داخل code "
          "block واحد فقط (```python ... ```)، لأن هذا الرد سيُشغَّل فعلياً للتجربة. "
          "لا تضع أي نص أو شرح داخل ذلك الـ code block نفسه، واشرح ما فعلته خارجه باختصار."
    )

    current_code = file_content
    current_error_log = initial_error_log
    progress_msg = None
    try:
        progress_msg = await bot.send_message(chat_id, f" {label} يحلّل الملف كاملاً ويبدأ العمل...")
    except Exception:
        pass

    for attempt in range(1, AI_FIX_MAX_ATTEMPTS + 1):
        if attempt == 1:
            prompt_content = (
                f"سجل الأخطاء الحالي:\n```\n{current_error_log}\n```\n\n"
                f"محتوى ملف البوت الحالي كاملاً ({target_file.name}):\n```python\n{current_code}\n```\n\n"
                f"{user_request}"
            )
        else:
            prompt_content = (
                f"جرّبنا تشغيل النسخة السابقة فعلياً على السيرفر ولم تعمل. هذا سجل فشل "
                f"التشغيل الفعلي (وليس سجل خطأ قديم):\n```\n{current_error_log[-3000:]}\n```\n\n"
                f"هذا هو الكود الذي جرّبناه بالضبط ({target_file.name}):\n```python\n{current_code}\n```\n\n"
                "أصلح السبب الجذري لهذا الفشل تحديداً وأعد كامل الملف مصححاً. "
                f"(محاولة {attempt} من {AI_FIX_MAX_ATTEMPTS})"
            )

        try:
            if progress_msg:
                await bot.edit_message_text(
                    f" {label} — محاولة {attempt}/{AI_FIX_MAX_ATTEMPTS}: يعدّل الكود...",
                    chat_id=chat_id, message_id=progress_msg.message_id,
                )
        except Exception:
            pass

        ok, raw_reply = await ask_ai_chat(
            [{"role": "user", "content": prompt_content}], fix_system_prompt, user_id=user_id,
        )
        await _bump_ai_model_usage_stat(model_key, bot_id, user_id)

        if not ok:
            await bot.send_message(
                chat_id,
                f" تعذر التواصل مع {label} حالياً.\n{sanitize_html_for_telegram(str(raw_reply), max_len=500)}",
            )
            return

        ai_code = extract_ai_code_block(raw_reply)
        if not ai_code:
            await _safe_bot_send(
                chat_id,
                f" {label} رد بدون كود قابل للتطبيق مباشرة:\n\n{format_ai_reply_for_telegram(raw_reply)}",
            )
            return

        try:
            if progress_msg:
                await bot.edit_message_text(
                    f" محاولة {attempt}/{AI_FIX_MAX_ATTEMPTS}: نجرّب تشغيل النسخة المعدَّلة فعلياً على السيرفر...",
                    chat_id=chat_id, message_id=progress_msg.message_id,
                )
        except Exception:
            pass

        run_ok, run_log = await try_run_candidate_code(bot_id, bot_data, ai_code)

        if run_ok:
            apply_ok, apply_msg = await apply_ai_code_to_bot_file(bot_id, ai_code)
            if not apply_ok:
                await bot.send_message(chat_id, apply_msg)
                return
            try:
                await notify_admin_ai_file_edit(bot_id, user_id, model_key, target_file.name)
            except Exception:
                pass
            try:
                await _bump_ai_model_usage_stat(model_key, bot_id, user_id, edit_applied=True)
            except Exception:
                pass
            final_text = " تم! البوت يعمل الآن بشكل صحيح."
            try:
                if progress_msg:
                    await bot.edit_message_text(final_text, chat_id=chat_id, message_id=progress_msg.message_id)
                else:
                    await bot.send_message(chat_id, final_text)
            except Exception:
                await bot.send_message(chat_id, final_text)
            return

        # فشلت التجربة — نجهّز للمحاولة التالية بسجل التشغيل الفعلي الجديد
        current_code = ai_code
        current_error_log = run_log or "توقف الملف فور التشغيل بدون أي سجل."

    # استُنفدت كل المحاولات دون الوصول لنسخة شغّالة
    await bot.send_message(
        chat_id,
        f" حاول {label} تصحيح البوت {AI_FIX_MAX_ATTEMPTS} مرات متتالية، لكن لم "
        "نصل لنسخة تعمل فعلياً. لم يُعدَّل الملف الحقيقي (بقي كما كان). آخر سجل فشل:\n\n"
        f"<code>{sanitize_html_for_telegram(current_error_log[-800:], max_len=800)}</code>",
    )


@dp.message_handler(state=AskAIState.waiting_question, content_types=types.ContentType.ANY)
async def msg_ai_question(message: types.Message, state: FSMContext):
    """ملاحظة استقرار مهمة: كامل جسم هذه الدالة مغلَّف بـtry/except خارجي (أسفل)
    لضمان أن أي خطأ غير متوقع (شبكة، تحليل رد AI، إلخ) لا يترك المستخدم عالقاً
    بحالة AskAIState.waiting_question بدون طريقة للخروج — وهو السبب الشائع الذي
    يبدو معه "توقف البوت كله" رغم أن باقي البوت يعمل بشكل طبيعي فعلياً."""
    try:
        await _msg_ai_question_inner(message, state)
    except Exception as e:
        logger.error(f"msg_ai_question: خطأ غير متوقع، يُنهى الـstate بأمان: {e}", exc_info=True)
        try:
            await state.finish()
        except Exception:
            pass
        try:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="القائمة الرئيسية ◆", callback_data="main_menu")],
            ])
            await message.answer(
                " صار خطأ غير متوقع أثناء معالجة سؤالك للذكاء الاصطناعي.\n"
                "تم إنهاء الجلسة الحالية بأمان — جرّب تفتح 'اسأل EYRX-AI' من جديد.",
                reply_markup=kb,
            )
        except Exception:
            pass


async def _msg_ai_question_inner(message: types.Message, state: FSMContext):
    data = await state.get_data()
    bot_id = data.get("ai_bot_id")
    bot_data = await get_bot_by_id(bot_id) if bot_id else None
    if not bot_data or bot_data["user_id"] != message.from_user.id:
        await message.answer(" حدث خطأ، ابدأ العملية من جديد.")
        await state.finish()
        return

    wallet = await get_ai_wallet(message.from_user.id)
    using_wallet = wallet["ai_questions_balance"] > 0

    if not using_wallet:
        can_ask, remaining_minutes = await can_user_ask_ai(message.from_user.id, bot_id)
        if not can_ask:
            hours = remaining_minutes // 60
            minutes = remaining_minutes % 60
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="شحن AI ", callback_data="ai_charge_menu", style="success")],
            ])
            await message.answer(
                f" استهلكت حد الأسئلة المسموح ({AI_QUESTIONS_LIMIT} سؤال). "
                f"يفتح مجدداً بعد {hours} ساعة و{minutes} دقيقة تقريباً.",
                reply_markup=kb,
            )
            await state.finish()
            return

    # ── مرفقات: مسموحة فقط لأصحاب صلاحية "إرسال ملفات" (الباقة الثالثة)
    user_question = message.text or message.caption or ""
    attachment_note = ""
    if message.content_type != types.ContentType.TEXT:
        if not wallet["can_send_files"]:
            await message.answer(
                " إرسال الملفات للذكاء الاصطناعي متاح فقط مع باقة AI الذهبية (200 ).\n"
                "اكتب سؤالك كنص، أو اشحن الباقة المناسبة."
            )
            return
        try:
            file_id = None
            file_name = "attachment"
            if message.document:
                file_id = message.document.file_id
                file_name = message.document.file_name or file_name
            elif message.photo:
                file_id = message.photo[-1].file_id
                file_name = "photo.jpg"
            if file_id:
                tg_file = await bot.get_file(file_id)
                dest_dir = Path("ai_uploads")
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest_path = dest_dir / f"{message.from_user.id}_{uuid.uuid4().hex[:8]}_{file_name}"
                await bot.download_file(tg_file.file_path, destination=str(dest_path))
                try:
                    async with aiofiles.open(dest_path, mode='r', encoding='utf-8', errors='ignore') as f:
                        file_content = await f.read()
                    attachment_note = f"\n\nمحتوى الملف المرفق ({file_name}):\n```\n{file_content[:4000]}\n```"
                except Exception:
                    attachment_note = f"\n\n(تم رفع ملف {file_name} لكن لا يمكن قراءته كنص)"
        except Exception as e:
            logger.error(f"AI attachment handling failed: {e}", exc_info=True)
            attachment_note = "\n\n(تعذر معالجة الملف المرفق)"

    # ── قراءة الملفات/السجل: للباقة الثالثة فقط، مضافة كسياق تلقائي
    error_log = await get_bot_error_log(bot_id)  # السجل الأساسي متاح دائماً للتشخيص العام
    extra_context = ""
    if wallet["can_read_logs"]:
        full_log = await get_bot_full_log(bot_id)
        extra_context += f"\n\nسجل التشغيل الكامل (آخر جزء، متاح بصلاحيتك):\n```\n{full_log[:3000]}\n```"

    if wallet["can_read_files"]:
        try:
            target_file = resolve_bot_target_file(bot_data)
            if target_file.exists():
                async with aiofiles.open(target_file, mode='r', encoding='utf-8', errors='ignore') as f:
                    file_content = await f.read()
                extra_context += f"\n\nمحتوى ملف البوت ({target_file.name}):\n```\n{file_content[:4000]}\n```"
        except Exception as e:
            logger.error(f"AI can_read_files context failed: {e}", exc_info=True)

    system_prompt = EYRX_AI_DIAGNOSTIC_SYSTEM_PROMPT
    if wallet["can_edit_files"]:
        system_prompt = (
            EYRX_AI_DIAGNOSTIC_SYSTEM_PROMPT
            + " هذا المستخدم لديه صلاحية تعديل مباشر وفوري على ملف بوته. إذا كان السؤال يتطلب "
              "إصلاح خطأ، تصحيح أسطر فيها مشكلة، أو إضافة أي شيء يطلبه المستخدم للملف: أعد كتابة "
              "الملف بالكامل بعد التعديل (كل الأسطر، مو فقط الجزء المعدَّل) داخل code block واحد فقط "
              "(```python ... ```)، لأن هذا الرد بالذات سيُطبَّق تلقائياً وحرفياً على الملف الحقيقي "
              "فور ضغط المستخدم زر 'تطبيق التعديل على الملف'. لا تضع أي نص أو شرح داخل ذلك الـ code "
              "block نفسه، واشرح ما فعلته خارج الـ code block."
        )

    ok, raw_reply = await _run_ai_with_thinking_indicator(
        message.chat.id,
        [{"role": "user", "content": f"سجل الخطأ:\n```\n{error_log[:3000]}\n```\n\nسؤال المستخدم: {user_question}{extra_context}{attachment_note}"}],
        system_prompt,
        user_id=message.from_user.id,
    )
    if ok:
        reply = raw_reply
    else:
        logger.error(f"msg_ai_question failed: {raw_reply}")
        reply = " تعذر التواصل مع الذكاء الاصطناعي حالياً. حاول لاحقاً، أو تواصل مع الأدمن إذا استمرت المشكلة."

    if using_wallet:
        await consume_ai_wallet_question(message.from_user.id)
        wallet = await get_ai_wallet(message.from_user.id)
        questions_left = wallet["ai_questions_balance"]
        footer = f"\n\n━━━━━━━━━━━━━━━━━━━\n رصيدك المتبقي: {questions_left} سؤال"
    else:
        await record_ai_question_used(message.from_user.id, bot_id)
        usage = await get_ai_usage(message.from_user.id, bot_id)
        questions_left = max(0, AI_QUESTIONS_LIMIT - usage["questions_used"]) if usage else AI_QUESTIONS_LIMIT
        footer = f"\n\n━━━━━━━━━━━━━━━━━━━\n الأسئلة المتبقية: {questions_left}/{AI_QUESTIONS_LIMIT}"
        if questions_left <= 0:
            footer += f"\n سيُقفل السؤال لهذا البوت لمدة {AI_COOLDOWN_HOURS} ساعات."

    # ── تعديل مباشر على الملف / إرسال الرد كملف: فقط لأصحاب باقة AI الذهبية (200 )
    ai_code = extract_ai_code_block(raw_reply) if ok else None
    action_row = []
    if ok and ai_code and wallet["can_edit_files"]:
        await state.update_data(ai_pending_code=ai_code, ai_pending_bot_id=bot_id)
        action_row.append(InlineKeyboardButton(text="تطبيق التعديل على الملف ", callback_data=f"ai_apply_edit_{bot_id}", style="success"))
    if ok and wallet["can_send_files"]:
        await state.update_data(ai_last_reply_text=raw_reply)
        action_row.append(InlineKeyboardButton(text="إرسال الرد كملف ⇡", callback_data="ai_send_reply_file", style="primary"))

    kb_rows = []
    if action_row:
        kb_rows.append(action_row)
    kb_rows.append([InlineKeyboardButton(text="شحن AI ", callback_data="ai_charge_menu", style="success")])
    kb_rows.append([InlineKeyboardButton(text="رجوع", callback_data=f"select_bot_{bot_id}", style="danger")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    await message.answer(f" {format_ai_reply_for_telegram(reply)}{html_module.escape(footer)}", reply_markup=kb)

    if questions_left > 0:
        await AskAIState.waiting_question.set()
    else:
        await state.finish()


# ─────────────────────────────────────────────
# USER BOT DELETE HANDLER
# ─────────────────────────────────────────────
@dp.callback_query_handler(text_startswith="user_bot_delete_", state='*')
async def cb_user_bot_delete(callback: types.CallbackQuery, state: FSMContext):
    """يعرض شاشة تأكيد قبل حذف البوت (بدل الحذف الفوري)."""
    await state.finish()
    await safe_answer_callback(callback)
    bot_id = int(callback.data.split('_')[3])
    bot_data = await get_bot_by_id(bot_id)
    if not bot_data or bot_data["user_id"] != callback.from_user.id:
        await safe_answer_callback(callback, " البوت غير موجود.", show_alert=True)
        return
    lang = await get_user_language(callback.from_user.id) or "ar"
    text = f"{t('confirm_delete_title', lang)}\n\n{t('confirm_delete_bot_body', lang)}\n\n {bot_data['file_name']}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=t('confirm_yes_delete', lang), callback_data=f"botdeldo_{bot_id}", style="danger"),
            InlineKeyboardButton(text=t('confirm_no_cancel', lang), callback_data=f"select_bot_{bot_id}", style="success"),
        ],
    ])
    await edit_or_send_message(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)


@dp.callback_query_handler(text_startswith="botdeldo_", state='*')
async def cb_user_bot_delete_do(callback: types.CallbackQuery, state: FSMContext):
    """التنفيذ الفعلي للحذف بعد ضغط زر التأكيد فقط."""
    await state.finish()
    await safe_answer_callback(callback)
    bot_id = int(callback.data.split('_')[1])
    bot_data = await get_bot_by_id(bot_id)
    if not bot_data or bot_data["user_id"] != callback.from_user.id:
        await safe_answer_callback(callback, " البوت غير موجود.", show_alert=True)
        return
    await stop_bot_process(bot_id)
    file_path = Path(bot_data["file_path"])
    if file_path.exists():
        try:
            os.remove(file_path)
        except Exception:
            pass
    async with db_cursor() as conn:
        conn.execute("DELETE FROM bots WHERE id = ? AND user_id = ?", (bot_id, callback.from_user.id))
    await safe_answer_callback(callback, "تم الحذف.", show_alert=True)
    await cb_my_bots(callback, state)


@dp.callback_query_handler(text_startswith="user_site_download_", state='*')
async def cb_user_site_download(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    site_id = int(callback.data.split('_')[3])
    site_data = await get_site_by_id(site_id)
    lang = await get_user_language(callback.from_user.id) or "ar"
    if not site_data or site_data["user_id"] != callback.from_user.id:
        await safe_answer_callback(callback, t('site_not_found', lang), show_alert=True)
        return
    file_path = Path(site_data["file_path"])
    if not file_path.exists():
        await safe_answer_callback(callback, " الملف غير موجود.", show_alert=True)
        return
    try:
        await bot.send_document(callback.from_user.id, InputFile(str(file_path)))
        await safe_answer_callback(callback, " تم إرسال الملف.", show_alert=True)
    except Exception as e:
        logger.error(f"Error sending site file: {e}", exc_info=True)
        await safe_answer_callback(callback, " حدث خطأ.", show_alert=True)


@dp.callback_query_handler(text_startswith="user_site_delete_confirm_", state='*')
async def cb_user_site_delete_confirm(callback: types.CallbackQuery, state: FSMContext):
    """يعرض شاشة تأكيد قبل حذف الموقع، مع خيار إضافي لحذف كل مواقع المستخدم دفعة واحدة."""
    await state.finish()
    await safe_answer_callback(callback)
    site_id = int(callback.data.split('_')[4])
    site_data = await get_site_by_id(site_id)
    lang = await get_user_language(callback.from_user.id) or "ar"
    if not site_data or site_data["user_id"] != callback.from_user.id:
        await safe_answer_callback(callback, t('site_not_found', lang), show_alert=True)
        return
    text = f"{t('confirm_delete_title', lang)}\n\n{t('confirm_delete_site_body', lang)}\n\n {sanitize_html_for_telegram(site_data['file_name'], max_len=150)}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="مسح هذا الموقع فقط ", callback_data=f"user_site_delete_do_{site_id}", style="danger"),
        ],
        [
            InlineKeyboardButton(text="مسح جميع مواقعي ", callback_data="user_site_delete_all_confirm", style="danger"),
        ],
        [
            InlineKeyboardButton(text=t('confirm_no_cancel', lang), callback_data="my_sites", style="success"),
        ],
    ])
    await edit_or_send_message(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)


@dp.callback_query_handler(text="user_site_delete_all_confirm", state='*')
async def cb_user_site_delete_all_confirm(callback: types.CallbackQuery, state: FSMContext):
    """شاشة تأكيد إضافية (تأكيد على التأكيد) قبل حذف كل مواقع المستخدم، لتفادي حذف
    جماعي بضغطة عرضية واحدة."""
    await state.finish()
    await safe_answer_callback(callback)
    lang = await get_user_language(callback.from_user.id) or "ar"
    sites = await get_user_sites(callback.from_user.id)
    text = (
        f" تأكيد نهائي \n\n"
        f"سيتم حذف <b>{len(sites)}</b> موقع نهائياً من حسابك. هذا الإجراء لا يمكن التراجع عنه.\n\n"
        f"هل أنت متأكد فعلاً؟"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="نعم، امسح الكل نهائياً ", callback_data="user_site_delete_all_do", style="danger")],
        [InlineKeyboardButton(text=t('confirm_no_cancel', lang), callback_data="my_sites", style="success")],
    ])
    await edit_or_send_message(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)


@dp.callback_query_handler(text="user_site_delete_all_do", state='*')
async def cb_user_site_delete_all_do(callback: types.CallbackQuery, state: FSMContext):
    """التنفيذ الفعلي لحذف كل مواقع المستخدم دفعة واحدة."""
    await state.finish()
    await safe_answer_callback(callback)
    lang = await get_user_language(callback.from_user.id) or "ar"
    sites = await get_user_sites(callback.from_user.id)
    deleted_count = 0
    for site_data in sites:
        try:
            file_path = Path(site_data["file_path"])
            if file_path.exists():
                os.remove(file_path)
        except Exception as e:
            logger.warning(f"cb_user_site_delete_all_do: failed to remove file for site {site_data['id']}: {e}")
        deleted_count += 1
    async with db_cursor() as conn:
        conn.execute("DELETE FROM sites WHERE user_id = ?", (callback.from_user.id,))
    await safe_answer_callback(callback, f" تم حذف {deleted_count} موقع.", show_alert=True)
    await cb_my_sites(callback, state)


@dp.callback_query_handler(text_startswith="user_site_delete_do_", state='*')
async def cb_user_site_delete_do(callback: types.CallbackQuery, state: FSMContext):
    """التنفيذ الفعلي لحذف الموقع بعد التأكيد."""
    await state.finish()
    await safe_answer_callback(callback)
    site_id = int(callback.data.split('_')[4])
    site_data = await get_site_by_id(site_id)
    lang = await get_user_language(callback.from_user.id) or "ar"
    if not site_data or site_data["user_id"] != callback.from_user.id:
        await safe_answer_callback(callback, t('site_not_found', lang), show_alert=True)
        return
    file_path = Path(site_data["file_path"])
    if file_path.exists():
        try:
            os.remove(file_path)
        except Exception:
            pass
    async with db_cursor() as conn:
        conn.execute("DELETE FROM sites WHERE id = ? AND user_id = ?", (site_id, callback.from_user.id))
    await safe_answer_callback(callback, t('site_deleted', lang), show_alert=True)
    await cb_my_sites(callback, state)


# ─────────────────────────────────────────────
# VIP FEATURES: INSTALL LIBRARIES
# ─────────────────────────────────────────────
@dp.callback_query_handler(text_startswith="vip_install_libs_", state='*')
async def cb_vip_install_libs(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    user_id = callback.from_user.id
    if not await is_vip_user(user_id):
        await safe_answer_callback(callback, " هذه الميزة متاحة فقط لأعضاء VIP. ادعو 6 أشخاص للحصول على VIP.", show_alert=True)
        return
    bot_id, is_admin_view = parse_vip_callback(callback.data)
    if is_admin_view is None:
        is_admin_view = await is_admin(user_id)
    await state.update_data(edit_bot_id=bot_id, vip_admin_view=is_admin_view)
    text = "━━━━━━━━━━━━━━━━━━━\n◆ تثبيت مكاتب ◆\n━━━━━━━━━━━━━━━━━━━\n\nأرسل اسم المكتبة التي تريد تثبيتها:\n(مثال: aiogram, requests, bs4)"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=deco("back", "رجوع"), callback_data=vip_back_target(bot_id, is_admin_view), style="danger")]
    ])
    await delete_and_send(callback.message.chat.id, user_id, text, kb, callback.message.message_id)
    await VipInstallLibsState.waiting_lib_name.set()


@dp.message_handler(state=VipInstallLibsState.waiting_lib_name)
async def msg_vip_install_libs(message: types.Message, state: FSMContext):
    if not await is_vip_user(message.from_user.id):
        await state.finish()
        return
    lib_name = message.text.strip()
    data = await state.get_data()
    bot_id = data.get("edit_bot_id")
    is_admin_view = data.get("vip_admin_view", False)
    try:
        await message.delete()
    except Exception:
        pass
    await message.answer(f" جاري تثبيت: {lib_name}...")
    success, output, error = await safe_execute_terminal(f"pip install {lib_name}", timeout=120)
    if success:
        text = f" تم تثبيت {lib_name} بنجاح\n\n<pre>{sanitize_html_for_telegram(output[:2000])}</pre>"
    else:
        text = f" فشل تثبيت {lib_name}\n\n<pre>{sanitize_html_for_telegram(error[:2000])}</pre>"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=deco("back", "رجوع"), callback_data=vip_back_target(bot_id, is_admin_view), style="danger")]
    ])
    await message.answer(text, reply_markup=kb)
    await state.finish()


# ─────────────────────────────────────────────
# VIP FEATURES: EDIT CODE
# ─────────────────────────────────────────────
@dp.callback_query_handler(text_startswith="vip_edit_code_", state='*')
async def cb_vip_edit_code(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    user_id = callback.from_user.id
    if not await is_vip_user(user_id):
        await safe_answer_callback(callback, " هذه الميزة متاحة فقط لأعضاء VIP. ادعو 6 أشخاص للحصول على VIP.", show_alert=True)
        return
    bot_id = int(callback.data.split("_")[3])
    bot_data = await get_bot_by_id(bot_id)
    if not bot_data:
        return
    await state.update_data(edit_bot_id=bot_id)
    text = (
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"◆ تعديل الكود ◆\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"أرسل الكود الجديد كاملاً وسيتم استبدال ملف البوت.\n"
        f"الملف: <code>{bot_data['file_name']}</code>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="رجوع", callback_data=f"select_bot_{bot_id}", style="danger")]
    ])
    await delete_and_send(callback.message.chat.id, user_id, text, kb, callback.message.message_id)
    await VipEditCodeState.waiting_code.set()


@dp.message_handler(state=VipEditCodeState.waiting_code)
async def msg_vip_edit_code(message: types.Message, state: FSMContext):
    if not await is_vip_user(message.from_user.id):
        await state.finish()
        return
    data = await state.get_data()
    bot_id = data.get("edit_bot_id")
    bot_data = await get_bot_by_id(bot_id)
    if not bot_data:
        await message.answer(" البوت غير موجود.")
        await state.finish()
        return
    try:
        await message.delete()
    except Exception:
        pass
    new_code = message.text
    file_path = Path(bot_data["file_path"])
    try:
        metadata_block = generate_pixel_encoding_block(
            bot_data["user_id"], bot_id,
            "javascript" if file_path.suffix.lower() == ".js" else "python_bot"
        )
        async with aiofiles.open(file_path, mode='w', encoding='utf-8') as f:
            await f.write(metadata_block + new_code)
        restart_result = await restart_bot_if_running(bot_id, bot_data["file_path"])
        text = " تم تعديل الكود بنجاح."
        if restart_result is not None:
            started, reason = restart_result
            text += f"\nإعادة التشغيل: {' نجح' if started else ' فشل - ' + reason}"
    except Exception as e:
        text = f" خطأ: {e}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="رجوع", callback_data=f"select_bot_{bot_id}", style="danger")]
    ])
    await message.answer(text, reply_markup=kb)
    await state.finish()


# ─────────────────────────────────────────────
# VIP FEATURES: EDIT FILE
# ─────────────────────────────────────────────
@dp.callback_query_handler(text_startswith="vip_edit_file_", state='*')
async def cb_vip_edit_file(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    user_id = callback.from_user.id
    if not await is_vip_user(user_id):
        await safe_answer_callback(callback, " هذه الميزة متاحة فقط لأعضاء VIP. ادعو 6 أشخاص للحصول على VIP.", show_alert=True)
        return
    bot_id, is_admin_view = parse_vip_callback(callback.data)
    if is_admin_view is None:
        is_admin_view = await is_admin(user_id)
    await state.update_data(edit_bot_id=bot_id, vip_admin_view=is_admin_view)
    text = (
        "━━━━━━━━━━━━━━━━━━━\n"
        "◆ تعديل الملف ◆\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        "أرسل ملف .py أو .php أو .js جديد وسيتم استبدال الملف الحالي."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=deco("back", "رجوع"), callback_data=vip_back_target(bot_id, is_admin_view), style="danger")]
    ])
    await delete_and_send(callback.message.chat.id, user_id, text, kb, callback.message.message_id)
    await VipEditFileState.waiting_file.set()


@dp.message_handler(content_types=types.ContentType.DOCUMENT, state=VipEditFileState.waiting_file)
async def msg_vip_edit_file(message: types.Message, state: FSMContext):
    if not await is_vip_user(message.from_user.id):
        await state.finish()
        return
    data = await state.get_data()
    bot_id = data.get("edit_bot_id")
    is_admin_view = data.get("vip_admin_view", False)
    bot_data = await get_bot_by_id(bot_id)
    if not bot_data:
        await message.answer(" البوت غير موجود.")
        await state.finish()
        return
    doc = message.document
    if not doc.file_name.endswith((".py", ".php", ".js")):
        await message.answer(" الملف يجب أن يكون بصيغة .py أو .php أو .js")
        return
    try:
        await message.delete()
    except Exception:
        pass
    file_info = await bot.get_file(doc.file_id)
    dest = Path(bot_data["file_path"])
    try:
        await bot.download_file(file_info.file_path, destination=dest)
        metadata_block = generate_pixel_encoding_block(
            bot_data["user_id"], bot_id,
            "javascript" if doc.file_name.endswith(".js") else "python_bot"
        )
        await prepend_metadata_to_file(dest, metadata_block)
        restart_result = await restart_bot_if_running(bot_id, bot_data["file_path"])
        text = f" تم استبدال الملف بـ {sanitize_html_for_telegram(doc.file_name, max_len=200)} بنجاح."
        if restart_result is not None:
            started, reason = restart_result
            text += f"\nإعادة التشغيل: {' نجح' if started else ' فشل - ' + reason}"
    except Exception as e:
        text = f" خطأ: {e}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=deco("back", "رجوع"), callback_data=vip_back_target(bot_id, is_admin_view), style="danger")]
    ])
    await message.answer(text, reply_markup=kb)
    await state.finish()


# ─────────────────────────────────────────────
# USER FEATURE: FIND & REPLACE (تحرير)
# ─────────────────────────────────────────────
@dp.callback_query_handler(text_startswith="user_bot_findreplace_", state='*')
async def cb_user_bot_findreplace(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    user_id = callback.from_user.id
    bot_id = int(callback.data.split("_")[3])
    bot_data = await get_bot_by_id(bot_id)
    if not bot_data or bot_data["user_id"] != user_id:
        await safe_answer_callback(callback, " البوت غير موجود.", show_alert=True)
        return
    await state.update_data(fr_bot_id=bot_id)
    text = (
        "━━━━━━━━━━━━━━━━━━━\n"
        "◆ تحرير (استبدال نص) ◆\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        "أرسل الآن النص المراد استبداله (النص القديم) كما هو تماماً بالملف."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="رجوع", callback_data=f"select_bot_{bot_id}", style="danger")]
    ])
    await delete_and_send(callback.message.chat.id, user_id, text, kb, callback.message.message_id)
    await UserFindReplaceState.waiting_old_text.set()


@dp.message_handler(content_types=types.ContentType.TEXT, state=UserFindReplaceState.waiting_old_text)
async def msg_user_findreplace_old(message: types.Message, state: FSMContext):
    data = await state.get_data()
    bot_id = data.get("fr_bot_id")
    bot_data = await get_bot_by_id(bot_id)
    if not bot_data or bot_data["user_id"] != message.from_user.id:
        await message.answer(" البوت غير موجود.")
        await state.finish()
        return

    old_text = message.text
    file_path = Path(bot_data["file_path"])
    try:
        async with aiofiles.open(file_path, mode='r', encoding='utf-8') as f:
            content = await f.read()
    except Exception as e:
        await message.answer(f" تعذّر قراءة الملف: {e}")
        await state.finish()
        return

    if old_text not in content:
        await message.answer(
            " لم يتم العثور على هذا النص بالملف. تأكد من كتابته بنفس الصيغة تماماً وحاول مرة أخرى، "
            "أو اضغط رجوع للإلغاء.",
        )
        return

    await state.update_data(fr_old_text=old_text)
    await message.answer(" تم العثور على النص.\nالآن أرسل النص الجديد الذي سيحل محله.")
    await UserFindReplaceState.waiting_new_text.set()


@dp.message_handler(content_types=types.ContentType.TEXT, state=UserFindReplaceState.waiting_new_text)
async def msg_user_findreplace_new(message: types.Message, state: FSMContext):
    data = await state.get_data()
    bot_id = data.get("fr_bot_id")
    old_text = data.get("fr_old_text")
    bot_data = await get_bot_by_id(bot_id)
    if not bot_data or bot_data["user_id"] != message.from_user.id or old_text is None:
        await message.answer(" حدث خطأ، ابدأ العملية من جديد.")
        await state.finish()
        return

    new_text = message.text
    file_path = Path(bot_data["file_path"])
    try:
        async with aiofiles.open(file_path, mode='r', encoding='utf-8') as f:
            content = await f.read()

        if old_text not in content:
            await message.answer(" لم يعد النص القديم موجوداً بالملف (ربما تغيّر الملف بالأثناء). تم إلغاء العملية.")
            await state.finish()
            return

        occurrences = content.count(old_text)
        new_content = content.replace(old_text, new_text)

        async with aiofiles.open(file_path, mode='w', encoding='utf-8') as f:
            await f.write(new_content)

        restart_result = await restart_bot_if_running(bot_id, bot_data["file_path"])
        text = f" تم الاستبدال بنجاح ({occurrences} مرة/مرات)."
        if restart_result is not None:
            started, reason = restart_result
            text += f"\nإعادة التشغيل: {' نجح' if started else ' فشل - ' + reason}"
    except Exception as e:
        text = f" خطأ: {e}"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="رجوع", callback_data=f"select_bot_{bot_id}", style="danger")]
    ])
    await message.answer(text, reply_markup=kb)
    await state.finish()



@dp.callback_query_handler(text_startswith="vip_bot_stats_", state='*')
async def cb_vip_bot_stats(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    user_id = callback.from_user.id
    if not await is_vip_user(user_id):
        await safe_answer_callback(callback, " هذه الميزة متاحة فقط لأعضاء VIP.", show_alert=True)
        return
    bot_id, is_admin_view = parse_vip_callback(callback.data)
    if is_admin_view is None:
        is_admin_view = await is_admin(user_id)
    bot_data = await get_bot_by_id(bot_id)
    if not bot_data:
        return
    proc = RUNNING_BOT_PROCESSES.get(bot_id)
    info = "متوقف"
    mem = "N/A"
    if proc and proc.returncode is None:
        try:
            import time
            p = None
            mem_mb = p.memory_info().rss / (1024 * 1024)
            mem = f"{mem_mb:.2f} MB"
            info = "يعمل"
        except Exception:
            info = "يعمل (لا يمكن قراءة البيانات)"
    text = (
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"◆ إحصائيات البوت ◆\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"الملف: <code>{bot_data['file_name']}</code>\n"
        f"الحالة: {info}\n"
        f"استهلاك الذاكرة: {mem}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=deco("back", "رجوع"), callback_data=vip_back_target(bot_id, is_admin_view), style="danger")]
    ])
    await delete_and_send(callback.message.chat.id, user_id, text, kb, callback.message.message_id)


# ─────────────────────────────────────────────
# VIP FEATURES: SHARE BOT
# ─────────────────────────────────────────────
@dp.callback_query_handler(text_startswith="vip_share_bot_", state='*')
async def cb_vip_share_bot(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    user_id = callback.from_user.id
    if not await is_vip_user(user_id):
        await safe_answer_callback(callback, " هذه الميزة متاحة فقط لأعضاء VIP.", show_alert=True)
        return
    bot_id, is_admin_view = parse_vip_callback(callback.data)
    if is_admin_view is None:
        is_admin_view = await is_admin(user_id)
    await state.update_data(share_bot_id=bot_id, vip_admin_view=is_admin_view)
    text = "━━━━━━━━━━━━━━━━━━━\n◆ مشاركة البوت ◆\n━━━━━━━━━━━━━━━━━━━\n\nأرسل ايدي المستخدم الذي تريد إرسال الملف إليه:"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=deco("back", "رجوع"), callback_data=vip_back_target(bot_id, is_admin_view), style="danger")]
    ])
    await delete_and_send(callback.message.chat.id, user_id, text, kb, callback.message.message_id)
    await VipShareBotState.waiting_target_user.set()


@dp.message_handler(state=VipShareBotState.waiting_target_user)
async def msg_vip_share_bot(message: types.Message, state: FSMContext):
    if not await is_vip_user(message.from_user.id):
        await state.finish()
        return
    try:
        target_id = int(message.text.strip())
    except ValueError:
        await message.answer(" ايدي غير صالح.")
        return
    data = await state.get_data()
    bot_id = data.get("share_bot_id")
    is_admin_view = data.get("vip_admin_view", False)
    bot_data = await get_bot_by_id(bot_id)
    if not bot_data:
        await message.answer(" البوت غير موجود.")
        await state.finish()
        return
    try:
        await message.delete()
    except Exception:
        pass
    file_path = Path(bot_data["file_path"])
    if not file_path.exists():
        await message.answer(" الملف غير موجود.")
        await state.finish()
        return
    try:
        original_content = await remove_metadata_from_file(file_path)
        temp_file = file_path.parent / f"temp_share_{file_path.name}"
        async with aiofiles.open(temp_file, mode='w') as f:
            await f.write(original_content)
        await bot.send_document(target_id, InputFile(str(temp_file)), caption=f"ملف من EYRX Hosting\nالملف: {bot_data['file_name']}")
        os.remove(temp_file)
        text = f" تم إرسال الملف إلى {target_id}"
    except Exception as e:
        text = f" فشل الإرسال: {e}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=deco("back", "رجوع"), callback_data=vip_back_target(bot_id, is_admin_view), style="danger")]
    ])
    await message.answer(text, reply_markup=kb)
    await state.finish()


# ─────────────────────────────────────────────
# ADMIN: MAINTENANCE MODE
# ─────────────────────────────────────────────
@dp.callback_query_handler(text='admin_maintenance', state='*')
async def cb_admin_maintenance(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    current = await get_config_value("maintenance_mode")
    is_on = current == "1"
    status_text = "مفعّل" if is_on else "معطّل"
    text = (
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"◆ وضع الصيانة ◆\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"الحالة الحالية: <b>{status_text}</b>\n\n"
        f"عند تفعيل الصيانة، لا يستطيع المستخدمون العاديون استخدام البوت."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="تفعيل الصيانة" if not is_on else "إيقاف الصيانة", callback_data="toggle_maintenance", style="danger" if not is_on else "success")],
        [InlineKeyboardButton(text="رجوع", callback_data="admin_panel", style="danger")]
    ])
    await delete_and_send(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)


@dp.callback_query_handler(text='toggle_maintenance', state='*')
async def cb_toggle_maintenance(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        return
    current = await get_config_value("maintenance_mode")
    new_val = "0" if current == "1" else "1"
    await set_config_value("maintenance_mode", new_val)
    status = "مفعّل" if new_val == "1" else "معطّل"
    text = f" تم {'تفعيل' if new_val == '1' else 'إيقاف'} وضع الصيانة.\n\nالحالة: <b>{status}</b>"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="رجوع", callback_data="admin_panel", style="danger")]
    ])
    await delete_and_send(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)


# ─────────────────────────────────────────────
# ADMIN: DB BACKUP
# ─────────────────────────────────────────────
@dp.callback_query_handler(text='admin_db_backup', state='*')
async def cb_admin_db_backup(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback, " جاري إنشاء النسخة الاحتياطية...", show_alert=False)
    if not await is_admin(callback.from_user.id):
        return
    try:
        from datetime import datetime as dt
        timestamp = dt.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"backup_{timestamp}.db"
        import shutil
        shutil.copy2(DB_PATH, backup_path)
        await bot.send_document(callback.from_user.id, InputFile(backup_path), caption=f"نسخة احتياطية: {timestamp}")
        os.remove(backup_path)
    except Exception as e:
        await bot.send_message(callback.from_user.id, f" فشل إنشاء النسخة: {e}")


# ─────────────────────────────────────────────
# ADMIN: SEARCH USER BY ID
# ─────────────────────────────────────────────
@dp.callback_query_handler(text='admin_search_user', state='*')
async def cb_admin_search_user(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        return
    await callback.message.answer("━━━━━━━━━━━━━━━━━━━\n◆ بحث بالايدي ◆\n━━━━━━━━━━━━━━━━━━━\n\nأرسل ايدي المستخدم:")
    await AdminSearchUserState.waiting_user_id.set()


@dp.message_handler(state=AdminSearchUserState.waiting_user_id)
async def msg_admin_search_user(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await state.finish()
        return
    try:
        uid = int(message.text.strip())
    except ValueError:
        await message.answer(" ايدي غير صالح.")
        return
    try:
        await message.delete()
    except Exception:
        pass
    user = await get_user(uid)
    if not user:
        await message.answer(f" المستخدم {uid} غير موجود.")
        await state.finish()
        return
    tier_label = UPGRADE_TIERS.get(user["upgrade_tier"] or "none", UPGRADE_TIERS["none"])["label"]
    text = (
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"◆ معلومات المستخدم ◆\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"الايدي: <code>{user['user_id']}</code>\n"
        f"اليوزر: @{user['username'] or 'N/A'}\n"
        f"الاسم: {user['first_name'] or 'N/A'}\n"
        f"النقاط: <b>{user['points']}</b>\n"
        f"الإحالات: <b>{user['referrals_count']}</b>\n"
        f"VIP: {'نعم' if user['is_vip'] else 'لا'}\n"
        f"الأدمن: {'نعم' if user['is_admin'] else 'لا'}\n"
        f"مالك: {'نعم' if user['is_owner'] else 'لا'}\n"
        f"محظور: {'نعم' if user['is_banned'] else 'لا'}\n"
        f"الترقية: {tier_label}\n"
        f"تاريخ التسجيل: {user['created_at']}\n"
        f"آخر نشاط: {user['last_active']}"
    )
    await message.answer(text, reply_markup=admin_back_keyboard())
    await state.finish()


# ─────────────────────────────────────────────
# ADMIN: LIVE MONITOR
# ─────────────────────────────────────────────
@dp.callback_query_handler(text='admin_live_monitor', state='*')
async def cb_admin_live_monitor(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        return
    text_lines = ["━━━━━━━━━━━━━━━━━━━\n◆ المراقبة المباشرة ◆\n━━━━━━━━━━━━━━━━━━━\n"]
    running_count = 0
    for bot_id, proc in RUNNING_BOT_PROCESSES.items():
        if proc.returncode is None:
            running_count += 1
            try:
                p = None
                mem = p.memory_info().rss / (1024 * 1024)
                cpu = p.cpu_percent()
                bot_data = await get_bot_by_id(bot_id)
                name = bot_data["file_name"] if bot_data else "Unknown"
                text_lines.append(f"\n◆ البوت #{bot_id}: <code>{name}</code>")
                text_lines.append(f" PID: {proc.pid} | RAM: {mem:.2f}MB | CPU: {cpu:.1f}%")
            except Exception:
                text_lines.append(f"\n◆ البوت #{bot_id}: يعمل (لا يمكن قراءة البيانات)")
    if running_count == 0:
        text_lines.append("\nلا توجد بوتات تعمل حالياً.")
    text = "".join(text_lines)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="تحديث", callback_data="admin_live_monitor", style="success")],
        [InlineKeyboardButton(text="رجوع", callback_data="admin_panel", style="danger")]
    ])
    await delete_and_send(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)


# ─────────────────────────────────────────────
# ADMIN: AUTO APPROVE
# ─────────────────────────────────────────────
@dp.callback_query_handler(text='admin_auto_approve', state='*')
async def cb_admin_auto_approve(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        return
    current = await get_config_value("auto_approve")
    is_on = current == "1"
    status_text = "مفعّل" if is_on else "معطّل"
    text = (
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"◆ القبول التلقائي ◆\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"الحالة: <b>{status_text}</b>\n\n"
        f"عند التفعيل، يتم قبول الملفات المرفوعة تلقائياً دون مراجعة."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="تفعيل" if not is_on else "إيقاف", callback_data="toggle_auto_approve", style="success" if not is_on else "danger")],
        [InlineKeyboardButton(text="رجوع", callback_data="admin_panel", style="danger")]
    ])
    await delete_and_send(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)


@dp.callback_query_handler(text='toggle_auto_approve', state='*')
async def cb_toggle_auto_approve(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        return
    current = await get_config_value("auto_approve")
    new_val = "0" if current == "1" else "1"
    await set_config_value("auto_approve", new_val)
    status = "مفعّل" if new_val == "1" else "معطّل"
    text = f" القبول التلقائي: <b>{status}</b>"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="رجوع", callback_data="admin_panel", style="danger")]
    ])
    await delete_and_send(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)


# ─────────────────────────────────────────────
# ADMIN: ADVANCED STATS
# ─────────────────────────────────────────────
@dp.callback_query_handler(text='admin_advanced_stats', state='*')
async def cb_admin_advanced_stats(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        return
    async with db_cursor() as conn:
        total = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
        today = conn.execute("SELECT COUNT(*) as c FROM users WHERE date(last_active) = date('now')").fetchone()["c"]
        banned = conn.execute("SELECT COUNT(*) as c FROM users WHERE is_banned = 1").fetchone()["c"]
        vip_count = conn.execute("SELECT COUNT(*) as c FROM users WHERE is_vip = 1").fetchone()["c"]
        total_refs = conn.execute("SELECT SUM(referrals_count) as c FROM users").fetchone()["c"] or 0
        total_bots = conn.execute("SELECT COUNT(*) as c FROM bots").fetchone()["c"]
        running_bots = conn.execute("SELECT COUNT(*) as c FROM bots WHERE status = 'running'").fetchone()["c"]
        pending = conn.execute("SELECT COUNT(*) as c FROM bots WHERE status = 'pending'").fetchone()["c"]
        total_sites = conn.execute("SELECT COUNT(*) as c FROM sites").fetchone()["c"]
        db_size = os.path.getsize(DB_PATH) / (1024 * 1024)
        try:
            uploads_size = sum(os.path.getsize(os.path.join(dp, f)) for dp, dn, filenames in os.walk("uploads") for f in filenames) / (1024 * 1024)
        except Exception:
            uploads_size = 0
    cpu = get_cpu_usage()
    ram = get_ram_usage()
    text = (
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"◆ إحصائيات متقدمة ◆\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"◆ المستخدمون:\n"
        f" الإجمالي: <b>{total}</b>\n"
        f" النشطون اليوم: <b>{today}</b>\n"
        f" المحظورون: <b>{banned}</b>\n"
        f" VIP: <b>{vip_count}</b>\n"
        f" إجمالي الدعوات: <b>{total_refs}</b>\n\n"
        f"◆ البوتات:\n"
        f" الإجمالي: <b>{total_bots}</b>\n"
        f" تعمل: <b>{running_bots}</b>\n"
        f" معلقة: <b>{pending}</b>\n\n"
        f"◆ المواقع: <b>{total_sites}</b>\n\n"
        f"◆ النظام:\n"
        f" CPU: <b>{cpu:.1f}%</b>\n"
        f"  RAM: <b>{ram['used']:.2f}GB / {ram['total']:.2f}GB</b>\n"
        f" حجم القاعدة: <b>{db_size:.2f}MB</b>\n"
        f" حجم الرفعات: <b>{uploads_size:.2f}MB</b>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="تحديث", callback_data="admin_advanced_stats", style="success")],
        [InlineKeyboardButton(text="رجوع", callback_data="admin_panel", style="danger")]
    ])
    await delete_and_send(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)


# ─────────────────────────────────────────────
# ADMIN: MASS BAN
# ─────────────────────────────────────────────
@dp.callback_query_handler(text='admin_mass_ban', state='*')
async def cb_admin_mass_ban(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        return
    text = "━━━━━━━━━━━━━━━━━━━\n◆ حظر جماعي ◆\n━━━━━━━━━━━━━━━━━━━\n\nأرسل الأيديات مفصولة بفواصل أو مسافات:"
    await callback.message.answer(text)
    await AdminMassBanState.waiting_user_ids.set()


@dp.message_handler(state=AdminMassBanState.waiting_user_ids)
async def msg_admin_mass_ban(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await state.finish()
        return
    try:
        await message.delete()
    except Exception:
        pass
    parts = re.split(r'[ ,\s]+', message.text.strip())
    banned = 0
    failed = 0
    for part in parts:
        try:
            uid = int(part)
            await ban_user(uid)
            banned += 1
        except Exception:
            failed += 1
    text = f" تم حظر <b>{banned}</b> مستخدم."
    if failed:
        text += f"\n فشل حظر <b>{failed}</b> أيدي."
    await message.answer(text, reply_markup=admin_back_keyboard())
    await state.finish()


# ─────────────────────────────────────────────
# ADMIN: FOLDER MANAGEMENT
# ─────────────────────────────────────────────
@dp.callback_query_handler(text='admin_folders', state='*')
async def cb_admin_folders(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        return
    folders = ["uploads", "uploads/bots", "uploads/sites", "logs", "transferred"]
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for f in folders:
        kb.inline_keyboard.append([InlineKeyboardButton(text=f, callback_data=f"browse_folder_{f}", style="primary")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="منح صلاحية وصول لمجلد ⇢", callback_data="grant_folder_perm_start", style="success")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="رجوع", callback_data="admin_panel", style="danger")])
    text = "━━━━━━━━━━━━━━━━━━━\n◆ إدارة المجلدات ◆\n━━━━━━━━━━━━━━━━━━━\n\nاختر مجلداً للتصفح:"
    await delete_and_send(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)


@dp.callback_query_handler(text="grant_folder_perm_start", state='*')
async def cb_grant_folder_perm_start(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        return
    text = (
        "━━━━━━━━━━━━━━━━━━━\n"
        "◆ منح صلاحية وصول لمجلد ◆\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        "أرسل آيدي المستخدم (Telegram user_id) المراد منحه الصلاحية."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="إلغاء", callback_data="admin_folders", style="danger")]
    ])
    await delete_and_send(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)
    await GrantFolderPermissionState.waiting_user_id.set()


@dp.message_handler(state=GrantFolderPermissionState.waiting_user_id)
async def msg_grant_folder_perm_user_id(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await state.finish()
        return
    raw = message.text.strip()
    if not raw.isdigit():
        await message.answer(" أرسل آيدي رقمي صحيح.")
        return
    target_user_id = int(raw)
    target_user = await get_user(target_user_id)
    if not target_user:
        await message.answer(" لا يوجد مستخدم بهذا الآيدي مسجّل بالبوت. تأكد من الآيدي وحاول مرة أخرى.")
        return
    await state.update_data(grant_target_user_id=target_user_id)
    await message.answer(
        " تم تحديد المستخدم.\n\nالآن أرسل اسم/مسار المجلد المراد منح الصلاحية عليه "
        "(مثال: uploads/bots)."
    )
    await GrantFolderPermissionState.waiting_folder_path.set()


@dp.message_handler(state=GrantFolderPermissionState.waiting_folder_path)
async def msg_grant_folder_perm_path(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await state.finish()
        return
    data = await state.get_data()
    target_user_id = data.get("grant_target_user_id")
    if not target_user_id:
        await message.answer(" حدث خطأ، ابدأ العملية من جديد.")
        await state.finish()
        return

    folder_path = message.text.strip()
    if not folder_path or ".." in folder_path or folder_path.startswith("/"):
        await message.answer(" اسم/مسار مجلد غير صالح. حاول مرة أخرى.")
        return

    ok = await grant_folder_permission(target_user_id, folder_path, message.from_user.id)
    if ok:
        text = f" تم منح المستخدم <code>{target_user_id}</code> صلاحية الوصول للمجلد:\n<code>{sanitize_html_for_telegram(folder_path, max_len=200)}</code>"
        try:
            await bot.send_message(
                target_user_id,
                f" تم منحك صلاحية وصول لمجلد جديد:\n<code>{sanitize_html_for_telegram(folder_path, max_len=200)}</code>",
            )
        except Exception:
            pass
    else:
        text = " حدث خطأ أثناء منح الصلاحية."

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="رجوع", callback_data="admin_folders", style="danger")]
    ])
    await message.answer(text, reply_markup=kb)
    await state.finish()


# ─────────────────────────────────────────────
# لوحة إدارة الاشتراك الإجباري (قنوات/بوتات/انستغرام)
# ─────────────────────────────────────────────
def force_sub_admin_row_color(idx: int) -> str:
    return FORCE_SUB_BUTTON_COLOR_CYCLE[idx % len(FORCE_SUB_BUTTON_COLOR_CYCLE)]


@dp.callback_query_handler(text='admin_force_sub_list', state='*')
async def cb_admin_force_sub_list(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return

    targets = await get_all_force_sub_targets()
    text = "━━━━━━━━━━━━━━━━━━━\n◆ إدارة الاشتراك الإجباري ◆\n━━━━━━━━━━━━━━━━━━━\n\n"
    if not targets:
        text += "لا توجد أي قنوات/روابط مضافة حالياً.\n\nملاحظة: التحقق الآلي الحقيقي (منع الدخول فعلياً) يعمل فقط مع قنوات تيليجرام، وبشرط أن يكون البوت أدمن بها. بوتات تيليجرام وحسابات انستغرام تُعرض كروابط تشجيعية فقط بدون إمكانية تحقق آلي."
    else:
        text += "اضغط على أي عنصر لحذفه أو تفعيله/تعطيله:\n\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for idx, target in enumerate(targets):
        status_icon = "" if target["is_active"] else ""
        type_label = FORCE_SUB_TYPE_LABELS.get(target["target_type"], target["target_type"])
        color = force_sub_admin_row_color(idx)
        kb.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"{status_icon} {type_label}: {target['display_name']}",
                callback_data=f"fst_toggle_{target['id']}",
                style=color,
            ),
            InlineKeyboardButton(text="", callback_data=f"fst_delete_{target['id']}", style="danger"),
        ])

    kb.inline_keyboard.append([InlineKeyboardButton(text="إضافة قناة تيليجرام ⁘›", callback_data="fst_add_channel", style="primary")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="إضافة بوت تيليجرام ⁘", callback_data="fst_add_tg_bot", style="danger")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="إضافة حساب انستغرام ⁘⁘", callback_data="fst_add_instagram", style="success")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="رجوع ‹", callback_data="admin_panel", style="danger")])

    await edit_or_send_message(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)


@dp.callback_query_handler(text_startswith="fst_toggle_", state='*')
async def cb_fst_toggle(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        return
    target_id = int(callback.data.split("_")[2])
    await toggle_force_sub_target(target_id)
    await cb_admin_force_sub_list(callback, state)


@dp.callback_query_handler(text_startswith="fst_delete_", state='*')
async def cb_fst_delete(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        return
    target_id = int(callback.data.split("_")[2])
    await delete_force_sub_target(target_id)
    await safe_answer_callback(callback, " تم الحذف.", show_alert=True)
    await cb_admin_force_sub_list(callback, state)


@dp.callback_query_handler(text_startswith="fst_add_", state='*')
async def cb_fst_add_start(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        return

    target_type = callback.data.replace("fst_add_", "")
    if target_type not in (FORCE_SUB_TYPE_CHANNEL, FORCE_SUB_TYPE_TG_BOT, FORCE_SUB_TYPE_INSTAGRAM):
        return

    await state.update_data(fst_target_type=target_type)
    type_label = FORCE_SUB_TYPE_LABELS.get(target_type, target_type)
    text = (
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"◆ إضافة: {type_label} ◆\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"أرسل الاسم الذي سيظهر على الزر (مثال: قناتنا الرسمية)."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="إلغاء", callback_data="admin_force_sub_list", style="danger")]
    ])
    await delete_and_send(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)
    await AddForceSubTargetState.waiting_display_name.set()


@dp.message_handler(state=AddForceSubTargetState.waiting_display_name)
async def msg_fst_display_name(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await state.finish()
        return
    name = message.text.strip()
    if not name:
        await message.answer(" أرسل اسماً صالحاً.")
        return
    await state.update_data(fst_display_name=name)
    data = await state.get_data()
    target_type = data.get("fst_target_type")

    if target_type == FORCE_SUB_TYPE_CHANNEL:
        prompt = (
            "الآن أرسل يوزر القناة (مثال: @mychannel) أو آيدي القناة الرقمي (مثال: -1001234567890).\n\n"
            " مهم: يجب إضافة هذا البوت كأدمن بالقناة أولاً، وإلا لن يعمل التحقق الآلي."
        )
    else:
        prompt = "الآن أرسل الرابط الكامل (مثال: https://t.me/mybot أو https://instagram.com/myaccount)."

    await message.answer(prompt)
    await AddForceSubTargetState.waiting_identifier_or_url.set()


@dp.message_handler(state=AddForceSubTargetState.waiting_identifier_or_url)
async def msg_fst_identifier(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await state.finish()
        return
    data = await state.get_data()
    target_type = data.get("fst_target_type")
    display_name = data.get("fst_display_name")
    if not target_type or not display_name:
        await message.answer(" حدث خطأ، ابدأ العملية من جديد.")
        await state.finish()
        return

    raw = message.text.strip()

    if target_type == FORCE_SUB_TYPE_CHANNEL:
        identifier = raw
        if identifier.startswith("@"):
            url = f"https://t.me/{identifier[1:]}"
        elif identifier.startswith("-") or identifier.isdigit():
            url = "https://t.me/"  # آيدي رقمي لا يملك رابط مباشر صالح دائماً؛ نتركه للأدمن ليعدله لاحقاً إذا لزم
        else:
            identifier = f"@{identifier}"
            url = f"https://t.me/{raw}"
    else:
        if not (raw.startswith("http://") or raw.startswith("https://")):
            await message.answer(" الرابط يجب أن يبدأ بـ http:// أو https://. حاول مرة أخرى.")
            return
        identifier = raw
        url = raw

    new_id = await add_force_sub_target(target_type, display_name, identifier, url)
    text = f" تمت الإضافة بنجاح.\n\n {display_name}\n {sanitize_html_for_telegram(url, max_len=200)}"
    if target_type == FORCE_SUB_TYPE_CHANNEL:
        text += "\n\n تذكير: تأكد أن البوت أدمن بهذه القناة، وإلا لن يعمل التحقق الآلي."

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="رجوع للقائمة ‹", callback_data="admin_force_sub_list", style="danger")]
    ])
    await message.answer(text, reply_markup=kb)
    await state.finish()


# ─────────────────────────────────────────────
# لوحة تحكم الأدمن بنظام AI
# ─────────────────────────────────────────────
@dp.callback_query_handler(text="admin_ai_panel", state='*')
async def cb_admin_ai_panel(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return

    configured_models = await get_configured_ai_models()
    ai_on = await is_ai_enabled_globally()
    key_status = f" {len(configured_models)}/{len(AI_MODELS_CATALOG)} نماذج مضبوطة" if configured_models else " لا يوجد أي نموذج مضبوط بعد"
    status_icon = " مفعّل" if ai_on else " معطّل"
    current_model = AI_MODELS_CATALOG.get(await get_ai_model_choice(callback.from_user.id), {}).get("label", "—")

    text = (
        "━━━━━━━━━━━━━━━━━━━\n"
        "◆ إدارة الذكاء الاصطناعي (AI) ◆\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        f" النموذج الحالي (لك): {current_model}\n"
        f" المفاتيح: {key_status}\n"
        f" الحالة العامة: {status_icon}\n"
        f" حد الأسئلة: {AI_QUESTIONS_LIMIT} سؤال / {AI_COOLDOWN_HOURS} ساعات لكل بوت\n"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="محادثة مفتوحة (بدون حد أسئلة) ", callback_data="admin_ai_open_chat", style="primary")],
        [InlineKeyboardButton(text="اختيار نموذج AI ", callback_data="admin_ai_model_select", style="primary")],
        [InlineKeyboardButton(text="شحن AI ", callback_data="ai_charge_menu", style="success")],
        [InlineKeyboardButton(text="منح صلاحية AI كاملة لمستخدم ", callback_data="admin_ai_grant_full_start", style="success")],
        [InlineKeyboardButton(text="إدارة المفاتيح ", callback_data="admin_ai_keys_panel", style="primary")],
        [InlineKeyboardButton(text="تعطيل/تفعيل الذكاء لمستخدم معيّن ", callback_data="admin_ai_disable_user_start", style="danger")],
        [InlineKeyboardButton(
            text=(f"{' تفعيل' if not ai_on else ' تعطيل'} الذكاء عالمياً"),
            callback_data="admin_ai_toggle_global", style="success" if not ai_on else "danger"
        )],
        [InlineKeyboardButton(text="حذف نهائي للذكاء (المفتاح + كل السجلات) ", callback_data="admin_ai_delete_confirm", style="danger")],
        [InlineKeyboardButton(text="رجوع ‹", callback_data="admin_panel", style="danger")],
    ])
    await edit_or_send_message(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)


@dp.callback_query_handler(text="admin_ai_toggle_global", state='*')
async def cb_admin_ai_toggle_global(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        return
    current = await is_ai_enabled_globally()
    await set_ai_setting("ai_enabled", "0" if current else "1")
    await safe_answer_callback(callback, " تم تحديث الحالة.", show_alert=True)
    await cb_admin_ai_panel(callback, state)


@dp.callback_query_handler(text="admin_ai_model_select", state='*')
async def cb_admin_ai_model_select(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        return
    current = await get_ai_model_choice(callback.from_user.id)
    text = (
        "━━━━━━━━━━━━━━━━━━━\n"
        "◆ اختيار نموذج AI ◆\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        "اختر النموذج الذي تريد استخدامه بمحادثاتك مع EYRX-AI:"
    )
    rows = []
    for key, cfg in AI_MODELS_CATALOG.items():
        prefix = " " if key == current else ""
        rows.append([InlineKeyboardButton(
            text=f"{prefix}{cfg['label']}",
            callback_data=f"admin_ai_model_set_{key}",
            style="success" if key == current else "primary",
        )])
    rows.append([InlineKeyboardButton(text="رجوع ‹", callback_data="admin_ai_panel", style="danger")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await edit_or_send_message(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)


@dp.callback_query_handler(text_startswith="admin_ai_model_set_", state='*')
async def cb_admin_ai_model_set(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    model_key = callback.data[len("admin_ai_model_set_"):]
    if model_key not in AI_MODELS_CATALOG:
        await safe_answer_callback(callback, " نموذج غير معروف.", show_alert=True)
        return
    await set_ai_model_choice(callback.from_user.id, model_key)
    await safe_answer_callback(callback, f" تم اختيار: {AI_MODELS_CATALOG[model_key]['label']}", show_alert=True)
    await cb_admin_ai_model_select(callback, state)


@dp.callback_query_handler(text="user_ai_model_select", state='*')
async def cb_user_ai_model_select(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    current = await get_ai_model_choice(callback.from_user.id)
    text = (
        "━━━━━━━━━━━━━━━━━━━\n"
        "◆ اختيار نموذج AI ◆\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        "اختر النموذج الذي تريد استخدامه بمحادثاتك مع EYRX-AI:"
    )
    rows = []
    for key, cfg in AI_MODELS_CATALOG.items():
        prefix = " " if key == current else ""
        rows.append([InlineKeyboardButton(
            text=f"{prefix}{cfg['label']}",
            callback_data=f"user_ai_model_set_{key}",
            style="success" if key == current else "primary",
        )])
    rows.append([InlineKeyboardButton(text="رجوع ‹", callback_data="ai_charge_menu", style="danger")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await edit_or_send_message(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)


@dp.callback_query_handler(text_startswith="user_ai_model_set_", state='*')
async def cb_user_ai_model_set(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    model_key = callback.data[len("user_ai_model_set_"):]
    if model_key not in AI_MODELS_CATALOG:
        await safe_answer_callback(callback, " نموذج غير معروف.", show_alert=True)
        return
    await set_ai_model_choice(callback.from_user.id, model_key)
    await safe_answer_callback(callback, f" تم اختيار: {AI_MODELS_CATALOG[model_key]['label']}", show_alert=True)
    await cb_user_ai_model_select(callback, state)


def _mask_ai_key(key: str) -> str:
    """يقنّع مفتاحاً حسّاساً لعرضه بأمان بالواجهة: يبقي أول 6 وآخر 4 محارف فقط."""
    if len(key) <= 12:
        return key[:2] + "…" + key[-2:]
    return key[:6] + "…" + key[-4:]


@dp.callback_query_handler(text="admin_ai_keys_panel", state='*')
async def cb_admin_ai_keys_panel(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        return

    lines = [
        "━━━━━━━━━━━━━━━━━━━",
        "◆ إدارة مفاتيح النماذج الرسمية ◆",
        "━━━━━━━━━━━━━━━━━━━",
        "",
        f"كل نموذج يقبل حتى {AI_MAX_KEYS_PER_MODEL} مفاتيح/روابط. عند فشل مفتاح أثناء "
        "الاستخدام، يُنتقل تلقائياً للمفتاح التالي بالترتيب ويصلك إشعار فوري بذلك.",
        "",
    ]
    kb_rows = []
    for key, cfg in AI_MODELS_CATALOG.items():
        creds = await get_official_ai_credentials(key)
        status = f" {len(creds)}/{AI_MAX_KEYS_PER_MODEL} مفاتيح مضبوطة" if creds else " لا يوجد أي مفتاح"
        lines.append(f"{cfg['label']}: {status}")
        kb_rows.append([InlineKeyboardButton(text=f"إدارة مفاتيح {cfg['label']} ", callback_data=f"admin_ai_model_keys_{key}", style="primary")])

    kb_rows.append([InlineKeyboardButton(text="رجوع للوحة AI «", callback_data="admin_ai_panel", style="danger")])

    await edit_or_send_message(
        callback.message.chat.id, callback.from_user.id,
        "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=kb_rows), callback.message.message_id
    )


@dp.callback_query_handler(text_startswith="admin_ai_model_keys_", state='*')
async def cb_admin_ai_model_keys(callback: types.CallbackQuery, state: FSMContext):
    """يعرض قائمة المفاتيح الحالية (حتى 5) لنموذج واحد محدد، مع زر حذف مستقل لكل
    مفتاح وزر إضافة مفتاح جديد إذا لم تُستنفد الحصة بعد."""
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        return
    model_key = callback.data[len("admin_ai_model_keys_"):]
    cfg = AI_MODELS_CATALOG.get(model_key)
    if not cfg:
        await safe_answer_callback(callback, " نموذج غير معروف.", show_alert=True)
        return

    creds = await get_official_ai_credentials(model_key)
    lines = [
        "━━━━━━━━━━━━━━━━━━━",
        f"◆  مفاتيح {cfg['label']} ◆",
        "━━━━━━━━━━━━━━━━━━━",
        "",
        "الترتيب أدناه هو ترتيب المحاولة: المفتاح 1 يُجرَّب أولاً، وعند فشله يُنتقل "
        "تلقائياً للمفتاح 2 وهكذا.",
        "",
    ]
    if creds:
        for i, cred in enumerate(creds):
            lines.append(f"{i + 1}. <code>{_mask_ai_key(cred)}</code>")
    else:
        lines.append("لا يوجد أي مفتاح مضبوط بعد لهذا النموذج.")

    kb_rows = []
    for i in range(len(creds)):
        kb_rows.append([InlineKeyboardButton(text=f"حذف المفتاح رقم {i + 1} ", callback_data=f"admin_ai_del_key_{model_key}_{i}", style="danger")])
    if len(creds) < AI_MAX_KEYS_PER_MODEL:
        kb_rows.append([InlineKeyboardButton(text="إضافة مفتاح جديد +", callback_data=f"admin_ai_add_key_{model_key}", style="success")])
    else:
        lines.append(f"\n وصلت الحد الأقصى ({AI_MAX_KEYS_PER_MODEL}). احذف مفتاحاً لإضافة آخر.")
    kb_rows.append([InlineKeyboardButton(text="رجوع ‹", callback_data="admin_ai_keys_panel", style="danger")])

    await edit_or_send_message(
        callback.message.chat.id, callback.from_user.id,
        "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=kb_rows), callback.message.message_id
    )


@dp.callback_query_handler(text_startswith="admin_ai_add_key_", state='*')
async def cb_admin_ai_add_key(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        return
    model_key = callback.data[len("admin_ai_add_key_"):]
    cfg = AI_MODELS_CATALOG.get(model_key)
    if not cfg:
        await safe_answer_callback(callback, " نموذج غير معروف.", show_alert=True)
        return
    creds = await get_official_ai_credentials(model_key)
    if len(creds) >= AI_MAX_KEYS_PER_MODEL:
        await safe_answer_callback(callback, f" وصلت الحد الأقصى ({AI_MAX_KEYS_PER_MODEL}).", show_alert=True)
        return

    await state.update_data(ai_official_target_model=model_key)
    text = (
        "━━━━━━━━━━━━━━━━━━━\n"
        f"◆  إضافة مفتاح لـ{cfg['label']} (رقم {len(creds) + 1}/{AI_MAX_KEYS_PER_MODEL}) ◆\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        "أرسل الآن إما:\n"
        "• مفتاح API الرسمي (Bearer key) من موقع الشركة، أو\n"
        "• رابط اتصال جاهز كامل (يبدأ بـhttp) إذا زوّدتك الشركة به مباشرة.\n\n"
        "سيُضاف كمفتاح جديد بآخر قائمة هذا النموذج (يُجرَّب بعد كل المفاتيح الحالية)."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="إلغاء", callback_data=f"admin_ai_model_keys_{model_key}", style="danger")]
    ])
    await delete_and_send(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)
    await AdminSetAIKeyState.waiting_official_credential.set()


@dp.message_handler(state=AdminSetAIKeyState.waiting_official_credential, content_types=types.ContentType.TEXT)
async def msg_admin_ai_set_official_credential(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await state.finish()
        return
    data = await state.get_data()
    model_key = data.get("ai_official_target_model")
    cfg = AI_MODELS_CATALOG.get(model_key)
    if not cfg:
        await message.answer(" حدث خطأ، ابدأ من جديد.")
        await state.finish()
        return

    new_value = message.text.strip()
    if not new_value:
        await message.answer(" أرسل مفتاحاً أو رابطاً صالحاً.")
        return

    ok, msg_text = await add_official_ai_credential(model_key, new_value)
    try:
        await message.delete()
    except Exception:
        pass

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="رجوع لمفاتيح هذا النموذج ‹", callback_data=f"admin_ai_model_keys_{model_key}", style="danger")]
    ])
    if ok:
        await message.answer(
            f" تمت إضافة مفتاح/رابط {cfg['label']} بنجاح. (حُذفت رسالتك تلقائياً لحمايته)",
            reply_markup=kb
        )
    else:
        await message.answer(f" {msg_text}", reply_markup=kb)
    await state.finish()


@dp.callback_query_handler(text_startswith="admin_ai_del_key_", state='*')
async def cb_admin_ai_del_key(callback: types.CallbackQuery, state: FSMContext):
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        return
    rest = callback.data[len("admin_ai_del_key_"):]
    try:
        model_key, index_str = rest.rsplit("_", 1)
        index = int(index_str)
    except (ValueError, IndexError):
        await safe_answer_callback(callback, " خطأ بالبيانات.", show_alert=True)
        return
    cfg = AI_MODELS_CATALOG.get(model_key)
    if not cfg:
        return
    removed = await remove_official_ai_credential_at(model_key, index)
    await safe_answer_callback(callback, " تم حذف المفتاح." if removed else " لم يُعثر على هذا المفتاح.", show_alert=True)
    # نعيد بناء callback.data ليطابق تنسيق admin_ai_model_keys_ قبل إعادة استخدام المعالج
    callback.data = f"admin_ai_model_keys_{model_key}"
    await cb_admin_ai_model_keys(callback, state)


@dp.callback_query_handler(text="admin_ai_delete_confirm", state='*')
async def cb_admin_ai_delete_confirm(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        return
    text = (
        " تأكيد نهائي \n\n"
        "سيتم حذف مفتاح الذكاء الاصطناعي نهائياً، وتعطيل الخدمة بالكامل، ومسح كل "
        "سجلات استخدام الأسئلة لكل المستخدمين. هذا الإجراء لا يمكن التراجع عنه.\n\n"
        "هل أنت متأكد؟"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="نعم، احذف نهائياً ", callback_data="admin_ai_delete_do", style="danger")],
        [InlineKeyboardButton(text="إلغاء ", callback_data="admin_ai_panel", style="success")],
    ])
    await edit_or_send_message(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)


@dp.callback_query_handler(text="admin_ai_delete_do", state='*')
async def cb_admin_ai_delete_do(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        return

    async with db_cursor() as conn:
        for cfg in AI_MODELS_CATALOG.values():
            conn.execute("DELETE FROM ai_settings WHERE key = ?", (cfg["setting_key"],))
        conn.execute("DELETE FROM ai_settings WHERE key = 'openrouter_api_key'")
        conn.execute("DELETE FROM ai_settings WHERE key = 'openrouter_api_keys'")
        conn.execute("DELETE FROM ai_settings WHERE key = 'ai_enabled'")
        conn.execute("DELETE FROM ai_settings WHERE key LIKE 'ai_disabled_user_%'")
        conn.execute("DELETE FROM ai_usage")
        conn.execute("DELETE FROM ai_model_usage_stats")

    await safe_answer_callback(callback, " تم حذف كل شيء متعلق بالذكاء الاصطناعي نهائياً.", show_alert=True)
    await cb_admin_ai_panel(callback, state)


# ─────────────────────────────────────────────
# ربط IP/دومين المواقع (بدل export من الترمينال)
# ─────────────────────────────────────────────
@dp.callback_query_handler(text="admin_set_site_ip", state='*')
async def cb_admin_set_site_ip(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return

    current_url = await get_site_host_url()
    is_env_override = bool(os.environ.get("SITE_HOST_PUBLIC_URL"))
    text = (
        "━━━━━━━━━━━━━━━━━━━\n"
        "◆ ربط IP/دومين المواقع ◆\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        f" الرابط الحالي: <code>{sanitize_html_for_telegram(current_url, max_len=200)}</code>\n\n"
        "أرسل الآن الرابط الجديد الذي تتصل به المواقع (IP أو دومين)، مثل:\n"
        "<code>http://1.2.3.4:8082</code>\n"
        "أو\n"
        "<code>https://mysite.com</code>\n\n"
        "بعد الحفظ، كل المواقع المقبولة سابقاً ستتحدث تلقائياً لتستخدم هذا الرابط الجديد."
    )
    if is_env_override:
        text += (
            "\n\n تنبيه: متغيّر البيئة SITE_HOST_PUBLIC_URL مضبوط حالياً على السيرفر "
            "وله الأولوية على أي قيمة تحفظها هنا. لتفعيل هذا الزر فعلياً، احذف ذلك "
            "المتغيّر من السيرفر أولاً."
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="إلغاء", callback_data="admin_panel", style="danger")]
    ])
    await delete_and_send(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)
    await AdminSetSiteIPState.waiting_url.set()


@dp.message_handler(state=AdminSetSiteIPState.waiting_url, content_types=types.ContentType.TEXT)
async def msg_admin_set_site_ip(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await state.finish()
        return

    raw = message.text.strip()
    if not (raw.startswith("http://") or raw.startswith("https://")):
        await message.answer(" الرابط يجب أن يبدأ بـ http:// أو https://. حاول مرة أخرى.")
        return
    if "localhost" in raw.lower() or "127.0.0.1" in raw.lower() or "0.0.0.0" in raw.lower():
        await message.answer(" لا يمكن استخدام localhost أو 127.0.0.1 — هذا عنوان محلي غير مرئي للمستخدمين. أرسل IP عام أو دومين حقيقي.")
        return

    new_url = raw.rstrip("/")
    await set_config_value("site_host_public_url", new_url)

    try:
        updated_count = await update_all_site_urls_to_real_hosting()
    except Exception as e:
        logger.error(f"msg_admin_set_site_ip: failed to refresh site urls: {e}", exc_info=True)
        updated_count = 0

    text = (
        f" تم حفظ الرابط الجديد:\n<code>{sanitize_html_for_telegram(new_url, max_len=200)}</code>\n\n"
        f" تم تحديث {updated_count} رابط موقع تلقائياً ليستخدم هذا الرابط الجديد.\n\n"
        f" تأكد أن هذا العنوان يصل فعلياً لسيرفرك (عبر فتح البورت بالجدار الناري، أو "
        f"استخدام أداة نفق مثل Cloudflare Tunnel لو ما عندك IP ثابت)، وإلا الروابط "
        f"لن تعمل فعلياً رغم حفظها بنجاح هنا."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="رجوع للوحة الأدمن »", callback_data="admin_panel", style="danger")]
    ])
    await message.answer(text, reply_markup=kb)
    await state.finish()


@dp.callback_query_handler(text="admin_ai_disable_user_start", state='*')
async def cb_admin_ai_disable_user_start(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        return
    text = "أرسل آيدي المستخدم (Telegram user_id) المراد تعطيل/تفعيل الذكاء الاصطناعي له."
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="إلغاء", callback_data="admin_ai_panel", style="danger")]
    ])
    await delete_and_send(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)
    await AdminToggleAIForUserState.waiting_user_id.set()


@dp.message_handler(state=AdminToggleAIForUserState.waiting_user_id, content_types=types.ContentType.TEXT)
async def msg_admin_ai_toggle_user(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await state.finish()
        return
    raw = message.text.strip()
    if not raw.isdigit():
        await message.answer(" أرسل آيدي رقمي صحيح.")
        return

    target_user_id = int(raw)
    target_user = await get_user(target_user_id)
    if not target_user:
        await message.answer(" لا يوجد مستخدم بهذا الآيدي مسجّل بالبوت.")
        return

    currently_disabled = await is_ai_disabled_for_user(target_user_id)
    new_value = "0" if currently_disabled else "1"
    await set_ai_setting(f"ai_disabled_user_{target_user_id}", new_value)

    action_label = "تفعيل" if currently_disabled else "تعطيل"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="رجوع للوحة AI «", callback_data="admin_ai_panel", style="danger")]
    ])
    await message.answer(f" تم {action_label} الذكاء الاصطناعي للمستخدم <code>{target_user_id}</code>.", reply_markup=kb)
    await state.finish()


# ─────────────────────────────────────────────
# منح صلاحية AI كاملة (كل مميزات الباقة الذهبية) لمستخدم معيّن مجاناً
# ─────────────────────────────────────────────
AI_FULL_ACCESS_QUESTIONS_GRANT = 120  # نفس رصيد الباقة الذهبية (200)


@dp.callback_query_handler(text="admin_ai_grant_full_start", state='*')
async def cb_admin_ai_grant_full_start(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        return
    text = (
        " منح صلاحية AI كاملة لمستخدم\n\n"
        f"أرسل آيدي المستخدم (Telegram user_id). رح يحصل فوراً ومجاناً على:\n"
        f" {AI_FULL_ACCESS_QUESTIONS_GRANT} سؤال إضافي\n"
        f" قراءة الملفات\n قراءة السجل\n تعديل فوري على الملف\n إرسال ملفات للذكاء\n\n"
        "(نفس مميزات باقة الـ200 نجمة، بدون أي دفع)"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="إلغاء", callback_data="admin_ai_panel", style="danger")]
    ])
    await delete_and_send(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)
    await AdminGrantAIFullAccessState.waiting_user_id.set()


@dp.message_handler(state=AdminGrantAIFullAccessState.waiting_user_id, content_types=types.ContentType.TEXT)
async def msg_admin_ai_grant_full(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await state.finish()
        return
    raw = message.text.strip()
    if not raw.isdigit():
        await message.answer(" أرسل آيدي رقمي صحيح.")
        return

    target_user_id = int(raw)
    target_user = await get_user(target_user_id)
    if not target_user:
        await message.answer(" لا يوجد مستخدم بهذا الآيدي مسجّل بالبوت.")
        return

    await add_ai_package_to_user(target_user_id, "ai_pkg_3")
    wallet = await get_ai_wallet(target_user_id)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="رجوع للوحة AI «", callback_data="admin_ai_panel", style="danger")]
    ])
    await message.answer(
        f" تم منح صلاحية AI كاملة للمستخدم <code>{target_user_id}</code>.\n"
        f" رصيده الحالي: <b>{wallet['ai_questions_balance']}</b> سؤال، مع كل الصلاحيات مفعّلة.",
        reply_markup=kb,
    )

    try:
        target_lang = await get_user_language(target_user_id) or "ar"
        await bot.send_message(
            target_user_id,
            " هدية من إدارة EYRX Hosting!\n\n"
            "تم منحك صلاحية AI كاملة مجاناً:\n"
            f" {AI_FULL_ACCESS_QUESTIONS_GRANT} سؤال إضافي\n"
            " قراءة الملفات\n قراءة السجل\n تعديل فوري على الملف\n إرسال ملفات للذكاء\n\n"
            "استمتع! ",
        )
    except Exception:
        pass

    await state.finish()


@dp.callback_query_handler(text="admin_ai_open_chat", state='*')
async def cb_admin_ai_open_chat(callback: types.CallbackQuery, state: FSMContext):
    """محادثة مفتوحة للأدمن فقط مع EYRX-AI مباشرة، بدون حد أسئلة وبدون تقييد
    الموضوع — يرد على أي سؤال (وليس فقط تشخيص أخطاء البوتات)."""
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        return


    await state.update_data(ai_history=[], ai_bot_id=None)

    text = (
        " محادثة مفتوحة مع EYRX-AI (أدمن فقط)\n\n"
        "اكتب أي سؤال أو رسالة — بدون أي حد على عدد الأسئلة وبدون تقييد الموضوع. "
        "لو طلبت إصلاح كود، رح يرسله لك بصيغة كود منسّقة. "
        f"يحتفظ EYRX-AI بآخر {AI_HISTORY_LIMIT} رسائل من المحادثة كسياق. "
        "اضغط 'إنهاء المحادثة' للخروج."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="إنهاء المحادثة ", callback_data="admin_ai_panel", style="danger")]
    ])
    await delete_and_send(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)
    await AdminAIChatState.waiting_message.set()


@dp.message_handler(state=AdminAIChatState.waiting_message, content_types=types.ContentType.TEXT)
async def msg_admin_ai_open_chat(message: types.Message, state: FSMContext):
    """مغلَّفة بحماية من الانهيار حتى لا تعلّق جلسة الأدمن بالمحادثة المفتوحة."""
    try:
        await _msg_admin_ai_open_chat_inner(message, state)
    except Exception as e:
        logger.error(f"msg_admin_ai_open_chat: خطأ غير متوقع: {e}", exc_info=True)
        try:
            await message.answer(" صار خطأ غير متوقع. اكتب رسالتك مرة أخرى أو اضغط 'إنهاء المحادثة'.")
        except Exception:
            pass


async def _msg_admin_ai_open_chat_inner(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await state.finish()
        return

    data = await state.get_data()
    history = data.get("ai_history") or []
    bot_id = data.get("ai_bot_id")

    user_content = message.text
    system_prompt = EYRX_AI_OPEN_SYSTEM_PROMPT
    # لو هاي المحادثة انفتحت من زر "اسأل EYRX-AI" جوّا سجل بوت معيّن، نرفق له
    # سجل الأخطاء وسجل التشغيل الكامل تلقائياً بأول رسالة فقط (مو بكل رسالة)،
    # ونفعّل تعليمات التعديل المباشر لأن الأدمن عنده صلاحية كاملة دائماً على كل بوت.
    if bot_id:
        system_prompt = (
            EYRX_AI_OPEN_SYSTEM_PROMPT
            + " للأدمن صلاحية تعديل مباشر وفوري على ملف هذا البوت. إذا كان الطلب يتطلب إصلاح "
              "خطأ، تصحيح أسطر فيها مشكلة، أو إضافة أي شيء يطلبه الأدمن للملف: أعد كتابة الملف "
              "بالكامل بعد التعديل (كل الأسطر) داخل code block واحد فقط (```python ... ```)، لأن "
              "هذا الرد سيُطبَّق تلقائياً وحرفياً على الملف الحقيقي فور ضغط زر 'تطبيق التعديل على "
              "الملف'. اشرح ما فعلته خارج الـ code block فقط."
        )
        if not history:
            error_log = await get_bot_error_log(bot_id)
            full_log = await get_bot_full_log(bot_id)
            user_content = (
                f"بيانات بوت #{bot_id}:\n\n"
                f"سجل الأخطاء:\n```\n{error_log[:2000]}\n```\n\n"
                f"سجل التشغيل الكامل (آخر جزء):\n```\n{full_log[:2000]}\n```\n\n"
                f"سؤال الأدمن: {message.text}"
            )

    messages = history + [{"role": "user", "content": user_content}]
    ok, reply = await _run_ai_with_thinking_indicator(message.chat.id, messages, system_prompt, user_id=message.from_user.id)

    # ── تعديل مباشر على الملف / إرسال الرد كملف: متاح دائماً للأدمن
    ai_code = extract_ai_code_block(reply) if ok else None
    action_row = []
    if ok and bot_id and ai_code:
        await state.update_data(ai_pending_code=ai_code, ai_pending_bot_id=bot_id)
        action_row.append(InlineKeyboardButton(text="تطبيق التعديل على الملف ", callback_data=f"ai_apply_edit_{bot_id}", style="success"))
    if ok:
        await state.update_data(ai_last_reply_text=reply)
        action_row.append(InlineKeyboardButton(text="إرسال الرد كملف ⇡", callback_data="ai_send_reply_file", style="primary"))

    kb_rows = []
    if action_row:
        kb_rows.append(action_row)
    kb_rows.append([InlineKeyboardButton(text="إنهاء المحادثة ", callback_data="admin_ai_panel", style="danger")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)

    if ok:
        new_history = _trim_ai_history(messages + [{"role": "assistant", "content": reply}])
        await state.update_data(ai_history=new_history)
        await _safe_ai_reply_send(message.chat.id, reply, kb, ai_code)
    else:
        # نعرض للأدمن سبب الفشل الحقيقي (مفتاح خاطئ، رصيد منتهي، rate limit...الخ)
        # بدل رسالة عامة، حتى يقدر يشخّص لوحده ليش الذكاء ما عم يرد.
        await message.answer(f"{reply}", reply_markup=kb, parse_mode=None)

    await AdminAIChatState.waiting_message.set()


# ─────────────────────────────────────────────
# AI FILE ACTIONS: تطبيق تعديل الذكاء الاصطناعي مباشرة على الملف / إرسال الرد كملف
# متاح دائماً للأدمن، ومتاح للمستخدم فقط إذا كان صاحب باقة AI الذهبية (200 ) وعلى بوته هو
# ─────────────────────────────────────────────
@dp.callback_query_handler(text_startswith="ai_apply_edit_", state='*')
async def cb_ai_apply_edit(callback: types.CallbackQuery, state: FSMContext):
    """تطبيق فعلي لتعديل الذكاء الاصطناعي على ملف حقيقي — أهم نقطة أمان بكل هذا
    النظام، لذلك مغلَّفة بالكامل بحماية من الانهيار (apply_ai_code_to_bot_file
    أصلاً تأخذ نسخة احتياطية قبل الكتابة، وهنا نضمن أيضاً عدم توقف باقي البوت
    حتى لو صار خطأ غير متوقع أثناء الإشعار أو تحديث الإحصاء بعد الكتابة)."""
    try:
        await _cb_ai_apply_edit_inner(callback, state)
    except Exception as e:
        logger.error(f"cb_ai_apply_edit: خطأ غير متوقع: {e}", exc_info=True)
        try:
            await bot.send_message(
                callback.message.chat.id,
                " صار خطأ غير متوقع أثناء تطبيق التعديل. تحقق من حالة الملف يدوياً "
                "أو راجع النسخة الاحتياطية إن كانت الكتابة قد بدأت.",
            )
        except Exception:
            pass


async def _cb_ai_apply_edit_inner(callback: types.CallbackQuery, state: FSMContext):
    await safe_answer_callback(callback, " جاري تطبيق التعديل على الملف...", show_alert=False)
    bot_id = int(callback.data.split("_")[3])
    bot_data = await get_bot_by_id(bot_id)
    if not bot_data:
        await safe_answer_callback(callback, " البوت غير موجود.", show_alert=True)
        return

    is_admin_user = await is_admin(callback.from_user.id)
    if not is_admin_user:
        if bot_data["user_id"] != callback.from_user.id:
            await safe_answer_callback(callback, " البوت غير موجود.", show_alert=True)
            return
        wallet = await get_ai_wallet(callback.from_user.id)
        if not wallet["can_edit_files"]:
            await safe_answer_callback(
                callback,
                " تطبيق التعديل مباشرة على الملف متاح فقط مع باقة AI الذهبية (200 ).",
                show_alert=True,
            )
            return

    data = await state.get_data()
    pending_code = data.get("ai_pending_code")
    pending_bot_id = data.get("ai_pending_bot_id")
    if not pending_code or pending_bot_id != bot_id:
        await safe_answer_callback(
            callback,
            " لا يوجد تعديل جاهز للتطبيق حالياً. اطلب من الذكاء الاصطناعي إصلاحاً أو إضافة أولاً.",
            show_alert=True,
        )
        return

    ok, result_msg = await apply_ai_code_to_bot_file(bot_id, pending_code)
    await state.update_data(ai_pending_code=None, ai_pending_bot_id=None)

    if ok:
        model_key = data.get("ai_active_model") or await get_ai_model_choice(callback.from_user.id)
        try:
            file_name_for_notice = bot_data["file_name"] if "file_name" in bot_data.keys() else str(bot_id)
            await _bump_ai_model_usage_stat(model_key, bot_id, callback.from_user.id, edit_applied=True)
            await notify_admin_ai_file_edit(bot_id, callback.from_user.id, model_key, file_name_for_notice)
        except Exception as e:
            logger.error(f"cb_ai_apply_edit: فشل إشعار الأدمن أو تحديث الإحصاء: {e}", exc_info=True)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="رجوع لهذا البوت",
            callback_data=f"admin_select_bot_{bot_id}" if is_admin_user else f"select_bot_{bot_id}",
            style="danger",
        )]
    ])
    await bot.send_message(callback.message.chat.id, result_msg, reply_markup=kb)


@dp.callback_query_handler(text="ai_send_reply_file", state='*')
async def cb_ai_send_reply_file(callback: types.CallbackQuery, state: FSMContext):
    await safe_answer_callback(callback, " جاري تجهيز الملف...", show_alert=False)
    is_admin_user = await is_admin(callback.from_user.id)
    if not is_admin_user:
        wallet = await get_ai_wallet(callback.from_user.id)
        if not wallet["can_send_files"]:
            await safe_answer_callback(
                callback,
                " إرسال رد الذكاء الاصطناعي كملف متاح فقط مع باقة AI الذهبية (200 ).",
                show_alert=True,
            )
            return

    data = await state.get_data()
    pending_code = data.get("ai_pending_code")
    last_reply = data.get("ai_last_reply_text")
    if pending_code:
        content, filename = pending_code, "ward_ai_fix.py"
    elif last_reply:
        content, filename = last_reply, "ward_ai_reply.txt"
    else:
        await safe_answer_callback(callback, " لا يوجد رد حالياً لإرساله كملف.", show_alert=True)
        return

    sent_ok = await send_text_as_file(callback.message.chat.id, content, filename)
    if not sent_ok:
        await bot.send_message(callback.message.chat.id, " تعذّر إرسال الملف، حاول مرة أخرى.")


@dp.callback_query_handler(text_startswith="browse_folder_", state='*')
async def cb_browse_folder(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        return
    folder_path = callback.data.replace("browse_folder_", "")
    if not os.path.isdir(folder_path):
        await safe_answer_callback(callback, "المجلد غير موجود.", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    text_lines = [f"━━━━━━━━━━━━━━━━━━━\n◆ {folder_path} ◆\n━━━━━━━━━━━━━━━━━━━\n"]
    try:
        entries = sorted(os.listdir(folder_path))
        if not entries:
            text_lines.append("\n(فارغ)")
        for entry in entries[:30]:
            full = os.path.join(folder_path, entry)
            if os.path.isdir(full):
                text_lines.append(f" {entry}/")
                kb.inline_keyboard.append([InlineKeyboardButton(text=entry, callback_data=f"browse_folder_{full}", style="primary")])
            else:
                size = os.path.getsize(full) / 1024
                size_str = f"{size:.1f}KB" if size < 1024 else f"{size/1024:.1f}MB"
                text_lines.append(f" {entry} ({size_str})")
                kb.inline_keyboard.append([InlineKeyboardButton(text=f"حذف: {entry}", callback_data=f"delete_file_{full}", style="danger")])
    except Exception as e:
        text_lines.append(f"\n خطأ: {e}")
    kb.inline_keyboard.append([InlineKeyboardButton(text="رجوع", callback_data="admin_folders", style="danger")])
    await delete_and_send(callback.message.chat.id, callback.from_user.id, "".join(text_lines), kb, callback.message.message_id)


@dp.callback_query_handler(text_startswith="delete_file_", state='*')
async def cb_delete_file(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        return
    file_path = callback.data.replace("delete_file_", "")
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            await safe_answer_callback(callback, " تم الحذف.", show_alert=True)
        else:
            await safe_answer_callback(callback, "الملف غير موجود.", show_alert=True)
    except Exception as e:
        await safe_answer_callback(callback, f" خطأ: {e}", show_alert=True)
    # Refresh folder view
    parent = str(Path(file_path).parent)
    callback.data = f"browse_folder_{parent}"
    await cb_browse_folder(callback, state)


# ─────────────────────────────────────────────
# ADMIN: DELETE ALL MEDIA
# ─────────────────────────────────────────────
@dp.callback_query_handler(text='admin_delete_all_media', state='*')
async def cb_admin_delete_all_media(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        return
    async with db_cursor() as conn:
        conn.execute("DELETE FROM media_messages")
        conn.execute("DELETE FROM section_media")
    text = " تم حذف جميع الوسائط بنجاح."
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="رجوع", callback_data="admin_panel", style="danger")]
    ])
    await delete_and_send(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)


# ─────────────────────────────────────────────
# CHANGE OWNER ID (works for both admin and user — auth checked at apply time)
# ─────────────────────────────────────────────
@dp.callback_query_handler(text_startswith="bot_change_owner2_", state='*')
async def cb_bot_change_owner2(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        return
    bot_id = int(callback.data.split("_")[3])
    await state.update_data(owner_edit_bot_id=bot_id, is_admin_view=True)
    lang = await get_user_language(callback.from_user.id) or "ar"
    text = (
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"◆ {t('change_owner_id', lang)} ◆\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"{t('send_new_owner_id', lang)}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=en(t("back", lang)), callback_data=f"admin_select_bot_{bot_id}", style="danger")]
    ])
    await delete_and_send(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)
    await AdminChangeOwnerState.waiting_new_owner_id.set()


@dp.callback_query_handler(text_startswith="user_bot_change_owner_", state='*')
async def cb_user_bot_change_owner(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    bot_id = int(callback.data.split("_")[4])
    bot_data = await get_bot_by_id(bot_id)
    if not bot_data or bot_data["user_id"] != callback.from_user.id:
        await safe_answer_callback(callback, " البوت غير موجود.", show_alert=True)
        return
    await state.update_data(owner_edit_bot_id=bot_id, is_admin_view=False)
    lang = await get_user_language(callback.from_user.id) or "ar"
    text = (
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"◆ {t('change_owner_id', lang)} ◆\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"{t('send_new_owner_id', lang)}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=en(t("back", lang)), callback_data=f"select_bot_{bot_id}", style="danger")]
    ])
    await delete_and_send(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)
    await AdminChangeOwnerState.waiting_new_owner_id.set()


# ─────────────────────────────────────────────
# BOT DOWNLOAD (admin)
# ─────────────────────────────────────────────
@dp.callback_query_handler(text_startswith="bot_download_", state='*')
async def cb_bot_download(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        return
    bot_id = int(callback.data.split("_")[2])
    bot_data = await get_bot_by_id(bot_id)
    if not bot_data:
        return
    file_path = Path(bot_data["file_path"])
    if not file_path.exists():
        await safe_answer_callback(callback, "الملف غير موجود.", show_alert=True)
        return
    try:
        original_content = await remove_metadata_from_file(file_path)
        temp_file = file_path.parent / f"temp_{file_path.name}"
        async with aiofiles.open(temp_file, mode='w') as f:
            await f.write(original_content)
        await bot.send_document(callback.from_user.id, InputFile(str(temp_file)))
        os.remove(temp_file)
        await safe_answer_callback(callback, " تم إرسال الملف.", show_alert=True)
    except Exception as e:
        await safe_answer_callback(callback, f" خطأ: {e}", show_alert=True)




# ─────────────────────────────────────────────
# VIP: VIEW CODE (large portion)
# ─────────────────────────────────────────────
class VipViewCodeState(StatesGroup):
    pass


@dp.callback_query_handler(text_startswith="vip_view_code_", state='*')
async def cb_vip_view_code(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    user_id = callback.from_user.id
    if not await is_vip_user(user_id):
        await safe_answer_callback(callback, t("vip_required", await get_user_language(user_id) or "ar"), show_alert=True)
        return
    bot_id, is_admin_view, page = parse_view_code_callback(callback.data)
    if is_admin_view is None:
        is_admin_view = await is_admin(user_id)
    bot_data = await get_bot_by_id(bot_id)
    if not bot_data:
        return
    lang = await get_user_language(user_id) or "ar"
    result = await get_file_preview_page(bot_data["file_path"], page=page, lines_per_page=80, skip_metadata=True)
    page_info = f"({result['page'] + 1}/{result['total_pages']})" if result["total_pages"] > 1 else ""
    text = (
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"◆ {t('view_code_title', lang)} {page_info} ◆\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"{t('view_code_desc', lang)}\n\n"
        f"{result['preview']}"
    )
    back_cb = vip_back_target(bot_id, is_admin_view)
    kb_rows = []
    nav_row = []
    if result["has_prev"]:
        nav_row.append(InlineKeyboardButton(text="السابق ‹", callback_data=view_code_callback(bot_id, is_admin_view, result["page"] - 1), style="primary"))
    if result["has_next"]:
        nav_row.append(InlineKeyboardButton(text="التالي ›", callback_data=view_code_callback(bot_id, is_admin_view, result["page"] + 1), style="primary"))
    if nav_row:
        kb_rows.append(nav_row)
    kb_rows.append([InlineKeyboardButton(text=en(t("back", lang)), callback_data=back_cb, style="danger")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    await delete_and_send(callback.message.chat.id, user_id, text, kb, callback.message.message_id)


# ─────────────────────────────────────────────
# VIP: FILE CONTENTS (send as file)
# ─────────────────────────────────────────────
class VipFileContentsState(StatesGroup):
    pass


@dp.callback_query_handler(text_startswith="vip_file_contents_", state='*')
async def cb_vip_file_contents(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    user_id = callback.from_user.id
    if not await is_vip_user(user_id):
        await safe_answer_callback(callback, t("vip_required", await get_user_language(user_id) or "ar"), show_alert=True)
        return
    bot_id, is_admin_view = parse_vip_callback(callback.data)
    if is_admin_view is None:
        is_admin_view = await is_admin(user_id)
    bot_data = await get_bot_by_id(bot_id)
    if not bot_data:
        return
    file_path = Path(bot_data["file_path"])
    if not file_path.exists():
        await safe_answer_callback(callback, "", show_alert=True)
        return
    lang = await get_user_language(user_id) or "ar"
    back_cb = vip_back_target(bot_id, is_admin_view)
    # لوحة بعد إرسال الملف: زر زخرفي (سهم بدون إيموجي) فوق زر الرجوع، وبدون زر تحديث
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="", callback_data=back_cb, style="primary")],
        [InlineKeyboardButton(text=en(t("back", lang)), callback_data=back_cb, style="danger")],
    ])
    try:
        original_content = await remove_metadata_from_file(file_path)
        temp_file = file_path.parent / f"temp_view_{file_path.name}"
        async with aiofiles.open(temp_file, mode='w', encoding='utf-8') as f:
            await f.write(original_content)
        await bot.send_document(user_id, InputFile(str(temp_file)), caption=f" {t('file_contents_title', lang)}: {bot_data['file_name']}")
        os.remove(temp_file)
        await bot.send_message(user_id, f"◆ {t('file_contents_title', lang)} ◆", reply_markup=kb)
        await safe_answer_callback(callback, "", show_alert=True)
    except Exception as e:
        await safe_answer_callback(callback, f" {e}", show_alert=True)


# ─────────────────────────────────────────────
# BOT MAIN LINK (replaces speed test)
# ─────────────────────────────────────────────
@dp.callback_query_handler(text_startswith="bot_main_link_", state='*')
async def cb_bot_main_link(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        return
    bot_id = int(callback.data.split("_")[3])
    bot_data = await get_bot_by_id(bot_id)
    if not bot_data:
        return
    lang = await get_user_language(callback.from_user.id) or "ar"
    token = bot_data["bot_token"] or ""
    bot_username = ""
    if token and ":" in token:
        try:
            bot_info = await Bot(token=token.split(":")[0] + ":" + token.split(":")[1]).get_me()
            bot_username = bot_info.username or ""
        except Exception:
            pass
    if bot_username:
        link = f"https://t.me/{bot_username}"
        text = (
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"◆ {t('bot_link_title', lang)} ◆\n"
            f"━━━━━━━━━━━━━━━━━━━\n\n"
            f" {t('file_label', lang)}: <code>{bot_data['file_name']}</code>\n"
            f" {t('status_label', lang)}: {status_text(bot_data['status'])}\n"
            f" @{bot_username}\n"
            f" <a href=\"{link}\">{link}</a>"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"{t('bot_link_title', lang)} ⁘", url=link, style="success")],
            [InlineKeyboardButton(text=en(t("back", lang)), callback_data=f"admin_select_bot_{bot_id}", style="danger")]
        ])
    else:
        text = (
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"◆ {t('bot_link_title', lang)} ◆\n"
            f"━━━━━━━━━━━━━━━━━━━\n\n"
            f" {t('file_label', lang)}: <code>{bot_data['file_name']}</code>\n"
            f" {t('token_label', lang)}: <code>{token[:10]}...{'●' * 10}</code>\n\n"
            f" لم يتم العثور على اسم البوت. تأكد من صحة التوكن."
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=en(t("back", lang)), callback_data=f"admin_select_bot_{bot_id}", style="danger")]
        ])
    await delete_and_send(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)


@dp.callback_query_handler(text_startswith="user_bot_main_link_", state='*')
async def cb_user_bot_main_link(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    user_id = callback.from_user.id
    bot_id = int(callback.data.split("_")[4])
    bot_data = await get_bot_by_id(bot_id)
    if not bot_data or bot_data["user_id"] != user_id:
        await safe_answer_callback(callback, "", show_alert=True)
        return
    lang = await get_user_language(user_id) or "ar"
    token = bot_data["bot_token"] or ""
    bot_username = ""
    if token and ":" in token:
        try:
            bot_info = await Bot(token=token.split(":")[0] + ":" + token.split(":")[1]).get_me()
            bot_username = bot_info.username or ""
        except Exception:
            pass
    if bot_username:
        link = f"https://t.me/{bot_username}"
        text = (
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"◆ {t('bot_link_title', lang)} ◆\n"
            f"━━━━━━━━━━━━━━━━━━━\n\n"
            f" @{bot_username}\n"
            f" <a href=\"{link}\">{link}</a>"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"{t('bot_link_title', lang)} ⁘", url=link, style="success")],
            [InlineKeyboardButton(text=en(t("back", lang)), callback_data=f"select_bot_{bot_id}", style="danger")]
        ])
    else:
        text = (
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"◆ {t('bot_link_title', lang)} ◆\n"
            f"━━━━━━━━━━━━━━━━━━━\n\n"
            f" لم يتم العثور على اسم البوت. تأكد من صحة التوكن."
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=en(t("back", lang)), callback_data=f"select_bot_{bot_id}", style="danger")]
        ])
    await delete_and_send(callback.message.chat.id, user_id, text, kb, callback.message.message_id)


# ─────────────────────────────────────────────
# BONUS: Bot Health Check (VIP)
# ─────────────────────────────────────────────
@dp.callback_query_handler(text_startswith="vip_health_check_", state='*')
async def cb_vip_health_check(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    user_id = callback.from_user.id
    if not await is_vip_user(user_id):
        await safe_answer_callback(callback, t("vip_required", await get_user_language(user_id) or "ar"), show_alert=True)
        return
    bot_id = int(callback.data.split("_")[3])
    bot_data = await get_bot_by_id(bot_id)
    if not bot_data:
        return
    lang = await get_user_language(user_id) or "ar"
    proc = RUNNING_BOT_PROCESSES.get(bot_id)
    checks = []
    # Process check
    if proc and proc.returncode is None:
        checks.append(f" العملية: تعمل (PID: {proc.pid})")
        try:
            p = None
            mem_mb = p.memory_info().rss / (1024 * 1024)
            cpu_p = p.cpu_percent(interval=0.5)
            checks.append(f" الذاكرة: {mem_mb:.2f} MB")
            checks.append(f" المعالج: {cpu_p:.1f}%")
            checks.append(f" وقت التشغيل: {datetime.now().strftime('%H:%M:%S')}")
        except Exception:
            checks.append(" لا يمكن قراءة بيانات العملية")
    else:
        checks.append(" العملية: متوقفة")
    # Log file check
    log_file = Path(f"logs/bot_{bot_id}.log")
    if log_file.exists():
        size_kb = log_file.stat().st_size / 1024
        checks.append(f" سجل الأخطاء: {size_kb:.1f} KB")
    else:
        checks.append(" سجل الأخطاء: غير موجود")
    # File check
    file_path = Path(bot_data["file_path"])
    if file_path.exists():
        size_kb = file_path.stat().st_size / 1024
        checks.append(f" حجم الملف: {size_kb:.1f} KB")
    else:
        checks.append(" الملف: غير موجود!")
    text = (
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"◆ فحص صحة البوت ◆\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        + "\n".join(checks)
    )
    is_admin_view = await is_admin(user_id)
    back_cb = f"admin_select_bot_{bot_id}" if is_admin_view else f"select_bot_{bot_id}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=en(t("back", lang)), callback_data=back_cb, style="danger")]
    ])
    await delete_and_send(callback.message.chat.id, user_id, text, kb, callback.message.message_id)


# ─────────────────────────────────────────────
# BONUS: Quick Restart All User Bots
# ─────────────────────────────────────────────
@dp.callback_query_handler(text='restart_all_my_bots', state='*')
async def cb_restart_all_my_bots(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback, "", show_alert=False)
    user_id = callback.from_user.id
    lang = await get_user_language(user_id) or "ar"
    bots = await get_user_bots(user_id)
    if not bots:
        await safe_answer_callback(callback, "", show_alert=True)
        return
    restarted = 0
    failed = 0
    for b in bots:
        if b["status"] == "running":
            await stop_bot_process(b["id"])
        started, reason = await run_bot_process(b["id"], b["file_path"])
        if started:
            restarted += 1
        else:
            failed += 1
    text = (
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"◆ إعادة تشغيل الكل ◆\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f" تم تشغيل: {restarted}\n"
        f" فشل: {failed}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=en(t("back", lang)), callback_data="my_bots", style="danger")]
    ])
    await delete_and_send(callback.message.chat.id, user_id, text, kb, callback.message.message_id)

# ─────────────────────────────────────────────
# DECORATE ADMIN PANEL MESSAGE
# ─────────────────────────────────────────────

# ─────────────────────────────────────────────
# ملفات ورد: عرض كل الملفات (بوتات + مواقع) وقت رفعها، صفحة بصفحة عبر سهم
# ─────────────────────────────────────────────
async def get_all_ward_files() -> List[Dict]:
    async with db_cursor() as conn:
        bots_rows = conn.execute("SELECT * FROM bots ORDER BY created_at DESC").fetchall()
        sites_rows = conn.execute("SELECT * FROM sites ORDER BY created_at DESC").fetchall()

    combined = []
    for b in bots_rows:
        combined.append({
            "kind": "bot",
            "id": b["id"],
            "file_name": b["file_name"],
            "file_path": b["file_path"],
            "user_id": b["user_id"],
            "status": b["status"],
            "created_at": b["created_at"],
        })
    for s in sites_rows:
        combined.append({
            "kind": "site",
            "id": s["id"],
            "file_name": s["file_name"],
            "file_path": s["file_path"],
            "user_id": s["user_id"],
            "status": s["status"],
            "created_at": s["created_at"],
        })

    combined.sort(key=lambda x: x["created_at"], reverse=True)
    return combined


@dp.callback_query_handler(text_startswith='ward_files_', state='*')
async def cb_ward_files(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return

    try:
        index = int(callback.data.replace("ward_files_", ""))
    except ValueError:
        index = 0

    files = await get_all_ward_files()
    if not files:
        await edit_or_send_message(
            callback.message.chat.id, callback.from_user.id,
            " ملفات ورد:\n\nلا توجد ملفات مرفوعة حتى الآن.",
            admin_back_keyboard(), callback.message.message_id
        )
        return

    index = max(0, min(index, len(files) - 1))
    f = files[index]
    kind_label = " بوت" if f["kind"] == "bot" else " موقع"

    text = (
        f" ملفات ورد ({index + 1}/{len(files)})\n\n"
        f"{kind_label}\n"
        f" الاسم: <code>{sanitize_html_for_telegram(f['file_name'], max_len=200)}</code>\n"
        f" المستخدم: <code>{f['user_id']}</code>\n"
        f" الحالة: {status_text(f['status'])}\n"
        f" وقت الرفع: <code>{f['created_at']}</code>\n"
    )
    kb = ward_files_keyboard(index, len(files))

    try:
        if callback.message.message_id:
            try:
                await bot.delete_message(callback.message.chat.id, callback.message.message_id)
            except Exception:
                pass
        file_path = Path(f["file_path"])
        if file_path.exists():
            sent = await bot.send_document(
                callback.from_user.id,
                document=InputFile(str(file_path)),
                caption=text,
                reply_markup=kb,
            )
        else:
            sent = await bot.send_message(
                callback.from_user.id,
                text=text + "\n\n الملف غير موجود على القرص.",
                reply_markup=kb,
            )
    except Exception as e:
        logger.error(f"cb_ward_files failed to send document: {e}", exc_info=True)
        await bot.send_message(callback.from_user.id, text=text, reply_markup=kb)


@dp.message_handler(state='*', content_types=types.ContentTypes.ANY)
async def handle_all_messages(message: types.Message, state: FSMContext):
    pass


# ─────────────────────────────────────────────
# ADMIN: ADD FOLDER — Admin clicks button → asks user ID → asks which section
# (bots/sites/both) → asks folder size → asks folder name → creates folder on disk
# ─────────────────────────────────────────────
@dp.callback_query_handler(text='admin_add_folder', state='*')
async def cb_admin_add_folder(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    lang = await get_user_language(callback.from_user.id) or "ar"
    text = (
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"◆ {t('add_folder_title', lang)} ◆\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"{t('add_folder_prompt_user_id', lang)}"
    )
    kb = admin_back_keyboard(lang)
    await delete_and_send(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)
    await AdminAddFolderState.waiting_user_id.set()


@dp.message_handler(state=AdminAddFolderState.waiting_user_id)
async def msg_admin_add_folder_uid(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await state.finish()
        return
    try:
        uid = int(message.text.strip())
    except ValueError:
        lang = await get_user_language(message.from_user.id) or "ar"
        await message.answer(t("add_folder_invalid_id", lang))
        return
    try:
        await message.delete()
    except Exception:
        pass
    lang = await get_user_language(message.from_user.id) or "ar"
    await state.update_data(target_uid=uid)
    text = (
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"◆ {t('add_folder_title', lang)} ◆\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f" {t('user_word', lang)}: <code>{uid}</code>\n\n"
        f"{t('add_folder_prompt_section', lang)}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t("add_folder_section_bots", lang), callback_data="add_folder_section_bots", style="success")],
        [InlineKeyboardButton(text=t("add_folder_section_sites", lang), callback_data="add_folder_section_sites", style="primary")],
        [InlineKeyboardButton(text=t("add_folder_section_both", lang), callback_data="add_folder_section_both", style="success")],
        [InlineKeyboardButton(text=en(t("back", lang)), callback_data="admin_panel", style="danger")],
    ])
    await message.answer(text, reply_markup=kb)
    await AdminAddFolderState.waiting_section.set()


@dp.callback_query_handler(text="add_folder_section_bots", state=AdminAddFolderState.waiting_section)
@dp.callback_query_handler(text="add_folder_section_sites", state=AdminAddFolderState.waiting_section)
@dp.callback_query_handler(text="add_folder_section_both", state=AdminAddFolderState.waiting_section)
async def cb_admin_add_folder_section(callback: types.CallbackQuery, state: FSMContext):
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await state.finish()
        return
    section = callback.data.replace("add_folder_section_", "")  # bots / sites / both
    lang = await get_user_language(callback.from_user.id) or "ar"
    await state.update_data(folder_section=section)
    text = (
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"◆ {t('add_folder_title', lang)} ◆\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"{t('add_folder_prompt_size', lang)}"
    )
    kb = admin_back_keyboard(lang)
    await delete_and_send(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)
    await AdminAddFolderState.waiting_size.set()


@dp.message_handler(state=AdminAddFolderState.waiting_size)
async def msg_admin_add_folder_size(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await state.finish()
        return
    try:
        size_mb = int(message.text.strip())
        if size_mb < 0:
            raise ValueError
    except ValueError:
        lang = await get_user_language(message.from_user.id) or "ar"
        await message.answer(t("add_folder_invalid_size", lang))
        return
    try:
        await message.delete()
    except Exception:
        pass
    lang = await get_user_language(message.from_user.id) or "ar"
    await state.update_data(folder_size_mb=size_mb)
    text = (
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"◆ {t('add_folder_title', lang)} ◆\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"{t('add_folder_prompt_name', lang)}"
    )
    kb = admin_back_keyboard(lang)
    await message.answer(text, reply_markup=kb)
    await AdminAddFolderState.waiting_name.set()


@dp.message_handler(state=AdminAddFolderState.waiting_name)
async def msg_admin_add_folder_name(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await state.finish()
        return
    lang = await get_user_language(message.from_user.id) or "ar"
    data = await state.get_data()
    uid = data.get("target_uid")
    section = data.get("folder_section", "both")
    size_mb = data.get("folder_size_mb", 0)
    raw_name = (message.text or "").strip()

    # /auto → use user_id as folder name
    if raw_name.lower() == "/auto" or not raw_name:
        folder_name = f"user_{uid}"
    else:
        # sanitize: letters/numbers/underscore only
        if not re.match(r"^[A-Za-z0-9_]+$", raw_name):
            await message.answer(t("add_folder_invalid_name", lang))
            return
        folder_name = raw_name

    try:
        await message.delete()
    except Exception:
        pass

    # Determine target paths
    sections_to_create = []
    if section in ("bots", "both"):
        sections_to_create.append(("bots", BOTS_DIR))
    if section in ("sites", "both"):
        sections_to_create.append(("sites", SITES_DIR))

    created_paths = []
    failed = []
    for sec_name, base_dir in sections_to_create:
        # Folder path: uploads/<sec>/<folder_name>
        target_dir = base_dir / folder_name
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            # Drop a .folder_meta.txt inside so the folder is queryable later
            meta_path = target_dir / ".folder_meta.txt"
            async with aiofiles.open(meta_path, mode='w', encoding='utf-8') as f:
                await f.write(
                    f"user_id={uid}\n"
                    f"section={sec_name}\n"
                    f"max_size_mb={size_mb}\n"
                    f"created_at={datetime.now().isoformat()}\n"
                    f"created_by={message.from_user.id}\n"
                )
            created_paths.append(str(target_dir))
            logger.info(f"Admin {message.from_user.id} created folder {target_dir} for user {uid}")
        except Exception as e:
            failed.append(f"{sec_name}/{folder_name}: {e}")

    size_label = f"{size_mb} MB" if size_mb > 0 else "∞"
    if created_paths and not failed:
        text = t("add_folder_created", lang,
                 path="\n".join(created_paths), size=size_label, user_id=uid)
    elif created_paths and failed:
        text = (
            t("add_folder_created", lang,
              path="\n".join(created_paths), size=size_label, user_id=uid)
            + "\n\n " + "\n ".join(failed)
        )
    else:
        text = t("add_folder_failed", lang, reason="; ".join(failed) or "unknown")

    await message.answer(text, reply_markup=admin_back_keyboard(lang))
    await state.finish()


# ─────────────────────────────────────────────
# ADMIN: DELETE USER FILES — Admin clicks button → asks user ID → asks which
# section (bots/sites/both) → stops any running bots + deletes files + DB rows
# ─────────────────────────────────────────────
@dp.callback_query_handler(text='admin_delete_user_files', state='*')
async def cb_admin_delete_user_files(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    lang = await get_user_language(callback.from_user.id) or "ar"
    text = (
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"◆ {t('delete_user_files_title', lang)} ◆\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"{t('delete_user_files_prompt_user_id', lang)}"
    )
    kb = admin_back_keyboard(lang)
    await delete_and_send(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)
    await AdminDeleteUserFilesState.waiting_user_id.set()


@dp.message_handler(state=AdminDeleteUserFilesState.waiting_user_id)
async def msg_admin_delete_user_files_uid(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await state.finish()
        return
    try:
        uid = int(message.text.strip())
    except ValueError:
        await message.answer(" معرف غير صالح.")
        return
    try:
        await message.delete()
    except Exception:
        pass
    lang = await get_user_language(message.from_user.id) or "ar"
    await state.update_data(target_uid=uid)
    text = (
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"◆ {t('delete_user_files_title', lang)} ◆\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f" {t('user_word', lang)}: <code>{uid}</code>\n\n"
        f"{t('delete_user_files_prompt_section', lang)}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t("add_folder_section_bots", lang), callback_data="delete_user_files_section_bots", style="danger")],
        [InlineKeyboardButton(text=t("add_folder_section_sites", lang), callback_data="delete_user_files_section_sites", style="danger")],
        [InlineKeyboardButton(text=t("add_folder_section_both", lang), callback_data="delete_user_files_section_both", style="danger")],
        [InlineKeyboardButton(text=en(t("back", lang)), callback_data="admin_panel", style="primary")],
    ])
    await message.answer(text, reply_markup=kb)
    await AdminDeleteUserFilesState.waiting_section.set()


@dp.callback_query_handler(text="delete_user_files_section_bots", state=AdminDeleteUserFilesState.waiting_section)
@dp.callback_query_handler(text="delete_user_files_section_sites", state=AdminDeleteUserFilesState.waiting_section)
@dp.callback_query_handler(text="delete_user_files_section_both", state=AdminDeleteUserFilesState.waiting_section)
async def cb_admin_delete_user_files_section(callback: types.CallbackQuery, state: FSMContext):
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await state.finish()
        return
    section = callback.data.replace("delete_user_files_section_", "")  # bots / sites / both
    lang = await get_user_language(callback.from_user.id) or "ar"
    data = await state.get_data()
    uid = data.get("target_uid")

    deleted_bots = 0
    deleted_sites = 0

    if section in ("bots", "both"):
        async with db_cursor() as conn:
            bot_rows = conn.execute("SELECT id, file_path FROM bots WHERE user_id = ?", (uid,)).fetchall()
        for b in bot_rows:
            try:
                # Stop the bot process if running
                await stop_bot_process(b["id"])
                # Remove the file from disk
                fp = Path(b["file_path"])
                if fp.exists():
                    try:
                        os.remove(fp)
                    except Exception as e:
                        logger.warning(f"Failed to remove file {fp}: {e}")
            except Exception as e:
                logger.warning(f"Failed to clean bot #{b['id']}: {e}")
        async with db_cursor() as conn:
            cur = conn.execute("DELETE FROM bots WHERE user_id = ?", (uid,))
            deleted_bots = cur.rowcount if cur.rowcount is not None else len(bot_rows)

    if section in ("sites", "both"):
        async with db_cursor() as conn:
            site_rows = conn.execute("SELECT id, file_path FROM sites WHERE user_id = ?", (uid,)).fetchall()
        for s in site_rows:
            try:
                fp = Path(s["file_path"])
                if fp.exists():
                    try:
                        os.remove(fp)
                    except Exception as e:
                        logger.warning(f"Failed to remove file {fp}: {e}")
            except Exception as e:
                logger.warning(f"Failed to clean site #{s['id']}: {e}")
        async with db_cursor() as conn:
            cur = conn.execute("DELETE FROM sites WHERE user_id = ?", (uid,))
            deleted_sites = cur.rowcount if cur.rowcount is not None else len(site_rows)

    await state.finish()

    if section == "bots":
        if deleted_bots == 0:
            text = t("delete_user_files_none", lang)
        else:
            text = t("delete_user_files_confirm_bots", lang, n=deleted_bots, user_id=uid)
    elif section == "sites":
        if deleted_sites == 0:
            text = t("delete_user_files_none", lang)
        else:
            text = t("delete_user_files_confirm_sites", lang, n=deleted_sites, user_id=uid)
    else:  # both
        if deleted_bots == 0 and deleted_sites == 0:
            text = t("delete_user_files_none", lang)
        else:
            text = t("delete_user_files_confirm_both", lang, bots=deleted_bots, sites=deleted_sites, user_id=uid)

    kb = admin_back_keyboard(lang)
    await delete_and_send(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)


# ─────────────────────────────────────────────
# شحن الرصيد عبر نجوم تيليغرام (Telegram Stars)
# ─────────────────────────────────────────────

def _charge_packages_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t("charge_pkg_15", lang), callback_data="stars_pay_15", style="success")],
        [InlineKeyboardButton(text=t("charge_pkg_25", lang), callback_data="stars_pay_25", style="success")],
        [InlineKeyboardButton(text=t("charge_pkg_50", lang), callback_data="stars_pay_50", style="success")],
        [InlineKeyboardButton(text=t("charge_pkg_100", lang), callback_data="stars_pay_100", style="success")],
        [InlineKeyboardButton(text=en(t('back', lang)), callback_data="referral", style="danger")],
    ])


async def _send_charge_packages_to_user(chat_id: int, user_id: int, lang: str, message_id=None):
    text = (
        f"{t('charge_balance_title', lang)}\n\n"
        f"{t('charge_balance_desc', lang)}\n\n"
        f"┌────────────────────────┐\n"
        f"│ 15 → 6 │\n"
        f"│ 25 → 12 │\n"
        f"│ 50 → 21 │\n"
        f"│ 100 → 50 │\n"
        f"└────────────────────────┘\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    kb = _charge_packages_keyboard(lang)
    await edit_or_send_message(chat_id, user_id, text, kb, message_id)


@dp.callback_query_handler(text='charge_balance', state='*')
async def cb_charge_balance(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    user = await get_user(callback.from_user.id)
    lang = await get_user_language(callback.from_user.id) or "ar"

    auto_charge = await get_config_value("auto_charge_approve")

    if auto_charge == "1":
        await _send_charge_packages_to_user(callback.message.chat.id, callback.from_user.id, lang, callback.message.message_id)
        return

    async with db_cursor() as conn:
        pending = conn.execute(
            "SELECT id FROM charge_requests WHERE user_id = ? AND status = 'pending'",
            (callback.from_user.id,),
        ).fetchone()
        if pending:
            await edit_or_send_message(
                callback.message.chat.id, callback.from_user.id,
                f"{t('charge_waiting_title', lang)}\n\n{t('charge_waiting_msg', lang)}",
                back_keyboard(lang), callback.message.message_id
            )
            return

        cur = conn.execute(
            "INSERT INTO charge_requests (user_id, status) VALUES (?, 'pending')",
            (callback.from_user.id,),
        )
        req_id = cur.lastrowid

    await edit_or_send_message(
        callback.message.chat.id, callback.from_user.id,
        f"{t('charge_waiting_title', lang)}\n\n{t('charge_waiting_msg', lang)}",
        back_keyboard(lang), callback.message.message_id
    )

    try:
        username = user["username"] or "N/A"
        first_name = user["first_name"] or "N/A"
        admin_text = t("admin_charge_request", lang, user_id=callback.from_user.id, username=username, first_name=first_name)
        admin_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="موافقة ", callback_data=f"approve_charge_{req_id}_{callback.from_user.id}", style="success"),
             InlineKeyboardButton(text="رفض ", callback_data=f"reject_charge_{req_id}_{callback.from_user.id}", style="danger")],
        ])
        admin_msg = await bot.send_message(OWNER_ID, admin_text, reply_markup=admin_kb)
        async with db_cursor() as conn:
            conn.execute("UPDATE charge_requests SET admin_message_id = ? WHERE id = ?", (admin_msg.message_id, req_id))
    except Exception as e:
        logger.error(f"Failed to notify admin about charge request: {e}", exc_info=True)


@dp.callback_query_handler(text_startswith='approve_charge_', state='*')
async def cb_approve_charge(callback: types.CallbackQuery, state: FSMContext):
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        return
    parts = callback.data.split('_')
    if len(parts) < 4:
        return
    try:
        req_id = int(parts[2])
        target_user_id = int(parts[3])
    except (IndexError, ValueError):
        return

    async with db_cursor() as conn:
        conn.execute("UPDATE charge_requests SET status = 'approved' WHERE id = ?", (req_id,))

    try:
        await bot.edit_message_reply_markup(callback.message.chat.id, callback.message.message_id, reply_markup=None)
    except Exception:
        pass

    try:
        await bot.edit_message_caption(
            callback.message.chat.id, callback.message.message_id,
            caption=callback.message.caption + "\n\n تمت الموافقة على الطلب.",
        )
    except Exception:
        try:
            await bot.send_message(callback.message.chat.id, " تمت الموافقة على طلب الشحن.")
        except Exception:
            pass

    target_lang = await get_user_language(target_user_id) or "ar"
    try:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t("charge_approved_to_user_btn", target_lang), callback_data="charge_packages_show", style="success")],
            [InlineKeyboardButton(text=en(t('main_menu_btn', target_lang)), callback_data="main_menu", style="danger")],
        ])
        await bot.send_message(
            target_user_id,
            t("charge_approved_notif", target_lang),
            reply_markup=kb,
        )
    except Exception as e:
        logger.error(f"Failed to notify user {target_user_id} about charge approval: {e}")


@dp.callback_query_handler(text_startswith='reject_charge_', state='*')
async def cb_reject_charge(callback: types.CallbackQuery, state: FSMContext):
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        return
    parts = callback.data.split('_')
    if len(parts) < 4:
        return
    try:
        req_id = int(parts[2])
        target_user_id = int(parts[3])
    except (IndexError, ValueError):
        return

    async with db_cursor() as conn:
        conn.execute("UPDATE charge_requests SET status = 'rejected' WHERE id = ?", (req_id,))

    try:
        await bot.edit_message_caption(
            callback.message.chat.id, callback.message.message_id,
            caption=callback.message.caption + "\n\n تم رفض الطلب.",
        )
    except Exception:
        try:
            await bot.send_message(callback.message.chat.id, " تم رفض طلب الشحن.")
        except Exception:
            pass

    target_lang = await get_user_language(target_user_id) or "ar"
    try:
        await bot.send_message(target_user_id, t("charge_rejected_notif", target_lang))
    except Exception:
        pass


@dp.callback_query_handler(text='charge_packages_show', state='*')
async def cb_charge_packages_show(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    lang = await get_user_language(callback.from_user.id) or "ar"
    await _send_charge_packages_to_user(callback.message.chat.id, callback.from_user.id, lang, callback.message.message_id)


# ─────────────────────────────────────────────
# شحن رصيد الذكاء الاصطناعي (قسائم AI عبر Telegram Stars)
# ─────────────────────────────────────────────
def _ai_charge_keyboard(back_cb: str = "main_menu") -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for key, pkg in AI_PACKAGES.items():
        short = key.split('_')[-1]  # "1" / "2" / "3"
        kb.inline_keyboard.append([
            InlineKeyboardButton(text=pkg["label"], callback_data=f"aicharge_buy_{short}", style="success")
        ])
    kb.inline_keyboard.append([InlineKeyboardButton(text="رجوع ‹", callback_data=back_cb, style="danger")])
    return kb


async def _send_ai_charge_menu(chat_id: int, user_id: int, message_id=None, back_cb: str = "main_menu"):
    wallet = await get_ai_wallet(user_id)
    text = (
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"◆ شحن رصيد الذكاء الاصطناعي ◆\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f" رصيدك الحالي: <b>{wallet['ai_questions_balance']}</b> سؤال\n\n"
        f"اختر باقتك — الدفع فوري عبر نجوم تيليغرام \n\n"
        f"┌────────────────────────────┐\n"
        f"│ 35 ← 20 سؤال │\n"
        f"│ 70 ← 50 سؤال │\n"
        f"│ 200 ← 120 سؤال │\n"
        f"│ + قراءة/تعديل الملفات │\n"
        f"│ + قراءة السجل │\n"
        f"│ + إرسال ملفات للذكاء │\n"
        f"└────────────────────────────┘"
    )
    kb = _ai_charge_keyboard(back_cb)
    await edit_or_send_message(chat_id, user_id, text, kb, message_id)


@dp.callback_query_handler(text='ai_charge_menu', state='*')
async def cb_ai_charge_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await safe_answer_callback(callback)
    await _send_ai_charge_menu(callback.message.chat.id, callback.from_user.id, callback.message.message_id)


@dp.callback_query_handler(text_startswith='aicharge_buy_', state='*')
async def cb_ai_charge_buy(callback: types.CallbackQuery, state: FSMContext):
    await safe_answer_callback(callback)
    short = callback.data.split('_')[-1]
    package_key = f"ai_pkg_{short}"
    pkg = AI_PACKAGES.get(package_key)
    if not pkg:
        await safe_answer_callback(callback, " باقة غير موجودة.", show_alert=True)
        return

    try:
        await bot.send_invoice(
            callback.message.chat.id,
            title=f"شحن رصيد AI — {pkg['stars']} ",
            description=f" إضافة {pkg['questions']} سؤال لرصيد الذكاء الاصطناعي\n المبلغ: {pkg['stars']} نجمة تيليغرام",
            payload=f"aipkg_{short}_{callback.from_user.id}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label=f"+{pkg['questions']} سؤال AI", amount=pkg['stars'])],
        )
    except Exception as e:
        logger.error(f"Failed to send AI Stars invoice: {e}", exc_info=True)
        lang = await get_user_language(callback.from_user.id) or "ar"
        try:
            await bot.send_message(
                callback.message.chat.id,
                t("error_with_back", lang),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=en(t('main_menu_btn', lang)), callback_data="main_menu", style="danger")],
                ])
            )
        except Exception:
            pass


@dp.callback_query_handler(text='admin_auto_charge', state='*')
async def cb_admin_auto_charge(callback: types.CallbackQuery, state: FSMContext):
    await safe_answer_callback(callback)
    if not await is_admin(callback.from_user.id):
        await safe_answer_callback(callback, " غير مسموح", show_alert=True)
        return
    current = await get_config_value("auto_charge_approve")
    if current == "1":
        await set_config_value("auto_charge_approve", "0")
        status_text = " مغلق — طلبات الشحن تحتاج موافقة يدوية"
    else:
        await set_config_value("auto_charge_approve", "1")
        status_text = " مفعّل — طلبات الشحن تظهر فوراً لكل المستخدمين"

    lang = await get_user_language(callback.from_user.id) or "ar"
    text = (
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"◆ {t('adm_auto_charge', lang)} ◆\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"{status_text}\n\n"
        f"{t('adm_auto_charge_desc', lang)}"
    )
    kb = admin_back_keyboard(lang)
    await edit_or_send_message(callback.message.chat.id, callback.from_user.id, text, kb, callback.message.message_id)


@dp.callback_query_handler(text_startswith='stars_pay_', state='*')
async def cb_stars_pay(callback: types.CallbackQuery, state: FSMContext):
    await safe_answer_callback(callback)
    try:
        stars = int(callback.data.split('_')[2])
    except (IndexError, ValueError):
        await safe_answer_callback(callback, " طلب غير صالح.", show_alert=True)
        return

    if stars not in STARS_PACKAGES:
        await safe_answer_callback(callback, " باقة غير موجودة.", show_alert=True)
        return

    points = STARS_PACKAGES[stars]
    lang = await get_user_language(callback.from_user.id) or "ar"

    try:
        await bot.send_invoice(
            callback.message.chat.id,
            title=f"شحن رصيد EYRX — {stars} ",
            description=f" إضافة {points} نقطة لرصيدك في EYRX Hosting\n المبلغ: {stars} نجمة تيليغرام",
            payload=f"stars_{stars}_{points}_{callback.from_user.id}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label=f"+{points} {t('points_word', lang)}", amount=stars)],
        )
    except Exception as e:
        logger.error(f"Failed to send Stars invoice: {e}", exc_info=True)
        try:
            await bot.send_message(
                callback.message.chat.id,
                t("error_with_back", lang),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=en(t('main_menu_btn', lang)), callback_data="main_menu", style="danger")],
                ])
            )
        except Exception:
            pass


@dp.pre_checkout_query_handler(state='*')
async def process_pre_checkout_query(pre_checkout_query: types.PreCheckoutQuery):
    try:
        payload = pre_checkout_query.invoice_payload

        # ── قسائم شحن الذكاء الاصطناعي: payload = "aipkg_<package_key>_<user_id>"
        if payload.startswith("aipkg_"):
            payload_parts = payload.split('_')
            if len(payload_parts) != 3:
                await pre_checkout_query.answer(ok=False, error_message="Invalid invoice payload.")
                return
            package_key = f"ai_pkg_{payload_parts[1]}"
            user_id = int(payload_parts[2])
            if package_key not in AI_PACKAGES:
                await pre_checkout_query.answer(ok=False, error_message="Package mismatch.")
                return
            if pre_checkout_query.from_user.id != user_id:
                await pre_checkout_query.answer(ok=False, error_message="User ID mismatch.")
                return
            await pre_checkout_query.answer(ok=True)
            return

        payload_parts = payload.split('_')
        if len(payload_parts) != 4 or payload_parts[0] != "stars":
            await pre_checkout_query.answer(ok=False, error_message="Invalid invoice payload.")
            return
        stars = int(payload_parts[1])
        points = int(payload_parts[2])
        user_id = int(payload_parts[3])

        if stars not in STARS_PACKAGES or STARS_PACKAGES[stars] != points:
            await pre_checkout_query.answer(ok=False, error_message="Package mismatch.")
            return

        if pre_checkout_query.from_user.id != user_id:
            await pre_checkout_query.answer(ok=False, error_message="User ID mismatch.")
            return

        await pre_checkout_query.answer(ok=True)
    except Exception as e:
        logger.error(f"Pre-checkout error: {e}", exc_info=True)
        try:
            await pre_checkout_query.answer(ok=False, error_message="An error occurred, try again.")
        except Exception:
            pass


@dp.message_handler(content_types=types.ContentType.SUCCESSFUL_PAYMENT, state='*')
async def process_successful_payment(message: types.Message, state: FSMContext):
    try:
        payment = message.successful_payment
        payload = payment.invoice_payload

        # ── قسائم شحن الذكاء الاصطناعي
        if payload.startswith("aipkg_"):
            payload_parts = payload.split('_')
            if len(payload_parts) != 3:
                return
            package_key = f"ai_pkg_{payload_parts[1]}"
            user_id = int(payload_parts[2])
            if package_key not in AI_PACKAGES:
                return

            pkg = AI_PACKAGES[package_key]
            await add_ai_package_to_user(user_id, package_key)
            wallet = await get_ai_wallet(user_id)

            lang = await get_user_language(user_id) or "ar"
            perks = ""
            if pkg["can_read_files"]:
                perks = (
                    "\n\n صلاحيات إضافية مفعّلة الآن:\n"
                    " قراءة الملفات\n قراءة السجل\n تعديل فوري على الملف\n إرسال ملفات للذكاء"
                )
            text = (
                f" تم شحن رصيد الذكاء الاصطناعي بنجاح!\n\n"
                f" الباقة: <b>{pkg['label']}</b>\n"
                f" المبلغ المدفوع: <b>{pkg['stars']}</b> نجمة\n"
                f" الأسئلة المضافة: <b>{pkg['questions']}</b>\n"
                f" رصيدك الحالي من الأسئلة: <b>{wallet['ai_questions_balance']}</b>"
                f"{perks}"
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=en(t('main_menu_btn', lang)), callback_data="main_menu", style="success")],
            ])
            await bot.send_message(message.chat.id, text, reply_markup=kb)

            try:
                admin_msg = (
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"◆ شحن رصيد AI ناجح ◆\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f" المستخدم: <code>{user_id}</code>\n"
                    f" المبلغ: <b>{pkg['stars']}</b> نجمة\n"
                    f" الأسئلة المضافة: <b>{pkg['questions']}</b>\n"
                    f" الرصيد الجديد: <b>{wallet['ai_questions_balance']}</b>"
                )
                await bot.send_message(OWNER_ID, admin_msg)
            except Exception:
                pass
            return

        payload_parts = payload.split('_')
        if len(payload_parts) != 4 or payload_parts[0] != "stars":
            return

        stars = int(payload_parts[1])
        points = int(payload_parts[2])
        user_id = int(payload_parts[3])

        if stars not in STARS_PACKAGES or STARS_PACKAGES[stars] != points:
            return

        await update_user_points(user_id, points)

        lang = await get_user_language(user_id) or "ar"
        user = await get_user(user_id)
        total = user['points'] if user else points

        text = (
            f"{t('payment_success_title', lang)}\n\n"
            f"{t('payment_success_msg', lang, pts=points, stars=stars, total=total)}"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=en(t('main_menu_btn', lang)), callback_data="main_menu", style="success")],
        ])
        await bot.send_message(message.chat.id, text, reply_markup=kb)

        try:
            admin_msg = (
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"◆ عملية دفع ناجحة ◆\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f" المستخدم: <code>{user_id}</code>\n"
                f" المبلغ المدفوع: <b>{stars}</b> نجمة\n"
                f" النقاط المضافة: <b>{points}</b>\n"
                f" رصيد المستخدم الجديد: <b>{total}</b>"
            )
            await bot.send_message(OWNER_ID, admin_msg)
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Payment processing error: {e}", exc_info=True)


# ─────────────────────────────────────────────
# تسجيل الـ Middleware الخاص بالبوابة الإجبارية (لغة + اشتراك)
# ─────────────────────────────────────────────
# ملاحظة: تم إزالة تسجيل DuplicateUpdateGuardMiddleware مؤقتاً لأنه مصدر خطر
# محتمل غير ضروري (لا يحل مشكلة عمليتين Python منفصلتين فعلياً، لأن كل عملية
# لها كاش ذاكرة مستقل)، والأولوية القصوى الآن استقرار استجابة الأزرار.
dp.middleware.setup(DuplicateUpdateGuardMiddleware())
dp.middleware.setup(MandatoryGateMiddlewareSafe())


# ─────────────────────────────────────────────
# ENTRYPOINT مع حماية كاملة من الانهيار
# ─────────────────────────────────────────────
async def ensure_default_force_sub():
    async with db_cursor() as conn:
        row = conn.execute(
            "SELECT id FROM force_sub_targets WHERE identifier = ?", ("@Eyrx_c",)
        ).fetchone()
        if not row:
            conn.execute("DELETE FROM force_sub_targets")
            conn.execute(
                "INSERT INTO force_sub_targets (target_type, display_name, identifier, url) VALUES (?, ?, ?, ?)",
                ("channel", "اشترك بالقناة", "@Eyrx_c", "https://t.me/Eyrx_c"),
            )


async def send_force_sub(chat_id, lang):
    kb = await force_sub_keyboard(lang)
    text = "يجب الاشتراك في القنوات أدناه لاستخدام البوت:"
    try:
        await bot.request("sendMessage", {
            "chat_id": chat_id,
            "text": text,
            "reply_markup": json.dumps(kb.to_python()),
            "message_effect_id": "5104841245755180586",
        })
    except Exception as e:
        logger.warning(f"send_force_sub: effect failed, fallback: {e}")
        await bot.send_message(chat_id, text, reply_markup=kb)


async def _polling_loop():
    backoff = 5
    max_backoff = 60
    while True:
        try:
            logger.info("Starting polling...")
            await dp.start_polling()
            logger.info("Polling stopped normally.")
            break
        except (asyncio.CancelledError, KeyboardInterrupt):
            logger.info("Polling cancelled by user/system, shutting down.")
            raise
        except Exception as e:
            error_text = str(e)
            if "Conflict" in error_text or "terminated by other getUpdates" in error_text:
                logger.critical(
                    " السبب الفعلي لعدم استجابة أي زر بالبوت: توجد عملية Python أخرى "
                    "شغّالة حالياً بنفس توكن هذا البوت (Conflict: terminated by other "
                    "getUpdates). تيليجرام يسمح باتصال getUpdates واحد فقط بالتوكن بنفس "
                    "الوقت، فطالما هناك عمليتان شغالتان، كلتاهما لن تستقبل أي تحديثات "
                    "بشكل مستقر.\n"
                    "الحل: أوقف كل العمليات القديمة قبل التشغيل من جديد، مثلاً على Termux: "
                    "pkill -f python ، ثم أعد تشغيل البوت مرة واحدة فقط."
                )
                # نرجع بسرعة أكبر من الـ backoff العادي حتى لا يبقى البوت متوقفاً
                # لفترة طويلة إذا كان التعارض قد انتهى فعلياً (العملية القديمة أُغلقت).
                await asyncio.sleep(3)
                continue
            logger.error(f"Polling crashed unexpectedly: {e}", exc_info=True)
            logger.info(f"Restarting polling in {backoff} seconds...")
            try:
                await asyncio.sleep(backoff)
            except Exception:
                pass
            backoff = min(backoff * 2, max_backoff)
            continue
        else:
            backoff = 5


async def start_static_file_server():
    """يشغّل سيرفر ملفات ستاتيك حقيقي (aiohttp) يقدّم محتوى SITES_DIR
    ليجعل روابط المواقع المرفوعة تعمل فعلياً بدل الرابط الوهمي القديم.

    يدعم أيضاً تنفيذ ملفات PHP فعلياً (وليس فقط تقديمها كنص خام) إذا كان مفسّر
    PHP متوفراً على السيرفر (php-cgi)، عبر تشغيله كعملية فرعية لكل طلب ملف .php
    وإرجاع ناتج التنفيذ الحقيقي كـ HTML. طول ما البوت شغال، هذا السيرفر شغال
    ومستمر بالعمل بشكل متوازٍ مع استقبال رسائل تيليجرام (polling)، بدون أي علاقة
    بينهما — توقف أحدهما لا يوقف الآخر.

    محمي بالكامل من إيقاف تشغيل البوت الأساسي: إذا فشل بدء هذا السيرفر لأي سبب
    (مثل البورت محجوز مسبقاً من عملية قديمة لم تُغلق بشكل صحيح)، يُسجَّل تحذير
    واضح بالسبب والحل، ويستمر البوت بالعمل بشكل طبيعي بدون استضافة المواقع فقط،
    بدل إيقاف كل شيء بسبب ميزة إضافية غير أساسية لعمل البوت."""
    try:
        from aiohttp import web
    except ImportError:
        logger.error("aiohttp غير متوفرة؛ لن يعمل سيرفر استضافة المواقع الستاتيكي. ثبّت aiohttp لتفعيل الروابط الحقيقية.")
        return

    php_cgi_path = shutil.which("php-cgi") or shutil.which("php")
    php_available = php_cgi_path is not None
    if php_available:
        logger.info(f" مفسّر PHP متوفر ({php_cgi_path})؛ ملفات .php ستُنفَّذ فعلياً وليس كنص خام.")
    else:
        logger.warning(
            " لم يُعثر على PHP بالسيرفر (لا php-cgi ولا php بالـ PATH). ملفات .php المرفوعة "
            "ستُقدَّم كنص خام غير منفَّذ. لتفعيل تشغيل PHP فعلياً، ثبّته على Termux عبر: "
            "pkg install php"
        )

    async def handle_site_request(request: "web.Request") -> "web.StreamResponse":
        rel_path = request.match_info.get("tail", "")
        requested_path = (SITES_DIR / rel_path).resolve()
        # حماية من الخروج عن مجلد SITES_DIR (path traversal)
        try:
            requested_path.relative_to(SITES_DIR.resolve())
        except ValueError:
            return web.Response(status=403, text="Forbidden")

        if requested_path.is_dir():
            index_php = requested_path / "index.php"
            index_html = requested_path / "index.html"
            if php_available and index_php.exists():
                requested_path = index_php
            elif index_html.exists():
                requested_path = index_html
            else:
                return web.Response(status=404, text="404 Not Found")

        if not requested_path.exists() or not requested_path.is_file():
            return web.Response(status=404, text="404 Not Found")

        if requested_path.suffix == ".php":
            if not php_available:
                # لا يوجد مفسّر PHP؛ نعرض النص الخام كحل احتياطي بدل فشل كامل.
                try:
                    content = requested_path.read_text(encoding="utf-8", errors="ignore")
                except Exception as e:
                    return web.Response(status=500, text=f"Error reading file: {e}")
                return web.Response(text=content, content_type="text/plain")

            try:
                proc = await asyncio.create_subprocess_exec(
                    php_cgi_path,
                    str(requested_path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(requested_path.parent),
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
                if proc.returncode != 0:
                    logger.warning(f"PHP execution failed for {requested_path}: {stderr.decode(errors='ignore')[:500]}")
                    return web.Response(status=500, text="500 Internal Server Error (PHP execution failed)")
                output = stdout.decode(errors="ignore")
                is_real_cgi = "cgi" in os.path.basename(php_cgi_path).lower()
                if is_real_cgi:
                    # php-cgi يُرجع رؤوس HTTP فعلية بأول السطور، نفصلها عن المحتوى.
                    if "\r\n\r\n" in output:
                        _headers, _, body = output.partition("\r\n\r\n")
                    elif "\n\n" in output:
                        _headers, _, body = output.partition("\n\n")
                    else:
                        body = output
                else:
                    # php CLI العادي لا يُرجع رؤوس HTTP؛ الناتج كامل هو المحتوى الفعلي.
                    body = output
                return web.Response(text=body, content_type="text/html")
            except asyncio.TimeoutError:
                return web.Response(status=504, text="504 Gateway Timeout (PHP execution took too long)")
            except Exception as e:
                logger.error(f"PHP execution error for {requested_path}: {e}", exc_info=True)
                return web.Response(status=500, text="500 Internal Server Error")

        return web.FileResponse(requested_path)

    try:
        app = web.Application()
        app.router.add_get("/{tail:.*}", handle_site_request)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", SITE_SERVER_PORT)
        await site.start()
    except OSError as e:
        logger.error(
            f" فشل تشغيل سيرفر استضافة المواقع على البورت {SITE_SERVER_PORT}: {e}\n"
            f"السبب الأشيع: عملية سابقة للبوت لم تُغلق بشكل صحيح وما زالت تحجز هذا البورت.\n"
            f"الحل: أوقف أي عملية بايثون قديمة للبوت قبل التشغيل من جديد "
            f"(مثال على Termux: pkill -f python)، أو غيّر البورت عبر "
            f"export SITE_SERVER_PORT=8083 مثلاً. البوت سيستمر بالعمل الآن "
            f"بدون استضافة المواقع فقط."
        )
        return
    except Exception as e:
        logger.error(f" فشل غير متوقع بتشغيل سيرفر استضافة المواقع: {e}", exc_info=True)
        return

    current_host_url = await get_site_host_url()
    logger.info(f"Static+PHP site file server started on 0.0.0.0:{SITE_SERVER_PORT} (public URL base: {current_host_url})")
    if not is_valid_public_url(current_host_url):
        logger.warning(
            " رابط استضافة المواقع يستخدم القيمة الافتراضية (localhost) وهي غير قابلة للفتح من هاتف "
            "المستخدمين. روابط المواقع 'approved' لن تظهر بزر URL حتى تضبط الرابط الحقيقي عبر "
            "زر 'ربط IP/دومين المواقع' بلوحة الأدمن، أو متغير البيئة SITE_HOST_PUBLIC_URL."
        )


# ─────────────────────────────────────────────
# KILL CONFLICTING PROCESSES (AUTO-FIX) 
# ─────────────────────────────────────────────
def kill_old_bot_processes():
    try:
        subprocess.run(["pkill", "-f", "python.*warddddddd-23.py"], capture_output=True)
        print(" تم إيقاف العمليات القديمة.")
    except Exception as e:
        print(f" {e}")

if __name__ == "__main__":
    async def main():
        kill_old_bot_processes()  # <---- السطر الجديد الوحيد المضاف
        await init_db()
        await ensure_default_force_sub()
        try:
            updated_count = await update_all_site_urls_to_real_hosting()
            logger.info(f"تم تحديث {updated_count} رابط موقع لاستخدام الاستضافة الحقيقية الجديدة.")
        except Exception as e:
            logger.error(f"فشل تحديث روابط المواقع القديمة: {e}", exc_info=True)
        await start_static_file_server()
        await _polling_loop()

    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped by user.")
    except Exception as e:
        logger.critical(f"Fatal error outside polling loop: {e}", exc_info=True)
        raise