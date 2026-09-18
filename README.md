# GridWise — LLM-Assisted Energy Optimization

An LLM-assisted 24-hour energy optimization API developed for the **BUP CSE Fest 2026 Hackathon**.

GridWise converts natural-language campus operator notes into structured, machine-checkable energy directives using a language-capable generative model. The validated directives are then applied to a mathematical optimization model that produces a valid low-cost 24-hour electricity schedule.

---

## 1. Problem Overview

The system models a smart campus using:

- Grid electricity
- Rooftop solar generation
- Battery energy storage
- Time-varying electricity demand
- Time-varying electricity tariffs
- Natural-language operator instructions

For every scenario, the system receives:

1. A 24-hour demand profile
2. A 24-hour solar availability profile
3. A 24-hour grid tariff profile
4. Battery specifications
5. 1–3 natural-language operator notes

The system must:

1. Understand every operator note using an LLM
2. Convert each note into one supported directive
3. Deterministically validate the LLM output
4. Apply all valid directives to the optimization model
5. Generate a valid 24-hour energy schedule
6. Minimize total grid electricity cost
7. Return both the structured interpretation and final schedule

The LLM is therefore part of the actual optimization path, rather than being used only for explanation or documentation.

---

## 2. Solution Architecture

```text
                  ┌─────────────────────────┐
                  │   POST /optimize-energy │
                  │                         │
                  │  Scenario + Operator    │
                  │       Notes             │
                  └────────────┬────────────┘
                               │
                               ▼
                  ┌─────────────────────────┐
                  │   LLM Interpretation    │
                  │                         │
                  │ Groq + Qwen 3.8 27B     │
                  │ Structured JSON output  │
                  └────────────┬────────────┘
                               │
                               ▼
                  ┌─────────────────────────┐
                  │ Deterministic Guardrails│
                  │                         │
                  │ - Directive type        │
                  │ - note_index            │
                  │ - applies semantics     │
                  │ - hour validation       │
                  │ - numeric validation    │
                  │ - adjustment shape      │
                  └────────────┬────────────┘
                               │
                               ▼
                  ┌─────────────────────────┐
                  │    Optimization Model   │
                  │                         │
                  │       SciPy LP           │
                  │       linprog            │
                  │                         │
                  │ Minimize grid cost      │
                  │ subject to constraints  │
                  └────────────┬────────────┘
                               │
                               ▼
                  ┌─────────────────────────┐
                  │ Independent Validation  │
                  │                         │
                  │ Energy balance          │
                  │ Battery limits          │
                  │ Directive compliance    │
                  │ Cost recalculation      │
                  │ End-of-day neutrality   │
                  └────────────┬────────────┘
                               │
                               ▼
                  ┌─────────────────────────┐
                  │     JSON Response       │
                  │                         │
                  │ Interpretation + Plan   │
                  └─────────────────────────┘
```

### Core design principle

```text
Natural Language
       ↓
      LLM
       ↓
Structured Directive
       ↓
Deterministic Validation
       ↓
Optimization Constraints
       ↓
24-Hour Schedule
       ↓
Independent Validation
```

Human-language instructions are never directly trusted as mathematical constraints. They are first converted into structured data and validated before being applied.

---

## 3. Supported Operator Directives

The system supports the following directive types.

| Directive | Meaning | Structured Adjustment |
|---|---|---|
| `solar_reduction` | Reduce usable solar during selected hours | `{"hours":[...], "factor": number}` |
| `minimum_battery_reserve` | Keep battery energy above a required level | `{"hours":[...], "minimum_energy_kwh": number}` |
| `no_charge_window` | Charging is not allowed during selected hours | `{"hours":[...]}` |
| `no_discharge_window` | Discharging is not allowed during selected hours | `{"hours":[...]}` |
| `max_grid_window` | Limit grid import during selected hours | `{"hours":[...], "max_grid_kwh": number}` |
| `no_op` | Note does not affect the current energy schedule | `null` |

### Important semantics

Time windows use whole-hour intervals with:

- start hour included
- end hour excluded

For example:

```text
1 PM to 3 PM
```

maps to:

```json
[13, 14]
```

For `solar_reduction`, the factor represents the fraction of solar that remains usable.

Example:

```text
80% solar reduction
```

means:

```json
{
  "factor": 0.2
}
```

because 20% of the original solar remains usable.

---

## 4. LLM Layer

### Provider

**Groq**

### Model

```text
qwen/qwen3.8-27b
```

### SDK

The implementation uses the OpenAI-compatible Python client with the Groq OpenAI-compatible API endpoint.

The environment variable is intentionally named:

```text
OPENAI_API_KEY
```

for SDK compatibility, but the value should be a **Groq API key**.

### LLM responsibility

The LLM is responsible for interpreting the natural-language `operator_notes` into structured directives.

For each note, the LLM must produce:

- `note_index`
- `applies`
- `directive_type`
- `structured_adjustment`
- `explanation`

The structured interpretation is then deterministically validated before reaching the optimizer.

### What the LLM does NOT control

The LLM does not directly decide:

- demand values
- solar values
- tariffs
- battery capacity
- battery rates
- final grid imports
- final charge/discharge values
- optimization objective
- unsupported directive types

Those values come from the scenario or deterministic application logic.

---

## 5. Deterministic Guardrails

LLM output is treated as untrusted structured data.

Before applying any directive, the application validates:

### Directive type

Must be one of:

```text
solar_reduction
minimum_battery_reserve
no_charge_window
no_discharge_window
max_grid_window
no_op
```

### Note mapping

Every operator note must produce exactly one interpretation entry.

Entries must remain in:

```text
0, 1, 2, ...
```

`note_index` order.

### Applies semantics

For every applicable directive:

```json
"applies": true
```

For `no_op`:

```json
"applies": false
```

`no_op` is the only directive allowed to use:

```json
"applies": false
```

### Hour validation

All hour arrays must contain:

- integers
- values from `0` through `23`
- unique values
- ascending order

### Numeric validation

Relevant numeric values are checked for:

- correct type
- finite values
- valid ranges
- directive-specific constraints

### Structured adjustment validation

The structure must match the selected directive.

Examples:

#### Solar reduction

```json
{
  "hours": [13, 14],
  "factor": 0.2
}
```

#### Battery reserve

```json
{
  "hours": [18, 19, 20],
  "minimum_energy_kwh": 120
}
```

#### No charging

```json
{
  "hours": [14, 15]
}
```

#### No discharging

```json
{
  "hours": [17, 18]
}
```

#### Grid cap

```json
{
  "hours": [19, 20],
  "max_grid_kwh": 150
}
```

#### No-op

```json
null
```

---

## 6. Optimization Model

The final scheduling problem is formulated as a linear program.

### Objective

Minimize total grid electricity cost:

```text
total_cost_bdt =
    Σ(grid_kwh[h] × tariff_bdt_per_kwh[h])
```

for:

```text
h = 0 ... 23
```

### Decision variables

For each hour:

- `grid_kwh`
- `solar_used_kwh`
- `charge_kwh`
- `discharge_kwh`
- `battery_energy_after_kwh`

### Energy balance

For each hour:

```text
grid_kwh + solar_used_kwh + discharge_kwh
=
demand_kwh + charge_kwh
```

### Battery transition

For hour `h`:

```text
battery_energy_after[h]
=
battery_energy_before[h]
+ charge_kwh[h]
- discharge_kwh[h]
```

For hour `0`, the initial battery energy is used as the starting state.

### Battery bounds

At every hour:

```text
minimum_energy_kwh
<=
battery_energy_after_kwh
<=
capacity_kwh
```

### Charge limit

```text
charge_kwh[h]
<=
max_charge_kwh_per_hour
```

### Discharge limit

```text
discharge_kwh[h]
<=
max_discharge_kwh_per_hour
```

### Solar availability

```text
solar_used_kwh[h]
<=
effective_solar_kwh[h]
```

where:

```text
effective_solar_kwh[h]
=
solar_kwh[h] × applicable solar factor
```

### End-of-day neutrality

The final battery energy must equal the initial battery energy:

```text
battery_energy_after[23]
=
initial_energy_kwh
```

This prevents the optimizer from obtaining artificially low costs by simply consuming stored battery energy without restoring it.

---

## 7. Directive Application

After deterministic validation, directives are translated directly into optimizer constraints.

### `solar_reduction`

```text
effective_solar[h] = original_solar[h] × factor
```

for every affected hour.

### `minimum_battery_reserve`

```text
battery_energy_after[h]
>=
max(
    base_minimum_energy,
    directive_minimum_energy
)
```

for every affected hour.

### `no_charge_window`

```text
charge[h] = 0
```

for affected hours.

### `no_discharge_window`

```text
discharge[h] = 0
```

for affected hours.

### `max_grid_window`

```text
grid[h] <= max_grid_kwh
```

for affected hours.

### `no_op`

No optimization constraint is added.

---

## 8. Project Structure

```text
GridWise/
│
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── schemas.py
│   ├── llm_parser.py
│   └── optimizer.py
│
├── .dockerignore
├── .gitignore
├── .env.example
├── Dockerfile
├── README.md
├── requirements.txt
│
├── test_runner.py
├── debug_llm.py
│
└── BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json
```

### Main components

#### `app/main.py`

FastAPI application.

Provides:

```text
GET  /health
POST /optimize-energy
```

Also performs final independent validation before returning the result.

#### `app/schemas.py`

Contains Pydantic request and response models.

Responsible for structural validation of:

- request payload
- battery specification
- hourly data
- directive interpretation
- hourly plan
- final response

#### `app/llm_parser.py`

Handles:

- LLM client initialization
- prompt construction
- structured JSON interpretation
- output parsing
- deterministic directive validation
- retry handling
- interpretation caching

#### `app/optimizer.py`

Contains the mathematical scheduling engine using:

```text
SciPy scipy.optimize.linprog
```

#### `test_runner.py`

Runs the public sample cases against the API and checks:

- directive interpretation
- directive application
- energy balance
- battery transitions
- battery limits
- solar limits
- charge/discharge windows
- grid caps
- end-of-day neutrality
- recalculated totals
- expected public-case cost

#### `debug_llm.py`

Development utility for checking only the LLM interpretation layer against the public sample semantics.

---

## 9. Requirements

The project uses:

```text
Python 3.11
```

Main dependencies:

```text
fastapi==0.110.0
uvicorn==0.28.0
pydantic==2.6.4
scipy==1.12.0
numpy==1.26.4
requests==2.31.0
openai==1.14.0
httpx==0.27.2
```

Install everything using:

```bash
pip install -r requirements.txt
```

---

## 10. Environment Variables

Create a local `.env` file or configure environment variables through the deployment platform.

Required/available variables:

```text
OPENAI_API_KEY=your_groq_api_key_here
GROQ_MODEL=qwen/qwen3.8-27b
LLM_TIMEOUT_SECONDS=15
LLM_MAX_OUTPUT_TOKENS=300
LLM_MAX_ATTEMPTS=3
```

### Variable description

| Variable | Purpose | Example |
|---|---|---|
| `OPENAI_API_KEY` | Groq API key used through the OpenAI-compatible client | `your_groq_api_key_here` |
| `GROQ_MODEL` | LLM model identifier | `qwen/qwen3.8-27b` |
| `LLM_TIMEOUT_SECONDS` | Maximum LLM request timeout | `15` |
| `LLM_MAX_OUTPUT_TOKENS` | Maximum generated output tokens | `300` |
| `LLM_MAX_ATTEMPTS` | Maximum interpretation attempts | `3` |

### Security

Never commit an actual API key.

Do not put secrets inside:

- source code
- `.env`
- README
- Docker image
- Git history
- API responses
- logs

Use:

```text
.env.example
```

for documenting variable names only.

---

## 11. Local Setup

### 11.1 Clone the repository

```bash
git clone <YOUR_REPOSITORY_URL>
cd GridWise
```

### 11.2 Create virtual environment

Windows:

```bash
python -m venv venv
venv\Scripts\activate
```

Linux/macOS:

```bash
python3 -m venv venv
source venv/bin/activate
```

### 11.3 Install dependencies

```bash
pip install -r requirements.txt
```

### 11.4 Configure environment

Create:

```text
.env
```

and configure the required variables.

Example:

```text
OPENAI_API_KEY=your_groq_api_key_here
GROQ_MODEL=qwen/qwen3.8-27b
LLM_TIMEOUT_SECONDS=15
LLM_MAX_OUTPUT_TOKENS=300
LLM_MAX_ATTEMPTS=3
```

---

## 12. Run the API Locally

Start the FastAPI application with:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

For development with automatic reload:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The service will be available at:

```text
http://localhost:8000
```

---

## 13. Health Check

### Request

```bash
curl http://localhost:8000/health
```

### Expected response

```json
{
  "status": "ok"
}
```

The endpoint is intentionally lightweight and does not require an optimization request.

---

## 14. API Endpoint

### `POST /optimize-energy`

Accepts one 24-hour scenario and returns:

- directive interpretation
- final hourly schedule
- total grid usage
- total grid cost
- peak grid usage
- strategy summary

---

## 15. Request Schema

Example:

```json
{
  "scenario_id": "GRID-101",
  "operator_notes": [
    "Solar output will drop to about 20% from 1 PM to 3 PM.",
    "Do not charge the battery between 2 PM and 4 PM.",
    "The cafeteria menu changes tomorrow."
  ],
  "hours": [
    {
      "hour": 0,
      "demand_kwh": 180,
      "solar_kwh": 0,
      "tariff_bdt_per_kwh": 7
    },
    {
      "hour": 1,
      "demand_kwh": 175,
      "solar_kwh": 0,
      "tariff_bdt_per_kwh": 7
    },
    {
      "hour": 2,
      "demand_kwh": 170,
      "solar_kwh": 0,
      "tariff_bdt_per_kwh": 7
    },
    {
      "hour": 3,
      "demand_kwh": 165,
      "solar_kwh": 0,
      "tariff_bdt_per_kwh": 7
    },
    {
      "hour": 4,
      "demand_kwh": 160,
      "solar_kwh": 0,
      "tariff_bdt_per_kwh": 7
    },
    {
      "hour": 5,
      "demand_kwh": 165,
      "solar_kwh": 5,
      "tariff_bdt_per_kwh": 8
    },
    {
      "hour": 6,
      "demand_kwh": 170,
      "solar_kwh": 20,
      "tariff_bdt_per_kwh": 9
    },
    {
      "hour": 7,
      "demand_kwh": 180,
      "solar_kwh": 40,
      "tariff_bdt_per_kwh": 10
    },
    {
      "hour": 8,
      "demand_kwh": 200,
      "solar_kwh": 70,
      "tariff_bdt_per_kwh": 11
    },
    {
      "hour": 9,
      "demand_kwh": 220,
      "solar_kwh": 100,
      "tariff_bdt_per_kwh": 12
    },
    {
      "hour": 10,
      "demand_kwh": 230,
      "solar_kwh": 130,
      "tariff_bdt_per_kwh": 12
    },
    {
      "hour": 11,
      "demand_kwh": 240,
      "solar_kwh": 150,
      "tariff_bdt_per_kwh": 13
    },
    {
      "hour": 12,
      "demand_kwh": 250,
      "solar_kwh": 160,
      "tariff_bdt_per_kwh": 13
    },
    {
      "hour": 13,
      "demand_kwh": 255,
      "solar_kwh": 170,
      "tariff_bdt_per_kwh": 14
    },
    {
      "hour": 14,
      "demand_kwh": 260,
      "solar_kwh": 165,
      "tariff_bdt_per_kwh": 14
    },
    {
      "hour": 15,
      "demand_kwh": 255,
      "solar_kwh": 150,
      "tariff_bdt_per_kwh": 13
    },
    {
      "hour": 16,
      "demand_kwh": 250,
      "solar_kwh": 130,
      "tariff_bdt_per_kwh": 13
    },
    {
      "hour": 17,
      "demand_kwh": 245,
      "solar_kwh": 100,
      "tariff_bdt_per_kwh": 14
    },
    {
      "hour": 18,
      "demand_kwh": 240,
      "solar_kwh": 60,
      "tariff_bdt_per_kwh": 15
    },
    {
      "hour": 19,
      "demand_kwh": 235,
      "solar_kwh": 30,
      "tariff_bdt_per_kwh": 15
    },
    {
      "hour": 20,
      "demand_kwh": 230,
      "solar_kwh": 15,
      "tariff_bdt_per_kwh": 14
    },
    {
      "hour": 21,
      "demand_kwh": 220,
      "solar_kwh": 5,
      "tariff_bdt_per_kwh": 12
    },
    {
      "hour": 22,
      "demand_kwh": 205,
      "solar_kwh": 0,
      "tariff_bdt_per_kwh": 10
    },
    {
      "hour": 23,
      "demand_kwh": 190,
      "solar_kwh": 0,
      "tariff_bdt_per_kwh": 8
    }
  ],
  "battery": {
    "capacity_kwh": 500,
    "initial_energy_kwh": 200,
    "minimum_energy_kwh": 50,
    "max_charge_kwh_per_hour": 100,
    "max_discharge_kwh_per_hour": 100
  }
}
```

---

## 16. Example Curl Request

Save the request payload as:

```text
sample_request.json
```

Then run:

```bash
curl -X POST "http://localhost:8000/optimize-energy" \
  -H "Content-Type: application/json" \
  --data-binary "@sample_request.json"
```

On Windows CMD:

```cmd
curl -X POST "http://localhost:8000/optimize-energy" ^
  -H "Content-Type: application/json" ^
  --data-binary "@sample_request.json"
```

---

## 17. Response Schema

A successful response contains:

```json
{
  "scenario_id": "GRID-101",
  "directive_interpretation": [
    {
      "note_index": 0,
      "applies": true,
      "directive_type": "solar_reduction",
      "structured_adjustment": {
        "hours": [13, 14],
        "factor": 0.2
      },
      "explanation": "Solar availability is reduced during the specified maintenance window."
    },
    {
      "note_index": 1,
      "applies": true,
      "directive_type": "no_charge_window",
      "structured_adjustment": {
        "hours": [14, 15]
      },
      "explanation": "Battery charging is not permitted during the specified hours."
    },
    {
      "note_index": 2,
      "applies": false,
      "directive_type": "no_op",
      "structured_adjustment": null,
      "explanation": "The note does not affect the current 24-hour energy schedule."
    }
  ],
  "hourly_plan": [
    {
      "hour": 0,
      "grid_kwh": 180.0,
      "solar_used_kwh": 0.0,
      "battery_action": "idle",
      "battery_kwh": 0.0,
      "battery_energy_after_kwh": 200.0
    }
  ],
  "total_grid_kwh": 1000.0,
  "total_cost_bdt": 10000.0,
  "peak_grid_kwh": 200.0,
  "plan_summary": "The schedule uses available solar first and shifts battery energy toward higher-tariff periods while respecting all operator directives."
}
```

The exact numerical values in the response depend on the submitted scenario.

---

## 18. Public Sample Test

The repository contains the official public sample cases:

```text
BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json
```

Run the complete public validation suite:

```bash
python test_runner.py
```

The test runner checks both:

### LLM interpretation

- note relevance
- directive type
- affected hours
- numeric parameters
- `applies` semantics
- `no_op` behavior

### Optimization correctness

- exactly 24 hourly entries
- unique hours 0–23
- energy balance
- solar limits
- battery capacity
- battery reserve
- charge limits
- discharge limits
- no-charge windows
- no-discharge windows
- grid caps
- end-of-day battery neutrality
- recalculated total grid usage
- recalculated total cost
- recalculated peak grid usage
- expected public-case cost

Equivalent valid optimal schedules are accepted; the implementation does not need to reproduce one exact hourly plan byte-for-byte.

---

## 19. LLM Debugging Utility

For development-only testing of operator-note interpretation:

```bash
python debug_llm.py
```

This utility focuses on the interpretation layer and helps verify semantic extraction against the public sample cases.

It is not required for running the production API.

---

## 20. Validation Pipeline

The API performs validation at multiple stages.

```text
Incoming JSON
     │
     ▼
Pydantic Request Validation
     │
     ▼
LLM Interpretation
     │
     ▼
Deterministic Directive Validation
     │
     ▼
Directive Application
     │
     ▼
Linear Optimization
     │
     ▼
Independent Schedule Validation
     │
     ▼
Recalculate Totals
     │
     ▼
JSON Response
```

This prevents a correct-looking LLM interpretation from being accepted without verifying its downstream effect on the final schedule.

---

## 21. Independent Final Validation

Before returning a successful response, the API rechecks the generated plan independently of the optimizer.

The final validation verifies:

```text
24 unique hours
        +
Non-negative values
        +
Energy balance
        +
Solar availability
        +
Battery capacity
        +
Battery minimum reserve
        +
Charge rate
        +
Discharge rate
        +
No-charge windows
        +
No-discharge windows
        +
Grid caps
        +
End-of-day neutrality
        +
Recalculated total grid
        +
Recalculated total cost
        +
Recalculated peak grid
```

If the plan fails these checks, the service does not return it as a successful result.

---

## 22. API Error Handling

The API uses controlled HTTP responses.

### `200`

Successful health or optimization response.

### `400`

Malformed request or structurally invalid input.

### `422`

Semantically invalid request rejected by request validation.

### `500`

Controlled internal failure.

Internal exceptions are not exposed as raw stack traces through the API.

---

## 23. Docker

The project includes a production container definition.

### Build

```bash
docker build -t gridwise-llm:latest .
```

### Run

```bash
docker run --rm -p 8000:8000 \
  -e OPENAI_API_KEY="your_groq_api_key_here" \
  -e GROQ_MODEL="qwen/qwen3.8-27b" \
  -e LLM_TIMEOUT_SECONDS="15" \
  -e LLM_MAX_OUTPUT_TOKENS="300" \
  -e LLM_MAX_ATTEMPTS="3" \
  gridwise-llm:latest
```

Windows PowerShell:

```powershell
docker run --rm -p 8000:8000 `
  -e OPENAI_API_KEY="your_groq_api_key_here" `
  -e GROQ_MODEL="qwen/qwen3.8-27b" `
  -e LLM_TIMEOUT_SECONDS="15" `
  -e LLM_MAX_OUTPUT_TOKENS="300" `
  -e LLM_MAX_ATTEMPTS="3" `
  gridwise-llm:latest
```

### Health check

```bash
curl http://localhost:8000/health
```

Expected:

```json
{
  "status": "ok"
}
```

The container binds the service to:

```text
0.0.0.0:8000
```

---

## 24. Deployment

The service can be deployed on a public HTTP hosting platform that supports Python web services or containers.

Required production behavior:

```text
GET  /health
POST /optimize-energy
```

The judge must be able to access the service without:

- login
- VPN
- manual approval
- private-network access

The deployed service should remain reachable throughout the evaluation period.

### Production environment variables

Configure the variables through the hosting provider's secret/environment-variable system:

```text
OPENAI_API_KEY
GROQ_MODEL
LLM_TIMEOUT_SECONDS
LLM_MAX_OUTPUT_TOKENS
LLM_MAX_ATTEMPTS
```

Do not hard-code the actual API key into source code or Docker images.

---

## 25. Performance Considerations

The API is designed around the challenge's per-request limits.

The optimization stage is a small 24-hour linear program, so the primary variable latency source is the external LLM request.

The implementation therefore uses:

- bounded LLM output
- configurable request timeout
- limited retries
- deterministic post-processing
- interpretation caching
- lightweight linear optimization
- final validation performed in-process

Recommended production testing should measure:

```text
/health latency
/optimize-energy latency
success rate
LLM failure rate
repeated-request stability
```

---

## 26. Known Limitations

### External LLM dependency

Operator-note interpretation depends on the configured LLM provider.

Provider-side issues such as:

- API availability
- rate limits
- quota limitations
- network failures

can affect request latency or availability.

### No runtime model training

The solution does not perform model training or fine-tuning during request processing.

### Fixed directive vocabulary

The optimizer only supports the challenge-defined directives. Unsupported instructions are not converted into arbitrary optimization rules.

### 24-hour horizon

The optimization model is designed specifically for the challenge's 24-hour scheduling horizon.

### Synthetic challenge data

The implementation is designed for the supplied challenge scenarios and does not claim to model all real-world campus energy systems.

---

## 27. Security

Security-sensitive data must never be committed to the repository.

### Never commit

```text
.env
API keys
access tokens
passwords
private credentials
secret configuration
```

### Recommended local setup

Use:

```text
.env
```

locally and:

```text
.env.example
```

for documentation.

The `.gitignore` and `.dockerignore` files are configured to help prevent accidental inclusion of environment files and local artifacts.

---

## 28. Reproducibility

A clean environment can reproduce the project using:

```bash
git clone <YOUR_REPOSITORY_URL>
cd GridWise

python -m venv venv
```

Activate the environment and install:

```bash
pip install -r requirements.txt
```

Configure the required environment variables and start:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Check:

```bash
curl http://localhost:8000/health
```

Then execute:

```bash
python test_runner.py
```

---

## 29. Example End-to-End Flow

Example operator notes:

```text
"Solar output will drop to about 20% from 1 PM to 3 PM."

"Do not charge the battery between 2 PM and 4 PM."

"The cafeteria menu changes tomorrow."
```

### Step 1 — LLM interpretation

The language model maps them to:

```text
Note 0 → solar_reduction
Note 1 → no_charge_window
Note 2 → no_op
```

### Step 2 — Deterministic validation

The application verifies:

```text
hours are valid
factors are valid
directive types are supported
applies values are correct
adjustment structures are correct
```

### Step 3 — Constraint generation

The optimizer receives:

```text
Solar reduction
+
No-charge window
```

while the `no_op` note adds no scheduling constraint.

### Step 4 — Optimization

The LP minimizes:

```text
Σ(grid × tariff)
```

while satisfying all energy, battery, solar, and operator constraints.

### Step 5 — Final validation

The returned schedule is independently replayed and checked.

### Step 6 — Response

The service returns:

```text
directive_interpretation
+
hourly_plan
+
total_grid_kwh
+
total_cost_bdt
+
peak_grid_kwh
+
plan_summary
```

---

## 30. Design Philosophy

GridWise deliberately separates three responsibilities:

### Language understanding

Handled by the LLM.

```text
Human note
↓
Semantic interpretation
```

### Safety and correctness

Handled deterministically.

```text
Structured output
↓
Schema validation
↓
Guardrails
```

### Mathematical scheduling

Handled by the optimizer.

```text
Validated directives
↓
Optimization constraints
↓
Lowest-cost valid schedule
```

This separation reduces the chance that an LLM can directly produce an invalid mathematical schedule.

---

## 31. Technology Stack

| Component | Technology |
|---|---|
| API framework | FastAPI |
| Language | Python 3.11 |
| Validation | Pydantic |
| LLM client | OpenAI-compatible Python SDK |
| LLM provider | Groq |
| LLM model | Qwen 3.8 27B |
| Optimization | SciPy `linprog` |
| Numerical computing | NumPy |
| HTTP client/testing | Requests |
| ASGI server | Uvicorn |
| Containerization | Docker |

---

## 32. Important Challenge Compliance Notes

The implementation is designed around the canonical GridWise challenge rules:

- `GET /health` is implemented.
- `POST /optimize-energy` is implemented.
- Operator notes are interpreted through a language-capable generative model.
- Every note produces one interpretation entry.
- Supported directive types are explicitly constrained.
- LLM output is deterministically validated.
- Valid directives are applied to the optimizer.
- The final plan contains 24 hours.
- Energy balance is enforced.
- Battery limits are enforced.
- Solar limits are enforced.
- Operator windows are enforced.
- Final battery energy returns to the initial level.
- Totals are recalculated from the returned hourly plan.
- The API does not expose raw stack traces through successful/failure responses.
- Secrets are not intended to be included in the repository or Docker image.

---

## 33. License

This project was developed as a hackathon submission for:

**BUP CSE Fest 2026 Hackathon — GridWise**

All challenge-specific data and materials are used only for the intended hackathon evaluation and development purposes.

---

## 34. Quick Reference

### Start locally

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Health

```bash
curl http://localhost:8000/health
```

### Optimize

```bash
curl -X POST "http://localhost:8000/optimize-energy" \
  -H "Content-Type: application/json" \
  --data-binary "@sample_request.json"
```

### Run public tests

```bash
python test_runner.py
```

### Build Docker image

```bash
docker build -t gridwise-llm:latest .
```

### Run Docker image

```bash
docker run --rm -p 8000:8000 \
  -e OPENAI_API_KEY="your_groq_api_key_here" \
  -e GROQ_MODEL="qwen/qwen3.8-27b" \
  -e LLM_TIMEOUT_SECONDS="15" \
  -e LLM_MAX_OUTPUT_TOKENS="300" \
  -e LLM_MAX_ATTEMPTS="3" \
  gridwise-llm:latest
```

---

## 35. Final Summary

GridWise combines:

```text
LLM-based natural-language understanding
                +
Deterministic guardrails
                +
Linear programming
                +
Independent schedule validation
```

to transform natural-language campus instructions into a valid, low-cost 24-hour energy schedule.

The core execution path is:

```text
Operator Notes
      ↓
Qwen 3.8 27B
      ↓
Structured Directives
      ↓
Deterministic Validation
      ↓
SciPy Linear Program
      ↓
24-Hour Energy Plan
      ↓
Independent Validation
      ↓
Final JSON API Response
```
