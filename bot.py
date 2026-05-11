import asyncio
import re
import os
from calendar import monthrange
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from agent import process_readings, get_user_current_readings
from database import (
    reset_user_readings, get_user_history, get_user_tariffs, update_user_tariff,
    get_readings_for_month, delete_all_user_data, interpolate_reading, date,
    get_previous_reading, get_readings_for_date, add_or_update_history_record,
    get_connection,  # <-- Добавлено для прямых запросов при редактировании
    # Функции для профиля и стационарных платежей
    get_user_profile, update_user_profile,
    get_fixed_services, add_fixed_service, remove_fixed_service, get_fixed_services_total,
    copy_fixed_services
)

# 🔐 Загрузка токена из .env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    print("❌ ОШИБКА: Токен не найден в файле .env!")
    exit()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# 🔥 СЛОВАРИ СОСТОЯНИЙ
user_states = {}
user_temp_data = {}  # Для хранения ID редактируемого платежа

TARIFF_KEY_MAP = {
    "вода": "water", "water": "water",
    "газ": "gas", "gas": "gas",
    "свет": "electricity", "electricity": "electricity",
    "электроэнергия": "electricity", "электричество": "electricity"
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

# 🎛 ГЛАВНОЕ МЕНЮ (ReplyKeyboard)
def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Мои тарифы"), KeyboardButton(text="📜 История")],
            [KeyboardButton(text="📅 Показания за месяц"), KeyboardButton(text="🔄 Сброс")],
            [KeyboardButton(text="🧮 Рассчитать на дату"), KeyboardButton(text="🏗 Пересчёт границ")],
            [KeyboardButton(text="⚙️ Изменить тариф"), KeyboardButton(text="❓ Инструкция")],
            [KeyboardButton(text="🏠 Мои данные"), KeyboardButton(text="🏢 Стационарные платежи")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Введите показания или выберите действие"
    )

# 🔧 Вспомогательный класс для эмуляции сообщений (обход frozen Message)
class _FakeMsg:
    def __init__(self, chat_id, text, bot_instance):
        self.chat = types.Chat(id=chat_id, type="private")
        self.text = text
        self.from_user = types.User(id=chat_id, is_bot=False, first_name="User")
        self._bot = bot_instance
    
    async def answer(self, text, **kwargs):
        await self._bot.send_message(self.chat.id, text, **kwargs)

# 🔥 Меню для стационарных платежей (InlineKeyboard)
def get_fixed_services_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Текущий месяц", callback_data="fixed_current")],
        [InlineKeyboardButton(text="🗓 Выбрать месяц", callback_data="fixed_choose_month")],
        [InlineKeyboardButton(text="➕ Добавить платеж", callback_data="fixed_add")],
        [InlineKeyboardButton(text="📋 Копировать платежи", callback_data="fixed_copy")]
    ])

@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.chat.id
    if user_id in user_states: del user_states[user_id]
    history = get_user_current_readings(user_id)
    tariffs = get_user_tariffs(user_id)

    await message.answer(
        "🤖 Привет! Я твой помощник по учёту коммунальных услуг.\n\n"
        "📝 Отправляй показания в любом формате:\n"
        "`Вода 12450, Газ 4521, Свет 88456` — на сегодня\n"
        "`Вода 12500 10.03.2026` — на указанную дату\n\n"
        "📊 Текущие показания:\n"
        f"💧 Вода: {history.get('water', 0)}\n"
        f"🔥 Газ: {history.get('gas', 0)}\n"
        f"⚡ Свет: {history.get('electricity', 0)}\n\n"
        f"💰 Тарифы:\n"
        f"💧 Вода: {tariffs['water']} ₽/м³\n"
        f"🔥 Газ: {tariffs['gas']} ₽/м³\n"
        f"⚡ Свет: {tariffs['electricity']} ₽/кВт·ч",
        reply_markup=get_main_keyboard()
    )

@dp.message(Command("reset"))
async def cmd_reset(message: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить всё", callback_data="reset_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="reset_cancel")]
    ])
    await message.answer(
        "⚠️ ВНИМАНИЕ!\n\n"
        "Вы собираетесь удалить ВСЕ данные:\n"
        "• Всю историю показаний\n"
        "• Текущие показания\n"
        "• Настроенные тарифы и стационарные платежи\n\n"
        "Это действие НЕОБРАТИМО!\n\n"
        "Продолжить?",
        reply_markup=keyboard
    )

@dp.callback_query(lambda c: c.data == "reset_confirm")
async def confirm_reset(callback_query: types.CallbackQuery):
    deleted_count = delete_all_user_data(callback_query.from_user.id)
    await callback_query.message.edit_text(
        f"🗑️ Все данные удалены!\n\n"
        f"Удалено записей: {deleted_count}\n"
        f"Бот готов к работе с нуля."
    )
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == "reset_cancel")
async def cancel_reset(callback_query: types.CallbackQuery):
    await callback_query.message.edit_text("❌ Отменено.\n\nВсе данные сохранены.")
    await callback_query.answer()

@dp.message(Command("history"))
async def cmd_history(message: Message):
    if message.chat.id in user_states: del user_states[message.chat.id]
    records = get_user_history(message.chat.id, limit=10)
    if not records:
        await message.answer("📭 История пуста.")
        return
    report = ["📊 История подач (последние 10):\n"]
    for i, r in enumerate(records, 1):
        d = str(r.get("reading_date", "N/A"))[:16]
        mark = " (расчёт)" if r.get("is_calculated") else ""
        report.append(f"{i}. {d}{mark} — 💰 {r['total_cost']:.2f} ₽")
    await message.answer("\n".join(report))

@dp.message(Command("calc"))
async def cmd_calc(message: Message):
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Формат: `/calc 10.04.2026`")
        return
    try:
        d, m, y = map(int, args[1].split('.'))
        if y < 100: y += 2000
        target = date(y, m, d)
    except:
        await message.answer("❌ Некорректная дата. Формат: ДД.ММ.ГГГГ")
        return

    tariffs = get_user_tariffs(message.chat.id)
    report = [f"📊 **Расчёт на {target.strftime('%d.%m.%Y')}**:\n"]
    total = 0.0
    saved = {"water": 0, "gas": 0, "electricity": 0}
    costs = {"water": 0.0, "gas": 0.0, "electricity": 0.0}

    for key, (label, db) in {"water": ("💧 Вода", "water"), "gas": ("🔥 Газ", "gas"), "electricity": ("⚡ Свет", "electricity")}.items():
        res = interpolate_reading(message.chat.id, db, target)
        if not res:
            report.append(f"{label}: нет данных")
            continue
        val = res["value"]
        prev_d = res.get("prev_date")
        prev_val = 0
        if prev_d:
            prev = get_readings_for_date(message.chat.id, date.fromisoformat(prev_d) if isinstance(prev_d, str) else prev_d)
            if prev: prev_val = prev[db]
        else:
            p = get_previous_reading(message.chat.id, target)
            if p: prev_val = p[db]
        delta = val - prev_val
        tar = tariffs.get(db, 0)
        cost = delta * tar if delta > 0 else 0
        total += cost
        saved[db] = val
        costs[db] = cost
        m_txt = "✓ факт" if res["method"]=="exact" else ("📐 интерполяция" if res["method"]=="linear_interp" else f"⚠️ экстраполяция ({res.get('avg_daily',0):.2f}/день)" if "avg" in res["method"] else "⚠️ экстраполяция")
        report.append(f"{label}: {val:.2f} (расход: {delta:.2f}) = {cost:.2f} ₽ (Тариф: {tar}) {m_txt}")
        if res.get("warning"): report.append(f"   ⚠️ {res['warning']}")

    report.append(f"\n💰 **Примерная стоимость: {total:.2f} ₽**")
    add_or_update_history_record(message.chat.id, saved["water"], saved["gas"], saved["electricity"],
                                 costs["water"], costs["gas"], costs["electricity"], total, target, is_calculated=True)
    report.append("\n💾 Расчёт сохранён в историю")
    await message.answer("\n".join(report))

@dp.message(Command("month"))
async def cmd_month(message: Message):
    args = message.text.split()
    if len(args) != 2:
        await message.answer("❌ Формат: `/month 05.2026` или `/month май 2026`")
        return
    txt = args[1].lower()
    m_dot = re.match(r'(\d{1,2}).(\d{2,4})', txt)
    m_name = re.match(r'(\w+)\s+(\d{2,4})', txt)
    month = year = None
    if m_dot:
        month, year = int(m_dot.group(1)), int(m_dot.group(2))
    elif m_name:
        clean = m_name.group(1).rstrip('аяеийюя')
        if clean in MONTH_NAMES: month = MONTH_NAMES[clean]
        else:
            await message.answer(f"❌ Не распознал месяц '{m_name.group(1)}'.")
            return
        year = int(m_name.group(2))
    if year < 100: year += 2000
    if not month or not (1 <= month <= 12):
        await message.answer("❌ Некорректная дата.")
        return

    records = get_readings_for_month(message.chat.id, year, month)
    if not records:
        names = {1:"январь",2:"февраль",3:"март",4:"апрель",5:"май",6:"июнь",7:"июль",8:"август",9:"сентябрь",10:"октябрь",11:"ноябрь",12:"декабрь"}
        await message.answer(f"📭 За {names[month]} {year} года нет записей.")
        return

    names_cap = {1:"Январь",2:"Февраль",3:"Март",4:"Апрель",5:"Май",6:"Июнь",7:"Июль",8:"Август",9:"Сентябрь",10:"Октябрь",11:"Ноябрь",12:"Декабрь"}
    tariffs = get_user_tariffs(message.chat.id)
    report = [f"📊 **{names_cap[month]} {year} года:**\n"]
    prev = {"water":0, "gas":0, "electricity":0}
    total_cons = {"water":0, "gas":0, "electricity":0}
    total_cost = 0.0
    
    for i, r in enumerate(records, 1):
        d = str(r.get("reading_date", "N/A"))[:10]
        w, g, e = r.get("water",0) or 0, r.get("gas",0) or 0, r.get("electricity",0) or 0
        wd, gd, ed = w-prev["water"], g-prev["gas"], e-prev["electricity"]
        wc = wd*tariffs["water"] if wd >0 else 0
        gc = gd*tariffs["gas"] if gd >0 else 0
        ec = ed*tariffs["electricity"] if ed >0 else 0
        rc = wc+gc+ec
        total_cons["water"]+=wd; total_cons["gas"]+=gd; total_cons["electricity"]+=ed; total_cost+=rc
        prev = {"water":w, "gas":g, "electricity":e}
        report.append(f"{i}. {d}\n   💧 {w} (+{wd}) | 🔥 {g} (+{gd}) | ⚡ {e} (+{ed})\n   💰 {rc:.2f} ₽")
        
    fixed_total = get_fixed_services_total(message.chat.id, year, month)
    if fixed_total > 0:
        fixed_services = get_fixed_services(message.chat.id, year, month)
        report.append("\n🏠 **Стационарные платежи:**")
        for s in fixed_services:
            report.append(f"• {s['service_name']}: {s['amount']} ₽")
        report.append(f"💰 Итого за стационарные: {fixed_total:.2f} ₽")
        total_cost += fixed_total

    report.append(f"\n📈 **Итого за месяц:**\n💧 Вода: {total_cons['water']} (расход)\n🔥 Газ: {total_cons['gas']} (расход)\n⚡ Свет: {total_cons['electricity']} (расход)\n💰 **Всего: {total_cost:.2f} ₽**")
    await message.answer("\n".join(report))

@dp.message(Command("recalculate_month"))
async def cmd_recalculate_month(message: Message):
    args = message.text.split()
    if len(args) != 2:
        await message.answer("❌ Формат: `/recalculate_month 04.2026`")
        return
    try:
        m, y = map(int, args[1].split('.'))
        if y < 100: y += 2000
    except:
        await message.answer("❌ Некорректная дата. Формат: ММ.ГГГГ")
        return
    first = date(y, m, 1)
    _, last_num = monthrange(y, m)
    last = date(y, m, last_num)
    tariffs = get_user_tariffs(message.chat.id)
    report = [f"🔄 Пересчёт границ {first.strftime('%m.%Y')}:\n\n"]

    for t, lbl in [(first, "1-е число"), (last, "последнее число")]:
        ex = get_readings_for_date(message.chat.id, t)
        if ex and not ex.get("is_calculated", False):
            report.append(f"⏭️ {t.strftime('%d.%m.%Y')} ({lbl}) — есть факт, пропускаем")
            continue
        readings = {}; costs = {}; tc = 0.0
        for db in ["water", "gas", "electricity"]:
            res = interpolate_reading(message.chat.id, db, t)
            if res:
                readings[db] = res["value"]
                p = get_previous_reading(message.chat.id, t)
                pv = p[db] if p else 0
                delta = readings[db] - pv
                cost = delta * tariffs.get(db, 0) if delta > 0 else 0
                costs[db] = cost; tc += cost
        add_or_update_history_record(message.chat.id, readings.get("water",0), readings.get("gas",0), readings.get("electricity",0),
                                     costs.get("water",0), costs.get("gas",0), costs.get("electricity",0), tc, t, is_calculated=True)
        report.append(f"✅ {t.strftime('%d.%m.%Y')} ({lbl}) — рассчитано")
    report.append("\n💾 Готово!")
    await message.answer("\n".join(report))

@dp.message(Command("my_tariffs"))
async def cmd_my_tariffs(message: Message):
    if message.chat.id in user_states: del user_states[message.chat.id]
    t = get_user_tariffs(message.chat.id)
    await message.answer(f"💰 Тарифы:\n💧 Вода: {t['water']} ₽\n🔥 Газ: {t['gas']} ₽\n⚡ Свет: {t['electricity']} ₽")

@dp.message(Command("set_tariff"))
async def cmd_set_tariff(message: Message):
    args = message.text.split()
    if len(args) != 3:
        await message.answer("❌ `/set_tariff вода 55.0`")
        return
    k = args[1].lower()
    if k not in TARIFF_KEY_MAP:
        await message.answer("❌ Ключи: вода, газ, свет")
        return
    try: v = float(args[2])
    except:
        await message.answer("❌ Цена должна быть числом")
        return
    update_user_tariff(message.chat.id, TARIFF_KEY_MAP[k], v)
    await message.answer(f"✅ Обновлено: {args[1]} = {v} ₽")

# 🔥 ПРОФИЛЬ
@dp.message(Command("profile"))
async def cmd_profile(message: Message):
    if message.chat.id in user_states: del user_states[message.chat.id]
    p = get_user_profile(message.chat.id)
    await message.answer(
        f"🏠 Ваши данные:\n"
        f"📐 Площадь: {p['area']} м²\n"
        f"👥 Проживающих: {p['residents']}\n\n"
        f"Для изменения:\n`/update_profile <площадь> <кол-во>`"
    )

@dp.message(Command("update_profile"))
async def cmd_update_profile(message: Message):
    args = message.text.split()
    if len(args) != 3:
        await message.answer("❌ Формат: `/update_profile 43.6 3`")
        return
    try:
        area = float(args[1])
        res = int(args[2])
        update_user_profile(message.chat.id, area, res)
        await message.answer(f"✅ Данные обновлены: {area} м², {res} чел.")
    except:
        await message.answer("❌ Ошибка ввода.")

# 🔥 КОМАНДА: КОПИРОВАНИЕ СТАЦИОНАРНЫХ ПЛАТЕЖЕЙ
@dp.message(Command("copy_fixed"))
async def cmd_copy_fixed(message: Message):
    if message.chat.id in user_states: del user_states[message.chat.id]
    args = message.text.split()
    if len(args) != 3:
        await message.answer("❌ Формат: `/copy_fixed ММ.ГГГГ ММ.ГГГГ`\nПример: `/copy_fixed 03.2026 04.2026`")
        return
    try:
        from_month, from_year = map(int, args[1].split('.'))
        to_month, to_year = map(int, args[2].split('.'))
        
        if from_year < 100: from_year += 2000
        if to_year < 100: to_year += 2000
        
        if not (1 <= from_month <= 12) or not (1 <= to_month <= 12):
            await message.answer("❌ Некорректный месяц. Используйте ММ.ГГГГ")
            return
            
    except ValueError:
        await message.answer("❌ Некорректный формат даты. Используйте ММ.ГГГГ")
        return

    count = copy_fixed_services(message.chat.id, from_year, from_month, to_year, to_month)

    if count == 0:
        await message.answer(f"📭 В {from_month:02d}.{from_year} нет стационарных платежей для копирования.")
    else:
        await message.answer(f"✅ Скопировано {count} услуг из {from_month:02d}.{from_year} в {to_month:02d}.{to_year}.\nПроверьте: /fixed")

# 🔥 ЛОГИКА СТАЦИОНАРНЫХ ПЛАТЕЖЕЙ (МЕНЮ + CALLBACKS)
async def show_fixed_services_for_month(message: Message, year: int, month: int):
    """Функция отображения списка за конкретный месяц с кнопками редактирования"""
    services = get_fixed_services(message.chat.id, year, month)
    total = get_fixed_services_total(message.chat.id, year, month)
    month_names = {1:"Январь",2:"Февраль",3:"Март",4:"Апрель",5:"Май",6:"Июнь",7:"Июль",8:"Август",9:"Сентябрь",10:"Октябрь",11:"Ноябрь",12:"Декабрь"}
    m_name = month_names.get(month, "Неизвестный")
    
    if not services:
        await message.answer(
            f"📭 **{m_name} {year}:**\n"
            "В этом месяце пока нет стационарных платежей."
        )
        return
        
    report = [f"🏢 **{m_name} {year}:**"]
    
    # Создаем кнопки для каждого платежа
    keyboard_buttons = []
    for s in services:
        report.append(f"• {s['service_name']}: {s['amount']} {s['unit']}")
        # Кнопки: Карандаш (редактировать) и Крестик (удалить)
        keyboard_buttons.append([
            InlineKeyboardButton(text=f"✏️ {s['service_name']}", callback_data=f"fixed_edit_{s['id']}"),
            InlineKeyboardButton(text=f"❌", callback_data=f"fixed_delete_{s['id']}")
        ])
        
    report.append(f"\n💰 Итого: {total:.2f} ₽")
    
    # Кнопка "Назад"
    keyboard_buttons.append([InlineKeyboardButton(text="🔙 Главное меню платежей", callback_data="fixed_main")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    await message.answer("\n".join(report), reply_markup=keyboard)

@dp.callback_query(lambda c: c.data.startswith("fixed_"))
async def handle_fixed_callbacks(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    action = callback_query.data
    msg = callback_query.message
    
    if action == "fixed_main":
        await callback_query.answer()
        await msg.edit_text("🏢 **Управление стационарными платежами**\n\nВыберите действие:", reply_markup=get_fixed_services_kb())
        
    elif action == "fixed_current":
        await callback_query.answer()
        d = date.today()
        await show_fixed_services_for_month(msg, d.year, d.month)
        
    elif action == "fixed_choose_month":
        # Включаем режим ожидания ввода месяца
        user_states[user_id] = "fixed_select_month"
        await callback_query.answer()
        await msg.edit_text(
            "🗓 **Выбор месяца**\n\n"
            "Введите месяц и год в формате `ММ.ГГГГ`.\n"
            "Например: `05.2026`",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="fixed_main")]])
        )
        
    elif action == "fixed_add":
        # ВКЛЮЧАЕМ РЕЖИМ ДОБАВЛЕНИЯ
        user_states[user_id] = "fixed_adding"
        await callback_query.answer()
        await msg.edit_text(
            "➕ **Добавить платеж**\n\n"
            "Напиши название и сумму через пробел.\n"
            "Например: `Аренда 5000`\n"
            "Или: `Интернет 600`",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="fixed_main")]])
        )
        
    elif action == "fixed_copy":
        await callback_query.answer()
        await msg.edit_text(
            "📋 **Копирование платежей**\n\n"
            "Используйте команду:\n"
            "`/copy_fixed ММ.ГГГГ ММ.ГГГГ`\n\n"
            "Пример (из марта в апрель):\n"
            "`/copy_fixed 03.2026 04.2026`",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="fixed_main")]])
        )
        
    elif action.startswith("fixed_edit_"):
        # 🔥 ОБРАБОТКА КНОПКИ РЕДАКТИРОВАНИЯ
        service_id = int(action.split("_")[2])
        
        # Получаем информацию о платеже
        from database import get_db_manager
        with get_db_manager().get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT service_name, amount FROM fixed_services WHERE id = ? AND user_id = ?", 
                           (service_id, str(user_id)))
            service = cursor.fetchone()
        
        if not service:
            await callback_query.answer("❌ Платеж не найден!")
            return
            
        # Сохраняем ID платежа для редактирования
        user_temp_data[user_id] = {"edit_id": service_id, "name": service["service_name"]}
        user_states[user_id] = "fixed_editing"
        
        await callback_query.answer()
        await msg.edit_text(
            f"✏️ **Редактирование: {service['service_name']}**\n\n"
            f"Текущая сумма: {service['amount']} ₽\n\n"
            f"Отправь **новую сумму** (только число):",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Отмена", callback_data="fixed_main")]])
        )
        
    elif action.startswith("fixed_delete_"):
        # 🔥 ОБРАБОТКА КНОПКИ УДАЛЕНИЯ
        service_id = int(action.split("_")[2])
        remove_fixed_service(user_id, service_id)
        await callback_query.answer("🗑️ Удалено!")
        await callback_query.message.answer("✅ Запись удалена.")

@dp.message(Command("fixed"))
async def cmd_fixed_menu(message: Message):
    """Вход в меню через команду"""
    user_id = message.chat.id
    if user_id in user_states: del user_states[user_id]
    await message.answer(
        "🏢 **Управление стационарными платежами**\n\n"
        "Выберите действие:",
        reply_markup=get_fixed_services_kb()
    )

# 🔥 ОБРАБОТКА ВСЕХ ВВОДОВ (КНОПКИ И ТЕКСТ)
@dp.message()
async def handle_message(message: Message):
    if not message.text: return
    user_id = message.chat.id
    text = message.text.strip()
    
    # 1. ОБРАБОТКА КНОПОК МЕНЮ
    if text == "📊 Мои тарифы":
        if user_id in user_states: del user_states[user_id]
        return await cmd_my_tariffs(message)

    if text == "📜 История":
        if user_id in user_states: del user_states[user_id]
        return await cmd_history(message)

    if text == "🔄 Сброс":
        if user_id in user_states: del user_states[user_id]
        return await cmd_reset(message)

    if text == "🏠 Мои данные":
        if user_id in user_states: del user_states[user_id]
        return await cmd_profile(message)

    if text == "🏢 Стационарные платежи":
        if user_id in user_states: del user_states[user_id]
        return await cmd_fixed_menu(message)

    # Кнопки, требующие ввода текста
    if text == "📅 Показания за месяц":
        user_states[user_id] = "month"
        return await message.answer("📅 **Показания за месяц**\n\nНапиши месяц и год:\n`04.2026` или `апрель 2026`")

    if text == "🧮 Рассчитать на дату":
        user_states[user_id] = "calc"
        return await message.answer("🧮 **Рассчитать на дату**\n\nНапиши дату:\n`10.04.2026`")

    if text == "🏗 Пересчёт границ":
        user_states[user_id] = "recalculate"
        return await message.answer("🏗 **Пересчёт границ месяца**\n\nНапиши месяц и год:\n`04.2026`")

    if text == "⚙️ Изменить тариф":
        if user_id in user_states: del user_states[user_id]
        return await message.answer("✏️ Чтобы изменить тариф, напиши:\n`/set_tariff вода 55.0`")

    if text == "❓ Инструкция":
        if user_id in user_states: del user_states[user_id]
        return await message.answer(
            "📖 **Инструкция:**\n\n"
            "1️⃣ **Ввод показаний:**\nПросто отправь текст с цифрами:\n• `Вода 100`\n• `Газ 50 10.05.2026`\n\n"
            "2️⃣ **Меню:**\n• 📊 Тарифы • 📜 История •  Месяц • 🔄 Сброс\n• 🧮 Расчёт • 🏗 Границы • ⚙️ Тариф • ❓ Справка\n• 🏠 Данные • 🏢 Стационарные\n\n"
            "💡 *Бот автоматически понимает даты и месяцы!*"
        )

    # 2. ОБРАБОТКА ВВОДА В ЗАВИСИМОСТИ ОТ СОСТОЯНИЯ
    if user_id in user_states:
        state = user_states[user_id]
        
        # --- СОСТОЯНИЕ: Выбор месяца для фиксированных платежей ---
        if state == "fixed_select_month":
            if re.match(r'^\d{1,2}\.\d{2,4}$', text):
                try:
                    m, y = map(int, text.split('.'))
                    if y < 100: y += 2000
                    if 1 <= m <= 12:
                        del user_states[user_id]
                        await show_fixed_services_for_month(message, y, m)
                        return
                except: pass
            await message.answer("❌ Неверный формат. Используйте `ММ.ГГГГ` (например: `05.2026`)")
            return

        # --- СОСТОЯНИЕ: Добавление платежа ---
        elif state == "fixed_adding":
            parts = text.split()
            if len(parts) >= 2:
                try:
                    amount = float(parts[-1])
                    name = " ".join(parts[:-1])
                    
                    today = date.today()
                    effective_date = date(today.year, today.month, 1)
                    
                    add_fixed_service(user_id, name, amount, effective_date=effective_date)
                    await message.answer(f"✅ Добавлено: {name} = {amount} ₽ на {effective_date.strftime('%d.%m.%Y')}")
                    
                    del user_states[user_id]
                    return
                except ValueError:
                    await message.answer("❌ Сумма должна быть числом. Попробуй еще раз.")
                    return
            else:
                await message.answer("❌ Формат: `Название Сумма` (например: Аренда 5000)")
                return

        # --- СОСТОЯНИЕ: Показания за месяц ---
        elif state == "month":
            if re.match(r'^\d{1,2}\.\d{2,4}$', text) or re.match(r'^(январь|февраль|март|апрель|май|июнь|июль|август|сентябрь|октябрь|ноябрь|декабрь)\s+\d{2,4}$', text.lower()):
                fake_msg = _FakeMsg(user_id, f"/month {text}", bot)
                del user_states[user_id]
                return await cmd_month(fake_msg)
            await message.answer("❌ Неверный формат. Напиши:\n`04.2026` или `апрель 2026`")
            return

        # --- СОСТОЯНИЕ: Расчет на дату ---
        elif state == "calc":
            if re.match(r'^\d{1,2}\.\d{1,2}\.\d{2,4}$', text):
                fake_msg = _FakeMsg(user_id, f"/calc {text}", bot)
                del user_states[user_id]
                return await cmd_calc(fake_msg)
            await message.answer("❌ Неверный формат. Напиши:\n`10.04.2026`")
            return

        # --- СОСТОЯНИЕ: Пересчет границ ---
        elif state == "recalculate":
            if re.match(r'^\d{1,2}\.\d{2,4}$', text):
                fake_msg = _FakeMsg(user_id, f"/recalculate_month {text}", bot)
                del user_states[user_id]
                return await cmd_recalculate_month(fake_msg)
            await message.answer("❌ Неверный формат. Напиши:\n`04.2026`")
            return

        # --- СОСТОЯНИЕ: Редактирование платежа ---
        elif state == "fixed_editing":
            if user_id not in user_temp_data or "edit_id" not in user_temp_data[user_id]:
                await message.answer("❌ Ошибка: данные для редактирования не найдены.")
                del user_states[user_id]
                return
            
            try:
                new_amount = float(text)
                if new_amount < 0:
                    await message.answer("❌ Сумма не может быть отрицательной!")
                    return
                
                service_id = user_temp_data[user_id]["edit_id"]
                service_name = user_temp_data[user_id]["name"]
                
                # Обновляем платеж в БД
                from database import get_db_manager
                with get_db_manager().get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        UPDATE fixed_services 
                        SET amount = ? 
                        WHERE id = ? AND user_id = ?
                    """, (new_amount, service_id, str(user_id)))
                    conn.commit()
                
                # Очищаем данные
                del user_states[user_id]
                del user_temp_data[user_id]
                
                await message.answer(f"✅ Обновлено: {service_name} = {new_amount} ₽")
                
            except ValueError:
                await message.answer("❌ Введите корректное число (например: 500.09)")
                return

    # 3. ЕСЛИ НЕ КНОПКА И НЕ СОСТОЯНИЕ -> ОБРАБАТЫВАЕМ КАК ПОКАЗАНИЯ
    if not re.search(r'\d+', text):
        return await message.answer(
            "❓ Не понял. Отправляй числа:\n`Вода 100, Газ 50`\nИспользуй меню снизу 👇",
            reply_markup=get_main_keyboard()
        )

    await bot.send_chat_action(message.chat.id, action="typing")
    try:
        await message.answer(process_readings(text, user_id))
    except ValueError as e:
        await message.answer(str(e))
    except Exception as e:
        await message.answer(f"⚠️ Ошибка: {e}")

async def main():
    await bot.delete_webhook()
    print("🚀 Бот запущен. База данных: counters.db")
    await dp.start_polling(bot)

# 🔥 ИСПРАВЛЕН ЗАПУСК (было if name == "main")
if __name__ == "__main__":
    asyncio.run(main())