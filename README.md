# Competitive Intel Agents

AI-powered competitive analysis multi-agent collaboration system.

## Core Features

- **Multi-Agent Collaboration**: Collection → Analysis → Writing → Quality Review, DAG-based task orchestration
- **Full Traceability**: Every analysis conclusion is traceable back to its source data and agent decision chain
- **Observability**: Per-agent behavior monitoring — stall detection, hallucination tripwire, circuit breaker
- **Feedback Loop**: Quality review rejects trigger automatic rework with context injection

## Architecture

```
User Input → Orchestrator (Task Decomposition + DAG)
                │
    ┌───────────┼───────────┐
    ▼           ▼           ▼
Collector    Analyst     Writer
 Agent       Agent       Agent
    │           │           │
    └───────────┼───────────┘
                ▼
         Quality Reviewer
                │
        ┌───────┴───────┐
        ▼               ▼
     Approve         Reject → Auto Rework
        │
        ▼
   Structured Report Output
```

## Tech Stack (TBD)

- Backend: Python / Go
- Agent Runtime: Custom (inspired by Astra engine)
- LLM: Anthropic / OpenAI API
- Storage: PostgreSQL / SQLite

## Project Status

Early development.
