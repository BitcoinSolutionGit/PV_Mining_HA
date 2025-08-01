FROM python:3.11-slim

WORKDIR /app
COPY . .

RUN chmod +x run.sh
RUN pip install dash plotly requests

CMD ["bash", "run.sh"]
