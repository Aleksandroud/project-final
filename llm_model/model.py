import os
from openai import OpenAI
from collect_data import get_user_profile


def after_think(text: str) -> str:
    last_think_pos = text.rfind("</think>")
    if last_think_pos == -1:
        return text
    return text[last_think_pos + len("</think>"):].strip()


client = OpenAI(
    base_url="https://router.huggingface.co/v1",
    api_key=os.environ["HUGGINGFACE_API_KEY"],
)

def generate_clothing_recommendation(
    telegram_id: int,
    weather_description: str,
) -> str:
    profile = get_user_profile(telegram_id)

    if profile is None:
        return "Я пока не знаю ничего о вас. Пожалуйста, заполните профиль 🙂"

    user_context = f"""
    Имя: {profile.get("first_name")}
    Пол: {profile.get("gender")}
    Город: {profile.get("city")}
    Стиль одежды: {profile.get("clothing_style")}
    """

    # user_context = f"""
    #     Имя: Иван
    #     Пол: male
    #     Город: Москва
    #     Стиль одежды: спортивный
    # """

    messages = [
        {
            "role": "system",
            "content": (
                "Ты — бот-стилист. "
                "Давай персональные советы по тому, что пользователю надеть на русском языке, "
                "учитывая профиль пользователя и погоду. "
                "Пиши кратко, дружелюбно и по делу, "
                "Используй разговорные слова, не нужно использовать термины, типа с мембраной и хорошим протектором, пиши по-человечески. "
                "Не забудь добавить пожелание на день."
                "Кратко скажи какая будет погода,"
                "Напиши максимально краткие и емкие рекомендации, не больше 50 слов на все сообщение."
            ),
        },
        {
            "role": "user",
            "content": (
                f"{user_context}\n\n"
                f"Погода: {weather_description}\n"
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

text = generate_clothing_recommendation(
    telegram_id=123456789,
    weather_description="7–15°C, дождь и сильный ветер",
)

print(text)
