---
name: nuke-project-clone
description: "Trigger: clonar proyecto nuke, clonar comp, clonar .nk, clonar Nuke, create nuke comp from template, clone nuke project, png/jpg referencia, me llegaron planos, nuevos planos, ingesta planos, codificar planos firebase, crear shots firebase, CSV breakdown, notas de planos, link de frame, frame.io. Ingesta completa de capítulo: lee la carpeta de planos, parsea el CSV de breakdown, codifica los shots en Firestore (vfxFlow), sube las imágenes de referencia a Storage, crea los comentarios por plano en shotActivity, y luego clona las comps SAMAN de Nuke."
license: Apache-2.0
metadata:
  author: "emanuel"
  version: "2.0"
---

# Nuke Project Clone + Firebase Ingesta (HTLR → vfxFlow)

Flujo de dos etapas cuando llegan planos nuevos de un capítulo:
1. **Ingesta vfxFlow**: codificar planos en Firestore, subir imágenes de referencia, crear comentarios por plano con las notas del CSV.
2. **Clonado Nuke**: el flujo actual de comps SAMAN (read frame 1, formatos, rutas dinámicas, JPGs 720p).

## Activation Contract

Load when the user says planos arrived ("me llegaron planos de X carpeta"), or asks to clone/create Nuke comps, or to ingest/codify shots into vfxFlow, or to process a breakdown CSV. Trigger includes firebase/shot/CSV ingesta language.

## REGLA DE ORO — VFXFlow es SOLO CONSULTA

- El repositorio `/Volumes/wupm/2026/VFXFlow` (app React + Firebase vfxpm-be912) es **SOLO CONSULTA**. NUNCA escribir, ejecutar ni generar scripts dentro de él, ni modificar sus reglas, índices, skills o archivos.
- Se consulta únicamente como referencia de tipos y estructura real: `skills/vfxflow-data-auth/references/data-map.md`, `src/types/models.ts`, `src/lib/firebase.ts` (config pública), `src/components/project/ShotFormDialog.tsx`, `src/components/project/ShotDetailsPanel.tsx`, `src/components/project/BulkReferenceImageUpload.tsx`.
- Si la tarea requiere inspeccionar datos reales de Firestore, usar la REST API con el token OAuth de la CLI de Firebase (ya logueado). **NUNCA** crear un script dentro de VFXFlow.
- No tocar `firestore.rules` de producción ni desplegar reglas desde ningún lado.

## Etapa 1 — Ingesta vfxFlow

### 1.1 Leer la estructura de la carpeta de planos

- Listar los `.mov` de `TO_VFX/EP_{EP}/{fecha}/`. Validar cada nombre contra `HTLR_{EP}_{escena}_{shot}_V{nn}.mov` (el token `_V{nn}` al FINAL del basename). Nunca renombrar archivos sin consentimiento explícito.
- Decodificar cada plano: `HTLR_101_0012_0100` → projectCode `HTLR`, chapterCode `HTLR_101`, escena/sequence `0012`, shot code `0012_0100`. En la plataforma vfxFlow: `Shot.code = "0012_0100"` (sin prefijo de proyecto/capítulo), `projectId` = documento del proyecto con `code == "HTLR"`, `chapterId` = documento del capítulo con `title == "HTLR_101"`.

### 1.2 Parsear el CSV de breakdown

- Ubicar el CSV `HTLR_VFX_Breakdown.xlsx - CAP_{EP}_{CODIGO}.csv` en la misma carpeta de planos.
- Columnas reales (verificar en el archivo concreto; no asumir orden): `Name`, `Notes`, `Reference`, `Frames`, `LINK FRAME IO REF`, `Estatus`, `FECHA DE ENVIO A VFX`, `FECHA DE ENTREGA`, ...
- Por cada fila con `Name`: `notes` = columna Notes, `linkFrame` = columna LINK FRAME IO REF (URLs `https://f.io/...`), `frames` = columna Frames (entero), `estatus` = columna Estatus.

### 1.3 Revisión de patrón IA (MANDATORY — no asumir ciegamente)

**El cliente a veces marca mal el CSV.** Antes de escribir CUALQUIER cosa en Firestore, la IA debe:
1. Leer el CSV completo y deducir el patrón real de secuencias: agrupar los `Name` por escena (prefijo `HTLR_101_XXXX_`).
2. Detectar dónde caen los links de frame: normalmente el link aparece SOLO en el primer plano de una secuencia (`.0100`) y debe **replicarse a los demás planos de esa secuencia**. Verificar que esto se cumpla en el CSV concreto; si hay anomalías (links en otros planos, secuencias sin link, filas vacías, estatus CANCELADO), documentarlas.
3. Decidir el mapeo de estatus → `Shot.status` (`ENVIADO A VFX` → `received`; `CANCELADO` → NO crear el shot, solo reportarlo; otros valores → preguntar).
4. Presentar al usuario un resumen del patrón detectado y los casos que no encajan, y **ESPERAR confirmación** antes de escribir. Nunca escribir sin esa confirmación (Lossless Blocking Prompts si hay opciones).

### 1.4 Descubrir IDs Firebase (REST API + token CLI)

- Base de Firestore REST: `https://firestore.googleapis.com/v1/projects/vfxpm-be912/databases/(default)/documents`
- Obtener token: leer `~/.config/configstore/firebase-tools.json` → `tokens.access_token`. Si 401: pedir `firebase login --reauth` y releer. Header: `Authorization: Bearer <token>`.
- Descubrir `projectId`: listar `projects` (PATCH no; `GET .../projects?pageSize=300`) y filtrar por `code == "HTLR"`.
- Descubrir `chapterId`: bajo ese proyecto, listar `chapters` y filtrar por `title == "HTLR_101"` (el título del capítulo en la plataforma es `HTLR_{EP}`, p. ej. "HTLR_101"). Si no existe, STOP y preguntar (¿crear capítulo?).
- Descubrir `stateId`: listar `projectStates` del proyecto y tomar el documento con `stateType == "received"` (o el que la estructura real del proyecto use para planos recibidos; ver `ProjectState.stateType`). Si no hay, dejar el campo fuera y reportarlo.
- Descubrir `userId` (autor de los comentarios): del token OAuth se obtiene la cuenta autenticada; buscar `users` por ese email para obtener `id`, `name`, `avatarUrl`. Si no se encuentra el usuario en la colección `users`, STOP y pedir el UID/autor.
- Listar los shots EXISTENTES del capítulo (`GET .../chapters/{chapterId}/shots?pageSize=300`) y observar: (a) si los IDs de documento son autogenerados o derivados del código, (b) qué campos reales traen (`code`, `status`, `stateId`, `referenceImages`, `thumbnailUrl`, `Attachments`, `Archivos`, timestamps). **Replicar ese esquema real**, no el teórico.

### 1.5 Codificar los shots en Firestore

Para cada plano del CSV con estatus activo, en orden de secuencia:
1. **Idempotencia**: comprobar si ya existe un shot con ese `code` en el capítulo (filtrar el listado de 1.4). Si existe → NO crear duplicado: actualizar solo lo que falte (imágenes/comentarios) y reportarlo.
2. Crear el documento con `documentId` replicando el patrón de IDs real observado (si el patrón es autogenerado, usar `PATCH .../shots?documentId=` con un ID nuevo tipo uuid o dejar que Firebase lo genere omitiendo `documentId`; si el patrón usa el código como ID, usar el código).
3. Campos (basados en la forma real de vfxFlow, verbatim de `ShotFormDialog` + `shotService.addShot`):
   - `code` = `"0012_0100"` (string)
   - `description` = `""`
   - `status` = `"received"` (según mapeo de 1.3)
   - `progress` = `0` (integer)
   - `assigneeId` = `""`
   - `thumbnailUrl` = URL del JPG subido en 1.6 (string)
   - `referenceImages` = `[URL del JPG]` (array de strings)
   - `version` = `1` (integer)
   - `teamMembers` = `[]`
   - `stateId` = el descubierto en 1.4 (string)
   - `projectId`, `chapterId` (strings)
   - `dueDate`: si el CSV da FECHA DE ENTREGA, usarla en formato ISO; si no, omitir el campo (no inventar fechas).
   - `createdAt`/`updatedAt` = `{"timestampValue": "<now ISO>"}` (Timestamps reales; NUNCA strings ISO en el cuerpo REST).
4. Multi-documento: usar el endpoint batch `...:commit` (máx. 500 ops) o `PATCH` documento por documento; nunca dejar escrituras parciales sin reportar. Cualquier fallo → detener, reportar qué se escribió y qué falta.

### 1.6 Generar y subir la imagen de referencia

- Generar el JPG 720p (el mismo comando del clonado, q2): `ffmpeg -y -v error -i <clip>.mov -frames:v 1 -q:v 2 -vf "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2" -f image2 .../TO_VFX/EP_{EP}/{fecha}/PNG/<basename-sin-Vnn>.jpg`. Si ya existe en `PNG/`, reutilizarlo.
- Subir a Storage REST: `POST https://firebasestorage.googleapis.com/v0/b/vfxpm-be912.firebasestorage.app/o?uploadType=media&name=projects/{projectId}/chapters/{chapterId}/shots/{shotId}/references/<basename>.jpg` con `Authorization: Bearer <token>`, `Content-Type: image/jpeg`, `--data-binary @<jpg>`.
- URL de referencia para el shot: `https://firebasestorage.googleapis.com/v0/b/vfxpm-be912.firebasestorage.app/o/<path-encoded>?alt=media` (verificar accesibilidad real; las reglas de Storage de producción no están en el repo y NO se tocan).
- Guardar esa misma URL en `thumbnailUrl` y `referenceImages` del shot (decisión: ambas, patrón del proyecto).
- Si el shot ya existía y tenía `referenceImages`, añadir la URL sin duplicar (comprobar `includes`; usar `PATCH` con `updateMask` solo de `referenceImages`/`thumbnailUrl`).

### 1.7 Crear los comentarios por plano (shotActivity)

- Ruta REAL de comentarios: `projects/{projectId}/shotActivity` con `type: 'comment'` (**NO** la subcolección `comments` — es código muerto). Documento por plano, cuyo `shotId` apunta al shot creado.
- Regla de secuencia: si un plano de la secuencia tiene `linkFrame` (normalmente el `.0100`), el comentario con ESE link se crea en **CADA plano de esa secuencia**. Si una secuencia no tiene link, el comentario lleva solo la nota.
- Contenido del comentario (decisión: nota CSV + link de frame combinados, legible):
  ```
  <notes CSV>

  Link de frame: <linkFrame>
  Frames: <frames>
  ```
  Si no hay link: omitir la línea del link. Si no hay notas: solo el link. Ignorar espacios/duplicados del CSV.
- Campos del documento (replicar `ShotDetailsPanel`/`activityLogger`):
  - `shotId`, `projectId` (strings)
  - `type` = `"comment"`
  - `userId`, `userName`, `userPhotoURL` (del usuario descubierto en 1.4)
  - `timestamp`/`createdAt`/`updatedAt` = `{"timestampValue": "<now ISO>"}` (Timestamps; `timestamp` y `createdAt` son campos separados)
  - `content` (string, el texto de arriba)
  - `isPrivate` = `false`
  - `parentId` = `null`, `quotedCommentId` = `null` (o omitidos si el esquema real los omite)
  - `metadata` = `{ "userRole": "<rol real del usuario>" }`
- Idempotencia: antes de crear, listar `shotActivity` del proyecto filtrado por `shotId` (o `where shotId == ...` con `runQuery`), y si ya existe un comment con el mismo `content` para ese shot, NO duplicar; reportarlo.
- Si hay más de un link en una secuencia o el patrón detectado no es el esperado, volver a 1.3 y pedir confirmación.

## Etapa 2 — Clonado Nuke (flujo existente, sin cambios)

## Hard Rules

- Read frame MUST start at 1: set `first 1` on every Read and Write, plus matching `last`/`origlast` and `origset true`.
- Project format AND Read format MUST match the actual clip resolution. Detect with ffprobe; use `UHD_4K` for 3840x2160 and `4K_DCP` for 4096x2160. Never inherit the template format blindly.
- Keep dynamic relative paths: `[python {PYTHON_TO_VFX}]/...`, `[python {PYTHON_COMP}]/...`, `[python {PYTHON_FROM_VFX}]/...`. NEVER absolute paths. Variables come from the `RUTAS2` node.
- The `.nk` filename drives the Write Tcl expressions: name it `HTLR_{EP}_{escena}_{shot}_comp_SAMAN_V{nn}.nk` inside `COMP/EP_{EP}/{escena}_{shot}_comp_SAMAN/`. `comp_SAMAN` es el sufijo de EMPRESA (no el artista); todo comp del estudio lo lleva.
- Every plate generates a 720p reference JPG (q2, ~110KB) from frame 1 into `TO_VFX/EP_{EP}/{fecha}/PNG/`, named like the mov basename WITHOUT the `_V{nn}` token (case-insensitive). Examples: `HTLR_107_012_01500_V01.mov` -> `HTLR_107_012_01500.jpg`; `HTLR_108_028_V01_0100.mov` -> `HTLR_108_028_0100.jpg`. Resolution 1280x720, pad to preserve aspect. Use JPG `-q:v 2`: PNG lossless is ~10x heavier with no review benefit.
- Validate plate names BEFORE cloning: the version token `_V{nn}` (case-insensitive) MUST sit at the END of the basename (`HTLR_{EP}_{escena}_{shot}_V{nn}.mov`). If a client file has it elsewhere (e.g. `HTLR_108_034_V01_0100.mov`), STOP and ask the user whether to rename it to the convention (`HTLR_108_034_0100_V01.mov`) before creating projects. Never rename silently.
- .nk must pass the SamanTools sanitizer before delivery (removes machine-specific volatile knobs).
- VFXFlow repo is READ-ONLY reference. Never modify, never run scripts inside it, never deploy rules.

## Decision Gates

| Clip resolution | Nuke format |
|---|---|
| 3840 x 2160 | `"3840 2160 0 0 3840 2160 1 UHD_4K"` |
| 4096 x 2160 | `"4096 2160 0 0 4096 2160 1 4K_DCP"` |

| Plate filename | Valid? | Correction |
|---|---|---|
| `HTLR_107_008_00100_V01.mov` | Yes | — |
| `HTLR_108_034_V01_0100.mov` | No (`_V01` mid-name) | `HTLR_108_034_0100_V01.mov` |

| CSV pattern | Action |
|---|---|
| Link solo en `.0100` y hermanos sin link | Replicar link a toda la secuencia (1.7) |
| Link en varios planos de la secuencia | Usar el link propio de cada plano; reportar |
| Secuencia sin link | Comentario solo con nota |
| `Estatus == CANCELADO` | NO crear shot; reportar en resumen |
| `Estatus` desconocido | Preguntar (Lossless Blocking Prompt) |
| Shot ya existe con el mismo `code` | No duplicar; actualizar solo lo faltante |
| User (autor) no encontrado en `users` | STOP, pedir UID/autor |

If the source plate has audio (WAV next to the mov), re-add the AudioRead with a dynamic path (the cleaned template removed it).

## Execution Steps (Nuke — se ejecuta después de Etapa 1)

1. List the plate files and validate each name against `HTLR_{EP}_{escena}_{shot}_V{nn}.mov`. For any file whose `_V{nn}` token is NOT at the end, present the correction choice to the user (rename to convention / keep as-is) and WAIT for the answer; rename only with explicit consent, then use the corrected names everywhere (Read, PNG, .nk).
2. Copy the base template (`COMP/EP_100/HTLR_100_000_00000_comp_SAMAN_V01.nk`) into the new shot folder and rename to the convention above.
3. Probe the clip: `ffprobe -v error -select_streams v:0 -show_entries stream=width,height,nb_frames -of csv=p=0 clip.mov`.
4. Generate the reference JPG (frame 1, 720p q2, name without `_V{nn}`):
   `ffmpeg -y -v error -i <clip>.mov -frames:v 1 -q:v 2 -vf "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2" "TO_VFX/EP_{EP}/{fecha}/PNG/<name>.jpg"`
5. In Nuke, Save As to fix `Root.name`, then set Root format, `fps 23.976`, `lock_range true`, `last_frame` = clip frames.
6. On the Read: set `file` to `[python {PYTHON_TO_VFX}]/EP_{EP}/{fecha}/<clip>.mov`, format = clip resolution, `first 1`, `last`/`origlast` = clip frames, colorspace `DaVinci Intermediate WideGamut`.
7. Fix every Write: `first 1`, `last` = clip frames, verify Tcl name derivation matches the new filename.
8. Clean leftover viewer names (e.g., `DPCP_EP_101_0042_comp_DGTV_V001`).
9. Save, reopen isolated, render one proof frame.
10. Sanitize the saved .nk: machine-specific volatile knobs (`mov64_prraw_plugin`, `render_settings_schema`, `monitorOutNDISenderName`) must NOT travel in shared/versioned comps. Run the sanitizer over the final saved `.nk`:
    `python3 -c "import sys; sys.path.insert(0, '<ruta-del-checkout-de saman-nuke-tools>'); from SamanTools.limpiar import sanitizar_archivo; sanitizar_archivo('<ruta>.nk')"`
    Note: if SamanTools is in NUKE_PATH, you can also run it from inside Nuke with `import SamanTools.limpiar as l; l.sanitizar_archivo(nuke.root().name())`. This removes `mov64_prraw_plugin`/`render_settings_schema`/`monitorOutNDISenderName` so the comp opens clean on machines without the plugin or with an older Nuke.

## Output Contract

Return:
1. **Ingesta**: ruta del CSV, patrón detectado (secuencias, links, cancelados), `projectId`/`chapterId`/`stateId`/autor usados, shots creados vs ya existentes (códigos), JPGs generados y sus URLs de Storage, comentarios creados por plano (nota+link y a qué shots), e indicación de que VFXFlow no fue modificado.
2. **Clonado**: cloned `.nk` paths, clip resolution + frames used, format chosen, generated JPG paths, naming validation outcome, and confirmation that all Reads/Writes have `first 1` and no absolute paths remain (`grep -E 'PYTHON_|first|last|format' *.nk`).

## References

- `/Volumes/wupm/2026/HTLR/COMP/EP_100/PRACTICAS_CLONADO_NUKE.md` — full practice guide and EP_108 clip table.
- `/Volumes/wupm/2026/HTLR/COMP/EP_100/HTLR_100_000_00000_comp_SAMAN_V01.nk` — base template file.
- `/Volumes/wupm/2026/VFXFlow/skills/vfxflow-data-auth/SKILL.md` + `references/data-map.md` — SOLO CONSULTA: esquema real de Firestore, rutas de colecciones, gotchas (comentarios en `shotActivity`, no `comments`; reglas de producción ≠ repo).
- `/Volumes/wupm/2026/VFXFlow/src/types/models.ts` — SOLO CONSULTA: tipos `Shot`, `ShotActivity`, `Chapter`, `ProjectState`.
- `/Volumes/wupm/2026/VFXFlow/src/components/project/ShotFormDialog.tsx`, `ShotDetailsPanel.tsx`, `BulkReferenceImageUpload.tsx` — SOLO CONSULTA: formas reales de creación de shot/comentario/upload.