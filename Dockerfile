FROM python:3.13-slim

WORKDIR /app

COPY requirements.runtime.txt ./
RUN pip install --no-cache-dir --index-url https://pypi.org/simple --retries 10 --timeout 120 \
    -r requirements.runtime.txt

COPY app app/
COPY run.py ./

RUN mkdir -p /app/data

ENV PYTHONUNBUFFERED=1
EXPOSE 8001

CMD ["python", "run.py"]
