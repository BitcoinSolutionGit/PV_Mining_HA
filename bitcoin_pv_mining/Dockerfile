FROM python:3.11-slim

WORKDIR /app
COPY . .

RUN pip install dash plotly requests

#CMD ["python3", "ui/dashboard.py"]

CMD ["bash", "run.sh"]