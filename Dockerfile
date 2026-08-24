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

# Expose poort
EXPOSE 8000

# Start de applicatie
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
