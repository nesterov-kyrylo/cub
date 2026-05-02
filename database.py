import sqlite3
import os
from datetime import datetime

DB_FILE = "counters.db"

def get_connection():
    """Создаёт подключение к БД и создаёт таблицы, если их нет"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row  # Позволяет обращаться к колонкам по имени
    create_tables(conn)
    return conn

def create_tables(conn):
    """Создаёт необходимые таблицы"""
    cursor = conn.cursor()
    
    # Таблица последних показаний (аналог старого JSON)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS current_readings (
            user_id TEXT PRIMARY KEY,
            water INTEGER DEFAULT 0,
            gas INTEGER DEFAULT 0,
            electricity INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Таблица истории (новая фича!)
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()

def get_current_readings(user_id: int) -> dict:
    """Получает текущие показания пользователя"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT water, gas, electricity FROM current_readings 
        WHERE user_id = ?
    """, (str(user_id),))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            "water": row["water"] or 0,
            "gas": row["gas"] or 0,
            "electricity": row["electricity"] or 0
        }
    return {"water": 0, "gas": 0, "electricity": 0}

def update_current_readings(user_id: int, water: int, gas: int, electricity: int):
    """Обновляет текущие показания (INSERT или UPDATE)"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO current_readings (user_id, water, gas, electricity, updated_at)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
    """, (str(user_id), water, gas, electricity))
    conn.commit()
    conn.close()

def add_history_record(user_id: int, water: int, gas: int, electricity: int,
                       water_cost: float, gas_cost: float, electricity_cost: float, total_cost: float):
    """Добавляет запись в историю"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO history (user_id, water, gas, electricity, water_cost, gas_cost, electricity_cost, total_cost)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (str(user_id), water, gas, electricity, water_cost, gas_cost, electricity_cost, total_cost))
    conn.commit()
    conn.close()

def get_user_history(user_id: int, limit: int = 10) -> list:
    """Получает историю пользователя (последние N записей)"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT water, gas, electricity, total_cost, created_at 
        FROM history 
        WHERE user_id = ? 
        ORDER BY created_at DESC 
        LIMIT ?
    """, (str(user_id), limit))
    
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def reset_user_readings(user_id: int):
    """Сбрасывает показания пользователя на 0"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO current_readings (user_id, water, gas, electricity, updated_at)
        VALUES (?, 0, 0, 0, CURRENT_TIMESTAMP)
    """, (str(user_id),))
    conn.commit()
    conn.close()