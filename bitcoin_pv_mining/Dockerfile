FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x /app/run.sh
EXPOSE 8080

CMD ["/bin/sh", "/app/run.sh"]

