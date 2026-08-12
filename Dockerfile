FROM python:3.12.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN addgroup --system paply && adduser --system --ingroup paply paply

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --upgrade pip && python -m pip install .

COPY config ./config

USER paply
EXPOSE 4387

CMD ["uvicorn", "paply_gateway.main:app", "--host", "0.0.0.0", "--port", "4387", "--proxy-headers", "--forwarded-allow-ips=*"]

