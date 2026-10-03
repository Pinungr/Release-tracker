# Build and run without Docker Compose

Run from the repository root in PowerShell with Docker's Linux container engine running:

```powershell
.\scripts\build-app-image.ps1 -Image pds-scheduler:2026.10
```

To also save a portable image archive:

```powershell
.\scripts\build-app-image.ps1 -Image pds-scheduler:2026.10 -ExportPath .\artifacts\pds-scheduler-2026.10.tar
```

The script works from any directory; relative export paths refer to your current directory. Add `-NoCache` for a clean rebuild. Existing archives are never overwritten. Building requires access to the base-image registries and dependency repositories. Image archives contain the application and its dependencies, not database records or uploaded documents. Use a target server with the same CPU architecture as the build engine.

## Import on another server

Copy the archive to the server, then run:

```powershell
docker image load --input .\artifacts\pds-scheduler-2026.10.tar
```

## Run against an existing PostgreSQL database

Create a private `pds-runtime.env` file outside the repository with actual values:

```dotenv
ENVIRONMENT=production
DATABASE_URL=postgresql+psycopg://scheduler:URL_ENCODED_PASSWORD@DATABASE_HOST:5432/scheduler
JWT_SECRET=REPLACE_WITH_A_UNIQUE_RANDOM_SECRET_AT_LEAST_32_CHARACTERS
BOOTSTRAP_ADMIN_USERNAME=admin
BOOTSTRAP_ADMIN_PASSWORD=REPLACE_WITH_A_UNIQUE_PASSWORD
TIMEZONE=Asia/Kolkata
AI_PROVIDER=builtin
STORAGE_DIR=/var/lib/pds/storage
FRONTEND_DIST=/app/frontend/dist
```

`DATABASE_HOST` must be reachable from inside the container. On Docker Desktop, `host.docker.internal` addresses the host; `localhost` addresses the application container itself. The Compose hostname `postgres` works only when a database container shares a Docker network with that name or alias. URL-encode special characters in the database password.

```powershell
docker volume create pds-app-storage
docker run --detach --name pds-app-standalone --restart unless-stopped --env-file C:\private\pds-runtime.env --publish 8000:8000 --mount type=volume,source=pds-app-storage,target=/var/lib/pds/storage pds-scheduler:2026.10
```

Open `http://localhost:8000`. Verify startup with:

```powershell
docker logs pds-app-standalone
docker exec pds-app-standalone curl --fail http://localhost:8000/health/ready
```

For Linux, use the server's environment-file path instead of the Windows example. The published port must be free; use `--publish 9000:8000` if needed. The database must already be running. Application startup runs migrations; back up an existing database before upgrading the application.

The named volume persists uploaded files when the container is removed. When moving an existing Compose installation, use its actual application-storage volume name from `docker volume ls` instead of creating an empty volume, and point to the existing database. Copy or back up both PostgreSQL data and document storage separately when moving servers. Secrets belong in the runtime environment file and are not included in the image.
