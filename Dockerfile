# Dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install OS deps first (and git only if you really need it)
RUN apt-get update && apt-get install -y build-essential curl && rm -rf /var/lib/apt/lists/*

# 1) copy requirements and install them
#    Make sure the file is named exactly: requirements.txt
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2) copy the app code
COPY . .

# Streamlit in container
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0
ENV STREAMLIT_SERVER_PORT=8501
EXPOSE 8501
CMD ["streamlit","run","app.py","--server.address=0.0.0.0","--server.port=8501"]
