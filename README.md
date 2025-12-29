# Code Force DEMO

**Code Force DEMO** is a hands-on demonstration of an AI-agent workflow for software delivery with **GPT-class models**.  
Given a natural-language task, the system:

1. **Clones** a Git repository that you previously prepared (seeded with the demo backend code).
2. Uses a **GPT Agent** to propose a **branch name** and create the **feature branch**.
3. Routes the task to a small “delivery team” of agents:
   - **Coordinator** (drives the plan and assigns work)
   - **Developer** (implements the feature and tests)
   - **Sonar Analyst** (runs SonarQube analysis and iterates until the project passes the Quality Gate)
4. Ensures the change meets the **SonarQube Quality Gate**, reducing risk of introducing:
   - code smells / maintainability issues
   - bugs
   - vulnerabilities
   - low-quality patterns

This repository contains the orchestrator script and configuration needed to reproduce the demo locally.

---

## What you will run

- A local **SonarQube Community** instance backed by **PostgreSQL**
- A local **MySQL** instance used by the demo application
- A Python-based orchestration script that coordinates the agents:
  - `code_force_demo.py`

---

## Prerequisites

### System requirements
- A modern machine (the workflow can take a while and uses Docker + analysis tooling)
- **Docker** installed and running

### Accounts / credentials
- A GitHub account (or any Git remote) to host the seeded demo repository
- An API key for the LLM provider you plan to use
  - If using OpenAI: `OPENAI_API_KEY`

---

## Repository overview (conceptual)

This demo expects a **separate repository** that contains the backend code (seeded from `bike_backend.zip`).  
The orchestrator will `git clone` that repository and work against it (creating branches, applying changes, scanning, etc.).

Typical flow:

1. You create a repo (public is fine), upload the unzipped `bike_backend/` contents.
2. You configure `.env` (tokens, URLs, models).
3. You start the required Docker containers.
4. You run `python code_force_demo.py`.
5. The agents implement the task and iterate until SonarQube’s Quality Gate passes.

---

## Step-by-step local setup

### 1) Prepare the target Git repository (seed repository)

1. Locate `bike_backend.zip` (provided alongside this demo).
2. Unzip it to obtain a directory named `bike_backend/`.
3. Create a new Git repository (e.g., on GitHub).
4. Commit and push the contents of `bike_backend/` into that repository.

At the end you should have a repo URL that the demo can clone (HTTPS or SSH).

---

### 2) Start SonarQube + PostgreSQL (for SonarQube)

#### 2.1 Create Docker volumes
Run:

```bash
docker volume create sonarqube_conf
docker volume create sonarqube_data
docker volume create sonarqube_extensions
docker volume create sonarqube_logs
docker volume create postgres_data
```

#### 2.2 Start PostgreSQL for SonarQube
```bash
docker run -d --name postgres-sonarqube \
  -e POSTGRES_USER=sonar \
  -e POSTGRES_PASSWORD=sonarpass \
  -e POSTGRES_DB=sonarqube \
  -v postgres_data:/var/lib/postgresql/data \
  --restart unless-stopped \
  postgres:15
```

#### 2.3 Start SonarQube Community
```bash
docker run -d --name sonarqube \
  --link postgres-sonarqube:db \
  -e SONAR_JDBC_URL=jdbc:postgresql://db:5432/sonarqube \
  -e SONAR_JDBC_USERNAME=sonar \
  -e SONAR_JDBC_PASSWORD=sonarpass \
  -p 9000:9000 \
  -v sonarqube_conf:/opt/sonarqube/conf \
  -v sonarqube_data:/opt/sonarqube/data \
  -v sonarqube_extensions:/opt/sonarqube/extensions \
  -v sonarqube_logs:/opt/sonarqube/logs \
  sonarqube:community
```

#### 2.4 Verify SonarQube is accessible
Open:

- http://localhost:9000

Log in as admin and follow the UI prompts to set/confirm the admin password.

> Note: On some Linux environments SonarQube may require kernel tuning (`vm.max_map_count`).  
> If SonarQube fails to start, check the container logs and apply the recommended system setting.

---

### 3) Create a SonarQube user token

You will need a token so the **Sonar Analyst agent** can authenticate to SonarQube.

1. Go to SonarQube UI → your user profile → **Security**
2. Generate a **User Token**
3. Copy it and set it in your `.env` as `SONARQUBE_TOKEN`

---

### 4) Start MySQL (for the demo application)

#### 4.1 Run the MySQL container
```bash
docker run --name mysql -d \
  -p 3306:3306 \
  -e MYSQL_ROOT_PASSWORD=1234567890 \
  -v mysql:/var/lib/mysql \
  mysql:lts
```

#### 4.2 Create the application database
Enter the container:

```bash
docker exec -it mysql bash
```

Log into MySQL as root (password is the `MYSQL_ROOT_PASSWORD` you used above):

```bash
mysql -u root -p
```

Create the database and exit:

```sql
CREATE DATABASE bike_backend;
```

```sql
exit;
```

---

### 5) Pre-pull required images (recommended)

To avoid timeouts during the run, pre-pull:

```bash
docker pull mcp/sonarqube
docker pull mcp/filesystem
```

---

### 6) Testcontainers / Docker Java configuration (recommended)

If your environment uses Testcontainers and you want to reduce surprises with Docker detection, create this file in the **HOME** directory of the user running the demo:

```bash
touch ~/.docker-java.properties
```

This is a conservative safeguard used in some Docker/Testcontainers setups.

---

### 7) Python environment setup

From the root of this repository:

1. Create a virtual environment:

```bash
python -m venv .venv
```

2. Activate it:

```bash
source .venv/bin/activate
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Configuration (.env)

Create a `.env` file in the repository root (or copy from a template if provided).

At minimum, set:

- `OPENAI_API_KEY` (if using OpenAI)
- `SONARQUBE_TOKEN`
- Any model / provider parameters used by your setup
- The Git repository URL that will be cloned by the demo script (if the script expects it via env)

Example (illustrative only—use the variables your project expects):

```env
OPENAI_API_KEY=your_openai_key_here
SONARQUBE_URL=http://localhost:9000
SONARQUBE_TOKEN=your_sonarqube_user_token_here

# Target repo seeded with bike_backend code:
TARGET_REPO_URL=https://github.com/<you>/<your-seeded-bike-backend-repo>.git

# Optional: model/provider settings
MODEL_NAME=gpt-4.1
```

> Security note: Do not commit `.env` to a public repository.  
> Keep tokens local and rotate them if exposed.

---

## Running the demo

Before running, confirm:

- Docker is running
- Containers are up:
  - SonarQube (http://localhost:9000 responds)
  - PostgreSQL for SonarQube
  - MySQL (and `bike_backend` database exists)
- Your Python virtual environment is activated

Run:

```bash
python code_force_demo.py
```

The end-to-end run can take significant time depending on machine performance, task complexity, and scanning/quality iterations.

---

## Operational notes

### What to expect during execution
- The system will clone your seeded repository locally
- A new branch will be created for the task
- The agents will implement changes, run checks, and iterate based on:
  - build/test results
  - SonarQube findings and Quality Gate status

### Where to look if something fails
- **Docker logs**:
  - `docker logs sonarqube`
  - `docker logs postgres-sonarqube`
  - `docker logs mysql`
- SonarQube UI:
  - Project background tasks
  - Quality Gate details and issue list

---

## Troubleshooting

### SonarQube container won’t start
- Check `docker logs sonarqube`
- On Linux hosts, apply the kernel settings mentioned in the logs (commonly `vm.max_map_count`).

### SonarQube is running but authentication fails
- Confirm `SONARQUBE_TOKEN` is correct and active
- Confirm the token is a **User Token** created under your SonarQube account

### MySQL connection issues
- Confirm MySQL is listening on `localhost:3306`
- Confirm the `bike_backend` database exists
- Confirm credentials match your app configuration

### Timeout or slow first run
- Pre-pull required images:
  - `mcp/sonarqube`
  - `mcp/filesystem`
- Ensure Docker has sufficient CPU/RAM allocated (especially on Docker Desktop)

---

## Clean up

To stop containers:

```bash
docker stop sonarqube postgres-sonarqube mysql
```

To remove containers:

```bash
docker rm sonarqube postgres-sonarqube mysql
```

To remove volumes (this deletes stored data):

```bash
docker volume rm sonarqube_conf sonarqube_data sonarqube_extensions sonarqube_logs postgres_data mysql
```

---

## License

Add your preferred license here (e.g., MIT, Apache-2.0) and ensure it matches the intended public usage of the demo.

---

## Disclaimer

This is a demonstration project intended for experimentation and education.  
Review generated code carefully before using patterns, configurations, or outputs in production systems.
