from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

STYLES = {
    "classic": "👔 Классический",
    "casual": "😌 Повседневный",
    "sporty": "🏃 Спортивный",
    "minimalism": "🧱 Минимализм",
    "streetwear": "🗽 Уличный"
}

STYLE_TO_NUMBER = {
    "classic": 1,
    "casual": 2,
    "sporty": 3,
    "minimalism": 4,
    "streetwear": 5
}

STYLE_NAMES = {
    "classic": "Классический",
    "casual": "Повседневный",
    "sporty": "Спортивный",
    "minimalism": "Минимализм",
    "streetwear": "Уличный"
}


def get_style_choice_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    row = []

    for i, (style_key, style_name) in enumerate(STYLES.items(), 1):
        row.append(InlineKeyboardButton(
            text=style_name,
            callback_data=f"style_{style_key}"
        ))

        if i % 2 == 0 or i == len(STYLES):
            buttons.append(row)
            row = []

    return InlineKeyboardMarkup(inline_keyboard=buttons)