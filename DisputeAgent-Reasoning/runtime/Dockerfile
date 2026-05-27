# Amazon Bedrock AgentCore Runtime: ARM64, port 8080, /invocations + /ping.
# Build: docker build --platform linux/arm64 -f runtime/Dockerfile -t dispute-analysis-agentcore .
FROM public.ecr.aws/docker/library/python:3.11-slim-bookworm

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

COPY requirements.txt ./requirements.txt
COPY runtime/requirements.txt ./runtime/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r runtime/requirements.txt

COPY src ./src
COPY runtime ./runtime

EXPOSE 8080

CMD ["python", "runtime/main.py"]
