# Dockerfile

# Use the full official Python runtime as a parent image
FROM python:3.11

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set work directory
WORKDIR /app

# Install system dependencies if needed (e.g., for libraries that compile C extensions)
# RUN apt-get update && apt-get install -y --no-install-recommends some-package && rm -rf /var/lib/apt/lists/*

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
# Copy only requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Optional: If you want to reduce final image size, you could remove
# build dependencies in a later stage of a multi-stage build,
# or uninstall them here if not needed at runtime.
# RUN apt-get purge -y --auto-remove build-essential python3-dev

# Copy project code into the container
COPY ./app /app/app

# Expose port 8000 (the default for uvicorn)
EXPOSE 8000

# Command to run the application using uvicorn
# Use 0.0.0.0 to make it accessible from outside the container
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# For production, consider removing --reload and potentially using gunicorn with uvicorn workers:
# CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "-c", "/path/to/gunicorn_conf.py", "app.main:app"]
