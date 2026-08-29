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

import html
import os
import re
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timezone

import nuke

try:
    from PySide2 import QtCore, QtWidgets
    # PySide2: los enums cuelgan directo de Qt (Qt.AlignCenter, Qt.Checked).
    QtAlignment = QtCore.Qt
except ImportError:
    from PySide6 import QtCore, QtWidgets
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

# Paleta oscura acorde a Nuke (fondo gris oscuro, acento azul #1f8ecd).
# Se aplica SOLO a este widget (`self.setStyleSheet`), NUNCA global: no se
# tocan los skins de Nuke ni de otros paneles.
_ESTILO_PANEL = """
QWidget {
    background-color: #2b2b2b;
    color: #dcdcdc;
    font-size: 12px;
}
QLabel {
    background: transparent;
    color: #dcdcdc;
}
QLabel#autorActividad {
    font-weight: bold;
}
QLabel#avatarActividad {
    color: #1f8ecd;
    font-weight: bold;
}
QLabel#rolActividad,
QLabel#tiempoActividad,
QLabel#versionActividad {
    color: #9a9a9a;
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
    background-color: #333333;
    border: 1px solid #4a4a4a;
    border-radius: 6px;
    padding: 6px;
}
QLabel#chipEstado {
    background-color: #3e3e3e;
    border: 1px solid #5a5a5a;
    border-radius: 9px;
    padding: 2px 8px;
    color: #e8e8e8;
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


def _html_archivos(actividad):
    """HTML (seguro) del cuerpo de file_upload: una línea por attachment.

    Para `type=="image"` muestra "[imagen] <name>" (NO baja la imagen en
    v1.6.1, solo se muestra el link); para el resto "Adjuntó: <name>". Si hay
    `url`, queda clicable. Sin attachments usa `content`.
    """
    adjuntos = actividad.get("attachments")
    if not adjuntos:
        return _escapar_y_linkificar(actividad.get("content") or "")
    lineas = []
    for adj in adjuntos:
        if not isinstance(adj, dict):
            continue
        tipo = adj.get("type")
        nombre = (adj.get("name") or "").strip()
        url = adj.get("url") or ""
        if tipo == "image":
            texto = "[imagen] {0}".format(nombre) if nombre else "[imagen]"
        else:
            texto = "Adjuntó: {0}".format(nombre) if nombre else "Adjuntó un archivo"
        if url:
            texto = "{0}  {1}".format(texto, url)
        lineas.append(texto)
    return "<br/>".join(_escapar_y_linkificar(l) for l in lineas)


def _cuerpo_actividad(actividad):
    """Cuerpo de una card según el type (HTML seguro) + extras. Puro.

    Devuelve {"html", "chips", "versiones"}:
      - "html": línea(s) del cuerpo, HTML seguro con URLs enlazadas.
      - "chips": (previo, nuevo) o None; badges de estados (status/batch).
      - "versiones": "V<prev> → V<new>" o None (batch_update).

    El feed es de actividad completa: los 8 tipos de shotActivity se muestran
    como cards (comentarios, archivos, estados, versiones, tareas, asignación).
    """
    tipo = actividad.get("type")
    content = actividad.get("content")
    if tipo == "comment":
        return {"html": _escapar_y_linkificar(content), "chips": None, "versiones": None}
    if tipo == "reply":
        return {"html": _escapar_y_linkificar("↳ {0}".format(content or "")), "chips": None, "versiones": None}
    if tipo == "file_upload":
        return {"html": _html_archivos(actividad), "chips": None, "versiones": None}
    if tipo == "status_change":
        texto = content or _estado_cambiada(actividad)
        return {"html": _escapar_y_linkificar(texto), "chips": _chips_estados(actividad), "versiones": None}
    if tipo == "version_update":
        texto = content
        if not texto:
            prev = _formatear_version(actividad.get("previousVersion"))
            nuevo = _formatear_version(actividad.get("newVersion"))
            if prev and nuevo:
                texto = "Versión actualizada de {0} a {1}".format(prev, nuevo)
            else:
                texto = "Versión actualizada"
        return {"html": _escapar_y_linkificar(texto), "chips": None, "versiones": None}
    if tipo == "task_update":
        return {"html": _escapar_y_linkificar(_texto_tarea(actividad)), "chips": None, "versiones": None}
    if tipo == "batch_update":
        return {
            "html": _escapar_y_linkificar(content or ""),
            "chips": _chips_estados(actividad),
            "versiones": _versiones_diferentes(actividad),
        }
    if tipo == "assignment_change":
        return {"html": _escapar_y_linkificar(_texto_asignacion(actividad)), "chips": None, "versiones": None}
    return {"html": _escapar_y_linkificar(content or ""), "chips": None, "versiones": None}


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
        form_sesion = QtWidgets.QFormLayout(seccion_sesion)
        self._label_conectado = QtWidgets.QLabel("—", self)
        form_sesion.addRow("Conectado", self._label_conectado)
        self._boton_desconectar = QtWidgets.QPushButton(
            "Desconectar", self
        )
        self._boton_desconectar.clicked.connect(self._on_desconectar)
        form_sesion.addRow(self._boton_desconectar)
        layout.addWidget(seccion_sesion)
        self._seccion_sesion = seccion_sesion

        seccion_comentarios = QtWidgets.QGroupBox("Actividad por Plano", self)
        lay_comentarios = QtWidgets.QVBoxLayout(seccion_comentarios)

        # Header (v1.6.1): plano identificado + combo de estado deshabilitado.
        fila_header = QtWidgets.QHBoxLayout()
        self._header_plano = QtWidgets.QLabel("—", seccion_comentarios)
        self._header_plano.setStyleSheet("font-weight: bold;")
        fila_header.addWidget(self._header_plano)
        fila_header.addStretch(1)
        self._combo_estado = QtWidgets.QComboBox(seccion_comentarios)
        self._combo_estado.addItem("Estado")
        self._combo_estado.setEnabled(False)  # v1.6.2 lo activa (solo lectura ahora)
        fila_header.addWidget(self._combo_estado)
        lay_comentarios.addLayout(fila_header)

        # Input de comentario (v1.6.1 SOLO LECTURA: el envío es v1.6.2).
        fila_input = QtWidgets.QHBoxLayout()
        self._input_comentario = QtWidgets.QLineEdit(seccion_comentarios)
        self._input_comentario.setPlaceholderText("Escribe comentario.")
        self._input_comentario.setEnabled(False)
        fila_input.addWidget(self._input_comentario)
        self._boton_enviar = QtWidgets.QPushButton("➔", seccion_comentarios)
        self._boton_enviar.setEnabled(False)
        fila_input.addWidget(self._boton_enviar)
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
        self._scroll_actividad.setMinimumHeight(160)
        lay_comentarios.addWidget(self._scroll_actividad)

        self._label_mensaje_actividad = QtWidgets.QLabel(self._widget_contenido_actividad)
        self._label_mensaje_actividad.setWordWrap(True)
        layout.addWidget(seccion_comentarios)
        self._seccion_comentarios = seccion_comentarios

        self._etiqueta_estado = QtWidgets.QLabel(self)
        self._etiqueta_estado.setWordWrap(True)
        layout.addWidget(self._etiqueta_estado)
        layout.addStretch(1)

        # Estado inicial: sin sesión, se muestra el login (la sesión se oculta).
        self._aplicar_estado_sesion_ui()

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
        """Guarda la sesion en memoria y persiste refresh_token en disco."""
        sesion_previa = self.sesion or {}
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
                respuesta.get("local_id") or sesion_previa.get("local_id")
            ),
            "email": (
                email or respuesta.get("email") or sesion_previa.get("email")
            ),
            "expira_en": expira_en,
        }
        sesion_vfxflow.guardar_sesion(self.sesion)

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
            respuesta = vfxflow_auth.refrescar_id_token(
                guardada["refresh_token"]
            )
            self._registrar_sesion(respuesta, email=guardada.get("email"))
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
        """Worker daemon: resuelve el shot y lee la actividad de Firestore.

        Nunca toca widgets: publica el resultado en `_comentarios_trabajo`
        ("ok" con la lista, o "error" con mensaje/codigo). El QTimer
        (`_poll_comentarios`) es quien aplica a la UI. Los "no encontrado" de
        la resolucion son un error de datos (no de red): mensaje normalizado.
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
            self._comentarios_trabajo = {
                "estado": "ok",
                "comentarios": actividad,
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
            self._publicar_actividad(trabajo.get("comentarios") or [])
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

    def _crear_card_actividad(self, actividad):
        """Construye la QFrame de una actividad (header + cuerpo por tipo).

        Todo el look vive en `_ESTILO_PANEL` (selectores por objectName); el
        avatar es la INICIAL como texto plano "[E]" (sin reborde redondeado),
        como en el mock original.
        """
        card = QtWidgets.QFrame(self._widget_contenido_actividad)
        card.setObjectName("cardActividad")
        card.setFrameShape(QtWidgets.QFrame.NoFrame)
        lay_card = QtWidgets.QVBoxLayout(card)
        lay_card.setContentsMargins(8, 6, 8, 6)

        # Fila avatar (inicial) + autor + rol + tiempo relativo.
        fila_autor = QtWidgets.QHBoxLayout()
        avatar = QtWidgets.QLabel(
            "[{0}]".format(_inicial_avatar(actividad.get("userName"))), card
        )
        avatar.setObjectName("avatarActividad")
        fila_autor.addWidget(avatar)
        autor = QtWidgets.QLabel(actividad.get("userName") or "Anónimo", card)
        autor.setObjectName("autorActividad")
        fila_autor.addWidget(autor)
        rol = actividad.get("userRole") or ""
        if rol:
            label_rol = QtWidgets.QLabel("[{0}]".format(rol), card)
            label_rol.setObjectName("rolActividad")
            fila_autor.addWidget(label_rol)
        fila_autor.addStretch(1)
        tiempo = QtWidgets.QLabel(
            _tiempo_relativo(actividad.get("createdAt")), card
        )
        tiempo.setObjectName("tiempoActividad")
        fila_autor.addWidget(tiempo)
        lay_card.addLayout(fila_autor)

        # Cuerpo segun el tipo de actividad (puro y testeable).
        cuerpo = _cuerpo_actividad(actividad)
        if cuerpo["html"]:
            label_cuerpo = QtWidgets.QLabel(cuerpo["html"], card)
            label_cuerpo.setWordWrap(True)
            label_cuerpo.setTextFormat(QtCore.Qt.RichText)
            label_cuerpo.setOpenExternalLinks(True)
            lay_card.addWidget(label_cuerpo)
        if cuerpo["chips"] is not None:
            previo, nuevo = cuerpo["chips"]
            fila_estados = QtWidgets.QHBoxLayout()
            fila_estados.addWidget(self._chip_estado(previo, card))
            flecha = QtWidgets.QLabel("➔", card)
            fila_estados.addWidget(flecha, 0, QtAlignment.AlignCenter)
            fila_estados.addWidget(self._chip_estado(nuevo, card))
            fila_estados.addStretch(1)
            lay_card.addLayout(fila_estados)
        if cuerpo.get("versiones"):
            label_version = QtWidgets.QLabel(cuerpo["versiones"], card)
            label_version.setObjectName("versionActividad")
            lay_card.addWidget(label_version)
        return card

    def _chip_estado(self, texto, parent):
        """Label estilo chip para los badges de estados (nunca hardcodeados).

        El look (fondo/borde/texto) lo define el selector `QLabel#chipEstado`
        de `_ESTILO_PANEL`, no un color hardcodeado acá.
        """
        chip = QtWidgets.QLabel(str(texto), parent)
        chip.setObjectName("chipEstado")
        chip.setAlignment(QtAlignment.AlignCenter)
        return chip

    def _publicar_actividad(self, actividad):
        """Pinta las cards del feed (o el mensaje de vacio) en la UI."""
        if not actividad:
            self._mostrar_mensaje_actividad(_MENSAJE_SIN_ACTIVIDAD)
            self._estado(_MENSAJE_SIN_ACTIVIDAD)
            return
        self._limpiar_feed()
        for item in actividad:
            self._layout_actividad.addWidget(self._crear_card_actividad(item))
        self._layout_actividad.addStretch(1)
        cantidad = len(actividad)
        self._estado(
            "%d actividad%s."
            % (cantidad, "es" if cantidad != 1 else "")
        )

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
        for _url, _ruta_local, nombre in descargados:
            try:
                nodo = nuke.createNode("Read")
                nodo["file"].setValue("ref/" + nombre)
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