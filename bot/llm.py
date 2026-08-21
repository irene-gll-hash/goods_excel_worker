import asyncio
import json
import logging
import os
import random

from openai import AsyncOpenAI
from openai import AuthenticationError, BadRequestError, PermissionDeniedError
from dotenv import load_dotenv

load_dotenv()

client = AsyncOpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
    max_retries=0,
    timeout=60.0,
)

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 5


def _parse_and_validate_response(content: str | None) -> dict:
    if not content:
        raise ValueError("DeepSeek вернул пустой ответ")

    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```")
        cleaned = cleaned.removesuffix("```").strip()

    result = json.loads(cleaned)
    required_fields = {"cn_hs", "ru_hs", "duty_rate", "vat_rate"}
    missing_fields = required_fields - result.keys()
    if missing_fields:
        raise ValueError(
            f"В ответе DeepSeek нет полей: {', '.join(sorted(missing_fields))}"
        )

    for field in ("cn_hs", "ru_hs"):
        code = str(result[field]).replace(" ", "")
        if len(code) != 10 or not code.isdigit():
            raise ValueError(f"Некорректный код {field}: {result[field]}")
        result[field] = code

    result["duty_rate"] = float(result["duty_rate"])
    result["vat_rate"] = float(result["vat_rate"])
    if not 0 <= result["duty_rate"] <= 1:
        raise ValueError("Ставка пошлины должна быть от 0 до 1")
    if result["vat_rate"] not in (0.1, 0.22):
        raise ValueError("Ставка НДС должна быть 0.10 или 0.22")

    return result

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
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = await client.chat.completions.create(
                model="deepseek-v4-pro",
                messages=[
                    {"role": "system", "content": "Ты возвращаешь только валидный JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                response_format={"type": "json_object"}
            )
            return _parse_and_validate_response(response.choices[0].message.content)
        except (AuthenticationError, PermissionDeniedError, BadRequestError):
            # Повтор не поможет при неверном ключе, правах или параметрах запроса.
            raise
        except Exception as error:
            if attempt == MAX_ATTEMPTS:
                raise RuntimeError(
                    f"DeepSeek не ответил корректно после {MAX_ATTEMPTS} попыток: {error}"
                ) from error

            delay = min(2 ** attempt, 20) + random.uniform(0, 1)
            logger.warning(
                "Ошибка DeepSeek (попытка %s/%s): %s. Повтор через %.1f сек.",
                attempt,
                MAX_ATTEMPTS,
                error,
                delay,
            )
            await asyncio.sleep(delay)
