FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY samu_sim ./samu_sim
COPY dados ./dados
COPY docs/experimentos ./docs/experimentos
RUN pip install --no-cache-dir .
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "samu_sim.api"]
