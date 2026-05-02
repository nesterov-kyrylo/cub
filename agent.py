import json
import os
import ollama

MODEL = "qwen2.5-coder:3b"
HISTORY_FILE = "history.json"
TARIFFS_FILE = "tariffs.json"

SYSTEM_PROMPT = """
Ты — агент для извлечения показаний счётчиков.
Из входной строки извлеки три числа и верни ТОЛЬКО валидный JSON в формате:
{"water": число, "gas": число, "electricity": число}
Никаких пояснений, только JSON.
"""

def load_json(path, default):
    if not os.path.exists(path):
        save_json(path, default)
        return default.copy()
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not data or not isinstance(data, dict):
            save_json(path, default)
            return default.copy()
        return data
    except Exception:
        save_json(path, default)
        return default.copy()

def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

def get_user_history(all_data, user_id, default):
    """Получает историю конкретного пользователя"""
    if str(user_id) not in all_data:
        all_data[str(user_id)] = default.copy()
    user_data = all_data[str(user_id)]
    # Заполняем отсутствующие ключи
    for key, default_val in default.items():
        if key not in user_data or user_data[key] is None:
            user_data[key] = default_val
    return user_data

def save_user_history(all_data, user_id, user_data):
    """Сохраняет историю конкретного пользователя"""
    all_data[str(user_id)] = user_data
    return all_data

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
    return json.loads(raw)

def process_readings(user_input: str, user_id: int) -> str:
    """Принимает сырой текст и user_id, возвращает отчёт. Сохраняет данные пользователя."""
    tariffs = load_json(TARIFFS_FILE, {"water": 53.0, "gas": 12.0, "electricity": 6.0})
    all_history = load_json(HISTORY_FILE, {})
    history = get_user_history(all_history, user_id, {"water": 0, "gas": 0, "electricity": 0})

    new_data = get_readings_from_llm(user_input)
    report, total_cost = [], 0.0

    for key, label in [('water', '💧 Вода'), ('gas', '🔥 Газ'), ('electricity', '⚡ Свет')]:
        old_val = history.get(key, 0)
        new_val = new_data.get(key)
        if new_val is None:
            continue
        if new_val < old_val:
            raise ValueError(f"{label} ({new_val}) меньше предыдущего ({old_val}). Проверьте ввод.")
        
        delta = new_val - old_val
        cost = delta * tariffs.get(key, 0)
        total_cost += cost
        report.append(f"{label}: {new_val} (расход: {delta}) = {cost:.2f} ₽")

    report.append(f"💰 ИТОГО К ОПЛАТЕ: {total_cost:.2f} ₽")
    
    # Сохраняем обновлённую историю пользователя
    all_history = save_user_history(all_history, user_id, new_data)
    save_json(HISTORY_FILE, all_history)
    
    return "\n".join(report)

def get_user_current_readings(user_id: int) -> dict:
    """Возвращает текущие показания пользователя"""
    all_history = load_json(HISTORY_FILE, {})
    return get_user_history(all_history, user_id, {"water": 0, "gas": 0, "electricity": 0})

def reset_user_history(user_id: int):
    """Сбрасывает историю пользователя на нули"""
    all_history = load_json(HISTORY_FILE, {})
    default = {"water": 0, "gas": 0, "electricity": 0}
    all_history = save_user_history(all_history, user_id, default)
    save_json(HISTORY_FILE, all_history)
    return default