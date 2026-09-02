"""
SamanTools.panel_rutas - Panel docked GLOBAL de rutas VFX.

Reemplaza (a futuro) el nodo Rutas legacy. Guarda la config en
~/.config/saman/rutas_global.json y aplica PYTHON_* al arrancar y al
cambiar valores. El nodo legacy sigue funcionando por compatibilidad
(coexistencia); este panel es la fuente de verdad nueva.

Patron de registro identico a panel_comentarios: registerWidgetAsPanel
(nukescripts.panels) + addToPane. La UI se construye con PySide2/PySide6.
"""

import os

import nuke

try:
    from PySide2 import QtCore, QtGui, QtWidgets
    QtAlignment = QtCore.Qt
except ImportError:
    from PySide6 import QtCore, QtGui, QtWidgets
    QtAlignment = QtCore.Qt.AlignmentFlag

from SamanTools import entorno
from SamanTools import rutas_global

_ID_PANEL = "pe.saman.rutas.global"
_NOMBRE_PANEL = "Rutas Globales — SamanTools"

# (usuario, titulo_grupo, (clave_TO_VFX, clave_COMP, clave_FROM_VFX))
_GRUPOS = (
    ("MacServer", "Ruta MacServer",
     ("TO_VFX_SERVER_MAC", "comp_SERVER_MAC", "FROM_VFX_SERVER_MAC")),
    ("Windows", "Ruta Windows",
     ("TO_VFX_SERVER_WINDOWS", "comp_SERVER_WINDOWS", "FROM_VFX_SERVER_WINDOWS")),
    ("Artist", "Ruta Artist",
     ("TO_VFX_SERVER_ARTIST", "comp_SERVER_ARTIST", "FROM_VFX_SERVER_ARTIST")),
)

_ETIQUETAS_CLAVE = {
    "TO_VFX_SERVER_MAC": "TO_VFX", "comp_SERVER_MAC": "COMP", "FROM_VFX_SERVER_MAC": "FROM_VFX",
    "TO_VFX_SERVER_WINDOWS": "TO_VFX", "comp_SERVER_WINDOWS": "COMP", "FROM_VFX_SERVER_WINDOWS": "FROM_VFX",
    "TO_VFX_SERVER_ARTIST": "TO_VFX", "comp_SERVER_ARTIST": "COMP", "FROM_VFX_SERVER_ARTIST": "FROM_VFX",
}

_PANEL = None


def _estado_unidad_texto():
    """Estado de la unidad (SO detectado + primera ruta base disponible)."""
    try:
        so = entorno.detectar_so()
        ruta_base = entorno.primera_ruta_disponible(so)
        estado = entorno.estado_unidad(ruta_base)
        texto = "Conectado" if estado.get("conectado") else "Desconectado"
        detalle = estado.get("detalle") or ""
        return so, (texto + " - " + detalle) if detalle else texto
    except Exception:
        return "?", "—"


class PanelRutasGlobales(QtWidgets.QWidget):
    """Formulario de config global: usuario, proyecto, 9 rutas y acciones."""

    def __init__(self, parent=None):
        super(PanelRutasGlobales, self).__init__(parent)
        self.cfg = rutas_global.cargar_config()
        self.campos_rutas = {}
        self.grupos_widgets = {}
        self._construir_ui()
        self._cargar_en_ui()
        self._on_usuario_cambio(self.combo_usuario.currentText())
        self._refrescar_estado()

    # ---- UI ----
    def _construir_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(10, 10, 10, 10)

        fila_usuario = QtWidgets.QHBoxLayout()
        fila_usuario.addWidget(QtWidgets.QLabel("Usuario Activo:"))
        self.combo_usuario = QtWidgets.QComboBox()
        self.combo_usuario.addItems([g[0] for g in _GRUPOS])
        fila_usuario.addWidget(self.combo_usuario, 1)
        layout.addLayout(fila_usuario)

        fila_proyecto = QtWidgets.QHBoxLayout()
        fila_proyecto.addWidget(QtWidgets.QLabel("Proyecto:"))
        self.campo_proyecto = QtWidgets.QLineEdit()
        fila_proyecto.addWidget(self.campo_proyecto, 1)
        self.boton_cambiar_proy = QtWidgets.QPushButton("Cambiar Proyecto")
        fila_proyecto.addWidget(self.boton_cambiar_proy)
        layout.addLayout(fila_proyecto)

        for usuario, titulo, claves in _GRUPOS:
            caja = QtWidgets.QGroupBox(titulo)
            grid = QtWidgets.QGridLayout(caja)
            for i, clave in enumerate(claves):
                grid.addWidget(QtWidgets.QLabel(_ETIQUETAS_CLAVE[clave]), i, 0)
                campo = QtWidgets.QLineEdit()
                self.campos_rutas[clave] = campo
                grid.addWidget(campo, i, 1)
            layout.addWidget(caja)
            self.grupos_widgets[usuario] = caja

        fila_botones = QtWidgets.QHBoxLayout()
        self.boton_aplicar = QtWidgets.QPushButton("Aplicar Proyecto")
        self.boton_refrescar = QtWidgets.QPushButton("Refrescar Fuentes")
        self.boton_importar = QtWidgets.QPushButton("Importar desde nodo")
        fila_botones.addWidget(self.boton_aplicar)
        fila_botones.addWidget(self.boton_refrescar)
        fila_botones.addWidget(self.boton_importar)
        layout.addLayout(fila_botones)

        self.label_estado = QtWidgets.QLabel("")
        self.label_estado.setWordWrap(True)
        layout.addWidget(self.label_estado)
        layout.addStretch(1)

        self.combo_usuario.currentTextChanged.connect(self._on_usuario_cambio)
        self.boton_aplicar.clicked.connect(self.aplicar)
        self.boton_refrescar.clicked.connect(self.refrescar_fuentes)
        self.boton_cambiar_proy.clicked.connect(self.cambiar_proyecto)
        self.boton_importar.clicked.connect(self.importar_desde_nodo)

    # ---- Estado <-> UI ----
    def _cargar_en_ui(self):
        """Llena los campos desde self.cfg (sin disparar cambios)."""
        usuario = self.cfg.get("usuario_activo") or ""
        if usuario in [g[0] for g in _GRUPOS]:
            self.combo_usuario.setCurrentText(usuario)
        self.campo_proyecto.setText(self.cfg.get("proyecto") or "")
        rutas_cfg = self.cfg.get("rutas") or {}
        for clave, campo in self.campos_rutas.items():
            campo.setText(str(rutas_cfg.get(clave) or ""))

    def _tomar_de_ui(self):
        """Arma el config desde los campos del formulario."""
        cfg = rutas_global.config_vacia()
        cfg["usuario_activo"] = self.combo_usuario.currentText()
        cfg["proyecto"] = self.campo_proyecto.text().strip()
        for clave, campo in self.campos_rutas.items():
            cfg["rutas"][clave] = campo.text().strip()
        return cfg

    def _on_usuario_cambio(self, usuario):
        """Muestra solo el grupo de rutas del usuario activo (igual que el nodo)."""
        for nombre, caja in self.grupos_widgets.items():
            caja.setVisible(nombre == usuario)

    def _refrescar_estado(self):
        so, texto = _estado_unidad_texto()
        plano = ""
        try:
            ruta = nuke.root().name()
            if ruta:
                from SamanTools import nombres
                datos = nombres.parsear_plato(ruta) or {}
                plano = " | Plano: {0}".format(datos.get("plano") or "")
        except Exception:
            pass
        self.label_estado.setText(
            "SO: {0} | Unidad: {1}{2}".format(so, texto, plano)
        )

    # ---- Acciones ----
    def aplicar(self):
        """Guarda la config y aplica PYTHON_* (recarga Reads que cambiaron)."""
        self.cfg = self._tomar_de_ui()
        if not rutas_global.guardar_config(self.cfg):
            nuke.message("No se pudo guardar la config de rutas globales.")
            return
        ok = rutas_global.aplicar_global(self.cfg)
        self._refrescar_estado()
        nuke.message(
            "Config global de rutas aplicada.\n\n"
            "PYTHON_TO_VFX / PYTHON_COMP / PYTHON_FROM_VFX actualizadas."
            if ok else
            "Config guardada, pero el usuario activo no es válido o no se "
            "pudieron cargar los scripts del proyecto."
        )

    def refrescar_fuentes(self):
        """Recarga TODOS los Reads dinamicos (forzar=True)."""
        self.cfg = self._tomar_de_ui()
        rutas_global.guardar_config(self.cfg)
        recargados = rutas_global.aplicar_global(self.cfg, forzar=True)
        if recargados:
            nuke.message("Se recargaron %d fuente(s)." % recargados)
        else:
            nuke.message(
                "No se encontraron Reads con rutas dinámicas [python ...] para recargar."
            )

    def cambiar_proyecto(self):
        """Reescribe el segmento de proyecto en las 9 rutas y aplica."""
        proy = self.campo_proyecto.text().strip()
        if not proy:
            nuke.message("Por favor, ingrese un código o nombre de proyecto válido.")
            return
        cfg, cambios = rutas_global.cambiar_proyecto_global(self._tomar_de_ui(), proy)
        self.cfg = cfg
        rutas_global.guardar_config(cfg)
        self._cargar_en_ui()
        self.aplicar()
        nuke.message(
            "Se actualizaron %d rutas al proyecto: \"%s\".\n"
            "Usá 'Refrescar Fuentes' para recargar los Reads." % (cambios, proy)
        )

    def importar_desde_nodo(self):
        """Importa los valores de un nodo Rutas legacy al panel (migracion)."""
        from SamanTools import rutas
        nodos = rutas.encontrar_nodos_rutas()
        if not nodos:
            nuke.message("No hay nodos Rutas en este comp para importar.")
            return
        nodo = nodos[0]
        self.cfg = rutas_global.importar_desde_nodo(self.cfg, nodo)
        self._cargar_en_ui()
        self._on_usuario_cambio(self.cfg.get("usuario_activo") or "")
        nuke.message(
            "Config importada desde el nodo Rutas '%s'.\n"
            "Revisala y pulsá 'Aplicar Proyecto'." % (nodo.name() if hasattr(nodo, "name") else nodo)
        )


def abrir_panel():
    """Registra (si hace falta) y acopla el panel docked al pane actual.

    Mismo patron que panel_comentarios.abrir_panel: registerWidgetAsPanel
    con el widget como STRING evaluable + addToPane(). Nunca lanza hacia
    arriba; en modo no-GUI solo avisa.
    """
    global _PANEL
    _WIDGET_STRING = (
        "from SamanTools.panel_rutas import PanelRutasGlobales\n"
        "PanelRutasGlobales()"
    )
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