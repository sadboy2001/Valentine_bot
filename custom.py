import os
import json
import logging
from datetime import datetime
from aiogram import types, filters, F, Router, Bot
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import Optional
import config
from moderation import (
    check_bad_words, 
    get_censored_word, 
    log_violation,
    get_user_violations_count,
    get_recent_violations,
    get_violations_stats,
    clear_violations
)

router = Router()

# Файлы для хранения данных
VALENTINES_FILE = "valentines.json"
USERS_FILE = "users.json"

# Количество пользователей на странице
USERS_PER_PAGE = 5


# === СОСТОЯНИЯ FSM ===
class SendValentineStates(StatesGroup):
    choosing_method = State()
    browsing_users = State()
    waiting_for_recipient = State()
    waiting_for_message = State()
    waiting_for_anonymous_choice = State()


# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===
def load_json(filename: str) -> dict:
    """Загрузка данных из JSON файла"""
    if os.path.exists(filename):
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_json(filename: str, data: dict):
    """Сохранение данных в JSON файл"""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_user(user_id: int, username: str, first_name: str = None, last_name: str = None):
    """Сохраняем данные пользователя"""
    if not username:
        return
    users = load_json(USERS_FILE)
    users[username.lower()] = {
        "user_id": user_id,
        "username": username.lower(),
        "first_name": first_name or "",
        "last_name": last_name or "",
        "registered_at": datetime.now().isoformat()
    }
    save_json(USERS_FILE, users)


def get_user_id(username: str) -> Optional[int]:
    """Получаем user_id по username"""
    users = load_json(USERS_FILE)
    user_data = users.get(username.lower())
    if user_data:
        return user_data.get("user_id")
    return None


def get_all_users() -> list:
    """Получаем список всех пользователей"""
    users = load_json(USERS_FILE)
    return list(users.values())


def is_user_registered(username: str) -> bool:
    """Проверяем, зарегистрирован ли пользователь"""
    users = load_json(USERS_FILE)
    return username.lower() in users


def count_unread_valentines(username: str) -> int:
    """Подсчёт непрочитанных валентинок"""
    valentines = load_json(VALENTINES_FILE)
    user_valentines = valentines.get(username.lower(), [])
    return sum(1 for v in user_valentines if not v.get("is_read", False))


def mark_valentines_as_read(username: str):
    """Отмечаем все валентинки как прочитанные"""
    valentines = load_json(VALENTINES_FILE)
    username = username.lower()
    
    if username in valentines:
        for valentine in valentines[username]:
            valentine["is_read"] = True
        save_json(VALENTINES_FILE, valentines)


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


def get_recipient_method_keyboard():
    """Клавиатура выбора способа указания получателя"""
    buttons = [
        [
            types.KeyboardButton(text="📋 Выбрать из списка"),
            types.KeyboardButton(text="✏️ Ввести username"),
        ],
        [types.KeyboardButton(text="❌ Отмена")],
    ]
    return types.ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


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


def get_check_valentines_inline_keyboard():
    """Inline-кнопка для просмотра валентинок"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💝 Посмотреть валентинки", callback_data="check_valentines")]
    ])


def get_users_list_keyboard(users: list, current_page: int, total_pages: int, current_user_id: int):
    """Клавиатура со списком пользователей и пагинацией"""
    buttons = []
    
    # Кнопки пользователей
    for user in users:
        if user.get("user_id") == current_user_id:
            continue  # Пропускаем себя
        
        username = user.get("username", "")
        first_name = user.get("first_name", "")
        last_name = user.get("last_name", "")
        full_name = f"{first_name} {last_name}".strip() or username
        
        buttons.append([
            InlineKeyboardButton(
                text=f"💌 {full_name} (@{username})",
                callback_data=f"select_user:{username}"
            )
        ])
    
    # Навигация
    nav_buttons = []
    if current_page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️", callback_data=f"page:{current_page - 1}"))
    
    nav_buttons.append(InlineKeyboardButton(text=f"{current_page + 1}/{total_pages}", callback_data="page_info"))
    
    if current_page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="➡️", callback_data=f"page:{current_page + 1}"))
    
    if nav_buttons:
        buttons.append(nav_buttons)
    
    # Кнопка отмены
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_browse")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_valentine_word(count: int) -> str:
    """Склонение слова 'валентинка'"""
    if count % 10 == 1 and count % 100 != 11:
        return "валентинка"
    elif 2 <= count % 10 <= 4 and (count % 100 < 10 or count % 100 >= 20):
        return "валентинки"
    else:
        return "валентинок"


def get_new_word(count: int) -> str:
    """Склонение слова 'новая'"""
    if count % 10 == 1 and count % 100 != 11:
        return "новая"
    elif 2 <= count % 10 <= 4 and (count % 100 < 10 or count % 100 >= 20):
        return "новые"
    else:
        return "новых"


# === ФУНКЦИЯ ОТПРАВКИ УВЕДОМЛЕНИЯ ===
async def send_valentine_notification(
    bot: Bot, 
    recipient_username: str, 
    is_anonymous: bool, 
    sender_username: str = None
) -> bool:
    """Отправляет уведомление о новой валентинке"""
    
    recipient_id = get_user_id(recipient_username)
    if not recipient_id:
        return False
    
    try:
        unread = count_unread_valentines(recipient_username)
        word = get_valentine_word(unread)
        new_word = get_new_word(unread)
        
        if is_anonymous:
            sender_text = "🎭 <b>Тайный поклонник</b> отправил тебе валентинку!"
        else:
            sender_text = f"👤 <b>@{sender_username}</b> отправил(а) тебе валентинку!"
        
        notification_text = (
            f"💌✨ <b>НОВАЯ ВАЛЕНТИНКА!</b> ✨💌\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{sender_text}\n\n"
            f"🔔 У тебя <b>{unread} {new_word} {word}</b>!\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💕 Скорее нажми кнопку ниже, чтобы прочитать!"
        )
        
        await bot.send_message(
            recipient_id,
            notification_text,
            parse_mode="HTML",
            reply_markup=get_check_valentines_inline_keyboard()
        )
        return True
        
    except Exception as e:
        logging.error(f"Ошибка отправки уведомления для {recipient_username}: {e}")
        return False


# === ФУНКЦИЯ ПОКАЗА СПИСКА ПОЛЬЗОВАТЕЛЕЙ ===
async def show_users_page(
    bot: Bot,
    chat_id: int,
    current_user_id: int,
    page: int,
    state: FSMContext,
    message_to_edit: types.Message = None
):
    """Показывает страницу со списком пользователей"""
    
    all_users = get_all_users()
    
    # Исключаем текущего пользователя
    users = [u for u in all_users if u.get("user_id") != current_user_id]
    
    if not users:
        text = (
            "😔 <b>Пока никто не зарегистрирован в боте...</b>\n\n"
            "Выберите «✏️ Ввести username» чтобы ввести вручную!"
        )
        if message_to_edit:
            await message_to_edit.edit_text(text, parse_mode="HTML")
        else:
            await bot.send_message(chat_id, text, parse_mode="HTML")
        return
    
    total_pages = (len(users) + USERS_PER_PAGE - 1) // USERS_PER_PAGE
    page = max(0, min(page, total_pages - 1))
    
    start_idx = page * USERS_PER_PAGE
    end_idx = start_idx + USERS_PER_PAGE
    page_users = users[start_idx:end_idx]
    
    # Сохраняем текущую страницу
    await state.update_data(current_page=page)
    
    text = (
        f"👥 <b>Выберите получателя:</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Всего пользователей: {len(users)}\n"
        f"Страница {page + 1} из {total_pages}"
    )
    
    keyboard = get_users_list_keyboard(page_users, page, total_pages, current_user_id)
    
    if message_to_edit:
        try:
            await message_to_edit.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            await bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=keyboard)
    else:
        await bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=keyboard)


# === КОМАНДА /start ===
@router.message(filters.CommandStart())
async def handler_command_start(message: types.Message, state: FSMContext):
    await state.clear()
    
    save_user(
        message.from_user.id, 
        message.from_user.username,
        message.from_user.first_name,
        message.from_user.last_name
    )
    
    username = message.from_user.username
    unread_count = 0
    unread_message = ""
    
    if username:
        unread_count = count_unread_valentines(username)
        if unread_count > 0:
            word = get_valentine_word(unread_count)
            new_word = get_new_word(unread_count)
            unread_message = (
                f"\n\n🔔 <b>У тебя {unread_count} {new_word} {word}!</b>\n"
                f"Нажми кнопку ниже, чтобы прочитать! 👇"
            )
    
    if unread_count > 0:
        await message.answer(
            "Привет! 💕\n\n"
            "Это чат бот для отправки валентинок колледжа IThub, "
            "созданный специально ко дню всех влюбленных.\n\n"
            f"✨ <b>Ты хочешь отправить валентинку или проверить свои?</b>"
            f"{unread_message}",
            reply_markup=get_check_valentines_inline_keyboard(),
            parse_mode="HTML"
        )
        await message.answer(
            "Или выбери действие:",
            reply_markup=get_main_keyboard()
        )
    else:
        await message.answer(
            "Привет! 💕\n\n"
            "Это чат бот для отправки валентинок колледжа IThub, "
            "созданный специально ко дню всех влюбленных.\n\n"
            f"✨ <b>Ты хочешь отправить валентинку или проверить свои?</b>",
            reply_markup=get_main_keyboard(),
            parse_mode="HTML"
        )


# === ОТМЕНА ДЕЙСТВИЯ (reply keyboard) ===
@router.message(F.text == "❌ Отмена")
async def cancel_action(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "❌ Действие отменено.\n\n"
        "Что хотите сделать?",
        reply_markup=get_main_keyboard()
    )


# === ОТМЕНА ПРОСМОТРА (inline keyboard) ===
@router.callback_query(F.data == "cancel_browse")
async def cancel_browse(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("Отменено")
    await state.clear()
    
    if callback.message:
        await callback.message.edit_text("❌ Действие отменено.")
    
    await callback.message.answer(
        "Что хотите сделать?",
        reply_markup=get_main_keyboard()
    )


# === ИНФОРМАЦИЯ О СТРАНИЦЕ ===
@router.callback_query(F.data == "page_info")
async def page_info(callback: types.CallbackQuery):
    await callback.answer("Текущая страница")


# === ОТПРАВКА ВАЛЕНТИНКИ ===
@router.message(F.text == "💌 Отправить валентинку")
async def start_send_valentine(message: types.Message, state: FSMContext):
    # Очищаем предыдущее состояние
    await state.clear()
    
    save_user(
        message.from_user.id, 
        message.from_user.username,
        message.from_user.first_name,
        message.from_user.last_name
    )
    
    await state.set_state(SendValentineStates.choosing_method)
    await message.answer(
        "💌 <b>Как выбрать получателя?</b>\n\n"
        "📋 <b>Выбрать из списка</b> — увидите всех пользователей бота\n"
        "✏️ <b>Ввести username</b> — введите @username вручную",
        reply_markup=get_recipient_method_keyboard(),
        parse_mode="HTML"
    )


# === ВЫБОР ИЗ СПИСКА ===
@router.message(SendValentineStates.choosing_method, F.text == "📋 Выбрать из списка")
async def choose_from_list(message: types.Message, state: FSMContext, bot: Bot):
    await state.set_state(SendValentineStates.browsing_users)
    await show_users_page(
        bot=bot,
        chat_id=message.chat.id,
        current_user_id=message.from_user.id,
        page=0,
        state=state
    )


# === ВВОД USERNAME ВРУЧНУЮ ===
@router.message(SendValentineStates.choosing_method, F.text == "✏️ Ввести username")
async def enter_username_manually(message: types.Message, state: FSMContext):
    await state.set_state(SendValentineStates.waiting_for_recipient)
    await message.answer(
        "💌 <b>Кому отправить валентинку?</b>\n\n"
        "Введите username получателя:\n"
        "<i>(например: @username или просто username)</i>",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )


# === ПАГИНАЦИЯ ===
@router.callback_query(SendValentineStates.browsing_users, F.data.startswith("page:"))
async def paginate_users(callback: types.CallbackQuery, state: FSMContext, bot: Bot):
    await callback.answer()
    
    page = int(callback.data.split(":")[1])
    
    await show_users_page(
        bot=bot,
        chat_id=callback.message.chat.id,
        current_user_id=callback.from_user.id,
        page=page,
        state=state,
        message_to_edit=callback.message
    )


# === ВЫБОР ПОЛЬЗОВАТЕЛЯ ИЗ СПИСКА ===
@router.callback_query(SendValentineStates.browsing_users, F.data.startswith("select_user:"))
async def select_user_from_list(callback: types.CallbackQuery, state: FSMContext, bot: Bot):
    await callback.answer("✅ Выбрано!")
    
    username = callback.data.split(":")[1]
    
    # Получаем информацию о пользователе
    users = load_json(USERS_FILE)
    user_data = users.get(username, {})
    first_name = user_data.get("first_name", "")
    last_name = user_data.get("last_name", "")
    full_name = f"{first_name} {last_name}".strip() or username
    user_id = user_data.get("user_id")
    
    # Редактируем сообщение со списком
    if callback.message:
        await callback.message.edit_text(f"✅ Выбран: <b>{full_name}</b> (@{username})", parse_mode="HTML")
    
    # Пробуем показать фото профиля
    if user_id:
        try:
            photos = await bot.get_user_profile_photos(user_id, limit=1)
            if photos.total_count > 0:
                photo = photos.photos[0][-1]
                await callback.message.answer_photo(
                    photo=photo.file_id,
                    caption=f"💝 Получатель: <b>{full_name}</b>\n📱 @{username}",
                    parse_mode="HTML"
                )
        except Exception as e:
            logging.warning(f"Не удалось получить фото: {e}")
    
    await state.update_data(
        recipient=username,
        recipient_registered=True
    )
    await state.set_state(SendValentineStates.waiting_for_message)
    
    await callback.message.answer(
        "✅ <i>Пользователь сразу получит уведомление!</i>\n\n"
        "Теперь напишите текст вашей валентинки:\n"
        "<i>(можете использовать эмодзи 💕❤️🥰)</i>",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )


# === ПОЛУЧЕНИЕ USERNAME ПОЛУЧАТЕЛЯ (ручной ввод) ===
@router.message(SendValentineStates.waiting_for_recipient)
async def get_recipient(message: types.Message, state: FSMContext):
    recipient = message.text.strip()
    
    if recipient.startswith("@"):
        recipient = recipient[1:]
    
    if not recipient:
        await message.answer(
            "⚠️ Username не может быть пустым. Попробуйте ещё раз:",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    is_registered = is_user_registered(recipient)
    
    await state.update_data(
        recipient=recipient.lower(),
        recipient_registered=is_registered
    )
    await state.set_state(SendValentineStates.waiting_for_message)
    
    if is_registered:
        status = "✅ <i>Пользователь использует бота — сразу получит уведомление!</i>"
    else:
        status = "⚠️ <i>Пользователь ещё не в боте — увидит валентинку, когда зайдёт</i>"
    
    await message.answer(
        f"💝 Получатель: <b>@{recipient}</b>\n"
        f"{status}\n\n"
        "Теперь напишите текст вашей валентинки:\n"
        "<i>(можете использовать эмодзи 💕❤️🥰)</i>",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )


# === ПОЛУЧЕНИЕ ТЕКСТА ВАЛЕНТИНКИ ===
# === ПОЛУЧЕНИЕ ТЕКСТА ВАЛЕНТИНКИ ===
@router.message(SendValentineStates.waiting_for_message)
async def get_valentine_message(message: types.Message, state: FSMContext, bot: Bot):
    valentine_text = message.text
    
    if not valentine_text:
        await message.answer(
            "⚠️ Текст валентинки не может быть пустым. Попробуйте ещё раз:",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    # === ПРОВЕРКА НА ЗАПРЕЩЁННЫЕ СЛОВА ===
    is_clean, bad_word = check_bad_words(valentine_text)
    
    if not is_clean:
        # Получаем данные получателя
        data = await state.get_data()
        recipient = data.get("recipient", "unknown")
        
        # Логируем нарушение
        log_violation(
            user_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            recipient=recipient,
            message=valentine_text,
            bad_word=bad_word
        )
        
        # Уведомляем админов
        await notify_admins_violation(
            bot=bot,
            user_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            recipient=recipient,
            message=valentine_text,
            bad_word=bad_word
        )
        
        # Проверяем количество нарушений
        violations_count = get_user_violations_count(message.from_user.id)
        
        if violations_count >= 5:
            warning = "\n\n⚠️ <b>Внимание!</b> У вас много нарушений. Администратор может заблокировать вам доступ."
        elif violations_count >= 3:
            warning = f"\n\n⚠️ У вас уже {violations_count} нарушений."
        else:
            warning = ""
        
        censored = get_censored_word(bad_word) if bad_word else "***"
        await message.answer(
            f"🚫 <b>Сообщение содержит недопустимое слово!</b>\n\n"
            f"Обнаружено: <code>{censored}</code>\n\n"
            f"Пожалуйста, напишите валентинку без грубых слов.\n"
            f"Давайте будем добрее друг к другу! 💕"
            f"{warning}",
            parse_mode="HTML",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    # Проверка на минимальную длину
    if len(valentine_text.strip()) < 3:
        await message.answer(
            "⚠️ Валентинка слишком короткая. Напишите хотя бы пару слов! 💕",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    await state.update_data(message=valentine_text)
    await state.set_state(SendValentineStates.waiting_for_anonymous_choice)
    
    await message.answer(
        "🎭 <b>Как отправить валентинку?</b>\n\n"
        "👤 <b>Показать моё имя</b> — получатель увидит ваш username\n"
        "🎭 <b>Анонимно</b> — получатель не узнает от кого валентинка",
        reply_markup=get_anonymous_keyboard(),
        parse_mode="HTML"
    )


# === ВЫБОР АНОНИМНОСТИ И ОТПРАВКА ===
@router.message(SendValentineStates.waiting_for_anonymous_choice, F.text.in_(["👤 Показать моё имя", "🎭 Анонимно"]))
async def choose_anonymous(message: types.Message, state: FSMContext, bot: Bot):
    is_anonymous = message.text == "🎭 Анонимно"
    
    data = await state.get_data()
    recipient = data.get("recipient")
    valentine_text = data.get("message")
    recipient_registered = data.get("recipient_registered", False)
    
    sender = message.from_user.username
    sender_id = message.from_user.id
    
    if sender:
        sender = sender.lower()
    else:
        sender = f"user_{sender_id}"
    
    # Сохраняем валентинку
    valentines = load_json(VALENTINES_FILE)
    
    if recipient not in valentines:
        valentines[recipient] = []
    
    valentines[recipient].append({
        "from": "Аноним 🎭" if is_anonymous else sender,
        "from_id": None if is_anonymous else sender_id,
        "message": valentine_text,
        "is_anonymous": is_anonymous,
        "is_read": False,
        "sent_at": datetime.now().isoformat()
    })
    
    save_json(VALENTINES_FILE, valentines)
    await state.clear()
    
    # Отправляем уведомление
    notification_sent = False
    if recipient_registered:
        notification_sent = await send_valentine_notification(
            bot=bot,
            recipient_username=recipient,
            is_anonymous=is_anonymous,
            sender_username=sender
        )
    
    # Ответ отправителю
    anon_text = "анонимно 🎭" if is_anonymous else f"от @{sender}"
    
    if notification_sent:
        delivery_status = "✅ <b>Получатель получил уведомление!</b>"
    elif recipient_registered:
        delivery_status = "⚠️ Не удалось отправить уведомление, но валентинка сохранена"
    else:
        delivery_status = "📨 Получатель увидит валентинку, когда зайдёт в бота"
    
    await message.answer(
        f"✅ <b>Валентинка отправлена {anon_text}!</b>\n\n"
        f"💌 Получатель: @{recipient}\n"
        f"📝 Текст: <i>{valentine_text[:50]}{'...' if len(valentine_text) > 50 else ''}</i>\n\n"
        f"{delivery_status}",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )


# === CALLBACK ПРОСМОТР ВАЛЕНТИНОК ===
@router.callback_query(F.data == "check_valentines")
async def callback_check_valentines(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    
    save_user(
        callback.from_user.id, 
        callback.from_user.username,
        callback.from_user.first_name,
        callback.from_user.last_name
    )
    
    await show_valentines(callback.message, callback.from_user.username)


# === ПРОВЕРКА СВОИХ ВАЛЕНТИНОК (кнопка) ===
@router.message(F.text == "💝 Проверить свои")
async def check_valentines(message: types.Message, state: FSMContext):
    await state.clear()
    
    save_user(
        message.from_user.id, 
        message.from_user.username,
        message.from_user.first_name,
        message.from_user.last_name
    )
    
    await show_valentines(message, message.from_user.username)


# === ОБЩАЯ ФУНКЦИЯ ПОКАЗА ВАЛЕНТИНОК ===
async def show_valentines(message: types.Message, username: str):
    """Показывает валентинки пользователя"""
    
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
    
    user_valentines = valentines[username]
    total = len(user_valentines)
    unread = count_unread_valentines(username)
    word = get_valentine_word(total)
    
    if unread > 0:
        new_word = get_new_word(unread)
        header = f"🎉 <b>У вас {total} {word}!</b>\n🆕 Из них {unread} {new_word}!\n"
    else:
        header = f"🎉 <b>У вас {total} {word}!</b>\n"
    
    await message.answer(header, parse_mode="HTML")
    
    for i, valentine in enumerate(user_valentines, 1):
        from_user = valentine.get("from", "Аноним 🎭")
        text = valentine.get("message", "")
        is_anon = valentine.get("is_anonymous", False)
        is_read = valentine.get("is_read", False)
        
        if is_anon:
            from_display = "🎭 Тайный поклонник"
        else:
            from_display = f"👤 @{from_user}"
        
        new_badge = "" if is_read else " 🆕"
        
        await message.answer(
            f"💌 <b>Валентинка #{i}</b>{new_badge}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"{from_display}\n\n"
            f"💬 <i>{text}</i>\n"
            f"━━━━━━━━━━━━━━━━",
            parse_mode="HTML"
        )
    
    # Отмечаем как прочитанные
    mark_valentines_as_read(username)
    
    await message.answer(
        "💕 <b>Это все ваши валентинки!</b>\n\n"
        "Хотите отправить ответную валентинку? 💌",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )


# === СТАТИСТИКА ===
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
        f"👤 Зарегистрировано: {total_users}",
        parse_mode="HTML"
    )

# === УВЕДОМЛЕНИЕ АДМИНИСТРАТОРОВ ===
async def notify_admins_violation(
    bot: Bot,
    user_id: int,
    username: str,
    first_name: str,
    recipient: str,
    message: str,
    bad_word: str
):
    """Отправляет уведомление администраторам о нарушении"""
    
    if not config.NOTIFY_ADMINS_ON_VIOLATION:
        return
    
    violations_count = get_user_violations_count(user_id)
    censored_word = get_censored_word(bad_word)
    
    # Определяем уровень угрозы
    if violations_count >= 5:
        warning_level = "🔴 ЧАСТЫЙ НАРУШИТЕЛЬ"
    elif violations_count >= 3:
        warning_level = "🟡 ПОВТОРНОЕ НАРУШЕНИЕ"
    else:
        warning_level = "🟢 ПЕРВОЕ НАРУШЕНИЕ"
    
    notification = (
        f"🚨 <b>МОДЕРАЦИЯ: Заблокировано сообщение</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{warning_level}\n\n"
        f"👤 <b>Отправитель:</b>\n"
        f"   • ID: <code>{user_id}</code>\n"
        f"   • Username: @{username or 'нет'}\n"
        f"   • Имя: {first_name or 'нет'}\n"
        f"   • Нарушений: {violations_count}\n\n"
        f"📨 <b>Получатель:</b> @{recipient}\n\n"
        f"🚫 <b>Найдено слово:</b> <code>{censored_word}</code>\n\n"
        f"💬 <b>Текст сообщения:</b>\n"
        f"<i>{message[:200]}{'...' if len(message) > 200 else ''}</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
    )
    
    for admin_id in config.ADMIN_ID:
        try:
            await bot.send_message(admin_id, notification, parse_mode="HTML")
        except Exception as e:
            logging.error(f"Не удалось отправить уведомление админу {admin_id}: {e}")

# === ОБРАБОТЧИК ОСТАЛЬНЫХ СООБЩЕНИЙ ===
@router.message()
async def handle_other_messages(message: types.Message, state: FSMContext):
    save_user(
        message.from_user.id, 
        message.from_user.username,
        message.from_user.first_name,
        message.from_user.last_name
    )
    
    # Проверяем текущее состояние
    current_state = await state.get_state()
    
    if current_state:
        await message.answer(
            "⚠️ Пожалуйста, используйте кнопки или завершите текущее действие.\n\n"
            "Для отмены нажмите «❌ Отмена»",
            reply_markup=get_cancel_keyboard()
        )
    else:
        await message.answer(
            "🤔 Не понимаю вас.\n\n"
            "Используйте кнопки ниже 👇",
            reply_markup=get_main_keyboard()
        )

# === ПРОВЕРКА НА АДМИНА ===
def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором"""
    return user_id in config.ADMIN_IDS


# === КОМАНДА /moderation - СТАТИСТИКА МОДЕРАЦИИ ===
@router.message(filters.Command("moderation"))
async def cmd_moderation(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа к этой команде.")
        return
    
    stats = get_violations_stats()
    
    # Формируем статистику по словам
    word_stats = ""
    if stats["word_counts"]:
        sorted_words = sorted(stats["word_counts"].items(), key=lambda x: x[1], reverse=True)[:10]
        word_stats = "\n".join([f"   • {get_censored_word(w)}: {c}" for w, c in sorted_words])
    else:
        word_stats = "   Нет данных"
    
    # Формируем топ нарушителей
    violators_stats = ""
    if stats["top_violators"]:
        for user_id, data in stats["top_violators"]:
            username = data.get("username", "unknown")
            count = data.get("count", 0)
            violators_stats += f"   • @{username}: {count} нарушений\n"
    else:
        violators_stats = "   Нет данных"
    
    await message.answer(
        f"📊 <b>СТАТИСТИКА МОДЕРАЦИИ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🚫 <b>Всего заблокировано:</b> {stats['total_violations']}\n"
        f"👥 <b>Уникальных нарушителей:</b> {stats['unique_users']}\n\n"
        f"📝 <b>Топ запрещённых слов:</b>\n{word_stats}\n\n"
        f"👤 <b>Топ нарушителей:</b>\n{violators_stats}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📋 Команды:\n"
        f"/logs - последние нарушения\n"
        f"/clearviolations - очистить логи",
        parse_mode="HTML"
    )


# === КОМАНДА /logs - ПОСЛЕДНИЕ НАРУШЕНИЯ ===
@router.message(filters.Command("logs"))
async def cmd_logs(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа к этой команде.")
        return
    
    violations = get_recent_violations(10)
    
    if not violations:
        await message.answer("📋 Нарушений пока нет.")
        return
    
    await message.answer(
        f"📋 <b>ПОСЛЕДНИЕ НАРУШЕНИЯ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━",
        parse_mode="HTML"
    )
    
    for v in violations:
        timestamp = v.get("timestamp", "")
        try:
            dt = datetime.fromisoformat(timestamp)
            time_str = dt.strftime("%d.%m %H:%M")
        except:
            time_str = "?"
        
        username = v.get("username", "unknown")
        recipient = v.get("recipient", "unknown")
        bad_word = v.get("bad_word", "?")
        msg = v.get("message", "")[:100]
        
        await message.answer(
            f"🕐 <b>{time_str}</b>\n"
            f"👤 От: @{username}\n"
            f"📨 Кому: @{recipient}\n"
            f"🚫 Слово: <code>{get_censored_word(bad_word)}</code>\n"
            f"💬 <i>{msg}{'...' if len(v.get('message', '')) > 100 else ''}</i>",
            parse_mode="HTML"
        )


# === КОМАНДА /clearviolations - ОЧИСТИТЬ ЛОГИ ===
@router.message(filters.Command("clearviolations"))
async def cmd_clear_violations(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа к этой команде.")
        return
    
    # Запрашиваем подтверждение
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, очистить", callback_data="confirm_clear_violations"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_clear_violations"),
        ]
    ])
    
    await message.answer(
        "⚠️ <b>Вы уверены?</b>\n\n"
        "Это действие удалит ВСЕ логи нарушений безвозвратно.",
        parse_mode="HTML",
        reply_markup=keyboard
    )


@router.callback_query(F.data == "confirm_clear_violations")
async def confirm_clear_violations(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    
    clear_violations()
    await callback.answer("✅ Логи очищены!")
    await callback.message.edit_text("✅ <b>Все логи нарушений удалены.</b>", parse_mode="HTML")


@router.callback_query(F.data == "cancel_clear_violations")
async def cancel_clear_violations(callback: types.CallbackQuery):
    await callback.answer("Отменено")
    await callback.message.edit_text("❌ Очистка отменена.")


# === КОМАНДА /userinfo - ИНФОРМАЦИЯ О ПОЛЬЗОВАТЕЛЕ ===
@router.message(filters.Command("userinfo"))
async def cmd_user_info(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа к этой команде.")
        return
    
    # Получаем username из аргументов
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "ℹ️ Использование: /userinfo @username\n\n"
            "Пример: <code>/userinfo @ivan_petrov</code>",
            parse_mode="HTML"
        )
        return
    
    username = args[1].strip().lstrip("@").lower()
    
    # Ищем пользователя
    users = load_json(USERS_FILE)
    user_data = users.get(username)
    
    if not user_data:
        await message.answer(f"❌ Пользователь @{username} не найден в базе.")
        return
    
    # Проверяем формат данных
    if isinstance(user_data, int):
        user_id = user_data
        first_name = ""
        last_name = ""
    else:
        user_id = user_data.get("user_id")
        first_name = user_data.get("first_name", "")
        last_name = user_data.get("last_name", "")
    
    # Получаем статистику нарушений
    violations_data = load_violations()
    user_stats = violations_data.get("stats", {}).get(str(user_id), {})
    violations_count = user_stats.get("count", 0)
    violations_words = user_stats.get("words", [])
    
    # Получаем количество отправленных валентинок
    valentines = load_json(VALENTINES_FILE)
    sent_count = 0
    for recipient_valentines in valentines.values():
        for v in recipient_valentines:
            if v.get("from_id") == user_id:
                sent_count += 1
    
    # Получаем количество полученных валентинок
    received_count = len(valentines.get(username, []))
    
    # Формируем ответ
    full_name = f"{first_name} {last_name}".strip() or "Не указано"
    
    words_str = ", ".join([get_censored_word(w) for w in violations_words]) if violations_words else "Нет"
    
    await message.answer(
        f"👤 <b>ИНФОРМАЦИЯ О ПОЛЬЗОВАТЕЛЕ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📱 Username: @{username}\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"👤 Имя: {full_name}\n\n"
        f"💌 <b>Валентинки:</b>\n"
        f"   • Отправлено: {sent_count}\n"
        f"   • Получено: {received_count}\n\n"
        f"🚫 <b>Нарушения:</b>\n"
        f"   • Количество: {violations_count}\n"
        f"   • Слова: {words_str}",
        parse_mode="HTML"
    )


def load_violations():
    """Загружает логи нарушений"""
    from moderation import load_violations as load_v
    return load_v()