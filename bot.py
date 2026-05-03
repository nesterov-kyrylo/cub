import asyncio
import re
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, CommandObject
from agent import process_readings, get_user_current_readings
from database import reset_user_readings, get_user_history, get_user_tariffs, update_user_tariff, get_readings_for_month, delete_all_user_data

BOT_TOKEN = "8667184295:AAHlL96N4FFIULDOXMUet5qXUfx0RYsTTm8"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Хранилище состояний для подтверждения удаления
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
        "/month май 2026 — тоже самое\n\n"
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
    
    # Создаем кнопки подтверждения
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
    
    # Удаляем все данные
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
    await callback_query.message.edit_text(
        "❌ **Отменено.**\n\nВсе данные сохранены."
    )
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
        report.append(f"{i}. {date_str} — 💰 {record['total_cost']:.2f} ₽")
    
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
        if year < 100:
            year += 2000
    elif match_name:
        month_str, year_str = match_name.groups()
        month_clean = month_str.rstrip('аяеийюя')
        if month_clean in MONTH_NAMES:
            month = MONTH_NAMES[month_clean]
        else:
            await message.answer(f"❌ Не распознал месяц '{month_str}'. Используй: январь, февраль, ... или номер 1-12")
            return
        year = int(year_str)
        if year < 100:
            year += 2000
    
    if not month or not year or month < 1 or month > 12:
        await message.answer("❌ Некорректная дата. Пример: `/month 05.2026` или `/month май 2026`")
        return
    
    records = get_readings_for_month(user_id, year, month)
    
    if not records:
        month_names_ru = {
            1: "январь", 2: "февраль", 3: "март", 4: "апрель",
            5: "май", 6: "июнь", 7: "июль", 8: "август",
            9: "сентябрь", 10: "октябрь", 11: "ноябрь", 12: "декабрь"
        }
        await message.answer(f"📭 За {month_names_ru[month]} {year} года нет записей.")
        return
    
    month_names_ru = {
        1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
        5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
        9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"
    }
    
    report = [f"📊 **{month_names_ru[month]} {year} года:**\n"]
    
    total_water = 0
    total_gas = 0
    total_electricity = 0
    total_cost = 0.0
    
    for i, record in enumerate(records, 1):
        reading_date = record.get("reading_date", "N/A")
        date_str = str(reading_date)[:10] if reading_date else "N/A"
        
        water = record.get("water", 0) or 0
        gas = record.get("gas", 0) or 0
        electricity = record.get("electricity", 0) or 0
        cost = record.get("total_cost", 0) or 0.0
        
        total_water += water
        total_gas += gas
        total_electricity += electricity
        total_cost += cost
        
        report.append(
            f"{i}. {date_str}\n"
            f"   💧 {water} | 🔥 {gas} | ⚡ {electricity}\n"
            f"   💰 {cost:.2f} ₽"
        )
    
    report.append(f"\n📈 **Итого за месяц:**")
    report.append(f"💧 Вода: {total_water}")
    report.append(f"🔥 Газ: {total_gas}")
    report.append(f"⚡ Свет: {total_electricity}")
    report.append(f"💰 **Всего: {total_cost:.2f} ₽**")
    
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
        await message.answer(
            "❌ Неверный формат. Используй:\n"
            "`/set_tariff <ключ> <цена>`\n\n"
            "Примеры:\n"
            "`/set_tariff вода 55.0`\n"
            "`/set_tariff газ 12.5`\n"
            "`/set_tariff свет 6.0`"
        )
        return
    
    key_input = args[1].lower()
    
    if key_input in TARIFF_KEY_MAP:
        key = TARIFF_KEY_MAP[key_input]
    else:
        await message.answer(
            f"❌ Неверный ключ. Доступно:\n"
            f"💧 вода / water\n"
            f"🔥 газ / gas\n"
            f"⚡ свет / electricity"
        )
        return
    
    try:
        value = float(args[2])
    except ValueError:
        await message.answer("❌ Цена должна быть числом. Пример: `/set_tariff вода 55.0`")
        return
    
    update_user_tariff(user_id, key, value)
    
    key_labels = {
        "water": "💧 Вода",
        "gas": "🔥 Газ",
        "electricity": "⚡ Свет"
    }
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
            "/month 05.2026 — показать за месяц"
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
            await message.answer("❌ Не удалось распознать показания. Попробуй:\n`Вода 100, Газ 200, Свет 300`")
        else:
            await message.answer(f"⚠️ Ошибка: {error_text}")

async def main():
    await bot.delete_webhook()
    print("🚀 Бот запущен. База данных: counters.db")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())