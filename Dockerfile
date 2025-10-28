FROM python:3.11-slim

LABEL maintainer="Vantage6 Node Manager"
LABEL description="Docker-based web application for managing Vantage6 nodes"

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install --no-install-recommends -y \
    curl=8.14.1-2 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app.py .
COPY templates/ templates/
COPY static/ static/

# Create directory for vantage6 configs (will be mounted)
RUN mkdir -p /root/.config/vantage6/node && \
    mkdir -p /etc/vantage6/node && \
    mkdir -p /data

# Expose port
EXPOSE 5000

# Set environment variables
ENV FLASK_APP=app.py
ENV PYTHONUNBUFFERED=1
ENV VANTAGE6_CONFIG_DIR=/root/.config/vantage6/node
ENV VANTAGE6_SYSTEM_CONFIG_DIR=/etc/vantage6/node
ENV VANTAGE6_DATA_DIR=/data

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5000/ || exit 1

# Run the application
CMD ["python", "app.py"]
