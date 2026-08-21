import os
import tempfile
from aiogram import Router, F, Bot
from aiogram.types import Message, FSInputFile, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from bot.excel_processor import process_excel
from bot.llm import get_hs_and_rates

router = Router()

class Modes(StatesGroup):
    choosing = State()
    table_mode = State()
    code_mode = State()

def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Таблица DDP")],
            [KeyboardButton(text="Код ТН ВЭД")],
        ],
        resize_keyboard=True)

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.set_state(Modes.choosing)
    await message.answer(
        "Привет! Выбери режим:",
        reply_markup=main_keyboard())

@router.message(F.text == "Таблица DDP")
async def mode_table(message: Message, state: FSMContext):
    await state.set_state(Modes.table_mode)
    await message.answer(
        "Режим таблицы.\nОтправьте Excel-файл.",
        reply_markup=ReplyKeyboardRemove())

@router.message(F.text == "Код ТН ВЭД")
async def mode_code(message: Message, state: FSMContext):
    await state.set_state(Modes.code_mode)
    await message.answer(
        "Режим определения кода ТН ВЭД.\n"
        "Пришлите описание товара.",
        reply_markup=ReplyKeyboardRemove())

@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext):
    await state.set_state(Modes.choosing)
    await message.answer("Выбери режим:", reply_markup=main_keyboard())

@router.message(Modes.table_mode, F.document)
async def handle_document(message: Message, bot: Bot, state: FSMContext):
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
    await message.answer("Выбери режим:", reply_markup=main_keyboard())
    await state.set_state(Modes.choosing)

@router.message(Modes.code_mode, F.text)
async def handle_code_request(message: Message, state: FSMContext):
    text = message.text.strip()
    if len(text) < 5:
        await message.answer("Слишком короткое описание. Напиши подробнее.")
        return
    status = await message.answer("Думаю...")
    try:
        result = await get_hs_and_rates(
            product_name=text,
            purpose="",
            specs=""
        )
        cn = result.get("cn_hs", "—")
        ru = result.get("ru_hs", "—")
        duty = result.get("duty_rate", 0)
        vat = result.get("vat_rate", 22)
        conf = result.get("confidence", 0)
        reply = (
            f"<b>Результат:</b>\n\n"
            f"🇷🇺 Код ТН ВЭД РФ: <code>{ru}</code>\n"
            f"🇨🇳 Код ТН ВЭД КНР: <code>{cn}</code>\n"
            f"Ставка пошлины: <b>{duty}%</b>\n"
            f"НДС: <b>{vat}%</b>\n"
            f"Уверенность: {conf:.0%}"
        )
        await status.edit_text(reply)
    except Exception as e:
        await status.edit_text(f"Ошибка:\n<code>{str(e)}</code>")
    await message.answer("Можешь прислать ещё описание или /menu для смены режима.")

@router.message(Modes.choosing)
async def choose_mode(message: Message):
    await message.answer("Выбери режим кнопкой ниже:", reply_markup=main_keyboard())