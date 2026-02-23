# Use a lightweight Python base image
FROM python:3.11-slim

# Set the working directory inside the container
WORKDIR /app

# Install the required Python libraries
RUN pip install --no-cache-dir flask requests

# Copy the proxy script into the container
COPY onvif_proxy.py .

# Expose the port the proxy listens on
EXPOSE 8080

# Command to run the script
CMD ["python", "-u", "onvif_proxy.py"]
