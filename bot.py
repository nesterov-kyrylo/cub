import asyncio
from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import Command
from agent import process_readings, get_user_current_readings, reset_user_history

# 🔑 Вставь сюда токен, который дал @BotFather
BOT_TOKEN = "8667184295:AAHlL96N4FFIULDOXMUet5qXUfx0RYsTTm8"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.chat.id
    history = get_user_current_readings(user_id)
    await message.answer(
        "🤖 Привет! Я твой помощник по учёту коммунальных услуг.\n\n"
        "Просто отправь показания в любом формате, например:\n"
        "📝 `Вода 12450, Газ 4521, Свет 88456`\n\n"
        "Доступные команды:\n"
        "/start — показать текущие показания\n"
        "/reset — сбросить показания на 0\n\n"
        f"📊 Текущие показания в памяти:\n"
        f"💧 Вода: {history.get('water', 0)}\n"
        f"🔥 Газ: {history.get('gas', 0)}\n"
        f"⚡ Свет: {history.get('electricity', 0)}"
    )

@dp.message(Command("reset"))
async def cmd_reset(message: Message):
    user_id = message.chat.id
    reset_user_history(user_id)
    await message.answer("🔄 Показания сброшены на 0. Теперь можешь ввести новые.")

@dp.message()
async def handle_message(message: Message):
    if not message.text:
        return

    user_id = message.chat.id
    await bot.send_chat_action(message.chat.id, action="typing")

    try:
        result = process_readings(message.text, user_id)
        await message.answer(result)
    except Exception as e:
        error_text = str(e)
        if "Expecting value" in error_text or "JSON" in error_text:
            await message.answer("❌ Не удалось распознать показания. Попробуй написать проще:\n`Вода 100, Газ 200, Свет 300`")
        elif "меньше предыдущего" in error_text:
            await message.answer(f"❌ {error_text}")
        else:
            await message.answer(f"⚠️ Произошла ошибка: {error_text}")

async def main():
    print("🚀 Бот запущен. Ожидает сообщений...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())