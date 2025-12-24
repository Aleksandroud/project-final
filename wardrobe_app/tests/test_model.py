import pytest
from unittest.mock import MagicMock

from wardrobe_app.services.recommendation import (
    after_think,
    get_clothing_recommendation,
    STYLES,
    client,
)

@pytest.fixture
def mock_llm_response():
    mock_choice = MagicMock()
    mock_choice.message.content = "Лёгкая футболка и шорты будут идеально. Не забудь кроссовки!"

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    return mock_response


@pytest.mark.asyncio
async def test_after_think_removes_think_tags():
    text_with_think = """
    <think>Анализирую погоду...</think>
    <think>Учитываю стиль casual</think>
    Надень лёгкую куртку и джинсы.
    """
    expected = "Надень лёгкую куртку и джинсы."
    assert after_think(text_with_think) == expected.strip()

    text_no_think = "Просто рекомендация без тегов."
    assert after_think(text_no_think) == text_no_think.strip()

    text_end_think = "Рекомендация<think>финальный анализ</think>"
    assert after_think(text_end_think) == ""


@pytest.mark.asyncio
async def test_get_clothing_recommendation_calls_llm_correctly(mock_llm_response, monkeypatch):
    mock_create = MagicMock(return_value=mock_llm_response)
    monkeypatch.setattr(client.chat.completions, "create", mock_create)

    result = get_clothing_recommendation(
        temperature=25.0,
        conditions="ясно",
        gender="male",
        style=2  # casual
    )

    mock_create.assert_called_once()
    call_args = mock_create.call_args[1]

    assert call_args["model"] == "deepseek-ai/DeepSeek-R1-0528:together"
    assert call_args["temperature"] == 0.6

    messages = call_args["messages"]
    assert len(messages) == 2

    system_content = messages[0]["content"]
    assert "бот-стилист" in system_content
    assert "кратко" in system_content
    assert "не больше 25 слов" in system_content
    assert "Не нужно здороваться или прощаться" in system_content
    assert "только рекомендации по одежде" in system_content

    user_content = messages[1]["content"]
    assert "Пол: male" in user_content
    assert "Стиль одежды: casual" in user_content
    assert "Температура: 25.0" in user_content
    assert "Погода: ясно" in user_content
    assert "Что мне надеть сегодня?" in user_content


@pytest.mark.asyncio
async def test_get_clothing_recommendation_different_styles_and_genders(mock_llm_response, monkeypatch):
    mock_create = MagicMock(return_value=mock_llm_response)
    monkeypatch.setattr(client.chat.completions, "create", mock_create)

    result_female = get_clothing_recommendation(10, "облачно", "female", style=4)

    user_content = mock_create.call_args_list[-1][1]["messages"][1]["content"]
    assert "Пол: female" in user_content
    assert "Стиль одежды: minimalism" in user_content

    result_no_style = get_clothing_recommendation(0, "дождь", "male", style=0)
    user_content = mock_create.call_args_list[-1][1]["messages"][1]["content"]
    assert "Стиль одежды: предпочтений нет" in user_content


def test_styles_dictionary():
    assert len(STYLES) == 6
    assert STYLES[0] == "предпочтений нет"
    assert STYLES[1] == "classic"
    assert STYLES[5] == "streetwear"