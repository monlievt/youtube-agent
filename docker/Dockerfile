FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    default-mysql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user sesuai blueprint (RULE-005)
RUN groupadd -g 1000 hermes && \
    useradd -u 1000 -g hermes -m -s /bin/bash hermes

WORKDIR /app

# Install Python deps sebagai root dulu
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy kode
COPY --chown=hermes:hermes . .

# Switch ke non-root user
USER 1000:1000

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
