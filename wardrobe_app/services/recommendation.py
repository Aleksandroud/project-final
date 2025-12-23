def get_clothing_recommendation(
        temperature: float,
        conditions: str,
        style: int = 1,
        gender: str = "male"
) -> str:
    """
    Заглушка для рекомендательной системы.

    Args:
        temperature: Температура в °C
        conditions: Описание погоды ("ясно", "дождь" и т.д.)
        style: Номер стиля от 1 до 10
        gender: "male" или "female"

    Returns:
        Фиксированная рекомендация
    """
    return "Сегодня наденьте удобную одежду по погоде. Не забудьте зонт на случай дождя!"