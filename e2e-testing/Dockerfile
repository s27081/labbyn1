# Use a lightweight Python 3.12 image
FROM python:3.12-slim

# Install Chromium and the Chromium driver
# Using apt-get is the easiest way to ensure browser/driver versions match
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory inside the container
WORKDIR /code

# Copy your requirements file and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy your test code and conftest.py into the container
COPY . .

# Set the default command to run your tests
CMD ["pytest", "--html=report.html", "--self-contained-html"]