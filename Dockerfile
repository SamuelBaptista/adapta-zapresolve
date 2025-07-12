FROM python:3.12-slim

COPY . .

RUN pip install --upgrade pip && \
    pip install uv && \
    uv sync --frozen --no-install-project --no-dev

EXPOSE 8000

CMD ["uv", "run", "app.py"]