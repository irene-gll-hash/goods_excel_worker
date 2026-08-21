import os
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

client = AsyncOpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)

async def get_hs_and_rates(product_name: str, purpose: str, specs: str) -> dict:
    """
    Определяет коды ТН ВЭД и ставки через DeepSeek
    """
    prompt = f"""
Ты — опытный таможенный классификатор, работающий с импортом из Китая в Россию.

Товар: {product_name}
Назначение: {purpose}
Характеристики: {specs}

Твоя задача:
1. Определить наиболее точный 10-значный код ТН ВЭД ЕАЭС (Россия).
2. Подобрать соответствующий 10-значный код ТН ВЭД Китая.
3. Указать ставку ввозной пошлины по этому коду (в долях).
4. Указать ставку НДС при импорте: только 0.10 или 0.22.

Важные правила:
- Код ТН ВЭД должен быть реальным и максимально точным.
- Если есть сомнения между несколькими кодами — выбирай наиболее вероятный и снижай confidence.
- Ставка НДС: 0.22 по умолчанию. 0.10 — только если товар явно относится к льготным категориям (продукты, детские товары, медицина и т.п.).
- Не придумывай ставки пошлины. Если не уверен — ставь наиболее распространённую для этой группы.

Верни только JSON:
{{
  "cn_hs": "10 цифр",
  "ru_hs": "10 цифр",
  "duty_rate": 0.0,
  "vat_rate": 0.22,
  "confidence": 0.0
}}
"""
    response = await client.chat.completions.create(
        model="deepseek-v4-pro",
        messages=[
            {"role": "system", "content": "Ты возвращаешь только валидный JSON."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.1,
        response_format={"type": "json_object"}
    )

    import json
    return json.loads(response.choices[0].message.content)