FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend

# package-lock.json is committed, so the image build is reproducible.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r ./backend/requirements.txt

COPY backend ./backend
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

WORKDIR /app/backend
EXPOSE 8000

# One worker on purpose: the login rate limiter and the logout revocation
# list are process-local, so extra workers would weaken both. Scale out by
# moving those to Redis first.
CMD ["python", "-m", "app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
