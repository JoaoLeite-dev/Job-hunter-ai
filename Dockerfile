FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY alembic.ini ./
COPY migrations ./migrations
RUN useradd --create-home jobhunter
USER jobhunter
EXPOSE 5000
CMD ["flask", "--app", "job_hunter:create_app", "run", "--host=0.0.0.0"]
