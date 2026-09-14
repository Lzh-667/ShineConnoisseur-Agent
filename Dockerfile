FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app app/
COPY run.py ./

RUN mkdir -p /app/data

ENV PYTHONUNBUFFERED=1
EXPOSE 8001

CMD ["python", "run.py"]
