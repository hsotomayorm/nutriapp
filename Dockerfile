# syntax=docker/dockerfile:1

FROM python:3.11-slim

# Prevents Python from writing .pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1         PYTHONUNBUFFERED=1

# Create non-root user
RUN useradd -m -u 1001 appuser

# Set workdir
WORKDIR /app

# System deps (curl only for health/debug), and security updates
RUN apt-get update && apt-get install -y --no-install-recommends         build-essential         curl       && rm -rf /var/lib/apt/lists/*

# Copy dependency list and install
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the source code (expects an existing app.py in the build context)
COPY . /app

# Gunicorn config reads PORT from env (Code Engine sets it). Default 8080.
ENV PORT=8080

# Use a non-root user for security
USER appuser

# Expose the port for local runs (optional)
EXPOSE 8080

# Start the server. Gunicorn will import app from wsgi:app
CMD ["gunicorn", "wsgi:app", "-c", "gunicorn.conf.py"]
