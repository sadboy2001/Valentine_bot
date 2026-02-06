import os
import json
import re
from datetime import datetime
from typing import Optional
from bad_words import BAD_WORDS, SYMBOL_REPLACEMENTS

# Файл для хранения логов нарушений
VIOLATIONS_FILE = "violations.json"


def normalize_text(text: str) -> tuple[str, str]:
    """
    Нормализует текст для проверки:
    - Приводит к нижнему регистру
    - Заменяет символы на буквы
    - Убирает лишние пробелы и символы
    """
    text = text.lower()
    
    # Заменяем символы на буквы
    for symbol, letter in SYMBOL_REPLACEMENTS.items():
        text = text.replace(symbol, letter)
    
    # Убираем повторяющиеся буквы (типа "дуууурак")
    text = re.sub(r'(.)\1{2,}', r'\1', text)
    
    # Убираем все символы кроме букв
    text_clean = re.sub(r'[^а-яёa-z]', '', text)
    
    # Также проверяем текст с пробелами (для "д у р а к")
    text_with_spaces = re.sub(r'[^а-яёa-z\s]', '', text)
    text_no_spaces = text_with_spaces.replace(' ', '')
    
    return text_clean, text_no_spaces


def check_bad_words(text: str) -> tuple[bool, Optional[str]]:
    """
    Проверяет текст на наличие запрещённых слов.
    
    Возвращает:
        (True, None) - если текст чистый
        (False, "слово") - если найдено запрещённое слово
    """
    text_clean, text_no_spaces = normalize_text(text)
    
    for check_text in [text_clean, text_no_spaces]:
        for bad_word in BAD_WORDS:
            if bad_word in check_text:
                return False, bad_word
    
    return True, None


def get_censored_word(word: str) -> str:
    """Цензурирует слово (показывает первую и последнюю букву)"""
    if len(word) <= 2:
        return "*" * len(word)
    return word[0] + "*" * (len(word) - 2) + word[-1]


def get_censored_text(text: str, bad_word: str) -> str:
    """Цензурирует найденное слово в тексте"""
    # Находим все вариации слова в тексте
    pattern = re.compile(re.escape(bad_word), re.IGNORECASE)
    return pattern.sub(get_censored_word(bad_word), text)


# === ЛОГИРОВАНИЕ НАРУШЕНИЙ ===

def load_violations() -> dict:
    """Загружает логи нарушений"""
    if os.path.exists(VIOLATIONS_FILE):
        try:
            with open(VIOLATIONS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {"violations": [], "stats": {}}
    return {"violations": [], "stats": {}}


def save_violations(data: dict):
    """Сохраняет логи нарушений"""
    with open(VIOLATIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def log_violation(
    user_id: int,
    username: str,
    first_name: str,
    recipient: str,
    message: str,
    bad_word: str
):
    """
    Логирует нарушение
    """
    data = load_violations()
    
    violation = {
        "id": len(data["violations"]) + 1,
        "timestamp": datetime.now().isoformat(),
        "user_id": user_id,
        "username": username or "unknown",
        "first_name": first_name or "",
        "recipient": recipient,
        "message": message,
        "bad_word": bad_word,
    }
    
    data["violations"].append(violation)
    
    # Обновляем статистику по пользователям
    user_key = str(user_id)
    if user_key not in data["stats"]:
        data["stats"][user_key] = {
            "username": username or "unknown",
            "first_name": first_name or "",
            "count": 0,
            "words": []
        }
    
    data["stats"][user_key]["count"] += 1
    if bad_word not in data["stats"][user_key]["words"]:
        data["stats"][user_key]["words"].append(bad_word)
    
    save_violations(data)
    
    return violation


def get_user_violations_count(user_id: int) -> int:
    """Получает количество нарушений пользователя"""
    data = load_violations()
    user_stats = data.get("stats", {}).get(str(user_id), {})
    return user_stats.get("count", 0)


def get_recent_violations(limit: int = 10) -> list:
    """Получает последние нарушения"""
    data = load_violations()
    violations = data.get("violations", [])
    return violations[-limit:][::-1]  # Последние N в обратном порядке


def get_violations_stats() -> dict:
    """Получает общую статистику нарушений"""
    data = load_violations()
    
    violations = data.get("violations", [])
    stats = data.get("stats", {})
    
    # Подсчёт по словам
    word_counts = {}
    for v in violations:
        word = v.get("bad_word", "unknown")
        word_counts[word] = word_counts.get(word, 0) + 1
    
    # Топ нарушителей
    top_violators = sorted(
        stats.items(),
        key=lambda x: x[1].get("count", 0),
        reverse=True
    )[:5]
    
    return {
        "total_violations": len(violations),
        "unique_users": len(stats),
        "word_counts": word_counts,
        "top_violators": top_violators
    }


def clear_violations():
    """Очищает все логи нарушений"""
    save_violations({"violations": [], "stats": {}})