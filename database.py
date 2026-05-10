import sqlite3
from datetime import datetime, date, timedelta

DB_FILE = "counters.db"

def get_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    migrate_data(conn)
    return conn

def create_tables(conn):
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS current_readings (
            user_id TEXT PRIMARY KEY,
            water INTEGER DEFAULT 0,
            gas INTEGER DEFAULT 0,
            electricity INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            water INTEGER,
            gas INTEGER,
            electricity INTEGER,
            water_cost REAL,
            gas_cost REAL,
            electricity_cost REAL,
            total_cost REAL,
            reading_date DATE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_calculated BOOLEAN DEFAULT 0,
            calc_method TEXT,
            UNIQUE(user_id, reading_date)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tariff_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            water REAL NOT NULL,
            gas REAL NOT NULL,
            electricity REAL NOT NULL,
            effective_date DATE NOT NULL,
            UNIQUE(user_id, effective_date)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_tariffs (
            user_id TEXT PRIMARY KEY,
            water REAL DEFAULT 53.0,
            gas REAL DEFAULT 12.0,
            electricity REAL DEFAULT 6.0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 🔥 ТАБЛИЦЫ для стационарных платежей
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_profile (
            user_id TEXT PRIMARY KEY,
            area REAL DEFAULT 0.0,
            residents INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fixed_services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            service_name TEXT NOT NULL,
            amount REAL NOT NULL,
            unit TEXT DEFAULT 'руб',
            effective_date DATE NOT NULL,
            UNIQUE(user_id, service_name, effective_date)
        )
    """)

    conn.commit()

def migrate_data(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM tariff_history")
    if cursor.fetchone()[0] == 0:
        cursor.execute("SELECT user_id, water, gas, electricity FROM user_tariffs")
        rows = cursor.fetchall()
        if rows:
            print("🔄 Миграция: Переносим тарифы в историю...")
            for row in rows:
                cursor.execute("""
                    INSERT INTO tariff_history (user_id, water, gas, electricity, effective_date)
                    VALUES (?, ?, ?, ?, '2000-01-01')
                """, (row["user_id"], row["water"], row["gas"], row["electricity"]))
            conn.commit()
            print("✅ Миграция завершена.")

# ... (Остальные функции get_current_readings и т.д. без изменений) ...

def get_current_readings(user_id: int) -> dict:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT water, gas, electricity FROM current_readings WHERE user_id = ?", (str(user_id),))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"water": row["water"] or 0, "gas": row["gas"] or 0, "electricity": row["electricity"] or 0}
    return {"water": 0, "gas": 0, "electricity": 0}

def update_current_readings(user_id: int, water: int, gas: int, electricity: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO current_readings (user_id, water, gas, electricity, updated_at)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
    """, (str(user_id), water, gas, electricity))
    conn.commit()
    conn.close()

def get_user_tariffs(user_id: int) -> dict:
    return get_tariff_for_date(user_id, date.today())

def get_tariff_for_date(user_id: int, target_date: date) -> dict:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT water, gas, electricity FROM tariff_history 
        WHERE user_id = ? AND effective_date <= ?
        ORDER BY effective_date DESC LIMIT 1
    """, (str(user_id), target_date.isoformat()))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"water": row["water"], "gas": row["gas"], "electricity": row["electricity"]}
    return {"water": 53.0, "gas": 12.0, "electricity": 6.0}

def add_tariff_version(user_id: int, water: float, gas: float, electricity: float, effective_date: date):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO tariff_history (user_id, water, gas, electricity, effective_date)
        VALUES (?, ?, ?, ?, ?)
    """, (str(user_id), water, gas, electricity, effective_date.isoformat()))
    conn.commit()
    conn.close()

def update_user_tariff(user_id: int, key: str, value: float):
    add_tariff_version(user_id, 53.0, 12.0, 6.0)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT water, gas, electricity FROM tariff_history WHERE user_id = ? ORDER BY effective_date DESC LIMIT 1", (str(user_id),))
    row = cursor.fetchone()
    curr = {"water": row["water"], "gas": row["gas"], "electricity": row["electricity"]} if row else {"water": 53.0, "gas": 12.0, "electricity": 6.0}
    curr[key] = value
    add_tariff_version(user_id, curr["water"], curr["gas"], curr["electricity"], date.today())
    conn.close()

def get_readings_for_date(user_id: int, reading_date: date) -> dict:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT water, gas, electricity FROM history WHERE user_id = ? AND reading_date = ?", (str(user_id), reading_date.isoformat()))
    row = cursor.fetchone()
    conn.close()
    return {"water": row["water"], "gas": row["gas"], "electricity": row["electricity"]} if row else None

def get_previous_reading(user_id: int, reading_date: date) -> dict:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT water, gas, electricity, reading_date FROM history 
        WHERE user_id = ? AND reading_date < ? ORDER BY reading_date DESC LIMIT 1
    """, (str(user_id), reading_date.isoformat()))
    row = cursor.fetchone()
    conn.close()
    return {"water": row["water"], "gas": row["gas"], "electricity": row["electricity"], "date": row["reading_date"]} if row else None

def get_next_reading(user_id: int, reading_date: date) -> dict:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT water, gas, electricity, reading_date FROM history 
        WHERE user_id = ? AND reading_date > ? ORDER BY reading_date ASC LIMIT 1
    """, (str(user_id), reading_date.isoformat()))
    row = cursor.fetchone()
    conn.close()
    return {"water": row["water"], "gas": row["gas"], "electricity": row["electricity"], "date": row["reading_date"]} if row else None

def cleanup_calculated_records(user_id: int, start_date: date) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        DELETE FROM history 
        WHERE user_id = ? AND reading_date > ? AND is_calculated = 1
    """, (str(user_id), start_date.isoformat()))
    count = cursor.rowcount
    conn.commit()
    conn.close()
    return count

def add_or_update_history_record(user_id: int, water: int, gas: int, electricity: int,
                                  water_cost: float, gas_cost: float, electricity_cost: float, 
                                  total_cost: float, reading_date: date, is_calculated: bool = False):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO history (user_id, water, gas, electricity, water_cost, gas_cost, electricity_cost, total_cost, reading_date, is_calculated)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, reading_date) DO UPDATE SET
            water = excluded.water, gas = excluded.gas, electricity = excluded.electricity,
            water_cost = excluded.water_cost, gas_cost = excluded.gas_cost, electricity_cost = excluded.electricity_cost,
            total_cost = excluded.total_cost, is_calculated = excluded.is_calculated, created_at = CURRENT_TIMESTAMP
    """, (str(user_id), water, gas, electricity, water_cost, gas_cost, electricity_cost, total_cost, reading_date.isoformat(), int(is_calculated)))
    conn.commit()
    conn.close()

def get_user_history(user_id: int, limit: int = 10) -> list:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT water, gas, electricity, total_cost, reading_date, is_calculated FROM history WHERE user_id = ? ORDER BY reading_date DESC LIMIT ?", (str(user_id), limit))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_readings_for_month(user_id: int, year: int, month: int) -> list:
    conn = get_connection()
    cursor = conn.cursor()
    first_day = f"{year:04d}-{month:02d}-01"
    last_day = f"{year+1 if month==12 else year:04d}-{1 if month==12 else month+1:02d}-01"
    cursor.execute("""
        SELECT water, gas, electricity, water_cost, gas_cost, electricity_cost, total_cost, reading_date
        FROM history WHERE user_id = ? AND reading_date >= ? AND reading_date < ? ORDER BY reading_date ASC
    """, (str(user_id), first_day, last_day))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def calculate_avg_daily_consumption(user_id: int, counter: str) -> dict:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT water, gas, electricity, reading_date 
        FROM history 
        WHERE user_id = ? 
        ORDER BY reading_date DESC
    """, (str(user_id),))
    rows = cursor.fetchall()
    conn.close()
    
    if len(rows) < 2:
        return {"avg_daily": 0, "last_value": rows[0][counter] if rows else 0, "last_date": None, "error": "Недостаточно данных"}
    
    last_row = dict(rows[0])
    last_value = last_row[counter]
    last_date = date.fromisoformat(last_row["reading_date"]) if isinstance(last_row["reading_date"], str) else last_row["reading_date"]
    
    for i in range(1, len(rows)):
        prev_row = dict(rows[i])
        prev_value = prev_row[counter]
        prev_date = date.fromisoformat(prev_row["reading_date"]) if isinstance(prev_row["reading_date"], str) else prev_row["reading_date"]
        days_diff = (last_date - prev_date).days
        if days_diff > 0:
            return {"avg_daily": round((last_value - prev_value) / days_diff, 4), "last_value": last_value, "last_date": last_date, "error": None}
    
    return {"avg_daily": 0, "last_value": last_value, "last_date": last_date, "error": "Все записи в один день"}

def interpolate_reading(user_id: int, counter: str, target_date: date) -> dict:
    exact = get_readings_for_date(user_id, target_date)
    if exact:
        return {"value": exact[counter], "method": "exact", "is_extrapolated": False, "prev_date": None, "next_date": None}
    
    prev = get_previous_reading(user_id, target_date)
    next_ = get_next_reading(user_id, target_date)
    
    if prev and next_:
        prev_val = prev[counter]
        next_val = next_[counter]
        prev_d = date.fromisoformat(prev["date"]) if isinstance(prev["date"], str) else prev["date"]
        next_d = date.fromisoformat(next_["date"]) if isinstance(next_["date"], str) else next_["date"]
        total_days = (next_d - prev_d).days
        if total_days > 0:
            days_from_prev = (target_date - prev_d).days
            return {"value": round(prev_val + (next_val - prev_val) * (days_from_prev / total_days), 2), "method": "linear_interp", "prev_date": prev["date"], "next_date": next_["date"], "is_extrapolated": False}

    avg_data = calculate_avg_daily_consumption(user_id, counter)
    if avg_data["error"]:
        return {"value": prev[counter] if prev else 0, "method": "fallback_last", "prev_date": prev["date"] if prev else None, "next_date": None, "is_extrapolated": True, "warning": avg_data["error"]}

    if prev and not next_:
        days_diff = (target_date - avg_data["last_date"]).days
        if days_diff >= 0:
            return {"value": round(avg_data["last_value"] + (days_diff * avg_data["avg_daily"]), 2), "method": "extrapolate_forward_avg", "prev_date": avg_data["last_date"].isoformat(), "next_date": None, "is_extrapolated": True, "avg_daily": avg_data["avg_daily"]}
    
    return None

def reset_user_readings(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO current_readings (user_id, water, gas, electricity, updated_at) VALUES (?, 0, 0, 0, CURRENT_TIMESTAMP)", (str(user_id),))
    conn.commit()
    conn.close()

def delete_all_user_data(user_id: int) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM history WHERE user_id = ?", (str(user_id),))
    count = cursor.fetchone()[0]
    cursor.execute("DELETE FROM history WHERE user_id = ?", (str(user_id),))
    cursor.execute("DELETE FROM current_readings WHERE user_id = ?", (str(user_id),))
    cursor.execute("DELETE FROM tariff_history WHERE user_id = ?", (str(user_id),))
    cursor.execute("DELETE FROM user_tariffs WHERE user_id = ?", (str(user_id),))
    cursor.execute("DELETE FROM user_profile WHERE user_id = ?", (str(user_id),))
    cursor.execute("DELETE FROM fixed_services WHERE user_id = ?", (str(user_id),))
    conn.commit()
    conn.close()
    return count

# 🔥 ФУНКЦИИ ДЛЯ ПРОФИЛЯ
def get_user_profile(user_id: int) -> dict:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT area, residents FROM user_profile WHERE user_id = ?", (str(user_id),))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"area": row["area"] or 0.0, "residents": row["residents"] or 0}
    return {"area": 0.0, "residents": 0}

def update_user_profile(user_id: int, area: float = None, residents: int = None):
    conn = get_connection()
    cursor = conn.cursor()
    current = get_user_profile(user_id)
    if area is None: area = current["area"]
    if residents is None: residents = current["residents"]
    cursor.execute("INSERT OR REPLACE INTO user_profile (user_id, area, residents, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)", (str(user_id), area, residents))
    conn.commit()
    conn.close()

# 🔥 ФУНКЦИИ ДЛЯ СТАЦИОНАРНЫХ ПЛАТЕЖЕЙ
def get_fixed_services(user_id: int, year: int, month: int) -> list:
    conn = get_connection()
    cursor = conn.cursor()
    first_day = f"{year:04d}-{month:02d}-01"
    last_day = f"{year+1 if month==12 else year:04d}-{1 if month==12 else month+1:02d}-01"
    cursor.execute("""
        SELECT id, service_name, amount, unit
        FROM fixed_services
        WHERE user_id = ? AND effective_date >= ? AND effective_date < ?
        ORDER BY service_name
    """, (str(user_id), first_day, last_day))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def delete_fixed_service_by_id(user_id: int, service_id: int):
    """Удаляет услугу по уникальному ID"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM fixed_services WHERE user_id = ? AND id = ?", (str(user_id), service_id))
    conn.commit()
    conn.close()

def add_fixed_service(user_id: int, service_name: str, amount: float, unit: str = "руб", effective_date: date = None):
    if effective_date is None: effective_date = date.today()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO fixed_services (user_id, service_name, amount, unit, effective_date) VALUES (?, ?, ?, ?, ?)", (str(user_id), service_name, amount, unit, effective_date.isoformat()))
    conn.commit()
    conn.close()

def remove_fixed_service(user_id: int, service_id: int):
    """Удаляет услугу по ID (безопасно)"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        DELETE FROM fixed_services
        WHERE user_id = ? AND id = ?
    """, (str(user_id), service_id))
    conn.commit()
    conn.close()

def get_fixed_services_total(user_id: int, year: int, month: int) -> float:
    services = get_fixed_services(user_id, year, month)
    return sum(s["amount"] for s in services)

# 🔥 НОВАЯ ФУНКЦИЯ: КОПИРОВАНИЕ
def copy_fixed_services(user_id: int, from_year: int, from_month: int, to_year: int, to_month: int) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    
    # Даты источника
    first_from = f"{from_year:04d}-{from_month:02d}-01"
    last_from = f"{from_year + 1 if from_month == 12 else from_year:04d}-{1 if from_month == 12 else from_month + 1:02d}-01"
    
    # Даты назначения
    first_to = f"{to_year:04d}-{to_month:02d}-01"
    
    # Получаем данные из источника
    cursor.execute("SELECT service_name, amount, unit FROM fixed_services WHERE user_id = ? AND effective_date >= ? AND effective_date < ?", (str(user_id), first_from, last_from))
    services = cursor.fetchall()
    
    if not services:
        conn.close()
        return 0
    
    # Вставляем в назначение
    count = 0
    for s in services:
        cursor.execute("""
            INSERT OR REPLACE INTO fixed_services (user_id, service_name, amount, unit, effective_date)
            VALUES (?, ?, ?, ?, ?)
        """, (str(user_id), s["service_name"], s["amount"], s["unit"], first_to))
        count += 1
    
    conn.commit()
    conn.close()
    return count