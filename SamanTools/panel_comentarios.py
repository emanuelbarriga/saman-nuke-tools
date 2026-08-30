"""
SamanTools.panel_comentarios - Panel docked "Comentarios por Plano".

Ventana acoplable de Nuke que muestra el contexto del plano activo
(proyecto, capitulo, plano) parseado con `SamanTools.nombres`, permite
iniciar sesion contra VFXFlow (Firebase) y muestra el feed de actividad del
plano activo (SOLO LECTURA, v1.6.1) leido desde Firestore.

La logica de auth REST vive en `vfxflow_auth` (pura, testeable), la
persistencia segura del refresh token en `sesion_vfxflow` y la resolucion de
planos/actividad (cadena proyecto -> capitulo -> shot -> actividad) en
`vfxflow_datos`. La red SIEMPRE corre en un thread daemon y un QTimer del
hilo principal observa/publica resultados (regla Qt: la UI se toca solo desde
el hilo principal).

El feed de actividad reemplaza el QTextBrowser de la v1.6.0 por un
QScrollArea de cards. En v1.6.1 todo es solo consulta: el combo "Estado" y el
input de comentario estan deshabilitados (el envio y el cambio de estado son
v1.6.2). El avatar por foto (userPhotoURL) tambien queda documentado para
despues: v1.6.1 muestra la INICIAL del usuario. El import de referencias
(v1.6.4, "Importar refs") baja las imágenes de referencia del plano a
`<dir del comp>/ref` y crea un nodo Read por cada una con ruta relativa,
reusando el mismo patron de worker daemon + QTimer.

Import de PySide con el patron de `frame_manager` (try PySide2, except
PySide6) para mantener compatibilidad entre Nuke 14 y 17.
"""

import hashlib
import html
import os
import re
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timezone

import nuke

try:
    from PySide2 import QtCore, QtGui, QtWidgets
    # PySide2: los enums cuelgan directo de Qt (Qt.AlignCenter, Qt.Checked).
    QtAlignment = QtCore.Qt
except ImportError:
    from PySide6 import QtCore, QtGui, QtWidgets
    # PySide6/Nuke 14+: enums con namespace explícito.
    QtAlignment = QtCore.Qt.AlignmentFlag

from . import sesion_vfxflow
from . import vfxflow_auth
from . import vfxflow_config
from . import vfxflow_datos

_ID_PANEL = "pe.saman.vfxflow.comentarios"
_NOMBRE_PANEL = "Comentarios por Plano — SamanTools"

# Sin marca de expiracion en la sesion: se refresca si el archivo se escribio
# hace mas de 50 minutos (el id_token dura 1 hora).
_VENTANA_REFRESH_SEGUNDOS = 50 * 60

# Techo del canje loopback en background. El canje hace 3 llamadas de red
# encadenadas (canjear_codigo_autorizacion + loguear_con_google +
# obtener_usuario), cada una con timeout interno de 10 s; con margen se corta
# la espera de la UI a los 35 s para no dejarla colgada si la red se traba.
_LOOPBACK_TIMEOUT_TRABAJO_SEGUNDOS = 35

# Mensaje para el codigo "red" del login Google: la red del estudio bloquea la
# salida directa a googleapis.com aunque el navegador (proxy) si conecte.
_MENSAJE_FIREWALL_GOOGLE = (
    "No se pudo contactar con Google. Parece que la red bloquea la salida "
    "directa a Google (los dominios googleapis.com). El navegador puede "
    "funcionar, pero el panel necesita acceso de red directo: verificá el "
    "firewall/proxy del estudio para oauth2.googleapis.com y "
    "firestore.googleapis.com."
)

# Mensajes del area de actividad (copia UI en espanol).
_MENSAJE_PLANO_NO_IDENTIFICADO = (
    "Plano no identificado: guardá el comp con la convención "
    "{PROYECTO}_{EP}_{escena}_{shot}_V{nn}."
)
_MENSAJE_SIN_SESION = "Iniciá sesión para ver actividad."
_MENSAJE_SIN_ACTIVIDAD = "Sin actividad para este plano."

# Mensajes del import de referencias (v1.6.4).
_MENSAJE_SIN_REFS = "Este plano no tiene imágenes de referencia."
_MENSAJE_SIN_SESION_REFS = "Iniciá sesión para importar referencias."
_MENSAJE_COMP_SIN_GUARDAR = "Guardá el comp antes de importar referencias."

# Timeout de cada descarga individual de referencia (URL firmada de storage).
_REFS_TIMEOUT_SEGUNDOS = 10

# Campos que se codifican como timestampValue en los payloads de escritura.
_CAMPOS_TIMESTAMP = ("createdAt", "updatedAt", "timestamp")

# Color neutro del chip/menú de estado cuando el estado no trae `color`
# (slate-600, el fallback del EnhancedShotStateSelector de la app web).
_COLOR_ESTADO_NEUTRAL = "#616E7C"

# Intervalo del QTimer que observa el resultado del fetch de actividad.
_COMENTARIOS_POLL_MS = 500

# Intervalo del QTimer que observa el comp activo (cambio de plano).
_POLL_PLANO_MS = 1500

# Colores de la paleta oscura usados en strings dinamicos (el resto vive en
# _ESTILO_PANEL). Se aislan para poder probarlos sin QApplication.
_COLOR_ERROR = "#ff6b6b"
_COLOR_MENSAJE = "#9a9a9a"

# Banderas de tiempo relativo (espanol) para el feed de actividad.
_DIA_SEGUNDOS = 86400
_MES_SEGUNDOS = 30 * _DIA_SEGUNDOS
_ANIO_SEGUNDOS = 365 * _DIA_SEGUNDOS

# Paleta oscura acorde a Nuke + spec de la app web (bg-slate-700 #334155,
# bg-slate-800 #1e293b, text-slate-100 #f1f5f9, text-slate-400 #94a3b8,
# bg-sky-800 #075985, text-sky-300 #7dd3fc, amber #f59e0b). Se aplica SOLO a
# este widget (`self.setStyleSheet`), NUNCA global.
_ESTILO_PANEL = """
QWidget {
    background-color: #2b2b2b;
    color: #f1f5f9;
    font-size: 12px;
}
QLabel {
    background: transparent;
    color: #f1f5f9;
}
QLabel#autorActividad {
    color: #f1f5f9;
    font-weight: bold;
}
QLabel#verboActividad {
    color: #94a3b8;
}
QLabel#avatarActividad {
    background-color: #334155;
    color: #f1f5f9;
    border-radius: 16px;
    font-weight: bold;
}
QLabel#rolActividad {
    background-color: #334155;
    color: #94a3b8;
    padding: 2px 6px;
    border-radius: 2px;
}
QLabel#tiempoActividad,
QLabel#glifoTipo,
QLabel#versionActividad {
    color: #94a3b8;
    font-size: 11px;
}
QLabel#editoActividad {
    color: #94a3b8;
    font-style: italic;
    font-size: 10px;
}
QLabel#ventanaActividad {
    color: #f59e0b;
    font-weight: bold;
}
QGroupBox {
    background-color: transparent;
    border: 1px solid #4a4a4a;
    border-radius: 4px;
    margin-top: 12px;
    color: #d0d0d0;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
}
QLineEdit {
    background-color: #1e1e1e;
    color: #ffffff;
    border: 1px solid #4a4a4a;
    border-radius: 3px;
    padding: 3px 6px;
    selection-background-color: #1f8ecd;
    selection-color: #ffffff;
}
QLineEdit:focus {
    border: 1px solid #1f8ecd;
}
QLineEdit:disabled {
    background-color: #262626;
    color: #6a6a6a;
}
QComboBox {
    background-color: #1e1e1e;
    color: #ffffff;
    border: 1px solid #4a4a4a;
    border-radius: 3px;
    padding: 2px 8px;
}
QComboBox:disabled {
    background-color: #262626;
    color: #6a6a6a;
}
QComboBox QAbstractItemView {
    background-color: #2b2b2b;
    color: #dcdcdc;
    border: 1px solid #4a4a4a;
    selection-background-color: #1f8ecd;
}
QPushButton {
    background-color: #3a3a3a;
    color: #e6e6e6;
    border: 1px solid #555555;
    border-radius: 3px;
    padding: 4px 10px;
}
QPushButton:hover {
    background-color: #444444;
}
QPushButton:pressed {
    background-color: #4a4a50;
}
QPushButton:disabled {
    background-color: #262626;
    color: #6a6a6a;
}
QFrame#cardActividad {
    background-color: #334155;
    border: 1px solid #475569;
    border-radius: 6px;
    padding: 6px;
}
QFrame#cardRespuesta {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 4px;
    padding: 6px;
}
QLabel#chipEstado {
    background-color: #334155;
    border: 1px solid #475569;
    border-radius: 9px;
    padding: 2px 8px;
    color: #f1f5f9;
}
QLabel#chipVersionVieja {
    background-color: #334155;
    border: 1px solid #475569;
    border-radius: 9px;
    padding: 2px 8px;
    color: #94a3b8;
}
QLabel#chipVersionNueva {
    background-color: #075985;
    border: 1px solid #075985;
    border-radius: 9px;
    padding: 2px 8px;
    color: #7dd3fc;
}
QToolButton#botonRespuestas {
    color: #94a3b8;
    border: none;
    background: transparent;
    padding: 2px 0;
    font-weight: bold;
}
QToolButton#botonRespuestas:hover {
    color: #f1f5f9;
}
QToolButton#botonResponder {
    color: #7dd3fc;
    border: none;
    background: transparent;
    padding: 2px 6px;
    font-weight: bold;
}
QToolButton#botonEstadoActual {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 9px;
    padding: 2px 8px;
    color: #f1f5f9;
}
QToolButton#botonEstadoActual:hover {
    background-color: #334155;
}
QToolButton#botonEstadoAnterior,
QToolButton#botonEstadoSiguiente {
    border: none;
    background: transparent;
    color: #94a3b8;
    padding: 2px 6px;
}
QToolButton#botonEstadoAnterior:hover,
QToolButton#botonEstadoSiguiente:hover {
    color: #f1f5f9;
}
QToolButton#botonEstadoAnterior:disabled,
QToolButton#botonEstadoSiguiente:disabled {
    color: #475569;
}
QMenu {
    background-color: #1e293b;
    color: #f1f5f9;
    border: 1px solid #334155;
}
QMenu::item:selected {
    background-color: #334155;
}
QScrollArea {
    background: transparent;
    border: none;
}
QScrollArea > QWidget > QWidget {
    background: transparent;
}
QScrollBar:vertical {
    background: #2b2b2b;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #4a4a4a;
    border-radius: 5px;
    min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}
"""


# --------------------------------------------------------- helpers puros

def _escapar_y_linkificar(texto):
    """Escapa `texto` e hipervincula las URLs `https?://\\S+` (HTML seguro).

    Escapa TODO el texto primero (nunca HTML arbitrario) y envuelve las URLs
    resultantes en `<a href="...">`. Devuelve HTML seguro para las labels de
    las cards del feed (que abren los links con QLabel.setOpenExternalLinks).
    """
    if not texto:
        return ""
    escapado = html.escape(str(texto))

    def _enlace(m):
        url = m.group(0)
        return '<a href="{0}">{1}</a>'.format(url, url)

    return re.sub(r"https?://\S+", _enlace, escapado)


def _tiempo_relativo(creado_en):
    """Tiempo relativo en espanol desde `creado_en` (ISO 8601) hasta ahora.

    "ahora" (<1 min), "hace Xm" (<60 min), "hace Xh" (<24 h), "hace Xd"
    (<30 dias), "hace Xmes" (1 mes singular / X meses) y "hace Xa"
    (>=365 dias). Compara contra `datetime.now(timezone.utc)`; acepta ISO con
    'Z' o con offset. Si no se puede parsear, devuelve el string recortado a
    19 caracteres. Puro (para testear sin QApplication).
    """
    if not creado_en:
        return ""
    try:
        texto = str(creado_en)
        if texto.endswith("Z"):
            texto = texto[:-1] + "+00:00"
        instante = datetime.fromisoformat(texto)
        if instante.tzinfo is None:
            instante = instante.replace(tzinfo=timezone.utc)
        segundos = (datetime.now(timezone.utc) - instante).total_seconds()
    except (TypeError, ValueError):
        return str(creado_en)[:19]
    if segundos < 60:
        return "ahora"
    if segundos < 60 * 60:
        return "hace {0}m".format(int(segundos // 60))
    if segundos < _DIA_SEGUNDOS:
        return "hace {0}h".format(int(segundos // 3600))
    if segundos < _MES_SEGUNDOS:
        return "hace {0}d".format(int(segundos // _DIA_SEGUNDOS))
    if segundos < _ANIO_SEGUNDOS:
        meses = int(segundos // _MES_SEGUNDOS)
        return "hace 1 mes" if meses == 1 else "hace {0} meses".format(meses)
    anios = int(segundos // _ANIO_SEGUNDOS)
    return "hace {0}a".format(anios)


def _inicial_avatar(nombre):
    """Inicial para el avatar circular de la card; '?' si no hay nombre. Puro.

    v1.6.1 no descarga userPhotoURL: el avatar por URL queda documentado para
    una versión posterior (la inicial no depende de red ni de fakes Qt).
    """
    nombre = str(nombre or "").strip()
    if not nombre:
        return "?"
    return nombre[0].upper()


def _abreviar_nombre(nombre):
    """Abrevia un nombre a "Primer Apellido." (o el nombre si es uno solo)."""
    partes = [p for p in str(nombre or "").split() if p]
    if not partes:
        return "?"
    if len(partes) == 1:
        return partes[0]
    return "{0} {1}.".format(partes[0], partes[1][0])


def _resumen_asignados(assignees):
    """Resumen legible de assignees: "Emanuel B. (+2)" o "—" si no hay datos.

    Usa `primaryName` (abreviado) y cuenta los `secondaryNames`. Puro.
    """
    if not isinstance(assignees, dict):
        return "—"
    primario = _abreviar_nombre(assignees.get("primaryName")) if assignees.get("primaryName") else None
    secundarios = assignees.get("secondaryNames") or []
    if primario and secundarios:
        return "{0} (+{1})".format(primario, len(secundarios))
    if primario:
        return primario
    if secundarios:
        return "(+{0})".format(len(secundarios))
    return "—"


def _es_verdadero(valor):
    """Interpreta un booleano de Firestore (bool o su string) como True/False."""
    if isinstance(valor, bool):
        return valor
    return str(valor or "").strip().lower() in ("true", "1")


def _estado_cambiada(actividad):
    """Texto sintetizado de status_change cuando content llega vacio."""
    prev = actividad.get("previousStateName") or "desconocido"
    nuevo = actividad.get("newStateName") or "desconocido"
    return "Estado cambiado de '{0}' a '{1}'".format(prev, nuevo)


def _chips_estados(actividad):
    """Badges (previo, nuevo) de estados; None si faltan los dos nombres."""
    prev = actividad.get("previousStateName")
    nuevo = actividad.get("newStateName")
    if prev and nuevo:
        return (str(prev), str(nuevo))
    return None


def _formatear_version(valor):
    """"V<valor>" sin duplicar la 'V' si el dato ya viene con ella (o None)."""
    if valor is None:
        return None
    texto = str(valor).strip()
    if not texto:
        return None
    if not texto.startswith(("V", "v")):
        texto = "V" + texto
    return texto.upper()


def _versiones_diferentes(actividad):
    """"V<prev> → V<new>" solo si ambas versiones existen y difieren."""
    prev = _formatear_version(actividad.get("previousVersion"))
    nuevo = _formatear_version(actividad.get("newVersion"))
    if prev is None or nuevo is None or prev == nuevo:
        return None
    return "{0} → {1}".format(prev, nuevo)


def _texto_tarea(actividad):
    """Línea de task_update: "Tarea '<taskName>' completada/pendiente"."""
    nombre = actividad.get("taskName") or ""
    estado = "completada" if _es_verdadero(actividad.get("completed")) else "pendiente"
    if nombre:
        return "Tarea '{0}' {1}".format(nombre, estado)
    return "Tarea {0}".format(estado)


def _texto_asignacion(actividad):
    """Línea de assignment_change con resúmenes de previo/nuevo asignado."""
    prev = _resumen_asignados(actividad.get("previousAssignees"))
    nuevo = _resumen_asignados(actividad.get("newAssignees"))
    return "Asignación cambiada: {0} → {1}".format(prev, nuevo)


# ----------------------------------------------------- helpers v1.6.5 (puros)

def _tiempo_relativo_largo(creado_en):
    """Tiempo relativo en espanol COMPLETO (spec app web).

    "ahora", "hace X minutos/horas/días", "hace 1 mes/X meses",
    "hace 1 año/X años" (singular/plural). Misma base de parseo que
    `_tiempo_relativo`; fallback: recorta a 19 caracteres. Puro.
    """
    if not creado_en:
        return ""
    try:
        texto = str(creado_en)
        if texto.endswith("Z"):
            texto = texto[:-1] + "+00:00"
        instante = datetime.fromisoformat(texto)
        if instante.tzinfo is None:
            instante = instante.replace(tzinfo=timezone.utc)
        segundos = (datetime.now(timezone.utc) - instante).total_seconds()
    except (TypeError, ValueError):
        return str(creado_en)[:19]
    if segundos < 60:
        return "ahora"
    if segundos < 60 * 60:
        minutos = int(segundos // 60)
        return "hace 1 minuto" if minutos == 1 else "hace {0} minutos".format(minutos)
    if segundos < _DIA_SEGUNDOS:
        horas = int(segundos // 3600)
        return "hace 1 hora" if horas == 1 else "hace {0} horas".format(horas)
    if segundos < _MES_SEGUNDOS:
        dias = int(segundos // _DIA_SEGUNDOS)
        return "hace 1 día" if dias == 1 else "hace {0} días".format(dias)
    if segundos < _ANIO_SEGUNDOS:
        meses = int(segundos // _MES_SEGUNDOS)
        return "hace 1 mes" if meses == 1 else "hace {0} meses".format(meses)
    anios = int(segundos // _ANIO_SEGUNDOS)
    return "hace 1 año" if anios == 1 else "hace {0} años".format(anios)


def _dentro_ventana_10min(creado_en):
    """True si `createdAt` cae en la ventana de edicion de 10 min. Puro."""
    try:
        texto = str(creado_en)
        if texto.endswith("Z"):
            texto = texto[:-1] + "+00:00"
        instante = datetime.fromisoformat(texto)
        if instante.tzinfo is None:
            instante = instante.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return False
    segundos = (datetime.now(timezone.utc) - instante).total_seconds()
    return 0 <= segundos < 10 * 60


def _es_autor(actividad, sesion):
    """True si la actividad es del usuario de la sesion (solo visual).

    Compara `userId` contra `sesion.local_id`; sin id del item, compara el
    `userName` con la parte previa a '@' del email. Nunca lanza.
    """
    if not sesion:
        return False
    local_id = sesion.get("local_id")
    user_id = actividad.get("userId")
    if local_id and user_id:
        return str(local_id) == str(user_id)
    email = sesion.get("email") or ""
    user_name = actividad.get("userName") or ""
    if not email or not user_name:
        return False
    return (
        user_name.split("@")[0].strip().lower()
        == email.split("@")[0].strip().lower()
    )


_GLIFOS_TIPO = {
    "comment": "💬",
    "reply": "↳",
    "file_upload": "🖼",
    "status_change": "⇄",
    "version_update": "v",
    "task_update": "✓",
    "batch_update": "≡",
    "assignment_change": "⚑",
}

_VERBOS_TIPO = {
    "comment": "comentó",
    "reply": "respondió",
    "file_upload": "subió imagen",
    "status_change": "cambió estado",
    "version_update": "actualizó versión",
    "task_update": "actualizó tarea",
    "batch_update": "actualizó estados",
    "assignment_change": "cambió asignación",
}


def _glifo_tipo(tipo):
    """Glifo discreto por tipo de actividad (al final de la fila). Puro."""
    return _GLIFOS_TIPO.get(tipo, "")


def _verbo_tipo(tipo):
    """Verbo corto por tipo (gris tras el autor). Puro."""
    return _VERBOS_TIPO.get(tipo, "")


_REGEX_EP = re.compile(r"(?:\A|/)EP_(\d+)(?:/|\Z)")


def _ep_desde_ruta(ruta):
    """Segmento 'EP_<digitos>' de una ruta, o None. Puro."""
    m = _REGEX_EP.search(str(ruta or "").replace("\\", "/"))
    if m:
        return "EP_{0}".format(m.group(1))
    return None


def _ruta_read_ref(comp_path, filename):
    """Valor del knob `file` del Read con la convencion del estudio.

    "[python {PYTHON_COMP}]/EP_<nn>/{carpeta_comp}/ref/{filename}" donde
    `carpeta_comp` es el basename del directorio del comp y `EP_<nn>` sale de
    un segmento 'EP_<digitos>' de la ruta o, si no, del capitulo parseado.
    Sin comp guardado (o sin EP deducible) -> ruta relativa "ref/<filename>".
    Puro.
    """
    ruta = str(comp_path or "").replace("\\", "/")
    if not ruta.strip():
        return "ref/{0}".format(filename)
    carpeta_comp = os.path.basename(os.path.dirname(ruta))
    if not carpeta_comp:
        return "ref/{0}".format(filename)
    ep = _ep_desde_ruta(ruta)
    if not ep:
        try:
            from SamanTools import nombres

            cap = (nombres.parsear_plato(ruta) or {}).get("capitulo")
            if cap is not None:
                ep = "EP_{0}".format(cap)
        except Exception:
            ep = None
    if not ep:
        return "ref/{0}".format(filename)
    # Las llaves de {PYTHON_COMP} son literales: se escapan para .format.
    return "[python {{PYTHON_COMP}}]/{0}/{1}/ref/{2}".format(ep, carpeta_comp, filename)


def _formatear_tamano_bytes(size):
    """"114 KB" (o "560 B") desde el campo size de un adjunto. Puro."""
    try:
        size = int(size)
    except (TypeError, ValueError):
        return ""
    if size < 1024:
        return "{0} B".format(size)
    return "{0:.0f} KB".format(size / 1024.0)


_CACHE_ADJUNTOS_DIR = os.path.join(
    os.path.expanduser("~"), ".config", "saman", "cache_adjuntos"
)


def _ruta_cache_imagen(url):
    """Ruta de cache estable por URL firmada (md5 del url). Puro."""
    digest = hashlib.md5(str(url or "").encode("utf-8")).hexdigest()
    return os.path.join(_CACHE_ADJUNTOS_DIR, digest + ".img")


def _cargar_imagen_cacheada(url, abrir=None):
    """Ruta local de una imagen adjunta (cacheada) o None si no se pudo.

    Si ya existe la cache la devuelve; si no, descarga con GET puro (el token
    va en la URL firmada) via `vfxflow_auth._abrir`, escribiendo a un tmp y
    moviendo (nunca cache parcial). Sin widgets: corre en el worker de
    actividad. Un fallo devuelve None (el render cae al texto).
    """
    abrir = abrir or vfxflow_auth._abrir
    try:
        ruta = _ruta_cache_imagen(url)
        if os.path.exists(ruta):
            return ruta
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        req = urllib.request.Request(str(url), method="GET")
        with abrir(req, timeout=_REFS_TIMEOUT_SEGUNDOS) as respuesta:
            datos = respuesta.read()
        tmp = ruta + ".tmp"
        with open(tmp, "wb") as archivo:
            archivo.write(datos)
        os.replace(tmp, ruta)
        return ruta
    except Exception:
        return None


def _cargar_imagenes_adjuntas(actividad, abrir=None):
    """Descarga a cache las imagenes de los adjuntos; {url: ruta_local}."""
    rutas = {}
    for item in actividad or []:
        for adj in item.get("attachments") or []:
            if not isinstance(adj, dict) or adj.get("type") != "image":
                continue
            url = adj.get("url")
            if not url:
                continue
            ruta = _cargar_imagen_cacheada(url, abrir=abrir)
            if ruta:
                rutas[str(url)] = ruta
    return rutas


def _agrupar_actividad(actividad):
    """(padres, hijas_por_padre) agrupando las replies bajo su comentario.

    Una activity es hija si trae `parentId`; se agrupa por ese id. Los padres
    quedan en el orden del fetch (DESC por createdAt) y las hijas mantienen su
    propio orden dentro de cada grupo. Puro.
    """
    padres = []
    hijas = {}
    for item in actividad or []:
        if item.get("parentId"):
            hijas.setdefault(item.get("parentId"), []).append(item)
        else:
            padres.append(item)
    return padres, hijas


def _color_estado(colores, state_id):
    """Color hex de un estado desde el mapa {stateId: color}, o ''. Puro."""
    if not colores or not state_id:
        return ""
    return str(colores.get(str(state_id)) or "")


def _styles_chip_color(color):
    """QSS de un chip con el color real del estado (`bg <color>4D` ~30% alpha).

    Con color ausente devuelve '' (el chip cae al selector neutral
    `QLabel#chipEstado`). Puro.
    """
    texto = str(color or "").strip()
    if not texto.startswith("#") or len(texto) not in (4, 7):
        return ""
    rgb = texto[1:]
    return "background-color:#{0}4D; border:1px solid {1}; color:{1};".format(
        rgb, texto
    )


def _ids_estados(actividad):
    """(id_previo, id_nuevo) de estados o None (para colorear chips). Puro."""
    prev = actividad.get("previousState")
    nuevo = actividad.get("newState")
    if prev and nuevo:
        return (str(prev), str(nuevo))
    return None


def _html_cita(actividad):
    """HTML seguro del bloque de cita (quoted), o '' si no hay datos. Puro.

    La cita viaja en `metadata.quotedComment` ({content, userName}); sin
    contenido, ya fue sintetizada en `content` y no se repite el bloque.
    """
    meta = actividad.get("metadata") or {}
    cita = meta.get("quotedComment") or {}
    contenido = cita.get("content")
    if not contenido:
        return ""
    autor_cita = cita.get("userName") or "Anónimo"
    cuerpo = _escapar_y_linkificar(str(contenido))
    return (
        "<div style='border-left:2px solid #64748b; padding-left:8px; "
        "color:#94a3b8; margin-top:4px;'>"
        "<span style='color:#94a3b8;'>{0} escribió:</span><br/>{1}</div>"
    ).format(_escapar_y_linkificar(autor_cita), cuerpo)


def _linea_adjunto_texto(adj):
    """Línea de texto de un adjunto sin thumbnail ("Adjuntó: name (114 KB)")."""
    nombre = (adj.get("name") or "").strip()
    url = adj.get("url") or ""
    if adj.get("type") == "image":
        texto = "[imagen] {0}".format(nombre) if nombre else "[imagen]"
    else:
        texto = "Adjuntó: {0}".format(nombre) if nombre else "Adjuntó un archivo"
        tamanio = _formatear_tamano_bytes(adj.get("size"))
        if tamanio:
            texto += " ({0})".format(tamanio)
    if url:
        texto = "{0}  {1}".format(texto, url)
    return texto


def _html_archivos(actividad):
    """HTML (seguro) del cuerpo de file_upload: una línea por attachment.

    Para `type=="image"` muestra "[imagen] <name>" (fallback a texto: en la
    card el thumbnail lo reemplaza); para el resto "Adjuntó: <name> (<size>
    KB)". Si hay `url`, queda clicable. Sin attachments usa `content`.
    """
    adjuntos = actividad.get("attachments")
    if not adjuntos:
        return _escapar_y_linkificar(actividad.get("content") or "")
    lineas = []
    for adj in adjuntos:
        if not isinstance(adj, dict):
            continue
        lineas.append(_linea_adjunto_texto(adj))
    return "<br/>".join(_escapar_y_linkificar(l) for l in lineas)


# ----------------------------------------------------- helpers v1.7.0 (puros)

def _iso_ahora():
    """Timestamp ISO actual en UTC (para los campos timestampValue). Puro."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _encode_valor_firestore(valor):
    """Codifica un valor Python a un Value Firestore REST (tipado). Puro.

    None -> nullValue, bool -> booleanValue, numero -> integerValue, dict ->
    mapValue (recursivo), list -> arrayValue (recursivo), resto -> stringValue.
    Los map/array se filtran para no escribir claves None (Firestore no acepta
    campos con nullValue dentro de mapValue).
    """
    if valor is None:
        return {"nullValue": None}
    if isinstance(valor, bool):
        return {"booleanValue": valor}
    if isinstance(valor, (int, float)):
        return {"integerValue": str(int(valor))}
    if isinstance(valor, dict):
        campos = {
            k: _encode_valor_firestore(v)
            for k, v in valor.items()
            if v is not None
        }
        return {"mapValue": {"fields": campos}}
    if isinstance(valor, list):
        return {
            "arrayValue": {
                "values": [_encode_valor_firestore(v) for v in valor]
            }
        }
    return {"stringValue": str(valor)}


def _payload_actividad(campos, timestamp_campos=None):
    """Arma los `fields` REST de Firestore de una actividad (escritura). Puro.

    Las claves en `timestamp_campos` (default createdAt/updatedAt/timestamp)
    se codifican como timestampValue; el resto con `_encode_valor_firestore`.
    Devuelve el dict listo para el body de createDocument.
    """
    timestamp_campos = timestamp_campos or _CAMPOS_TIMESTAMP
    fields = {}
    for clave, valor in campos.items():
        if clave in timestamp_campos:
            fields[clave] = {"timestampValue": str(valor)}
        else:
            fields[clave] = _encode_valor_firestore(valor)
    return fields


def _nombre_usuario_sesion(sesion):
    """userName razonable desde la sesión (local part del email). Puro."""
    sesion = sesion or {}
    nombre = (sesion.get("userName") or "").strip()
    if nombre:
        return nombre
    email = sesion.get("email") or ""
    return email.split("@")[0].strip() or "artista"


def _rol_sesion(sesion):
    """Rol de la sesión para el payload ("artist" por defecto). Puro."""
    sesion = sesion or {}
    return (sesion.get("role") or sesion.get("userRole") or "artist")


def _base_campos_actividad(project_id, shot_id, sesion, tipo, contenido):
    """Campos comunes de una actividad de escritura (v1.7.0). Puro.

    Denormaliza la identidad de la sesión (userId/userName/userRole/role/
    userPhotoURL) como la app web: la sesión ahora persiste el perfil real
    (ver `_fusionar_identidad_en_sesion` y `sesion_vfxflow`).
    """
    sesion = sesion or {}
    ahora = _iso_ahora()
    nombre = _nombre_usuario_sesion(sesion)
    rol = _rol_sesion(sesion)
    return {
        "type": tipo,
        "content": contenido or "",
        "shotId": shot_id,
        "projectId": project_id,
        "userId": sesion.get("local_id") or "",
        "userName": nombre,
        "userRole": rol,
        "role": rol,
        "userPhotoURL": sesion.get("userPhotoURL") or "",
        "isPrivate": False,
        "createdAt": ahora,
        "updatedAt": ahora,
        "timestamp": ahora,
        "metadata": {},
        "parentId": None,
        "quotedCommentId": None,
    }


def _campos_status_change(project_id, shot_id, sesion, previo_id, previo_nombre,
                          nuevo_id, nuevo_nombre):
    """Campos de la actividad status_change (con nombres sintetizados). Puro."""
    campos = _base_campos_actividad(
        project_id,
        shot_id,
        sesion,
        "status_change",
        "Estado cambiado de '{0}' a '{1}'".format(previo_nombre, nuevo_nombre),
    )
    campos.update(
        {
            "previousState": previo_id,
            "previousStateName": previo_nombre,
            "newState": nuevo_id,
            "newStateName": nuevo_nombre,
        }
    )
    return campos


def _color_estado_chip(estado):
    """Color del chip de estado (fallback slate-600 si no hay `color`). Puro."""
    color = (estado or {}).get("color")
    return str(color) if color else _COLOR_ESTADO_NEUTRAL


def _icono_dot_estado(color):
    """QIcon 16×16 del color (el "●" del selector), o None si no hay paint.

    QToolButton/QAction no renderizan rich text; el color del estado viaja
    como icono cuadrado pequeño (igual que la app web usa un círculo). Sin
    plataforma gráfica devuelve None (el texto queda sin color, no rompe).
    """
    try:
        pixmap = QtWidgets.QPixmap(16, 16)
        pixmap.fill(QtGui.QColor(str(color)))
        return QtGui.QIcon(pixmap)
    except Exception:
        return None


def _indices_estado_anterior_siguiente(ids_ordenados, estado_actual_id):
    """"(anterior_id, siguiente_id) por el orden del selector, o None cada uno.

    Primer estado -> anterior None; último -> siguiente None; estado actual
    fuera de la lista -> ambos None (no se navega a ciegas). `ids_ordenados`
    ya viene en orden `order` asc. Puro (testeable sin widgets).
    """
    ids = list(ids_ordenados or [])
    if not estado_actual_id or str(estado_actual_id) not in ids:
        return (None, None)
    indice = ids.index(str(estado_actual_id))
    anterior = ids[indice - 1] if indice > 0 else None
    siguiente = ids[indice + 1] if indice < len(ids) - 1 else None
    return (anterior, siguiente)


def _acciones_estado(estados_ordenados, estados_combo, estado_actual_id):
    """Items del menú del selector: [(estado_id, texto, es_actual)]. Puro.

    El estado actual se marca con "✓ " (texto plano: los QMenu nativos no
    renderizan rich text en QAction de forma confiable).
    """
    acciones = []
    for estado_id in estados_ordenados or []:
        item = (estados_combo or {}).get(str(estado_id)) or {}
        nombre = item.get("name") or str(estado_id)
        es_actual = str(estado_id) == str(estado_actual_id)
        texto = "✓ {0}".format(nombre) if es_actual else nombre
        acciones.append((str(estado_id), texto, es_actual))
    return acciones


def _rect_crop_central(src_w, src_h, tgt_ratio=16.0 / 9.0):
    """Crop central (x, y, w, h) con aspect `tgt_ratio` dentro de la fuente.

    Devuelve el rectángulo central más grande con la ratio pedida (16/9 por
    defecto) contenido en la fuente. Si la fuente ya tiene esa ratio, devuelve
    el rect completo. Usa tuplas (no QRect) para poder testear sin
    QApplication. Puro.
    """
    ancho = int(src_w)
    alto = int(src_h)
    if ancho <= 0 or alto <= 0 or tgt_ratio <= 0:
        return (0, 0, ancho, alto)
    if abs(ancho / float(alto) - tgt_ratio) < 1e-6:
        return (0, 0, ancho, alto)
    if ancho / float(alto) > tgt_ratio:
        w = int(alto * tgt_ratio)
        return ((ancho - w) // 2, 0, w, alto)
    h = int(ancho / tgt_ratio)
    return (0, (alto - h) // 2, ancho, h)


def _ruta_jpg_temporal():
    """Ruta temporal para el jpg 1280×720 de la subida (nunca colisiona)."""
    return os.path.join(
        tempfile.gettempdir(),
        "ref_upload_{0}_{1}.jpg".format(int(time.time() * 1000), threading.get_ident()),
    )


def _convertir_jpg_1280x720(ruta_origen, ruta_destino, calidad=90):
    """Crop central 16:9 + escala exacta a 1280×720 y guarda jpg.

    Sin Pillow: usa QImage de QtGui (funciona sin QApplication, son objetos de
    datos). Devuelve `ruta_destino` en éxito o None si no pudo leer/guardar.
    Puede correr en el hilo principal (rápido) o en un worker.
    """
    try:
        imagen = QtGui.QImage(ruta_origen)
        if imagen.isNull():
            return None
        x, y, w, h = _rect_crop_central(imagen.width(), imagen.height())
        imagen = imagen.copy(x, y, w, h)
        imagen = imagen.scaled(
            1280, 720, QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.SmoothTransformation
        )
        if not imagen.save(ruta_destino, "JPG", calidad):
            return None
        return ruta_destino
    except Exception:
        return None


def _debe_mostrar_boton_importar(adjunto, imagenes):
    """True si el adjunto de imagen lleva botón "⬇ Importar" SIEMPRE.

    El botón se muestra por cada adjunto image con url aunque el thumbnail
    falle (cache ausente/pixmap nulo): el usuario siempre puede descargar la
    imagen del comentario. `imagenes` no es determinante (solo decide si hay
    preview). Puro.
    """
    if not isinstance(adjunto, dict):
        return False
    if adjunto.get("type") != "image":
        return False
    return bool(adjunto.get("url"))


def _label_read_adjunto(contexto):
    """Etiqueta del Read importado desde un comentario (knob `label`). Puro.

    "comentario de {autor}: {contenido}" recortado a ~60 caracteres; sin autor
    -> "comentario: {contenido}"; sin contexto -> "comentario".
    """
    contexto = contexto or {}
    autor = str(contexto.get("autor") or "").strip()
    contenido = str(contexto.get("contenido") or "").strip()
    if autor:
        base = (
            "comentario de {0}: {1}".format(autor, contenido)
            if contenido
            else "comentario de {0}".format(autor)
        )
    else:
        base = (
            "comentario: {0}".format(contenido)
            if contenido
            else "comentario"
        )
    if len(base) > 60:
        return base[:57].rstrip() + "..."
    return base


def _cuerpo_actividad(actividad):
    """Cuerpo de una card según el type (HTML seguro) + extras. Puro.

    Devuelve:
      - "html": línea(s) del cuerpo, HTML seguro con URLs enlazadas.
      - "chips": (nombre_previo, nombre_nuevo) o None (status/batch).
      - "chip_ids": (id_previo, id_nuevo) o None (para colorear por projectState).
      - "versiones": "V<prev> → V<new>" o None (batch_update, texto simple).
      - "versiones_chip": (previo, nuevo) o None (chips de versión).
      - "cita": HTML de la cita (quoted) o '' (comment/reply).

    El feed es de actividad completa: los 8 tipos de shotActivity se muestran
    como cards (comentarios, archivos, estados, versiones, tareas, asignación).
    """
    tipo = actividad.get("type")
    content = actividad.get("content")
    base = {
        "chips": None,
        "chip_ids": None,
        "versiones": None,
        "versiones_chip": None,
        "cita": _html_cita(actividad),
    }
    if tipo == "comment":
        return dict(base, html=_escapar_y_linkificar(content))
    if tipo == "reply":
        return dict(base, html=_escapar_y_linkificar("↳ {0}".format(content or "")))
    if tipo == "file_upload":
        if (actividad.get("attachments") or []):
            # Los adjuntos se renderizan como widgets en la card (thumbnails o
            # filas de texto), no como cuerpo HTML: no se duplica el preview.
            html = ""
            return dict(base, html=html)
        return dict(base, html=_escapar_y_linkificar(content or ""))
    if tipo == "status_change":
        texto = content or _estado_cambiada(actividad)
        return dict(
            base,
            html=_escapar_y_linkificar(texto),
            chips=_chips_estados(actividad),
            chip_ids=_ids_estados(actividad),
        )
    if tipo == "version_update":
        texto = content
        versiones_chip = None
        prev = _formatear_version(actividad.get("previousVersion"))
        nuevo = _formatear_version(actividad.get("newVersion"))
        if not texto:
            if prev and nuevo:
                texto = "Versión actualizada de {0} a {1}".format(prev, nuevo)
            else:
                texto = "Versión actualizada"
        if prev and nuevo and prev != nuevo:
            versiones_chip = (prev, nuevo)
        return dict(base, html=_escapar_y_linkificar(texto), versiones_chip=versiones_chip)
    if tipo == "task_update":
        return dict(base, html=_escapar_y_linkificar(_texto_tarea(actividad)))
    if tipo == "batch_update":
        prev = _formatear_version(actividad.get("previousVersion"))
        nuevo = _formatear_version(actividad.get("newVersion"))
        versiones_chip = (prev, nuevo) if (prev and nuevo and prev != nuevo) else None
        return dict(
            base,
            html=_escapar_y_linkificar(content or ""),
            chips=_chips_estados(actividad),
            chip_ids=_ids_estados(actividad),
            versiones=_versiones_diferentes(actividad),
            versiones_chip=versiones_chip,
        )
    if tipo == "assignment_change":
        return dict(base, html=_escapar_y_linkificar(_texto_asignacion(actividad)))
    return dict(base, html=_escapar_y_linkificar(content or ""))


# ------------------------------------------------------- refs (v1.6.4)

def _ruta_destino_refs(ruta_comp):
    """Directorio donde se importan las refs: "<dir del comp>/ref" o None.

    Sin ruta de comp (aun sin guardar) devuelve None. Puro.
    """
    ruta = ruta_comp or ""
    if not str(ruta).strip():
        return None
    return os.path.join(os.path.dirname(str(ruta)), "ref")


def _filename_desde_url_ref(url, indice=0):
    """Basename decodificado de una URL firmada de storage (o fallback).

    La URL firmada es `.../o/<path>%2F<filename>?alt=media&token=...': se toma
    lo que sigue a `/o/` hasta `?alt=media`, se decodifica con
    `urllib.parse.unquote` y se queda con el ultimo segmento. Si el parseo
    falla (URL rara o sin `/o/`), devuelve `ref_<indice>.jpg`. Puro.
    """
    try:
        texto = str(url or "")
        inicio = texto.find("/o/")
        if inicio < 0:
            return "ref_{0}.jpg".format(indice)
        resto = texto[inicio + 3:]
        fin = resto.find("?alt=media")
        if fin < 0:
            fin = resto.find("?")
        if fin >= 0:
            resto = resto[:fin]
        nombre = urllib.parse.unquote(resto).replace("\\", "/")
        nombre = nombre.split("/")[-1].strip()
        if not nombre or nombre in (".", ".."):
            return "ref_{0}.jpg".format(indice)
        return nombre
    except Exception:
        return "ref_{0}.jpg".format(indice)


def _descargar_refs(urls, directorio, abrir=None):
    """Descarga una lista de URLs firmadas a `directorio` (una a una).

    Usa las firmadas tal cual (su token viaja en el query): GET puro con
    `urllib.request.Request(url)`, NUNCA Bearer. Reutiliza el opener de
    `vfxflow_auth._abrir` (que ya se memoiza). El `abrir` se recibe como
    parametro para poder fakearlo en tests (por defecto `vfxflow_auth._abrir`).

    Devuelve un dict con "ok" (lista de (url, ruta_local, filename) exitosas)
    y "fallidos" (lista de (url, mensaje)). Un fallo de una URL NO corta las
    demas.
    """
    abrir = abrir or vfxflow_auth._abrir
    os.makedirs(directorio, exist_ok=True)
    descargados = []
    fallidos = []
    for indice, url in enumerate(urls or []):
        nombre = _filename_desde_url_ref(url, indice)
        try:
            req = urllib.request.Request(str(url), method="GET")
            with abrir(req, timeout=_REFS_TIMEOUT_SEGUNDOS) as respuesta:
                datos = respuesta.read()
            ruta_local = os.path.join(directorio, nombre)
            with open(ruta_local, "wb") as archivo:
                archivo.write(datos)
            descargados.append((str(url), ruta_local, nombre))
        except Exception as e:
            fallidos.append((str(url), str(e)))
    return {"ok": descargados, "fallidos": fallidos}


class PanelComentarios(QtWidgets.QWidget):
    """Widget docked: contexto del plano activo + login a VFXFlow."""

    def __init__(self, parent=None):
        super(PanelComentarios, self).__init__(parent)
        # Estado de sesion en memoria: id_token/refresh_token/local_id/email
        # (+ expira_en: epoch aproximado de expiracion del id_token).
        self.sesion = None

        # Estado del canje loopback en worker: evita lanzar dos workers y le
        # dice al QTimer que solo observe `_loopback_trabajo` (regla Qt: la UI
        # se toca SOLO desde el hilo principal).
        self._loopback_trabajo = None
        self._loopback_trabajo_en_curso = False
        self._loopback_tiempo_trabajo_inicio = 0.0

        # Estado del fetch de comentarios en worker (misma regla que loopback):
        # `_comentarios_trabajo` publica "pendiente"/"ok"/"error" + datos y el
        # QTimer (`_poll_comentarios`) lo aplica a la UI en el hilo principal.
        self._comentarios_trabajo = None
        self._comentarios_trabajo_en_curso = False

        # Estado del import de refs en worker (misma regla): `_refs_trabajo`
        # publica "pendiente"/"ok"/"error" y el QTimer (`_poll_refs`) aplica.
        self._refs_trabajo = None
        self._refs_trabajo_en_curso = False

        # Estado del import de UN adjunto imagen (v1.6.5): `_adjunto_trabajo`
        # publica y el QTimer (`_poll_adjunto`) crea el Read.
        self._adjunto_trabajo = None
        self._adjunto_trabajo_en_curso = False

        # Escritura (v1.7.0): comentario/reply, estado y subida corren en un
        # worker y `_poll_escritura` aplica en el hilo principal.
        self._escritura_trabajo = None
        self._escritura_trabajo_en_curso = False

        # Modo respuesta: si `_reply_padre_id` es truthy, el input envía reply.
        self._reply_padre_id = None
        self._reply_padre_autor = ""

        # Última resolución del plano (worker) para escribir (ids + stateId).
        self._plano_resuelto = None
        # Estados reales del proyecto para el selector de estado.
        self._estados_combo = {}
        self._estados_ordenados = []
        self._estado_actual_id = ""

        self._construir_ui()
        self._arrancar_poll_plano()
        self._mostrar_plano_activo()
        self._autologin_si_hay_sesion()
        self._cargar_comentarios_del_plano()

    # ------------------------------------------------------------- UI

    def _construir_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        titulo = QtWidgets.QLabel("Comentarios por Plano — v1 (login)", self)
        titulo.setAlignment(QtAlignment.AlignCenter)
        titulo.setStyleSheet("font-weight: bold;")
        layout.addWidget(titulo)

        seccion_plano = QtWidgets.QGroupBox("Plano activo", self)
        grilla = QtWidgets.QGridLayout(seccion_plano)
        self._label_proyecto = self._fila_contexto(grilla, 0, "Proyecto")
        self._label_capitulo = self._fila_contexto(grilla, 1, "Capítulo")
        self._label_plano = self._fila_contexto(grilla, 2, "Plano")
        layout.addWidget(seccion_plano)

        seccion_login = QtWidgets.QGroupBox("Login VFXFlow", self)
        form = QtWidgets.QFormLayout(seccion_login)
        self._campo_email = QtWidgets.QLineEdit(self)
        self._campo_email.setPlaceholderText("email@samanestudio.com")
        form.addRow("Email", self._campo_email)
        self._campo_password = QtWidgets.QLineEdit(self)
        self._campo_password.setEchoMode(QtWidgets.QLineEdit.Password)
        self._campo_password.setPlaceholderText("contraseña")
        form.addRow("Contraseña", self._campo_password)
        self._boton_login = QtWidgets.QPushButton("Iniciar sesión", self)
        self._boton_login.clicked.connect(self._on_login)
        form.addRow(self._boton_login)
        self._boton_google = QtWidgets.QPushButton("Continuar con Google", self)
        self._boton_google.clicked.connect(self._on_login_google)
        form.addRow(self._boton_google)
        layout.addWidget(seccion_login)
        self._seccion_login = seccion_login

        seccion_sesion = QtWidgets.QGroupBox("Sesión VFXFlow", self)
        # Email + botón Desconectar en UNA línea: label a la izquierda, botón
        # a la derecha (antes el form tenía el botón en fila propia).
        fila_sesion = QtWidgets.QHBoxLayout(seccion_sesion)
        fila_sesion.setContentsMargins(8, 6, 8, 6)
        self._label_conectado = QtWidgets.QLabel("—", self)
        self._label_conectado.setWordWrap(False)
        fila_sesion.addWidget(self._label_conectado, 1)
        self._boton_desconectar = QtWidgets.QPushButton(
            "Desconectar", self
        )
        self._boton_desconectar.clicked.connect(self._on_desconectar)
        fila_sesion.addWidget(self._boton_desconectar)
        layout.addWidget(seccion_sesion)
        self._seccion_sesion = seccion_sesion

        seccion_comentarios = QtWidgets.QGroupBox("Actividad por Plano", self)
        lay_comentarios = QtWidgets.QVBoxLayout(seccion_comentarios)

        # Header (v1.6.1): plano identificado + selector de estado de 3 piezas
        # (v1.7.1, spec EnhancedShotStateSelector): ◀ chip ▶ + menú.
        fila_header = QtWidgets.QHBoxLayout()
        self._header_plano = QtWidgets.QLabel("—", seccion_comentarios)
        self._header_plano.setStyleSheet("font-weight: bold;")
        fila_header.addWidget(self._header_plano)
        fila_header.addStretch(1)

        self._estado_selector = QtWidgets.QWidget(seccion_comentarios)
        lay_selector = QtWidgets.QHBoxLayout(self._estado_selector)
        lay_selector.setContentsMargins(0, 0, 0, 0)
        lay_selector.setSpacing(2)
        self._boton_estado_anterior = QtWidgets.QToolButton(self._estado_selector)
        self._boton_estado_anterior.setText("◀")
        self._boton_estado_anterior.setToolTip("Estado anterior")
        self._boton_estado_anterior.setObjectName("botonEstadoAnterior")
        self._boton_estado_anterior.clicked.connect(self._on_estado_anterior)
        lay_selector.addWidget(self._boton_estado_anterior)
        self._boton_estado_actual = QtWidgets.QToolButton(self._estado_selector)
        self._boton_estado_actual.setObjectName("botonEstadoActual")
        self._boton_estado_actual.setToolTip("Cambiar estado")
        # NOTA: QToolButton NO soporta setTextFormat (eso es de QLabel); el
        # color del estado se muestra con el icono dot (ver _icono_estado).
        self._boton_estado_actual.setText("Estado")
        self._menu_estados = QtWidgets.QMenu(self._boton_estado_actual)
        self._menu_estados.triggered.connect(self._on_estado_menu)
        self._boton_estado_actual.setMenu(self._menu_estados)
        self._boton_estado_actual.setPopupMode(
            QtWidgets.QToolButton.InstantPopup
        )
        lay_selector.addWidget(self._boton_estado_actual)
        self._boton_estado_siguiente = QtWidgets.QToolButton(self._estado_selector)
        self._boton_estado_siguiente.setText("▶")
        self._boton_estado_siguiente.setToolTip("Estado siguiente")
        self._boton_estado_siguiente.setObjectName("botonEstadoSiguiente")
        self._boton_estado_siguiente.clicked.connect(self._on_estado_siguiente)
        lay_selector.addWidget(self._boton_estado_siguiente)
        fila_header.addWidget(self._estado_selector)
        lay_comentarios.addLayout(fila_header)

        # Fila de modo respuesta (v1.7): "Respondiendo a <autor> — [Cancelar]".
        fila_respuesta = QtWidgets.QHBoxLayout()
        self._label_modo_respuesta = QtWidgets.QLabel("", seccion_comentarios)
        self._label_modo_respuesta.setObjectName("verboActividad")
        fila_respuesta.addWidget(self._label_modo_respuesta)
        fila_respuesta.addStretch(1)
        self._boton_cancelar_respuesta = QtWidgets.QToolButton(seccion_comentarios)
        self._boton_cancelar_respuesta.setText("Cancelar")
        self._boton_cancelar_respuesta.clicked.connect(
            self._cancelar_modo_respuesta
        )
        fila_respuesta.addWidget(self._boton_cancelar_respuesta)
        self._fila_respuesta = QtWidgets.QWidget(seccion_comentarios)
        self._fila_respuesta.setLayout(fila_respuesta)
        self._fila_respuesta.setVisible(False)
        lay_comentarios.addWidget(self._fila_respuesta)

        # Input de comentario (v1.7.0 habilitado con sesión + plano).
        fila_input = QtWidgets.QHBoxLayout()
        self._input_comentario = QtWidgets.QLineEdit(seccion_comentarios)
        self._input_comentario.setPlaceholderText("Escribe comentario.")
        self._input_comentario.setEnabled(False)
        self._input_comentario.returnPressed.connect(self._on_enviar_comentario)
        fila_input.addWidget(self._input_comentario)
        self._boton_enviar = QtWidgets.QPushButton("➔", seccion_comentarios)
        self._boton_enviar.setEnabled(False)
        self._boton_enviar.setToolTip("Publicar comentario")
        self._boton_enviar.clicked.connect(self._on_enviar_comentario)
        fila_input.addWidget(self._boton_enviar)
        self._boton_subir_imagen = QtWidgets.QPushButton("🖼", seccion_comentarios)
        self._boton_subir_imagen.setEnabled(False)
        self._boton_subir_imagen.setToolTip("Subir imagen de referencia 1280×720")
        self._boton_subir_imagen.clicked.connect(self._on_subir_imagen)
        fila_input.addWidget(self._boton_subir_imagen)
        lay_comentarios.addLayout(fila_input)

        # Feed header: título + botón de refs (v1.6.4) + botón de refresco.
        fila_feed = QtWidgets.QHBoxLayout()
        label_titulo_feed = QtWidgets.QLabel("Actividad Reciente", seccion_comentarios)
        label_titulo_feed.setStyleSheet("font-weight: bold;")
        fila_feed.addWidget(label_titulo_feed)
        fila_feed.addStretch(1)
        self._boton_importar_refs = QtWidgets.QPushButton("Importar refs", seccion_comentarios)
        self._boton_importar_refs.setToolTip(
            "Descargar las imágenes de referencia del plano como nodos Read"
        )
        self._boton_importar_refs.clicked.connect(self._on_importar_refs)
        fila_feed.addWidget(self._boton_importar_refs)
        self._boton_refrescar = QtWidgets.QPushButton("↻", seccion_comentarios)
        self._boton_refrescar.setToolTip("Actualizar actividad")
        self._boton_refrescar.clicked.connect(self._on_actualizar_comentarios)
        fila_feed.addWidget(self._boton_refrescar)
        lay_comentarios.addLayout(fila_feed)

        # Feed de cards: QScrollArea con contenedor vertical de cards.
        self._scroll_actividad = QtWidgets.QScrollArea(seccion_comentarios)
        self._scroll_actividad.setWidgetResizable(True)
        self._scroll_actividad.setFrameShape(QtWidgets.QFrame.NoFrame)
        self._scroll_actividad.setAutoFillBackground(False)
        try:
            # el viewport por defecto es blanco en macOS: se deja transparente
            # para que se vea el fondo oscuro del panel (el QSS lo refuerza).
            self._scroll_actividad.viewport().setAutoFillBackground(False)
        except Exception:
            pass
        self._widget_contenido_actividad = QtWidgets.QWidget(self._scroll_actividad)
        self._layout_actividad = QtWidgets.QVBoxLayout(self._widget_contenido_actividad)
        self._layout_actividad.setContentsMargins(0, 0, 0, 0)
        self._scroll_actividad.setWidget(self._widget_contenido_actividad)
        # El feed necesita espacio: mínimo cómodo + factor de stretch para que
        # crezca con la altura disponible del panel (antes quedaba clavado en
        # 160 px y era incómodo explorar la actividad).
        self._scroll_actividad.setMinimumHeight(400)
        lay_comentarios.addWidget(self._scroll_actividad, 1)

        self._label_mensaje_actividad = QtWidgets.QLabel(self._widget_contenido_actividad)
        self._label_mensaje_actividad.setWordWrap(True)
        # La sección de actividad crece con el panel (factor 1): el feed es el
        # protagonista del widget y la etiqueta de estado mantiene su tamaño.
        layout.addWidget(seccion_comentarios, 1)
        self._seccion_comentarios = seccion_comentarios

        self._etiqueta_estado = QtWidgets.QLabel(self)
        self._etiqueta_estado.setWordWrap(True)
        layout.addWidget(self._etiqueta_estado)
        layout.addStretch(1)

        # Estado inicial: sin sesión, se muestra el login (la sesión se oculta).
        self._aplicar_estado_sesion_ui()

        # Habilitar escritura según sesión + plano identificado (v1.7).
        self._actualizar_habilitacion_escritura()

        # Tema oscuro acorde a Nuke, SOLO en este widget (nunca global).
        self.setStyleSheet(_ESTILO_PANEL)

    def _fila_contexto(self, grilla, fila, nombre):
        grilla.addWidget(QtWidgets.QLabel(nombre), fila, 0)
        valor = QtWidgets.QLabel("—")
        grilla.addWidget(valor, fila, 1)
        return valor

    # ---------------------------------------------------- contexto del plano

    def _plano_activo(self):
        """Dict de `nombres.parsear_plato` del comp abierto, o None.

        Sin comp guardado o sin parseo posible => None. Nunca lanza.
        """
        try:
            from SamanTools import nombres

            ruta = nuke.root().name() or ""
            if not ruta:
                return None
            return nombres.parsear_plato(ruta)
        except Exception:
            return None

    def _mostrar_plano_activo(self):
        """Rellena las etiquetas de contexto desde el comp abierto.

        Sin comp guardado o sin parseo posible => '—'. Nunca lanza.
        """
        try:
            from SamanTools import entorno

            ruta = nuke.root().name() or ""
            datos = self._plano_activo()

            proyecto = datos.get("proyecto") if datos else None
            if not proyecto:
                proyecto = entorno.proyecto_desde_ruta(ruta)
            capitulo = datos.get("capitulo") if datos else None
            plano = datos.get("plano") if datos else None

            self._label_proyecto.setText(proyecto or "—")
            self._label_capitulo.setText(
                str(capitulo) if capitulo is not None else "—"
            )
            self._label_plano.setText(plano or "—")
        except Exception:
            self._label_proyecto.setText("—")
            self._label_capitulo.setText("—")
            self._label_plano.setText("—")
        self._header_plano.setText(self._header_plano_texto())

    def _header_plano_texto(self):
        """Texto del header de la sección: "{proyecto}_{capitulo}_{plano}".

        Reconstruye el identificador del plano desde `nombres.parsear_plato`
        (sin versión ni extensión; el `canonico` las incluye y el header del
        mock solo muestra el plano). Sin plano identificado => "—".
        """
        try:
            datos = self._plano_activo() or {}
        except Exception:
            return "—"
        proyecto = datos.get("proyecto")
        capitulo = datos.get("capitulo")
        plano = datos.get("plano")
        if proyecto and capitulo is not None and plano:
            return "{0}_{1}_{2}".format(proyecto, capitulo, plano)
        return "—"

    def _arrancar_poll_plano(self):
        """Levanta el QTimer que detecta el cambio de comp activo.

        Cada `_POLL_PLANO_MS` compara `nuke.root().name()` con
        `_root_anterior`; si cambió, `_chequear_cambio_plano` refresca las
        etiquetas y recarga el feed (bug reportado: el feed no se actualizaba
        al abrir otro plano). Corre SIEMPRE en el hilo principal (QTimer). El
        root se captura con try/except para no romper bajo pytest (donde `nuke`
        es un stub que responde siempre). El timer vive mientras el widget;
        Nuke lo descarta al cerrar el panel.
        """
        try:
            self._root_anterior = nuke.root().name() or ""
        except Exception:
            self._root_anterior = ""
        self._plano_anterior = self._plano_activo()
        self._timer_plano = QtCore.QTimer(self)
        self._timer_plano.setInterval(_POLL_PLANO_MS)
        self._timer_plano.timeout.connect(self._chequear_cambio_plano)
        self._timer_plano.start()

    def _chequear_cambio_plano(self):
        """Tick del poll del comp activo: refresca y recarga si cambió el root.

        Lee `nuke.root().name()` y lo compara con `_root_anterior` (la fuente
        de verdad del cambio; `_plano_activo()` se re-parsea como dato para el
        fetch). Si cambió: actualiza el root guardado, refresca las etiquetas
        de contexto/header y recarga el feed automáticamente SOLO si hay una
        sesión con id_token vigente (sin sesión el feed se actualiza recién
        con ↻). No recarga si hay un worker de actividad en vuelo. Con el comp
        cerrado (`root` sin nombre), `_mostrar_plano_activo()` ya pone "—";
        tampoco se dispara red con plano None.
        """
        try:
            nombre = nuke.root().name() or ""
        except Exception:
            return
        if nombre == self._root_anterior:
            return
        self._root_anterior = nombre
        self._plano_anterior = self._plano_activo()
        self._mostrar_plano_activo()
        self._actualizar_habilitacion_escritura()
        if getattr(self, "_comentarios_trabajo_en_curso", False):
            return  # no molestar mientras hay un worker de actividad en vuelo
        sesion = getattr(self, "sesion", None)
        if sesion and sesion.get("email") and self._id_token_actual():
            self._cargar_comentarios_del_plano()

    # --------------------------------------------------------------- login

    def _on_login(self):
        email = self._campo_email.text().strip()
        contraseña = self._campo_password.text()
        if not email or not contraseña:
            self._estado("Ingresá email y contraseña.", error=True)
            return

        self._boton_login.setEnabled(False)  # evita el doble click
        self._estado("Iniciando sesión con VFXFlow…")
        try:
            respuesta = vfxflow_auth.loguear(email, contraseña)
            self._registrar_sesion(respuesta, email=email)
            usuario = vfxflow_auth.obtener_usuario(
                respuesta["local_id"], respuesta["id_token"]
            )
            self._fusionar_identidad_en_sesion(usuario)
            rol = usuario.get("role") or "artist"
            self._estado("Conectado como %s (%s)" % (email, rol))
            self._aplicar_estado_sesion_ui()
        except vfxflow_auth.VfxFlowAuthError as e:
            self._estado(str(e), error=True)
        except Exception as e:
            self._estado("Error inesperado: %s" % e, error=True)
        finally:
            self._boton_login.setEnabled(True)

    def _on_login_google(self):
        """"Continuar con Google": elige loopback o Device Flow según config.

        Si `google_client_id_escritorio` (client OAuth "Desktop app") está
        configurado usa el flujo de escritorio (loopback + PKCE, mejor UX:
        no hay que tipear un código); si no, cae al Device Flow existente
        (`_on_login_google_device`). Sin ninguno, avisa qué falta.
        """
        cfg = vfxflow_config.obtener_config_efectiva()
        if (cfg or {}).get("google_client_id_escritorio"):
            self._on_login_google_loopback()
        elif (cfg or {}).get("google_client_id"):
            self._on_login_google_device()
        else:
            self._estado(
                "Falta google_client_id_escritorio (loopback) y "
                "google_client_id (device flow) en la config.",
                error=True,
            )

    def _on_login_google_device(self):
        """Arranca el Device Flow de Google sin bloquear la UI de Nuke.

        Variante de respaldo (fallback) de "Continuar con Google" cuando no
        hay `google_client_id_escritorio`. Deshabilita ambos botones, pide el
        device_code, muestra la URL y el codigo al usuario (y abre el
        navegador si se puede) y dispara el polling con QTimer: un tick cada
        `interval` ms. El polling NUNCA congela Nuke. El refresh_token de
        Google no se toca ni se guarda.
        """
        self._boton_login.setEnabled(False)
        self._boton_google.setEnabled(False)
        try:
            codigo = vfxflow_auth.obtener_codigo_dispositivo()
        except vfxflow_auth.VfxFlowAuthError as e:
            self._estado(str(e), error=True)
            self._habilitar_botones_login()
            return
        except Exception as e:
            self._estado("Error inesperado: %s" % e, error=True)
            self._habilitar_botones_login()
            return

        self._google_device_code = codigo["device_code"]
        self._google_tiempo_inicio = time.time()
        self._google_intervalo = max(int(codigo.get("interval") or 5), 1)
        self._google_tiempo_maximo = int(codigo.get("expires_in") or 300)

        self._estado(
            "Andá a %s\ne ingresá el código: %s"
            % (codigo["verification_url"], codigo["user_code"])
        )
        try:
            webbrowser.open(codigo["verification_url"])
        except Exception:
            pass  # sin navegador, el usuario abre la URL a mano
        QtCore.QTimer.singleShot(
            self._google_intervalo * 1000,
            lambda: self._poll_google_login(
                self._google_device_code,
                self._google_intervalo,
                self._google_tiempo_inicio,
            ),
        )

    def _poll_google_login(self, device_code, intervalo, tiempo_inicio):
        """Un tick del polling del Device Flow; si sigue pendiente reprograma.

        Los estados authorization_pending / slow_down vuelven a programar el
        siguiente tick con QTimer.singleShot (así la UI respira entre polls);
        access_denied o el agotamiento del tiempo cortan el flujo.
        """
        if time.time() - tiempo_inicio >= self._google_tiempo_maximo:
            self._estado(
                "Se agotó el tiempo para autorizar el dispositivo en Google.",
                error=True,
            )
            self._habilitar_botones_login()
            return

        try:
            resultado = vfxflow_auth.consultar_estado_dispositivo(device_code)
        except vfxflow_auth.VfxFlowAuthError as e:
            self._estado(str(e), error=True)
            self._habilitar_botones_login()
            return
        except Exception as e:
            self._estado("Error inesperado: %s" % e, error=True)
            self._habilitar_botones_login()
            return

        if resultado["estado"] != "ok":
            codigo_error = resultado.get("codigo")
            if codigo_error == "authorization_pending":
                QtCore.QTimer.singleShot(
                    intervalo * 1000,
                    lambda: self._poll_google_login(
                        device_code, intervalo, tiempo_inicio
                    ),
                )
            elif codigo_error == "slow_down":
                nuevo_intervalo = intervalo + 5
                QtCore.QTimer.singleShot(
                    nuevo_intervalo * 1000,
                    lambda: self._poll_google_login(
                        device_code, nuevo_intervalo, tiempo_inicio
                    ),
                )
            elif codigo_error == "access_denied":
                self._estado(
                    "Inicio de sesión con Google denegado.", error=True
                )
                self._habilitar_botones_login()
            else:
                self._estado(
                    "Google respondió con un error en el flujo de dispositivo"
                    " (%s)." % codigo_error,
                    error=True,
                )
                self._habilitar_botones_login()
            return

        try:
            respuesta = vfxflow_auth.loguear_con_google(
                resultado["datos"]["id_token"]
            )
            email = respuesta.get("email") or ""
            self._registrar_sesion(respuesta, email=email)
            usuario = vfxflow_auth.obtener_usuario(
                respuesta["local_id"], respuesta["id_token"]
            )
            self._fusionar_identidad_en_sesion(usuario)
            rol = usuario.get("role") or "artist"
            self._estado("Conectado como %s (%s)" % (email, rol))
            self._aplicar_estado_sesion_ui()
        except vfxflow_auth.VfxFlowAuthError as e:
            self._estado(str(e), error=True)
        except Exception as e:
            self._estado("Error inesperado: %s" % e, error=True)
        finally:
            self._habilitar_botones_login()

    def _on_login_google_loopback(self):
        """Arranca el flujo OAuth de escritorio (loopback redirect + PKCE).

        Genera el par PKCE, levanta un mini server HTTP local en un puerto
        aleatorio (serve_forever SIEMPRE en thread daemon), muestra la URL de
        autorización y abre el navegador si se puede, y dispara el polling
        con QTimer (~1 s). El polling NUNCA congela Nuke. El servidor se
        cierra SIEMPRE (éxito, error, acceso denegado o timeout): nunca queda
        huérfano. El refresh_token de Google no se toca ni se guarda.
        """
        self._boton_login.setEnabled(False)
        self._boton_google.setEnabled(False)
        self._limpiar_loopback()
        self._loopback_trabajo = None
        self._loopback_trabajo_en_curso = False
        self._loopback_tiempo_trabajo_inicio = 0.0
        try:
            client_id = vfxflow_auth.obtener_client_id_escritorio()
            verifier, challenge = vfxflow_auth.generar_pkce()
            servidor, puerto = vfxflow_auth.crear_servidor_loopback()
        except vfxflow_auth.VfxFlowAuthError as e:
            self._estado(str(e), error=True)
            self._habilitar_botones_login()
            return
        except Exception as e:
            self._estado("Error inesperado: %s" % e, error=True)
            self._habilitar_botones_login()
            return

        self._loopback_client_id = client_id
        self._loopback_servidor = servidor
        self._loopback_tiempo_inicio = time.time()
        self._loopback_tiempo_maximo = 300
        redirect_uri = "http://127.0.0.1:%d" % puerto

        threading.Thread(
            target=servidor.serve_forever, daemon=True
        ).start()

        url = vfxflow_auth.construir_url_autorizacion(
            client_id, redirect_uri, challenge
        )
        self._estado("Si no se abrió el navegador, entrá a:\n%s" % url)
        try:
            webbrowser.open(url)
        except Exception:
            pass  # sin navegador, el usuario abre la URL a mano
        QtCore.QTimer.singleShot(
            1000,
            lambda: self._poll_loopback(servidor, redirect_uri, verifier),
        )

    def _poll_loopback(self, servidor, redirect_uri, verifier):
        """Un tick del polling del loopback; solo lee estado y delega.

        Regla inicial: NUNCA hace red en el hilo principal. Mientras el worker
        de canje corre, este metodo solo mira `self._loopback_trabajo` (y el
        reloj) y aplica el resultado a la UI cuando llega ("ok"/"error") o
        corta la espera si la red se traba mas de
        `_LOOPBACK_TIMEOUT_TRABAJO_SEGUNDOS`. Si el navegador todavia no
        redirigio con el code, reprograma en ~1 s; el timeout global (~300 s)
        corta el flujo completo y cierra el servidor.
        """
        if time.time() - self._loopback_tiempo_inicio >= self._loopback_tiempo_maximo:
            self._loopback_trabajo_en_curso = False
            self._limpiar_loopback()
            self._estado(
                "Se agotó el tiempo para autorizar el inicio de sesión con "
                "Google.",
                error=True,
            )
            self._habilitar_botones_login()
            return

        if self._loopback_trabajo_en_curso:
            self._vigilar_trabajo_loopback(servidor, redirect_uri, verifier)
            return

        resultado = servidor.resultado
        if not resultado:
            QtCore.QTimer.singleShot(
                1000,
                lambda: self._poll_loopback(servidor, redirect_uri, verifier),
            )
            return

        if "code" in resultado:
            # El canje (3 llamadas de red x hasta 10 s) corre en un worker
            # daemon; este tick NO bloquea. El servidor lo cierra el worker al
            # terminar (o el QTimer al cortar por timeout).
            self._lanzar_canje(servidor, resultado["code"], redirect_uri, verifier)
            QtCore.QTimer.singleShot(
                1000,
                lambda: self._poll_loopback(servidor, redirect_uri, verifier),
            )
            return

        self._limpiar_loopback()
        self._estado(
            "Google rechazó el inicio de sesión (%s)."
            % (resultado.get("error") or "error desconocido"),
            error=True,
        )
        self._habilitar_botones_login()

    def _vigilar_trabajo_loopback(self, servidor, redirect_uri, verifier):
        """Aplica el fin del worker de canje a la UI (hilo principal si o si).

        No toca widgets desde el hilo del worker: este metodo corre en el
        QTimer (hilo principal). Con "ok"/"error" publicados por el worker
        aplica el estado y deja de reprogramar; si sigue "pendiente" pasados
        ~35 s corta mostrando el mensaje de firewall y deja el worker daemon
        vivo en background (aceptable: la UI nunca queda esperando).
        """
        trabajo = self._loopback_trabajo or {}
        estado = trabajo.get("estado")

        if estado == "pendiente":
            if (
                time.time() - self._loopback_tiempo_trabajo_inicio
                >= _LOOPBACK_TIMEOUT_TRABAJO_SEGUNDOS
            ):
                self._loopback_trabajo_en_curso = False
                self._limpiar_loopback()
                self._estado(
                    self._mensaje_error_login_google(
                        "El canje de Google tardó demasiado.", "red"
                    ),
                    error=True,
                )
                self._habilitar_botones_login()
                return
            QtCore.QTimer.singleShot(
                1000,
                lambda: self._poll_loopback(servidor, redirect_uri, verifier),
            )
            return

        self._loopback_trabajo_en_curso = False
        self._limpiar_loopback()
        if estado == "ok":
            self._estado(
                "Conectado como %s (%s)" % (trabajo["email"], trabajo["rol"])
            )
            self._aplicar_estado_sesion_ui()
        else:
            self._estado(
                self._mensaje_error_login_google(
                    trabajo.get("mensaje") or "Error en el canje de Google.",
                    trabajo.get("codigo"),
                ),
                error=True,
            )
        self._habilitar_botones_login()

    def _lanzar_canje(self, servidor, code, redirect_uri, verifier):
        """Canjea el code (canjear->loguear->obtener_usuario->registrar) en un
        thread daemon para que NUNCA congele la UI de Nuke.

        El resultado se publica en `self._loopback_trabajo`
        ("pendiente"/"ok"/"error") y quien aplica los widgets es SIEMPRE el
        QTimer (hilo principal). `_registrar_sesion` escribe llaves de sesion
        en disco: se permite desde el worker (IO corta). Regla Qt respetada:
        desde el worker NO se toca ningun widget. `self._loopback_client_id`
        se fija antes de arrancar este worker y ya no cambia.
        """
        self._loopback_trabajo_en_curso = True
        self._loopback_tiempo_trabajo_inicio = time.time()
        self._loopback_trabajo = {"estado": "pendiente"}

        def trabajo():
            try:
                tokens = vfxflow_auth.canjear_codigo_autorizacion(
                    code,
                    redirect_uri,
                    verifier,
                    self._loopback_client_id,
                )
                respuesta = vfxflow_auth.loguear_con_google(tokens["id_token"])
                email = respuesta.get("email") or ""
                self._registrar_sesion(respuesta, email=email)
                usuario = vfxflow_auth.obtener_usuario(
                    respuesta["local_id"], respuesta["id_token"]
                )
                self._fusionar_identidad_en_sesion(usuario)
                rol = usuario.get("role") or "artist"
                self._loopback_trabajo = {"estado": "ok", "email": email, "rol": rol}
            except vfxflow_auth.VfxFlowAuthError as e:
                self._loopback_trabajo = {
                    "estado": "error",
                    "mensaje": str(e),
                    "codigo": e.codigo,
                }
            except Exception as e:
                self._loopback_trabajo = {
                    "estado": "error",
                    "mensaje": "Error inesperado: %s" % e,
                    "codigo": "desconocido",
                }
            finally:
                try:
                    servidor.cerrar()
                except Exception:
                    pass

        threading.Thread(target=trabajo, daemon=True).start()

    def _mensaje_error_login_google(self, mensaje, codigo):
        """Define que mensaje mostrar segun el tipo de fallo del login Google.

        Cuando la red no conecta ("red": timeout / sin salida a Google) se
        explica el bloqueo de outbound del estudio, porque el sintoma real es
        confuso (el navegador funciona, el panel no). Con cualquier otro codigo
        se muestra el error original de la API.
        """
        if codigo == "red":
            return _MENSAJE_FIREWALL_GOOGLE
        return mensaje

    def _limpiar_loopback(self):
        """Cierra el servidor loopback si sigue vivo (nunca dejar huérfanos).

        Idempotente: `cerrar()` del servidor ya es no-op tras la primera
        llamada (la hace el propio handler al recibir el callback).
        """
        servidor = getattr(self, "_loopback_servidor", None)
        if servidor is not None:
            try:
                servidor.cerrar()
            except Exception:
                pass
        self._loopback_servidor = None

    def _habilitar_botones_login(self):
        self._boton_login.setEnabled(True)
        self._boton_google.setEnabled(True)

    def _aplicar_estado_sesion_ui(self):
        """Muestra login o sesión según haya una sesión activa.

        Con sesión en memoria se oculta la sección "Login VFXFlow" y se
        muestra "Sesión VFXFlow" con el email conectado y el botón para
        desconectar; sin sesión, lo inverso. Tolerante a widgets ausentes
        (instancias de prueba creadas con `__new__`): si no se construyó la
        UI no hace nada.
        """
        if not getattr(self, "_seccion_login", None):
            return
        conectado = bool(self.sesion and self.sesion.get("email"))
        self._seccion_login.setVisible(not conectado)
        self._seccion_sesion.setVisible(conectado)
        if conectado:
            self._label_conectado.setText(self.sesion["email"])
        self._actualizar_habilitacion_escritura()

    def _on_desconectar(self):
        """Cierra la sesión local (y la persistida) y vuelve al login.

        No revoca el refresh_token en Google ni en VFXFlow: el usuario puede
        volver a entrar sin reautorizar; desconectar solo saca los tokens del
        equipo. Nunca lanza.
        """
        try:
            sesion_vfxflow.borrar_sesion()
        except Exception:
            pass
        self.sesion = None
        self._aplicar_estado_sesion_ui()
        self._estado("Sesión cerrada.")

    def _registrar_sesion(self, respuesta, email=None):
        """Guarda la sesión en memoria y persiste tokens + perfil en disco.

        `local_id` sale de `respuesta.local_id` o `respuesta.user_id` (el
        refresh devuelve `user_id`, no `local_id`): asi el autologin no pierde
        el id (fix v1.7.x de identidad). La identidad denormalizada
        (userName/userPhotoURL/role) prevalece de la respuesta o se conserva
        de la sesión previa; viaja a `guardar_sesion` para el autologin y el
        payload de escritura. Nunca guarda id_token/password.
        """
        sesion_previa = getattr(self, "sesion", None) or {}
        try:
            expira_en = time.time() + int(respuesta.get("expires_in", 3600))
        except (TypeError, ValueError):
            expira_en = time.time() + 3600

        self.sesion = {
            "id_token": respuesta["id_token"],
            "refresh_token": (
                respuesta.get("refresh_token")
                or sesion_previa.get("refresh_token")
                or ""
            ),
            "local_id": (
                respuesta.get("local_id")
                or respuesta.get("user_id")
                or sesion_previa.get("local_id")
                or ""
            ),
            "email": (
                email or respuesta.get("email") or sesion_previa.get("email")
            ),
            "expira_en": expira_en,
            "userName": (
                respuesta.get("userName") or sesion_previa.get("userName") or ""
            ),
            "userPhotoURL": (
                respuesta.get("userPhotoURL")
                or respuesta.get("avatarUrl")
                or sesion_previa.get("userPhotoURL")
                or ""
            ),
            "role": (respuesta.get("role") or sesion_previa.get("role") or ""),
        }
        sesion_vfxflow.guardar_sesion(self.sesion)

    def _fusionar_identidad_en_sesion(self, usuario):
        """Denormaliza el perfil `users/{uid}` en la sesión y la persiste.

        `usuario` es el doc aplanado de `obtener_usuario` (name/role/
        avatarUrl/userPhotoURL). Actualiza userName/userPhotoURL/role solo si
        vienen (sin pisar lo ya presente) y vuelve a persistir: la identidad
        queda disponible en el autologin y en `_base_campos_actividad`.
        Devuelve la sesión actualizada. Nunca lanza.
        """
        sesion = self.sesion or {}
        usuario = usuario or {}
        nombre = usuario.get("name") or usuario.get("userName") or ""
        if nombre:
            sesion["userName"] = nombre
        rol = usuario.get("role") or ""
        if rol:
            sesion["role"] = rol
        foto = usuario.get("avatarUrl") or usuario.get("userPhotoURL") or ""
        if foto:
            sesion["userPhotoURL"] = foto
        self.sesion = sesion
        try:
            sesion_vfxflow.guardar_sesion(self.sesion)
        except Exception:
            pass
        return sesion

    def _rellenar_identidad_si_falta(self):
        """Autologin: rellena la identidad best-effort si la sesión no la trae.

        Sesiones viejas (persistidas antes del fix) no tienen userName/role:
        se consulta `users/{uid}` y se fusiona. Nunca rompe el autologin.
        """
        sesion = getattr(self, "sesion", None) or {}
        if not sesion.get("local_id") or not sesion.get("id_token"):
            return
        if sesion.get("userName") and sesion.get("role"):
            return
        try:
            usuario = vfxflow_auth.obtener_usuario(
                sesion["local_id"], sesion["id_token"]
            )
            self._fusionar_identidad_en_sesion(usuario)
        except Exception:
            pass

    def _autologin_si_hay_sesion(self):
        """Si hay refresh_token guardado, reconecta silenciosamente.

        GATE DE ACCESO: si la config del disco (.saman/vfxflow_config.json)
        no esta disponible (unidad wupm no montada o archivo ausente), NO
        autologinea ni reutiliza la sesion: la config vive tras los ACL de
        LucidLink y sin ella no hay credenciales de app. Ante CUALQUIER
        fallo borra la sesion y deja que el usuario inicie sesion de nuevo.
        Nunca bloquea la apertura del panel.
        """
        try:
            from . import vfxflow_config

            if not vfxflow_config.config_disco_disponible():
                self._estado("Sin acceso: conectá la unidad wupm.")
                return
        except Exception:
            pass  # sin config no se puede validar el acceso; no autologinear
        try:
            guardada = sesion_vfxflow.cargar_sesion()
            if not guardada or not guardada.get("refresh_token"):
                return
            # Seed con lo guardado (incluye la identidad denormalizada) para
            # que `_registrar_sesion` la conserve al refrescar (v1.7.x).
            if getattr(self, "sesion", None) is None:
                self.sesion = dict(guardada)
            respuesta = vfxflow_auth.refrescar_id_token(
                guardada["refresh_token"]
            )
            self._registrar_sesion(respuesta, email=guardada.get("email"))
            # Sesiones viejas (antes del fix) no traen identidad: rellenarla.
            self._rellenar_identidad_si_falta()
            email = guardada.get("email")
            if email:
                self._estado("Reconectado como %s" % email)
            else:
                self._estado("Reconectado con VFXFlow.")
            self._aplicar_estado_sesion_ui()
        except Exception:
            sesion_vfxflow.borrar_sesion()

    # ------------------------------------------------------ token vigente

    def _id_token_actual(self):
        """Devuelve un id_token vigente, refrescandolo solo si hace falta.

        Si la sesion tiene `expira_en` (epoch), refresca al vencer; si no lo
        tiene (sesion reconstruida desde disco), refresca si el archivo de
        sesion fue escrito hace mas de 50 minutos. Devuelve None si no hay
        sesion o si el refresh falla.
        """
        if not self.sesion:
            return None
        id_token = self.sesion.get("id_token")
        if not id_token or not self.sesion.get("refresh_token"):
            return id_token

        expira_en = self.sesion.get("expira_en")
        if expira_en is not None:
            vencido = time.time() > expira_en
        else:
            vencido = self._sesion_guardada_hace_mas_de(
                _VENTANA_REFRESH_SEGUNDOS
            )
        if not vencido:
            return id_token

        try:
            respuesta = vfxflow_auth.refrescar_id_token(
                self.sesion["refresh_token"]
            )
        except Exception:
            return None
        self._registrar_sesion(respuesta)
        return self.sesion.get("id_token")

    def _sesion_guardada_hace_mas_de(self, segundos):
        """Aproxima la antiguedad con la mtime del archivo persistido."""
        try:
            return (
                time.time() - os.path.getmtime(sesion_vfxflow.ruta_sesion())
            ) > segundos
        except OSError:
            return True

    # ------------------------------------------------------ actividad del plano

    def _on_actualizar_comentarios(self):
        """Botón "↻" del feed: dispara el fetch de actividad del plano activo."""
        self._cargar_comentarios_del_plano()

    def _cargar_comentarios_del_plano(self):
        """Dispara el fetch de actividad del plano activo (worker daemon).

        Precondiciones antes de tocar la red: plano identificado y sesión con
        id_token vigente. Sin plano o sin token NO se lanza query: se muestra
        el mensaje correspondiente en el área de actividad. Con las
        precondiciones listas publica `pendiente` en `_comentarios_trabajo`,
        corre el fetch en un thread daemon y programa el QTimer que aplica el
        resultado a la UI (nunca se tocan widgets desde el worker).
        """
        plano = self._plano_activo()
        if plano is None:
            self._mostrar_mensaje_actividad(_MENSAJE_PLANO_NO_IDENTIFICADO)
            self._estado(_MENSAJE_PLANO_NO_IDENTIFICADO)
            return

        token = self._id_token_actual()
        if not token:
            self._mostrar_mensaje_actividad(_MENSAJE_SIN_SESION)
            self._estado(_MENSAJE_SIN_SESION)
            return

        if getattr(self, "_comentarios_trabajo_en_curso", False):
            return  # ya hay un worker de actividad en vuelo

        self._comentarios_trabajo_en_curso = True
        self._comentarios_trabajo = {"estado": "pendiente"}
        self._estado("Cargando actividad…")
        threading.Thread(
            target=self._trabajo_comentarios,
            args=(plano, token),
            daemon=True,
        ).start()
        QtCore.QTimer.singleShot(_COMENTARIOS_POLL_MS, self._poll_comentarios)

    def _trabajo_comentarios(self, plano, token):
        """Worker daemon: resuelve el shot, lee actividad, colores y cache.

        Nunca toca widgets: publica el resultado en `_comentarios_trabajo`
        ("ok" con la actividad + colores de estados + imagenes cacheadas, o
        "error" con mensaje/codigo). El QTimer (`_poll_comentarios`) es quien
        aplica a la UI. Los "no encontrado" de la resolucion son un error de
        datos (no de red): mensaje normalizado. Las descargas de imagenes de
        adjuntos corren acá (worker) y la UI solo lee las rutas locales.
        """
        try:
            resuelto = vfxflow_datos.resolver_plano(plano, token)
            if resuelto is None or resuelto.get("error"):
                self._comentarios_trabajo = {
                    "estado": "error",
                    "mensaje": self._mensaje_error_resolucion(resuelto),
                    "codigo": "resolucion",
                }
                return
            actividad = vfxflow_datos.listar_actividad(
                resuelto["project_id"], resuelto["shot_id"], token
            )
            # Los colores de estados y las imagenes de adjuntos NUNCA rompen el
            # feed: ante fallo caen a {} / texto sin thumbnail.
            colores = vfxflow_datos.obtener_colores_estados(
                resuelto["project_id"], token
            )
            try:
                imagenes = _cargar_imagenes_adjuntas(actividad)
            except Exception:
                imagenes = {}
            # Estados reales para el combo (v1.7): [] no rompe el feed.
            try:
                estados = vfxflow_datos.obtener_estados(
                    resuelto["project_id"], token
                )
            except Exception:
                estados = []
            self._plano_resuelto = resuelto
            self._comentarios_trabajo = {
                "estado": "ok",
                "comentarios": actividad,
                "colores_estados": colores,
                "imagenes": imagenes,
                "estados": estados,
                "estado_actual": (resuelto.get("shot") or {}).get("stateId") or "",
            }
        except vfxflow_auth.VfxFlowAuthError as e:
            self._comentarios_trabajo = {
                "estado": "error",
                "mensaje": str(e),
                "codigo": e.codigo,
            }
        except Exception as e:
            self._comentarios_trabajo = {
                "estado": "error",
                "mensaje": "Error inesperado: %s" % e,
                "codigo": "desconocido",
            }

    def _poll_comentarios(self):
        """Tick del QTimer (hilo principal): aplica el resultado del fetch.

        Solo observa `_comentarios_trabajo` (nunca toca widgets desde el
        worker). Mientras es "pendiente" reprograma el tick; con "ok"/"error"
        publica en la UI y libera `_comentarios_trabajo_en_curso`.
        """
        if not getattr(self, "_comentarios_trabajo_en_curso", False):
            return
        trabajo = self._comentarios_trabajo or {}
        estado = trabajo.get("estado")

        if estado == "pendiente":
            QtCore.QTimer.singleShot(
                _COMENTARIOS_POLL_MS, self._poll_comentarios
            )
            return

        self._comentarios_trabajo_en_curso = False
        if estado == "ok":
            self._poblar_estado_selector(
                trabajo.get("estados") or [],
                trabajo.get("estado_actual") or "",
            )
            self._publicar_actividad(
                trabajo.get("comentarios") or [],
                colores_estados=trabajo.get("colores_estados") or {},
                imagenes=trabajo.get("imagenes") or {},
            )
        else:
            self._aplicar_error_actividad(trabajo)

    # ------------------------------------------------- feed de cards

    def _limpiar_feed(self):
        """Quita todas las cards (y el mensaje) del layout del feed."""
        layout = getattr(self, "_layout_actividad", None)
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

    def _publicar_actividad(self, actividad, colores_estados=None, imagenes=None):
        """Pinta las cards del feed (o el mensaje de vacio), agrupando replies.

        `_agrupar_actividad` separa padres e hijas (parentId set); cada padre
        publica su card y, si tiene respuestas, un bloque colapsable debajo
        (`_crear_bloque_respuestas`). `colores_estados` y `imagenes` (rutas de
        cache) ya vienen del worker: acá solo se aplican.
        """
        if not actividad:
            self._mostrar_mensaje_actividad(_MENSAJE_SIN_ACTIVIDAD)
            self._estado(_MENSAJE_SIN_ACTIVIDAD)
            return
        self._limpiar_feed()
        colores_estados = colores_estados or {}
        imagenes = imagenes or {}
        padres, hijas = _agrupar_actividad(actividad)
        for padre in padres:
            self._layout_actividad.addWidget(
                self._crear_card_actividad(
                    padre,
                    colores_estados=colores_estados,
                    imagenes=imagenes,
                )
            )
            hijas_padre = hijas.get(padre.get("id")) or []
            if hijas_padre:
                self._layout_actividad.addWidget(
                    self._crear_bloque_respuestas(
                        hijas_padre,
                        colores_estados=colores_estados,
                        imagenes=imagenes,
                    )
                )
        self._layout_actividad.addStretch(1)
        cantidad = len(actividad)
        self._estado(
            "%d actividad%s."
            % (cantidad, "es" if cantidad != 1 else "")
        )

    def _crear_card_actividad(
        self, actividad, colores_estados=None, imagenes=None, es_respuesta=False
    ):
        """Construye la QFrame de una actividad (header + cuerpo por tipo).

        v1.6.5 (spec app web): avatar circular 32×32 con la inicial, autor
        negrita, verbo gris, rol como chip, tiempo relativo largo en español,
        "• editado" si metadata.edited, ⚠ si el autor está en la ventana de
        10 min, glifo de tipo, chips de estado con el color REAL de
        projectStates (nuevo → previo), chips de versión, y thumbnails de
        adjuntos imagen (click → zoom; botón importar). Todo el look vive en
        `_ESTILO_PANEL` por objectName.
        """
        card = QtWidgets.QFrame(self._widget_contenido_actividad)
        card.setObjectName("cardRespuesta" if es_respuesta else "cardActividad")
        card.setFrameShape(QtWidgets.QFrame.NoFrame)
        lay_card = QtWidgets.QVBoxLayout(card)
        lay_card.setContentsMargins(8, 6, 8, 6)

        # Fila avatar circular + autor + verbo + rol chip + tiempo largo.
        fila_autor = QtWidgets.QHBoxLayout()
        avatar = QtWidgets.QLabel(
            _inicial_avatar(actividad.get("userName")), card
        )
        avatar.setObjectName("avatarActividad")
        avatar.setFixedSize(32, 32)
        avatar.setAlignment(QtAlignment.AlignCenter)
        fila_autor.addWidget(avatar)
        autor = QtWidgets.QLabel(actividad.get("userName") or "Anónimo", card)
        autor.setObjectName("autorActividad")
        fila_autor.addWidget(autor)
        verbo = _verbo_tipo(actividad.get("type"))
        if verbo:
            label_verbo = QtWidgets.QLabel(verbo, card)
            label_verbo.setObjectName("verboActividad")
            fila_autor.addWidget(label_verbo)
        rol = actividad.get("userRole") or ""
        if rol:
            label_rol = QtWidgets.QLabel(rol, card)
            label_rol.setObjectName("rolActividad")
            fila_autor.addWidget(label_rol)
        fila_autor.addStretch(1)
        sesion = getattr(self, "sesion", None)
        if _dentro_ventana_10min(actividad.get("createdAt")) and _es_autor(
            actividad, sesion
        ):
            ventana = QtWidgets.QLabel("⚠", card)
            ventana.setObjectName("ventanaActividad")
            ventana.setToolTip(
                "Puede editar/eliminar (ventana de 10 minutos)"
            )
            fila_autor.addWidget(ventana)
        tiempo = QtWidgets.QLabel(
            _tiempo_relativo_largo(actividad.get("createdAt")), card
        )
        tiempo.setObjectName("tiempoActividad")
        fila_autor.addWidget(tiempo)
        if (actividad.get("metadata") or {}).get("edited"):
            editado = QtWidgets.QLabel("• editado", card)
            editado.setObjectName("editoActividad")
            fila_autor.addWidget(editado)
        glifo = _glifo_tipo(actividad.get("type"))
        if glifo:
            label_glifo = QtWidgets.QLabel(glifo, card)
            label_glifo.setObjectName("glifoTipo")
            fila_autor.addWidget(label_glifo)
        lay_card.addLayout(fila_autor)

        # Cuerpo segun el tipo (puro y testeable) + cita + adjuntos.
        cuerpo = _cuerpo_actividad(actividad)
        if cuerpo["html"]:
            label_cuerpo = QtWidgets.QLabel(cuerpo["html"], card)
            label_cuerpo.setWordWrap(True)
            label_cuerpo.setTextFormat(QtCore.Qt.RichText)
            label_cuerpo.setOpenExternalLinks(True)
            lay_card.addWidget(label_cuerpo)
        if cuerpo["cita"]:
            label_cita = QtWidgets.QLabel(cuerpo["cita"], card)
            label_cita.setWordWrap(True)
            label_cita.setTextFormat(QtCore.Qt.RichText)
            lay_card.addWidget(label_cita)
        for widget in self._render_adjuntos(actividad, card, imagenes or {}):
            lay_card.addWidget(widget)
        if cuerpo["chips"] is not None:
            self._agregar_fila_estados(
                cuerpo, colores_estados or {}, card, lay_card
            )
        if cuerpo.get("versiones_chip"):
            previo, nuevo = cuerpo["versiones_chip"]
            fila_v = QtWidgets.QHBoxLayout()
            chip_vieja = QtWidgets.QLabel("[{0}]".format(previo), card)
            chip_vieja.setObjectName("chipVersionVieja")
            chip_nueva = QtWidgets.QLabel("[{0}]".format(nuevo), card)
            chip_nueva.setObjectName("chipVersionNueva")
            flecha_v = QtWidgets.QLabel("→", card)
            fila_v.addWidget(chip_nueva)
            fila_v.addWidget(flecha_v, 0, QtAlignment.AlignCenter)
            fila_v.addWidget(chip_vieja)
            fila_v.addStretch(1)
            lay_card.addLayout(fila_v)
        elif cuerpo.get("versiones"):
            label_version = QtWidgets.QLabel(cuerpo["versiones"], card)
            label_version.setObjectName("versionActividad")
            lay_card.addWidget(label_version)
        # Botón "Responder" (v1.7) en cards padre comentables (comment/file).
        if not es_respuesta and actividad.get("type") in ("comment", "file_upload"):
            fila_acciones = QtWidgets.QHBoxLayout()
            fila_acciones.addStretch(1)
            boton_responder = QtWidgets.QToolButton(card)
            boton_responder.setText("Responder")
            boton_responder.setObjectName("botonResponder")
            autor = actividad.get("userName") or "Anónimo"
            padre_id = actividad.get("id") or ""
            boton_responder.clicked.connect(
                lambda checked=False, a=autor, p=padre_id:
                self._iniciar_modo_respuesta(a, p)
            )
            fila_acciones.addWidget(boton_responder)
            lay_card.addLayout(fila_acciones)
        return card

    def _agregar_fila_estados(self, cuerpo, colores, card, lay_card):
        """Chips de status [NUEVO] → [PREVIO] con el color real del estado.

        El color sale del mapa {stateId: color} (id en `cuerpo["chip_ids"]`);
        sin color cae al chip neutral `QLabel#chipEstado`. Orden invertido
        segun la spec (el estado nuevo a la izquierda).
        """
        previo, nuevo = cuerpo["chips"]
        ids = cuerpo.get("chip_ids")
        color_previo = ""
        color_nuevo = ""
        if ids:
            id_previo, id_nuevo = ids
            color_previo = _color_estado(colores, id_previo)
            color_nuevo = _color_estado(colores, id_nuevo)
        fila = QtWidgets.QHBoxLayout()
        fila.addWidget(self._chip_estado(nuevo, card, color_nuevo))
        flecha = QtWidgets.QLabel("→", card)
        fila.addWidget(flecha, 0, QtAlignment.AlignCenter)
        fila.addWidget(self._chip_estado(previo, card, color_previo))
        fila.addStretch(1)
        lay_card.addLayout(fila)

    def _chip_estado(self, texto, parent, color=""):
        """Label estilo chip para las badges de estados (nunca hardcodeados).

        El look base lo define `QLabel#chipEstado`; con `color` (hex real del
        projectState) se aplica un stylesheet inline con alpha ~30%.
        """
        chip = QtWidgets.QLabel(str(texto), parent)
        chip.setObjectName("chipEstado")
        chip.setAlignment(QtAlignment.AlignCenter)
        if color:
            chip.setStyleSheet(_styles_chip_color(color))
        return chip

    # ------------------------------------------------- adjuntos (v1.6.5)

    def _render_adjuntos(self, actividad, parent, imagenes):
        """Widgets de adjuntos: thumbnails/texto + botón importar por imagen.

        Cada adjunto image lleva SIEMPRE el botón "⬇ Importar"
        (`_debe_mostrar_boton_importar`), aunque el thumbnail falle (cache
        ausente o QPixmap nulo por codecs): el usuario siempre puede bajar la
        imagen. Los adjuntos file caen a filas de texto con su tamaño.
        """
        adjuntos = [
            a for a in (actividad.get("attachments") or []) if isinstance(a, dict)
        ]
        if not adjuntos:
            return []
        # Contexto del comentario padre para marcar el Read/Text2 importado.
        contexto = {
            "autor": actividad.get("userName") or "",
            "contenido": actividad.get("content") or "",
            "comentario_id": actividad.get("id") or "",
        }
        widgets = []
        for adj in adjuntos:
            if _debe_mostrar_boton_importar(adj, imagenes or {}):
                ruta = imagenes.get(str(adj.get("url"))) if adj.get("url") else None
                widgets.append(
                    self._crear_adjunto_imagen(adj, ruta, parent, contexto)
                )
            else:
                label = QtWidgets.QLabel(
                    _escapar_y_linkificar(_linea_adjunto_texto(adj)), parent
                )
                label.setWordWrap(True)
                label.setTextFormat(QtCore.Qt.RichText)
                label.setOpenExternalLinks(True)
                widgets.append(label)
        return widgets

    def _crear_adjunto_imagen(self, adj, ruta_local, parent, contexto=None):
        """Contenedor de un adjunto imagen: preview (si pudo) + botón importar.

        El botón "⬇ Importar" aparece SIEMPRE (TAREA A). Si el thumbnail cargó
        va debajo del preview; si no, aparece junto al texto. `contexto`
        (dict con autor/contenido/comentario_id) marca el Read/Text2.

        UX (v1.7.2): clic simple en la miniatura = importar (la cadena Read +
        Text2 con el comentario y su autor); doble clic = zoom modal. El botón
        ⬇ debajo queda como affordance explícita (redundante por diseño).
        """
        cont = QtWidgets.QWidget(parent)
        lay = QtWidgets.QVBoxLayout(cont)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        pixmap = (
            QtWidgets.QPixmap(ruta_local) if ruta_local else QtWidgets.QPixmap()
        )
        if pixmap.isNull():
            # Sin preview (codecs/cache): texto + botón en la misma fila.
            fila = QtWidgets.QHBoxLayout()
            label = QtWidgets.QLabel(
                _escapar_y_linkificar(_linea_adjunto_texto(adj)), cont
            )
            label.setWordWrap(True)
            label.setTextFormat(QtCore.Qt.RichText)
            label.setOpenExternalLinks(True)
            fila.addWidget(label, 1)
            fila.addWidget(self._crear_boton_importar(adj, cont, contexto))
            lay.addLayout(fila)
            return cont
        boton_importar = self._crear_boton_importar(adj, cont, contexto)
        miniatura = QtWidgets.QLabel(cont)
        miniatura.setPixmap(
            pixmap.scaled(
                320, 208, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation
            )
        )
        miniatura.setCursor(QtCore.Qt.PointingHandCursor)
        nombre = (adj.get("name") or "adjunto").strip()
        tamanio = _formatear_tamano_bytes(adj.get("size"))
        miniatura.setToolTip(
            "{0} — {1}".format(nombre, tamanio) if tamanio else nombre
        )

        def _importar_por_clic():
            if self._clic_importar_adjunto(adj, contexto, objetivo=boton_importar):
                # Feedback mínimo sobre la miniatura mientras descarga.
                miniatura.setToolTip("Importando…")
                miniatura.setCursor(QtCore.Qt.WaitCursor)

        miniatura.mousePressEvent = lambda evento: _importar_por_clic()
        miniatura.mouseDoubleClickEvent = (
            lambda evento, r=ruta_local: self._doble_clic_zoom_adjunto(r)
        )
        lay.addWidget(miniatura)
        fila = QtWidgets.QHBoxLayout()
        label_nombre = QtWidgets.QLabel("Adjuntó: {0}".format(nombre), cont)
        label_nombre.setWordWrap(True)
        fila.addWidget(label_nombre)
        fila.addStretch(1)
        fila.addWidget(boton_importar)
        lay.addLayout(fila)
        return cont

    def _clic_importar_adjunto(self, adj, contexto=None, objetivo=None):
        """Handler del clic (botón ⬇ o miniatura): importa con feedback.

        Si ya hay un worker de adjunto en vuelo no hace nada (False). Con
        `objetivo` (el QToolButton ⬇) lo deshabilita y muestra "⏳…", y al
        final dispara `_importar_adjunto(url, nombre, contexto)` — la misma
        cadena que crea Read + Text2 con el comentario y su autor.
        """
        if not isinstance(adj, dict):
            return False
        if getattr(self, "_adjunto_trabajo_en_curso", False):
            return False
        url = (adj.get("url") or "").strip()
        nombre = (adj.get("name") or "adjunto").strip()
        if objetivo is not None:
            for metodo, valor in (
                ("setEnabled", False),
                ("setToolTip", "Importando…"),
                ("setText", "⏳…"),
            ):
                try:
                    getattr(objetivo, metodo)(valor)
                except Exception:
                    pass
        self._importar_adjunto(url, nombre, contexto)
        return True

    def _doble_clic_zoom_adjunto(self, ruta_local):
        """Doble clic en la miniatura: abre el zoom modal sin bloquear el clic."""
        self._abrir_zoom_imagen(ruta_local)

    def _crear_boton_importar(self, adj, parent, contexto=None):
        """QToolButton "⬇ Importar" por adjunto de imagen (TAREA A).

        Al pulsar descarga a `<dir>/ref/adjuntos/<filename>` y crea el Read +
        Text2 marcados con el comentario (`contexto`). Muestra "⏳…" mientras
        el worker del adjunto está en vuelo. Afordance explícita: el clic en
        la miniatura hace lo mismo.
        """
        boton = QtWidgets.QToolButton(parent)
        boton.setText("⬇ Importar")
        boton.setToolTip("Descargar el adjunto y crearlo como nodo Read")

        def _click():
            self._clic_importar_adjunto(adj, contexto, objetivo=boton)

        boton.clicked.connect(lambda checked=False: _click())
        return boton

    def _abrir_zoom_imagen(self, ruta_local, parent=None):
        """Modal con la imagen en tamaño completo (escalada a la pantalla)."""
        try:
            pixmap = QtWidgets.QPixmap(ruta_local)
            if pixmap.isNull():
                return
            dialogo = QtWidgets.QDialog(parent or self)
            dialogo.setWindowTitle("Imagen adjunta")
            lay = QtWidgets.QVBoxLayout(dialogo)
            label = QtWidgets.QLabel(dialogo)
            label.setPixmap(
                pixmap.scaled(
                    1200, 800, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation
                )
            )
            lay.addWidget(label)
            cerrar = QtWidgets.QPushButton("Cerrar", dialogo)
            cerrar.clicked.connect(dialogo.accept)
            lay.addWidget(cerrar)
            dialogo.exec_()
        except Exception:
            pass

    def _importar_adjunto(self, url, nombre, contexto=None):
        """Importa un adjunto imagen a `<dir>/ref/adjuntos` + nodo Read/Text2.

        `contexto` (dict con autor/contenido/comentario_id) se guarda en
        `_adjunto_trabajo` para marcar el Read y crear el Text2 en
        `_poll_adjunto`. Corre con descarga en worker
        (`_trabajo_importar_adjunto`) y el createNode en QTimer, nunca desde
        el worker.
        """
        dir_comp = os.path.dirname(nuke.root().name() or "")
        if not dir_comp:
            self._estado("Guardá el comp antes de importar el adjunto.", error=True)
            return
        directorio = os.path.join(dir_comp, "ref", "adjuntos")
        if getattr(self, "_adjunto_trabajo_en_curso", False):
            return
        self._adjunto_trabajo_en_curso = True
        self._adjunto_trabajo = {"estado": "pendiente", "contexto": contexto}
        self._estado("Importando adjunto…")
        threading.Thread(
            target=self._trabajo_importar_adjunto,
            args=(url, directorio, nombre, contexto),
            daemon=True,
        ).start()
        QtCore.QTimer.singleShot(_COMENTARIOS_POLL_MS, self._poll_adjunto)

    def _trabajo_importar_adjunto(self, url, directorio, nombre, contexto=None):
        """Worker daemon: descarga un adjunto y publica en `_adjunto_trabajo`."""
        try:
            resultado = _descargar_refs([str(url)], directorio)
            if not resultado["ok"]:
                self._adjunto_trabajo = {
                    "estado": "error",
                    "mensaje": "No se pudo descargar el adjunto.",
                }
                return
            _url, _ruta_local, filename = resultado["ok"][0]
            self._adjunto_trabajo = {
                "estado": "ok",
                "nombre": filename,
                "directorio": directorio,
                "contexto": contexto,
            }
        except vfxflow_auth.VfxFlowAuthError as e:
            self._adjunto_trabajo = {"estado": "error", "mensaje": str(e)}
        except Exception as e:
            self._adjunto_trabajo = {
                "estado": "error",
                "mensaje": "Error inesperado: %s" % e,
            }

    def _poll_adjunto(self):
        """QTimer (hilo principal): crea el Read (y Text2) del adjunto.

        En éxito crea el Read con `file` (convención del estudio) y el knob
        `label` con el comentario, y un nodo Text2 suelto cuyo knob `message`
        lleva el contenido del comentario (no se conecta al Read; un fallo del
        Text2 no rompe el Read).
        """
        if not getattr(self, "_adjunto_trabajo_en_curso", False):
            return
        trabajo = self._adjunto_trabajo or {}
        if trabajo.get("estado") == "pendiente":
            QtCore.QTimer.singleShot(_COMENTARIOS_POLL_MS, self._poll_adjunto)
            return
        self._adjunto_trabajo_en_curso = False
        if trabajo.get("estado") == "ok":
            try:
                contexto = trabajo.get("contexto") or {}
                comp = nuke.root().name() or ""
                nodo = nuke.createNode("Read")
                nodo["file"].setValue(
                    _ruta_read_ref(comp, "adjuntos/{0}".format(trabajo["nombre"]))
                )
                try:
                    nodo["label"].setValue(_label_read_adjunto(contexto))
                except Exception:
                    pass
                # Text2 suelto con el texto del comentario (snippet del usuario).
                try:
                    contenido = (contexto.get("contenido") or "").strip()
                    nodo_texto = nuke.createNode("Text2")
                    nodo_texto["message"].setValue(
                        contenido or "«sin texto»"
                    )
                    autor = (contexto.get("autor") or "").strip()
                    nodo_texto["label"].setValue(
                        "comentario de {0}".format(autor) if autor else "comentario"
                    )
                except Exception:
                    pass  # un Text2 que falla no rompe el Read
                self._estado("Adjunto importado como Read (con comentario).")
            except Exception as e:
                self._estado("Error al importar el adjunto: %s" % e, error=True)
            return
        self._estado(
            trabajo.get("mensaje") or "Error al importar el adjunto.", error=True
        )

    # ------------------------------------------------- escritura (v1.7.0)

    def _actualizar_habilitacion_escritura(self):
        """Habilita input/➔/🖼 SOLO con sesión + plano identificado (v1.7)."""
        try:
            plano = self._plano_activo()
        except Exception:
            plano = None
        sesion = getattr(self, "sesion", None)
        habilitado = bool(sesion and sesion.get("email") and plano)
        for attr in ("_input_comentario", "_boton_enviar", "_boton_subir_imagen"):
            widget = getattr(self, attr, None)
            if widget is None:
                continue
            widget.setEnabled(habilitado)
        input_widget = getattr(self, "_input_comentario", None)
        if input_widget is not None:
            input_widget.setToolTip(
                "Necesitás iniciar sesión y un plano identificado para comentar."
                if not habilitado
                else ""
            )
        # El selector de estado se habilita con su propia lógica (estados +
        # sesión + escritura en vuelo): `_aplicar_estado_selector_enabled`.
        self._aplicar_estado_selector_enabled()
        # La fila de modo respuesta depende de la habilitación.
        fila = getattr(self, "_fila_respuesta", None)
        if fila is not None and not habilitado:
            self._cancelar_modo_respuesta()

    def _iniciar_modo_respuesta(self, autor, padre_id):
        """Pone el input en modo reply (guarda el padre y muestra el aviso)."""
        self._reply_padre_id = padre_id
        self._reply_padre_autor = autor or ""
        label = getattr(self, "_label_modo_respuesta", None)
        fila = getattr(self, "_fila_respuesta", None)
        if label is not None:
            label.setText("Respondiendo a {0}".format(autor or "…"))
        if fila is not None:
            fila.setVisible(True)
        self._input_comentario.setFocus()

    def _cancelar_modo_respuesta(self):
        """Saca el input del modo reply y restaura el placeholder."""
        self._reply_padre_id = None
        self._reply_padre_autor = ""
        fila = getattr(self, "_fila_respuesta", None)
        if fila is not None:
            fila.setVisible(False)
        self._input_comentario.setPlaceholderText("Escribe comentario.")

    def _on_enviar_comentario(self):
        """➔/Enter: valida y lanza la creación del comment o reply (worker)."""
        texto = self._input_comentario.text().strip()
        if not texto:
            return
        plano = self._plano_activo()
        token = self._id_token_actual()
        if not plano or not token:
            self._estado(
                "Necesitás plano identificado y sesión para comentar.", error=True
            )
            return
        if getattr(self, "_escritura_trabajo_en_curso", False):
            return  # no publicar dos actividades a la vez
        sesion = self.sesion or {}
        if self._reply_padre_id and not self._reply_padre_autor:
            self._reply_padre_autor = "…"
        tipo = "reply" if self._reply_padre_id else "comment"
        campos = _base_campos_actividad("", "", sesion, tipo, texto)
        if self._reply_padre_id:
            campos["parentId"] = self._reply_padre_id
        self._lanzar_escritura(
            self._trabajo_crear_actividad,
            (plano, campos, token),
            "Publicando {0}…".format("respuesta" if tipo == "reply" else "comentario"),
        )

    def _lanzar_escritura(self, trabajo_callable, args, mensaje_inicial):
        """Arranca un worker de escritura + QTimer que aplica."""
        self._escritura_trabajo_en_curso = True
        self._escritura_trabajo = {"estado": "pendiente"}
        self._estado(mensaje_inicial)
        threading.Thread(target=trabajo_callable, args=args, daemon=True).start()
        QtCore.QTimer.singleShot(_COMENTARIOS_POLL_MS, self._poll_escritura)

    def _trabajo_crear_actividad(self, plano, campos, token):
        """Worker: resuelve el plano y crea la actividad en shotActivity."""
        try:
            resuelto = vfxflow_datos.resolver_plano(plano, token)
            if resuelto is None or resuelto.get("error"):
                self._escritura_trabajo = {
                    "estado": "error",
                    "mensaje": self._mensaje_error_resolucion(resuelto),
                }
                return
            self._plano_resuelto = resuelto
            campos["shotId"] = resuelto["shot_id"]
            campos["projectId"] = resuelto["project_id"]
            self._crear_documento_actividad(resuelto["project_id"], campos, token)
            tipo = campos.get("type") or "actividad"
            self._escritura_trabajo = {
                "estado": "ok",
                "mensaje": "Comentario publicado."
                if tipo == "comment"
                else ("Respuesta publicada." if tipo == "reply" else "Publicado."),
                "publicado": True,
            }
        except vfxflow_auth.VfxFlowAuthError as e:
            self._escritura_trabajo = {
                "estado": "error",
                "mensaje": self._mensaje_error_escritura(e),
            }
        except Exception as e:
            self._escritura_trabajo = {
                "estado": "error",
                "mensaje": "Error inesperado: %s" % e,
            }

    def _poll_escritura(self):
        """QTimer (hilo principal): aplica el resultado de la escritura.

        En éxito limpia el input, cancela el modo reply y recarga el feed +
        combo (que el worker re-resolvió). Los errores van al estado sin
        romper la UI.
        """
        if not getattr(self, "_escritura_trabajo_en_curso", False):
            return
        trabajo = self._escritura_trabajo or {}
        if trabajo.get("estado") == "pendiente":
            QtCore.QTimer.singleShot(_COMENTARIOS_POLL_MS, self._poll_escritura)
            return
        self._escritura_trabajo_en_curso = False
        if trabajo.get("estado") == "ok":
            if trabajo.get("publicado"):
                self._input_comentario.clear()
                self._cancelar_modo_respuesta()
            self._estado(trabajo.get("mensaje") or "Hecho.")
            self._cargar_comentarios_del_plano()
            return
        self._estado(
            trabajo.get("mensaje") or "No se pudo escribir en VFXFlow.",
            error=True,
        )

    def _mensaje_error_escritura(self, error):
        """Mensaje claro para los fallos de escritura (403/400 rules, red…)."""
        codigo = getattr(error, "codigo", None)
        if codigo == "red":
            return _MENSAJE_FIREWALL_GOOGLE
        if codigo == "http":
            return (
                "No se pudo escribir en VFXFlow (parece un problema de "
                "permisos: consultá al admin si no tenés acceso de escritura)."
            )
        if codigo == "token":
            return "Sesión vencida: iniciá sesión de nuevo."
        return str(error)

    def _crear_documento_actividad(self, project_id, campos, token):
        """Crea un doc en projects/{pid}/shotActivity (createDocument REST)."""
        cfg = vfxflow_config.obtener_config_efectiva()
        fb = (cfg or {}).get("project_id") or project_id
        url = (
            "https://firestore.googleapis.com/v1/projects/{fb}/databases/"
            "(default)/documents/projects/{pid}/shotActivity"
        ).format(fb=fb, pid=project_id)
        return vfxflow_auth._post_json_bearer(
            url, {"fields": _payload_actividad(campos)}, token
        )

    def _actualizar_estado_shot(self, resuelto, nuevo_id, nuevo_nombre, token):
        """PATCH del doc del shot con stateId/status (updateMask)."""
        cfg = vfxflow_config.obtener_config_efectiva()
        fb = (cfg or {}).get("project_id") or resuelto["project_id"]
        url = (
            "https://firestore.googleapis.com/v1/projects/{fb}/databases/"
            "(default)/documents/projects/{pid}/chapters/{cid}/shots/{sid}"
        ).format(
            fb=fb,
            pid=resuelto["project_id"],
            cid=resuelto["chapter_id"],
            sid=resuelto["shot_id"],
        )
        payload = {
            "fields": {
                "stateId": {"stringValue": str(nuevo_id)},
                "status": {"stringValue": str(nuevo_nombre)},
            },
            "updateMask": {"fieldPaths": ["stateId", "status"]},
        }
        return vfxflow_auth._patch_json_bearer(url, payload, token)

    # ------------------------------------------- selector de estado (v1.7.1)

    def _poblar_estado_selector(self, estados, estado_actual):
        """Actualiza el selector de 3 piezas (chip + flechas + menú).

        Guarda `_estados_combo` {id: item}, `_estados_ordenados` (ids en el
        orden que llega: `obtener_estados` ya ordena por `order` asc) y el
        estado actual, y re-renderiza chip/menú/habilitación. `estados` viene
        del worker de actividad (nunca rompe el feed).
        """
        self._estados_combo = {str(e.get("id")): e for e in estados or []}
        self._estados_ordenados = [
            str(e["id"]) for e in estados or [] if e.get("id")
        ]
        self._estado_actual_id = str(estado_actual) if estado_actual else ""
        self._reconstruir_menu_estados()
        self._refrescar_chip_estado()
        self._aplicar_estado_selector_enabled()

    def _reconstruir_menu_estados(self):
        """Reconstruye el QMenu del chip con todos los estados del proyecto.

        El item actual va checkable+checked y con "✓ " (QAction plano: los
        menús nativos no renderizan rich text). El icono es un dot 16×16 del
        color del estado, best-effort (sin paint device se omite; el chip
        sigue mostrando el color). Decisión documentada.
        """
        menu = getattr(self, "_menu_estados", None)
        if menu is None:
            return
        menu.clear()
        for estado_id, texto, es_actual in _acciones_estado(
            self._estados_ordenados, self._estados_combo, self._estado_actual_id
        ):
            accion = menu.addAction(texto)
            accion.setData(estado_id)
            if es_actual:
                accion.setCheckable(True)
                accion.setChecked(True)
            color = _color_estado_chip(self._estados_combo.get(estado_id))
            icono = _icono_dot_estado(color)
            if icono is not None:
                accion.setIcon(icono)

    def _refrescar_chip_estado(self):
        """Pinta el chip central con "● color + nombre estado actual"."""
        chip = getattr(self, "_boton_estado_actual", None)
        if chip is None:
            return
        item = self._estados_combo.get(self._estado_actual_id) or {}
        nombre = item.get("name")
        if not nombre:
            chip.setText("Estado")
            return
        color = _color_estado_chip(item)
        # Sin rich text (QToolButton): el color va como icono dot + texto plano.
        icono = _icono_dot_estado(color)
        if icono is not None:
            chip.setIcon(icono)
        chip.setText(str(nombre))

    def _aplicar_estado_selector_enabled(self):
        """Habilita los 3 botones del selector según sesión/plano/estados.

        El chip se habilita con sesión + plano + estados reales; las flechas
        además con tener anterior/siguiente en el orden. Durante una escritura
        en vuelo (`_escritura_trabajo_en_curso`) todo queda deshabilitado.
        """
        try:
            plano = self._plano_activo()
        except Exception:
            plano = None
        sesion = getattr(self, "sesion", None)
        base = bool(sesion and sesion.get("email") and plano)
        base = base and not bool(getattr(self, "_escritura_trabajo_en_curso", False))
        estados_combo = getattr(self, "_estados_combo", None) or {}
        tiene_estados = bool(estados_combo)
        anterior_id, siguiente_id = _indices_estado_anterior_siguiente(
            getattr(self, "_estados_ordenados", []) or [],
            getattr(self, "_estado_actual_id", "") or "",
        )
        chip = getattr(self, "_boton_estado_actual", None)
        if chip is not None:
            chip.setEnabled(base and tiene_estados)
            chip.setToolTip(
                "Sin estados disponibles"
                if not tiene_estados
                else "Cambiar estado"
            )
        btn_ant = getattr(self, "_boton_estado_anterior", None)
        if btn_ant is not None:
            btn_ant.setEnabled(base and tiene_estados and anterior_id is not None)
        btn_sig = getattr(self, "_boton_estado_siguiente", None)
        if btn_sig is not None:
            btn_sig.setEnabled(base and tiene_estados and siguiente_id is not None)

    def _on_estado_menu(self, accion):
        """QMenu del chip: salto directo al estado elegido (handleStateChange)."""
        estado_id = accion.data() if accion is not None else None
        if estado_id:
            self._cambiar_a_estado(estado_id)

    def _on_estado_anterior(self):
        """◀: va al estado anterior en el orden `order` (si existe)."""
        anterior_id, _ = _indices_estado_anterior_siguiente(
            self._estados_ordenados, self._estado_actual_id
        )
        if anterior_id:
            self._cambiar_a_estado(anterior_id)

    def _on_estado_siguiente(self):
        """▶: va al estado siguiente en el orden `order` (si existe)."""
        _, siguiente_id = _indices_estado_anterior_siguiente(
            self._estados_ordenados, self._estado_actual_id
        )
        if siguiente_id:
            self._cambiar_a_estado(siguiente_id)

    def _cambiar_a_estado(self, nuevo_id):
        """Aplica el cambio de estado (actividad status_change + PATCH shot).

        Recibe el ID del estado (las flechas y el menú dan ids; el flujo de
        escritura es el mismo de siempre: worker + QTimer). Si el id es el
        actual no hace nada. En vuelo deshabilita el selector.
        """
        nuevo = self._estados_combo.get(str(nuevo_id)) if nuevo_id else None
        if not nuevo:
            return
        if str(nuevo_id) == self._estado_actual_id:
            return  # ya está en ese estado
        plano = self._plano_activo()
        token = self._id_token_actual()
        resuelto = getattr(self, "_plano_resuelto", None)
        if not plano or not token or not resuelto or resuelto.get("error"):
            self._estado(
                "Actualizá la actividad primero (resolver el plano).", error=True
            )
            return
        shot = resuelto.get("shot") or {}
        previo_id = shot.get("stateId") or ""
        previo_nombre = shot.get("status") or ""
        if not previo_nombre:
            previo_nombre = "desconocido"
        campos = _campos_status_change(
            resuelto["project_id"],
            resuelto["shot_id"],
            self.sesion or {},
            previo_id,
            previo_nombre,
            nuevo.get("id"),
            nuevo.get("name") or nuevo.get("id"),
        )
        if getattr(self, "_escritura_trabajo_en_curso", False):
            return
        self._lanzar_escritura(
            self._trabajo_cambio_estado,
            (plano, token, resuelto, campos),
            "Cambiando estado…",
        )
        self._aplicar_estado_selector_enabled()

    def _trabajo_cambio_estado(self, plano, token, resuelto, campos):
        """Worker: crea la actividad status_change y PATCHea el shot.

        Si el PATCH del shot falla por rules, la actividad queda creada y se
        avisa (decisión documentada): el feed registra el cambio igual.
        """
        try:
            self._crear_documento_actividad(resuelto["project_id"], campos, token)
        except (vfxflow_auth.VfxFlowAuthError, Exception) as e:
            self._escritura_trabajo = {
                "estado": "error",
                "mensaje": self._mensaje_error_escritura(e),
            }
            return
        try:
            self._actualizar_estado_shot(
                resuelto,
                campos["newState"],
                campos["newStateName"],
                token,
            )
        except vfxflow_auth.VfxFlowAuthError as e:
            self._escritura_trabajo = {
                "estado": "ok",
                "mensaje": (
                    "Estado registrado en la actividad; no se pudo actualizar "
                    "el shot ({0})".format(self._mensaje_error_escritura(e))
                ),
            }
            return
        except Exception as e:
            self._escritura_trabajo = {
                "estado": "ok",
                "mensaje": (
                    "Estado registrado; no se pudo actualizar el shot (%s)" % e
                ),
            }
            return
        self._escritura_trabajo = {"estado": "ok", "mensaje": "Estado cambiado."}

    # ------------------------------------------------------- subir imagen (B.3)

    def _on_subir_imagen(self):
        """🖼: elige imagen, la procesa a 1280×720 jpg y la sube (worker)."""
        plano = self._plano_activo()
        token = self._id_token_actual()
        if not plano or not token:
            self._estado(
                "Necesitás plano identificado y sesión para subir.", error=True
            )
            return
        if getattr(self, "_escritura_trabajo_en_curso", False):
            return
        ruta, _filtro = QtWidgets.QFileDialog.getOpenFileName(
            self, "Subir imagen", "",
            "Imágenes (*.jpg *.jpeg *.png *.tif *.tiff *.exr);;Todos (*)",
        )
        if not ruta:
            return
        jpg_temporal = _ruta_jpg_temporal()
        if not _convertir_jpg_1280x720(ruta, jpg_temporal):
            self._estado("No se pudo procesar la imagen.", error=True)
            return
        try:
            size = os.path.getsize(jpg_temporal)
        except OSError:
            size = 0
        nombre = os.path.basename(ruta)
        self._lanzar_escritura(
            self._trabajo_subir_imagen,
            (jpg_temporal, plano, token, nombre, size, self.sesion or {}),
            "Subiendo imagen…",
        )

    def _trabajo_subir_imagen(
        self, jpg_temporal, plano, token, nombre_origen, size, sesion
    ):
        """Worker: resuelve shot, sube el jpg a storage y crea file_upload."""
        try:
            resuelto = vfxflow_datos.resolver_plano(plano, token)
            if resuelto is None or resuelto.get("error"):
                self._escritura_trabajo = {
                    "estado": "error",
                    "mensaje": self._mensaje_error_resolucion(resuelto),
                }
                return
            self._plano_resuelto = resuelto
            project_id = resuelto["project_id"]
            cfg = vfxflow_config.obtener_config_efectiva()
            bucket = (cfg or {}).get("storage_bucket") or "vfxpm-be912.firebasestorage.app"
            local_id = (sesion or {}).get("local_id") or "anon"
            ruta_storage = "projects/{0}/image_comments/{1}_{2}.jpg".format(
                project_id, local_id, int(time.time())
            )
            encoded = urllib.parse.quote(ruta_storage, safe="")
            with open(jpg_temporal, "rb") as fh:
                datos = fh.read()
            url_subida = (
                "https://firebasestorage.googleapis.com/upload/storage/v1/b/"
                "{b}/o?uploadType=media&name={n}"
            ).format(b=bucket, n=encoded)
            vfxflow_auth._upload_media_bearer(url_subida, datos, token, "image/jpeg")
            # Token de descarga para la URL firmada del adjunto.
            meta_url = (
                "https://firebasestorage.googleapis.com/v0/b/{b}/o/{n}"
            ).format(b=bucket, n=encoded)
            meta = vfxflow_auth._get_con_bearer(meta_url, token) or {}
            tokens = (
                meta.get("downloadTokens")
                or meta.get("downloadToken")
                or meta.get("downloadURL")
                or ""
            )
            if tokens:
                firma = str(tokens).split(",")[0].strip()
                url_adjunto = (
                    "https://firebasestorage.googleapis.com/v0/b/{b}/o/{n}"
                    "?alt=media&token={t}"
                ).format(b=bucket, n=encoded, t=firma)
            else:
                media = meta.get("mediaLink") or ""
                if not media:
                    self._escritura_trabajo = {
                        "estado": "error",
                        "mensaje": "El storage no devolvió token de descarga.",
                    }
                    return
                url_adjunto = media
            campos = _base_campos_actividad(
                project_id,
                resuelto["shot_id"],
                sesion,
                "file_upload",
                nombre_origen,
            )
            campos["attachments"] = [
                {
                    "id": "att_{0}".format(int(time.time() * 1000)),
                    "type": "image",
                    "url": url_adjunto,
                    "name": nombre_origen,
                    "size": size,
                    "mimeType": "image/jpeg",
                }
            ]
            self._crear_documento_actividad(project_id, campos, token)
            self._escritura_trabajo = {"estado": "ok", "mensaje": "Imagen subida."}
        except vfxflow_auth.VfxFlowAuthError as e:
            self._escritura_trabajo = {
                "estado": "error",
                "mensaje": self._mensaje_error_escritura(e),
            }
        except Exception as e:
            self._escritura_trabajo = {
                "estado": "error",
                "mensaje": "Error inesperado: %s" % e,
            }

    # -------------------------------------------- respuestas (v1.6.5)

    def _crear_bloque_respuestas(
        self, hijas, colores_estados=None, imagenes=None
    ):
        """Bloque colapsable "▸/▾ Ver N respuestas" bajo un comentario padre.

        Las hijas se muestran indentadas (margin-left) como cards planas
        `cardRespuesta`; el estado expanded/collapsed vive solo en memoria de
        este widget. La flecha rota por cambio de glifo (▸/▾) en vez de QSS.
        """
        cantidad = len(hijas)
        sufijo = "respuesta" if cantidad == 1 else "respuestas"
        texto_cerrado = "▸ Ver {0} {1}".format(cantidad, sufijo)
        texto_abierto = "▾ Ver {0} {1}".format(cantidad, sufijo)

        bloque = QtWidgets.QWidget(self._widget_contenido_actividad)
        lay = QtWidgets.QVBoxLayout(bloque)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        boton = QtWidgets.QToolButton(bloque)
        boton.setObjectName("botonRespuestas")
        boton.setText(texto_cerrado)
        boton.setCheckable(True)
        boton.setChecked(False)
        boton.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
        lay.addWidget(boton)

        cont_hijas = QtWidgets.QWidget(bloque)
        lay_hijas = QtWidgets.QVBoxLayout(cont_hijas)
        lay_hijas.setContentsMargins(16, 0, 0, 0)
        lay_hijas.setSpacing(4)
        for hija in hijas:
            lay_hijas.addWidget(
                self._crear_card_actividad(
                    hija,
                    colores_estados=colores_estados,
                    imagenes=imagenes,
                    es_respuesta=True,
                )
            )
        cont_hijas.setVisible(False)
        lay.addWidget(cont_hijas)

        def _alternar():
            expandido = boton.isChecked()
            cont_hijas.setVisible(expandido)
            boton.setText(texto_abierto if expandido else texto_cerrado)

        boton.clicked.connect(lambda checked=False: _alternar())
        return bloque

    def _aplicar_error_actividad(self, trabajo):
        """Publica un error del fetch: firewall para "red", texto si no.

        El error detallado va SOLO en el area del feed (`_mostrar_mensaje_actividad`);
        la etiqueta de estado inferior lleva estados de accion ("cargando...",
        "3 actividades") y NO repite el mismo texto (evita la duplicacion visual
        que el usuario reporto en v1.6.1).
        """
        mensaje = trabajo.get("mensaje") or "No se pudieron cargar los comentarios."
        codigo = trabajo.get("codigo")
        if codigo == "red":
            texto = self._mensaje_error_login_google(mensaje, codigo)
        else:
            texto = mensaje
        self._mostrar_mensaje_actividad(texto, error=True)

    def _mensaje_error_resolucion(self, resuelto):
        """Texto del error de resolucion (plano sin registrar en VFXFlow)."""
        error = (resuelto or {}).get("error")
        if error == "proyecto_no_encontrado":
            return "El proyecto '{0}' no está en VFXFlow.".format(
                (resuelto or {}).get("proyecto")
            )
        if error == "capitulo_no_encontrado":
            return "El capítulo {0} no está en VFXFlow.".format(
                (resuelto or {}).get("capitulo")
            )
        if error == "plano_no_encontrado":
            return "El plano '{0}' no está en VFXFlow.".format(
                (resuelto or {}).get("plano")
            )
        return "El plano no se encontró en VFXFlow."

    def _mostrar_mensaje_actividad(self, texto, error=False):
        """Pinta un mensaje placeholder en el área del feed (reemplaza cards)."""
        self._limpiar_feed()
        label = getattr(self, "_label_mensaje_actividad", None)
        if label is None or getattr(self, "_layout_actividad", None) is None:
            return
        label.setText(texto)
        label.setStyleSheet(
            "color:{0};font-style:italic;".format(_COLOR_ERROR)
            if error
            else "color:{0};font-style:italic;".format(_COLOR_MENSAJE)
        )
        self._layout_actividad.addWidget(label)
        self._layout_actividad.addStretch(1)

    # ------------------------------------------------------- refs (v1.6.4)

    def _on_importar_refs(self):
        """Botón "Importar refs": dispara el import del plano activo."""
        self._cargar_refs_del_plano()

    def _cargar_refs_del_plano(self):
        """Dispara el import de refs del plano activo (worker daemon).

        Precondiciones antes de tocar la red: plano identificado, sesión con
        id_token vigente y comp guardado (el directorio destino es
        "<dir del comp>/ref", que se computa ACA en el hilo principal para no
        llamar a `nuke.root()` desde el worker). Sin precondiciones: mensaje
        de estado y NO se lanza el worker. Con las precondiciones listas
        publica `pendiente` en `_refs_trabajo`, corre el import en un thread
        daemon y programa el QTimer (`_poll_refs`) que aplica a la UI.
        """
        plano = self._plano_activo()
        if plano is None:
            self._estado(_MENSAJE_PLANO_NO_IDENTIFICADO, error=True)
            return

        token = self._id_token_actual()
        if not token:
            self._estado(_MENSAJE_SIN_SESION_REFS, error=True)
            return

        directorio = _ruta_destino_refs(nuke.root().name() or "")
        if not directorio:
            self._estado(_MENSAJE_COMP_SIN_GUARDAR, error=True)
            return

        if getattr(self, "_refs_trabajo_en_curso", False):
            return  # ya hay un worker de refs en vuelo

        self._refs_trabajo_en_curso = True
        self._refs_trabajo = {"estado": "pendiente"}
        self._estado("Importando referencias…")
        threading.Thread(
            target=self._importar_refs_del_plano,
            args=(plano, token, directorio),
            daemon=True,
        ).start()
        QtCore.QTimer.singleShot(_COMENTARIOS_POLL_MS, self._poll_refs)

    def _importar_refs_del_plano(self, plano, token, directorio):
        """Worker daemon: resuelve el shot, baja las refs y publica resultado.

        Nunca toca widgets ni nuke: publica en `_refs_trabajo`
        ("ok" con `descargados`/`fallidos`, o "error" con mensaje/codigo). El
        QTimer (`_poll_refs`) es quien aplica a la UI (incluido el createNode).
        Sin `referenceImages`: "ok" con `sin_refs=True` (mensaje informativo,
        no error). Sin thumbnails en v1.6.4: el foco es importar + nodo Read.
        """
        try:
            resuelto = vfxflow_datos.resolver_plano(plano, token)
            if resuelto is None or resuelto.get("error"):
                self._refs_trabajo = {
                    "estado": "error",
                    "mensaje": self._mensaje_error_resolucion(resuelto),
                    "codigo": "resolucion",
                }
                return
            urls = (resuelto.get("shot") or {}).get("referenceImages") or []
            if not urls:
                self._refs_trabajo = {
                    "estado": "ok",
                    "sin_refs": True,
                    "mensaje": _MENSAJE_SIN_REFS,
                }
                return
            resultado = _descargar_refs(urls, directorio)
            self._refs_trabajo = {
                "estado": "ok",
                "descargados": resultado["ok"],
                "fallidos": resultado["fallidos"],
                "directorio": directorio,
            }
        except vfxflow_auth.VfxFlowAuthError as e:
            self._refs_trabajo = {
                "estado": "error",
                "mensaje": str(e),
                "codigo": e.codigo,
            }
        except Exception as e:
            self._refs_trabajo = {
                "estado": "error",
                "mensaje": "Error inesperado: %s" % e,
                "codigo": "desconocido",
            }

    def _poll_refs(self):
        """Tick del QTimer (hilo principal): aplica el resultado del import.

        Solo observa `_refs_trabajo` (nunca toca widgets desde el worker).
        Mientras es "pendiente" reprograma; con "ok"/"error" aplica y libera
        `_refs_trabajo_en_curso`. El createNode de los Read corre ACÁ (hilo
        principal).
        """
        if not getattr(self, "_refs_trabajo_en_curso", False):
            return
        trabajo = self._refs_trabajo or {}
        estado = trabajo.get("estado")

        if estado == "pendiente":
            QtCore.QTimer.singleShot(
                _COMENTARIOS_POLL_MS, self._poll_refs
            )
            return

        self._refs_trabajo_en_curso = False
        try:
            self._aplicar_import_refs(trabajo)
        except Exception as e:
            self._estado("Error al importar referencias: %s" % e, error=True)

    def _aplicar_import_refs(self, trabajo):
        """Publica el import en `_etiqueta_estado` y crea los nodos Read.

        Corre SIEMPRE en el hilo principal (QTimer). Por cada referencia
        descargada crea un Read con ruta RELATIVA al comp guardado
        ("ref/<filename>"); un fallo de un nodo no corta el resto. Sin
        imágenes: mensaje informativo (no error). Nunca lanza.
        """
        if not trabajo:
            return
        estado = trabajo.get("estado")
        if estado != "ok":
            self._estado(
                trabajo.get("mensaje") or "Error al importar referencias.",
                error=True,
            )
            return

        if trabajo.get("sin_refs"):
            self._estado(trabajo.get("mensaje") or _MENSAJE_SIN_REFS)
            return

        descargados = trabajo.get("descargados") or []
        fallidos = trabajo.get("fallidos") or []
        comp = nuke.root().name() or ""
        for _url, _ruta_local, nombre in descargados:
            try:
                nodo = nuke.createNode("Read")
                # Convención del estudio: [python {PYTHON_COMP}]/EP_x/{carpeta}/ref/{fname}.
                nodo["file"].setValue(_ruta_read_ref(comp, nombre))
            except Exception:
                pass  # un nodo que falla no corta el resto
        directorio = trabajo.get("directorio") or ""
        cantidad = len(descargados)
        unidad = "referencia" if cantidad == 1 else "referencias"
        verbo = "importada" if cantidad == 1 else "importadas"
        resumen = "{0} {1} {2} a {3}".format(cantidad, unidad, verbo, directorio)
        if fallidos:
            resumen += " ({0} no se pudieron descargar)".format(len(fallidos))
        self._estado(resumen)

    # ------------------------------------------------------------ utilidad

    def _estado(self, texto, error=False):
        self._etiqueta_estado.setStyleSheet(
            "color: {0};".format(_COLOR_ERROR) if error else ""
        )
        self._etiqueta_estado.setText(texto)


# Instancia del panel mientras este abierto en esta sesion de Nuke
# (evita registrar duplicados y re-crear el widget al reutilizar).
_PANEL = None

# String EVALUABLE de la clase (API nukescripts.panels: registerWidgetAsPanel
# concatena 'WidgetKnob(' + widget + ')'; la clase NO se puede pasar directa).
_WIDGET_STRING = (
    "__import__('SamanTools.panel_comentarios', fromlist=['PanelComentarios'])"
    ".PanelComentarios"
)


def abrir_panel():
    """Registra (si hace falta) y acopla el panel docked al pane actual.

    API real de nukescripts.panels (verificado contra Nuke 17.1): NO existe
    panels() ni getPanel(); se registra con registerWidgetAsPanel(widget,
    name, id, create=True) que devuelve el PythonPanel, y se muestra con
    addToPane(). El widget se pasa como STRING evaluable de la clase.

    Si `nukescripts` no existe (pytest) o algo falla, no rompe: solo avisa
    cuando Nuke esta en modo GUI.
    """
    global _PANEL
    try:
        import nukescripts.panels as p

        if _PANEL is None:
            _PANEL = p.registerWidgetAsPanel(
                _WIDGET_STRING, _NOMBRE_PANEL, _ID_PANEL, create=True
            )
        _PANEL.addToPane()
    except Exception:
        try:
            if getattr(nuke, "GUI", False):
                nuke.message(
                    "No se pudo abrir el panel "
                    "(¿estás en Nuke con interfaz?)."
                )
        except Exception:
            pass