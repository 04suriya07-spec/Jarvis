FROM python:3.11-slim

# Install system dependencies for audio (sounddevice), video (opencv), and compilation
RUN apt-get update && apt-get install -y \
    libportaudio2 \
    libasound2-dev \
    libgl1-mesa-glx \
    libglib2.0-0 \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Ensure environment is configured for logging and network
ENV PYTHONUNBUFFERED=1

# Expose the web server port
EXPOSE 8000

# Default command starts the background daemon and web dashboard
CMD ["python", "main.py", "serve", "--host", "0.0.0.0", "--port", "8000"]
