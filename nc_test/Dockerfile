FROM python:3.11-slim
WORKDIR /app
COPY talkbot.py .
ENV BOT_PORT=9000
EXPOSE 9000
CMD ["python", "-u", "talkbot.py"]
