import asyncio
import re
from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import Command
from agent import process_readings, get_user_current_readings
from database import reset_user_readings, get_user_history, get_user_tariffs, update_user_tariff

BOT_TOKEN = "8667184295:AAHlL96N4FFIULDOXMUet5qXUfx0RYsTTm8"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

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

@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.chat.id
    history = get_user_current_readings(user_id)
    tariffs = get_user_tariffs(user_id)
    
    await message.answer(
        "🤖 Привет! Я твой помощник по учёту коммунальных услуг.\n\n"
        "📝 Отправляй показания в любом формате:\n"
        "`Вода 12450, Газ 4521, Свет 88456`\n\n"
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
    reset_user_readings(user_id)
    await message.answer("🔄 Показания сброшены на 0. Теперь можешь ввести новые.")

@dp.message(Command("history"))
async def cmd_history(message: Message):
    user_id = message.chat.id
    history_records = get_user_history(user_id, limit=5)
    
    if not history_records:
        await message.answer("📭 История пуста. Ещё не было подач показаний.")
        return
    
    report = ["📊 **История подач (последние 5):**\n"]
    for i, record in enumerate(history_records, 1):
        date = record["created_at"][:16].replace("T", " ") if record["created_at"] else "N/A"
        report.append(f"{i}. {date} — 💰 {record['total_cost']:.2f} ₽")
    
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

    # 🔥 ПРОВЕРКА: сообщение должно содержать цифры (показания счётчиков)
    if not re.search(r'\d+', message.text):
        await message.answer(
            "❓ Я не понял показания. Отправляй числа, например:\n"
            "`Вода 100, Газ 200, Свет 300`\n\n"
            "Используй команды:\n"
            "/start — помощь\n"
            "/my_tariffs — мои тарифы"
        )
        return

    user_id = message.chat.id
    await bot.send_chat_action(message.chat.id, action="typing")

    try:
        result = process_readings(message.text, user_id)
        await message.answer(result)
    except Exception as e:
        error_text = str(e)
        if "Expecting value" in error_text or "JSON" in error_text:
            await message.answer("❌ Не удалось распознать показания. Попробуй:\n`Вода 100, Газ 200, Свет 300`")
        elif "меньше предыдущего" in error_text:
            await message.answer(f"❌ {error_text}")
        else:
            await message.answer(f"⚠️ Ошибка: {error_text}")

async def main():
    print("🚀 Бот запущен. База данных: counters.db")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())