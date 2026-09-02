---
name: render-red
description: "Trigger: render en red, renderizar en red, render distribuido, render farm, renderizar plano, renderizar carpeta completa, DELIVERY_EXR, reparto de frames, calibracion de render. Renderiza comps de Nuke distribuido entre multiples maquinas (macOS/Linux/Windows) con reparto inteligente basado en calibracion real."
license: Apache-2.0
metadata:
  author: "emanuelbarriga"
  version: "1.0"
---

# Render en red (render distribuido)

## Activation Contract

Load when asked to render a Nuke comp (or all comps of a folder) across the
studio render machines, or to decide how to split frames between machines.
The flow expects the studio conventions: comps named `*_comp_SAMAN_V*.nk`,
delivery write `DELIVERY_EXR`, and range defined by the Read connected to the
`PLATE` stamp.

## Hard Rules

- **Never version the real config.** The orchestrator reads infrastructure
  (workers, bases per OS, suffixes) from `{base}/.saman/studio_config.json`
  — never from code. Only `studio_config.example.json` (fictional values) is
  public. `RENDER_LOCAL_CONFIG` in `config_local.py` (gitignored) may override.
- **Strict policy, no silent defaults.** Missing config aborts with guidance
  (copy the example). Distinguish missing-file (`FileNotFoundError`) from
  mount/network failure (`OSError`/timeout): never suggest copying the
  template when LucidLink is down.
- **Conventions are fixed, not configurable.** `PLATE`, `DELIVERY_EXR`,
  `_comp_SAMAN_*` are domain contract, not settings.
- **Never lose finished work.** Default policy is `keep`: render only missing
  frames + repaired corrupt ones; replacing existing valid frames requires the
  user's explicit `replace` decision.
- **ACL (D8):** `.saman/studio_config.json` is admin-WRITE + worker-READ
  (the `ssh_user`s of the workers). If a node cannot read it, distribute a
  complete `RENDER_LOCAL_CONFIG` there.

## Decision Gates

| Situation | Action |
|---|---|
| Render one comp | `render_distribuido.py --comp <rel> --wnode DELIVERY_EXR --auto-range` |
| Render everything still missing in the destination | Policy `keep` (default): only missing + corrupt frames are rendered |
| Calibrate before distributing | The flow always calibrates: probe → existing frames → policy → stratified calibration → plan → render |
| Store down / config missing | Abort with explicit diagnosis (do NOT degrade silently) |
| Corrupt EXR present | Repair only those frames (corruptos policy) or replace-all on user confirmation |

## Execution Steps

1. Ensure `{base}/.saman/studio_config.json` exists and is valid (copy the
   example, fill real workers/bases/suffixes; verify ACL in LucidLink).
2. Run the orchestrator from the shared repo:
   ```
   python3 render_distribuido/render_distribuido.py \
       --comp "HTLR/COMP/EP_xxx/..._comp_SAMAN_V05.nk" \
       --wnode DELIVERY_EXR --auto-range --from-suf /HTLR/FROM_VFX/
   ```
   (`--auto-range` uses the PLATE Read's first/last as the project range.)
3. Review the printed **PLAN** (frames per machine, estimated time) and the
   policy decision; confirm before production writes if anything is uncertain.
4. The flow: PROBE (detect PLATE range + output template) → EXISTING frames
   (header check; optional `--check-exr` deep validation with Nuke) → POLICY
   (ask once: keep/replace/corruptos) → CALIB (per machine: startup, load,
   stratified per-frame, official `-P` profiling; isolated
   `TEST_RENDER/calib_<worker>` so production is never touched) → PLAN
   (minimize `startup + load + per_frame×n`) → RENDER (disjoint frame lists
   via `nuke.execute`, env passed explicitly over SSH).
5. Verify output count and the final RESUMEN (planned vs real) in
   `render_distribuido.log`.

## Output Contract

Return: the machine split (frames per worker), estimated vs real time, policy
applied, count of missing/replaced/corrupt frames, destination of the output,
and any failure diagnosis (mount vs missing config). Never report a
calibration/PLAN as a finished render.

## References

- `render_distribuido/README.md` — config location, ACL, how to create `studio_config.json`.
- `render_distribuido/studio_config.example.json` — public schema template.
- `render_distribuido/render_config.py` — strict loader, schema validation, `traducir_ruta`.
- `render_distribuido/render_distribuido.py` — orchestrator (probe/calib/plan/render).
- `render_distribuido/render_worker.py` — per-machine worker (env-only suffixes).