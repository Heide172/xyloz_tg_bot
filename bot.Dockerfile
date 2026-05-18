# bot.Dockerfile
FROM python:3.11

# рабочая директория = корень проекта
WORKDIR /app

# копируем весь проект
COPY . .
RUN chmod +x scripts/wait-for-postgres.sh
RUN apt-get update && \
    apt-get install -y netcat-openbsd && \
    rm -rf /var/lib/apt/lists/*
# устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# чтобы Python видел bot, common и др.
ENV PYTHONPATH=/app

# команда запуска бота
CMD ["python", "bot/main.py"]
