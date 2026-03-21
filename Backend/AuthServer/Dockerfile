FROM python:3.13-slim

WORKDIR /app

# Установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование кода
COPY /app .

# Создание пользователя (безопасность)
RUN adduser --disabled-password --gecos '' appuser && \
    chown -R appuser:appuser /app
USER appuser

# Порт приложения
EXPOSE 8000

# Запуск сервера
CMD ["python", "main.py"]