import os
import json
import logging
from aiogram import types, filters, F, Router, Bot
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

router = Router()

# Файлы для хранения данных
VALENTINES_FILE = "valentines.json"
USERS_FILE = "users.json"  # Для сохранения user_id по username


# === СОСТОЯНИЯ FSM ===
class SendValentineStates(StatesGroup):
    waiting_for_recipient = State()
    waiting_for_message = State()
    waiting_for_anonymous_choice = State()


# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===
def load_json(filename):
    """Загрузка данных из JSON файла"""
    if os.path.exists(filename):
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_json(filename, data):
    """Сохранение данных в JSON файл"""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_user(user_id: int, username: str):
    """Сохраняем связь username -> user_id для уведомлений"""
    if not username:
        return
    users = load_json(USERS_FILE)
    users[username.lower()] = user_id
    save_json(USERS_FILE, users)


def get_user_id(username: str) -> int | None:
    """Получаем user_id по username"""
    users = load_json(USERS_FILE)
    return users.get(username.lower())


def get_main_keyboard():
    """Главная клавиатура"""
    buttons = [
        [
            types.KeyboardButton(text="💌 Отправить валентинку"),
            types.KeyboardButton(text="💝 Проверить свои"),
        ],
    ]
    return types.ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def get_cancel_keyboard():
    """Клавиатура с кнопкой отмены"""
    return types.ReplyKeyboardMarkup(
        keyboard=[[types.KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True
    )


def get_anonymous_keyboard():
    """Клавиатура выбора анонимности"""
    buttons = [
        [
            types.KeyboardButton(text="👤 Показать моё имя"),
            types.KeyboardButton(text="🎭 Анонимно"),
        ],
        [types.KeyboardButton(text="❌ Отмена")],
    ]
    return types.ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


# === КОМАНДА /start ===
@router.message(filters.CommandStart())
async def handler_command_start(message: types.Message, state: FSMContext):
    await state.clear()
    
    # Сохраняем пользователя для возможности уведомлений
    save_user(message.from_user.id, message.from_user.username)
    
    await message.answer(
        "Привет! 💕\n\n"
        "Это чат бот для отправки валентинок колледжа IThub, "
        "созданный специально ко дню всех влюбленных.\n\n"
        "✨ <b>Ты хочешь отправить валентинку или проверить свои?</b>",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )


# === ОТМЕНА ДЕЙСТВИЯ ===
@router.message(F.text == "❌ Отмена")
async def cancel_action(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "❌ Действие отменено.\n\n"
        "Что хотите сделать?",
        reply_markup=get_main_keyboard()
    )


# === ОТПРАВКА ВАЛЕНТИНКИ ===
@router.message(F.text == "💌 Отправить валентинку")
async def start_send_valentine(message: types.Message, state: FSMContext):
    # Сохраняем пользователя
    save_user(message.from_user.id, message.from_user.username)
    
    await state.set_state(SendValentineStates.waiting_for_recipient)
    await message.answer(
        "💌 <b>Кому отправить валентинку?</b>\n\n"
        "Введите username получателя:\n"
        "<i>(например: @username или просто username)</i>",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )


# === ПОЛУЧЕНИЕ USERNAME ПОЛУЧАТЕЛЯ ===
@router.message(SendValentineStates.waiting_for_recipient)
async def get_recipient(message: types.Message, state: FSMContext):
    recipient = message.text.strip()
    
    # Убираем @ если есть
    if recipient.startswith("@"):
        recipient = recipient[1:]
    
    # Проверка на пустой username
    if not recipient:
        await message.answer(
            "⚠️ Username не может быть пустым. Попробуйте ещё раз:",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    # Сохраняем получателя
    await state.update_data(recipient=recipient.lower())
    await state.set_state(SendValentineStates.waiting_for_message)
    
    await message.answer(
        f"💝 Отлично! Получатель: <b>@{recipient}</b>\n\n"
        "Теперь напишите текст вашей валентинки:\n"
        "<i>(можете использовать эмодзи 💕❤️🥰)</i>",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )


# === ПОЛУЧЕНИЕ ТЕКСТА ВАЛЕНТИНКИ ===
@router.message(SendValentineStates.waiting_for_message)
async def get_valentine_message(message: types.Message, state: FSMContext):
    valentine_text = message.text
    
    # Сохраняем текст
    await state.update_data(message=valentine_text)
    await state.set_state(SendValentineStates.waiting_for_anonymous_choice)
    
    await message.answer(
        "🎭 <b>Как отправить валентинку?</b>\n\n"
        "👤 <b>Показать моё имя</b> — получатель увидит ваш username\n"
        "🎭 <b>Анонимно</b> — получатель не узнает от кого валентинка",
        reply_markup=get_anonymous_keyboard(),
        parse_mode="HTML"
    )


# === ВЫБОР АНОНИМНОСТИ ===
@router.message(SendValentineStates.waiting_for_anonymous_choice, F.text.in_(["👤 Показать моё имя", "🎭 Анонимно"]))
async def choose_anonymous(message: types.Message, state: FSMContext, bot: Bot):
    is_anonymous = message.text == "🎭 Анонимно"
    
    data = await state.get_data()
    recipient = data.get("recipient")
    valentine_text = data.get("message")
    
    # Получаем данные отправителя
    sender = message.from_user.username
    sender_id = message.from_user.id
    
    if sender:
        sender = sender.lower()
    else:
        sender = f"user_{sender_id}"
    
    # Загружаем валентинки
    valentines = load_json(VALENTINES_FILE)
    
    # Добавляем новую валентинку
    if recipient not in valentines:
        valentines[recipient] = []
    
    valentines[recipient].append({
        "from": "Аноним 🎭" if is_anonymous else sender,
        "from_id": None if is_anonymous else sender_id,
        "message": valentine_text,
        "is_anonymous": is_anonymous
    })
    
    # Сохраняем
    save_json(VALENTINES_FILE, valentines)
    
    await state.clear()
    
    # Формируем сообщение об успехе
    anon_text = "анонимно 🎭" if is_anonymous else f"от @{sender}"
    await message.answer(
        f"✅ <b>Валентинка отправлена {anon_text}!</b>\n\n"
        f"💌 Получатель: @{recipient}\n"
        f"📝 Текст: <i>{valentine_text[:50]}{'...' if len(valentine_text) > 50 else ''}</i>",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )
    
    # === УВЕДОМЛЕНИЕ ПОЛУЧАТЕЛЯ ===
    recipient_id = get_user_id(recipient)
    if recipient_id:
        try:
            await bot.send_message(
                recipient_id,
                "🔔 <b>Вам пришла новая валентинка!</b> 💕\n\n"
                f"{'🎭 От тайного поклонника...' if is_anonymous else f'👤 От @{sender}'}\n\n"
                "Нажмите <b>«💝 Проверить свои»</b>, чтобы прочитать!",
                parse_mode="HTML"
            )
        except Exception as e:
            logging.error(f"Не удалось отправить уведомление: {e}")


# === ПРОВЕРКА СВОИХ ВАЛЕНТИНОК ===
@router.message(F.text == "💝 Проверить свои")
async def check_valentines(message: types.Message, state: FSMContext):
    await state.clear()
    
    # Сохраняем пользователя
    save_user(message.from_user.id, message.from_user.username)
    
    username = message.from_user.username
    
    if not username:
        await message.answer(
            "⚠️ <b>У вас не установлен username в Telegram!</b>\n\n"
            "Чтобы получать валентинки, установите username "
            "в настройках Telegram.",
            reply_markup=get_main_keyboard(),
            parse_mode="HTML"
        )
        return
    
    username = username.lower()
    valentines = load_json(VALENTINES_FILE)
    
    # Проверяем есть ли валентинки
    if username not in valentines or len(valentines[username]) == 0:
        await message.answer(
            "💔 <b>Пока что у вас нет валентинок...</b>\n\n"
            "Но не расстраивайтесь! День ещё не закончился, "
            "возможно кто-то уже пишет вам валентинку! 💕\n\n"
            "💡 <i>Поделитесь этим ботом с друзьями!</i>",
            reply_markup=get_main_keyboard(),
            parse_mode="HTML"
        )
        return
    
    # Выводим валентинки
    user_valentines = valentines[username]
    count = len(user_valentines)
    
    # Склонение слова "валентинка"
    if count == 1:
        word = "валентинка"
    elif 2 <= count <= 4:
        word = "валентинки"
    else:
        word = "валентинок"
    
    await message.answer(
        f"🎉 <b>У вас {count} {word}!</b>\n",
        parse_mode="HTML"
    )
    
    for i, valentine in enumerate(user_valentines, 1):
        from_user = valentine.get("from", "Аноним 🎭")
        text = valentine.get("message", "")
        is_anon = valentine.get("is_anonymous", False)
        
        if is_anon:
            from_display = "🎭 Тайный поклонник"
        else:
            from_display = f"👤 @{from_user}"
        
        await message.answer(
            f"💌 <b>Валентинка #{i}</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"{from_display}\n\n"
            f"💬 <i>{text}</i>\n"
            f"━━━━━━━━━━━━━━━━",
            parse_mode="HTML"
        )
    
    await message.answer(
        "💕 <b>Это все ваши валентинки!</b>\n\n"
        "Хотите отправить ответную валентинку? 💌",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )


# === СТАТИСТИКА (для админа) ===
@router.message(filters.Command("stats"))
async def show_stats(message: types.Message):
    valentines = load_json(VALENTINES_FILE)
    users = load_json(USERS_FILE)
    
    total_valentines = sum(len(v) for v in valentines.values())
    total_recipients = len(valentines)
    total_users = len(users)
    
    await message.answer(
        f"📊 <b>Статистика бота</b>\n\n"
        f"💌 Всего валентинок: {total_valentines}\n"
        f"👥 Получателей: {total_recipients}\n"
        f"👤 Пользователей: {total_users}",
        parse_mode="HTML"
    )


# === ОБРАБОТЧИК ОСТАЛЬНЫХ СООБЩЕНИЙ ===
@router.message()
async def handle_other_messages(message: types.Message, state: FSMContext):
    # Сохраняем пользователя
    save_user(message.from_user.id, message.from_user.username)
    
    await message.answer(
        "🤔 Не понимаю вас.\n\n"
        "Используйте кнопки ниже 👇",
        reply_markup=get_main_keyboard()
    )