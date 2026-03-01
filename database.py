import sqlite3
import contextlib
import time
import random
from datetime import datetime, date
from typing import Optional
from logger import get_logger

log = get_logger("database")
DB_PATH = "vpn_bot.db"

# Retry settings for database locked errors
MAX_RETRIES = 5
RETRY_DELAY_BASE = 0.1  # seconds


def _execute_with_retry(db, operation, *args, **kwargs):
    """
    Execute a database operation with retry on 'database is locked' errors.
    Uses exponential backoff with jitter.
    """
    last_exception = None
    for attempt in range(MAX_RETRIES):
        try:
            return operation(*args, **kwargs)
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e) and attempt < MAX_RETRIES - 1:
                delay = RETRY_DELAY_BASE * (2 ** attempt) + random.uniform(0, 0.1)
                log.warning(f"Database locked, retrying in {delay:.2f}s (attempt {attempt + 1}/{MAX_RETRIES})")
                time.sleep(delay)
            else:
                last_exception = e
                break
    if last_exception:
        raise last_exception


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextlib.contextmanager
def get_db():
    conn = _connect()
    try:
        yield conn
        _execute_with_retry(conn, conn.commit)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Create tables if they don't exist."""
    with get_db() as db:
        # Основная таблица пользователей
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id       INTEGER UNIQUE NOT NULL,
                username          TEXT,
                uuid              TEXT,
                subscription_end  TEXT,
                active            INTEGER DEFAULT 0,
                last_payment_id   TEXT UNIQUE,
                plan_days         INTEGER DEFAULT 30,
                created_at        TEXT NOT NULL,
                referred_by       INTEGER,
                trial_used        INTEGER DEFAULT 0,
                subscribed_channel INTEGER DEFAULT 0,
                FOREIGN KEY (referred_by) REFERENCES users(telegram_id)
            )
        """)
        
        # Добавляем новые колонки в существующую таблицу users (если они отсутствуют)
        try:
            db.execute("ALTER TABLE users ADD COLUMN referred_by INTEGER")
        except sqlite3.OperationalError:
            pass  # Колонка уже существует
        
        try:
            db.execute("ALTER TABLE users ADD COLUMN trial_used INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        
        try:
            db.execute("ALTER TABLE users ADD COLUMN subscribed_channel INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        
        # Лог платежей
        db.execute("""
            CREATE TABLE IF NOT EXISTS payment_log (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                payment_id    TEXT UNIQUE NOT NULL,
                telegram_id   INTEGER NOT NULL,
                amount        REAL,
                status        TEXT,
                gateway       TEXT,
                processed_at  TEXT NOT NULL
            )
        """)
        
        # Промокоды
        db.execute("""
            CREATE TABLE IF NOT EXISTS promo_codes (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                code            TEXT UNIQUE NOT NULL,
                bonus_days      INTEGER NOT NULL,
                max_uses        INTEGER,
                used_count      INTEGER DEFAULT 0,
                active          INTEGER DEFAULT 1,
                created_at      TEXT NOT NULL,
                created_by      INTEGER
            )
        """)
        
        # Использование промокодов
        db.execute("""
            CREATE TABLE IF NOT EXISTS promo_code_uses (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                promo_code_id   INTEGER NOT NULL,
                telegram_id     INTEGER NOT NULL,
                used_at         TEXT NOT NULL,
                FOREIGN KEY (promo_code_id) REFERENCES promo_codes(id),
                UNIQUE(promo_code_id, telegram_id)
            )
        """)
        
        # Рефералы
        db.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id     INTEGER NOT NULL,
                referred_id     INTEGER NOT NULL,
                referred_at     TEXT NOT NULL,
                bonus_paid      INTEGER DEFAULT 0,
                FOREIGN KEY (referrer_id) REFERENCES users(telegram_id),
                FOREIGN KEY (referred_id) REFERENCES users(telegram_id),
                UNIQUE(referred_id)
            )
        """)
        
        # Рассылки
        db.execute("""
            CREATE TABLE IF NOT EXISTS mailings (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                message_text    TEXT NOT NULL,
                sent_at         TEXT NOT NULL,
                sent_by         INTEGER NOT NULL,
                success_count   INTEGER DEFAULT 0,
                failed_count    INTEGER DEFAULT 0
            )
        """)
        
        # Настройки (канал, группа и т.д.)
        db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key             TEXT PRIMARY KEY,
                value           TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            )
        """)
        
        # Статистика трафика
        db.execute("""
            CREATE TABLE IF NOT EXISTS traffic_stats (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id     INTEGER NOT NULL,
                upload          INTEGER DEFAULT 0,
                download        INTEGER DEFAULT 0,
                total           INTEGER DEFAULT 0,
                recorded_at     TEXT NOT NULL
            )
        """)
        
        # Индексы
        db.execute("CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_users_active ON users(active)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_users_subscribed ON users(subscribed_channel)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_promo_codes_code ON promo_codes(code)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_id)")
        
        # Инициализация настроек по умолчанию
        now = datetime.utcnow().isoformat()
        db.execute("""
            INSERT OR IGNORE INTO settings (key, value, updated_at) 
            VALUES ('channel_username', '@your_channel', ?)
        """, (now,))
        db.execute("""
            INSERT OR IGNORE INTO settings (key, value, updated_at) 
            VALUES ('trial_days', '1', ?)
        """, (now,))
        db.execute("""
            INSERT OR IGNORE INTO settings (key, value, updated_at) 
            VALUES ('promo_free_month', '1', ?)
        """, (now,))
        
    log.info("Database initialized with all tables")


# ── User helpers ──────────────────────────────────────────────────────────────

def get_user(telegram_id: int) -> Optional[sqlite3.Row]:
    with get_db() as db:
        return db.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()


def register_user(telegram_id: int, username: Optional[str]) -> sqlite3.Row:
    now = datetime.utcnow().isoformat()
    with get_db() as db:
        db.execute(
            "INSERT OR IGNORE INTO users (telegram_id, username, created_at) VALUES (?, ?, ?)",
            (telegram_id, username, now),
        )
    log.info(f"User registered/ensured: telegram_id={telegram_id} username={username}")
    return get_user(telegram_id)


def update_user_uuid(telegram_id: int, uuid: str):
    with get_db() as db:
        db.execute("UPDATE users SET uuid = ? WHERE telegram_id = ?", (uuid, telegram_id))


def activate_user(telegram_id: int, uuid: str, days: int, payment_id: str):
    """
    Активирует или продлевает подписку.
    Если подписка уже активна — дни добавляются к текущей дате окончания.
    """
    from datetime import timedelta
    
    with get_db() as db:
        # Проверяем текущую подписку
        row = db.execute(
            "SELECT subscription_end, active FROM users WHERE telegram_id = ?",
            (telegram_id,)
        ).fetchone()
        
        if row and row["active"] == 1 and row["subscription_end"]:
            # Продление: добавляем дни к текущей дате окончания
            try:
                current_end = date.fromisoformat(row["subscription_end"])
                # Если подписка ещё активна (не истекла)
                if current_end >= date.today():
                    sub_end = (current_end + timedelta(days=days)).isoformat()
                else:
                    # Если истекла — отсчитываем от сегодня
                    sub_end = (date.today() + timedelta(days=days)).isoformat()
            except Exception:
                sub_end = (date.today() + timedelta(days=days)).isoformat()
        else:
            # Новая активация
            sub_end = (date.today() + timedelta(days=days)).isoformat()
        
        db.execute(
            """UPDATE users
               SET uuid = ?, subscription_end = ?, active = 1,
                   last_payment_id = ?, plan_days = ?
               WHERE telegram_id = ?""",
            (uuid, sub_end, payment_id, days, telegram_id),
        )
    log.info(f"User activated/extended: telegram_id={telegram_id} days={days} sub_end={sub_end} payment_id={payment_id}")


def deactivate_user(telegram_id: int):
    with get_db() as db:
        db.execute(
            "UPDATE users SET active = 0 WHERE telegram_id = ?",
            (telegram_id,),
        )
    log.info(f"User deactivated: telegram_id={telegram_id}")


def is_payment_processed(payment_id: str) -> bool:
    with get_db() as db:
        row = db.execute(
            "SELECT id FROM payment_log WHERE payment_id = ?", (payment_id,)
        ).fetchone()
        return row is not None


def log_payment(payment_id: str, telegram_id: int, amount: float, status: str, gateway: str):
    now = datetime.utcnow().isoformat()
    with get_db() as db:
        db.execute(
            """INSERT OR IGNORE INTO payment_log
               (payment_id, telegram_id, amount, status, gateway, processed_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (payment_id, telegram_id, amount, status, gateway, now),
        )
    log.info(f"Payment logged: payment_id={payment_id} telegram_id={telegram_id} amount={amount} status={status} gateway={gateway}")


def get_expired_users() -> list[sqlite3.Row]:
    today = date.today().isoformat()
    with get_db() as db:
        return db.execute(
            "SELECT * FROM users WHERE active = 1 AND subscription_end < ?",
            (today,),
        ).fetchall()


def get_user_count() -> int:
    with get_db() as db:
        return db.execute("SELECT COUNT(*) FROM users").fetchone()[0]


# ── Channel subscription ──────────────────────────────────────────────────────

def set_user_subscribed(telegram_id: int, subscribed: bool = True):
    """Set user's channel subscription status."""
    with get_db() as db:
        db.execute(
            "UPDATE users SET subscribed_channel = ? WHERE telegram_id = ?",
            (1 if subscribed else 0, telegram_id),
        )
    log.info(f"User subscription status updated: telegram_id={telegram_id} subscribed={subscribed}")


def is_user_subscribed(telegram_id: int) -> bool:
    """Check if user is subscribed to the channel."""
    with get_db() as db:
        row = db.execute(
            "SELECT subscribed_channel FROM users WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchone()
        return bool(row and row["subscribed_channel"])


def get_channel_username() -> str:
    """Get the channel username from settings."""
    with get_db() as db:
        row = db.execute(
            "SELECT value FROM settings WHERE key = 'channel_username'"
        ).fetchone()
        return row["value"] if row else "@your_channel"


def set_channel_username(username: str):
    """Set the channel username in settings."""
    now = datetime.utcnow().isoformat()
    with get_db() as db:
        db.execute(
            "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
            ("channel_username", username, now),
        )
    log.info(f"Channel username updated: {username}")


# ── Trial management ──────────────────────────────────────────────────────────

def has_user_used_trial(telegram_id: int) -> bool:
    """Check if user has already used trial."""
    with get_db() as db:
        row = db.execute(
            "SELECT trial_used FROM users WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchone()
        return bool(row and row["trial_used"])


def set_trial_used(telegram_id: int):
    """Mark trial as used for user."""
    with get_db() as db:
        db.execute(
            "UPDATE users SET trial_used = 1 WHERE telegram_id = ?",
            (telegram_id,),
        )
    log.info(f"Trial marked as used: telegram_id={telegram_id}")


def get_trial_days() -> int:
    """Get trial period days from settings."""
    with get_db() as db:
        row = db.execute(
            "SELECT value FROM settings WHERE key = 'trial_days'"
        ).fetchone()
        return int(row["value"]) if row else 1


def set_trial_days(days: int):
    """Set trial period days."""
    now = datetime.utcnow().isoformat()
    with get_db() as db:
        db.execute(
            "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
            ("trial_days", str(days), now),
        )
    log.info(f"Trial days updated: {days}")


# ── Referral system ───────────────────────────────────────────────────────────

def add_referral(referrer_id: int, referred_id: int):
    """Add a referral relationship."""
    now = datetime.utcnow().isoformat()
    with get_db() as db:
        db.execute(
            """INSERT OR IGNORE INTO referrals (referrer_id, referred_id, referred_at)
               VALUES (?, ?, ?)""",
            (referrer_id, referred_id, now),
        )
        db.execute(
            "UPDATE users SET referred_by = ? WHERE telegram_id = ?",
            (referrer_id, referred_id),
        )
    log.info(f"Referral added: referrer={referrer_id} referred={referred_id}")


def get_referrer_id(telegram_id: int) -> Optional[int]:
    """Get the referrer ID for a user."""
    with get_db() as db:
        row = db.execute(
            "SELECT referred_by FROM users WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchone()
        return row["referred_by"] if row else None


def get_referrals_count(referrer_id: int) -> int:
    """Get the number of referrals for a user."""
    with get_db() as db:
        return db.execute(
            "SELECT COUNT(*) FROM referrals WHERE referrer_id = ?",
            (referrer_id,),
        ).fetchone()[0]


def get_referrals_list(referrer_id: int) -> list[sqlite3.Row]:
    """Get list of referred users."""
    with get_db() as db:
        return db.execute(
            """SELECT u.telegram_id, u.username, u.created_at, r.referred_at
               FROM referrals r
               JOIN users u ON r.referred_id = u.telegram_id
               WHERE r.referrer_id = ?
               ORDER BY r.referred_at DESC""",
            (referrer_id,),
        ).fetchall()


def mark_referral_bonus_paid(referrer_id: int, referred_id: int):
    """Mark referral bonus as paid."""
    with get_db() as db:
        db.execute(
            """UPDATE referrals SET bonus_paid = 1
               WHERE referrer_id = ? AND referred_id = ?""",
            (referrer_id, referred_id),
        )
    log.info(f"Referral bonus marked as paid: referrer={referrer_id} referred={referred_id}")


def is_referral_bonus_paid(referrer_id: int, referred_id: int) -> bool:
    """Check if referral bonus was already paid."""
    with get_db() as db:
        row = db.execute(
            "SELECT bonus_paid FROM referrals WHERE referrer_id = ? AND referred_id = ?",
            (referrer_id, referred_id),
        ).fetchone()
        return bool(row and row["bonus_paid"])


# ── Promo codes ───────────────────────────────────────────────────────────────

def create_promo_code(code: str, bonus_days: int, max_uses: Optional[int] = None, created_by: Optional[int] = None) -> bool:
    """Create a new promo code."""
    now = datetime.utcnow().isoformat()
    with get_db() as db:
        try:
            db.execute(
                """INSERT INTO promo_codes (code, bonus_days, max_uses, created_at, created_by)
                   VALUES (?, ?, ?, ?, ?)""",
                (code, bonus_days, max_uses, now, created_by),
            )
            log.info(f"Promo code created: {code} days={bonus_days} max_uses={max_uses}")
            return True
        except sqlite3.IntegrityError:
            log.warning(f"Promo code already exists: {code}")
            return False


def get_promo_code(code: str) -> Optional[sqlite3.Row]:
    """Get promo code by code string."""
    with get_db() as db:
        return db.execute(
            "SELECT * FROM promo_codes WHERE code = ? AND active = 1",
            (code,),
        ).fetchone()


def use_promo_code(promo_code_id: int, telegram_id: int) -> bool:
    """Mark promo code as used by a user."""
    now = datetime.utcnow().isoformat()
    with get_db() as db:
        try:
            db.execute(
                """INSERT INTO promo_code_uses (promo_code_id, telegram_id, used_at)
                   VALUES (?, ?, ?)""",
                (promo_code_id, telegram_id, now),
            )
            db.execute(
                "UPDATE promo_codes SET used_count = used_count + 1 WHERE id = ?",
                (promo_code_id,),
            )
            log.info(f"Promo code used: id={promo_code_id} telegram_id={telegram_id}")
            return True
        except sqlite3.IntegrityError:
            log.warning(f"Promo code already used by user: id={promo_code_id} telegram_id={telegram_id}")
            return False


def has_user_used_promo(promo_code_id: int, telegram_id: int) -> bool:
    """Check if user has already used this promo code."""
    with get_db() as db:
        row = db.execute(
            "SELECT id FROM promo_code_uses WHERE promo_code_id = ? AND telegram_id = ?",
            (promo_code_id, telegram_id),
        ).fetchone()
        return bool(row)


def deactivate_promo_code(code: str) -> bool:
    """Deactivate a promo code."""
    with get_db() as db:
        result = db.execute(
            "UPDATE promo_codes SET active = 0 WHERE code = ?",
            (code,),
        )
        log.info(f"Promo code deactivated: {code}")
        return result.rowcount > 0


def get_all_promo_codes() -> list[sqlite3.Row]:
    """Get all promo codes."""
    with get_db() as db:
        return db.execute("SELECT * FROM promo_codes ORDER BY created_at DESC").fetchall()


# ── Statistics ────────────────────────────────────────────────────────────────

def get_stats() -> dict:
    """Get general statistics."""
    with get_db() as db:
        total_users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        active_users = db.execute("SELECT COUNT(*) FROM users WHERE active = 1").fetchone()[0]
        subscribed_users = db.execute("SELECT COUNT(*) FROM users WHERE subscribed_channel = 1").fetchone()[0]
        trial_used = db.execute("SELECT COUNT(*) FROM users WHERE trial_used = 1").fetchone()[0]
        total_revenue = db.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM payment_log WHERE status = 'success'"
        ).fetchone()[0]
        
        return {
            "total_users": total_users,
            "active_users": active_users,
            "subscribed_users": subscribed_users,
            "trial_used": trial_used,
            "total_revenue": total_revenue,
        }


def get_all_users() -> list[sqlite3.Row]:
    """Get all users for mailing."""
    with get_db() as db:
        return db.execute("SELECT telegram_id, username, active FROM users").fetchall()


def log_mailing(sent_by: int, message_text: str, success_count: int, failed_count: int):
    """Log a mailing."""
    now = datetime.utcnow().isoformat()
    with get_db() as db:
        db.execute(
            """INSERT INTO mailings (message_text, sent_at, sent_by, success_count, failed_count)
               VALUES (?, ?, ?, ?, ?)""",
            (message_text, now, sent_by, success_count, failed_count),
        )
    log.info(f"Mailing logged: sent_by={sent_by} success={success_count} failed={failed_count}")


def get_all_active_users() -> list[sqlite3.Row]:
    """Get all active users."""
    with get_db() as db:
        return db.execute("SELECT telegram_id, username FROM users WHERE active = 1").fetchall()


# ── Traffic Statistics ────────────────────────────────────────────────────────

def save_traffic_stats(telegram_id: int, upload: int, download: int, total: int):
    """Save traffic statistics for a user."""
    now = datetime.utcnow().isoformat()
    with get_db() as db:
        db.execute(
            """INSERT INTO traffic_stats (telegram_id, upload, download, total, recorded_at)
               VALUES (?, ?, ?, ?, ?)""",
            (telegram_id, upload, download, total, now),
        )


def get_user_traffic_stats(telegram_id: int) -> Optional[sqlite3.Row]:
    """Get latest traffic stats for a user."""
    with get_db() as db:
        return db.execute(
            """SELECT * FROM traffic_stats 
               WHERE telegram_id = ? 
               ORDER BY recorded_at DESC 
               LIMIT 1""",
            (telegram_id,),
        ).fetchone()
