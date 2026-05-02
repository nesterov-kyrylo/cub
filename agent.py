import ollama
from database import get_current_readings, update_current_readings, add_history_record

MODEL = "qwen2.5-coder:3b"
TARIFFS_FILE = "tariffs.json"

SYSTEM_PROMPT = """
Ты — агент для извлечения показаний счётчиков из текста.

МАППИНГ СЛОВ:
- "вода", "water", "холодная вода", "хв" → ключ "water"
- "газ", "gas", "газомер" → ключ "gas"  
- "свет", "electricity", "электроэнергия", "электричество", "электросчётчик" → ключ "electricity"

ПРАВИЛА:
1. Из входной строки извлеки ТОЛЬКО упомянутые счётчики
2. Верни СТРОГО валидный JSON ТОЛЬКО с упомянутыми ключами
3. Формат: {"water": число, "gas": число, "electricity": число}
4. Если упомянут только один счётчик — верни JSON с одним ключом
5. НЕ добавляй ключи, которые не упомянуты в тексте
6. Никаких пояснений, только JSON.

ПРИМЕРЫ:
Ввод: "вода 100" → Вывод: {"water": 100}
Ввод: "свет 130" → Вывод: {"electricity": 130}
Ввод: "газ 200" → Вывод: {"gas": 200}
Ввод: "вода 100, свет 120" → Вывод: {"water": 100, "electricity": 120}
"""

import json

def load_json(path, default):
    """Вспомогательная функция для загрузки тарифов"""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return default

def get_readings_from_llm(user_input: str) -> dict:
    response = ollama.chat(
        model=MODEL,
        messages=[
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': user_input}
        ],
        options={"temperature": 0.0}
    )
    raw = response['message']['content'].strip()
    if raw.startswith('```'):
        raw = raw.lstrip('`')
        if raw.lower().startswith('json'):
            raw = raw[4:]
        raw = raw.strip()
    if raw.endswith('```'):
        raw = raw.rstrip('`').strip()
    
    print(f"🔍 LLM ответ на '{user_input}': {raw}")
    
    parsed = json.loads(raw)
    
    valid_keys = {'water', 'gas', 'electricity'}
    for key in list(parsed.keys()):
        if key not in valid_keys:
            print(f"⚠️ LLM вернула некорректный ключ '{key}', удаляю")
            del parsed[key]
    
    return parsed

def process_readings(user_input: str, user_id: int) -> str:
    """Принимает сырой текст и user_id, возвращает отчёт. Сохраняет в SQLite."""
    tariffs = load_json(TARIFFS_FILE, {"water": 53.0, "gas": 12.0, "electricity": 6.0})
    history = get_current_readings(user_id)

    new_data = get_readings_from_llm(user_input)
    
    print(f"🔍 Распарсенные данные: {new_data}")
    
    if not new_data:
        raise ValueError("❌ Не удалось извлечь ни одного показания. Укажи: вода, газ или свет.")
    
    report, total_cost = [], 0.0
    updated_readings = history.copy()
    
    # Для записи в историю
    costs = {"water": 0.0, "gas": 0.0, "electricity": 0.0}

    for key, label in [('water', '💧 Вода'), ('gas', '🔥 Газ'), ('electricity', '⚡ Свет')]:
        old_val = history.get(key, 0)
        new_val = new_data.get(key)
        if new_val is None:
            continue
        if new_val < old_val:
            raise ValueError(f"{label} ({new_val}) меньше предыдущего ({old_val}). Проверьте ввод.")
        
        delta = new_val - old_val
        cost = delta * tariffs.get(key, 0)
        costs[key] = cost
        total_cost += cost
        report.append(f"{label}: {new_val} (расход: {delta}) = {cost:.2f} ₽")
        
        updated_readings[key] = new_val

    report.append(f"💰 ИТОГО К ОПЛАТЕ: {total_cost:.2f} ₽")
    
    # 🔥 Сохраняем в SQLite:
    # 1. Обновляем текущие показания
    update_current_readings(
        user_id, 
        updated_readings["water"], 
        updated_readings["gas"], 
        updated_readings["electricity"]
    )
    
    # 2. Добавляем запись в историю
    add_history_record(
        user_id,
        updated_readings["water"],
        updated_readings["gas"],
        updated_readings["electricity"],
        costs["water"],
        costs["gas"],
        costs["electricity"],
        total_cost
    )
    
    return "\n".join(report)

def get_user_current_readings(user_id: int) -> dict:
    """Возвращает текущие показания пользователя"""
    return get_current_readings(user_id)

def reset_user_history(user_id: int):
    """Сбрасывает показания пользователя на 0"""
    reset_user_readings(user_id)