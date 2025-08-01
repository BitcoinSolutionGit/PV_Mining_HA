FROM python:3.11-alpine
WORKDIR /app
COPY your_code /app
COPY run.sh /app/run.sh
RUN pip install --no-cache-dir -r /app/requirements.txt
CMD ["/bin/sh", "/app/run.sh"]
