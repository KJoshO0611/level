FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for Cairo and other components
RUN apt-get update && apt-get install -y \
    libcairo2-dev \
    libffi-dev \
    pkg-config \
    git \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Create required directories
RUN mkdir -p /external_volume /app/logs

# Install Python dependencies first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Set permissions
RUN chmod -R 755 /app
RUN chmod -R 777 /external_volume /app/logs

# Run the bot
CMD ["python", "main.py"]