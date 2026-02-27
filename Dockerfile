# Dockerfile для VPN-бота
FROM python:3.10-slim

# Рабочая директория
WORKDIR /opt/vpn_bot

# Установка зависимостей
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Копирование requirements.txt
COPY requirements.txt .

# Установка Python зависимостей
RUN pip install --no-cache-dir -r requirements.txt

# Копирование файлов проекта
COPY . .

# Создание директорий
RUN mkdir -p logs payments

# Установка прав
RUN chmod +x bot.py

# Порт webhook
EXPOSE 8080

# Команда запуска
CMD ["python", "bot.py"]

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8080/health')" || exit 1
