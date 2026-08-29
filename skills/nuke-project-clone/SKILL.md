---
name: nuke-project-clone
description: "Trigger: clonar proyecto nuke, clonar comp, clonar .nk, clonar Nuke, create nuke comp from template, clone nuke project, png/jpg referencia. Clone the HTLR SAMAN Nuke comp template for a new shot/episode with frame-1 reads, clip-matched formats, dynamic relative paths, and 720p reference JPGs."
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
- The `.nk` filename drives the Write Tcl expressions: name it `HTLR_{EP}_{escena}_{shot}_comp_SAMAN_V{nn}.nk` inside `COMP/EP_{EP}/{escena}_{shot}_comp_SAMAN/`. `comp_SAMAN` es el sufijo de EMPRESA (no el artista); todo comp del estudio lo lleva.
- Every plate generates a 720p reference JPG (q2, ~110KB) from frame 1 into `TO_VFX/EP_{EP}/{fecha}/PNG/`, named like the mov basename WITHOUT the `_V{nn}` token (case-insensitive). Examples: `HTLR_107_012_01500_V01.mov` -> `HTLR_107_012_01500.jpg`; `HTLR_108_028_V01_0100.mov` -> `HTLR_108_028_0100.jpg`. Resolution 1280x720, pad to preserve aspect. Use JPG `-q:v 2`: PNG lossless is ~10x heavier with no review benefit.
- Validate plate names BEFORE cloning: the version token `_V{nn}` (case-insensitive) MUST sit at the END of the basename (`HTLR_{EP}_{escena}_{shot}_V{nn}.mov`). If a client file has it elsewhere (e.g. `HTLR_108_034_V01_0100.mov`), STOP and ask the user whether to rename it to the convention (`HTLR_108_034_0100_V01.mov`) before creating projects. Never rename silently.

## Decision Gates

| Clip resolution | Nuke format |
|---|---|
| 3840 x 2160 | `"3840 2160 0 0 3840 2160 1 UHD_4K"` |
| 4096 x 2160 | `"4096 2160 0 0 4096 2160 1 4K_DCP"` |

| Plate filename | Valid? | Correction |
|---|---|---|
| `HTLR_107_008_00100_V01.mov` | Yes | — |
| `HTLR_108_034_V01_0100.mov` | No (`_V01` mid-name) | `HTLR_108_034_0100_V01.mov` |

If the source plate has audio (WAV next to the mov), re-add the AudioRead with a dynamic path (the cleaned template removed it).

## Execution Steps

1. List the plate files and validate each name against `HTLR_{EP}_{escena}_{shot}_V{nn}.mov`. For any file whose `_V{nn}` token is NOT at the end, present the correction choice to the user (rename to convention / keep as-is) and WAIT for the answer; rename only with explicit consent, then use the corrected names everywhere (Read, PNG, .nk).
2. Copy the base template (`COMP/EP_100/HTLR_100_000_00000_comp_SAMAN_V01.nk`) into the new shot folder and rename to the convention above.
3. Probe the clip: `ffprobe -v error -select_streams v:0 -show_entries stream=width,height,nb_frames -of csv=p=0 clip.mov`.
4. Generate the reference JPG (frame 1, 720p q2, name without `_V{nn}`):
   `ffmpeg -y -v error -i <clip>.mov -frames:v 1 -q:v 2 -vf "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2" "TO_VFX/EP_{EP}/{fecha}/PNG/<name>.jpg"`
5. In Nuke, Save As to fix `Root.name`, then set Root format, `fps 23.976`, `lock_range true`, `last_frame` = clip frames.
6. On the Read: set `file` to `[python {PYTHON_TO_VFX}]/EP_{EP}/{fecha}/<clip>.mov`, format = clip resolution, `first 1`, `last`/`origlast` = clip frames, colorspace `DaVinci Intermediate WideGamut`, `mov64_prraw_plugin Standard`.
7. Fix every Write: `first 1`, `last` = clip frames, verify Tcl name derivation matches the new filename.
8. Clean leftover viewer names (e.g., `DPCP_EP_101_0042_comp_DGTV_V001`).
9. Save, reopen isolated, render one proof frame.

## Output Contract

Return the cloned `.nk` path, the clip resolution + frames used, the format chosen, the generated JPG path, the naming validation outcome (renamed vs kept as-is), and confirmation that all Reads/Writes have `first 1` and no absolute paths remain (`grep -E 'PYTHON_|first|last|format' *.nk`).

## References

- `/Volumes/wupm/2026/HTLR/COMP/EP_100/PRACTICAS_CLONADO_NUKE.md` — full practice guide and EP_108 clip table.
- `/Volumes/wupm/2026/HTLR/COMP/EP_100/HTLR_100_000_00000_comp_SAMAN_V01.nk` — base template file.