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

def get_rate_from_db(code: str) -> float | None:
    """Ищем точный код в базе и возвращаем ставку пошлины в процентах"""
    try:
        res = _collection.get(ids=[code], include=["metadatas"])
        if res["ids"]:
            rate_str = res["metadatas"][0]["rate"]
            rate_str = rate_str.replace(",", ".").split("%")[0].strip()
            rate_str = rate_str.split(" ")[0]
            return float(rate_str)
    except Exception:
        pass
    return None

MAX_ATTEMPTS = 3

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
    ru_hs = str(data.get("ru_hs", "")).strip()
    cn_hs = str(data.get("cn_hs", "")).strip()
    vat_rate = int(data.get("vat_rate", 22))
    confidence = float(data.get("confidence", 0.5))
    duty_rate = get_rate_from_db(ru_hs)
    if duty_rate is None:
        search_query = f"{product_name} {purpose} {specs}"
        candidates = search_tnved(search_query, n_results=8)
        candidates_text = "\n".join(
            f"- {c['code']} | {c['name'][:100]} | ставка: {c['rate']}"
            for c in candidates
        )
        second_prompt = f"""
Товар: {product_name}
Назначение: {purpose}
Характеристики: {specs}

Ты предложил код: {ru_hs}

Этот код не найден в официальной базе. Вот наиболее релевантные коды из базы:
{candidates_text}

Выбери наиболее подходящий код из списка (или подтверди свой, если уверен).
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
                ru_hs = str(data2.get("ru_hs", ru_hs)).strip()
                cn_hs = str(data2.get("cn_hs", cn_hs)).strip()
                vat_rate = int(data2.get("vat_rate", vat_rate))
                confidence = float(data2.get("confidence", 0.6))
                duty_rate = get_rate_from_db(ru_hs)
                break
            except Exception as e:
                last_error = e
                if attempt < MAX_ATTEMPTS:
                    await asyncio.sleep(1.5 * attempt)
    if duty_rate is None:
        duty_rate = 0
    return {
        "cn_hs": cn_hs,
        "ru_hs": ru_hs,
        "duty_rate": duty_rate,
        "vat_rate": vat_rate,
        "confidence": confidence
    }