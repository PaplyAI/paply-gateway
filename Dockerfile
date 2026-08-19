FROM python:3.12.11-slim AS runtime

ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_DEFAULT_TIMEOUT=100

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=${PIP_DEFAULT_TIMEOUT}

RUN addgroup --system paply && adduser --system --ingroup paply paply

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --index-url "${PIP_INDEX_URL}" --upgrade pip \
    && python -m pip install --index-url "${PIP_INDEX_URL}" .

COPY config ./config
COPY scripts/create_access_token.py ./scripts/create_access_token.py
COPY web ./web

USER paply
EXPOSE 4387

CMD ["uvicorn", "paply_gateway.main:app", "--host", "0.0.0.0", "--port", "4387", "--proxy-headers", "--forwarded-allow-ips=*"]
