from openai import OpenAI
from wardrobe_app.config import settings
import aiohttp
from typing import Dict, Any, Optional
import asyncio


class WeatherForecast:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.openweathermap.org/data/2.5"
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def get_forecast(
        self,
        city: str,
        days: int = 1,
        lang: str = "ru",
    ) -> dict:
        if not self.session:
            raise RuntimeError("Use 'async with WeatherForecast(...)'")

        url = f"{self.base_url}/forecast"
        params = {
            "q": city,
            "appid": self.api_key,
            "units": "metric",
            "lang": lang,
        }

        async with self.session.get(url, params=params, timeout=10) as response:
            if response.status != 200:
                text = await response.text()
                raise RuntimeError(
                    f"OpenWeatherMap error {response.status}: {text}"
                )

            return await response.json()


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


async def main_rec(city: str = "Москва"):
    async with WeatherForecast(settings.WEATHERAPI_KEY) as weather:
        data = await weather.get_forecast(
            city=city,
            days=1,
            lang="ru",
        )

        today = data["list"][0]
        recommendation = get_clothing_recommendation(
            today["main"]["temp"],
            f"Ощущается как: {today["main"]["feels_like"]},\n Описание: {today["weather"][0]["description"]}, \n Ветер:{today["wind"]["speed"]} м/с",
            "male", 3)

        message = (
            f"Доброе утро!\n\n"
            f"Погода в Москве сегодня:\n"
            f"Температура: {today["main"]["temp"]:.1f}°C (ощущается как {today["main"]["feels_like"]:.1f}°C)\n"
            f"Условия: {today["weather"][0]["description"]}\n"
            f"Ветер: {today["wind"]["speed"]} км/ч\n\n"
            f"Рекомендация по одежде:\n{recommendation}\n"
            f"Хорошего дня! 🌤️"
        )
        return message
<<<<<<< HEAD
=======


if __name__ == "__main__":
    asyncio.run(main_rec())
>>>>>>> 2fe7b443d7233df4ec3f0f3e8f8696091008781c
