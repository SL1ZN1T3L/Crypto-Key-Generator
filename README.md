# 🔐 Crypto Key Generator Bot

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Telegram](https://img.shields.io/badge/Telegram-Bot-purple.svg)](https://core.telegram.org/bots)
[![Async](https://img.shields.io/badge/Async-AIogram-orange.svg)](https://aiogram.dev/)
[![Security](https://img.shields.io/badge/Security-Cryptography-green.svg)](https://cryptography.io/)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://hub.docker.com/r/sl1zn1t3ldev/crypto-bot)

---

## 📖 Описание

**Crypto Key Generator Bot** — Telegram-бот для криптографических операций: генерация SSH-ключей, экспорт их на серверы, вычисление хешей и работа с X.509-сертификатами.

### Основные возможности

#### 🔑 SSH-менеджмент
- **Генерация ключей**: RSA 4096, Ed25519, с поддержкой passphrase
- **Форматы**: OpenSSH и PKCS#8
- **Проверка ключей**: тип, размер, комментарий, отпечатки SHA256 и MD5
- **Экспорт на сервер**: 2FA, подтверждение отпечатка хоста, запись в `authorized_keys` с правами 700/600

#### #️⃣ Хеширование
- **Алгоритмы**: MD5, SHA-1, SHA-256, SHA-512, BLAKE2b
- **Входные данные**: текст, файлы до 20 МБ
- **Вывод**: hex в нижнем регистре

#### 🪪 X.509
- **Документы**: самоподписанные сертификаты и запросы CSR
- **Ключ**: RSA 3072, подпись SHA-256, шифрование passphrase
- **Расширения**: SAN, Key Usage, Extended Key Usage

#### 🛡️ Безопасность
- Приватные ключи и пароли не сохраняются на сервере
- Сообщения с паролями и passphrase удаляются из чата
- Работа только в личных сообщениях
- Подключения разрешены только на публичные IP
- Квоты на подключения: на пользователя и суммарно по боту
- Контейнер от непривилегированного пользователя, `read_only`, `cap_drop: ALL`

---

## 📦 Требования

| Компонент | Версия | Описание |
|-----------|--------|----------|
| **Python** | 3.11+ | Основной язык |
| **Aiogram** | 3.22.0 | Telegram Bot Framework |
| **AsyncSSH** | 2.21.1 | SSH-клиент |
| **Cryptography** | 46.0.2 | Криптография |
| **Bcrypt** | 5.0.0 | Шифрование passphrase |
| **Redis** | 6.4.0 | Хранение квот и состояний |
| **Python-dotenv** | 1.1.1 | Загрузка .env |

---

## 🐳 Установка через Docker (рекомендуется)

#### Установить Docker
```bash
sudo curl -fsSL https://get.docker.com | sh
```

#### Шаг 1. Загрузите необходимые файлы
```bash
mkdir /opt/crypto-bot && cd /opt/crypto-bot
```
```bash
curl -o docker-compose.yml https://raw.githubusercontent.com/SL1ZN1T3L/Crypto-Key-Generator/refs/heads/main/docker-compose.yml
```
```bash
curl -o .env https://raw.githubusercontent.com/SL1ZN1T3L/Crypto-Key-Generator/refs/heads/main/.env.example
```

#### Шаг 2. Настройте файл .env
Укажите токен вашего бота от [@BotFather](https://t.me/BotFather).

#### Шаг 3. Запустите контейнеры
```bash
docker compose up -d && docker compose logs -f -t
```

---

## 💻 Установка через GitHub

```bash
git clone https://github.com/SL1ZN1T3L/Crypto-Key-Generator.git
cd Crypto-Key-Generator
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
mv .env.example .env
python -m app
```

---

## ⚙️ Конфигурация

### Основное

| Переменная | По умолчанию | Описание |
|-----------|--------------|----------|
| `BOT_TOKEN` | — | Токен бота, обязательно |
| `ALLOWED_USER_IDS` | — | Telegram ID через запятую, пусто — доступ открыт |
| `SSH_EXPORT_ENABLED` | `1` | Экспорт ключей на серверы |
| `REDIS_URL` | — | `redis://redis:6379/0` |
| `LOG_LEVEL` | `INFO` | Уровень логирования |
| `LOG_TO_FILE` | `0` | Дублировать логи в файл |

### Криптография

| Переменная | По умолчанию | Описание |
|-----------|--------------|----------|
| `RSA_SSH_KEY_SIZE` | `4096` | Размер RSA для SSH |
| `RSA_X509_KEY_SIZE` | `3072` | Размер RSA для сертификатов |
| `MAX_FILE_SIZE_MB` | `20` | Лимит файла для хеширования |

### Сеть и лимиты

| Переменная | По умолчанию | Описание |
|-----------|--------------|----------|
| `ALLOW_PRIVATE_TARGETS` | `0` | Подключения в приватные сети |
| `SSH_CONNECT_TIMEOUT` | `15` | Таймаут подключения, с |
| `TWOFA_TIMEOUT` | `120` | Время на ввод 2FA, с |
| `RATE_LIMIT_SECONDS` | `0.7` | Интервал между запросами |
| `QUOTA_PROBE_USER_HOUR` | `15` | Обращений к серверам в час |
| `QUOTA_PROBE_USER_DAY` | `40` | Обращений к серверам в сутки |
| `QUOTA_PROBE_GLOBAL_HOUR` | `200` | То же, суммарно по боту |
| `QUOTA_AUTH_USER_HOUR` | `10` | Подключений с паролем в час |
| `QUOTA_AUTH_USER_DAY` | `25` | Подключений с паролем в сутки |
| `QUOTA_AUTH_GLOBAL_HOUR` | `120` | То же, суммарно по боту |
| `QUOTA_FAIL_USER_HOST` | `3` | Неудачных входов на один сервер |
| `QUOTA_FAIL_USER_TOTAL` | `8` | Неудачных входов всего |
| `QUOTA_DISTINCT_HOSTS_DAY` | `8` | Разных серверов в сутки |
| `QUOTA_MAX_CONCURRENT_SSH` | `5` | Одновременных SSH-сессий |

Полный список — в [`.env.example`](.env.example).

---

## 🎮 Команды

| Команда | Описание |
|---------|----------|
| `/start` | Главное меню |
| `/help` | Справка |
| `/cancel` | Отменить операцию |

---

## 📚 Документация

- [DEPLOY.md](DEPLOY.md) — сборка образа, публикация, CI
- [SECURITY.md](SECURITY.md) — политика безопасности

---

## 📄 Лицензия

MIT — см. [LICENSE](LICENSE).