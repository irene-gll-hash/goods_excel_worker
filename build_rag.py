import openpyxl
import chromadb
from chromadb.utils import embedding_functions
from pathlib import Path

EXCEL_PATH = "TWS_TNVED_2026-08-21.xlsx"  # или путь к твоему файлу
DB_PATH = "chroma_tnved"
COLLECTION_NAME = "tnved"

def main():
    print("Читаю Excel...")
    wb = openpyxl.load_workbook(EXCEL_PATH, read_only=True)
    ws = wb["ТНВЭД"]
    documents = []
    metadatas = []
    ids = []
    for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=1):
        if not row or not row[0]:
            continue
        code = str(row[0]).strip()
        name = str(row[1] or "").strip()
        rate = str(row[2] or "").strip()
        text = f"{code} {name}"
        documents.append(text)
        metadatas.append({
            "code": code,
            "name": name,
            "rate": rate
        })
        ids.append(code)
    print(f"Записей: {len(documents)}")
    print("Создаю ChromaDB...")
    client = chromadb.PersistentClient(path=DB_PATH)
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="models/paraphrase-multilingual-MiniLM-L12-v2"
    )
    try:
        client.delete_collection(COLLECTION_NAME)
    except:
        pass
    collection = client.create_collection(
        name=COLLECTION_NAME,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"}
    )
    batch_size = 500
    for start in range(0, len(documents), batch_size):
        end = start + batch_size
        collection.add(
            documents=documents[start:end],
            metadatas=metadatas[start:end],
            ids=ids[start:end]
        )
        print(f"  {end}/{len(documents)}")
    print("Готово! База сохранена в папку:", DB_PATH)

if __name__ == "__main__":
    main()