# API composition root

Stage 1 runs the API through `ctrl-api`, which composes FastAPI, PostgreSQL, private object
storage, parsers, domain policies, and the XLSX exporter. This directory is reserved for future
process-specific deployment assets; reusable runtime code remains under `src/ctrl_v2`.
