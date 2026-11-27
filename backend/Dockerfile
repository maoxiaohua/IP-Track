FROM python:3.11-slim

WORKDIR /app

# Install system dependencies including network tools
RUN apt-get update && apt-get install -y \
    iputils-ping \
    arp-scan \
    net-tools \
    ipmitool \
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
# 用 python -m 启动：uvicorn console script 启动时 sys.path[0]=/usr/local/bin，
# 若依赖把同名模块（如 impacket 的 services.py）装到该目录会遮蔽 /app/src/services
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8100"]
