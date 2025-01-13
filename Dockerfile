FROM python:3.12-slim-bullseye

# Install SQLite and any other OS-level dependencies
RUN apt-get update && \
    apt-get install -y sqlite3 && \
    rm -rf /var/lib/apt/lists/*

# Set working directory inside the container
WORKDIR /infogen

# Copy your dependency file and install dependencies
COPY requirements.txt /infogen/
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your app code
COPY . /infogen

# Run the FastAPI app using Uvicorn
CMD ["uvicorn", "infogen.main:infogen", "--host", "0.0.0.0", "--port", "80", "--reload"]

