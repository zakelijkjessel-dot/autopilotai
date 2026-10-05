FROM python:3.12-slim

# Zet werkdirectory
WORKDIR /app

# Installeer dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopieer broncode
COPY . .

# Maak uploads-map aan
RUN mkdir -p uploads

# Expose poort (lokaal; Railway routeert via $PORT)
EXPOSE 8000

# Start de applicatie — luister op $PORT (Railway) of 8000 (lokaal)
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
