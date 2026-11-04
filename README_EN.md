# DataPilot

[中文文档](README.md) · [Architecture](docs/architecture.md) · [Changelog](CHANGELOG.md)

A local, explainable sales analytics agent powered by Python and DeepSeek. Ask questions, inspect tool evidence and read-only SQL, generate charts, and export reports.

![Workspace](docs/screenshots/workspace.png)

## What is implemented

- Eleven schema-validated tools covering sales totals, products, dates, rankings, charts, schema discovery, business metrics and read-only SQL.
- Versioned metric definitions in `semantic/metrics.json`; weighted price is explicitly different from the simple average of prices.
- A bounded multi-step tool loop, complete-turn context management, error recovery and request telemetry.
- SQLite-backed web sessions with dataset, conversation and evidence restoration across restarts.
- A local web UI with CSV upload, history selection, SQL/result inspection, metric definitions, Markdown/CSV/PNG export and an explicitly labeled offline rules demo.
- Automated tests, fixed evaluation datasets, a data-size benchmark and Docker/CI configuration.

The design learns from DB-GPT's execution layering and WrenAI's semantic-context approach. It is independently implemented for a narrow sales-data use case, not a reimplementation of either platform.

## Run

Use Python 3.12, create a virtual environment and install `requirements-lock.txt`. Copy `.env.example` to `.env` and optionally configure a DeepSeek API key. Run:

```sh
python app.py
```

Open http://127.0.0.1:8765. Offline demo is the default and needs no model key; real model analysis is selected explicitly in the UI. Sessions are stored under `outputs/`, excluded from Git.

```sh
python -m unittest discover -v
python -m evals.run_eval --mode demo
python -m evals.run_eval --mode live --cases evals/sql_cases.json
python -m evals.benchmark_data
```

With Docker installed and a local `.env`, use `docker compose up --build`. The host port is bound to loopback; a named volume stores runtime data.

## Boundaries and evidence

This is a single-user local project, not a public multi-tenant service. SQL uses a separate in-memory `sales` table, an authorizer and function allowlist, row/time limits and no external-file access. This is not an arbitrary-code sandbox. Data must follow the documented sales CSV contract; currency and independent order identity are not inferred.

See [evaluation records](docs/evaluation.md) for actual results and limitations. Offline rules scores, unit tests and live model evaluation are different forms of evidence. Small fixed-dataset results do not establish production accuracy. Model requests in live mode send questions, necessary history and tool evidence to the configured provider.

The repository is private during development. Runtime datasets, state databases, keys, virtual environments and generated output directories are excluded from version control.
