"""
SamanTools.vfxflow_datos - Lectura (SOLO LECTURA) de planos y actividad
desde Firestore (VFXFlow), pura y testeable.

Resuelve la cadena proyecto -> capitulo -> shot -> actividad del plano
activo usando runQuery REST con filtro por campo UNICO (indice automatico
de Firestore): NO se usa orderBy ni ningun filtro compuesto para no requerir
indices manuales en produccion. El orden de la actividad se aplica en
memoria (createdAt DESC: el feed "Actividad Reciente" muestra lo mas nuevo
arriba).

La "actividad" NO es solo comentarios: shotActivity incluye los 8 tipos
(comment, reply, file_upload, status_change, version_update, task_update,
batch_update, assignment_change) y el feed del panel los muestra todos como
tarjetas de actividad.

Reutiliza el transporte autenticado de `vfxflow_auth`:
  - `_get_con_bearer`  -> sin uso aca (los runQuery son POST).
  - `_post_json_bearer`-> POST autenticado para las queries.

Cadena de resolucion desde `nombres.parsear_plato` (proyecto/capitulo/plano):
  1. projects              (WHERE code ==  "<proyecto>")            -> project_id
  2. projects/{pid}/chapters       (WHERE title == "<proyecto>_<cap>") -> chapter_id
  3. projects/{pid}/chapters/{cid}/shots (WHERE code == "<plano>")  -> shot_id
  4. projects/{pid}/shotActivity   (WHERE shotId == "<shot_id>")

Los "no encontrado" NO lanzan: `resolver_plano` devuelve un dict con un
campo `error` describiendo que paso fallo. Solo red/http/token lanzan
`VfxFlowAuthError`.
"""

from . import vfxflow_auth
from . import vfxflow_config

# Base de los documentos de Firestore de VFXFlow (el project_id es de
# Firebase, "vfxpm-be912", NO el codigo del proyecto de produccion como
# "HTLR": para las rutas subcoleccion el project_id funciona igual por ser
# el prefijo del resource name).
_URL_DOCUMENTOS = (
    "https://firestore.googleapis.com/v1/projects/{project_id}"
    "/databases/(default)/documents"
)

# Tipos de documento de shotActivity que se muestran en el feed de actividad
# (los 8 tipos: comentarios, archivos, estados, versiones, tareas, batch y
# asignaciones). file_upload SE muestra como actividad en el feed.
_TIPOS_ACTIVIDAD = (
    "comment",
    "reply",
    "file_upload",
    "status_change",
    "version_update",
    "task_update",
    "batch_update",
    "assignment_change",
)

# Campos que se exponen de cada actividad (proyeccion estable de la API).
# Incluye TODOS los campos que la UI del feed necesita por tipo.
_CAMPOS_ACTIVIDAD = (
    "content",
    "userName",
    "userRole",
    "role",
    "createdAt",
    "type",
    "isPrivate",
    "shotId",
    "parentId",
    "previousState",
    "previousStateName",
    "newState",
    "newStateName",
    "previousVersion",
    "newVersion",
    "previousAssignees",
    "newAssignees",
    "attachments",
    "taskId",
    "taskName",
    "completed",
    "userPhotoURL",
    "timestamp",
)


def _extraer_id_documento(name):
    """Devuelve el id de un documento Firestore desde su `name` REST.

    El `name` viene como
    `projects/vfxpm-be912/databases/(default)/documents/<ruta>`; el id es el
    ultimo segmento tras `/documents/`. Sin marcador, se usa el ultimo
    segmento del string. Nunca lanza.
    """
    if not name:
        return None
    nombre = str(name)
    marcador = "/documents/"
    indice = nombre.rfind(marcador)
    if indice >= 0:
        resto = nombre[indice + len(marcador):]
    else:
        resto = nombre
    resto = resto.rstrip("/")
    if not resto:
        return None
    return resto.split("/")[-1] or None


def _buscar_por_campo(coleccion_path, campo, valor, id_token, config=None, limite=None):
    """runQuery generico: devuelve los documentos que matchean `campo==valor`.

    `coleccion_path` es la ruta de la coleccion bajo
    `.../documents/` (p.ej. `projects/{pid}/chapters`); el `collectionId`
    del from es el ultimo segmento. La query es un fieldFilter EQUAL sobre
    `valor` (stringValue): filtro por campo unico = indice automatico de
    Firestore, sin orderBy. Con `limite` se agrega `"limit": N` al payload.

    Devuelve una lista de dicts `{"id", "name", "campos"}` (id = id del
    documento, campos = doc aplanado con `_aplanar_firestore_fields`) o la
    lista vacia si no hay coincidencias o la respuesta fue None/invalida
    (p.ej. 404 de Firestore). Levanta `VfxFlowAuthError` por red/http/token.
    """
    cfg = config or vfxflow_config.obtener_config_efectiva()
    project_id = (cfg or {}).get("project_id") or ""
    coleccion = coleccion_path.rstrip("/").split("/")[-1]

    url = _URL_DOCUMENTOS.format(project_id=project_id)
    if coleccion_path and "/" in coleccion_path:
        # Solo las subcolecciones se anidan en la URL (projects/{pid}/chapters);
        # una coleccion RAIZ se consulta en .../documents:runQuery con el
        # collectionId en el cuerpo (modelo REST de runQuery).
        url += "/" + coleccion_path.strip("/")
    url += ":runQuery"

    payload = {
        "structuredQuery": {
            "from": [{"collectionId": coleccion}],
            "where": {
                "fieldFilter": {
                    "field": {"fieldPath": campo},
                    "op": "EQUAL",
                    "value": {"stringValue": str(valor)},
                }
            },
        }
    }
    if limite is not None:
        payload["structuredQuery"]["limit"] = int(limite)

    respuesta = vfxflow_auth._post_json_bearer(url, payload, id_token)
    if not isinstance(respuesta, list):
        return []

    docs = []
    for entrada in respuesta:
        if not isinstance(entrada, dict) or "document" not in entrada:
            continue  # {"readTime": ...} y ruido se ignoran
        documento = entrada["document"]
        if not isinstance(documento, dict) or "name" not in documento:
            continue
        docs.append(
            {
                "id": _extraer_id_documento(documento.get("name")),
                "name": documento.get("name"),
                "campos": vfxflow_auth._aplanar_firestore_fields(
                    documento.get("fields")
                ),
            }
        )
    return docs


def _buscar_primero(coleccion_path, campo, valor, id_token, config):
    """Primer doc de `_buscar_por_campo` (limite 1) o None."""
    resultados = _buscar_por_campo(
        coleccion_path, campo, valor, id_token, config=config, limite=1
    )
    if not resultados:
        return None
    return resultados[0]


def resolver_plano(datos_plano, id_token, config=None):
    """Resuelve el shot del plano activo en Firestore (cadena completa).

    Recibe el dict de `nombres.parsear_plato` (con `proyecto`, `capitulo`,
    `plano`). Devuelve, en exito:
        {"project_id", "chapter_id", "shot_id",
         "project" (doc aplanado), "chapter", "shot"}
    Si un paso "no encontrado" falla devuelve un dict con un campo `error`
    identificando el paso (proyecto_no_encontrado / capitulo_no_encontrado /
    plano_no_encontrado), sin lanzar. Con datos de entrada incompletos o
    invalidos devuelve None. Red/http/token lanzan `VfxFlowAuthError`.
    """
    cfg = config or vfxflow_config.obtener_config_efectiva()
    if not isinstance(datos_plano, dict):
        return None
    proyecto = datos_plano.get("proyecto")
    capitulo = datos_plano.get("capitulo")
    plano = datos_plano.get("plano")
    if not proyecto or capitulo is None or not plano:
        return None

    doc_proyecto = _buscar_primero(
        "projects", "code", proyecto, id_token, cfg
    )
    if doc_proyecto is None:
        return {"error": "proyecto_no_encontrado", "proyecto": proyecto}
    project_id = doc_proyecto["id"]
    if not project_id:
        return {"error": "proyecto_no_encontrado", "proyecto": proyecto}

    titulo = "{0}_{1}".format(proyecto, capitulo)
    doc_capitulo = _buscar_primero(
        "projects/{0}/chapters".format(project_id),
        "title",
        titulo,
        id_token,
        cfg,
    )
    if doc_capitulo is None:
        return {
            "error": "capitulo_no_encontrado",
            "project_id": project_id,
            "capitulo": capitulo,
        }
    chapter_id = doc_capitulo["id"]
    if not chapter_id:
        return {
            "error": "capitulo_no_encontrado",
            "project_id": project_id,
            "capitulo": capitulo,
        }

    doc_plano = _buscar_primero(
        "projects/{0}/chapters/{1}/shots".format(project_id, chapter_id),
        "code",
        plano,
        id_token,
        cfg,
    )
    if doc_plano is None:
        return {
            "error": "plano_no_encontrado",
            "project_id": project_id,
            "chapter_id": chapter_id,
            "plano": plano,
        }
    shot_id = doc_plano["id"]
    if not shot_id:
        return {
            "error": "plano_no_encontrado",
            "project_id": project_id,
            "chapter_id": chapter_id,
            "plano": plano,
        }

    return {
        "project_id": project_id,
        "chapter_id": chapter_id,
        "shot_id": shot_id,
        "project": doc_proyecto["campos"],
        "chapter": doc_capitulo["campos"],
        "shot": doc_plano["campos"],
    }


def listar_actividad(project_id, shot_id, id_token, config=None):
    """Toda la actividad del shot (8 tipos de shotActivity), orden DESC.

    Query `projects/{project_id}/shotActivity` con filtro solo por `shotId`
    (campo unico, sin orderBy) y el filtrado/orden se hace en memoria:
    incluye TODOS los tipos de `_TIPOS_ACTIVIDAD` (el feed "Actividad
    Reciente" muestra comentarios, archivos, cambios de estado, versiones,
    tareas y asignaciones) y ordena por `createdAt` DESCENDENTE (lo mas
    reciente arriba, porque es un feed de actividad). Cada item proyecta los
    campos `_CAMPOS_ACTIVIDAD`; si Firestore devuelve `role` en vez de
    `userRole`, se normaliza a `userRole = role or userRole`.

    Decisión de orden (documentada): el panel muestra "Actividad Reciente",
    por eso DESC; antes (v1.6.0) los comentarios iban ASC dentro del
    QTextBrowser. La nueva lectura reemplaza TODO el feed.

    Devuelve la lista (posiblemente vacia) de dicts con los campos
    `_CAMPOS_ACTIVIDAD` proyectados. Red/http/token lanzan `VfxFlowAuthError`.
    """
    cfg = config or vfxflow_config.obtener_config_efectiva()
    resultados = _buscar_por_campo(
        "projects/{0}/shotActivity".format(project_id),
        "shotId",
        shot_id,
        id_token,
        config=cfg,
    )
    actividad = []
    for resultado in resultados:
        campos = resultado["campos"]
        if campos.get("type") not in _TIPOS_ACTIVIDAD:
            continue
        item = {clave: campos.get(clave) for clave in _CAMPOS_ACTIVIDAD}
        if not item.get("userRole") and item.get("role"):
            item["userRole"] = item["role"]
        actividad.append(item)
    actividad.sort(key=lambda a: a.get("createdAt") or "", reverse=True)
    return actividad


def listar_comentarios(project_id, shot_id, id_token, config=None):
    """Alias de `listar_actividad` (compatibilidad con el panel v1.6.0).

    La actividad del shot incluye todos los tipos (no solo comment/reply);
    el alias se mantiene para no romper llamadas previas al módulo.
    """
    return listar_actividad(project_id, shot_id, id_token, config=config)