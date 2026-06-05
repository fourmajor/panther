FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
COPY prompts ./prompts
COPY schemas ./schemas
COPY fixtures ./fixtures

RUN pip install --no-cache-dir -e .

ENTRYPOINT ["panther"]
