# Use the official Python image
FROM python:3.11-slim

# Set the working directory
WORKDIR /app

# Copy the bot script and requirements
COPY req.txt req.txt

# Install dependencies
RUN pip install -r req.txt

COPY . .

# Run the bot
CMD ["python", "main.py"]