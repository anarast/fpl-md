FROM python:3.8

ENV PIP_DEFAULT_TIMEOUT=100 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VERSION=1

RUN pip install "poetry==$POETRY_VERSION"

WORKDIR /app

COPY poetry.lock /app/
COPY pyproject.toml /app/

RUN poetry config virtualenvs.create false
RUN poetry install --no-dev

COPY . /app

CMD ["./docker-entrypoint.sh"]