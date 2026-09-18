# GridWise — LLM-Assisted Energy Optimization

An LLM-assisted 24-hour energy optimization API developed for the **BUP CSE Fest 2026 Hackathon**.

GridWise receives a 24-hour smart-campus energy scenario together with 1–3 natural-language operator notes. A language-capable generative model interprets those notes into structured energy directives. Deterministic guardrails validate the interpretation, and a linear-programming optimizer produces a valid low-cost 24-hour schedule.

The system is designed around the official GridWise challenge contract: understand the operator note, validate the structured directive, apply it to the optimization model, return a valid 24-hour schedule, and minimize grid electricity cost.

---

## 1. Live Deployment

### Production API

```text
https://gridwise-llm-optimizer-mpgg.onrender.com
```

### Health Endpoint

```text
GET /health
```

Full URL:

```text
https://gridwise-llm-optimizer-mpgg.onrender.com/health
```

Expected response:

```json
{
  "status": "ok"
}
```

### Optimization Endpoint

```text
POST /optimize-energy
```

Full URL:

```text
https://gridwise-llm-optimizer-mpgg.onrender.com/optimize-energy
```

---

## 2. Problem Overview

GridWise models a smart campus that uses:

- Grid electricity
- Rooftop solar generation
- Battery energy storage
- Time-varying electricity demand
- Time-varying grid tariffs
- Natural-language operator instructions

For every scenario, the service receives:

1. A unique scenario ID
2. 1–3 natural-language operator notes
3. Exactly 24 hourly entries
4. Battery specifications

The service must:

1. Interpret every operator note using an LLM
2. Convert each note into one supported directive
3. Mark irrelevant notes as `no_op`
4. Deterministically validate the LLM output
5. Apply valid directives to the optimization model
6. Generate a valid 24-hour energy schedule
7. Minimize total grid electricity cost
8. Recalculate and return the final schedule totals

The LLM is part of the actual operator-note interpretation path. It is not used only for `plan_summary` or documentation.

---

## 3. Solution Architecture

```text
                    ┌──────────────────────────────┐
                    │   POST /optimize-energy      │
                    │                              │
                    │ Scenario + Operator Notes    │
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │      LLM Interpretation      │
                    │                              │
                    │ Groq                         │
                    │ Qwen 3.8 27B                │
                    │ Structured JSON              │
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │   Deterministic Guardrails   │
                    │                              │
                    │ • Directive type             │
                    │ • note_index order           │
                    │ • applies semantics          │
                    │ • hour validation            │
                    │ • numeric validation         │
                    │ • adjustment structure       │
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │     Linear Optimization      │
                    │                              │
                    │ SciPy scipy.optimize.linprog │
                    │                              │
                    │ Minimize grid electricity    │
                    │ cost under all constraints   │
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │    Independent Validation    │
                    │                              │
                    │ • Energy balance             │
                    │ • Solar limits               │
                    │ • Battery limits             │
                    │ • Directive windows          │
                    │ • Grid caps                  │
                    │ • End-of-day neutrality      │
                    │ • Total recalculation        │
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │        JSON Response         │
                    │                              │
                    │ Interpretation + 24h Plan    │
                    └──────────────────────────────┘
```

### Core execution path

```text
Natural-Language Operator Note
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
              ↓
Final JSON Response
```

---

## 4. Supported Operator Directives

GridWise supports exactly these directive types:

| Directive | Meaning | Structured Adjustment |
|---|---|---|
| `solar_reduction` | Reduce usable solar during selected hours | `{"hours":[...], "factor": number}` |
| `minimum_battery_reserve` | Keep battery energy above a required level | `{"hours":[...], "minimum_energy_kwh": number}` |
| `no_charge_window` | Battery charging is unavailable during selected hours | `{"hours":[...]}` |
| `no_discharge_window` | Battery discharging is unavailable during selected hours | `{"hours":[...]}` |
| `max_grid_window` | Grid import may not exceed a stated value during selected hours | `{"hours":[...], "max_grid_kwh": number}` |
| `no_op` | The note does not affect the current 24-hour schedule | `null` |

### Time-window convention

Time windows use whole-hour intervals.

The start hour is included and the end hour is excluded.

Example:

```text
1 PM to 3 PM
```

becomes:

```json
[13, 14]
```

### Solar reduction convention

For `solar_reduction`, `factor` means the usable fraction that remains.

Example:

```text
80% reduction
```

means:

```json
{
  "factor": 0.2
}
```

because 20% of the original solar remains usable.

---

## 5. LLM Layer

### Provider

```text
Groq
```

### Model

```text
qwen/qwen3.8-27b
```

### Client

The implementation uses the OpenAI-compatible Python SDK with the Groq OpenAI-compatible API endpoint.

### LLM responsibility

For every operator note, the model produces:

- `note_index`
- `applies`
- `directive_type`
- `structured_adjustment`
- `explanation`

The structured result becomes input to the deterministic validation layer and, when valid, to the optimizer.

### The LLM does not directly control

The model does not invent or directly choose:

- demand values
- solar availability
- tariffs
- battery capacity
- battery limits
- final grid import
- final charge/discharge amounts
- unsupported directive types
- optimization objective

These are supplied by the scenario or determined by deterministic application logic.

---

## 6. Deterministic Guardrails

LLM output is treated as untrusted structured data until deterministic validation succeeds.

### Allowed directive types

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

The entries must be returned in:

```text
0, 1, 2, ...
```

`note_index` order.

### Applies semantics

For applicable directives:

```json
"applies": true
```

For `no_op`:

```json
"applies": false
```

Only `no_op` may use `applies = false`.

### Hours

Every `hours` array is validated to contain:

- integers
- values from `0` through `23`
- unique values
- ascending order

### Numeric values

Numeric values are checked for:

- numeric type
- finite values
- valid range
- directive-specific constraints

### Structured adjustment

The adjustment shape must match the selected directive.

#### `solar_reduction`

```json
{
  "hours": [13, 14],
  "factor": 0.2
}
```

#### `minimum_battery_reserve`

```json
{
  "hours": [18, 19, 20],
  "minimum_energy_kwh": 120
}
```

#### `no_charge_window`

```json
{
  "hours": [14, 15]
}
```

#### `no_discharge_window`

```json
{
  "hours": [17, 18]
}
```

#### `max_grid_window`

```json
{
  "hours": [19, 20],
  "max_grid_kwh": 150
}
```

#### `no_op`

```json
null
```

---

## 7. Optimization Model

The scheduling problem is formulated as a linear program.

### Objective

Minimize total grid electricity cost:

```text
total_cost_bdt =
    Σ(grid_kwh[h] × tariff_bdt_per_kwh[h])
```

for hours:

```text
h = 0 ... 23
```

### Decision variables

For every hour:

- `grid_kwh`
- `solar_used_kwh`
- `charge_kwh`
- `discharge_kwh`
- `battery_energy_after_kwh`

### Energy balance

For every hour:

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

Hour `0` starts from `initial_energy_kwh`.

### Battery bounds

At every hour:

```text
minimum_energy_kwh
≤
battery_energy_after_kwh
≤
capacity_kwh
```

### Charging rate

```text
charge_kwh[h] ≤ max_charge_kwh_per_hour
```

### Discharging rate

```text
discharge_kwh[h] ≤ max_discharge_kwh_per_hour
```

### Solar availability

```text
solar_used_kwh[h] ≤ effective_solar_kwh[h]
```

where:

```text
effective_solar_kwh[h]
=
solar_kwh[h] × applicable_solar_factor
```

### End-of-day neutrality

The final battery state equals the initial battery state:

```text
battery_energy_after[23]
=
initial_energy_kwh
```

This prevents the optimizer from reducing cost by consuming the starting battery energy without restoring it.

---

## 8. Directive Application to the Optimizer

After validation, directives are translated into deterministic optimization constraints.

### `solar_reduction`

```text
effective_solar[h]
=
original_solar[h] × factor
```

for affected hours.

### `minimum_battery_reserve`

```text
battery_energy_after[h]
≥
max(
    base_minimum_energy,
    directive_minimum_energy
)
```

for affected hours.

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
grid[h] ≤ max_grid_kwh
```

for affected hours.

### `no_op`

No optimization constraint is added.

---

## 9. Independent Final Validation

The generated plan is independently checked before the response is returned.

The validation layer verifies:

```text
Exactly 24 unique hours
        +
Hours 0–23
        +
Non-negative numeric values
        +
Energy balance for every hour
        +
Effective solar limit
        +
Battery capacity
        +
Battery minimum reserve
        +
Charge rate limit
        +
Discharge rate limit
        +
No-charge windows
        +
No-discharge windows
        +
Grid-cap windows
        +
Battery state transitions
        +
End-of-day neutrality
        +
Recalculated total grid
        +
Recalculated total cost
        +
Recalculated peak grid
```

This makes the returned `hourly_plan` independently machine-checkable.

---

## 10. API Contract

### `GET /health`

Returns:

```json
{
  "status": "ok"
}
```

### `POST /optimize-energy`

Accepts one scenario object.

Required top-level fields:

```text
scenario_id
operator_notes
hours
battery
```

### Hour fields

Each hour entry contains:

```text
hour
demand_kwh
solar_kwh
tariff_bdt_per_kwh
```

Exactly 24 hours are required, covering `0` through `23`.

### Battery fields

```text
capacity_kwh
initial_energy_kwh
minimum_energy_kwh
max_charge_kwh_per_hour
max_discharge_kwh_per_hour
```

### Response fields

A successful response contains:

```text
scenario_id
directive_interpretation
hourly_plan
total_grid_kwh
total_cost_bdt
peak_grid_kwh
plan_summary
```

### Directive interpretation fields

Each interpretation entry contains:

```text
note_index
applies
directive_type
structured_adjustment
explanation
```

### Hourly plan fields

Each hourly plan entry contains:

```text
hour
grid_kwh
solar_used_kwh
battery_action
battery_kwh
battery_energy_after_kwh
```

Allowed `battery_action` values:

```text
charge
discharge
idle
```

---

## 11. Project Structure

```text
gridwise-llm-optimizer/
│
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── schemas.py
│   ├── llm_parser.py
│   └── optimizer.py
│
├── .dockerignore
├── .env.example
├── .gitignore
├── .python-version
├── Dockerfile
├── README.md
├── requirements.txt
│
├── debug_llm.py
├── test_runner.py
│
└── BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json
```

### Component responsibilities

#### `app/main.py`

FastAPI application.

Provides:

```text
GET  /health
POST /optimize-energy
```

The main pipeline also performs final schedule validation and recalculates response totals.

#### `app/schemas.py`

Pydantic request and response models.

Handles structural validation for:

- request payloads
- hourly data
- battery data
- directive interpretation
- hourly plans
- final responses

#### `app/llm_parser.py`

Handles:

- LLM client initialization
- prompt construction
- structured JSON interpretation
- parsing
- deterministic validation
- retry handling
- interpretation caching

#### `app/optimizer.py`

Contains the mathematical energy scheduler using:

```text
scipy.optimize.linprog
```

#### `test_runner.py`

Runs the official public sample cases against a configurable API base URL.

It validates:

- interpretation semantics
- directive application
- energy balance
- battery transitions
- solar limits
- reserve constraints
- charge/discharge limits
- operator windows
- grid caps
- end-of-day neutrality
- recalculated totals
- public-case optimization cost

#### `debug_llm.py`

Development-only utility for checking the LLM interpretation layer against public sample semantics.

---

## 12. Technology Stack

| Component | Technology |
|---|---|
| API framework | FastAPI |
| Language | Python 3.11 |
| Data validation | Pydantic |
| LLM provider | Groq |
| LLM model | Qwen 3.8 27B |
| LLM client | OpenAI-compatible Python SDK |
| Optimization | SciPy `linprog` |
| Numerical computing | NumPy |
| HTTP testing | Requests |
| ASGI server | Uvicorn |
| Containerization | Docker |
| Deployment | Render |

---

## 13. Requirements

Python version:

```text
3.11
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

Install with:

```bash
pip install -r requirements.txt
```

---

## 14. Environment Variables

The service uses the following environment variables:

| Variable | Purpose | Example |
|---|---|---|
| `OPENAI_API_KEY` | Groq API key used through the OpenAI-compatible client | `your_groq_api_key_here` |
| `GROQ_MODEL` | LLM model identifier | `qwen/qwen3.8-27b` |
| `LLM_TIMEOUT_SECONDS` | LLM request timeout | `15` |
| `LLM_MAX_OUTPUT_TOKENS` | Maximum generated output tokens | `300` |
| `LLM_MAX_ATTEMPTS` | Maximum interpretation attempts | `3` |

### Example `.env`

```text
OPENAI_API_KEY=your_groq_api_key_here
GROQ_MODEL=qwen/qwen3.8-27b
LLM_TIMEOUT_SECONDS=15
LLM_MAX_OUTPUT_TOKENS=300
LLM_MAX_ATTEMPTS=3
```

Never commit a real API key.

---

## 15. Local Setup

### Clone

```bash
git clone <YOUR_REPOSITORY_URL>
cd gridwise-llm-optimizer
```

### Create a virtual environment

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

### Install dependencies

```bash
pip install -r requirements.txt
```

### Configure environment

Create `.env` or export the required environment variables.

Do not commit `.env`.

---

## 16. Run Locally

Start the API:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

For development:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The local service runs at:

```text
http://localhost:8000
```

---

## 17. Local Health Test

```bash
curl http://localhost:8000/health
```

Expected:

```json
{
  "status": "ok"
}
```

---

## 18. API Request Example

A representative request is:

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
    }
  ],
  "...": "22 additional hourly entries",
  "battery": {
    "capacity_kwh": 500,
    "initial_energy_kwh": 200,
    "minimum_energy_kwh": 50,
    "max_charge_kwh_per_hour": 100,
    "max_discharge_kwh_per_hour": 100
  }
}
```

A real request must contain exactly 24 hourly entries with hours `0` through `23`.

---

## 19. Example Curl Request

Save a complete request as `sample_request.json`, then run:

### Git Bash / Linux / macOS

```bash
curl -X POST "http://localhost:8000/optimize-energy" \
  -H "Content-Type: application/json" \
  --data-binary "@sample_request.json"
```

### Windows CMD

```cmd
curl -X POST "http://localhost:8000/optimize-energy" ^
  -H "Content-Type: application/json" ^
  --data-binary "@sample_request.json"
```

---

## 20. Response Example

A successful response has the following structure:

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
      "explanation": "Solar availability is reduced during the specified hours."
    },
    {
      "note_index": 1,
      "applies": true,
      "directive_type": "no_charge_window",
      "structured_adjustment": {
        "hours": [14, 15]
      },
      "explanation": "Battery charging is unavailable during the specified hours."
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
  "total_grid_kwh": 1234.56,
  "total_cost_bdt": 12345.67,
  "peak_grid_kwh": 250.0,
  "plan_summary": "The final schedule applies the validated operator directives and minimizes grid electricity cost while satisfying all energy and battery constraints."
}
```

The real response contains exactly 24 hourly plan entries.

---

## 21. Public Sample Testing

The repository contains the official public sample pack:

```text
BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json
```

The pack contains 10 public sample scenarios.

### Local API test

Start the local API:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Then:

```bash
export BASE_URL="http://localhost:8000"
python test_runner.py
```

On Windows PowerShell:

```powershell
$env:BASE_URL="http://localhost:8000"
python test_runner.py
```

### Live Render test

```bash
export BASE_URL="https://gridwise-llm-optimizer-mpgg.onrender.com"
python test_runner.py
```

The public validation suite currently passes:

```text
FINAL RESULT: 10/10 passed
```

Equivalent valid optimal schedules are accepted; the hourly action sequence does not need to match one reference schedule byte-for-byte.

---

## 22. LLM Debugging

For development-only interpretation testing:

```bash
python debug_llm.py
```

This script is not part of the production API path.

Avoid repeatedly running the debugging script against a rate-limited hosted LLM immediately before the full public test suite.

---

## 23. Docker

### Dockerfile

The container uses Python 3.11 and runs Uvicorn on port `8000`.

### Build

```bash
docker build -t gridwise-llm:1.0.0 .
```

### Run

First configure environment variables:

```bash
export OPENAI_API_KEY="YOUR_GROQ_API_KEY"
export GROQ_MODEL="qwen/qwen3.8-27b"
export LLM_TIMEOUT_SECONDS="15"
export LLM_MAX_OUTPUT_TOKENS="300"
export LLM_MAX_ATTEMPTS="3"
```

Then:

```bash
docker run --rm -p 8000:8000 \
  -e OPENAI_API_KEY \
  -e GROQ_MODEL \
  -e LLM_TIMEOUT_SECONDS \
  -e LLM_MAX_OUTPUT_TOKENS \
  -e LLM_MAX_ATTEMPTS \
  gridwise-llm:1.0.0
```

### Docker health test

In another terminal:

```bash
curl http://localhost:8000/health
```

Expected:

```json
{
  "status": "ok"
}
```

### Docker public-sample test

With the container running:

```bash
export BASE_URL="http://localhost:8000"
python test_runner.py
```

The Dockerized application should pass the same validation suite as the local application.

---

## 24. Docker Fallback Image

### Image

```text
gridwise-llm:1.0.0
```

### Image digest

```text
gridwise-llm@sha256:155998ac692581867b516f7a158589d5e274024e7af86c381e5a0003a68a1ed6
```

### Local pull/run

```bash
docker pull gridwise-llm:1.0.0
```

For the final hackathon registry submission, use the registry-qualified reference after the image is pushed to Docker Hub or GHCR.

Example format:

```text
<REGISTRY_NAMESPACE>/gridwise-llm:1.0.0
```

or:

```text
<REGISTRY_NAMESPACE>/gridwise-llm@sha256:155998ac692581867b516f7a158589d5e274024e7af86c381e5a0003a68a1ed6
```

The actual registry namespace should be the Docker Hub or GHCR namespace used for the submission.

---

## 25. Render Deployment

The production deployment is hosted on Render.

### Build Command

```bash
pip install -r requirements.txt
```

### Start Command

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

### Required environment variables

```text
OPENAI_API_KEY
GROQ_MODEL
LLM_TIMEOUT_SECONDS
LLM_MAX_OUTPUT_TOKENS
LLM_MAX_ATTEMPTS
```

### Health Check Path

```text
/health
```

### Production URL

```text
https://gridwise-llm-optimizer-mpgg.onrender.com
```

---

## 26. Performance and Reliability

The challenge requires the API to remain reachable during evaluation and to process valid `POST /optimize-energy` requests within the allowed request timeout.

The main variable-latency component is the external LLM request.

The implementation therefore uses:

- bounded LLM output
- configurable LLM timeout
- limited attempts
- deterministic validation
- interpretation caching
- lightweight 24-hour linear optimization
- independent final validation

Production deployment should be tested using repeated requests rather than a single request.

---

## 27. Error Handling

The API uses controlled error handling.

### `200`

Successful health or optimization request.

### `400`

Malformed or structurally invalid request.

### `422`

Semantically invalid request rejected by request validation.

### `500`

Controlled internal service failure.

Raw stack traces and secret values are not intended to be returned in API responses.

---

## 28. Security

Never commit secrets.

Do not commit:

```text
.env
API keys
access tokens
passwords
private credentials
```

Do not place secrets in:

```text
README.md
source code
Dockerfile
Docker image
API responses
logs
```

Use environment variables for runtime credentials.

The repository contains `.env.example` only for documenting variable names and example placeholders.

---

## 29. Reproducibility

A fresh environment can reproduce the service with:

```bash
git clone <YOUR_REPOSITORY_URL>
cd gridwise-llm-optimizer
python -m venv venv
```

Activate the virtual environment and install dependencies:

```bash
pip install -r requirements.txt
```

Configure the documented environment variables.

Start:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Check:

```bash
curl http://localhost:8000/health
```

Run the public validation suite:

```bash
export BASE_URL="http://localhost:8000"
python test_runner.py
```

---

## 30. Design Philosophy

GridWise intentionally separates:

### Language understanding

```text
Human operator note
        ↓
LLM
        ↓
Structured directive
```

### Correctness and safety

```text
Structured directive
        ↓
Schema validation
        ↓
Deterministic guardrails
```

### Mathematical scheduling

```text
Validated directives
        ↓
Optimization constraints
        ↓
Valid low-cost schedule
```

### Final verification

```text
Generated schedule
        ↓
Independent replay/checks
        ↓
Final API response
```

The optimizer never receives an unvalidated natural-language instruction directly.

---

## 31. Key Implementation Decisions

### LLM-assisted directive extraction

The system uses a language-capable model to interpret operator notes so that paraphrased instructions can map to the same supported directive.

### Deterministic guardrails

The LLM is not trusted to enforce challenge constraints by itself. Structured output is checked before it influences optimization.

### Linear programming

The 24-hour scheduling problem is solved with SciPy's `linprog`, allowing the service to minimize grid cost while enforcing energy and battery constraints.

### Independent validation

The final plan is checked again after optimization to make sure the returned JSON itself satisfies the required rules.

### Caching

Repeated identical interpretation requests can reuse cached structured interpretation instead of unnecessarily calling the model again.

---

## 32. Known Limitations

### External LLM dependency

Operator-note interpretation depends on the configured LLM provider.

Provider-side limitations such as:

- API availability
- quota
- rate limits
- network failures

may affect request latency or availability.

### Fixed directive vocabulary

Only the challenge-defined directives are supported.

### 24-hour horizon

The optimizer is specifically designed for the 24-hour challenge horizon.

### Synthetic data

The implementation is designed for the supplied synthetic challenge scenarios and is not intended to represent every real-world campus energy system.

### No runtime training

The service does not require model training or fine-tuning during evaluation.

---

## 33. Challenge Compliance

The implementation is designed to comply with the GridWise preliminary requirements:

- `GET /health` endpoint
- `POST /optimize-energy` endpoint
- LLM-based `operator_notes` interpretation
- One interpretation entry per note
- Supported directive vocabulary
- Deterministic LLM-output validation
- Directive application before optimization
- Exactly 24 hourly plan entries
- Energy balance
- Solar availability constraints
- Battery capacity and reserve constraints
- Charge/discharge rate limits
- Directive-specific windows and grid caps
- End-of-day battery neutrality
- Recalculated grid usage, cost, and peak grid
- Controlled API errors
- Environment-based secret handling
- Docker fallback support
- Local public-sample validation

---

## 34. Final Verification Status

| Component | Status |
|---|---|
| GitHub repository | Ready |
| Render deployment | Live |
| Render `/health` | Working |
| Public sample suite | `10/10 passed` |
| Docker image build | Successful |
| Docker image | `gridwise-llm:1.0.0` |
| Docker image digest | `sha256:155998ac692581867b516f7a158589d5e274024e7af86c381e5a0003a68a1ed6` |
| Live API | `https://gridwise-llm-optimizer-mpgg.onrender.com` |

---

## 35. Quick Reference

### Run locally

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Health

```bash
curl http://localhost:8000/health
```

### Run local public tests

```bash
export BASE_URL="http://localhost:8000"
python test_runner.py
```

### Test Render

```bash
export BASE_URL="https://gridwise-llm-optimizer-mpgg.onrender.com"
python test_runner.py
```

### Build Docker

```bash
docker build -t gridwise-llm:1.0.0 .
```

### Run Docker

```bash
docker run --rm -p 8000:8000 \
  -e OPENAI_API_KEY \
  -e GROQ_MODEL \
  -e LLM_TIMEOUT_SECONDS \
  -e LLM_MAX_OUTPUT_TOKENS \
  -e LLM_MAX_ATTEMPTS \
  gridwise-llm:1.0.0
```

### Live API

```text
https://gridwise-llm-optimizer-mpgg.onrender.com
```

---

## 36. Submission Checklist

Before final submission, verify:

```text
[ ] GET /health returns {"status":"ok"}
[ ] POST /optimize-energy returns the exact response schema
[ ] Render endpoint is reachable from outside the development machine
[ ] Public sample suite passes
[ ] Repeated requests remain stable
[ ] No API key is committed to the repository
[ ] No secrets are baked into the Docker image
[ ] Docker image can be pulled and started
[ ] README contains setup instructions
[ ] README contains environment-variable names
[ ] README identifies LLM provider/model
[ ] README explains LLM role
[ ] README explains deterministic guardrails
[ ] README explains optimizer/solver
[ ] README contains API examples
[ ] README contains public-sample test commands
[ ] README contains Docker fallback instructions
[ ] README contains dependencies and limitations
[ ] 3-minute solution video is prepared
[ ] GitHub repository visibility follows the official event rule
```

---

## 37. Final Summary

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

to transform natural-language campus operating instructions into a valid and cost-efficient 24-hour energy schedule.

Final execution path:

```text
Operator Notes
      ↓
Qwen 3.8 27B
      ↓
Structured Directives
      ↓
Deterministic Guardrails
      ↓
SciPy Linear Programming
      ↓
24-Hour Energy Schedule
      ↓
Independent Validation
      ↓
Final JSON API Response
```

### Live API

```text
https://gridwise-llm-optimizer-mpgg.onrender.com
```

### Docker image digest

```text
gridwise-llm@sha256:155998ac692581867b516f7a158589d5e274024e7af86c381e5a0003a68a1ed6
```

---

## 38. Credits and External Technologies

The implementation uses publicly available software libraries, frameworks, SDKs, and APIs including:

- Python
- FastAPI
- Pydantic
- NumPy
- SciPy
- Uvicorn
- Requests
- OpenAI-compatible Python SDK
- Groq API
- Qwen 3.8 27B
- Docker
- Render

These technologies are used as implementation dependencies; the GridWise application logic, directive handling, validation flow, and optimization pipeline are implemented for this challenge.
