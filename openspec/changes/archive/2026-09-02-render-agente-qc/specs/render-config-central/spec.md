# Delta for render-config-central

## MODIFIED Requirements

### Requirement: Schema integrity validation

ID: RC-CN-02 · Layer: Must

The load MUST validate the schema before use: top-level `bases_por_so` (mapping OS→path), `workers` (list), `sufijos` (mapping); each worker MUST have `nombre`, `ssh` (host or None), `ssh_user`, `nuke_exec`, `base`, `lc_all`. When present, top-level `proyectos` (project enablement, additive) MUST be a mapping whose values are booleans; its absence MUST NOT fail validation so legacy configs keep loading. Validation MUST accumulate ALL missing keys and type errors into one `SystemExit` listing each failure with repair guidance.
(Previously: schema validated only `bases_por_so`, `workers`, `sufijos`; `proyectos` did not exist)

#### Scenario: Multiple missing keys

- GIVEN JSON missing `workers` and worker lacking `nuke_exec`
- WHEN config loaded
- THEN one `SystemExit` lists both failures
- AND names each key path

#### Scenario: Wrong type

- GIVEN `bases_por_so` as a list instead of a mapping
- WHEN config loaded
- THEN `SystemExit` states the expected type

#### Scenario: Invalid proyectos entry

- GIVEN `proyectos` whose value for `PCF` is a string instead of a boolean
- WHEN config loaded
- THEN `SystemExit` states the expected boolean type

#### Scenario: Proyectos absent is valid

- GIVEN a legacy config without `proyectos`
- WHEN config loaded
- THEN validation passes; `proyectos` resolves to empty

### Requirement: Public template, docs, tests, sanitized commit

ID: RC-CN-05 · Layer: Must

The change MUST ship `studio_config.example.json` (no real data, schema-conformant, passing loader validation) and a README documenting pattern, real config location, ACL (admin WRITE + worker READ on `{base}/.saman/studio_config.json` via the workers' `ssh_user`, D8; fallback: a node that cannot read the JSON holds the complete `RENDER_LOCAL_CONFIG` in `config_local.py`) and creation steps. Template and README MUST use hostnames/DNS (e.g. `vfxserver`, `macserver.studio.local`) for hosts; IPs MAY appear only as fallback; the public template MUST NOT contain IP literals. Tests MUST run without Nuke via the existing stub, covering env base override, local precedence, strict abort, missing keys, wrong type, translation per OS combination, example validation. `render_distribuido/` MUST be committed sanitized: no real IPs, users or hosts tracked. Semantic roles (PLATE, DELIVERY, PREVIEW, SBS) MUST stay fixed in code as the stable domain; the physical folder layout is NOT fixed — each project declares its own relative layout patterns as DATA, resolved from `bases_por_so` plus enabled `proyectos`, and `test_no_fuga` MUST prove the layout data contains no absolute paths, IP literals or `@`-user tokens. Sanitizing versioned gizmos/skills is out of scope.
(Previously: domain conventions (PLATE, DELIVERY_EXR, `_comp_SAMAN_`, suffix names) stayed hardcoded as the fixed domain; layouts were not per-project data)

#### Scenario: Example validates

- GIVEN `studio_config.example.json` including a `proyectos` map
- WHEN validated through the strict loader
- THEN no `SystemExit` is raised

#### Scenario: Sanitized commit

- GIVEN the commit adding layout data
- WHEN tracked files are searched for `192.168` or `@`
- THEN zero matches

#### Scenario: No IPs in public template

- GIVEN `studio_config.example.json`
- WHEN scanned for IP literals
- THEN zero matches; worker hosts are hostnames

#### Scenario: ACL documented

- GIVEN the README
- WHEN read
- THEN it states admin WRITE + worker READ (workers' `ssh_user`) on `{base}/.saman/studio_config.json` — D8, infra not secret
- AND it documents the complete `RENDER_LOCAL_CONFIG` fallback for nodes that cannot read the JSON

#### Scenario: Layout data is relative

- GIVEN the per-project layout patterns
- WHEN scanned for absolute roots, IP literals or `@`+letter tokens
- THEN zero matches (`test_no_fuga` green)