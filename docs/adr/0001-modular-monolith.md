# ADR-0001: Go-owned modular monolith + Python ML scoring process

Status: Accepted for starter kit (validate during implementation).

Context: competition has two-day delivery window; user explicitly requires Go Uber Fx, Zap, well-documented layered architecture and already installed Graphify. ML experimentation needs scikit-learn. Judges favor testability, clarity and actual performance.

Decision: Go owns HTTP API, rule interpreter, conflict/policy engine and orchestrator. Python holds offline training and internal inference. Streamlit only presentation. JSON/HTTP interface under loopback for local demonstration; process boundary isolates Python ML but adds availability dependency.

Alternatives rejected: all-Python (violates Go constraint), gRPC for two small local processes (unnecessary codegen), event-driven microservices (too costly), Go model reimplementation (duplicates Python model and risks feature mismatch).

Consequences: Go->Python readiness, timeouts and typed errors essential; no implicit score fallback. Document contract version. Need reproducible setup script. Avoid database; report artifacts stored as files.
