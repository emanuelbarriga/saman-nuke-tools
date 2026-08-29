"""
Tests de SamanTools.vfxflow_datos (SOLO LECTURA de planos/comentarios).

Puros, sin red real: el transporte abre via `vfxflow_auth._abrir`, que se
monkeypatchea con respuestas runQuery fabricadas (RespuestaFalsa / HTTPError).
Se verifica la cadena proyecto -> capitulo -> shot -> comentarios, los errores
"no encontrado" (sin lanzar) y la clasificacion red/http/token de VfxFlowAuthError.
"""

import io
import json
import os
import socket
import sys
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from SamanTools import vfxflow_auth, vfxflow_datos
from SamanTools.vfxflow_auth import VfxFlowAuthError

# Config de test hermetico (no se lee la config efectiva del disco).
_CONFIG = {"project_id": "vfxpm-be912", "api_key": "AIzaSyTEST"}

NOMBRE_PROYECTO = (
    "projects/vfxpm-be912/databases/(default)/documents/projects/lxYgN96Zk8zyhsFEABOf"
)
NOMBRE_CAPITULO = (
    "projects/vfxpm-be912/databases/(default)/documents/projects/lxYgN96Zk8zyhsFEABOf"
    "/chapters/capXyz123"
)
NOMBRE_SHOT = (
    "projects/vfxpm-be912/databases/(default)/documents/projects/lxYgN96Zk8zyhsFEABOf"
    "/chapters/capXyz123/shots/shot_abc"
)


class RespuestaFalsa:
    """Emula la respuesta de urlopen: `.read()` y protocolo context."""

    def __init__(self, cuerpo, status=200):
        self._cuerpo = cuerpo
        self.status = status

    def read(self):
        return self._cuerpo

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


def _error_http(status, cuerpo):
    fp = io.BytesIO(json.dumps(cuerpo).encode("utf-8"))
    return urllib.error.HTTPError(
        "https://firestore.googleapis.com/invalido", status, "Error", {}, fp
    )


def _valor_firestore(valor):
    """Convierte un valor Python al value dict del REST de Firestore."""
    if isinstance(valor, bool):
        return {"booleanValue": valor}
    if isinstance(valor, int):
        return {"integerValue": str(valor)}
    if isinstance(valor, str):
        if "T" in valor and valor.endswith("Z"):
            return {"timestampValue": valor}
        return {"stringValue": valor}
    if valor is None:
        return {"nullValue": None}
    if isinstance(valor, dict):
        return {
            "mapValue": {
                "fields": {k: _valor_firestore(v) for k, v in valor.items()}
            }
        }
    if isinstance(valor, list):
        return {
            "arrayValue": {"values": [_valor_firestore(v) for v in valor]}
        }
    return {"stringValue": str(valor)}


def _doc(nombre, campos):
    """Doc Firestore fabricado: `name` + `fields` tipados para runQuery."""
    return {
        "document": {
            "name": nombre,
            "fields": {k: _valor_firestore(v) for k, v in campos.items()},
            "createTime": "2026-08-01T00:00:00Z",
            "updateTime": "2026-08-01T00:00:00Z",
        }
    }


def _respuesta_runquery(docs):
    """Cuerpo real de runQuery: docs + cierre readTime (que se ignora)."""
    return [{"document": d["document"]} for d in docs] + [
        {"readTime": "2026-08-01T00:00:00Z"}
    ]


class _TransporteRunQuery:
    """Fake de `vfxflow_auth._abrir`: responde por collectionId y registra.

    `rutas`: dict {collectionId del structuredQuery (p.ej. "chapters"): lista
    de docs o int (status de HTTPError)}. Matchear por collectionId (y no por
    sufijo de URL) es lo correcto: en el runQuery REST el collectionId va en
    el body y el parent en la URL (la subcoleccion NUNCA va en la URL, se
    verifico contra la API real). Registra en `pedidos` la
    (collectionId, payload, url) de cada POST.
    """

    def __init__(self, rutas):
        self.rutas = rutas
        self.pedidos = []

    def abrir(self, req, *args, **kwargs):
        url = req.full_url
        payload = json.loads(req.data.decode("utf-8")) if req.data else None
        coleccion = None
        if payload:
            coleccion = (
                (payload.get("structuredQuery") or {})
                .get("from", [{}])[0]
                .get("collectionId")
            )
        clave = coleccion or url
        if clave in self.rutas:
            self.pedidos.append((clave, payload, url))
            cuerpo = self.rutas[clave]
            if isinstance(cuerpo, int):
                raise _error_http(cuerpo, {"error": {"message": "x"}})
            return RespuestaFalsa(json.dumps(cuerpo).encode("utf-8"), status=200)
        raise AssertionError(
            "URL sin ruta de test: %s (collectionId %s)" % (url, coleccion)
        )


def _parchar_abrir(monkeypatch, abridora):
    """Conecta el fake de transporte: `abridora.abrir(req, *a, **k)` o callable."""
    if callable(abridora):
        monkeypatch.setattr(vfxflow_auth, "_abrir", abridora)
    else:
        monkeypatch.setattr(vfxflow_auth, "_abrir", abridora.abrir)


# --------------------------------------------------------------------------
# _extraer_id_documento
# --------------------------------------------------------------------------


def test_extraer_id_documento_ultimo_segmento():
    assert vfxflow_datos._extraer_id_documento(NOMBRE_SHOT) == "shot_abc"
    assert vfxflow_datos._extraer_id_documento(NOMBRE_PROYECTO) == "lxYgN96Zk8zyhsFEABOf"


def test_extraer_id_documento_valores_raros():
    assert vfxflow_datos._extraer_id_documento(None) is None
    assert vfxflow_datos._extraer_id_documento("") is None
    assert vfxflow_datos._extraer_id_documento("sin/marcador/ultimo") == "ultimo"
    assert vfxflow_datos._extraer_id_documento("documentos/") == "documentos"


# --------------------------------------------------------------------------
# resolver_plano (cadena proyecto -> capitulo -> shot)
# --------------------------------------------------------------------------


def test_resolver_plano_completo(monkeypatch):
    transporte = _TransporteRunQuery(
        {
            "projects": _respuesta_runquery(
                [_doc(NOMBRE_PROYECTO, {"code": "HTLR", "title": "HTLR"})]
            ),
            "chapters": _respuesta_runquery(
                [_doc(NOMBRE_CAPITULO, {"title": "HTLR_107", "code": "EP107"})]
            ),
            "shots": _respuesta_runquery(
                [_doc(NOMBRE_SHOT, {"code": "008_00100"})]
            ),
        }
    )
    _parchar_abrir(monkeypatch, transporte)

    res = vfxflow_datos.resolver_plano(
        {"proyecto": "HTLR", "capitulo": 107, "plano": "008_00100"},
        "TOKEN_ID",
        config=_CONFIG,
    )

    assert res["project_id"] == "lxYgN96Zk8zyhsFEABOf"
    assert res["chapter_id"] == "capXyz123"
    assert res["shot_id"] == "shot_abc"
    assert res["project"]["code"] == "HTLR"
    assert res["chapter"]["title"] == "HTLR_107"
    assert res["shot"]["code"] == "008_00100"

    # La query de la resolucion lleva limit=1 y filtra por el campo correcto.
    proyectos = [p for p in transporte.pedidos if p[0] == "projects"]
    assert proyectos and proyectos[0][1]["structuredQuery"]["limit"] == 1
    filtro = proyectos[0][1]["structuredQuery"]["where"]["fieldFilter"]
    assert filtro["field"]["fieldPath"] == "code"
    assert filtro["value"]["stringValue"] == "HTLR"
    capitulos = [p for p in transporte.pedidos if p[0] == "chapters"]
    filtro_capitulo = capitulos[0][1]["structuredQuery"]["where"]["fieldFilter"]
    assert filtro_capitulo["field"]["fieldPath"] == "title"
    assert filtro_capitulo["value"]["stringValue"] == "HTLR_107"

    # El collectionId va en el body y el parent (documento padre) en la URL: la
    # subcoleccion NUNCA va en la URL (aqui el parent es projects/{pid}, no
    # projects/{pid}/chapters).
    url_capitulos = capitulos[0][2]
    assert url_capitulos.endswith(
        "/documents/projects/lxYgN96Zk8zyhsFEABOf:runQuery"
    )
    assert "/chapters" not in url_capitulos.split(":runQuery")[0]
    assert capitulos[0][1]["structuredQuery"]["from"][0]["collectionId"] == "chapters"


def test_resolver_plano_proyecto_no_encontrado_devuelve_error(monkeypatch):
    transporte = _TransporteRunQuery({"projects": _respuesta_runquery([])})
    _parchar_abrir(monkeypatch, transporte)

    res = vfxflow_datos.resolver_plano(
        {"proyecto": "ZZZ", "capitulo": 107, "plano": "008_00100"},
        "TOKEN_ID",
        config=_CONFIG,
    )
    assert res == {"error": "proyecto_no_encontrado", "proyecto": "ZZZ"}


def test_resolver_plano_capitulo_no_encontrado_devuelve_error(monkeypatch):
    transporte = _TransporteRunQuery(
        {
            "projects": _respuesta_runquery(
                [_doc(NOMBRE_PROYECTO, {"code": "HTLR", "title": "HTLR"})]
            ),
            "chapters": _respuesta_runquery([]),
        }
    )
    _parchar_abrir(monkeypatch, transporte)

    res = vfxflow_datos.resolver_plano(
        {"proyecto": "HTLR", "capitulo": 999, "plano": "008_00100"},
        "TOKEN_ID",
        config=_CONFIG,
    )
    assert res["error"] == "capitulo_no_encontrado"
    assert res["project_id"] == "lxYgN96Zk8zyhsFEABOf"
    assert res["capitulo"] == 999


def test_resolver_plano_shot_no_encontrado_devuelve_error(monkeypatch):
    transporte = _TransporteRunQuery(
        {
            "projects": _respuesta_runquery(
                [_doc(NOMBRE_PROYECTO, {"code": "HTLR", "title": "HTLR"})]
            ),
            "chapters": _respuesta_runquery(
                [_doc(NOMBRE_CAPITULO, {"title": "HTLR_107"})]
            ),
            "shots": _respuesta_runquery([]),
        }
    )
    _parchar_abrir(monkeypatch, transporte)

    res = vfxflow_datos.resolver_plano(
        {"proyecto": "HTLR", "capitulo": 107, "plano": "999_99999"},
        "TOKEN_ID",
        config=_CONFIG,
    )
    assert res["error"] == "plano_no_encontrado"
    assert res["chapter_id"] == "capXyz123"
    assert res["plano"] == "999_99999"


def test_resolver_plano_datos_incompletos_devuelve_none():
    assert vfxflow_datos.resolver_plano(None, "TOKEN", config=_CONFIG) is None
    assert (
        vfxflow_datos.resolver_plano(
            {"proyecto": "HTLR"}, "TOKEN", config=_CONFIG
        )
        is None
    )
    assert (
        vfxflow_datos.resolver_plano(
            {"proyecto": "HTLR", "capitulo": 107}, "TOKEN", config=_CONFIG
        )
        is None
    )


def test_resolver_plano_401_lanza_token(monkeypatch):
    transporte = _TransporteRunQuery({"projects": 401})
    _parchar_abrir(monkeypatch, transporte)

    with pytest.raises(VfxFlowAuthError) as exc:
        vfxflow_datos.resolver_plano(
            {"proyecto": "HTLR", "capitulo": 107, "plano": "008_00100"},
            "TOKEN_VENCIDO",
            config=_CONFIG,
        )
    assert exc.value.codigo == "token"


# --------------------------------------------------------------------------
# listar_actividad (los 8 tipos, orden DESC, campos proyectados)
# ---------------------------------------------------------------------------


def _ruta_actividad(doc_id):
    """Ruta de un doc de shotActivity bajo el shot de test."""
    return NOMBRE_SHOT.replace("/shots/shot_abc", "/shotActivity/{0}".format(doc_id))


def test_listar_actividad_ocho_tipos_orden_desc_y_campos(monkeypatch):
    # Deliberadamente fuera de orden: el feed "Actividad Reciente" va DESC.
    t1 = "2026-08-01T08:00:00Z"  # status_change
    t2 = "2026-08-01T09:00:00Z"  # comment
    t3 = "2026-08-01T10:00:00Z"  # reply
    t4 = "2026-08-01T11:00:00Z"  # task_update
    t5 = "2026-08-01T12:00:00Z"  # assignment_change
    t6 = "2026-08-01T13:00:00Z"  # file_upload
    t7 = "2026-08-01T14:00:00Z"  # version_update
    t8 = "2026-08-01T15:00:00Z"  # batch_update
    transporte = _TransporteRunQuery(
        {
            "shotActivity": _respuesta_runquery(
                [
                    _doc(
                        _ruta_actividad("seguimiento"),
                        {
                            "type": "status_change",
                            "content": "Estado cambiado",
                            "userName": "Ana",
                            "role": "supervisor",  # normalización role -> userRole
                            "createdAt": t1,
                            "shotId": "shot_abc",
                            "previousState": "u1",
                            "previousStateName": "APROBADO",
                            "newState": "u2",
                            "newStateName": "ENTREGA",
                        },
                    ),
                    _doc(
                        _ruta_actividad("comentario"),
                        {
                            "type": "comment",
                            "content": "Buen plano",
                            "userName": "Ana",
                            "userRole": "artist",
                            "createdAt": t2,
                            "isPrivate": False,
                            "shotId": "shot_abc",
                        },
                    ),
                    _doc(
                        _ruta_actividad("respuesta"),
                        {
                            "type": "reply",
                            "parentId": "comentario",
                            "content": "Gracias",
                            "userName": "Luis",
                            "createdAt": t3,
                            "shotId": "shot_abc",
                        },
                    ),
                    _doc(
                        _ruta_actividad("tarea"),
                        {
                            "type": "task_update",
                            "taskId": "tk1",
                            "taskName": "Roto",
                            "completed": True,
                            "userName": "Ana",
                            "createdAt": t4,
                            "shotId": "shot_abc",
                        },
                    ),
                    _doc(
                        _ruta_actividad("asignacion"),
                        {
                            "type": "assignment_change",
                            "userName": "Ana",
                            "createdAt": t5,
                            "shotId": "shot_abc",
                            "previousAssignees": {
                                "primaryId": "a1",
                                "primaryName": "Emanuel Barriga",
                                "secondaryIds": ["a2"],
                                "secondaryNames": ["Luis M"],
                            },
                            "newAssignees": {
                                "primaryId": "a1",
                                "primaryName": "Emanuel Barriga",
                                "secondaryIds": ["a2", "a3"],
                                "secondaryNames": ["Luis M", "Carmen"],
                            },
                        },
                    ),
                    _doc(
                        _ruta_actividad("preview"),
                        {
                            "type": "file_upload",
                            "content": "preview.mov",
                            "userName": "Ana",
                            "createdAt": t6,
                            "shotId": "shot_abc",
                            "attachments": [
                                {
                                    "id": "at1",
                                    "type": "image",
                                    "url": "https://cdn.example/a.png",
                                    "name": "a.png",
                                }
                            ],
                        },
                    ),
                    _doc(
                        _ruta_actividad("version"),
                        {
                            "type": "version_update",
                            "userName": "Ana",
                            "createdAt": t7,
                            "shotId": "shot_abc",
                            "previousVersion": 1,
                            "newVersion": 2,
                        },
                    ),
                    _doc(
                        _ruta_actividad("batch"),
                        {
                            "type": "batch_update",
                            "content": "Task completada",
                            "userName": "Ana",
                            "createdAt": t8,
                            "shotId": "shot_abc",
                            "previousStateName": "APROBADO",
                            "newStateName": "ENTREGA",
                            "previousVersion": 2,
                            "newVersion": 3,
                        },
                    ),
                ]
            )
        }
    )
    _parchar_abrir(monkeypatch, transporte)

    res = vfxflow_datos.listar_actividad(
        "lxYgN96Zk8zyhsFEABOf", "shot_abc", "TOKEN_ID", config=_CONFIG
    )

    # Los 8 tipos incluidos, ordenados DESC por createdAt (mas reciente arriba).
    assert [a["type"] for a in res] == [
        "batch_update",
        "version_update",
        "file_upload",
        "assignment_change",
        "task_update",
        "reply",
        "comment",
        "status_change",
    ]
    assert [a["createdAt"] for a in res] == [t8, t7, t6, t5, t4, t3, t2, t1]

    # Campos proyectados por tipo.
    por_tipo = {a["type"]: a for a in res}
    estados = por_tipo["status_change"]
    assert estados["previousStateName"] == "APROBADO"
    assert estados["newStateName"] == "ENTREGA"
    assert por_tipo["version_update"]["previousVersion"] == 1
    assert por_tipo["version_update"]["newVersion"] == 2
    assert por_tipo["batch_update"]["previousVersion"] == 2
    assert por_tipo["batch_update"]["newVersion"] == 3
    adjuntos = por_tipo["file_upload"]["attachments"]
    assert adjuntos == [
        {"id": "at1", "type": "image", "url": "https://cdn.example/a.png", "name": "a.png"}
    ]
    asignacion = por_tipo["assignment_change"]
    assert asignacion["previousAssignees"]["primaryName"] == "Emanuel Barriga"
    assert asignacion["newAssignees"]["secondaryNames"] == ["Luis M", "Carmen"]
    assert por_tipo["task_update"]["taskName"] == "Roto"
    assert por_tipo["task_update"]["completed"] is True
    assert por_tipo["reply"]["parentId"] == "comentario"

    # Normalización: Firestore devolvió `role` (no `userRole`) => userRole.
    assert por_tipo["status_change"]["userRole"] == "supervisor"

    # La query de actividad NO lleva limit (trae todos) ni orderBy.
    actividad_q = [p for p in transporte.pedidos if p[0] == "shotActivity"]
    assert "limit" not in actividad_q[0][1]["structuredQuery"]
    assert "orderBy" not in actividad_q[0][1]["structuredQuery"]
    filtro = actividad_q[0][1]["structuredQuery"]["where"]["fieldFilter"]
    assert filtro["field"]["fieldPath"] == "shotId"
    assert filtro["value"]["stringValue"] == "shot_abc"
    # El parent de la URL es projects/{pid}, nunca projects/{pid}/shotActivity.
    url_actividad = actividad_q[0][2]
    assert url_actividad.endswith(
        "/documents/projects/lxYgN96Zk8zyhsFEABOf:runQuery"
    )
    assert "/shotActivity" not in url_actividad.split(":runQuery")[0]


def test_listar_comentarios_alias_devuelve_lo_mismo(monkeypatch):
    """El alias `listar_comentarios` delega en `listar_actividad` (compat)."""
    t1 = "2026-08-01T08:00:00Z"
    t2 = "2026-08-01T09:00:00Z"
    transporte = _TransporteRunQuery(
        {
            "shotActivity": _respuesta_runquery(
                [
                    _doc(
                        _ruta_actividad("viejo"),
                        {
                            "type": "comment",
                            "content": "a",
                            "userName": "Ana",
                            "userRole": "artist",
                            "createdAt": t1,
                            "shotId": "shot_abc",
                        },
                    ),
                    _doc(
                        _ruta_actividad("nuevo"),
                        {
                            "type": "file_upload",
                            "userName": "Luis",
                            "createdAt": t2,
                            "shotId": "shot_abc",
                        },
                    ),
                ]
            )
        }
    )
    _parchar_abrir(monkeypatch, transporte)

    res = vfxflow_datos.listar_comentarios(
        "lxYgN96Zk8zyhsFEABOf", "shot_abc", "TOKEN_ID", config=_CONFIG
    )
    esperado = vfxflow_datos.listar_actividad(
        "lxYgN96Zk8zyhsFEABOf", "shot_abc", "TOKEN_ID", config=_CONFIG
    )
    assert res == esperado
    assert [a["type"] for a in res] == ["file_upload", "comment"]  # DESC


def test_listar_comentarios_sin_coincidencias_devuelve_vacio(monkeypatch):
    transporte = _TransporteRunQuery(
        {"shotActivity": _respuesta_runquery([])}
    )
    _parchar_abrir(monkeypatch, transporte)

    res = vfxflow_datos.listar_comentarios(
        "lxYgN96Zk8zyhsFEABOf", "shot_abc", "TOKEN_ID", config=_CONFIG
    )
    assert res == []


def test_listar_actividad_solo_tipos_desconocidos_devuelve_vacio(monkeypatch):
    transporte = _TransporteRunQuery(
        {
            "shotActivity": _respuesta_runquery(
                [
                    _doc(
                        _ruta_actividad("sis"),
                        {"type": "system", "shotId": "shot_abc"},
                    )
                ]
            )
        }
    )
    _parchar_abrir(monkeypatch, transporte)

    res = vfxflow_datos.listar_actividad(
        "lxYgN96Zk8zyhsFEABOf", "shot_abc", "TOKEN_ID", config=_CONFIG
    )
    assert res == []


def test_listar_comentarios_401_lanza_token(monkeypatch):
    transporte = _TransporteRunQuery({"shotActivity": 401})
    _parchar_abrir(monkeypatch, transporte)

    with pytest.raises(VfxFlowAuthError) as exc:
        vfxflow_datos.listar_comentarios(
            "lxYgN96Zk8zyhsFEABOf", "shot_abc", "TOKEN_VENCIDO", config=_CONFIG
        )
    assert exc.value.codigo == "token"


# --------------------------------------------------------------------------
# transporte POST autenticado (vfxflow_auth._post_json_bearer)
# --------------------------------------------------------------------------


def test_post_json_bearer_error_de_red_lanza_codigo_red(monkeypatch):
    def _fake(req, *args, **kwargs):
        raise socket.timeout("timed out")

    _parchar_abrir(monkeypatch, _fake)
    with pytest.raises(VfxFlowAuthError) as exc:
        vfxflow_auth._post_json_bearer(
            "https://firestore.googleapis.com/v1/projects/vfxpm-be912/databases/(default)/documents:runQuery",
            {"structuredQuery": {}},
            "TOKEN_ID",
        )
    assert exc.value.codigo == "red"


def test_post_json_bearer_404_devuelve_none(monkeypatch):
    def _fake(req, *args, **kwargs):
        raise _error_http(404, {"error": {"message": "not found"}})

    _parchar_abrir(monkeypatch, _fake)
    res = vfxflow_auth._post_json_bearer(
        "https://firestore.googleapis.com/v1/projects/vfxpm-be912/databases/(default)/documents:runQuery",
        {"structuredQuery": {}},
        "TOKEN_ID",
    )
    assert res is None


# --------------------------------------------------------------------------
# obtener_colores_estados (projectStates -> {stateId: color})
# --------------------------------------------------------------------------


def test_obtener_colores_estados_mapa(monkeypatch):
    transporte = _TransporteRunQuery(
        {
            "projectStates": _respuesta_runquery(
                [
                    _doc(
                        NOMBRE_PROYECTO + "/projectStates/est1",
                        {"projectId": "lxYgN96Zk8zyhsFEABOf", "color": "#f59e0b"},
                    ),
                    _doc(
                        NOMBRE_PROYECTO + "/projectStates/est2",
                        {"projectId": "lxYgN96Zk8zyhsFEABOf", "color": "#22c55e"},
                    ),
                ]
            )
        }
    )
    _parchar_abrir(monkeypatch, transporte)

    res = vfxflow_datos.obtener_colores_estados(
        "lxYgN96Zk8zyhsFEABOf", "TOKEN_ID", config=_CONFIG
    )
    assert res == {"est1": "#f59e0b", "est2": "#22c55e"}
    estados = [p for p in transporte.pedidos if p[0] == "projectStates"]
    assert estados
    assert estados[0][1]["structuredQuery"]["from"][0]["collectionId"] == "projectStates"


def test_obtener_colores_estados_omite_docs_sin_color(monkeypatch):
    transporte = _TransporteRunQuery(
        {
            "projectStates": _respuesta_runquery(
                [
                    _doc(
                        NOMBRE_PROYECTO + "/projectStates/est1",
                        {"projectId": "lxYgN96Zk8zyhsFEABOf", "color": "#f59e0b"},
                    ),
                    _doc(
                        NOMBRE_PROYECTO + "/projectStates/est2",
                        {"projectId": "lxYgN96Zk8zyhsFEABOf"},
                    ),
                ]
            )
        }
    )
    _parchar_abrir(monkeypatch, transporte)

    res = vfxflow_datos.obtener_colores_estados(
        "lxYgN96Zk8zyhsFEABOf", "TOKEN_ID", config=_CONFIG
    )
    assert res == {"est1": "#f59e0b"}


def test_obtener_colores_estados_vacio_devuelve_vacio(monkeypatch):
    transporte = _TransporteRunQuery(
        {"projectStates": _respuesta_runquery([])}
    )
    _parchar_abrir(monkeypatch, transporte)

    assert (
        vfxflow_datos.obtener_colores_estados(
            "lxYgN96Zk8zyhsFEABOf", "TOKEN_ID", config=_CONFIG
        )
        == {}
    )


def test_obtener_colores_estados_error_devuelve_vacio(monkeypatch):
    """Ante error http/token NUNCA rompe el feed: devuelve {}."""
    transporte = _TransporteRunQuery({"projectStates": 401})
    _parchar_abrir(monkeypatch, transporte)

    assert (
        vfxflow_datos.obtener_colores_estados(
            "lxYgN96Zk8zyhsFEABOf", "TOKEN_ID", config=_CONFIG
        )
        == {}
    )