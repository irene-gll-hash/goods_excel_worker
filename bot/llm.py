import os
import json
import asyncio
from openai import AsyncOpenAI
from dotenv import load_dotenv
import chromadb
from chromadb.utils import embedding_functions

load_dotenv()

client = AsyncOpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)

DB_PATH = "chroma_tnved"
COLLECTION_NAME = "tnved"

_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="models/paraphrase-multilingual-MiniLM-L12-v2"
)
_chroma = chromadb.PersistentClient(path=DB_PATH)
_collection = _chroma.get_collection(
    name=COLLECTION_NAME,
    embedding_function=_ef
)

def search_tnved(query: str, n_results: int = 8) -> list[dict]:
    results = _collection.query(query_texts=[query], n_results=n_results)
    items = []
    for i in range(len(results["ids"][0])):
        meta = results["metadatas"][0][i]
        items.append({
            "code": meta["code"],
            "name": meta["name"],
            "rate": meta["rate"]
        })
    return items

def normalize_code(code: object) -> str:
    return "".join(character for character in str(code) if character.isdigit())


def get_tnved_record(code: str) -> dict | None:
    """Возвращает запись только при точном совпадении 10-значного кода."""
    normalized_code = normalize_code(code)
    if len(normalized_code) != 10:
        return None

    try:
        res = _collection.get(ids=[normalized_code], include=["metadatas"])
        if res["ids"]:
            return res["metadatas"][0]
    except Exception:
        pass
    return None


def get_rate_from_db(code: str) -> float | None:
    """Ищем точный код в базе и возвращаем ставку пошлины в процентах."""
    record = get_tnved_record(code)
    if not record:
        return None

    try:
        rate_str = record["rate"].replace(",", ".").split("%")[0].strip()
        rate_str = rate_str.split(" ")[0]
        return float(rate_str)
    except (AttributeError, TypeError, ValueError):
        return None

MAX_ATTEMPTS = 3
RAG_RESULTS = 15

async def get_hs_and_rates(product_name: str, purpose: str, specs: str) -> dict:
    """
    1. DeepSeek сам определяет код
    2. Ищем код в базе
    3. Если кода нет или он слабый — даём кандидатов и просим перепроверить
    4. Ставку пошлины всегда берём из базы
    5. НДС определяет DeepSeek (22 по умолчанию)
    """
    first_prompt = f"""
Ты — опытный таможенный классификатор, работающий с импортом из Китая в Россию.

Товар: {product_name}
Назначение: {purpose}
Характеристики: {specs}

Определи:
1. Наиболее точный 10-значный код ТН ВЭД ЕАЭС (Россия)
2. Соответствующий 10-значный код ТН ВЭД Китая
3. Ставку НДС: только 10 или 22 (22 по умолчанию, 10 — только для льготных категорий: продукты, детские товары, медицина, книги и т.п.)

Верни только JSON:
{{
  "cn_hs": "10 цифр",
  "ru_hs": "10 цифр",
  "vat_rate": 22,
  "confidence": 0.85
}}
"""
    data = None
    last_error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = await client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "Ты возвращаешь только валидный JSON."},
                    {"role": "user", "content": first_prompt}
                ],
                temperature=0.1,
                response_format={"type": "json_object"}
            )
            data = json.loads(response.choices[0].message.content)
            break
        except Exception as e:
            last_error = e
            if attempt < MAX_ATTEMPTS:
                await asyncio.sleep(1.5 * attempt)
    if not data:
        return {
            "cn_hs": "",
            "ru_hs": "",
            "duty_rate": 0,
            "vat_rate": 22,
            "confidence": 0,
            "error": str(last_error)
        }
    ru_hs = normalize_code(data.get("ru_hs", ""))
    cn_hs = normalize_code(data.get("cn_hs", ""))
    vat_rate = int(data.get("vat_rate", 22))
    confidence = float(data.get("confidence", 0.5))

    search_query = f"{product_name} {purpose} {specs}".strip()
    candidates = search_tnved(search_query, n_results=RAG_RESULTS)
    candidate_codes = {normalize_code(candidate["code"]) for candidate in candidates}
    record = get_tnved_record(ru_hs)
    code_confirmed = record is not None and ru_hs in candidate_codes

    if not code_confirmed:
        candidates_text = "\n".join(
            f"- {c['code']} | {c['name'][:300]} | ставка: {c['rate']}"
            for c in candidates
        )
        database_status = (
            "код существует в базе, но не совпал с кандидатами RAG"
            if record
            else "код отсутствует в базе"
        )
        second_prompt = f"""
Товар: {product_name}
Назначение: {purpose}
Характеристики: {specs}

При первой независимой классификации ты предложил код: {ru_hs}
Результат проверки: {database_status}.

RAG нашёл в официальной базе следующие наиболее релевантные коды:
{candidates_text}

Ещё раз внимательно сопоставь назначение, материал, состав и характеристики товара.
Выбери ровно один наиболее подходящий 10-значный код ТН ВЭД РФ только из списка RAG выше.
Также укажи НДС (10 или 22).

Верни только JSON:
{{
  "cn_hs": "10 цифр",
  "ru_hs": "10 цифр",
  "vat_rate": 22,
  "confidence": 0.7
}}
"""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = await client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[
                        {"role": "system", "content": "Ты возвращаешь только валидный JSON."},
                        {"role": "user", "content": second_prompt}
                    ],
                    temperature=0.1,
                    response_format={"type": "json_object"}
                )
                data2 = json.loads(response.choices[0].message.content)
                checked_ru_hs = normalize_code(data2.get("ru_hs", ""))
                if checked_ru_hs not in candidate_codes:
                    raise ValueError("DeepSeek выбрал код не из кандидатов RAG")

                checked_record = get_tnved_record(checked_ru_hs)
                if not checked_record:
                    raise ValueError("Выбранный код отсутствует в базе ТН ВЭД")

                ru_hs = checked_ru_hs
                cn_hs = normalize_code(data2.get("cn_hs", cn_hs))
                vat_rate = int(data2.get("vat_rate", vat_rate))
                confidence = float(data2.get("confidence", 0.6))
                record = checked_record
                code_confirmed = True
                break
            except Exception as e:
                last_error = e
                if attempt < MAX_ATTEMPTS:
                    await asyncio.sleep(1.5 * attempt)
    if not code_confirmed:
        raise RuntimeError(
            f"Не удалось подтвердить код ТН ВЭД через RAG: {last_error}"
        )

    duty_rate = get_rate_from_db(ru_hs)
    if duty_rate is None:
        raise RuntimeError(f"Для кода {ru_hs} в базе нет простой процентной ставки")
    return {
        "cn_hs": cn_hs,
        "ru_hs": ru_hs,
        "duty_rate": duty_rate,
        "vat_rate": vat_rate,
        "confidence": confidence
    }
