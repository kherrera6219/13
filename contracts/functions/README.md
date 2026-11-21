# Function I/O schemas

One pair per bound function, named per DLE-STD-001: `k01.in.json`, `k01.out.json` … `p14.in.json`, `p14.out.json` (JSON Schema 2020-12, snake_case fields).

Each pair is written in the same PR that implements the function, in the phase listed in documentation set §2 ("Function bindings by phase"), and its SHA-256 becomes part of the binding record checked by the adapter gate (FR-FN-05). `dle.tools.validate_contracts` fails if `config/functions.yaml` names a runtime function whose schema pair is missing once its phase has started.
