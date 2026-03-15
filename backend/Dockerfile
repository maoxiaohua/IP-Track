FROM python:3.11-slim

WORKDIR /app

# Install system dependencies including network tools
RUN apt-get update && apt-get install -y \
    iputils-ping \
    arp-scan \
    net-tools \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies with optional proxy support
ARG PIP_PROXY
RUN if [ -n "$PIP_PROXY" ]; then \
      pip install --proxy "$PIP_PROXY" --no-cache-dir -r requirements.txt; \
    else \
      pip install --no-cache-dir -r requirements.txt; \
    fi

# Copy application code
COPY src/ ./src/

# Create logs directory
RUN mkdir -p logs

# Set Python path
ENV PYTHONPATH=/app/src

# Expose port
EXPOSE 8100

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8100", "--reload"]
