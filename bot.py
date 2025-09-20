import os
import asyncio
import logging
import sys
import shlex
import hashlib
from typing import Dict, Any, Optional
from aiogram.enums import ParseMode
from cryptography.exceptions import UnsupportedAlgorithm

import asyncssh
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, StateFilter, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa, ed25519
from dotenv import load_dotenv

BOT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BOT_DIR, 'logs')

load_dotenv()



# Создаём базовый logger ДО настройки
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def setup_logging():
    """Безопасная настройка логирования"""
    global logger
    
    # Создаём директорию логов, если её нет
    os.makedirs(LOG_DIR, exist_ok=True)
    
    # Определяем путь к файлу лога
    log_file = os.path.join(LOG_DIR, 'bot.log')
    
    # Формат логов
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    
    # Настройка для Windows
    if os.name == 'nt':
        import sys
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
        
        # Пытаемся удалить старый файл лога, если он существует
        if os.path.exists(log_file):
            try:
                # Закрываем все открытые FileHandler'ы
                for handler in logging.root.handlers[:]:
                    if isinstance(handler, logging.FileHandler):
                        handler.close()
                        logging.root.handlers.remove(handler)
                
                # Теперь безопасно удаляем
                if os.path.exists(log_file):
                    os.remove(log_file)
                    
                logger.info("🧹 Старый лог-файл удалён (Windows)")
            except (PermissionError, OSError) as e:
                logger.warning(f"⚠️ Не удалось удалить старый лог: {e}")
        
        # Настраиваем новый FileHandler
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(logging.Formatter(log_format))
        
        # Удаляем старые handlers и добавляем новые
        logging.root.handlers.clear()
        logging.root.addHandler(file_handler)
        logging.root.addHandler(logging.StreamHandler(sys.stdout))
        logging.root.setLevel(logging.INFO)
        
    else:
        # Настройка для Unix/Linux/Mac
        try:
            # Пытаемся удалить старый файл лога
            if os.path.exists(log_file):
                os.remove(log_file)
                logger.info("🧹 Старый лог-файл удалён (Unix)")
        except (PermissionError, OSError) as e:
            logger.warning(f"⚠️ Не удалось удалить старый лог: {e}")
        
        # Настраиваем новый FileHandler
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(logging.Formatter(log_format))
        
        # Удаляем старые handlers и добавляем новые
        logging.root.handlers.clear()
        logging.root.addHandler(file_handler)
        logging.root.addHandler(logging.StreamHandler())
        logging.root.setLevel(logging.INFO)
    
    # Устанавливаем формат для всех handlers
    for handler in logging.root.handlers:
        handler.setFormatter(logging.Formatter(log_format))
    
    logger.info("📝 Логирование настроено")
    return logger

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN не найден в .env файле!")
    logger.error("💡 Создайте файл .env в корне проекта с содержимым:")
    logger.error("   BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrSTU")
    logger.error("💡 Шаблон: скопируйте .env.example → .env")
    logger.error("💡 Получите токен: @BotFather в Telegram")
    
    # Для Docker показываем дополнительную инструкцию
    if os.path.exists('/.dockerenv') or os.getenv('DOCKER_CONTAINER'):
        logger.error("🐳 DOCKER: Запустите с --env-file .env")
        logger.error("🐳 Пример: docker run --env-file .env your_image")
    
    sys.exit(1)

logger.info(f"✅ BOT_TOKEN успешно загружен (длина: {len(BOT_TOKEN)} символов)")
logger.info("🔐 Крипто-генератор: инициализация...")


# Инициализация логирования
logger = setup_logging()

PM2_RUNNING = os.getenv('BOT_TYPE') == 'docker-pm2' or 'pm2' in ' '.join(sys.argv).lower()

if PM2_RUNNING:
    logger.info("🚀 PM2 detected - running in production mode")
    os.environ['PYTHONUNBUFFERED'] = '1'

# Проверяем монтирование директории (только для Docker)
if os.path.ismount(LOG_DIR):
    logger.info("✅ Logs directory is mounted (Docker)")
else:
    logger.info("✅ Local logs directory ready")

if PM2_RUNNING:
    # Переконфигурируем логирование для PM2 (только stdout)
    for handler in logging.root.handlers[:]:
        if isinstance(handler, logging.FileHandler):
            try:
                handler.close()
                logging.root.handlers.remove(handler)
            except Exception as e:
                logger.warning(f"Не удалось закрыть file handler для PM2: {e}")
    
    # Добавляем только StreamHandler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    
    logging.root.handlers.clear()
    logging.root.addHandler(console_handler)
    logging.root.setLevel(logging.INFO)
    
    logger.info("📝 PM2 logging configured (stdout only)")


bot = Bot(token=os.getenv("BOT_TOKEN"))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

class CryptoSteps(StatesGroup):
    main_menu = State()
    ssh_menu = State()
    choose_ssh_key_type = State()
    ssh_get_passphrase = State()
    ssh_get_server_info = State()
    ssh_get_existing_public_key = State()
    ssh_get_server_info_for_existing = State()
    ssh_wait_for_password = State()
    ssh_wait_for_2fa = State()
    hash_menu = State()
    hash_choose_algorithm = State()
    hash_get_input = State()


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔑 SSH-ключи", callback_data="ssh_menu")],
        [InlineKeyboardButton(text="🔐 Хеширование", callback_data="hash_menu")]
    ])

def get_ssh_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔑 Сгенерировать новый SSH-ключ", callback_data="ssh_generate")],
        [InlineKeyboardButton(text="📤 Экспортировать существующий", callback_data="ssh_export")],
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="main_menu")]
    ])

def get_ssh_key_type_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="RSA (4096)", callback_data="ssh_key_rsa"),
         InlineKeyboardButton(text="Ed25519", callback_data="ssh_key_ed25519")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="ssh_menu")]
    ])

def get_hash_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔐 Вычислить хеш", callback_data="hash_calculate")],
        [InlineKeyboardButton(text="ℹ️ Справка по алгоритмам", callback_data="hash_info")],
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="main_menu")]
    ])

def get_hash_algorithm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="MD5", callback_data="hash_md5"),
         InlineKeyboardButton(text="SHA-1", callback_data="hash_sha1")],
        [InlineKeyboardButton(text="SHA-256", callback_data="hash_sha256"),
         InlineKeyboardButton(text="SHA-512", callback_data="hash_sha512")],
        [InlineKeyboardButton(text="BLAKE2b", callback_data="hash_blake2b"),
         InlineKeyboardButton(text="⬅️ Назад", callback_data="hash_menu")]
    ])

def get_ssh_export_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Экспортировать на сервер", callback_data="ssh_export_server")],
        [InlineKeyboardButton(text="⬅️ SSH-меню", callback_data="ssh_menu")]
    ])

def get_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
    ])

def get_passphrase_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Без passphrase", callback_data="no_passphrase")]
    ])

async def set_bot_commands():
    """Автоматическая регистрация команд в BotFather"""
    commands = [
        types.BotCommand(
            command="start",
            description="🚀 Запустить бота и главное меню"
        ),
        types.BotCommand(
            command="help", 
            description="📖 Показать справку по функциям"
        )
    ]
    
    try:
        await bot.set_my_commands(commands)
        logger.info("✅ Команды успешно зарегистрированы в BotFather")
    except Exception as e:
        logger.error(f"❌ Ошибка регистрации команд: {e}")

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Обработчик команды /start"""
    await state.clear()
    await message.answer(
        "🔐 *Крипто-генератор*\n\n"
        "Я помогу тебе сгенерировать:\n"
        "• SSH-ключи для серверов\n"
        "• Хеши для проверки целостности\n\n"
        "Выберите раздел:",
        reply_markup=get_main_menu_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    await state.set_state(CryptoSteps.main_menu)

@dp.message(Command("help"))
async def cmd_help(message: Message, state: FSMContext):
    """Обработчик команды /help - минимальная версия"""
    await state.clear()
    
    help_text = (
        "🔑 *Crypto Key Generator* — ваш крипто-арсенал\n\n"
        
        "🎯 *Что я умею:*\n\n"
        
        "**🔐 SSH-ключи:**\n"
        "• Генерация RSA 4096 бит и Ed25519\n"
        "• Шифрование с секретной фразой (рекомендуется)\n"
        "• Два формата: OpenSSH (.pem) + PKCS#8 (PEM)\n\n"
        
        "**📤 Экспорт на сервер:**\n"
        "• Поддержка пароля и 2FA\n"
        "• Автоматическое создание ~/.ssh/authorized\\_keys\n"
        "• Права доступа: chmod 700\\/600\n\n"
        
        "**🔍 Хеширование:**\n"
        "• Алгоритмы: MD5, SHA-1, SHA-256, SHA-512, BLAKE2b\n"
        "• *Файлы до 20 МБ* (лимит Bot API) + любой текст\n"
        "• Hex-формат, мгновенный результат\n\n"
        "⚠️ *Для файлов >20 МБ:* сожмите или используйте онлайн-сервисы\n\n"

        "**⚠️ Безопасность:**\n"
        "• Приватные ключи — ваш секрет!\n"
        "• Без секретной фразы = храните как золото\n"
        "• Сообщения с паролями удаляются\n\n"
        
        "**👨‍💻 Для кого:** Системные администраторы, DevOps, разработчики\n\n"
        "💡 *Начните с /start*"
    )
    
    try:
        await message.answer(
            help_text,
            reply_markup=get_main_menu_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.warning(f"Markdown ошибка в /help: {e}. Отправляю plain text.")
        plain_text = help_text.replace('*', '').replace('\\', '').replace('_', '')
        await message.answer(
            plain_text,
            reply_markup=get_main_menu_keyboard()
        )



        

@dp.callback_query(StateFilter(CryptoSteps.main_menu), lambda c: c.data == "ssh_menu")
async def ssh_menu_handler(query: types.CallbackQuery, state: FSMContext):
    """SSH-меню"""
    await query.message.edit_text(
        "🔑 *SSH-ключи*\n\n"
        "Генерация и управление SSH-ключами для безопасного доступа к серверам:",
        reply_markup=get_ssh_menu_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    await state.set_state(CryptoSteps.ssh_menu)


@dp.callback_query(StateFilter(CryptoSteps.main_menu), lambda c: c.data == "hash_menu")
async def hash_menu_handler(query: types.CallbackQuery, state: FSMContext):
    """Хеш-меню"""
    await query.message.edit_text(
        "🔐 *Хеширование*\n\n"
        "Вычисление контрольных сумм для проверки целостности файлов:",
        reply_markup=get_hash_menu_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    await state.set_state(CryptoSteps.hash_menu)


# === SSH SECTION ===
@dp.callback_query(StateFilter(CryptoSteps.ssh_menu), lambda c: c.data == "ssh_generate")
async def ssh_start_key_generation(query: types.CallbackQuery, state: FSMContext):
    """Начало генерации SSH-ключа"""
    await query.message.edit_text(
        "🔑 *Генерация SSH-ключа*\n\n"
        "Выберите тип ключа для генерации:",
        reply_markup=get_ssh_key_type_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    await state.set_state(CryptoSteps.choose_ssh_key_type)


@dp.callback_query(StateFilter(CryptoSteps.ssh_menu), lambda c: c.data == "ssh_export")
async def ssh_start_existing_key_export(query: types.CallbackQuery, state: FSMContext):
    """Начало экспорта существующего SSH-ключа"""
    await query.message.edit_text(
        "📤 *Экспорт существующего SSH-ключа*\n\n"
        "Отправьте мне ваш *публичный* SSH-ключ (содержимое файла `.pub`):",
        reply_markup=get_cancel_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    await state.set_state(CryptoSteps.ssh_get_existing_public_key)


@dp.message(StateFilter(CryptoSteps.ssh_get_existing_public_key))
async def ssh_process_existing_public_key(message: Message, state: FSMContext):
    """Обработка публичного SSH-ключа пользователя"""
    public_key_input = message.text.strip() if message.text else ""
    
    if public_key_input.startswith(("ssh-rsa", "ssh-ed25519")):
        await state.update_data(public_key=public_key_input)
        await message.answer(
            "✅ Публичный ключ принят!\n\n"
            "Теперь введите данные для подключения к серверу в формате:\n\n"
            "`имя_пользователя@ip_адрес`\n\n"
            "*Например:* `root@192.168.1.1`",
            reply_markup=get_cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        await state.set_state(CryptoSteps.ssh_get_server_info_for_existing)
    else:
        await message.answer(
            "❌ Это не похоже на публичный SSH-ключ.\n\n"
            "Убедитесь, что вы скопировали содержимое файла `.pub` (начинается с `ssh-rsa` или `ssh-ed25519`).\n\n"
            "Попробуйте снова:",
            reply_markup=get_cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )


@dp.callback_query(StateFilter(CryptoSteps.choose_ssh_key_type), lambda c: c.data.startswith("ssh_key_"))
async def ssh_request_passphrase(query: types.CallbackQuery, state: FSMContext):
    """Запрос passphrase для SSH-ключа"""
    key_type = "RSA" if query.data == "ssh_key_rsa" else "Ed25519"
    await state.update_data(key_type=key_type, chat_id=query.message.chat.id)
    
    await query.message.edit_text(
        "🔐 *Настройка безопасности*\n\n"
        "Введите секретную фразу для шифрования приватного ключа (рекомендуется):\n\n"
        "*Секретная фраза — это пароль для защиты ключа. "
        "Без него любой, кто получит файл, сможет его использовать.*\n\n"
        "Или нажмите кнопку для генерации без passphrase.",
        reply_markup=get_passphrase_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    await state.set_state(CryptoSteps.ssh_get_passphrase)


@dp.callback_query(StateFilter(CryptoSteps.ssh_get_passphrase), lambda c: c.data == "no_passphrase")
async def ssh_generate_key_without_passphrase(query: types.CallbackQuery, state: FSMContext):
    """Генерация SSH-ключа без passphrase"""
    await query.message.delete()
    await ssh_generate_key(state, None)


@dp.message(StateFilter(CryptoSteps.ssh_get_passphrase))
async def ssh_generate_key_with_passphrase(message: Message, state: FSMContext):
    """Генерация SSH-ключа с passphrase"""
    passphrase = message.text.strip().encode('utf-8') if message.text.strip() else None
    await message.delete()
    await ssh_generate_key(state, passphrase)


async def ssh_generate_key(state: FSMContext, passphrase: Optional[bytes]):
    """Генерация SSH ключей"""
    user_data = await state.get_data()
    key_type = user_data.get("key_type")
    chat_id = user_data.get("chat_id")
    
    generation_msg = await bot.send_message(chat_id, "⏳ Генерирую SSH-ключи...")

    if key_type == "RSA":
        private_key_obj = rsa.generate_private_key(public_exponent=65537, key_size=4096)
        key_info = "RSA (4096 бит)"
    else:
        private_key_obj = ed25519.Ed25519PrivateKey.generate()
        key_info = "Ed25519"

    encryption = serialization.BestAvailableEncryption(passphrase) if passphrase else serialization.NoEncryption()
    
    # OpenSSH формат
    try:
        openssh_private_key_bytes = private_key_obj.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.OpenSSH,
            encryption_algorithm=encryption
        )
    except UnsupportedAlgorithm:
        await bot.send_message(
            chat_id, 
            "⚠️ bcrypt недоступен. Ключ без шифрования.\n"
            "Установите: `pip install bcrypt`",
            parse_mode=ParseMode.MARKDOWN
        )
        encryption = serialization.NoEncryption()
        openssh_private_key_bytes = private_key_obj.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.OpenSSH,
            encryption_algorithm=encryption
        )
    openssh_private_key_str = openssh_private_key_bytes.decode('utf-8')

    # PEM формат
    try:
        pem_private_key_bytes = private_key_obj.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=encryption
        )
    except UnsupportedAlgorithm:
        pem_private_key_bytes = private_key_obj.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
    pem_private_key_str = pem_private_key_bytes.decode('utf-8')

    # Публичный ключ
    public_key_obj = private_key_obj.public_key()
    ssh_public_key_bytes = public_key_obj.public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH
    )
    public_key_str = ssh_public_key_bytes.decode('utf-8')

    await state.update_data(
        private_key=openssh_private_key_str, 
        public_key=public_key_str,
        key_type=key_info
    )

    await generation_msg.edit_text(f"✅ *{key_info}* ключи готовы!", parse_mode=ParseMode.MARKDOWN)

    await bot.send_document(
        chat_id,
        BufferedInputFile(openssh_private_key_str.encode('utf-8'), 
                         filename=f"id_{key_type.lower().replace(' ', '_')}_openssh.pem"),
        caption=f"🔐 *Приватный SSH-ключ {key_info}*\n\n"
        f"Формат: OpenSSH\n"
        f"Расширение: `.pem`\n\n"
        f"⚠️ *Сохраните в надёжном месте!*",
        parse_mode=ParseMode.MARKDOWN
    )

    await bot.send_document(
        chat_id,
        BufferedInputFile(pem_private_key_str.encode('utf-8'), 
                         filename=f"id_{key_type.lower().replace(' ', '_')}_pem.pem"),
        caption=f"🔐 *Приватный SSH-ключ {key_info} (PEM)*\n\n"
        f"Формат: PKCS#8\n"
        f"Расширение: `.pem`\n\n"
        f"📚 Для Python/Java/.NET",
        parse_mode=ParseMode.MARKDOWN
    )

    await bot.send_message(
        chat_id,
        f"```\n{public_key_str}\n```"
        f"🔓 *Публичный SSH-ключ*\n\n"
        f"Формат: OpenSSH\n"
        f"Расширение: `.pub`\n\n"
        f"✅ *Передавайте на серверы!*",
        parse_mode=ParseMode.MARKDOWN
    )

    if passphrase:
        await bot.send_message(
            chat_id,
            f"🔒 *{key_info}* защищены passphrase!\n\n"
            f"💡 *Не забудьте пароль!*",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await bot.send_message(
            chat_id,
            f"⚠️ *{key_info}* **без шифрования**!\n\n"
            f"🚨 *Храните в безопасности!*",
            parse_mode=ParseMode.MARKDOWN
        )

    await bot.send_message(
        chat_id,
        f"🚀 *Экспортировать {key_info} на сервер?*", parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_ssh_export_keyboard()
    )
    
    await state.set_state(CryptoSteps.ssh_get_server_info)
    await state.update_data(private_key=None)


@dp.callback_query(StateFilter(CryptoSteps.ssh_get_server_info), lambda c: c.data == "ssh_export_server")
async def ssh_request_server_info(query: types.CallbackQuery, state: FSMContext):
    """Запрос SSH-сервера"""
    await query.message.edit_text(
        "🌐 *SSH-подключение*\n\n"
        "Введите данные сервера:\n\n"
        "`пользователь@ip_адрес`\n\n"
        "*Примеры:*\n"
        "• `root@192.168.1.100`\n"
        "• `ubuntu@server.com`",
        reply_markup=get_cancel_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )


@dp.message(StateFilter(CryptoSteps.ssh_get_server_info, CryptoSteps.ssh_get_server_info_for_existing))
async def ssh_process_server_info(message: Message, state: FSMContext):
    """Обработка SSH-сервера"""
    server_input = message.text.strip()
    
    if '@' not in server_input or not server_input.split('@')[0] or not server_input.split('@')[1]:
        await message.answer(
            "*❌ Неверный формат!*\n\n"
            "Используйте: `пользователь@сервер`\n\n"
            "*Примеры:*\n"
            "• `root@192.168.1.100`\n"
            "• `ubuntu@server.com`",
            reply_markup=get_cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    await state.update_data(server_info=server_input, chat_id=message.chat.id)
    user_data = await state.get_data()
    asyncio.create_task(ssh_export_key_to_server(message, user_data))


async def ssh_export_key_to_server(message: Message, user_data: Dict[str, Any]):
    """Экспорт SSH-ключа на сервер"""
    chat_id = message.chat.id
    server_info = user_data.get('server_info')
    public_key = user_data.get('public_key')
    key_type = user_data.get('key_type', 'неизвестный')

    if not public_key:
        await bot.send_message(
            chat_id, 
            "*❌* Публичный ключ не найден!",
            reply_markup=get_main_menu_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    username, host = server_info.split('@', 1)
    
    connect_msg = await bot.send_message(
        chat_id,
        f"*🔌 Подключение* к `{server_info}`...\n\n"
        f"**Ключ:** {key_type}\n"
        f"**Пользователь:** {username}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_cancel_keyboard()
    )
    
    await bot.send_message(
        chat_id,
        "*⚠️ ВАЖНО:* Проверьте fingerprint сервера для первого подключения!",
        parse_mode=ParseMode.MARKDOWN
    )

    password_prompt = await bot.send_message(
        chat_id,
        f"*🔑 Пароль* для `{username}@{host}`:\n\n"
        f"*После экспорта — подключение без пароля!*",
        reply_markup=get_cancel_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    
    state = dp.fsm.resolve_context(bot, chat_id, chat_id)
    await state.set_state(CryptoSteps.ssh_wait_for_password)
    await state.update_data(
        password_prompt_message_id=password_prompt.message_id,
        connect_message_id=connect_msg.message_id
    )


class CustomSshClient(asyncssh.SSHClient):
    """SSH-клиент с поддержкой 2FA"""
    
    def __init__(self, bot_instance, chat_id, state: FSMContext, password: str):
        self._bot = bot_instance
        self._chat_id = chat_id
        self._state = state
        self._password = password
        super().__init__()

    def password_auth_requested(self):
        return self._password

    def kbdint_auth_requested(self):
        return ''

    async def kbdint_challenge_received(self, name, instructions, lang, prompts):
        if not prompts:
            return []

        responses = []
        for prompt_text, _ in prompts:
            future = asyncio.get_event_loop().create_future()
            
            msg = await self._bot.send_message(
                self._chat_id,
                f"*🔐 2FA-запрос:*\n\n"
                f"`{prompt_text}`\n\n"
                f"*Введите код:*",
                reply_markup=get_cancel_keyboard(),
                parse_mode=ParseMode.MARKDOWN
            )
            
            await self._state.update_data(two_fa_future=future, prompt_msg_id=msg.message_id)
            await self._state.set_state(CryptoSteps.ssh_wait_for_2fa)
            
            try:
                response = await asyncio.wait_for(future, timeout=120.0)
                responses.append(response)
            except asyncio.TimeoutError:
                await self._bot.send_message(
                    self._chat_id,
                    "*⏰* Время 2FA истекло!",
                    reply_markup=get_main_menu_keyboard(),
                    parse_mode=ParseMode.MARKDOWN
                )
                raise asyncssh.DisconnectError("2FA timeout", asyncssh.DISCONNECT_AUTH_CANCELLED)

        return responses


@dp.message(StateFilter(CryptoSteps.ssh_wait_for_2fa))
async def ssh_process_2fa_code(message: Message, state: FSMContext):
    """Обработка 2FA для SSH"""
    user_data = await state.get_data()
    future = user_data.get("two_fa_future")
    
    if future and not future.done():
        future.set_result(message.text.strip())
    
    try:
        await message.delete()
        prompt_msg_id = user_data.get('prompt_msg_id')
        if prompt_msg_id:
            await bot.delete_message(message.chat.id, prompt_msg_id)
    except Exception:
        pass
    
    await state.set_state(CryptoSteps.ssh_wait_for_password)


@dp.message(StateFilter(CryptoSteps.ssh_wait_for_password))
async def ssh_handle_connection(message: Message, state: FSMContext):
    """SSH-подключение и экспорт"""
    password = message.text.strip()
    chat_id = message.chat.id
    user_data = await state.get_data()
    
    try:
        await message.delete()
        prompt_id = user_data.get('password_prompt_message_id')
        if prompt_id:
            await bot.delete_message(chat_id, prompt_id)
        connect_id = user_data.get('connect_message_id')
        if connect_id:
            await bot.delete_message(chat_id, connect_id)
    except Exception:
        pass

    if password.lower() in ["отмена", "cancel"]:
        await bot.send_message(chat_id, "*❌* Экспорт отменён!", reply_markup=get_main_menu_keyboard(), parse_mode=ParseMode.MARKDOWN)
        await state.clear()
        return

    server_info = user_data.get('server_info')
    if not server_info:
        await bot.send_message(chat_id, "*❌* Данные сервера не найдены!", reply_markup=get_main_menu_keyboard(), parse_mode=ParseMode.MARKDOWN)
        await state.clear()
        return

    username, host = server_info.split('@', 1)
    public_key = user_data.get('public_key')
    key_type = user_data.get('key_type', 'неизвестный')

    if not public_key:
        await bot.send_message(chat_id, "*❌* Публичный ключ не найден!", reply_markup=get_main_menu_keyboard(), parse_mode=ParseMode.MARKDOWN)
        await state.clear()
        return

    auth_msg = await bot.send_message(chat_id, f"*🔐* Аутентификация для `{server_info}`...")

    try:
        client_factory = lambda: CustomSshClient(bot, chat_id, state, password)
        
        async with asyncssh.connect(host=host, username=username, client_factory=client_factory, connect_timeout=15) as conn:
            await auth_msg.edit_text("*✅* Подключение успешно! Добавляю ключ...")

            safe_public_key = shlex.quote(public_key.strip())
            command = (
                f'mkdir -p ~/.ssh && chmod 700 ~/.ssh && '
                f'if ! grep -qF "{safe_public_key}" ~/.ssh/authorized_keys 2>/dev/null; then '
                f'echo "{safe_public_key}" >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && '
                f'echo "Key added"; else echo "Key exists"; fi'
            )
            
            result = await conn.run(command, check=False)
            
            if result.exit_status == 0:
                output = result.stdout.decode('utf-8').strip()
                if "exists" in output.lower():
                    await auth_msg.edit_text(
                        f"*ℹ️* Ключ *{key_type}* уже есть на `{server_info}`!\n\n"
                        f"*✅* Теперь: `ssh {server_info}` без пароля!",
                        parse_mode=ParseMode.MARKDOWN
                    )
                else:
                    await auth_msg.edit_text(
                        f"*✅* Ключ *{key_type}* добавлен на `{server_info}`!\n\n"
                        f"*🎉* Теперь: `ssh {server_info}` без пароля!",
                        parse_mode=ParseMode.MARKDOWN
                    )
            else:
                await auth_msg.edit_text(
                    f"*⚠️* Ошибка добавления:\n\n"
                    f"`{result.stderr.decode('utf-8').strip()[:200]}`\n\n"
                    f"*🔧* Проверьте права `~/.ssh` на сервере.",
                    parse_mode=ParseMode.MARKDOWN
                )

    except asyncssh.PermissionDenied:
        await auth_msg.edit_text(
            "*❌* Ошибка аутентификации\n\n"
            f"*🔑* Неверный пароль для `{username}@{host}`\n"
            "*🔐* Или настройте 2FA\n\n"
            "*Попробуйте снова:*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_main_menu_keyboard()
        )
    except asyncssh.HostKeyNotVerifiable:
        await auth_msg.edit_text(
            "*❌* Проблема с хостом\n\n"
            "*🔒* Сервер не в known_hosts\n\n"
            "**Решение:**\n"
            "1. `ssh -v username@host` вручную\n"
            "2. Принять fingerprint\n"
            "3. Повторить экспорт",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_main_menu_keyboard()
        )
    except Exception as e:
        logger.error(f"SSH ошибка: {e}")
        await auth_msg.edit_text(
            f"*💥* Ошибка: `{str(e)[:100]}`\n\n"
            "*🔧* Проверьте подключение:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_main_menu_keyboard()
        )
    finally:
        await state.clear()
        await state.set_state(CryptoSteps.main_menu)


# === HASH SECTION ===
@dp.callback_query(StateFilter(CryptoSteps.hash_menu), lambda c: c.data == "hash_calculate")
async def hash_calculate_handler(query: types.CallbackQuery, state: FSMContext):
    """Выбор алгоритма хеширования"""
    await query.message.edit_text(
        "🔐 *Вычисление хеша*\n\n"
        "Выберите алгоритм хеширования:",
        reply_markup=get_hash_algorithm_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    await state.set_state(CryptoSteps.hash_choose_algorithm)


@dp.callback_query(StateFilter(CryptoSteps.hash_menu), lambda c: c.data == "hash_info")
async def hash_info_handler(query: types.CallbackQuery, state: FSMContext):
    """Справка по алгоритмам"""
    info_text = (
        "*📊 Справка по алгоритмам хеширования*\n\n"
        "**MD5:** 128 бит, устарел, только для проверки целостности\n"
        "**SHA-1:** 160 бит, устарел, не для криптографии\n"
        "**SHA-256:** 256 бит, стандарт для цифровых подписей\n"
        "**SHA-512:** 512 бит, высокая безопасность\n"
        "**BLAKE2b:** 512 бит, быстрый и безопасный\n\n"
        "*🔒 Рекомендуется: SHA-256 или BLAKE2b*"
    )
    
    await query.message.edit_text(
        info_text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="hash_menu")]
        ]),
        parse_mode=ParseMode.MARKDOWN
    )


@dp.callback_query(StateFilter(CryptoSteps.hash_choose_algorithm), lambda c: c.data.startswith("hash_"))
async def hash_request_input(query: types.CallbackQuery, state: FSMContext):
    """Запрос данных для хеширования"""
    algo_map = {
        "hash_md5": "MD5",
        "hash_sha1": "SHA-1", 
        "hash_sha256": "SHA-256",
        "hash_sha512": "SHA-512",
        "hash_blake2b": "BLAKE2b"
    }
    
    algorithm = algo_map.get(query.data, "SHA-256")
    await state.update_data(hash_algorithm=algorithm, chat_id=query.message.chat.id)
    
    input_text = (
        f"🔐 *Хеширование {algorithm}*\n\n"
        "Отправьте текст или файл для вычисления хеша:\n\n"
        "**Поддерживается:**\n"
        "• Текстовые сообщения (без лимита)\n"
        "• *Файлы до 20 МБ* (лимит Bot API)\n\n"
        "**⚠️ Важно:**\n"
        "• Файлы >20 МБ: сожмите (zip/7z)\n"
        "• Файлы старше 24ч: отправьте заново\n\n"
        "*Хеш будет в hex-формате (нижний регистр)*"
    )
    
    await query.message.edit_text(
        input_text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="ℹ️ Справка", callback_data="hash_info")],
            [InlineKeyboardButton(text="⬅️ Выбор алгоритма", callback_data="hash_calculate")]
        ]),
        parse_mode=ParseMode.MARKDOWN
    )
    await state.set_state(CryptoSteps.hash_get_input)


@dp.message(StateFilter(CryptoSteps.hash_get_input))
async def hash_process_input(message: Message, state: FSMContext):
    """Вычисление хеша из сообщения или файла"""
    user_data = await state.get_data()
    algorithm = user_data.get("hash_algorithm", "SHA-256")
    chat_id = user_data.get("chat_id")
    
    result_msg = await bot.send_message(chat_id, f"*🔄 Вычисляю {algorithm}-хеш...*",parse_mode=ParseMode.MARKDOWN)
    
    try:
        if message.document:
            file_size_limit = 20 * 1024 * 1024
            telegram_upload_limit = 50 * 1024 * 1024
            
            if message.document.file_size:
                file_size_bytes = message.document.file_size
                
                if file_size_bytes > file_size_limit:
                    file_size_mb = file_size_bytes / (1024 * 1024)
                    await result_msg.edit_text(
                        f"*❌ Файл слишком большой для бота!*\n\n"
                        f"📏 Размер: {file_size_mb:.1f} МБ\n"
                        f"🤖 *Лимит бота:* 20 МБ\n"
                        f"📱 *Лимит Telegram:* 50 МБ\n\n"
                        f"*💡 Решения:*\n"
                        f"• Сожмите файл до <20 МБ\n"
                        f"• Используйте онлайн-сервисы\n"
                        f"• Отправьте текст вместо файла\n\n"
                        f"*⚡ Для текста лимита нет!*",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return
                
                if file_size_bytes > telegram_upload_limit:
                    await result_msg.edit_text(
                        f"*❌ Файл превышает лимит Telegram!*\n\n"
                        f"📏 Размер: {file_size_mb:.1f} МБ\n"
                        f"📱 *Максимум:* 50 МБ\n\n"
                        f"*💡 Сожмите файл и отправьте заново*",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return
            
            filename = message.document.file_name or "file"
            file_id = message.document.file_id
            
            try:
                file_info = await bot.get_file(file_id)
                
                if not file_info.file_path:
                    raise Exception("File path not available")
                
                if file_info.file_size and file_info.file_size > file_size_limit:
                    file_size_mb = file_info.file_size / (1024 * 1024)
                    await result_msg.edit_text(
                        f"*❌ Файл слишком большой!*\n\n"
                        f"📏 Размер: {file_size_mb:.1f} МБ\n"
                        f"🤖 *Лимит бота:* 20 МБ\n\n"
                        f"*💡 Сожмите файл до <20 МБ*",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return
                
                logger.info(f"Скачиваю файл: {filename} ({file_info.file_size} байт)")
                file = await bot.download_file(file_info.file_path)
                file_data = file.read()
                
                if not file_data:
                    raise Exception("Файл пустой или не удалось прочитать")
                
                hash_value = calculate_file_hash(file_data, algorithm.lower())
                
                file_size_formatted = f"{len(file_data):,} байт"
                if len(file_data) > 1024 * 1024:
                    file_size_mb = len(file_data) / (1024 * 1024)
                    file_size_formatted = f"{file_size_mb:.1f} МБ"
                elif len(file_data) > 1024:
                    file_size_kb = len(file_data) / 1024
                    file_size_formatted = f"{file_size_kb:.1f} КБ"
                
                await result_msg.edit_text(
                    f"*📎 Хеш файла:* `{filename}`\n\n"
                    f"**{algorithm}:** `{hash_value}`\n\n"
                    f"*📏 Размер:* {file_size_formatted}\n"
                    f"*✅ Готово!*",
                    parse_mode=ParseMode.MARKDOWN
                )
                
            except Exception as file_error:
                logger.error(f"Ошибка работы с файлом {file_id}: {file_error}")
                error_msg = str(file_error).lower()
                
                if "too big" in error_msg or "file is too big" in error_msg:
                    await result_msg.edit_text(
                        f"*💥 Ошибка Telegram API:*\n\n"
                        f"**Файл слишком большой для бота**\n\n"
                        f"*🤖 Лимит Bot API:* 20 МБ\n"
                        f"*📱 Лимит клиента:* 50 МБ\n\n"
                        f"*🔧 Решение:*\n"
                        f"• Сожмите файл (zip, 7z)\n"
                        f"• Разделите на части <20 МБ\n"
                        f"• Используйте текст\n\n"
                        f"*⚡ Для файлов >20 МБ:* онлайн-сервисы",
                        parse_mode=ParseMode.MARKDOWN
                    )
                elif "file not found" in error_msg or "404" in error_msg:
                    await result_msg.edit_text(
                        f"*💥 Файл недоступен:*\n\n"
                        f"**Файл удалён с серверов Telegram**\n\n"
                        f"*⏰ Срок хранения:* 24 часа\n\n"
                        f"*📤 Решение:*\n"
                        f"• Отправьте файл заново\n"
                        f"• Используйте свежие файлы\n\n"
                        f"*⚠️ Файлы старше 24ч недоступны*",
                        parse_mode=ParseMode.MARKDOWN
                    )
                else:
                    await result_msg.edit_text(
                        f"*💥 Ошибка с файлом:*\n\n"
                        f"`{str(file_error)[:100]}`\n\n"
                        f"*🔧 Возможные причины:*\n"
                        f"• Проблемы с сетью\n"
                        f"• Файл повреждён\n"
                        f"• Временная ошибка API\n\n"
                        f"*📤 Попробуйте отправить заново*",
                        parse_mode=ParseMode.MARKDOWN
                    )
                return
                
        elif message.text:
            text_hash = calculate_text_hash(message.text, algorithm.lower())
            text_length = len(message.text)
            
            if text_length > 1000:
                text_length_formatted = f"{text_length:,} символов"
            else:
                text_length_formatted = f"{text_length} символов"
            
            await result_msg.edit_text(
                f"*📝 Хеш текста*\n\n"
                f"**{algorithm}:** `{text_hash}`\n\n"
                f"*📏 Длина:* {text_length_formatted}\n"
                f"*✅ Готово!*",
                parse_mode=ParseMode.MARKDOWN
            )
            
        else:
            await result_msg.edit_text(
                "*❌ Не удалось обработать данные!*\n\n"
                "*Поддерживается:*\n"
                "• Текстовые сообщения (без лимита)\n"
                "• Файлы до 20 МБ\n\n"
                "*💡 Для больших файлов:* \n"
                "• Сожмите до <20 МБ\n"
                "• Используйте онлайн-сервисы\n"
                "*📤 Отправьте текст или файл*",
                parse_mode=ParseMode.MARKDOWN
            )
            
    except Exception as e:
        logger.error(f"Общая хеш-ошибка: {e}")
        await result_msg.edit_text(
            f"*💥 Критическая ошибка:*\n\n"
            f"`{str(e)[:100]}`\n\n"
            f"*🔧 Обратитесь к разработчику*",
            parse_mode=ParseMode.MARKDOWN
        )


def calculate_text_hash(text: str, algorithm: str) -> str:
    """Хеш текста"""
    hash_functions = {
        'md5': hashlib.md5,
        'sha1': hashlib.sha1,
        'sha256': hashlib.sha256,
        'sha512': hashlib.sha512,
        'blake2b': lambda data: hashlib.blake2b(data, digest_size=64)
    }
    
    if algorithm not in hash_functions:
        algorithm = 'sha256'
    
    h = hash_functions[algorithm](text.encode('utf-8'))
    return h.hexdigest()


def calculate_file_hash(file_data: bytes, algorithm: str) -> str:
    """Хеш файла"""
    hash_functions = {
        'md5': hashlib.md5,
        'sha1': hashlib.sha1,
        'sha256': hashlib.sha256,
        'sha512': hashlib.sha512,
        'blake2b': lambda data: hashlib.blake2b(data, digest_size=64)
    }
    
    if algorithm not in hash_functions:
        algorithm = 'sha256'
    
    h = hash_functions[algorithm](file_data)
    return h.hexdigest()


@dp.callback_query(lambda c: c.data in ["cancel", "back_main", "main_menu", "ssh_menu", "hash_menu"])
async def handle_navigation(query: types.CallbackQuery, state: FSMContext):
    """Общая навигация"""
    await query.answer()
    
    if query.data == "cancel":
        await query.message.delete()
        await state.clear()
    
    data_map = {
        "back_main": "main_menu",
        "main_menu": get_main_menu_keyboard(),
        "ssh_menu": (get_ssh_menu_keyboard(), CryptoSteps.ssh_menu),
        "hash_menu": (get_hash_menu_keyboard(), CryptoSteps.hash_menu)
    }
    
    if query.data in data_map:
        if isinstance(data_map[query.data], tuple):
            keyboard, new_state = data_map[query.data]
            await query.message.edit_text(
                "🏠 *Главное меню*\n\nВыберите раздел:",
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN
            )
            await state.set_state(new_state)
        else:
            keyboard = data_map[query.data]
            await query.message.edit_text(
                "🏠 *Главное меню*\n\nВыберите раздел:",
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN
            )
            await state.set_state(CryptoSteps.main_menu)


async def main():
    """Запуск бота"""
    logger.info("🚀 Крипто-генератор запущен!")

    await set_bot_commands()
    
    try:
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logger.info("🛑 Остановка...")
    except Exception as e:
        logger.error(f"💥 Ошибка: {e}")
    finally:
        await bot.session.close()
        logger.info("👋 Бот остановлен")


if __name__ == "__main__":
    asyncio.run(main())