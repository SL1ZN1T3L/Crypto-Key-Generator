# 🔐 Crypto Key Generator Bot

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Telegram](https://img.shields.io/badge/Telegram-Bot-purple.svg)](https://core.telegram.org/bots)
[![Async](https://img.shields.io/badge/Async-AIogram-orange.svg)](https://aiogram.dev/)
[![Security](https://img.shields.io/badge/Security-Cryptography-green.svg)](https://cryptography.io/)

---

## 📖 Описание

**Crypto Key Generator Bot** — это Telegram-бот для криптографических операций, разработанный для автоматизации задач безопасности и управления ключами. Бот предоставляет полный набор инструментов для работы с SSH-доступом и криптографическими хешами, обеспечивая удобство использования и высокий уровень безопасности.

### Основные возможности

#### 🔑 SSH-менеджмент
- **Генерация ключей**: RSA (4096 бит), Ed25519 с поддержкой passphrase
- **Автоматический экспорт**: SSH-подключение с 2FA, добавление в `authorized_keys`
- **Безопасность**: Автоматическое удаление паролей, проверка дубликатов

#### 🔐 Хеширование
- **Алгоритмы**: MD5, SHA-1, SHA-256, SHA-512, BLAKE2b
- **Входные данные**: Текст, файлы до 50 МБ
- **Вывод**: Hex-строки с метаданными (размер, время)

#### 🛡️ Безопасность
- **FSM-состояния**: Изоляция пользовательских сессий
- **Временное хранение**: MemoryStorage с автоматической очисткой
- **Удаление sensitive данных**: Пароли и ключи удаляются из чата
- **Валидация**: Проверка форматов ключей и серверов

---

## 🎯 Назначение

Бот предназначен для:

- **DevOps-инженеров**: Быстрая настройка SSH-доступа к серверам
- **Системных администраторов**: Массовое развертывание ключей
- **Разработчиков**: Генерация ключей для CI/CD пайплайнов
- **Безопасности**: Проверка целостности файлов и ПО
- **Образования**: Изучение криптографии через практику

---

## 🏗️ Архитектура

### Компоненты

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Telegram API  │◄──►│   Aiogram 3.x    │◄──►│   FSM Storage   │
│   (Webhooks)    │    │  (Async Router)  │    │  (Memory/Redis) │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                │
                                ▼
                       ┌─────────────────┐
                       │   Crypto Core   │
                       │  (SSH/Hashes)   │
                       └─────────────────┘
                                │
                        ┌──────────────┐
                        │  Security    │
                        │  Middleware  │
                        └──────────────┘
```

### Поток данных

#### SSH-генерация
```
User Request → FSM State → Key Generation → File Export → FSM Storage
    ↓              ↓            ↓              ↓             ↓
Start     → choose_key_type → cryptography → BufferedInputFile → state.update_data()
```

#### Хеширование
```
User Input → Algorithm Selection → Hash Calculation → Result Display
    ↓              ↓                   ↓                ↓
Message/Document → hash_choose_algorithm → hashlib → Markdown Response
```

### Состояния FSM

| Состояние | Описание | Переходы |
|-----------|----------|----------|
| `main_menu` | Главное меню | ssh_menu, hash_menu |
| `ssh_menu` | SSH-меню | choose_ssh_key_type, ssh_get_existing_public_key |
| `choose_ssh_key_type` | Выбор типа SSH-ключа | ssh_get_passphrase |
| `ssh_get_passphrase` | Ввод passphrase | ssh_generate_key |
| `ssh_get_existing_public_key` | Загрузка публичного ключа | ssh_get_server_info_for_existing |
| `ssh_get_server_info` | Ввод данных сервера | ssh_wait_for_password |
| `ssh_wait_for_password` | Ожидание пароля | ssh_handle_connection |
| `ssh_wait_for_2fa` | Ожидание 2FA-кода | ssh_handle_connection |
| `hash_menu` | Хеш-меню | hash_choose_algorithm |
| `hash_choose_algorithm` | Выбор алгоритма | hash_get_input |
| `hash_get_input` | Ожидание данных | hash_process_input |

---

## 📦 Установка

### Требования

| Компонент | Версия | Описание |
|-----------|--------|----------|
| **Python** | 3.11+ | Основной язык |
| **Aiogram** | 3.22.0 | Telegram Bot Framework |
| **AsyncSSH** | 2.21.0 | SSH-клиент |
| **Cryptography** | 46.0.1 | Криптография |
| **Bcrypt** | 4.3.0 | Шифрование passphrase |
| **Python-dotenv** | 1.1.1 | Загрузка .env |


### Установка через Docker(Рекомендуется)
```bash
В разработке
```

### Установка через GitHub

```bash
git clone https://github.com/SL1ZN1T3L/Crypto-Key-Generator.git
python -m venv venv
source .venv/bin/activate
pip install -r requirements.txt
mv .env.example .env
```