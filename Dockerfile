# Step 1: Build the React frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Step 2: Set up the Python environment
FROM python:3.11-slim
WORKDIR /app

# Install git and other system dependencies if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install python dependencies
COPY backend/requirements.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy the rest of the application
COPY backend/ ./backend/
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Create a non-root user (Hugging Face Spaces runs as user 1000)
RUN useradd -m -u 1000 user && \
    chown -R user:user /app

USER user
ENV HOME=/home/user
ENV PATH=/home/user/.local/bin:$PATH

WORKDIR /app/backend

# Set up environment variables
ENV DELPHI_OFFLINE=0
ENV PORT=7860
ENV HOST=0.0.0.0

# Command to run FastAPI server
CMD ["python", "-m", "uvicorn", "delphi.api.main:app", "--host", "0.0.0.0", "--port", "7860"]
