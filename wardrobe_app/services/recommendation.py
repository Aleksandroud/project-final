from openai import OpenAI
from wardrobe_app.config import settings


def after_think(text: str) -> str:
    last_think_pos = text.rfind("</think>")
    if last_think_pos == -1:
        return text
    return text[last_think_pos + len("</think>"):].strip()

client = OpenAI(
    base_url="https://router.huggingface.co/v1",
    api_key=settings.HUGGINGFACE_API_KEY,
)

STYLES = {
    0: "предпочтений нет",
    1: "classic",
    2: "casual",
    3: "sporty",
    4: "minimalism",
    5: "streetwear"
}

def get_clothing_recommendation(
        temperature: float,
        conditions: str,
        gender: str = "male",
        style: int = 0
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

    user_context = f"""
    Пол: {gender}
    Стиль одежды: {STYLES[style]}
    """

    messages = [
        {
            "role": "system",
            "content": (
                "Ты — бот-стилист. "
                "Давай персональные советы по тому, что пользователю надеть на русском языке, "
                "учитывая профиль пользователя и погоду. "
                "Пиши кратко, дружелюбно и по делу, "
                "Используй разговорные слова, не нужно использовать термины, типа с мембраной и хорошим протектором, пиши по-человечески. "
                "Не нужно здороваться или прощаться с пользователем, нужно написать только рекомендации по одежде."
                "Напиши максимально краткие и емкие рекомендации без лишней информации, не больше 25 слов на все сообщение."
            ),
        },
        {
            "role": "user",
            "content": (
                f"{user_context}\n\n"
                f"Температура: {temperature}\n"
                f"Погода: {conditions}\n"
                "Что мне надеть сегодня?"
            ),
        },
    ]

    response = client.chat.completions.create(
        model="deepseek-ai/DeepSeek-R1-0528:together",
        messages=messages,
        temperature=0.6,
    )

    return after_think(
        response.choices[0].message.content
    )

print(get_clothing_recommendation(34, "ясно"))