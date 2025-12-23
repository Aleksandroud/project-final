from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_style_choice_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура с кнопками 1-10 для выбора стиля"""
    buttons = []
    row = []

    for i in range(1, 11):
        row.append(InlineKeyboardButton(text=str(i), callback_data=f"style_{i}"))
        if i % 5 == 0 or i == 10:  # По 5 кнопок в строке
            buttons.append(row)
            row = []

    return InlineKeyboardMarkup(inline_keyboard=buttons)