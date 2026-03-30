# Nova Apps Workshop 2026

__Goal:__ <br/>
Hands-on, vibe-coding–led workshop where each Nova participant uses Genie Code to build an end-to-end data & AI workflow:

- Generate synthetic data per user.
- Build a simple Delta medallion model (Bronze/Silver/Gold).
- Use Lakebase as an operational store.
- Build a Databricks App that reads from Delta & Lakebase.
- Add a “Deep Research / Incident Copilot” stretch module powered by a model/agent.

__Domain:__ Polymer/chemical production (extruder/pelletizer lines). <br/>
__Scenario:__ Each participant acts as a process engineer monitoring a line, logging incidents, and exploring quality trends through an app + copilot.
<br/>

##Target Audience & Prerequisites##

__Audience:__ Data engineers, analytics engineers, and citizen developers. Some basic familiarity with Python or SQL is helpful but not required.<br/>
__Skill prerequisites:__ Comfort with basic SQL and reading Python. No prior Databricks Apps or Lakebase experience required.

__Platform prerequisites (workspace):__
- Unity Catalog enabled.
- Serverless (SQL + compute) enabled.
- Genie Code enabled (Agent + inline in notebooks).
- Databricks Apps enabled.
- Lakebase (managed PostgreSQL) enabled in the region.
- Model Serving endpoint available for the Deep Research copilot (you pre-provision).


##High-Level Architecture##
###End-to-end flow for the lab###

__Synthetic data (per user):__ Users generate time-series sensor data for a production line using Genie Code in notebooks. Data lands as a raw Delta table under their own schema in a shared catalog (e.g., `nova_workshop.<user_schema>`).

__Delta Medallion Model:__
- Bronze: raw with ingestion metadata.
- Silver: cleaned and standardized events.
- Gold: daily line-level KPIs (avg temperature, max pressure, % BAD, alert flag).

__Lakebase (OLTP side):__ One Lakebase database instance (e.g., nova_incidents). Per-user schema with incidents tables, used for interactive app state (operator incidents).

__Databricks App:__ 
- Simple Python app (Streamlit or Gradio) deployed via Databricks Apps:
  - KPI dashboard from Gold Delta table.
  - Incident list + creation/update UI backed by Lakebase.

__Deep Research / Incident Copilot (Stretch Module)__
- App calls a model/agent endpoint (Model Serving) with structured context:
  - Recent incidents (Lakebase).
  - Recent KPIs (Gold Delta).
  - Endpoint returns a reasoned answer (root-cause ideas + next steps).
