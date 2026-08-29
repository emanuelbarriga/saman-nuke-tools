# Evaluación: Panel Nuke ↔ Firebase (vfxFlow) — Hallazgos y estado

> Documento vivo. Estado: **pausado** (2026-08-29). Se documenta para decidir más adelante.
> ⚠️ **CORRECCIÓN 2026-08-29**: los comentarios REALES viven en `shotActivity` (type comment/reply), NO en la subcolección `comments` (código muerto). Ver §2.1.
> Fuentes verificadas: `VFXFlow/skills/vfxflow-data-auth/SKILL.md`, `references/data-map.md`,
> `AGENTS.md`, `firestore.rules`, `firestore.indexes.json`, `src/services/*`, `src/lib/firebase.ts`.

## 1. Idea evaluada

Panel acoplable (docked) en Nuke 17 que conecta al artista con la metadata del proyecto en
Firebase: leer/enviar comentarios del shot actual, y previsualizar referencias/dailies de la nube.
Arquitectura liviana: REST con `urllib` (sin SDK Firebase dentro del Python de Nuke), PySide6,
login con las mismas credenciales email/password de la app web/móvil, idToken en cada request.

## 2. Corrección mayor — el backend real es FIRESTORE, no Realtime Database

La idea original asumía Realtime Database. VFXFlow (proyecto `vfxpm-be912`) está sobre
**Firestore**.

### 2.1 ⚠️ DÓNDE viven los comentarios REALES (corregido 2026-08-29)

**Los comentarios de la app viven en `shotActivity`, NO en una subcolección `comments`:**
`shotActivity` (type `comment` | `reply` | `file_upload`) bajo `projects/{projectId}/shotActivity/{activityId}`.

- La UI real (`ShotDetailsPanel.tsx`, `ShotsTable.tsx`) lee, crea, edita y borra TODOS los
  comentarios vía `projects/{pid}/shotActivity/{id}` con `type: 'comment'/'reply'/'file_upload'`.
- El path `projects/{pid}/chapters/{cid}/shots/{sid}/comments` SOLO existe como código muerto
  (`shotService.getCommentsByShotId`/`addComment` — cero consumidores activos).
- El panel Nuke DEBE consultar:
  ```
  projects/{projectId}/shotActivity  (collection)
  filter: shotId == <shot id>
  optional: type in ['comment','reply','file_upload']
  orderBy: timestamp DESC
  ```
  Índice `shotActivity: shotId ASC + timestamp DESC` YA existe en `firestore.indexes.json`.
  Reglas de `shotActivity` YA están cubiertas en `firestore.rules` (read equipo con privacidad
  isPrivate; create equipo; update/delete admin/coord/dueño).

### 2.2 Firestore REST

- No hay SSE streaming en Firestore REST (el streaming por event-stream es de RTDB).
  Con Firestore + REST, el "tiempo real" honesto = **polling** (QTimer 2-5 s; latencia percibida 1-6 s).
- Endpoint concreto: `https://firestore.googleapis.com/v1/projects/vfxpm-be912/databases/(default)/documents/...`
  con `Authorization: Bearer <idToken>`. Timestamps como `timestampValue` RFC3339.

## 3. Los 8 huecos, resueltos contra la realidad del repo

| # | Hueco | Resolución verificada |
|---|---|---|
| 1 | idToken expira en 1 h | Login: `POST https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=<API_KEY>` → `idToken + refreshToken + expiresIn(3600)`. Refresco: `POST https://securetoken.googleapis.com/v1/token?key=<API_KEY>` con `grant_type=refresh_token`. Loop ~50 min. Email/password existe en la app (`loginUser`). |
| 2 | Rol del usuario | **No hay custom claims.** Rol en `users/{uid}` (`role`, `globalRole`, `isGlobalAdmin`). El panel debe leer `users/{uid}` tras login. Reglas exigen `projects/{projectId}/projectTeam/{uid}` para membrecía. `ViewAsRole` es cosmético (solo UI). |
| 3 | Panel docked | `nukescripts.panels.registerWidgetAsPanel(WidgetClass, nombre, "id.único")`. Reusar patrón PySide2/PySide6 de `frame_manager.py`. |
| 4 | Identidad del shot | Resolver por collectionGroup: `projects/{projectId}/shots`, filtro `code == <nombre .nk>`. Índice `projectId + code` YA existe en `firestore.indexes.json`. **Eslabón pendiente: cómo obtener `projectId` desde el .nk** (señal natural: convención de ruta `PYTHON_COMP` vía nodo Rutas). |
| 5 | RefreshToken | Credential de larga vida → `~/.config/saman/` con permisos 600. NUNCA al repo (regla SamanTools: repo público). API key NO es secreto (seguridad real = rules). |
| 6 | Reglas y paths de comentarios | ✅ **RESUELTO/CORREGIDO 2026-08-29**: los comentarios se leen de `shotActivity` → rules YA cubrían ese path (con privacidad isPrivate y ownership) e índice YA existía. Se deployaron rules que además cubren el path anidado de shots (`chapters/{cid}/shots/{sid}`) usado por el collectionGroup y el CRUD real. |
| 7 | Storage | No hay `storage.rules` en repo (consola; estado desconocido). Las URLs guardadas (`thumbnailUrl`, `referenceImages`, `attachments`) vienen de `getDownloadURL()` e incluyen `downloadToken`: `...?alt=media&token=...` → el modal descarga con GET plano, sin Bearer. Subir desde Nuke (futuro) sí requerirá Bearer. |
| 8 | `requests` vs `urllib` | Decisión confirmada: `urllib.request` (stdlib garantizado). No asumir `requests` en el Python embebido de Nuke. |

## 4. Gotchas del repo que afectan al panel

- ⚠️ **Los comentarios viven en `shotActivity`, NO en subcolección `comments`** (ver §2.1). Cualquier
  cliente REST debe filtrar `shotActivity` por `shotId` (+ `type in ['comment','reply','file_upload']`).
- `Project.client` es `string`, `getProjectsByClient` filtra `clientId` (mismatch menor).
- `projectTeam` se consulta top-level en servicios, pero rules solo definían `projects/{projectId}/projectTeam` — mismatch de rules; se agregó match top-level (deploy 2026-08-29).
- Agentes/data work en VFXFlow: cargar la skill `vfxflow-data-auth` antes de tocar datos (regla AGENTS.md §11).

## 5. Veredicto

Idea sólida y ahora anclada a datos reales (paths, endpoints, índices, reglas verificados).
El "tiempo real" es polling de Firestore, no push. El prerrequisito de rules quedó alineado
(deploy 2026-08-29): el panel usa `shotActivity` (ya cubierto) y puede resolver shots por `code`
(collectionGroup cubierto). La lectura de comentarios NO depende de la subcolección `comments`.

## 6. Decisiones pendientes (cuando se retome)

1. ¿Cómo se resuelve `projectId` desde el .nk en el panel? (convención de ruta vs config)
2. ¿Formalizar como cambio SDD en saman-nuke-tools? (propuesta → specs → design → tasks)
3. ¿Alcance v1: solo leer/enviar comentarios + preview de referencias? (sin upload)