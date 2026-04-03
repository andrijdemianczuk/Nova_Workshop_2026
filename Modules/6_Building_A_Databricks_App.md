# Building a Databricks App

## Overview

This module walks through creating a custom Databricks App, connecting it to the source code in the adjacent `App/` directory, and configuring the resources and authorization scopes the app needs at runtime — specifically **Lakebase** for PostgreSQL-backed persistence, a **model serving endpoint** for agent access, an **MLflow experiment** for trace logging, and a **Genie space** for natural language analytics.

---

## Step 1: Create a Custom (Blank) App

1. In the Databricks sidebar, click **New** → **App**.
2. Select **Create a custom app**.
3. Enter a name for the app (lowercase letters, numbers, and hyphens only).
   > **Note:** The app name is permanent — it cannot be changed after creation and determines the app URL.
4. Add an optional description.
5. Click **Next: Configure** (or **Create app** to skip configuration and add resources later).

Databricks provisions a service principal for the app and generates the app URL, but does **not** deploy anything yet — you must sync your code first.

---

## Step 2: Sync Source Code from the `App/` Directory

The app source code lives at `Nova_Workshop_2026/App/` — adjacent to this `Modules/` directory. The structure is:

```
Nova_Workshop_2026/
├── App/
│   ├── app.py            # Dash application entry point
│   ├── app.yaml          # App manifest (command, env vars, resources)
│   └── requirements.txt  # Python dependencies
├── Modules/
│   └── 6_Building_A_Databricks_App.md   ← you are here
└── ...
```

After the app is created, the details page displays instructions for syncing code. From your local environment (or a Databricks terminal), use the Databricks CLI to push the `App/` directory contents to the app:

```bash
# Sync the App directory to the Databricks App workspace path
databricks apps deploy <your-app-name> \
  --source-code-path /Workspace/Users/<your-email>/Nova_Workshop_2026/App
```

The `app.yaml` manifest tells Databricks how to start the app and which environment variables to inject:

```yaml
command: ["python", "app.py"]
env:
  - name: PGENDPOINT
    valueFrom: postgres
  - name: MLFLOW_EXPERIMENT_ID
    valueFrom: experiment
```

* `PGENDPOINT` — resolved from the Lakebase resource (key: `postgres`)
* `MLFLOW_EXPERIMENT_ID` — resolved from the MLflow experiment resource (key: `experiment`)

---

## Step 3: Add App Resources

App resources grant the app's **service principal** access to Databricks platform services. Navigate to the app's **Edit** → **Configure** step, then use **+ Add resource** for each of the following.

### 3a. Lakebase Database

| Setting | Value |
| --- | --- |
| **Resource type** | Lakebase database |
| **Lakebase project** | *(select your Lakebase Autoscaling project)* |
| **Permission** | **Can connect and create** |
| **Resource key** | `postgres` |

When you add this resource, Databricks automatically:
* Creates a matching Postgres role for the app's service principal.
* Grants the service principal database access to connect, create schemas, and read/write data.
* Injects the standard `PG*` environment variables (`PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGSSLMODE`, `PGAPPNAME`) into the app runtime.

> **Important:** The auto-provisioned permissions only cover schemas the app itself creates. If your Lakebase project has **pre-existing schemas** (e.g., `andrij_demo`) that the app needs to query, you must explicitly grant access. Open the **Lakebase SQL Editor** and run the following against each schema:
>
> ```sql
> GRANT USAGE ON SCHEMA <your_schema> TO PUBLIC;
> GRANT SELECT ON ALL TABLES IN SCHEMA <your_schema> TO PUBLIC;
> ```
>
> Without these grants, the app's service principal will fail to query tables in schemas it did not create.

The `PGENDPOINT` env var (defined in `app.yaml` via `valueFrom: postgres`) provides the endpoint reference for the `generate_database_credential()` call in `app.py`.

### 3b. MLflow Experiment (Trace Logging)

| Setting | Value |
| --- | --- |
| **Resource type** | MLflow experiment |
| **Experiment** | *(select an existing experiment or create one)* |
| **Permission** | **Can edit** |
| **Resource key** | `experiment` |

This grants the app's service principal edit access to the selected experiment, enabling:
* Execution traces via `@mlflow.trace()` decorators (used in `ask_agent()`)
* Logging of request/response artifacts with `mlflow.log_text()`
* Parameter, metric, and artifact tracking throughout the app lifecycle

The `MLFLOW_EXPERIMENT_ID` env var (defined in `app.yaml` via `valueFrom: experiment`) is picked up by `mlflow.set_experiment(experiment_id=...)` in `app.py`.

### 3c. Model Serving Endpoint *(optional app resource)*

If you want the app's **service principal** to query the agent endpoint directly (app authorization), also add:

| Setting | Value |
| --- | --- |
| **Resource type** | Model serving endpoint |
| **Endpoint** | *(select your agent serving endpoint)* |
| **Permission** | **Can query** |
| **Resource key** | `serving-endpoint` |

> This is required when the app calls the endpoint using its own service principal identity (the default pattern in `app.py` via `workspace_client.api_client.do()`).

### 3d. Genie Space

| Setting | Value |
| --- | --- |
| **Resource type** | Genie space |
| **Genie space** | *(select an existing Genie space from your workspace)* |
| **Permission** | **Can run** |
| **Resource key** | `genie-space` |

When you add this resource, Databricks grants the app's service principal the specified permission on the selected Genie space. The app can then submit natural language queries to the space and receive structured responses with SQL and results.

> **Additional service principal permissions required:** The app's service principal also needs access to the **underlying data sources** that the Genie space queries. Grant the following in Unity Catalog:
>
> * `USE CATALOG` on the relevant catalog
> * `USE SCHEMA` on the relevant schema
> * `SELECT` on the tables the Genie space queries
>
> If the Genie space uses a dedicated SQL warehouse, the service principal also needs **Can use** on that warehouse.

Access is scoped to the selected space only — the app cannot access other Genie spaces unless they are added as separate resources.

---

## Step 4: Configure User Authorization Scopes

User authorization allows the app to act **on behalf of the logged-in user** rather than the app's service principal. This is critical when the serving endpoint enforces user-level permissions or when you need per-user identity for data access.

> **Prerequisite:** User authorization is in **Public Preview**. A workspace admin must enable it before scopes can be added.

In the **Configure** step, under **User authorization**, click **+ Add scope** and add the following:

### Serving Endpoints Scope (Agent Access)

| Scope | Purpose |
| --- | --- |
| `serving.serving-endpoints` | Allows the app to call model serving endpoints on behalf of the user. **Required** for Supervisor Agent endpoints and any endpoint with auth-policy scopes configured. |

This scope is essential when:
* The agent endpoint requires user authorization (e.g., Supervisor Agent endpoints always require it).
* The endpoint's auth policy includes API scopes that must be forwarded with the user's token.

### Genie Space Scope

| Scope | Purpose |
| --- | --- |
| `dashboards.genie` | Allows the app to interact with Genie spaces on behalf of the user, respecting their individual Unity Catalog permissions for row/column-level security. |

Add this scope if the app needs to forward the logged-in user's identity when querying the Genie space, rather than using the service principal's shared permissions.

### Lakebase Scope

Lakebase access is primarily handled through **app authorization** (the service principal). When you add a Lakebase database as an app resource (Step 3a), the service principal automatically receives the necessary Postgres role and permissions — **no additional user authorization scope is required** for standard Lakebase connectivity.

However, if your app needs to access Lakebase **on behalf of individual users** (e.g., per-user row-level access), you would enable user authorization and create corresponding Postgres roles for each user identity using `databricks_create_role()` in the Lakebase SQL Editor.

---

## Step 5: Deploy and Verify

Once resources and scopes are configured:

1. Click **Create app** (or **Save** if editing).
2. Deploy the app using the CLI:
   ```bash
   databricks apps deploy <your-app-name> \
     --source-code-path /Workspace/Users/<your-email>/Nova_Workshop_2026/App
   ```
3. Monitor the deployment status on the app details page.
4. Once running, open the app URL to verify:
   * The Lakebase-backed todo list and incidents table load correctly.
   * The chat assistant connects to the agent serving endpoint.
   * MLflow traces appear in the linked experiment.
   * Genie space queries return structured responses.

---

## Resource Summary

| Resource | Type | Key | Permission | Auth Model |
| --- | --- | --- | --- | --- |
| Lakebase database | Lakebase database | `postgres` | Can connect and create | App (service principal) |
| MLflow experiment | MLflow experiment | `experiment` | Can edit | App (service principal) |
| Agent endpoint | Model serving endpoint | `serving-endpoint` | Can query | App + User (`serving.serving-endpoints` scope) |
| Genie space | Genie space | `genie-space` | Can run | App + User (`dashboards.genie` scope) |

---

## ⚠️ Before You Deploy: Update Your Serving Endpoint

Each participant in this workshop creates their own **Genie space**, **Supervisor Agent**, and **agent serving endpoint**. The app source code ships with a placeholder endpoint name that **must be replaced** with your own before deploying.

Open `App/app.py` and locate **line 16**:

```python
AGENT_MODEL = "mas-8f48e375-endpoint"
```

Replace the value with your own serving endpoint name:

```python
AGENT_MODEL = "<your-serving-endpoint-name>"
```

**Where to find your endpoint name:**

1. In the Databricks sidebar, navigate to **Serving** (under Machine Learning).
2. Locate the endpoint created for your Supervisor Agent.
3. Copy the **endpoint name** from the top of the endpoint details page (e.g., `mas-<hash>-endpoint`).

This value is used in `app.py` to route chat requests to your agent:

```python
response = workspace_client.api_client.do(
    "POST",
    f"/serving-endpoints/{AGENT_MODEL}/invocations",
    body=body
)
```

> **Important:** If you skip this step, the app's chat assistant will either fail with a 404 (endpoint not found) or route requests to another participant's agent. Every user must point to their own endpoint.

Similarly, verify that the app resources added in **Step 3** reference **your own** instances:

| Resource | What to verify |
| --- | --- |
| **Lakebase database** | Points to your Lakebase Autoscaling project (with the synced table) |
| **Genie space** | Points to the Genie space you created (backed by your Lakebase table) |
| **MLflow experiment** | Points to an experiment in your workspace directory |
| **Model serving endpoint** | Points to your Supervisor Agent's serving endpoint |

Once all four resources and the `AGENT_MODEL` value are set to your own, proceed to **Step 5** to deploy.

---

## References

* [Create a custom Databricks app](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/create-custom-app/)
* [Add resources to a Databricks app](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/resources/)
* [Configure authorization in a Databricks app](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/auth/)
* [Add a Lakebase resource to a Databricks app](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/lakebase/)
* [Add an MLflow experiment resource to a Databricks app](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/mlflow/)
* [Add a Genie space resource to a Databricks app](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/genie/)
* [Using Lakebase with Databricks Apps](https://docs.databricks.com/aws/en/oltp/projects/databricks-apps/)
