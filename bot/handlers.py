import os
import tempfile
from aiogram import Router, F, Bot
from aiogram.types import Message, FSInputFile
from aiogram.filters import CommandStart
from bot.excel_processor import process_excel

router = Router()

@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "Привет! Отправь Excel-файл (.xlsx) с таблицей DDP — я полностью заполню его."
    )
@router.message(F.document)
async def handle_document(message: Message, bot: Bot):
    document = message.document
    if not document.file_name.lower().endswith(".xlsx"):
        await message.answer("Нужен файл в формате .xlsx")
        return
    status = await message.answer("Файл получен. Начинаю обработку...")
    result_path = None
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        file_path = tmp.name

    try:
        await bot.download(document, destination=file_path)
        result_path, info = await process_excel(file_path, status)
        result_file = FSInputFile(result_path, filename="DDP_filled.xlsx")
        await message.answer_document(
            result_file,
            caption=f"Готово!\n{info}"
        )
    except Exception as e:
        await status.edit_text(f"Ошибка при обработке:\n<code>{str(e)}</code>")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)
        if result_path and os.path.exists(result_path):
            os.remove(result_path)
