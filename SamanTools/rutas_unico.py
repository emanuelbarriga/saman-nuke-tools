"""
Política de nodo único de rutas para el nodo autocontenido `RutasV2` (3.0.0).

Recupera del plugin original (SamanTools/rutas.py) las ideas de detección por
knobs, marcador de versión y fusión del estado, y las aplica a los nodos nuevos
y a los viejos:

  - `es_nodo_rutas`          detecta por knobs, NUNCA por nombre (rutas.py:603).
  - `es_version_actual`      marcador de versión del nodo (rutas.py:638).
  - `encontrar_nodos_rutas`  todos los nodos de rutas del comp (rutas.py:629).
  - `avisar_duplicados`      la UX de "solo avisar si no se puede borrar"
                             (rutas.py:833) que se reusa para la cancelación.

Acciones publicas:

  - `aplicar_politica_al_cargar` es el hook de `nuke.addOnScriptLoad`: fusiona
    duplicados al abrir un comp y NUNCA inserta nodos (S11). Cuando deja un
    nodo vivo en el comp empuja su entorno (`PYTHON_*`) a este Nuke.
  - `crear_o_actualizar` es la accion EXPLICITA de menu, equivalente a
    `rutas.crear_o_reutilizar` (rutas.py:777): crea el nodo si no hay ninguno,
    reutiliza el actual y ACTUALIZA un nodo viejo conservando estado y posicion.
  - `sincronizar_entorno` ejecuta el motor embebido del nodo con la accion
    `sync`, como su propio `onCreate`: es lo que `rutas.aplicar_variables_
    desde_nodo` (rutas.py:245) hacia en 2.0.0, para que las expresiones
    `[python {PYTHON_*}]` de los Reads queden resueltas al abrir el comp.
  - `proyecto_activo` da el nombre del proyecto para las etiquetas de menu.

La actualizacion NO usa el repaste knob-por-knob de `_reconstruir_nodo`
(rutas.py:701): el nodo nuevo es autocontenido, asi que se pega el gizmo
instalado y en el nodo NUEVO se escribe el estado normalizado (`db_json`) y se
restaura la posicion; recien entonces se borra el viejo. En el hook de carga un
nodo viejo SE CONSERVA tal cual (con sus knobs y su posicion) y solo aporta su
estado a la fusion.

Este módulo se importa fuera de Nuke: `import nuke` va SIEMPRE dentro de las
funciones. Los tests usan el stub de `tests/conftest.py`.

Esquema de `db_json` (derivado, no inventado)
=============================================

Evidencia en el motor embebido de
`/Users/servermac/Documents/Nodos Saman/Nodos Estables/RutasV2_v2.gizmo`:

  - Declaración del knob (línea 71): `addUserKnob {1 db_json l "JSON crudo
    (editable)"}`; el valor por defecto (línea 72) es el JSON con
    `"active_user": "Mac"`, la lista `"folders"` y el objeto `"users"`.
  - `folders` es lista de objetos con identidad `id`; el default trae
    `{"id": "TO_VFX", "label": "Material Original", "knob": "folder_TO_VFX"}`,
    `COMP`/"Composiciones", `ASSETS`/"Assets" y `FROM_VFX`/"Entregas".
  - `users` es objeto nombre -> objeto `id_de_carpeta` -> ruta; el default trae
    `Mac`, `Linux`, `Windows` y `MacLocal`.
  - `_normalizar_db` del motor: `folders` sólo admite dicts con `id` str no
    vacío, `users` sólo dicts de dicts con valores coercidos a str, y
    `active_user` toma `''` si falta.
  - `_vars_de_panel`/`push_env`: la ruta se publica como `PYTHON_<ID>` en
    `__main__`, `nuke`, `os.environ` y `nuke.tcl`, más `PYTHON_CAP`,
    `PYTHON_CAP_DIR` y `PYTHON_CAP_NUM` (que no viven en la db).
  - `refresh_ui_values`/`knob_changed`: la ruta que muestra cada Knob File es
    `users[<pulldown>][<id>]`, y el knob `folder_<ID>` escribe exactamente ahí
    (con `/` final normalizado). `active_user` es el valor de `pulldown`.

Resumen del esquema:

    {
      "active_user": "<nombre de usuario>",
      "folders": [{"id": "TO_VFX", "label": "...", "knob": "folder_TO_VFX"}, ...],
      "users": {"<usuario>": {"TO_VFX": "/ruta/", "COMP": "/ruta/", ...}, ...}
    }

Un nodo viejo (knobs clásicos `UsuarioActivo` + `TO_VFX_SERVER_*`) se normaliza
a ese mismo esquema en `db_de`, y sus knobs crudos no interpretados quedan bajo
`legacy_knobs` para no perder nada (S9).
"""

import copy
import json
import os
import re

# Versión del nodo que esta política considera actual (S4: marcador de versión).
NODO_VER_ACTUAL = 1
KNOB_VERSION = "nodo_ver"
KNOB_ESTADO = "db_json"
# Knob oculto con el motor embebido del nodo (se ejecuta, no se interpreta).
KNOB_MOTOR = "Cerebro_Python"

# ---------------------------------------------------------------------------
# Esquema nuevo (RutasV2)
# ---------------------------------------------------------------------------

# Orden canónico de carpetas del JSON por defecto del gizmo.
_ORDEN_CARPETAS = ("TO_VFX", "COMP", "ASSETS", "FROM_VFX")

# Etiquetas del JSON por defecto del gizmo (línea 72 de RutasV2_v2.gizmo).
_ETIQUETAS_CARPETA = {
    "TO_VFX": "Material Original",
    "COMP": "Composiciones",
    "ASSETS": "Assets",
    "FROM_VFX": "Entregas",
}

# Claves del JSON que la política interpreta; el resto se copia tal cual.
_CLAVES_ESQUEMA = ("active_user", "folders", "users")

# Knobs estructurales que nunca se copian a legacy_knobs (Cerebro_Python pesa
# decenas de KB y se reescribe solo).
_KNOBS_ESTRUCTURALES = (KNOB_ESTADO, KNOB_VERSION, KNOB_MOTOR)

# ---------------------------------------------------------------------------
# Mundo viejo (nodo legacy de knobs clásicos, rutas.py)
# ---------------------------------------------------------------------------

# rutas.py:23 -> {"MacServer": "MAC", "Windows": "WINDOWS", "Artist": "ARTIST"}.
# Se conserva el nombre de usuario viejo TAL CUAL en la fusión: renombrarlo a
# Mac/Linux/Windows pisaría rutas del superviviente y perdería las del viejo.
_SUFIJOS_CLASICOS = (
    ("MAC", "MacServer"),
    ("WINDOWS", "Windows"),
    ("ARTIST", "Artist"),
)

# rutas.py:428 (KNOBS_RUTAS_BASE): prefijo de knob clásico -> id de carpeta nuevo.
_CARPETAS_CLASICAS = (
    ("TO_VFX_SERVER_", "TO_VFX"),
    ("comp_SERVER_", "COMP"),
    ("FROM_VFX_SERVER_", "FROM_VFX"),
)

_KNOB_USUARIO_CLASICO = "UsuarioActivo"

# Señales de detección del nodo viejo: con cualquiera de estos knobs alcanza
# (rutas.py:603), porque usa TO_VFX_SERVER_* y no RutaActual.
_SENALES_CLASICAS = ("TO_VFX_SERVER_MAC", "TO_VFX_SERVER_WINDOWS", "TO_VFX_SERVER_ARTIST")


# ---------------------------------------------------------------------------
# Acceso tolerante a nodos y knobs
# ---------------------------------------------------------------------------


def _knob(nodo, nombre):
    """Knob `nombre` del nodo, o None. Tolera stubs y nodos raros."""
    if nodo is None:
        return None
    try:
        buscador = getattr(nodo, "knob", None)
        if buscador is not None:
            return buscador(nombre)
    except Exception:
        return None
    try:
        return (nodo.knobs() or {}).get(nombre)
    except Exception:
        return None


def _valor(nodo, nombre, defecto=""):
    """Valor del knob `nombre`, o `defecto`. Nunca lanza."""
    k = _knob(nodo, nombre)
    if k is None:
        return defecto
    try:
        return k.value()
    except Exception:
        return defecto


def _nombres_de_knobs(nodo):
    """Lista de nombres de knobs del nodo (vacía si no se puede leer)."""
    try:
        return list((nodo.knobs() or {}).keys())
    except Exception:
        return []


def _nombre(nodo):
    """Nombre del nodo como str, o None. Tolerante."""
    if nodo is None:
        return None
    try:
        return str(nodo.name())
    except Exception:
        return None


def _en_headless():
    """True en Nuke sin GUI (-t / render). Sin atributo GUI se asume GUI."""
    try:
        import nuke

        return not bool(getattr(nuke, "GUI", True))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Detección (S3, S4): por knobs, nunca por nombre
# ---------------------------------------------------------------------------


def es_nodo_rutas(nodo):
    """
    True si el nodo es un nodo de rutas, nuevo o viejo. No depende del nombre:
    el artista puede renombrarlo y se sigue detectando.

    Acepta los DOS mundos:
      - nodo nuevo autocontenido: tiene el knob `db_json`;
      - nodo viejo: `UsuarioActivo` + algún `TO_VFX_SERVER_*` (rutas.py:603).

    Tolerante a None y a nodos que no exponen knobs.
    """
    if nodo is None:
        return False
    knobs = _nombres_de_knobs(nodo)
    if not knobs:
        return False
    if KNOB_ESTADO in knobs:
        return True
    if _KNOB_USUARIO_CLASICO not in knobs:
        return False
    return any(senal in knobs for senal in _SENALES_CLASICAS)


def es_version_actual(nodo):
    """
    True si el nodo declara la versión actual de la política: el knob
    `nodo_ver` vale NODO_VER_ACTUAL (1). Un nodo sin el knob es de una versión
    anterior (rutas.py:638, adaptado al marcador explícito).

    Se compara numéricamente para tolerar "1" guardado como texto en un comp.
    """
    if nodo is None:
        return False
    k = _knob(nodo, KNOB_VERSION)
    if k is None:
        return False
    try:
        return int(float(k.value())) == NODO_VER_ACTUAL
    except Exception:
        return False


def encontrar_nodos_rutas():
    """
    Todos los nodos de rutas del script actual, en el orden de
    `nuke.allNodes()` (orden estable para el desempate de S8).

    Igual que rutas.py:629 no entra en grupos: el hook de carga trabaja sobre
    el comp abierto, que es donde la política tiene que garantizar el nodo único.
    """
    try:
        import nuke

        todos = nuke.allNodes()
    except Exception:
        return []
    return [n for n in todos if es_nodo_rutas(n)]


# ---------------------------------------------------------------------------
# Estado: db_json normalizado, nuevo o viejo (S9)
# ---------------------------------------------------------------------------


def _db_vacia():
    """Estado mínimo, ya en el esquema nuevo."""
    return {"active_user": "", "folders": [], "users": {}}


def _normalizar_db(data):
    """
    Copia usable del esquema nuevo. NUNCA modifica la entrada.

    Reglas tomadas de `_normalizar_db` del motor del gizmo: `folders` sólo
    conserva dicts con `id` str no vacío, `users` sólo dicts de dicts con
    valores str, `active_user` cae a "". Además se deduplica `folders` por `id`
    (el primero gana) para que la fusión no pueda duplicar una carpeta.

    Las claves que la política no interpreta se copian tal cual, incluidas las
    de cada usuario y de cada carpeta.
    """
    base = copy.deepcopy(data) if isinstance(data, dict) else {}

    carpetas = base.get("folders")
    if not isinstance(carpetas, list):
        carpetas = []
    limpias = []
    vistos = []
    for f in carpetas:
        if not isinstance(f, dict):
            continue
        fid = f.get("id")
        if not isinstance(fid, str) or not fid.strip():
            continue
        if fid in vistos:
            continue
        vistos.append(fid)
        limpias.append(copy.deepcopy(f))

    usuarios = base.get("users")
    if not isinstance(usuarios, dict):
        usuarios = {}
    usuarios_ok = {}
    for nombre, rutas in usuarios.items():
        if not isinstance(rutas, dict):
            continue
        usuarios_ok[str(nombre)] = {
            str(k): (v if isinstance(v, str) else "") for k, v in rutas.items()
        }

    activo = base.get("active_user")
    base["active_user"] = activo if isinstance(activo, str) else ""
    base["folders"] = limpias
    base["users"] = usuarios_ok
    return base


def _knobs_sueltos(nodo, excluidos):
    """
    Knobs escalares no vacíos del nodo, crudos, para `legacy_knobs`.

    Excluye los estructurales (db_json, nodo_ver, Cerebro_Python) y los que la
    normalización ya interpretó (se pasan en `excluidos`). Los valores no
    escalares (knob arrays, colores) se saltean: no son transportables al JSON.
    """
    salida = {}
    for nombre in _nombres_de_knobs(nodo):
        if nombre in _KNOBS_ESTRUCTURALES or nombre in excluidos:
            continue
        valor = _valor(nodo, nombre, None)
        if isinstance(valor, bool):
            salida[nombre] = valor
        elif isinstance(valor, (int, float)):
            salida[nombre] = valor
        elif isinstance(valor, str) and valor.strip():
            salida[nombre] = valor
    return salida


def _orden_carpeta(fid):
    """Orden canónico de carpetas conocidas; las desconocidas van al final."""
    try:
        return (_ORDEN_CARPETAS.index(fid), "")
    except ValueError:
        return (len(_ORDEN_CARPETAS), fid)


def _db_desde_knobs_clasicos(nodo):
    """
    Normaliza un nodo viejo al esquema nuevo (S9): sus rutas y su usuario no se
    pierden.

    - `TO_VFX_SERVER_<SUF>`     -> users[<usuario>]["TO_VFX"]
    - `comp_SERVER_<SUF>`       -> users[<usuario>]["COMP"]
    - `FROM_VFX_SERVER_<SUF>`   -> users[<usuario>]["FROM_VFX"]
    - `UsuarioActivo`           -> active_user

    El usuario viejo conserva su nombre ("MacServer"/"Windows"/"Artist"): es su
    identidad en el comp y renombrarlo fusionaría en silencio rutas distintas.
    """
    consumidos = []
    usuarios = {}
    for sufijo, usuario in _SUFIJOS_CLASICOS:
        rutas = {}
        for prefijo, fid in _CARPETAS_CLASICAS:
            nombre = prefijo + sufijo
            consumidos.append(nombre)
            if nombre not in _nombres_de_knobs(nodo):
                continue
            valor = _valor(nodo, nombre, "")
            if isinstance(valor, str) and valor.strip():
                rutas[fid] = valor
        if rutas:
            usuarios[usuario] = rutas

    activo = _valor(nodo, _KNOB_USUARIO_CLASICO, "")
    activo = str(activo).strip() if isinstance(activo, str) else ""
    # UsuarioActivo NO va a `consumidos`: se conserva crudo en legacy_knobs
    # porque es el nombre completo del usuario viejo ("MacServer", no "MAC").
    if activo:
        usuarios.setdefault(activo, {})

    carpetas = []
    usadas = []
    for rutas in usuarios.values():
        for fid in rutas:
            if fid not in usadas:
                usadas.append(fid)
    for fid in sorted(usadas, key=_orden_carpeta):
        carpetas.append(
            {
                "id": fid,
                "label": _ETIQUETAS_CARPETA.get(fid, fid),
                "knob": "folder_" + fid,
            }
        )

    db = {
        "active_user": activo if activo in usuarios else "",
        "folders": carpetas,
        "users": usuarios,
    }
    sueltos = _knobs_sueltos(nodo, consumidos)
    if sueltos:
        db["legacy_knobs"] = sueltos
    return _normalizar_db(db)


def db_de(nodo):
    """
    Estado normalizado del nodo, en el esquema nuevo, sea nuevo o viejo.

    - Nodo nuevo: parsea `db_json` y lo normaliza (conserva claves desconocidas).
    - Nodo viejo: se deriva de sus knobs clásicos y los crudos quedan en
      `legacy_knobs` (S9, el viejo aporta rutas y usuario, no se descarta).
    - `db_json` ilegible: si el nodo además tiene knobs clásicos se usa esa vía
      y el texto crudo queda en `legacy_knobs["db_json_crudo"]`; si no, estado
      vacío. Nunca lanza y nunca escribe en el nodo.
    """
    if nodo is None:
        return _db_vacia()

    tiene_estado = _knob(nodo, KNOB_ESTADO) is not None
    if tiene_estado:
        crudo = _valor(nodo, KNOB_ESTADO, "")
        try:
            return _normalizar_db(json.loads(crudo))
        except Exception:
            db = _db_desde_knobs_clasicos(nodo)
            texto = crudo if isinstance(crudo, str) else str(crudo)
            if texto.strip():
                db.setdefault("legacy_knobs", {})["db_json_crudo"] = texto
            return db

    return _db_desde_knobs_clasicos(nodo)


# ---------------------------------------------------------------------------
# Fusión (S7, S8, S9)
# ---------------------------------------------------------------------------


def _contenido(db):
    """Peso del nodo para S8: carpetas + usuarios declarados."""
    carpetas = db.get("folders") or []
    usuarios = db.get("users") or {}
    return len(carpetas) + len(usuarios)


def elegir_superviviente(nodos):
    """
    Superviviente de la fusión (S8): el nodo de versión actual con más
    contenido (`folders` + `users`); desempate por orden de `nuke.allNodes()`
    (el orden en que llegan los nodos); un nodo de versión vieja nunca gana
    sobre uno actual.

    Devuelve el nodo, o None si la lista está vacía.
    """
    mejor = None
    mejor_clave = None
    for nodo in nodos or []:
        if nodo is None:
            continue
        db = db_de(nodo)
        clave = (1 if es_version_actual(nodo) else 0, _contenido(db))
        if mejor_clave is None or clave > mejor_clave:
            mejor = nodo
            mejor_clave = clave
    return mejor


def fusionar_dbs(dbs):
    """
    Puro (sin nuke): fusiona estados ya normalizados, EN ORDEN, sobre el
    primero (que es el superviviente). No modifica las entradas.

    - `folders`: unión por `id`; gana la definición del superviviente.
    - `users`: unión por nombre y, dentro de cada usuario, unión de rutas por
      `id` de carpeta: el superviviente conserva sus rutas y sólo se completan
      las que le faltan o están vacías.
    - Claves desconocidas: las del superviviente se copian tal cual; las de los
      demás sólo se agregan si el superviviente no las tiene (nada se pierde y
      nada se pisa).
    - `active_user`: se conserva el del superviviente si sigue siendo válido;
      si no, el primer usuario fusionado, o "" si no hay usuarios.

    El esquema se copia, nunca se reconstruye desde cero (S9).
    """
    lista = [d for d in (dbs or []) if isinstance(d, dict)]
    if not lista:
        return _db_vacia()

    base = _normalizar_db(lista[0])
    ids_vistos = [f["id"] for f in base["folders"]]

    for otro in lista[1:]:
        db = _normalizar_db(otro)

        for carpeta in db["folders"]:
            if carpeta["id"] in ids_vistos:
                continue
            base["folders"].append(copy.deepcopy(carpeta))
            ids_vistos.append(carpeta["id"])

        for usuario, rutas in db["users"].items():
            destino = base["users"].setdefault(usuario, {})
            for fid, valor in rutas.items():
                actual = destino.get(fid)
                if isinstance(actual, str) and actual.strip():
                    continue
                destino[fid] = valor

        for clave, valor in db.items():
            if clave in _CLAVES_ESQUEMA:
                continue
            if clave not in base:
                base[clave] = copy.deepcopy(valor)

    if base.get("active_user") not in base["users"]:
        base["active_user"] = next(iter(base["users"]), "")
    return base


def _escribir_estado(nodo, db):
    """Escribe el estado normalizado en `db_json`. False si no hay knob."""
    k = _knob(nodo, KNOB_ESTADO)
    if k is None:
        return False
    texto = json.dumps(db, indent=2)
    k.setValue(texto)
    return True


def _puede_recibir_estado(nodo):
    """True si el nodo puede guardar el estado fusionado (tiene db_json)."""
    return _knob(nodo, KNOB_ESTADO) is not None


def _iniciar_undo(nombre):
    """No abre ningún grupo de undo, a propósito.

    Nuke ya agrupa el comando de menú en un solo paso. La versión anterior
    llamaba a `nuke.Undo()` y a `nuke.EndUndo()` sin balance: no abría un grupo
    propio y cerraba el que Nuke había abierto para el comando, dejando el stack
    de undo inconsistente. Eso cerraba Nuke al insertar un segundo nodo de
    rutas. Se conserva la función para no tocar los llamadores.
    """
    return False


def _cerrar_undo(abierto):
    """No cierra nada: ver `_iniciar_undo`. Nunca lanza."""
    return


def _preguntar(texto):
    """`nuke.ask` tolerante: sin GUI o sin `ask` se asume NO (nada destructivo)."""
    try:
        import nuke

        preguntar = getattr(nuke, "ask", None)
        if preguntar is None:
            return False
        return bool(preguntar(texto))
    except Exception:
        return False


def _posicion(nodo):
    """(x, y) del nodo, o None si no se puede leer."""
    if nodo is None:
        return None
    try:
        return (nodo.xpos(), nodo.ypos())
    except Exception:
        return None


def _restaurar_posicion(nodo, posicion):
    """Devuelve el nodo a `posicion`. False si no se pudo."""
    if nodo is None or not posicion:
        return False
    setter = getattr(nodo, "setXYpos", None)
    if setter is None:
        return False
    try:
        setter(posicion[0], posicion[1])
        return True
    except Exception:
        return False


def _seleccionar(nodo):
    """Deja a `nodo` como unica seleccion. Tolerante (rutas.py:653)."""
    try:
        import nuke

        for otro in nuke.allNodes():
            deseleccionar = getattr(otro, "setSelected", None)
            if deseleccionar is not None:
                deseleccionar(False)
    except Exception:
        pass
    if nodo is None:
        return
    try:
        seleccionar = getattr(nodo, "setSelected", None)
        if seleccionar is not None:
            seleccionar(True)
    except Exception:
        pass


def _centro_de_la_vista():
    """(x, y) del centro visible del Node Graph, o None si no se puede leer.

    `nuke.center()` devuelve el centro del display del grupo, que es
    exactamente la forma que `nuke.zoom()` acepta como centro del DAG: son
    coordenadas de nodo, las mismas de `xpos`/`ypos`.
    """
    try:
        import nuke

        centro = nuke.center()
    except Exception:
        return None
    if not centro:
        return None
    try:
        return (int(centro[0]), int(centro[1]))
    except Exception:
        return None


def _widget_del_dag():
    """El widget Qt del Node Graph (un QGraphicsView), o None.

    Se busca por `objectName()`, que empieza con "DAG." (Nuke numera el widget
    según cuántas ventanas de Node Graph haya abiertas), recorriendo el árbol de
    widgets sin recursión profunda.
    """
    try:
        try:
            from PySide6 import QtWidgets
        except ImportError:
            from PySide2 import QtWidgets
    except Exception:
        return None
    try:
        pendientes = list(QtWidgets.QApplication.topLevelWidgets())
    except Exception:
        return None

    vistos = set()
    while pendientes:
        widget = pendientes.pop()
        if id(widget) in vistos:
            continue
        vistos.add(id(widget))
        try:
            nombre = widget.objectName() or ""
        except Exception:
            nombre = ""
        if nombre.startswith("DAG."):
            return widget
        try:
            hijos = widget.children()
        except Exception:
            continue
        for hijo in hijos:
            try:
                if hijo.isWidgetType():
                    pendientes.append(hijo)
            except Exception:
                continue
    return None


def _cursor_global():
    """Posición global del mouse, o None."""
    try:
        try:
            from PySide6 import QtGui
        except ImportError:
            from PySide2 import QtGui
    except Exception:
        return None
    try:
        return QtGui.QCursor.pos()
    except Exception:
        return None


def _posicion_del_cursor():
    """(x, y) en coordenadas de nodo bajo el mouse del Node Graph, o None.

    Se mapea el cursor global al QGraphicsView del DAG: `mapToScene` devuelve
    coordenadas de escena, que son exactamente las de `xpos`/`ypos`. **No se
    crea ni se borra ningún nodo**: la versión anterior creaba un `NoOp`
    descartable para leer su posición y lo borraba, y eso cerraba Nuke al
    insertar un segundo nodo de rutas.
    """
    if _en_headless():
        return None
    dag = _widget_del_dag()
    cursor = _cursor_global()
    if dag is None or cursor is None:
        return None
    try:
        escena = dag.mapToScene(dag.mapFromGlobal(cursor))
    except Exception:
        return None
    try:
        return (int(escena.x()), int(escena.y()))
    except Exception:
        return None


def _posicion_de_insercion():
    """Dónde va el nodo cuando ya existe: el cursor; si no, el centro visible."""
    posicion = _posicion_del_cursor()
    if posicion is not None:
        return posicion
    return _centro_de_la_vista()


def _mover_a_la_vista(nodo):
    """Pone `nodo` donde aparece un nodo recién creado: bajo el cursor.

    Devuelve True si lo movió. En headless no hay cursor que respetar.
    """
    if nodo is None or _en_headless():
        return False
    posicion = _posicion_de_insercion()
    if posicion is None:
        return False
    return _restaurar_posicion(nodo, posicion)


def _mostrar_en_la_vista(nodo):
    """Pone el nodo donde nace uno nuevo: bajo el cursor, sin mover la vista.

    Es lo contrario de `_enfocar`: no hace zoom ni pan (no toca
    `zoomToFitSelected`), trae el nodo al cursor y abre su panel. El nodo
    descartable que se usa para leer el cursor y el movimiento van en el mismo
    paso de undo, para que el artista deshaga todo junto.
    """
    abierto = _iniciar_undo("Nodo de rutas al cursor")
    try:
        movido = _mover_a_la_vista(nodo)
    finally:
        _cerrar_undo(abierto)
    _seleccionar(nodo)
    abrir = getattr(nodo, "showControlPanel", None) if nodo is not None else None
    if abrir is not None:
        try:
            abrir()
        except Exception:
            pass
    return movido


def _enfocar(nodo):
    """Selecciona, centra el Node Graph y abre el panel del nodo (rutas.py:676)."""
    _seleccionar(nodo)
    try:
        import nuke

        if hasattr(nuke, "zoomToFitSelected"):
            nuke.zoomToFitSelected()
    except Exception:
        pass
    abrir = getattr(nodo, "showControlPanel", None) if nodo is not None else None
    if abrir is not None:
        try:
            abrir()
        except Exception:
            pass


def _asegurar_version(nodo):
    """Deja `nodo_ver` en NODO_VER_ACTUAL (S4).

    Si el nodo ya declara el knob se corrige su valor; si el gizmo instalado
    todavía no trae el marcador se agrega, pero SÓLO sobre un nodo de rutas
    real (con `db_json`): marcar como "versión actual" cualquier otro nodo
    sería mentir sobre lo que hay en el comp.
    """
    k = _knob(nodo, KNOB_VERSION)
    if k is None:
        return _agregar_marcador_version(nodo)
    if es_version_actual(nodo):
        return True
    try:
        k.setValue(NODO_VER_ACTUAL)
        return es_version_actual(nodo)
    except Exception:
        return False


def _agregar_marcador_version(nodo):
    """Agrega el knob `nodo_ver` a un nodo de rutas que no lo declara."""
    if nodo is None or _knob(nodo, KNOB_ESTADO) is None:
        return False
    try:
        import nuke

        fabricar = getattr(nuke, "Int_Knob", None)
        agregar = getattr(nodo, "addKnob", None)
        if fabricar is None or agregar is None:
            return False
        agregar(fabricar(KNOB_VERSION, ""))
        k = _knob(nodo, KNOB_VERSION)
        if k is None:
            return False
        k.setValue(NODO_VER_ACTUAL)
        return es_version_actual(nodo)
    except Exception:
        return False


def _avisar(texto):
    """Avisa por la vía que exista. Nunca lanza."""
    try:
        import nuke

        nuke.message(texto)
        return
    except Exception:
        pass
    try:
        print(texto)
    except Exception:
        pass


def _resultado(accion, nodos, superviviente, detalle):
    """Armazón del informe que consume el bootstrap."""
    return {
        "accion": accion,
        "nodos": nodos,
        "superviviente": superviviente,
        "detalle": detalle,
    }


# ---------------------------------------------------------------------------
# Entorno del comp: variables PYTHON_* y proyecto activo (S4)
# ---------------------------------------------------------------------------

# En la matriz de rutas el proyecto es el segmento INMEDIATAMENTE anterior a
# una carpeta base; es la convención que ya usa `rutas._reescribir_proyecto_
# en_rutas` (rutas.py:288) para reemplazar el proyecto en las 9 rutas.
_RE_PROYECTO_EN_RUTA = re.compile(
    r"/([^/]+)/(TO_VFX|COMP|ASSETS|FROM_VFX)(?:/|$)", re.IGNORECASE
)

# Último recurso de `proyecto_activo`: sin estado y sin nombre de comp.
PROYECTO_POR_DEFECTO = "Proyecto"


def _proyecto_en_ruta(ruta):
    """Segmento de proyecto de una ruta de carpetas, o None. Nunca lanza."""
    if not isinstance(ruta, str) or not ruta.strip():
        return None
    try:
        encontrado = _RE_PROYECTO_EN_RUTA.search(ruta.replace("\\", "/"))
    except Exception:
        return None
    if not encontrado:
        return None
    proyecto = encontrado.group(1).strip()
    return proyecto or None


def _rutas_del_usuario_activo(db):
    """Rutas del usuario activo del estado; si no es válido, las del primero."""
    usuarios = db.get("users") or {}
    activo = db.get("active_user") or ""
    if activo in usuarios:
        return usuarios.get(activo) or {}
    for nombre in usuarios:
        return usuarios.get(nombre) or {}
    return {}


def _proyecto_de_estado(nodo):
    """Proyecto derivado de la ruta de la carpeta COMP del usuario activo."""
    return _proyecto_en_ruta(_rutas_del_usuario_activo(db_de(nodo)).get("COMP"))


def _proyecto_de_root():
    """Proyecto del comp abierto, desde `nuke.root().name()` (rutas.py:66)."""
    try:
        import nuke

        raiz = getattr(nuke, "root", None)
        ruta = raiz().name() if raiz is not None else ""
    except Exception:
        return None
    if not isinstance(ruta, str) or not ruta.strip():
        return None
    proyecto = _proyecto_en_ruta(ruta)
    if proyecto:
        return proyecto
    # v1 (`_sincronizar_plano`) parseaba el nombre del comp; se conserva como
    # tolerancia para comps que no viven bajo una carpeta TO_VFX/COMP/etc.
    try:
        from SamanTools import nombres

        return (nombres.parsear_plato(ruta) or {}).get("proyecto")
    except Exception:
        return None


def proyecto_activo():
    """
    Nombre del proyecto para las etiquetas de menú.

    Precedencia: el estado normalizado del nodo de rutas del comp (la ruta de
    la carpeta COMP del usuario activo), después el segmento de proyecto de
    `nuke.root().name()` (lo que hacía `_sincronizar_plano`, rutas.py:66) y por
    último "Proyecto". Nunca lanza y siempre devuelve str.
    """
    proyecto = None
    try:
        proyecto = _proyecto_de_estado(elegir_superviviente(encontrar_nodos_rutas()))
    except Exception:
        proyecto = None
    if not proyecto:
        try:
            proyecto = _proyecto_de_root()
        except Exception:
            proyecto = None
    if not isinstance(proyecto, str) or not proyecto.strip():
        return PROYECTO_POR_DEFECTO
    return proyecto.strip()


def sincronizar_entorno(nodo=None):
    """
    Empuja el entorno (`PYTHON_*`) del nodo ejecutando su motor embebido con la
    acción `sync`, exactamente como su propio `onCreate`:

        exec(nodo.knob('Cerebro_Python').value())
        rutas_engine('sync')

    Es el reemplazo v3 de `rutas.aplicar_variables_desde_nodo` (rutas.py:245):
    abrir un comp en un Nuke nuevo tiene que dejar resueltas las expresiones
    `[python {PYTHON_*}]` de los Reads sin que nadie toque el nodo. `sync`
    define las variables y refresca el panel; `reload_reads` es una acción
    aparte y NO se usa al cargar.

    `nodo` es opcional: sin argumento se usa el nodo de rutas del comp. Devuelve
    True sólo si el motor se ejecutó de verdad (hay nodo, tiene el knob del
    motor y el código expone `rutas_engine`). Sin nodo, sin knob, código vacío
    o motor que lanza -> False. Nunca lanza: un comp sin nodo de rutas o con un
    motor roto no puede impedir que el script abra.
    """
    try:
        import nuke

        if nodo is None:
            nodo = elegir_superviviente(encontrar_nodos_rutas())
        if nodo is None or _knob(nodo, KNOB_MOTOR) is None:
            return False
        codigo = _valor(nodo, KNOB_MOTOR, "")
        if not isinstance(codigo, str) or not codigo.strip():
            return False
        # Mismo contrato que el motor: define `rutas_engine(action, arg1)`.
        espacio = {"__name__": __name__ + ".motor", "nuke": nuke}
        exec(codigo, espacio)
        motor = espacio.get("rutas_engine")
        if not callable(motor):
            return False
        motor("sync")
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Hook de carga (S3, S7, S10, S11)
# ---------------------------------------------------------------------------


def aplicar_politica_al_cargar():
    """
    Hook de `nuke.addOnScriptLoad`: garantiza UN nodo de rutas por proyecto.

    Devuelve {"accion", "nodos", "superviviente", "detalle"} con accion en
    ("nada", "unico", "fusionado", "cancelado", "headless", "error");

    - cero nodos  -> "nada": la política NUNCA inserta nodos (S11).
    - un nodo     -> "unico": no se toca nada. La política no migra al abrir:
                     la actualización de un nodo viejo es la acción explícita
                     `crear_o_actualizar` (un viejo conserva knobs y posición).
                     El nodo empuja su entorno con `sincronizar_entorno`.
    - 2+ nodos    -> "fusionado": el superviviente absorbe el estado de los
                     demás y el estado fusionado se ESCRIBE ANTES de borrar
                     (S7). Pide confirmación una sola vez (S10); si el humano
                     dice no, sólo avisa y no borra: "cancelado". En headless
                     no borra nunca, sólo avisa: "headless". Recién con la
                     fusión ya escrita el superviviente empuja su entorno.
    - "error": un nodo de rutas sin `db_json` sobrevivió a la elección (todos
      los del comp son viejos): no hay dónde escribir el estado fusionado, así
      que no se borra nada.

    Sólo `unico` y `fusionado` dejan un nodo vivo en el comp y por eso son los
    únicos que sincronizan el entorno: en los demás no hay nada que empujar.

    Nunca lanza: un comp roto no puede impedir que abra el script.
    """
    try:
        nodos = encontrar_nodos_rutas()
    except Exception as exc:
        return _resultado(
            "error", 0, None, "No se pudieron listar los nodos de rutas: %s" % exc
        )

    total = len(nodos)
    if total == 0:
        return _resultado(
            "nada",
            0,
            None,
            "Sin nodos de rutas en el comp: la política no inserta nodos.",
        )

    if total == 1:
        nodo = nodos[0]
        estado = "versión actual" if es_version_actual(nodo) else "versión anterior"
        # Abrir un comp en un Nuke nuevo tiene que dejar los Reads resueltos:
        # el motor del nodo empuja PYTHON_* sin que nadie toque el nodo.
        sincronizar_entorno(nodo)
        return _resultado(
            "unico",
            1,
            _nombre(nodo),
            "Un solo nodo de rutas (%s): no se toca nada." % estado,
        )

    superviviente = elegir_superviviente(nodos)
    posicion = None
    for i, n in enumerate(nodos):
        if n is superviviente:
            posicion = i
            break
    if posicion is None:
        return _resultado(
            "error", total, None, "No se pudo elegir superviviente: no se tocó nada."
        )
    sobrantes = [n for i, n in enumerate(nodos) if i != posicion]
    nombre_superviviente = _nombre(superviviente)

    if _en_headless():
        detalle = (
            "Se detectaron %d nodos de rutas (se admite uno solo). En modo "
            "headless no se borra nada: fusión cancelada, revisalos a mano."
            % total
        )
        _avisar(detalle)
        return _resultado("headless", total, nombre_superviviente, detalle)

    if not _puede_recibir_estado(superviviente):
        detalle = (
            "Se detectaron %d nodos de rutas y ninguno de versión actual puede "
            "guardar el estado fusionado (sin '%s'). No se borró nada: "
            "revisalos a mano y deja uno."
            % (total, KNOB_ESTADO)
        )
        _avisar(detalle)
        return _resultado("error", total, nombre_superviviente, detalle)

    confirmado = _preguntar(
        "Se detectaron %d nodos de rutas en este comp (se admite uno solo)."
        "\n\n¿Fusionar su contenido en \"%s\" y borrar los otros %d?\n"
        "Se conservan carpetas, usuarios y claves desconocidas."
        % (total, nombre_superviviente, len(sobrantes))
    )
    if not confirmado:
        detalle = (
            "No se fusionó nada: se conservaron los %d nodos de rutas. "
            "Revisalos a mano y deja solo uno." % total
        )
        _avisar(detalle)
        return _resultado("cancelado", total, nombre_superviviente, detalle)

    # S7: primero el estado fusionado, después cualquier nuke.delete. El
    # superviviente va PRIMERO: fusionar_dbs toma el primer estado como base.
    try:
        orden = [superviviente] + sobrantes
        db = fusionar_dbs([db_de(n) for n in orden])
        if not _escribir_estado(superviviente, db):
            detalle = (
                "No se pudo escribir el estado fusionado en \"%s\": no se borró "
                "nada." % nombre_superviviente
            )
            _avisar(detalle)
            return _resultado("error", total, nombre_superviviente, detalle)
    except Exception as exc:
        detalle = (
            "Falló la fusión del estado (%s): no se borró nada."
            % type(exc).__name__
        )
        _avisar(detalle)
        return _resultado("error", total, nombre_superviviente, detalle)

    borrados = 0
    abierto = _iniciar_undo("Fusionar nodos de rutas")
    try:
        import nuke

        for n in sobrantes:
            try:
                nuke.delete(n)
                borrados += 1
            except Exception:
                continue
    except Exception:
        pass
    finally:
        _cerrar_undo(abierto)

    detalle = (
        "Se fusionaron %d nodos de rutas en \"%s\" y se borraron %d sobrantes."
        % (total, nombre_superviviente, borrados)
    )
    _avisar(detalle)
    # El estado fusionado ya está escrito y los sobrantes ya no están: recién
    # ahora el superviviente empuja su entorno a este Nuke.
    sincronizar_entorno(superviviente)
    return _resultado("fusionado", total, nombre_superviviente, detalle)


# ---------------------------------------------------------------------------
# Acción explícita de menú: crear o actualizar el nodo (S4, S11)
# ---------------------------------------------------------------------------


def _ruta_gizmo_por_defecto():
    """Ruta absoluta del gizmo instalado, junto a este módulo."""
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "nodos",
        "Rutas.gizmo",
    )


def _crear_nodo(ruta_gizmo):
    """Sin nodos: pega el gizmo y lo deja listo. No escribe estado (S11)."""
    abierto = _iniciar_undo("Crear nodo de rutas")
    try:
        try:
            import nuke

            nuevo = nuke.nodePaste(ruta_gizmo)
        except Exception:
            nuevo = None
        if nuevo is None:
            detalle = (
                "No se pudo crear el nodo de rutas desde \"%s\"." % ruta_gizmo
            )
            _avisar(detalle)
            return _resultado("error", 0, None, detalle)
        _asegurar_version(nuevo)
        _enfocar(nuevo)
        detalle = "Se creó el nodo de rutas desde \"%s\"." % ruta_gizmo
        return _resultado("creado", 1, _nombre(nuevo), detalle)
    finally:
        _cerrar_undo(abierto)


def _actualizar_nodo_viejo(viejo, ruta_gizmo):
    """
    Un solo nodo, de versión anterior: el "deja uno que actualiza" de S4.

    Pide confirmación UNA vez; si acepta, captura el estado normalizado y la
    posición del nodo viejo, pega el gizmo, escribe el estado en el nodo NUEVO,
    restaura la posición y recién entonces borra el viejo. En headless no
    pregunta, no pega y no borra: solo avisa.
    """
    nombre_viejo = _nombre(viejo)

    if _en_headless():
        detalle = (
            "Hay un nodo de rutas de una versión anterior. En modo headless no "
            "se actualiza ni se borra nada: se conserva el nodo viejo."
        )
        _avisar(detalle)
        return _resultado("headless", 1, nombre_viejo, detalle)

    if not _preguntar(
        "Hay un nodo de rutas de una versión anterior.\n\n"
        "¿Actualizarlo ahora?\n"
        "Se conservan las rutas, los usuarios y la posición del nodo."
    ):
        detalle = (
            "No se actualizó el nodo de rutas: se conserva la versión anterior."
        )
        _avisar(detalle)
        return _resultado("cancelado", 1, nombre_viejo, detalle)

    # Se captura ANTES de tocar nada: el estado y la posición del viejo.
    db = db_de(viejo)
    posicion = _posicion(viejo)

    abierto = _iniciar_undo("Actualizar nodo de rutas")
    try:
        try:
            import nuke

            nuevo = nuke.nodePaste(ruta_gizmo)
        except Exception:
            nuevo = None
        if nuevo is None:
            detalle = (
                "No se pudo pegar el nodo de rutas desde \"%s\": no se borró "
                "nada." % ruta_gizmo
            )
            _avisar(detalle)
            return _resultado("error", 1, nombre_viejo, detalle)

        _asegurar_version(nuevo)
        # El estado va al nodo NUEVO antes de tocar el viejo (misma regla que S7).
        if not _escribir_estado(nuevo, db):
            try:
                nuke.delete(nuevo)
            except Exception:
                pass
            detalle = (
                "El nodo nuevo no pudo guardar el estado: se descartó y se "
                "conserva el nodo de rutas anterior."
            )
            _avisar(detalle)
            return _resultado("error", 1, nombre_viejo, detalle)

        _restaurar_posicion(nuevo, posicion)

        try:
            nuke.delete(viejo)
        except Exception:
            detalle = (
                "Se actualizó el nodo pero no se pudo borrar el anterior: "
                "quedan dos nodos de rutas, revisalos a mano."
            )
            _avisar(detalle)
            return _resultado("error", 2, _nombre(nuevo), detalle)

        _enfocar(nuevo)
        detalle = (
            "Se actualizó el nodo de rutas: se conservaron el estado y la "
            "posición."
        )
        return _resultado("actualizado", 1, _nombre(nuevo), detalle)
    finally:
        _cerrar_undo(abierto)


def crear_o_actualizar(ruta_gizmo=None):
    """
    Acción explícita de menú: garantiza UN nodo de rutas al día (S4, S11).

    Es el equivalente v3 de `rutas.crear_o_reutilizar` (rutas.py:777). Si
    `ruta_gizmo` es None se usa `nodos/Rutas.gizmo`, junto a este módulo.

    Ramas:
      - cero nodos          -> pega el gizmo, marca `nodo_ver` en la versión
                               actual, selecciona y enfoca: "creado". Es la
                               ÚNICA vía que inserta nodos (S11).
      - un nodo actual      -> lo enfoca: "unico" (no pega nada).
      - un nodo viejo       -> confirma una vez y lo actualiza en el lugar:
                               captura estado + posición, pega el gizmo,
                               escribe el estado en el nodo nuevo, restaura la
                               posición y RECIÉN ENTONCES borra el viejo:
                               "actualizado". Si el humano dice no: "cancelado"
                               sin pegar ni borrar. En headless no pregunta, no
                               pega y no borra: "headless".
      - 2+ nodos            -> delega en `aplicar_politica_al_cargar` (fusión) y
                               devuelve su `accion`.

    Devuelve {"accion", "nodos", "superviviente", "detalle"} con accion en
    ("creado", "unico", "actualizado", "cancelado", "headless", "fusionado",
    "nada", "error"). `nodos` cuenta los nodos de rutas en juego: 1 en "creado"
    y "actualizado" (el nodo resultante), los detectados al empezar en
    "unico"/"cancelado"/"headless"/fusión, y el remanente si falla un borrado.
    Nunca lanza.
    """
    if ruta_gizmo is None:
        ruta_gizmo = _ruta_gizmo_por_defecto()
    try:
        nodos = encontrar_nodos_rutas()
    except Exception as exc:
        return _resultado(
            "error", 0, None, "No se pudieron listar los nodos de rutas: %s" % exc
        )

    if len(nodos) > 1:
        # Con varios nodos la decisión ya está tomada por la política de S7/S8.
        return aplicar_politica_al_cargar()

    if len(nodos) == 1:
        nodo = nodos[0]
        if es_version_actual(nodo):
            # El nodo viene al centro de lo que el usuario está mirando: no se
            # mueve la vista, se mueve el nodo.
            _mostrar_en_la_vista(nodo)
            return _resultado(
                "unico",
                1,
                _nombre(nodo),
                "El nodo de rutas ya está en la versión actual: se reutiliza "
                "y se trae al centro de la vista.",
            )
        return _actualizar_nodo_viejo(nodo, ruta_gizmo)

    return _crear_nodo(ruta_gizmo)
