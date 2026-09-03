---
name: render-red
description: "Trigger: render en red, renderizar en red, render distribuido, render farm, renderizar plano, renderizar carpeta completa, DELIVERY_EXR, reparto de frames, calibracion de render, render asistido, seleccion por mtime, validar plate, gate QC. Renderiza comps de Nuke distribuido entre multiples maquinas (macOS/Linux/Windows) con reparto inteligente basado en calibracion real y gate QC pre-render."
license: Apache-2.0
metadata:
  author: "emanuelbarriga"
  version: "2.0"
---

# Render en red (render distribuido)

## Activation Contract

Render Nuke comps across the studio machines, split frames, or the assisted
flow ("renderiza los planos del Capitulo 7"): project layout, mtime selection,
multi-node, QC gate. Semantic roles PLATE/DELIVERY/PREVIEW/SBS are fixed; the
physical layout is per-project relative data (HTLR `EP_n`, IPYD `101..106`
with `YYYYMMDD[-N]`, PCF `PFC_SC##`); comps `*_comp_SAMAN*.nk`, delivery Write
`DELIVERY_EXR`. Range comes from the `PLATE` Read.

## Hard Rules

- **Never version the real config.** Infra (workers, bases, suffixes, enabled
  `proyectos`) comes from `{base}/.saman/studio_config.json`; only
  `studio_config.example.json` (fictional) is public; `RENDER_LOCAL_CONFIG`
  (gitignored) may override.
- **Strict policy, no silent defaults.** Missing config aborts with guidance;
  folder without qualifying `.nk` or missing plate aborts NAMING the path.
- **Semantic roles fixed; layout = data.** Roles are domain contract; physical
  patterns are per-project relative DATA (`bases_por_so` + enabled `proyectos`):
  no absolute roots, IPs or user-host tokens.
- **Selection by real mtime on the orchestrator (iMac), never workers**
  (LucidLink collapses ctime/birthtime); `_V\d+` is tie-break/suspect only.
- **QC gate "Regla de Oro" ON in assisted flow**: plate deep-probed (ffprobe)
  vs Root/delivery template; discrepancies abort unless an override resolves
  them.
- **Never lose finished work.** Policy `keep` by default: missing + corrupt
  frames only; replacing valid frames needs explicit `replace`.
- **ACL (D8):** config is admin-WRITE + worker-READ; unreadable node holds
  complete `RENDER_LOCAL_CONFIG`.

## Decision Gates

| Situation | Action |
|---|---|
| Assisted run | `--proyecto` (default HTLR, notice) + `--comp-dir` (folder or intent, remapped) |
| Pick the comp | Real mtime wins; `sospechosa` if mtime beats higher `_V` → `--resolve-latest` / `--use-version V015` |
| Confirm batch | `[Confirmar]` / `[Ver lista y desmarcar]`; `--resolve-latest` skips |
| Multi-node | `--wnodes` real names; EXR per frame, MOV per file; CALIB/PLAN only DELIVERY_EXR; previews piggyback; `--force-exr` |
| QC discrepancies | Report `TEST_RENDER/qc_*.json` + `__DECISION__`, exit 3 → ask, re-invoke with override |
| QC overrides | `--force-qc` · `--plate-date` · `--validar-solo-duracion` · `--fps-forzar` |
| Legacy run (`--comp` only) | No layout/gate: previous behavior intact |
| Store down / config missing | Abort with explicit diagnosis |
| Corrupt EXR present | Repair those frames or replace-all on confirmation |

## Execution Steps

1. Ensure `{base}/.saman/studio_config.json` exists and is valid (example →
   real workers/bases/suffixes/`proyectos`; ACL).
2. Assisted run:
   ```
   python3 render_distribuido/render_distribuido.py \
       --proyecto HTLR --comp-dir "Capitulo 7" --resolve-latest \
       --wnodes DELIVERY_EXR,REVIEW_REC709
   ```
   Flow: selection → PROBE → QC gate (report, abort or rewrite delivery) →
   EXISTENTES → POLICY → CALIB → PLAN → RENDER.
3. Legacy: `--comp <rel> --wnode DELIVERY_EXR --auto-range --from-suf ...`.
4. Review PLAN/policy; confirm before production writes if uncertain.
5. Verify count + RESUMEN (planned vs real) in `render_distribuido.log`.

## Output Contract

Return: machine split, estimated vs real time, policy applied,
missing/replaced/corrupt counts, output destination, QC summary (plate probed,
discrepancies, report path, exit code). **Exit 3 = needs a decision**: surface
the `__DECISION__` JSON and re-invoke with the override. Never report a
calibration/PLAN as a finished render.

## References

- `render_distribuido/README.md` — config, ACL, layouts, full flag table, QC
  flow, exit codes, sad paths (authority for details).
- `render_distribuido/studio_config.example.json` — public schema template.
- `render_distribuido/layouts.py` — per-project relative layouts, mtime.
- `render_distribuido/plate_qc.py` — ffprobe plate, comparison, decisions.
- `render_distribuido/render_config.py` — strict loader, validation.
- `render_distribuido/render_distribuido.py` — orchestrator (assisted/legacy).
- `render_distribuido/render_worker.py` — per-machine worker.