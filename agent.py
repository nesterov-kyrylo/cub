import ollama
import json
import re
from datetime import datetime, date
from database import (
    get_current_readings, update_current_readings, 
    add_or_update_history_record, get_user_tariffs,
    get_readings_for_date, get_previous_reading, get_next_reading
)

MODEL = "qwen2.5-coder:3b"

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

def parse_date_from_input(user_input: str) -> tuple:
    """Извлекает дату из сообщения. Возвращает (очищенный текст, дата)"""
    date_pattern = r'\b(\d{1,2})\.(\d{1,2})\.(\d{2,4})\b'
    match = re.search(date_pattern, user_input)
    
    if match:
        day, month, year = match.groups()
        day = int(day)
        month = int(month)
        year = int(year)
        if year < 100: year += 2000
        
        try:
            reading_date = date(year, month, day)
            cleaned_input = user_input[:match.start()] + user_input[match.end():]
            return cleaned_input.strip(), reading_date
        except ValueError:
            raise ValueError(f"❌ Некорректная дата: {day}.{month}.{year}")
    
    return user_input.strip(), date.today()

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
        if raw.lower().startswith('json'): raw = raw[4:]
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
    """Основная логика: парсинг, валидация дат, расчёт"""
    
    cleaned_input, reading_date = parse_date_from_input(user_input)
    print(f"📅 Дата подачи: {reading_date.isoformat()}")
    
    tariffs = get_user_tariffs(user_id)
    
    # 🔥 Ищем "ПРЕДЫДУЩЕЕ" показание (самое близкое, но ДО reading_date)
    previous_reading = get_previous_reading(user_id, reading_date)
    
    # 🔥 Ищем "СЛЕДУЮЩЕЕ" показание (самое близкое, но ПОСЛЕ reading_date)
    next_reading = get_next_reading(user_id, reading_date)
    
    # Если до этой даты вообще ничего не было, начинаем от 0
    if previous_reading is None:
        history = {"water": 0, "gas": 0, "electricity": 0}
    else:
        history = {
            "water": previous_reading["water"],
            "gas": previous_reading["gas"],
            "electricity": previous_reading["electricity"]
        }
    
    # Проверяем, есть ли уже запись на эту дату
    existing_reading = get_readings_for_date(user_id, reading_date)
    
    new_data = get_readings_from_llm(cleaned_input)
    print(f"🔍 Распарсенные данные: {new_data}")
    
    if not new_data:
        raise ValueError("❌ Не удалось извлечь ни одного показания.")
    
    report, total_cost = [], 0.0
    updated_readings = history.copy()
    costs = {"water": 0.0, "gas": 0.0, "electricity": 0.0}

    for key, label in [('water', '💧 Вода'), ('gas', ' Газ'), ('electricity', '⚡ Свет')]:
        old_val = history.get(key, 0)
        new_val = new_data.get(key)
        
        # Если этот счётчик не упомянут, но есть старая запись на ЭТУ ЖЕ дату — оставляем её
        if new_val is None:
            if existing_reading and existing_reading.get(key) is not None:
                new_val = existing_reading[key]
            else:
                continue
        
        # ✅ ПРОВЕРКА 1: Новые показания должны быть >= ПРЕДЫДУЩИХ (chronologically)
        if new_val < old_val:
            prev_date_str = previous_reading['date'] if previous_reading else "начала отсчёта"
            raise ValueError(f"{label} ({new_val}) меньше предыдущих ({old_val} на {prev_date_str}).")
        
        # ✅ ПРОВЕРКА 2: Новые показания должны быть <= СЛЕДУЮЩИХ (chronologically)
        if next_reading and next_reading.get(key) is not None:
            next_val = next_reading[key]
            if new_val > next_val:
                raise ValueError(f"{label} ({new_val}) больше следующих показаний ({next_val} на {next_reading['date']}).")
        
        delta = new_val - old_val
        cost = delta * tariffs.get(key, 0)
        costs[key] = cost
        total_cost += cost
        report.append(f"{label}: {new_val} (расход: {delta}) = {cost:.2f} ₽")
        
        updated_readings[key] = new_val

    report.append(f"💰 ИТОГО К ОПЛАТЕ: {total_cost:.2f} ₽")
    
    # Сохраняем
    update_current_readings(user_id, updated_readings["water"], updated_readings["gas"], updated_readings["electricity"])
    add_or_update_history_record(
        user_id, updated_readings["water"], updated_readings["gas"], updated_readings["electricity"],
        costs["water"], costs["gas"], costs["electricity"], total_cost, reading_date
    )
    
    return "\n".join(report)

def get_user_current_readings(user_id: int) -> dict:
    return get_current_readings(user_id)

def reset_user_history(user_id: int):
    from database import reset_user_readings
    reset_user_readings(user_id)