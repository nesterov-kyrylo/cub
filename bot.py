import asyncio
import re
import os
from dotenv import load_dotenv # <-- Импортируем загрузчик
from calendar import monthrange
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from agent import process_readings, get_user_current_readings
from database import (
    reset_user_readings, get_user_history, get_user_tariffs, update_user_tariff,
    get_readings_for_month, delete_all_user_data, interpolate_reading, date,
    get_previous_reading, get_readings_for_date, add_or_update_history_record
)

load_dotenv() # <-- Загружаем переменные из файла .env

# Теперь берем токен из переменной окружения, а не пишем текстом
BOT_TOKEN = os.getenv("BOT_TOKEN") 

if not BOT_TOKEN:
    raise ValueError("Нет токена! Проверьте файл .env")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

reset_confirmation = {}

TARIFF_KEY_MAP = {
    "вода": "water",
    "water": "water",
    "газ": "gas",
    "gas": "gas",
    "свет": "electricity",
    "electricity": "electricity",
    "электроэнергия": "electricity",
    "электричество": "electricity"
}

MONTH_NAMES = {
    "январь": 1, "янв": 1, "1": 1,
    "февраль": 2, "фев": 2, "2": 2,
    "март": 3, "мар": 3, "3": 3,
    "апрель": 4, "апр": 4, "4": 4,
    "май": 5, "5": 5,
    "июнь": 6, "июн": 6, "6": 6,
    "июль": 7, "июл": 7, "7": 7,
    "август": 8, "авг": 8, "8": 8,
    "сентябрь": 9, "сен": 9, "сент": 9, "9": 9,
    "октябрь": 10, "окт": 10, "10": 10,
    "ноябрь": 11, "ноя": 11, "ноян": 11, "11": 11,
    "декабрь": 12, "дек": 12, "12": 12
}

@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.chat.id
    history = get_user_current_readings(user_id)
    tariffs = get_user_tariffs(user_id)
    
    await message.answer(
        "🤖 Привет! Я твой помощник по учёту коммунальных услуг.\n\n"
        "📝 Отправляй показания в любом формате:\n"
        "`Вода 12450, Газ 4521, Свет 88456` — на сегодня\n"
        "`Вода 12500 10.03.2026` — на указанную дату\n"
        "`свет 200 15.04.2026` — частично\n\n"
        "📊 Просмотр данных:\n"
        "/history — последние 10 записей\n"
        "/month 05.2026 — все записи за май 2026\n"
        "/month май 2026 — тоже самое\n"
        "/calc 10.04.2026 — расчёт показаний на дату\n"
        "/recalculate_month 04.2026 — пересчитать границы месяца\n\n"
        "⚙️ Управление тарифами:\n"
        "/my_tariffs — посмотреть текущие тарифы\n"
        "/set_tariff <ключ> <цена> — изменить тариф\n"
        "Примеры:\n"
        "`/set_tariff вода 55.0`\n"
        "`/set_tariff gas 12.5`\n\n"
        f"📊 Текущие показания:\n"
        f"💧 Вода: {history.get('water', 0)}\n"
        f"🔥 Газ: {history.get('gas', 0)}\n"
        f"⚡ Свет: {history.get('electricity', 0)}\n\n"
        f"💰 Тарифы:\n"
        f"💧 Вода: {tariffs['water']} ₽/м³\n"
        f"🔥 Газ: {tariffs['gas']} ₽/м³\n"
        f"⚡ Свет: {tariffs['electricity']} ₽/кВт·ч"
    )

@dp.message(Command("reset"))
async def cmd_reset(message: Message):
    user_id = message.chat.id
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить всё", callback_data="reset_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="reset_cancel")]
    ])
    
    await message.answer(
        "⚠️ **ВНИМАНИЕ!**\n\n"
        "Вы собираетесь удалить **ВСЕ данные**:\n"
        "• Всю историю показаний\n"
        "• Текущие показания\n"
        "• Настроенные тарифы\n\n"
        "Это действие **НЕОБРАТИМО**!\n\n"
        "Продолжить?",
        reply_markup=keyboard
    )

@dp.callback_query(lambda c: c.data == "reset_confirm")
async def confirm_reset(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    deleted_count = delete_all_user_data(user_id)
    
    await callback_query.message.edit_text(
        f"🗑️ **Все данные удалены!**\n\n"
        f"Удалено записей из истории: {deleted_count}\n"
        f"Сброшены текущие показания\n"
        f"Удалены персональные тарифы\n\n"
        f"Бот готов к работе с нуля."
    )
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == "reset_cancel")
async def cancel_reset(callback_query: types.CallbackQuery):
    await callback_query.message.edit_text("❌ **Отменено.**\n\nВсе данные сохранены.")
    await callback_query.answer()

@dp.message(Command("history"))
async def cmd_history(message: Message):
    user_id = message.chat.id
    history_records = get_user_history(user_id, limit=10)
    
    if not history_records:
        await message.answer("📭 История пуста. Ещё не было подач показаний.")
        return
    
    report = ["📊 **История подач (последние 10):**\n"]
    for i, record in enumerate(history_records, 1):
        reading_date = record.get("reading_date", record.get("created_at", "N/A"))
        if reading_date and "T" in str(reading_date):
            date_str = reading_date.replace("T", " ")[:16]
        else:
            date_str = str(reading_date)[:16] if reading_date else "N/A"
        
        is_calc = " (расчёт)" if record.get("is_calculated") else ""
        report.append(f"{i}. {date_str}{is_calc} — 💰 {record['total_cost']:.2f} ₽")
    
    await message.answer("\n".join(report))

@dp.message(Command("calc"))
async def cmd_calc(message: Message):
    user_id = message.chat.id
    args = message.text.split()
    
    if len(args) < 2:
        await message.answer(
            "❌ Неверный формат. Используй:\n"
            "`/calc 10.04.2026` — все счётчики\n"
            "`/calc 10.04.2026 water` — только вода\n\n"
            "Примеры:\n"
            "`/calc 10.04.2026`\n"
            "`/calc 15.05.2026 gas`"
        )
        return
    
    date_str = args[1]
    counter_filter = args[2].lower() if len(args) > 2 else None
    
    try:
        day, month, year = map(int, date_str.split('.'))
        if year < 100: year += 2000
        target_date = date(year, month, day)
    except:
        await message.answer("❌ Некорректная дата. Формат: ДД.ММ.ГГГГ")
        return
    
    tariffs = get_user_tariffs(user_id)
    
    counters = {
        "water": ("💧 Вода", "water"),
        "gas": ("🔥 Газ", "gas"),
        "electricity": ("⚡ Свет", "electricity")
    }
    
    if counter_filter and counter_filter not in counters:
        await message.answer(f"❌ Неверный счётчик. Доступно: {', '.join(counters.keys())}")
        return
    
    report = [f"📊 **Расчёт на {target_date.strftime('%d.%m.%Y')}**:\n"]
    total_cost = 0.0
    calc_readings = {"water": 0, "gas": 0, "electricity": 0}
    calc_costs = {"water": 0.0, "gas": 0.0, "electricity": 0.0}
    
    for key, (label, db_key) in counters.items():
        if counter_filter and key != counter_filter:
            continue
        
        result = interpolate_reading(user_id, db_key, target_date)
        
        if result is None:
            report.append(f"{label}: нет данных для расчёта")
            continue
        
        value = result["value"]
        method = result["method"]
        is_extrap = result.get("is_extrapolated", False)
        warning = result.get("warning", "")
        
        prev_date_str = result.get("prev_date")
        prev_val = 0
        
        if prev_date_str:
            prev_d = date.fromisoformat(prev_date_str) if isinstance(prev_date_str, str) else prev_date_str
            prev_reading = get_readings_for_date(user_id, prev_d)
            if prev_reading:
                prev_val = prev_reading[db_key]
        else:
            prev = get_previous_reading(user_id, target_date)
            prev_val = prev[db_key] if prev else 0
        
        delta = value - prev_val
        tariff = tariffs.get(db_key, 0)
        cost = delta * tariff if delta > 0 else 0
        total_cost += cost
        
        calc_readings[db_key] = value
        calc_costs[db_key] = cost
        
        method_text = ""
        if method == "exact":
            method_text = "✓ факт"
        elif method == "linear_interp":
            method_text = "📐 интерполяция"
        elif "avg" in method:
            avg_daily = result.get("avg_daily", 0)
            method_text = f"⚠️ экстраполяция ({avg_daily:.2f}/день)"
        else:
            method_text = "⚠️ экстраполяция"
        
        line = f"{label}: {value:.2f} (расход: {delta:.2f}) = {cost:.2f} ₽ (Тариф: {tariff}) {method_text}"
        if warning:
            line += f"\n   ⚠️ {warning}"
        report.append(line)
    
    report.append(f"\n💰 **Примерная стоимость: {total_cost:.2f} ₽**")
    
    # 🔥 СОХРАНЕНИЕ расчётной записи в БД
    add_or_update_history_record(
        user_id, 
        calc_readings["water"], 
        calc_readings["gas"], 
        calc_readings["electricity"],
        calc_costs["water"],
        calc_costs["gas"],
        calc_costs["electricity"],
        total_cost,
        target_date,
        is_calculated=True
    )
    
    report.append("\n💾 Расчёт сохранён в историю")
    
    await message.answer("\n".join(report))

@dp.message(Command("month"))
async def cmd_month(message: Message):
    user_id = message.chat.id
    args = message.text.split()
    
    if len(args) != 2:
        await message.answer(
            "❌ Неверный формат. Используй:\n"
            "`/month 05.2026` или `/month май 2026`\n\n"
            "Примеры:\n"
            "`/month 05.2026`\n"
            "`/month май 2026`\n"
            "`/month 12.2025`"
        )
        return
    
    month_year = args[1].lower()
    match_dot = re.match(r'(\d{1,2})\.(\d{2,4})', month_year)
    match_name = re.match(r'(\w+)\s+(\d{2,4})', month_year)
    
    month = None
    year = None
    
    if match_dot:
        month_str, year_str = match_dot.groups()
        month = int(month_str)
        year = int(year_str)
        if year < 100: year += 2000
    elif match_name:
        month_str, year_str = match_name.groups()
        month_clean = month_str.rstrip('аяеийюя')
        if month_clean in MONTH_NAMES:
            month = MONTH_NAMES[month_clean]
        else:
            await message.answer(f"❌ Не распознал месяц '{month_str}'.")
            return
        year = int(year_str)
        if year < 100: year += 2000
    
    if not month or not year or month < 1 or month > 12:
        await message.answer("❌ Некорректная дата.")
        return
    
    records = get_readings_for_month(user_id, year, month)
    
    if not records:
        month_names_ru = {1: "январь", 2: "февраль", 3: "март", 4: "апрель", 5: "май", 6: "июнь", 7: "июль", 8: "август", 9: "сентябрь", 10: "октябрь", 11: "ноябрь", 12: "декабрь"}
        await message.answer(f"📭 За {month_names_ru[month]} {year} года нет записей.")
        return
    
    month_names_ru = {1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель", 5: "Май", 6: "Июнь", 7: "Июль", 8: "Август", 9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"}
    tariffs = get_user_tariffs(user_id)
    
    report = [f"📊 **{month_names_ru[month]} {year} года:**\n"]
    
    # 🔥 ГИБРИДНЫЙ ПОДХОД: считаем расход между записями
    prev_values = {"water": 0, "gas": 0, "electricity": 0}
    total_consumption = {"water": 0, "gas": 0, "electricity": 0}
    total_cost = 0.0
    
    for i, record in enumerate(records, 1):
        reading_date = record.get("reading_date", "N/A")
        date_str = str(reading_date)[:10] if reading_date else "N/A"
        
        water = record.get("water", 0) or 0
        gas = record.get("gas", 0) or 0
        electricity = record.get("electricity", 0) or 0
        
        water_delta = water - prev_values["water"]
        gas_delta = gas - prev_values["gas"]
        electricity_delta = electricity - prev_values["electricity"]
        
        water_cost = water_delta * tariffs["water"] if water_delta > 0 else 0
        gas_cost = gas_delta * tariffs["gas"] if gas_delta > 0 else 0
        electricity_cost = electricity_delta * tariffs["electricity"] if electricity_delta > 0 else 0
        record_cost = water_cost + gas_cost + electricity_cost
        
        total_consumption["water"] += water_delta
        total_consumption["gas"] += gas_delta
        total_consumption["electricity"] += electricity_delta
        total_cost += record_cost
        
        prev_values["water"] = water
        prev_values["gas"] = gas
        prev_values["electricity"] = electricity
        
        report.append(
            f"{i}. {date_str}\n"
            f"   💧 {water} (+{water_delta}) | 🔥 {gas} (+{gas_delta}) | ⚡ {electricity} (+{electricity_delta})\n"
            f"   💰 {record_cost:.2f} ₽"
        )
    
    report.append(f"\n📈 **Итого за месяц:**")
    report.append(f"💧 Вода: {total_consumption['water']} (расход)")
    report.append(f"🔥 Газ: {total_consumption['gas']} (расход)")
    report.append(f"⚡ Свет: {total_consumption['electricity']} (расход)")
    report.append(f"💰 **Всего: {total_cost:.2f} ₽**")
    
    await message.answer("\n".join(report))

@dp.message(Command("recalculate_month"))
async def cmd_recalculate_month(message: Message):
    user_id = message.chat.id
    args = message.text.split()
    
    if len(args) != 2:
        await message.answer(
            "❌ Неверный формат. Используй:\n"
            "`/recalculate_month 04.2026`\n\n"
            "Это создаст расчётные записи на 1-е и последнее число месяца."
        )
        return
    
    date_str = args[1]
    try:
        month, year = map(int, date_str.split('.'))
        if year < 100: year += 2000
    except:
        await message.answer("❌ Некорректная дата. Формат: ММ.ГГГГ")
        return
    
    # Получаем первый и последний день месяца
    first_day = date(year, month, 1)
    _, last_day_num = monthrange(year, month)
    last_day = date(year, month, last_day_num)
    
    tariffs = get_user_tariffs(user_id)
    
    report = [f"🔄 **Пересчёт границ месяца {first_day.strftime('%m.%Y')}**:\n\n"]
    
    for target_date, label in [(first_day, "1-е число"), (last_day, "последнее число")]:
        # Проверяем, есть ли уже запись
        existing = get_readings_for_date(user_id, target_date)
        if existing and not existing.get("is_calculated", False):
            report.append(f"⏭️ {target_date.strftime('%d.%m.%Y')} ({label}) — уже есть фактическая запись, пропускаем")
            continue
        
        # Считаем для всех счётчиков
        readings = {}
        costs = {}
        total_cost = 0.0
        
        for db_key in ["water", "gas", "electricity"]:
            result = interpolate_reading(user_id, db_key, target_date)
            if result:
                readings[db_key] = result["value"]
                
                # Считаем расход
                prev = get_previous_reading(user_id, target_date)
                prev_val = prev[db_key] if prev else 0
                delta = readings[db_key] - prev_val
                tariff = tariffs.get(db_key, 0)
                cost = delta * tariff if delta > 0 else 0
                costs[db_key] = cost
                total_cost += cost
        
        # Сохраняем
        add_or_update_history_record(
            user_id,
            readings.get("water", 0),
            readings.get("gas", 0),
            readings.get("electricity", 0),
            costs.get("water", 0),
            costs.get("gas", 0),
            costs.get("electricity", 0),
            total_cost,
            target_date,
            is_calculated=True
        )
        
        report.append(f"✅ {target_date.strftime('%d.%m.%Y')} ({label}) — рассчитано и сохранено")
    
    report.append("\n💾 Готово!")
    await message.answer("\n".join(report))

@dp.message(Command("my_tariffs"))
async def cmd_my_tariffs(message: Message):
    user_id = message.chat.id
    tariffs = get_user_tariffs(user_id)
    
    await message.answer(
        f"💰 **Твои текущие тарифы:**\n\n"
        f"💧 Вода: {tariffs['water']} ₽/м³\n"
        f"🔥 Газ: {tariffs['gas']} ₽/м³\n"
        f"⚡ Свет: {tariffs['electricity']} ₽/кВт·ч\n\n"
        "Чтобы изменить, используй:\n"
        "`/set_tariff вода <цена>`\n"
        "`/set_tariff газ <цена>`\n"
        "`/set_tariff свет <цена>`"
    )

@dp.message(Command("set_tariff"))
async def cmd_set_tariff(message: Message):
    user_id = message.chat.id
    args = message.text.split()
    
    if len(args) != 3:
        await message.answer("❌ Неверный формат. Используй:\n`/set_tariff <ключ> <цена>`\n\nПримеры:\n`/set_tariff вода 55.0`\n`/set_tariff газ 12.5`\n`/set_tariff свет 6.0`")
        return
    
    key_input = args[1].lower()
    
    if key_input in TARIFF_KEY_MAP:
        key = TARIFF_KEY_MAP[key_input]
    else:
        await message.answer(f"❌ Неверный ключ. Доступно:\n💧 вода / water\n🔥 газ / gas\n⚡ свет / electricity")
        return
    
    try:
        value = float(args[2])
    except ValueError:
        await message.answer("❌ Цена должна быть числом.")
        return
    
    update_user_tariff(user_id, key, value)
    
    key_labels = {"water": "💧 Вода", "gas": "🔥 Газ", "electricity": "⚡ Свет"}
    label = key_labels.get(key, key)
    
    await message.answer(f"✅ {label}: тариф обновлён на {value} ₽")

@dp.message()
async def handle_message(message: Message):
    if not message.text:
        return

    if not re.search(r'\d+', message.text):
        await message.answer(
            "❓ Я не понял показания. Отправляй числа, например:\n"
            "`Вода 100, Газ 200, Свет 300`\n"
            "`свет 150 10.03.2026`\n\n"
            "Используй команды:\n"
            "/start — помощь\n"
            "/my_tariffs — мои тарифы\n"
            "/month 05.2026 — показать за месяц\n"
            "/calc 10.04.2026 — расчёт на дату"
        )
        return

    user_id = message.chat.id
    await bot.send_chat_action(message.chat.id, action="typing")

    try:
        result = process_readings(message.text, user_id)
        await message.answer(result)
    except ValueError as e:
        await message.answer(str(e))
    except Exception as e:
        error_text = str(e)
        if "Expecting value" in error_text or "JSON" in error_text:
            await message.answer("❌ Не удалось распознать показания.")
        else:
            await message.answer(f"⚠️ Ошибка: {error_text}")

async def main():
    await bot.delete_webhook()
    print("🚀 Бот запущен. База данных: counters.db")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())