---
name: vfxflow-panel-comentarios
description: "Trigger: vfxflow, panel comentarios, comentarios por plano, VFXFlow, shotActivity, login google Nuke, subir imagen referencia, cambiar estado plano, resumir panel. Conecta el panel 'Comentarios por Plano' de Nuke 17.1 con VFXFlow (Firebase): login email/Google OAuth, escritura y lectura de shotActivity, adjuntos e imágenes de referencia, y cambios de estado de plano vía REST Firestore sin SDK."
license: Apache-2.0
metadata:
  author: "emanuelbarriga"
  version: "1.0"
---

# Panel de Comentarios por Plano (VFXFlow)

## Activation Contract

Cargar cuando se trabaje sobre el panel "Comentarios por Plano" (`SamanTools/panel_comentarios.py`), que conecta Nuke 17.1 con VFXFlow (Firebase: project `vfxpm-be912`, Firestore `nam5`, storage `vfxpm-be912.firebasestorage.app`, api_key pública por diseño), o sobre cualquiera de sus áreas: VFXFlow, shotActivity, login Google Nuke, subir imagen de referencia, cambiar estado de plano, resumir panel, adjuntos de imagen, cadena de resolución plano→shot→actividad, feed de comentarios o la capa REST Firestore sin SDK.

## Hard Rules

**Registro del panel**
- Registrar con `nukescripts.panels.registerWidgetAsPanel(widget, name, id, create=True)` y `widget` como STRING evaluable. En Nuke 17.1 NO existen `panels()` / `getPanel()`.
- Import PySide2/PySide6 con fallback; en PySide6 los enums Qt requieren namespace explícito (`QtCore.Qt.MatchExactly`, etc.).

**Login / OAuth**
- Login email/password: `accounts:signInWithPassword?key={api_key}`.
- Google: Device Flow (client TV/Limited Input, `google_client_id`) o loopback PKCE (client Desktop `google_client_id_escritorio`, preferido).
- El client_secret del Desktop app es OBLIGATORIO en el canje `oauth2.googleapis.com/token` — solo PKCE NO alcanza (error `client_secret is missing`). Se lee de config; NUNCA del repo.
- El canje de Google se completa con `accounts:signInWithIdp` (postBody con id_token + providerId google.com + requestUri http://localhost).
- El refresh_token de Google NO se persiste; el de Firebase sí. El id_token dura 1h: refrescar con `securetoken.googleapis.com/v1/token?key={api_key}`, que devuelve `user_id` (NO `local_id`) — mapear user_id → local_id en el registro de sesión.
- **Regla Qt**: el canje de 3 llamadas de red corre en `threading.Thread(daemon=True)`; la UI NUNCA se toca desde el worker (un QTimer del hilo principal aplica el resultado). Los `_poll_*` observan `_*_trabajo`.
- **SSL**: el Python embebido de Nuke no tiene los CA del sistema → `SSLCertVerificationError`. Fix: `_contexto_ssl` (ssl.create_default_context con cafile `/etc/ssl/cert.pem` o exportando el Keychain vía `security find-certificate`).
- **Proxy**: config efectiva `proxy` → env `HTTPS_PROXY` → `scutil --proxy` (macOS). El firewall LuLu del estudio usa allowlist `(oauth2|identitytoolkit|securetoken|firestore)\.googleapis\.com` puerto 443.

**Config (pública, en runtime)**
- Prioridad: defaults versionados → `.saman/vfxflow_config.json` en la raíz de la unidad wupm (la ACL LucidLink es el gate de acceso: si no existe, el panel NO autologinea) → `config_local.py` (gitignored, override local; hoy vacío).
- client_ids + secret = "Google OAuth client ID" en el disco; NUNCA versionados.
- El consent screen pertenece a la ORG dueña del proyecto GCP (@pacoraproducciones.com); los usuarios @samanestudio.com deben ser test users o el screen debe ser External/Publicado.

**REST Firestore (sin SDK, urllib)**
- GET autenticado (Bearer id_token) para docs y metadata; POST para runQuery; PATCH para updates.
- **runQuery**: URL `.../documents:runQuery` para colecciones raíz, o `.../documents/{parent_doc}:runQuery` PARA SUBCOLECCIONES — el parent de la URL es el DOCUMENTO PADRE (`projects/{pid}/chapters` se consulta como `.../documents/projects/{pid}:runQuery` con `from:[{collectionId:"chapters"}]`). Poner la subcolección en la URL da `400 INVALID_ARGUMENT "Document parent name ... lacks /"` (bug cazado en v1.6.2).
- Filtro por CAMPO ÚNICO (equality) = índice automático; nunca orderBy (requiere índices compuestos). Ordenar en memoria. No tocar firestore.rules de producción (se revirtió al ruleset 80c52014).
- Decode con `_aplanar_firestore_fields` (stringValue/booleanValue/integerValue/doubleValue/timestampValue/nullValue + **mapValue/arrayValue recursivo**).
- 401 → código "token" (refrescar y reintentar en el flujo de sesión); 404 → None.

**Escritura**
- createDocument POST a `.../documents/projects/{pid}/shotActivity` con `{"fields": {...}}` codificados (stringValue; timestampValue para createdAt/updatedAt/timestamp; nullValue para parentId/quotedCommentId vacíos; mapValue para metadata).
- Identidad: userName/userRole/userPhotoURL provienen del doc `users/{uid}` (fusionado al login); si falta, se degrada a email-local-part/"artist". La sesión persiste userName/userPhotoURL/role.
- **Cambio de estado (spec app)**: (1) updateShot: PATCH `shots/{sid}` con payload MÍNIMO `{stateId, updatedAt, progress?}` (progress = defaultPercentage del estado nuevo si existe) — NUNCA escribir un campo `status` (el doc real no lo tiene; Firestore rechaza el updateMask; bug real v1.7.6). (2) DESPUÉS logShotUpdateActivity: crear la actividad status_change con metadata {previousState, previousStateName, newState, newStateName, userRole}. Primero el shot, después la actividad; si la actividad falla, el shot ya cambió (aviso); si el shot falla, NO crear la actividad.

**Refs / export / adjuntos**
- referenceImages del shot: URLs firmadas `?alt=media&token=...` — GET puro sin Bearer.
- Import como Read: carpeta `ref/`, ruta del knob `[python {PYTHON_COMP}]/EP_<nn>/{carpeta_comp}/ref/{filename}` (PYTHON_COMP se expande en Nuke; llaves literales).
- Export del nodo seleccionado (subir como adjunto del comentario): subgrafo Dot(label IN) → Reformat 1280x720 HD_720 → Crop → OCIODisplay(scene_linear → "sRGB - Display / ACES 2.0 - SDR 100 nits (Rec.709)") → Write(.jpg raw) → `nuke.render` (fallback `nuke.execute`) → ref/temp/ → se sube SOLO al enviar (adjunto pendiente en memoria; comment con metadata.attachments).
- `QTWidgets.QPixmap` NO existe: QPixmap está en `QtGui` (bug real que tumbaba las cards con imagen).

**UI / feed**
- Tema oscuro Nuke (#2b2b2b, acento #1f8ecd), QScrollArea transparente (macOS), QToolButton NO tiene setTextFormat (los menús/chips usan icono dot 16×16).
- Feed de 8 tipos, orden DESC por createdAt, replies agrupadas bajo el padre colapsadas ("▸ Ver N respuestas"), markdown bold `**x**` → `<b>x</b>` después del escape, tiempo relativo en español ("hace alrededor de X horas"), avatares con inicial (userPhotoURL queda pendiente como foto).
- **Resiliencia**: cada card se pinta con try/except individual (`_intentar_card`): una card rota NO corta el feed (reporta "X de Y mostradas (Z con error)" y loggea) — bug histórico del feed cortado.
- Polling del plano activo con QTimer 1.5s comparando `nuke.root().name()`.

## Esquema shotActivity (8 tipos)

Colección `projects/{pid}/shotActivity/{activityId}`. Campos comunes: type, content, shotId, projectId, userId, userName (SNAPSHOT denormalizado de `users/{uid}.name` al momento de crear — nunca se sincroniza), userRole/role (snapshot), userPhotoURL (snapshot), createdAt/updatedAt/timestamp (timestampValue), isPrivate, metadata (map opcional), parentId, quotedCommentId.

1. **comment** — texto en content. Los ADJUNTOS de imagen van en `metadata.attachments` (NO top-level; el doc real "Teste de imagen" lo confirma).
2. **reply** — igual + `parentId` (id del padre, top-level).
3. **file_upload** — `attachments: [{id, type: image|file, url (firmada con token), name, size, mimeType}]`; storage `projects/{pid}/image_comments/{file}` (panel) o `shots/{sid}/attachments/` (service).
4. **status_change** — previousState/previousStateName, newState/newStateName; content sintetizado "Estado cambiado de 'X' a 'Y'".
5. **version_update** — previousVersion/newVersion.
6. **task_update** — taskId/taskName/completed.
7. **batch_update** — estado+versión consolidados; completedTasks va en content (texto), no en metadata.
8. **assignment_change** — previousAssignees/newAssignees `{primaryId, primaryName, secondaryIds[], secondaryNames[]}`.

## Decision Gates

| Situación | Acción |
|---|---|
| Login del usuario | Email/password → `accounts:signInWithPassword`. Google → preferir loopback PKCE (Desktop `google_client_id_escritorio`); fallback Device Flow (TV/Limited Input, `google_client_id`) |
| Canje OAuth de Google | `oauth2.googleapis.com/token` CON client_secret de config (obligatorio); después `accounts:signInWithIdp` para el id_token |
| id_token expirado (1h) | Refrescar con `securetoken` (devuelve `user_id` → mapear a `local_id`); 401 → código "token" y reintentar |
| Consultar una subcolección (ej. chapters de projects/{pid}) | runQuery contra el DOCUMENTO padre: `.../documents/projects/{pid}:runQuery` |
| Filtrar/ordenar Firestore | Filtro equality de UN campo; ordenar en memoria; nunca orderBy |
| Cambiar el estado de un plano | updateShot con payload MÍNIMO (stateId/updatedAt/progress?); NUNCA `status`; después crear la actividad status_change |
| La actividad falla tras un updateShot OK | Avisar: el estado ya cambió y la actividad quedó inconsistente; no revertir |
| El updateShot falla | NO crear la actividad status_change |
| Subir adjunto desde el nodo seleccionado | Construir subgrafo de export → render → ref/temp/ → adjunto PENDIENTE en memoria hasta enviar el comentario |
| Card rota al pintar el feed | `_intentar_card`: aislar la excepción y seguir; reportar "X de Y mostradas (Z errores)" |
| Error SSL en Nuke | `_contexto_ssl`: create_default_context con cafile /etc/ssl/cert.pem o exporte de Keychain |
| Falta config (`.saman/vfxflow_config.json`) | No autologin; pedir credenciales manualmente (ACL LucidLink = gate) |
| Qt enum en PySide6 | Usar namespace explícito (`QtCore.Qt.*`) |

## Execution Steps

1. **Registro**: `nukescripts.panels.registerWidgetAsPanel("<clase evaluable>", name, id, create=True)`; import PySide2/PySide6 con fallback.
2. **Config**: cargar defaults versionados → `.saman/vfxflow_config.json` (si falta: sin autologin) → `config_local.py`. Si existe client_secret, leerlo de config, nunca del repo.
3. **Login**: preferir refresh de sesión (Firebase refresh token vía `securetoken`, mapeando user_id→local_id) o email/password; Google vía loopback PKCE. El canje de 3 llamadas de red corre en `threading.Thread(daemon=True)`; aplicar cambios a la UI desde QTimer del hilo principal; fusionar `users/{uid}` para userName/userRole/userPhotoURL.
4. **Resolución** con `parsear_plato` (`SamanTools/nombres.py`, formato {PROYECTO}_{EP}_{escena}_{shot}_V{nn}, comp_SAMAN es metadato): projects WHERE code == proyecto → chapters WHERE title == "{proyecto}_{capitulo}" (ej. HTLR_107; chapters tienen code/name/order/color) → shots WHERE code == plano (ej. 008_00200) → shotActivity WHERE shotId == id. Los IDs de documento Firestore (lxYgN..., B3W9...) NO son los códigos legibles — la cadena los resuelve.
5. **Feed**: GET + runQuery de shotActivity con `_aplanar_firestore_fields`; ordenar DESC por createdAt en memoria; agrupar replies bajo el padre colapsado; pintar cada card con `_intentar_card` (una card rota no corta el feed).
6. **Cambio de estado**: (1) updateShot PATCH `shots/{sid}` con payload mínimo `{stateId, updatedAt, progress?}`; (2) recién después crear la actividad status_change con metadata {previousState, previousStateName, newState, newStateName, userRole}. Selector: estados por `order` asc, flechas ◀▶ habilitadas según índice, chip con color y "✓" en el item actual, estado pendiente en ámbar; botones Save (escribe) y Undo (solo memoria, sin red). Estados reales en `projects/{pid}/projectStates/{stateId}`.
7. **Adjuntos**: imagen de referencia → Read dinámico `[python {PYTHON_COMP}]/EP_<nn>/{carpeta_comp}/ref/{filename}` o exporte del nodo (subgrafo 1280x720 → ref/temp/). Se sube SOLO al enviar (adjunto pendiente en memoria); al enviar: attachments en `metadata.attachments`.
8. **Polling**: QTimer 1.5s comparando `nuke.root().name()` para refrescar al cambiar de plano activo.

## Output Contract

Devolver: la ruta del panel tocada, la cadena de resolución usada (proyecto → capítulo → plano → shotId → actividad), las actividades escritas (tipo + campos), el cambio de estado hecho (previous→new con metadata), los adjuntos subidos (storage + URL firmada) y los fallos aislados por card/actividad.

## References

- `SamanTools/panel_comentarios.py` — panel "Comentarios por Plano" (VFXFlow ↔ Nuke 17.1).
- `SamanTools/nombres.py` — `parsear_plato`: {PROYECTO}_{EP}_{escena}_{shot}_V{nn}; comp_SAMAN es metadato.
- `.saman/vfxflow_config.json` (raíz de la unidad wupm) — config runtime pública; su existencia (ACL LucidLink) es el gate de autologin.
- `config_local.py` — override local gitignored.
- Firebase: project `vfxpm-be912`, Firestore `nam5`, storage `vfxpm-be912.firebasestorage.app`, api_key pública por diseño `AIzaSyARni3zruIfFx7ZTmKq8bDPsCkH6nhP0Bo`.
- Estados: `projects/{pid}/projectStates/{stateId}` con {id, projectId, name, stateType (received|in-progress|internal-review|producer-review|client-review|approved), defaultPercentage, order, color?}; cadena de defaults Recibido 5% → En Proceso 20% → Revisión Interna 70% → Revisión Productora 80% → Revisión Cliente 90% → Aprobado 100%.
- firestore.rules de producción: ruleset 80c52014 (no tocar).