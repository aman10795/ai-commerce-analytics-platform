FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV DBT_PROFILES_DIR=/app/.docker/dbt_profiles

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml README.md ./

RUN python -m pip install --upgrade pip \
    && pip install -r requirements.txt

COPY analytics ./analytics
COPY mcp_server ./mcp_server
COPY scripts ./scripts
COPY commerce_analytics_dbt ./commerce_analytics_dbt
COPY data/demo ./data/demo
COPY .docker ./.docker

RUN pip install -e .

RUN mkdir -p /app/data/warehouse

RUN python scripts/demo/create_demo_warehouse.py --reset

RUN cd commerce_analytics_dbt \
    && dbt deps \
    && dbt build --target demo

EXPOSE 8501

CMD ["streamlit", "run", "scripts/agent/streamlit_app.py", "--server.address=0.0.0.0", "--server.port=8501"]