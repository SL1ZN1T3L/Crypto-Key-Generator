FROM python:3.12-slim

# Устанавливаем Node.js и PM2
RUN apt-get update && apt-get install -y curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    npm install -g pm2 && \
    apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Рабочая директория
WORKDIR /app

# Устанавливаем Python-зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем файлы проекта
COPY . .

# Создаём папку для логов
RUN mkdir -p logs

# Копируем PM2 конфигурацию
COPY ecosystem.config.js .

# Запуск через PM2
CMD ["pm2-runtime", "start", "ecosystem.config.js"]