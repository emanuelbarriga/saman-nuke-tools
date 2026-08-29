---
name: nuke-project-clone
description: "Trigger: clonar proyecto nuke, clonar comp, clonar .nk, clonar Nuke, create nuke comp from template, clone nuke project. Clone the HTLR SAMAN Nuke comp template for a new shot/episode with frame-1 reads, clip-matched formats, and dynamic relative paths."
license: Apache-2.0
metadata:
  author: "emanuel"
  version: "1.0"
---

# Nuke Project Clone

## Activation Contract

Load when asked to clone, duplicate, or create a Nuke comp from an existing template, especially HTLR `*_comp_SAMAN_*.nk` files or the EP_100 base.

## Hard Rules

- Read frame MUST start at 1: set `first 1` on every Read and Write, plus matching `last`/`origlast` and `origset true`.
- Project format AND Read format MUST match the actual clip resolution. Detect with ffprobe; use `UHD_4K` for 3840x2160 and `4K_DCP` for 4096x2160. Never inherit the template format blindly.
- Keep dynamic relative paths: `[python {PYTHON_TO_VFX}]/...`, `[python {PYTHON_COMP}]/...`, `[python {PYTHON_FROM_VFX}]/...`. NEVER absolute paths. Variables come from the `RUTAS2` node.
- The `.nk` filename drives the Write Tcl expressions: name it `HTLR_{EP}_{escena}_{shot}_comp_{artista}_V{nn}.nk` inside `COMP/EP_{EP}/{escena}_{shot}_comp_{artista}/`.

## Decision Gates

| Clip resolution | Nuke format |
|---|---|
| 3840 x 2160 | `"3840 2160 0 0 3840 2160 1 UHD_4K"` |
| 4096 x 2160 | `"4096 2160 0 0 4096 2160 1 4K_DCP"` |

If the source plate has audio (WAV next to the mov), re-add the AudioRead with a dynamic path (the cleaned template removed it).

## Execution Steps

1. Copy the base template (`COMP/EP_100/HTLR_100_000_00000_comp_SAMAN_V01.nk`) into the new shot folder and rename to the convention above.
2. Probe the clip: `ffprobe -v error -select_streams v:0 -show_entries stream=width,height,nb_frames -of csv=p=0 clip.mov`.
3. In Nuke, Save As to fix `Root.name`, then set Root format, `fps 23.976`, `lock_range true`, `last_frame` = clip frames.
4. On the Read: set `file` to `[python {PYTHON_TO_VFX}]/EP_{EP}/{fecha}/<clip>.mov`, format = clip resolution, `first 1`, `last`/`origlast` = clip frames, colorspace `DaVinci Intermediate WideGamut`, `mov64_prraw_plugin Standard`.
5. Fix every Write: `first 1`, `last` = clip frames, verify Tcl name derivation matches the new filename.
6. Clean leftover viewer names (e.g., `DPCP_EP_101_0042_comp_DGTV_V001`).
7. Save, reopen isolated, render one proof frame.

## Output Contract

Return the cloned `.nk` path, the clip resolution + frames used, the format chosen, and confirmation that all Reads/Writes have `first 1` and no absolute paths remain (`grep -E 'PYTHON_|first|last|format' *.nk`).

## References

- `/Volumes/wupm/2026/HTLR/COMP/EP_100/PRACTICAS_CLONADO_NUKE.md` — full practice guide and EP_108 clip table.
- `/Volumes/wupm/2026/HTLR/COMP/EP_100/HTLR_100_000_00000_comp_SAMAN_V01.nk` — base template file.