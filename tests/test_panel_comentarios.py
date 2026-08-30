"""
Tests de SamanTools.panel_comentarios: apertura del panel docked.

El bug historico: abrir_panel usaba p.panels() y p.getPanel(), que NO existen
en nukescripts.panels de Nuke 17.1 (el dict interno es __panels, privado).
Este test inyecta un stub con el API REAL (registerWidgetAsPanel +
addToPane solamente) y verifica que abrir_panel funcione con el.

El widget PySide se requiere para importar el modulo; si no hay PySide en el
runner se salta (no se testea la UI, solo la logica de apertura).
"""

import html
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import nuke


pytest.importorskip("PySide6")


class _PanelFake:
    """PythonPanel simulado: registra que se llamo addToPane."""

    def __init__(self, widget, name, panel_id):
        self.widget = widget
        self.name = name
        self.panel_id = panel_id
        self.acoplado = False

    def addToPane(self):
        self.acoplado = True
        return self


class _PanelsFake:
    """Modulo nukescripts.panels con SOLO el API real de Nuke 17.1.

    A proposito NO expone panels() ni getPanel(): si el codigo bajo prueba
    intentara usarlos, el test fallaria con AttributeError.
    """

    def __init__(self):
        self.registrados = []

    def registerWidgetAsPanel(self, widget, name, panel_id, create=False):
        self.registrados.append((widget, name, panel_id, create))
        return _PanelFake(widget, name, panel_id)


@pytest.fixture
def nukescripts_panels_fake(monkeypatch):
    import types

    modulo = types.ModuleType("nukescripts.panels")
    fake = _PanelsFake()
    modulo.panels = fake  # nombre del atributo de este stub interno
    # registra el API real como atributos del modulo
    modulo.registerWidgetAsPanel = fake.registerWidgetAsPanel
    data = types.ModuleType("nukescripts")
    data.panels = modulo
    monkeypatch.setitem(sys.modules, "nukescripts", data)
    monkeypatch.setitem(sys.modules, "nukescripts.panels", modulo)
    return fake


@pytest.fixture
def panel_reset():
    from SamanTools import panel_comentarios

    panel_comentarios._PANEL = None
    yield panel_comentarios


def test_abrir_panel_registra_y_acopla(nukescripts_panels_fake, panel_reset):
    panel_reset.abrir_panel()
    # registrado UNA vez con el string evaluable, no con la clase directa
    assert len(nukescripts_panels_fake.registrados) == 1
    widget, nombre, panel_id, create = nukescripts_panels_fake.registrados[0]
    assert isinstance(widget, str)
    assert "PanelComentarios" in widget
    assert nombre == "Comentarios por Plano — SamanTools"
    assert panel_id == "pe.saman.vfxflow.comentarios"
    assert create is True
    # el panel devuelto se acoplo
    assert panel_reset._PANEL is not None
    assert panel_reset._PANEL.acoplado is True


def test_abrir_panel_reutiliza_sin_re_registrar(
    nukescripts_panels_fake, panel_reset
):
    panel_reset.abrir_panel()
    panel_reset.abrir_panel()
    assert len(nukescripts_panels_fake.registrados) == 1  # solo la primera


def test_abrir_panel_sin_nukescripts_no_rompe(panel_reset, monkeypatch):
    monkeypatch.delitem(sys.modules, "nukescripts", raising=False)
    monkeypatch.delitem(sys.modules, "nukescripts.panels", raising=False)
    # en modo no-GUI no debe lanzar
    try:
        panel_reset.abrir_panel()
    except Exception as e:  # pragma: no cover - el contrato es no lanzar
        raise AssertionError("abrir_panel lanzo sin nukescripts: %r" % e)


def test_mensaje_error_login_google_firewall():
    """El fallo de red del canje loopback se explica, el resto se pasa tal cual.

    Se instancia con `__new__` (sin __init__) para no levantar un QApplication
    en el runner: `_mensaje_error_login_google` no depende de widgets.
    """
    from SamanTools import panel_comentarios

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    mensaje_firewall = panel._mensaje_error_login_google("x", "red")
    assert "firewall" in mensaje_firewall
    assert "googleapis.com" in mensaje_firewall
    assert panel._mensaje_error_login_google("x", "http") == "x"


def test_autologin_no_refresca_sin_config_disco(monkeypatch):
    """Sin .saman/vfxflow_config.json el panel NO autologinea.

    El gate de acceso: si la unidad wupm no esta (o falta el archivo), no se
    reutiliza la sesion guardada ni se llama a refrescar_id_token.
    """
    from SamanTools import panel_comentarios, sesion_vfxflow, vfxflow_config

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    panel._estado = lambda texto, error=False: None

    monkeypatch.setattr(
        vfxflow_config, "config_disco_disponible", lambda: False
    )
    monkeypatch.setattr(sesion_vfxflow, "cargar_sesion", lambda: {"refresh_token": "RT"})
    refrescado = []

    def _no_debe_llamarse(*a, **k):
        refrescado.append(a)

    monkeypatch.setattr(
        panel_comentarios.vfxflow_auth, "refrescar_id_token", _no_debe_llamarse
    )

    panel._autologin_si_hay_sesion()

    assert refrescado == []  # nunca refresco sin config de disco


def test_autologin_refresca_con_config_disco(monkeypatch):
    """Con config de disco disponible, el autologin normal sigue funcionando.

    Se simula que config_disco_disponible() -> True y que refrescar_id_token
    devuelve tokens; la sesion se registra y el panel muestra 'Reconectado'.
    """
    from SamanTools import panel_comentarios, sesion_vfxflow, vfxflow_config

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    estados = []
    panel._estado = lambda texto, error=False: estados.append(texto)
    panel._registrar_sesion = lambda respuesta, email=None: None

    monkeypatch.setattr(
        vfxflow_config, "config_disco_disponible", lambda: True
    )
    monkeypatch.setattr(
        sesion_vfxflow,
        "cargar_sesion",
        lambda: {"refresh_token": "RT", "email": "a@b.com"},
    )
    monkeypatch.setattr(
        panel_comentarios.vfxflow_auth,
        "refrescar_id_token",
        lambda refresh_token: {
            "id_token": "ID",
            "refresh_token": "RT2",
            "expires_in": 3600,
            "user_id": "uid",
        },
    )

    panel._autologin_si_hay_sesion()

    assert any("Reconectado como" in e for e in estados)


# ---------------------------------------------------------------------------
# Sesión visible: con sesión activa el login se oculta y queda el botón
# "Desconectar"; sin sesión vuelve el login. Se testea con fakes porque no se
# levanta un QApplication en el runner.
# ---------------------------------------------------------------------------


class _WidgetFake:
    """QWidget minimal: registra setVisible y el último texto seteado."""

    def __init__(self):
        self.visible = True
        self.texto = ""

    def setVisible(self, valor):
        self.visible = valor

    def setText(self, texto):
        self.texto = texto

    def setParent(self, parent):
        pass

    def setFocus(self):
        pass


def _panel_con_ui_falsa():
    """PanelComentarios con secciones del login/sesión simuladas."""
    from SamanTools import panel_comentarios

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    panel._seccion_login = _WidgetFake()
    panel._seccion_sesion = _WidgetFake()
    panel._label_conectado = _WidgetFake()
    return panel


def test_estado_sesion_sin_sesion_muestra_login():
    panel = _panel_con_ui_falsa()
    panel.sesion = None
    panel._aplicar_estado_sesion_ui()
    assert panel._seccion_login.visible is True
    assert panel._seccion_sesion.visible is False


def test_estado_sesion_conectado_muestra_sesion_y_email():
    panel = _panel_con_ui_falsa()
    panel.sesion = {"email": "artista@samanestudio.com", "id_token": "ID"}
    panel._aplicar_estado_sesion_ui()
    assert panel._seccion_login.visible is False
    assert panel._seccion_sesion.visible is True
    assert panel._label_conectado.texto == "artista@samanestudio.com"


def test_desconectar_vuelve_al_login(monkeypatch):
    """Desconectar borra la sesión persistida y muestra el login de nuevo."""
    from SamanTools import panel_comentarios, sesion_vfxflow

    panel = _panel_con_ui_falsa()
    panel.sesion = {"email": "a@b.com", "id_token": "ID"}
    estados = []
    panel._estado = lambda texto, error=False: estados.append(texto)

    borrados = []
    monkeypatch.setattr(sesion_vfxflow, "borrar_sesion", lambda: borrados.append(1))

    panel._on_desconectar()

    assert borrados == [1]          # se limpió la sesión persistida
    assert panel.sesion is None
    assert panel._seccion_login.visible is True
    assert panel._seccion_sesion.visible is False
    assert "Sesión cerrada." in estados


# ---------------------------------------------------------------------------
# Actividad del plano (solo lectura): cards puras + flujo del fetch
# ---------------------------------------------------------------------------


class _LabelFake(_WidgetFake):
    """QLabel mínimo: además del texto registra el stylesheet seteado."""

    def __init__(self):
        super().__init__()
        self.style = ""

    def setWordWrap(self, valor):
        pass

    def setStyleSheet(self, s):
        self.style = s


class _ItemFake:
    """Item de layout simulado: devuelve el widget que envuelve."""

    def __init__(self, widget):
        self._widget = widget

    def widget(self):
        return self._widget


class _LayoutFake:
    """QVBoxLayout del feed simulado: registra widgets agregados por orden."""

    def __init__(self):
        self.items = []

    def count(self):
        return len(self.items)

    def takeAt(self, indice):
        return _ItemFake(self.items.pop(indice))

    def addWidget(self, widget):
        self.items.append(widget)

    def addStretch(self, n):
        self.items.append("stretch")


def _panel_con_feed_falsa():
    """PanelComentarios con el feed de actividad simulado (sin QApplication).

    `_crear_card_actividad` se reemplaza por la identidad para que el flujo
    no construya QFrame reales; el layout fake registra qué cards se pintan.
    `_limpiar_feed` se reemplaza para no llamar setParent sobre dicts.
    """
    from SamanTools import panel_comentarios

    p = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    layout = _LayoutFake()

    def _limpiar():
        layout.items = []

    p._layout_actividad = layout
    p._label_mensaje_actividad = _LabelFake()
    p._comentarios_trabajo_en_curso = False
    p._comentarios_trabajo = None
    p._crear_card_actividad = (
        lambda actividad, colores_estados=None, imagenes=None, es_respuesta=False: actividad
    )
    p._limpiar_feed = _limpiar
    return p


class _ThreadFake:
    """Reemplaza `threading.Thread`: `start()` corre el target sincrónico."""

    def __init__(self, target, args=(), daemon=None):
        self._target = target
        self._args = args

    def start(self):
        self._target(*self._args)


class _LineEditFake:
    """QLineEdit mínimo para probar el flujo de escritura sin QApplication."""

    def __init__(self, texto=""):
        self._texto = texto
        self.placeholder = ""
        self.habilitado = False
        self.tooltip = ""

    def text(self):
        return self._texto

    def setText(self, texto):
        self._texto = texto

    def clear(self):
        self._texto = ""

    def setPlaceholderText(self, texto):
        self.placeholder = texto

    def setFocus(self):
        pass

    def setEnabled(self, habilitado):
        self.habilitado = habilitado

    def setToolTip(self, tooltip):
        self.tooltip = tooltip


class _BotonSelectorFake:
    """QToolButton del selector de estado: registra texto/habilitación/tooltip."""

    def __init__(self):
        self.texto = ""
        self.habilitado = False
        self.tooltip = ""
        self.menu = None
        self.icono = None
        self.style = ""

    def setText(self, texto):
        self.texto = texto

    def setEnabled(self, habilitado):
        self.habilitado = habilitado

    def setToolTip(self, tooltip):
        self.tooltip = tooltip

    def setIcon(self, icono):
        self.icono = icono

    def setStyleSheet(self, estilo):
        self.style = estilo or ""

    def setTextFormat(self, formato):
        pass

    def setPopupMode(self, modo):
        pass

    def setMenu(self, menu):
        self.menu = menu


class _BotonAccionFake:
    """QPushButton de Save/Undo: registra habilitación/visibilidad/tooltip."""

    def __init__(self):
        self.habilitado = False
        self.visible = True
        self.texto = ""
        self.tooltip = ""

    def setEnabled(self, habilitado):
        self.habilitado = habilitado

    def setVisible(self, visible):
        self.visible = visible

    def setText(self, texto):
        self.texto = texto

    def setToolTip(self, tooltip):
        self.tooltip = tooltip


def _panel_con_selector():
    """Panel __new__ con el selector completo + plano/sesión mínimos."""
    from SamanTools import panel_comentarios

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    panel.sesion = {"email": "a@b.com", "id_token": "ID"}
    panel._plano_activo = lambda: {
        "proyecto": "HTLR",
        "capitulo": 107,
        "plano": "008_00100",
    }
    panel._boton_estado_anterior = _BotonSelectorFake()
    panel._boton_estado_actual = _BotonSelectorFake()
    panel._boton_estado_siguiente = _BotonSelectorFake()
    panel._boton_guardar_estado = _BotonAccionFake()
    panel._boton_cancelar_estado = _BotonAccionFake()
    panel._estado_pendiente_id = None
    panel._estados_combo = {}
    panel._estados_ordenados = []
    panel._estado_actual_id = ""
    panel._escritura_trabajo_en_curso = False
    return panel


def test_escapar_y_linkificar_escapa_html_y_enlaza_urls():
    from SamanTools import panel_comentarios

    salida = panel_comentarios._escapar_y_linkificar(
        'mirá http://ejemplo.com/x?a=1&b=2 y <script>alert(1)</script>'
    )
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in salida
    assert '<a href="http://ejemplo.com/x?a=1&amp;b=2">http://ejemplo.com/x?a=1&amp;b=2</a>' in salida


def test_tiempo_relativo_bandas_espanol():
    from datetime import timedelta
    from SamanTools import panel_comentarios

    ahora = datetime.now(timezone.utc)

    def iso(segundos):
        return (ahora - timedelta(seconds=segundos)).isoformat().replace("+00:00", "Z")

    assert panel_comentarios._tiempo_relativo(iso(0)) == "ahora"
    assert panel_comentarios._tiempo_relativo(iso(59)) == "ahora"
    assert panel_comentarios._tiempo_relativo(iso(61)) == "hace 1m"
    assert panel_comentarios._tiempo_relativo(iso(90)) == "hace 1m"
    assert panel_comentarios._tiempo_relativo(iso(3600)) == "hace 1h"
    assert panel_comentarios._tiempo_relativo(iso(3600 * 25)) == "hace 1d"
    assert panel_comentarios._tiempo_relativo(iso(2 * 86400)) == "hace 2d"
    assert panel_comentarios._tiempo_relativo(iso(30 * 86400)) == "hace 1 mes"
    assert panel_comentarios._tiempo_relativo(iso(61 * 86400)) == "hace 2 meses"
    assert panel_comentarios._tiempo_relativo(iso(365 * 86400)) == "hace 1a"


def test_tiempo_relativo_fallback_recorta_string():
    from SamanTools import panel_comentarios

    assert panel_comentarios._tiempo_relativo(None) == ""
    assert panel_comentarios._tiempo_relativo("") == ""
    assert panel_comentarios._tiempo_relativo("no es fecha") == "no es fecha"
    largo = "2026-08-20T10:00:00 + algo invalido"
    assert panel_comentarios._tiempo_relativo(largo) == largo[:19]


def test_inicial_avatar():
    from SamanTools import panel_comentarios

    assert panel_comentarios._inicial_avatar("Emanuel Barriga") == "E"
    assert panel_comentarios._inicial_avatar("ana") == "A"
    assert panel_comentarios._inicial_avatar("") == "?"
    assert panel_comentarios._inicial_avatar(None) == "?"


def test_resumen_asignados():
    from SamanTools import panel_comentarios

    assert panel_comentarios._resumen_asignados(None) == "—"
    assert panel_comentarios._resumen_asignados({}) == "—"
    assert (
        panel_comentarios._resumen_asignados({"primaryName": "Emanuel Barriga"})
        == "Emanuel B."
    )
    assert (
        panel_comentarios._resumen_asignados(
            {"primaryName": "Emanuel Barriga", "secondaryNames": ["Luis", "Carmen"]}
        )
        == "Emanuel B. (+2)"
    )
    assert (
        panel_comentarios._resumen_asignados({"secondaryNames": ["a"]}) == "(+1)"
    )


def test_cuerpo_actividad_comment_enlaza_urls():
    from SamanTools import panel_comentarios

    r = panel_comentarios._cuerpo_actividad(
        {"type": "comment", "content": "Buen plano https://x.example/v.png"}
    )
    assert r["chips"] is None and r["versiones"] is None
    assert "Buen plano" in r["html"]
    assert 'href="https://x.example/v.png"' in r["html"]


def test_cuerpo_actividad_reply_con_prefijo():
    from SamanTools import panel_comentarios

    r = panel_comentarios._cuerpo_actividad(
        {"type": "reply", "content": "Gracias"}
    )
    assert r["html"].startswith("↳ ")
    assert "Gracias" in r["html"]


def test_cuerpo_actividad_status_change():
    from SamanTools import panel_comentarios

    with_content = panel_comentarios._cuerpo_actividad(
        {
            "type": "status_change",
            "content": "Estado cambiado",
            "previousStateName": "APROBADO",
            "newStateName": "ENTREGA",
        }
    )
    assert with_content["html"] == "Estado cambiado"
    # Los chips NO hardcodean estados: salen de previous/newStateName.
    assert with_content["chips"] == ("APROBADO", "ENTREGA")

    sin_content = panel_comentarios._cuerpo_actividad(
        {
            "type": "status_change",
            "previousStateName": "QC INTERNO",
            "newStateName": "QC CLIENTE",
        }
    )
    sintesis = html.escape("Estado cambiado de 'QC INTERNO' a 'QC CLIENTE'")
    assert sintesis in sin_content["html"]
    assert sin_content["chips"] == ("QC INTERNO", "QC CLIENTE")


def test_formatear_version():
    from SamanTools import panel_comentarios

    assert panel_comentarios._formatear_version(2) == "V2"
    assert panel_comentarios._formatear_version("V2") == "V2"
    assert panel_comentarios._formatear_version("v3") == "V3"
    assert panel_comentarios._formatear_version(None) is None
    assert panel_comentarios._formatear_version("") is None


def test_cuerpo_actividad_version_update():
    from SamanTools import panel_comentarios

    r = panel_comentarios._cuerpo_actividad(
        {"type": "version_update", "previousVersion": 1, "newVersion": 2}
    )
    assert "de V1 a V2" in r["html"]
    assert r["chips"] is None


def test_cuerpo_actividad_task_update():
    from SamanTools import panel_comentarios

    done = panel_comentarios._cuerpo_actividad(
        {"type": "task_update", "taskName": "Roto", "completed": True}
    )
    assert done["html"] == html.escape("Tarea 'Roto' completada")
    pendiente = panel_comentarios._cuerpo_actividad(
        {"type": "task_update", "taskName": "Roto", "completed": False}
    )
    assert pendiente["html"] == html.escape("Tarea 'Roto' pendiente")
    # Firestore a veces llega como string; se interpreta igual.
    como_string = panel_comentarios._cuerpo_actividad(
        {"type": "task_update", "taskName": "Roto", "completed": "true"}
    )
    assert como_string["html"] == html.escape("Tarea 'Roto' completada")


def test_cuerpo_actividad_batch_update():
    from SamanTools import panel_comentarios

    r = panel_comentarios._cuerpo_actividad(
        {
            "type": "batch_update",
            "content": "Task completada",
            "previousStateName": "A",
            "newStateName": "B",
            "previousVersion": 1,
            "newVersion": 2,
        }
    )
    assert "Task completada" in r["html"]
    assert r["chips"] == ("A", "B")
    assert r["versiones"] == "V1 → V2"

    iguales = panel_comentarios._cuerpo_actividad(
        {"type": "batch_update", "previousVersion": 1, "newVersion": 1}
    )
    assert iguales["versiones"] is None


def test_cuerpo_actividad_assignment_change():
    from SamanTools import panel_comentarios

    r = panel_comentarios._cuerpo_actividad(
        {
            "type": "assignment_change",
            "previousAssignees": {"primaryName": "Emanuel Barriga"},
            "newAssignees": {
                "primaryName": "Emanuel Barriga",
                "secondaryNames": ["Luis M", "Carmen"],
            },
        }
    )
    assert "Asignación cambiada: Emanuel B. → Emanuel B. (+2)" in r["html"]
    sin_datos = panel_comentarios._cuerpo_actividad({"type": "assignment_change"})
    assert "Asignación cambiada: — → —" in sin_datos["html"]


def test_html_archivos_imagen_muestra_etiqueta_y_link():
    from SamanTools import panel_comentarios

    html = panel_comentarios._html_archivos(
        {
            "type": "file_upload",
            "attachments": [
                {
                    "id": "a1",
                    "type": "image",
                    "name": "a.png",
                    "url": "https://cdn.example/a.png",
                }
            ],
        }
    )
    assert "[imagen] a.png" in html
    assert 'href="https://cdn.example/a.png"' in html  # la imagen NO se descarga


def test_html_archivos_sin_attachments_usa_content():
    from SamanTools import panel_comentarios

    assert (
        panel_comentarios._html_archivos(
            {"type": "file_upload", "content": "preview.mov"}
        )
        == "preview.mov"
    )


def test_cargar_comentarios_sin_plano_no_hace_query(monkeypatch):
    from SamanTools import panel_comentarios

    monkeypatch.setitem(nuke._estado, "root_name", "/tmp/foo.nk")
    panel = _panel_con_feed_falsa()
    estados = []
    panel._estado = lambda texto, error=False: estados.append(texto)
    lanzados = []
    monkeypatch.setattr(
        panel_comentarios.vfxflow_datos,
        "resolver_plano",
        lambda *a, **k: lanzados.append(1) or {},
    )

    panel._cargar_comentarios_del_plano()

    assert lanzados == []  # nunca se resuelve sin plano identificado
    assert (
        panel_comentarios._MENSAJE_PLANO_NO_IDENTIFICADO
        in panel._label_mensaje_actividad.texto
    )
    assert panel._comentarios_trabajo_en_curso is False


def test_cargar_comentarios_sin_sesion_no_hace_query(monkeypatch):
    from SamanTools import panel_comentarios

    monkeypatch.setitem(nuke._estado, "root_name", "HTLR_107_008_00100_V01.mov")
    panel = _panel_con_feed_falsa()
    panel._id_token_actual = lambda: None
    estados = []
    panel._estado = lambda texto, error=False: estados.append(texto)
    lanzados = []
    monkeypatch.setattr(
        panel_comentarios.vfxflow_datos,
        "resolver_plano",
        lambda *a, **k: lanzados.append(1) or {},
    )

    panel._cargar_comentarios_del_plano()

    assert lanzados == []
    assert panel_comentarios._MENSAJE_SIN_SESION in panel._label_mensaje_actividad.texto
    assert panel._comentarios_trabajo_en_curso is False


def test_cargar_comentarios_con_sesion_publica_cards(monkeypatch):
    from SamanTools import panel_comentarios

    monkeypatch.setitem(nuke._estado, "root_name", "HTLR_107_008_00100_V01.mov")
    panel = _panel_con_feed_falsa()
    panel._id_token_actual = lambda: "TOKEN_ID"
    estados = []
    panel._estado = lambda texto, error=False: estados.append(texto)

    monkeypatch.setattr(panel_comentarios.threading, "Thread", _ThreadFake)
    disparos = []
    monkeypatch.setattr(
        panel_comentarios.QtCore.QTimer,
        "singleShot",
        lambda ms, cb: disparos.append((ms, cb)),
    )
    resueltos = []
    monkeypatch.setattr(
        panel_comentarios.vfxflow_datos,
        "resolver_plano",
        lambda datos, token, config=None: resueltos.append(datos)
        or {"project_id": "pid", "chapter_id": "cid", "shot_id": "sid"},
    )
    monkeypatch.setattr(
        panel_comentarios.vfxflow_datos,
        "listar_actividad",
        lambda pid, sid, token, config=None: [
            {
                "content": "Buen plano",
                "userName": "Ana",
                "userRole": "artist",
                "createdAt": "2026-08-20T10:00:00Z",
                "type": "comment",
            }
        ],
    )
    monkeypatch.setattr(
        panel_comentarios.vfxflow_datos,
        "obtener_colores_estados",
        lambda pid, token, config=None: {},
    )
    monkeypatch.setattr(
        panel_comentarios.vfxflow_datos,
        "obtener_estados",
        lambda pid, token, config=None: [],
    )

    panel._cargar_comentarios_del_plano()

    # El worker (sincrónico por el fake) dejó el resultado publicado.
    assert panel._comentarios_trabajo["estado"] == "ok"
    assert resueltos and resueltos[0]["plano"] == "008_00100"
    assert disparos  # se programó el poll del QTimer

    panel._poll_comentarios()

    assert panel._comentarios_trabajo_en_curso is False
    # El feed quedó con la card del comentario y el stretch final.
    assert panel._layout_actividad.items[0]["type"] == "comment"
    assert panel._layout_actividad.items[0]["content"] == "Buen plano"
    assert panel._layout_actividad.items[-1] == "stretch"
    assert any("1 actividad" in e for e in estados)


def test_cargar_comentarios_error_red_muestra_firewall(monkeypatch):
    from SamanTools import panel_comentarios
    from SamanTools.vfxflow_auth import VfxFlowAuthError

    monkeypatch.setitem(nuke._estado, "root_name", "HTLR_107_008_00100_V01.mov")
    panel = _panel_con_feed_falsa()
    panel._id_token_actual = lambda: "TOKEN_ID"
    estados = []
    panel._estado = lambda texto, error=False: estados.append((texto, error))

    monkeypatch.setattr(panel_comentarios.threading, "Thread", _ThreadFake)
    monkeypatch.setattr(panel_comentarios.QtCore.QTimer, "singleShot", lambda ms, cb: None)

    def _boom(datos, token, config=None):
        raise VfxFlowAuthError("No se pudo contactar VFXFlow.", codigo="red")

    monkeypatch.setattr(panel_comentarios.vfxflow_datos, "resolver_plano", _boom)

    panel._cargar_comentarios_del_plano()
    panel._poll_comentarios()

    assert panel._comentarios_trabajo_en_curso is False
    assert "firewall" in panel._label_mensaje_actividad.texto
    assert panel._label_mensaje_actividad.style  # el error se marca con estilo
    # El error NO se repite en la etiqueta de estado inferior (duplicado v1.6.1).
    assert not any("firewall" in texto for texto, error in estados)
    # El feed muestra un único mensaje (sin cards).
    sin_stretch = [i for i in panel._layout_actividad.items if i != "stretch"]
    assert len(sin_stretch) == 1


def test_cargar_comentarios_resolucion_no_encontrada(monkeypatch):
    from SamanTools import panel_comentarios

    monkeypatch.setitem(nuke._estado, "root_name", "HTLR_107_008_00100_V01.mov")
    panel = _panel_con_feed_falsa()
    panel._id_token_actual = lambda: "TOKEN_ID"
    estados = []
    panel._estado = lambda texto, error=False: estados.append((texto, error))

    monkeypatch.setattr(panel_comentarios.threading, "Thread", _ThreadFake)
    monkeypatch.setattr(panel_comentarios.QtCore.QTimer, "singleShot", lambda ms, cb: None)
    monkeypatch.setattr(
        panel_comentarios.vfxflow_datos,
        "resolver_plano",
        lambda datos, token, config=None: {
            "error": "capitulo_no_encontrado",
            "project_id": "pid",
            "capitulo": 107,
        },
    )

    panel._cargar_comentarios_del_plano()
    panel._poll_comentarios()

    assert "El capítulo 107" in panel._label_mensaje_actividad.texto
    # El error de resolucion NO se repite en la etiqueta de estado inferior.
    assert not any(
        "El capítulo 107" in texto for texto, error in estados
    )


def test_publicar_actividad_sin_datos_muestra_mensaje():
    from SamanTools import panel_comentarios

    panel = _panel_con_feed_falsa()
    estados = []
    panel._estado = lambda texto, error=False: estados.append(texto)

    panel._publicar_actividad([])

    assert (
        panel._label_mensaje_actividad.texto
        == panel_comentarios._MENSAJE_SIN_ACTIVIDAD
    )
    assert any(e == panel_comentarios._MENSAJE_SIN_ACTIVIDAD for e in estados)


def test_publicar_actividad_pinta_cards_en_orden():
    panel = _panel_con_feed_falsa()
    estados = []
    panel._estado = lambda texto, error=False: estados.append(texto)
    comentario = {"type": "comment", "content": "a"}
    estado = {"type": "status_change", "content": "b"}

    panel._publicar_actividad([comentario, estado])

    assert panel._layout_actividad.items[:2] == [comentario, estado]
    assert panel._layout_actividad.items[-1] == "stretch"
    assert any("2 actividades" in e for e in estados)


def test_header_plano_texto():
    from SamanTools import panel_comentarios

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    panel._plano_activo = lambda: {
        "proyecto": "HTLR",
        "capitulo": 107,
        "plano": "008_00200",
    }
    assert panel._header_plano_texto() == "HTLR_107_008_00200"
    panel._plano_activo = lambda: None
    assert panel._header_plano_texto() == "—"
    panel._plano_activo = lambda: {"proyecto": "HTLR"}
    assert panel._header_plano_texto() == "—"


def test_mensaje_error_resolucion():
    from SamanTools import panel_comentarios

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    assert "HTLR" in panel._mensaje_error_resolucion(
        {"error": "proyecto_no_encontrado", "proyecto": "HTLR"}
    )
    assert "107" in panel._mensaje_error_resolucion(
        {"error": "capitulo_no_encontrado", "capitulo": 107}
    )
    assert "008_00100" in panel._mensaje_error_resolucion(
        {"error": "plano_no_encontrado", "plano": "008_00100"}
    )
    assert panel._mensaje_error_resolucion(None)


# ---------------------------------------------------------------------------
# Poll del comp activo: refresh automático al cambiar de plano (bug v1.6.2)
# ---------------------------------------------------------------------------


def _panel_con_poll():
    """PanelComentarios con el estado mínimo del poll (sin QApplication)."""
    from SamanTools import panel_comentarios

    p = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    p._root_anterior = "HTLR_107_008_00000_V01.mov"
    p._plano_anterior = None
    p._comentarios_trabajo_en_curso = False
    p.sesion = None
    return p


def test_chequear_cambio_plano_no_hace_nada_si_root_igual(monkeypatch):
    monkeypatch.setitem(nuke._estado, "root_name", "HTLR_107_008_00100_V01.mov")
    panel = _panel_con_poll()
    panel._root_anterior = "HTLR_107_008_00100_V01.mov"
    llamado = []
    panel._mostrar_plano_activo = lambda: llamado.append("mostrar")
    panel._cargar_comentarios_del_plano = lambda: llamado.append("cargar")

    panel._chequear_cambio_plano()

    assert llamado == []  # root igual: no tocar nada


def test_chequear_cambio_plano_refresca_y_recarga_al_cambiar(monkeypatch):
    monkeypatch.setitem(nuke._estado, "root_name", "HTLR_107_008_00100_V01.mov")
    panel = _panel_con_poll()
    panel.sesion = {"email": "a@b.com", "id_token": "ID"}
    panel._id_token_actual = lambda: "TOKEN_ID"
    llamado = []
    panel._mostrar_plano_activo = lambda: llamado.append("mostrar")
    panel._cargar_comentarios_del_plano = lambda: llamado.append("cargar")

    panel._chequear_cambio_plano()

    assert llamado == ["mostrar", "cargar"]
    assert panel._root_anterior == "HTLR_107_008_00100_V01.mov"
    assert panel._plano_anterior["plano"] == "008_00100"


def test_chequear_cambio_plano_sin_sesion_no_recarga(monkeypatch):
    monkeypatch.setitem(nuke._estado, "root_name", "HTLR_107_008_00100_V01.mov")
    panel = _panel_con_poll()  # sin sesión
    llamado = []
    panel._mostrar_plano_activo = lambda: llamado.append("mostrar")
    panel._cargar_comentarios_del_plano = lambda: llamado.append("cargar")

    panel._chequear_cambio_plano()

    assert llamado == ["mostrar"]  # solo refresca labels, sin fetch
    assert panel._root_anterior == "HTLR_107_008_00100_V01.mov"


def test_chequear_cambio_plano_sin_token_vigente_no_recarga(monkeypatch):
    monkeypatch.setitem(nuke._estado, "root_name", "HTLR_107_008_00100_V01.mov")
    panel = _panel_con_poll()
    panel.sesion = {"email": "a@b.com", "id_token": ""}
    panel._id_token_actual = lambda: None
    llamado = []
    panel._mostrar_plano_activo = lambda: llamado.append("mostrar")
    panel._cargar_comentarios_del_plano = lambda: llamado.append("cargar")

    panel._chequear_cambio_plano()

    assert llamado == ["mostrar"]  # sesión sin token vigente: no recargar


def test_chequear_cambio_plano_worker_en_curso_no_recarga(monkeypatch):
    monkeypatch.setitem(nuke._estado, "root_name", "HTLR_107_008_00100_V01.mov")
    panel = _panel_con_poll()
    panel.sesion = {"email": "a@b.com", "id_token": "ID"}
    panel._id_token_actual = lambda: "TOKEN_ID"
    panel._comentarios_trabajo_en_curso = True  # ya hay un worker en vuelo
    llamado = []
    panel._mostrar_plano_activo = lambda: llamado.append("mostrar")
    panel._cargar_comentarios_del_plano = lambda: llamado.append("cargar")

    panel._chequear_cambio_plano()

    assert llamado == ["mostrar"]  # no se dispara fetch duplicado


def test_chequear_cambio_plano_root_sin_nombre_no_rompe(monkeypatch):
    monkeypatch.setitem(nuke._estado, "root_name", "")
    panel = _panel_con_poll()
    panel.sesion = {"email": "a@b.com", "id_token": "ID"}
    panel._id_token_actual = lambda: "TOKEN_ID"
    llamado = []
    panel._mostrar_plano_activo = lambda: llamado.append("mostrar")
    panel._cargar_comentarios_del_plano = lambda: llamado.append("cargar")

    panel._chequear_cambio_plano()

    # Con comp cerrado se refrescan las etiquetas a "—" y, al haber sesión, se
    # dispara el camino de limpieza del feed ("Plano no identificado") sin
    # tocar la red: `_cargar_comentarios_del_plano` corta en plano None.
    assert llamado == ["mostrar", "cargar"]


# ---------------------------------------------------------------------------
# Tema oscuro (v1.6.2): paleta Nuke + avatar sin reborde + contraste
# ---------------------------------------------------------------------------


def test_estilo_panel_oscuro_con_selectores():
    from SamanTools import panel_comentarios

    estilo = panel_comentarios._ESTILO_PANEL
    assert "#2b2b2b" in estilo                    # fondo del panel
    assert "QFrame#cardActividad" in estilo       # selector de las cards
    assert "chipEstado" in estilo                 # badges de estados
    assert "avatarActividad" in estilo            # inicial sin reborde
    assert "#1f8ecd" in estilo                    # acento azul de Nuke
    assert "background-color: #1e1e1e" in estilo  # inputs oscuros
    assert "#334155" in estilo                    # bg-slate-700 (cards/roles)


def test_estilo_panel_no_tiene_border_radius_circular_avatar():
    from SamanTools import panel_comentarios

    # El avatar v1.6.2 NO tiene reborde redondeado: la inicial es texto plano.
    assert "border-radius:12px" not in panel_comentarios._ESTILO_PANEL
    assert "border-radius: 12px" not in panel_comentarios._ESTILO_PANEL


def test_mensaje_actividad_error_usa_color_contraste():
    from SamanTools import panel_comentarios

    panel = _panel_con_feed_falsa()
    panel._mostrar_mensaje_actividad("boom", error=True)
    assert panel_comentarios._COLOR_ERROR in panel._label_mensaje_actividad.style


def test_mensaje_actividad_comun_usa_color_secundario():
    from SamanTools import panel_comentarios

    panel = _panel_con_feed_falsa()
    panel._mostrar_mensaje_actividad("sin actividad")
    assert panel_comentarios._COLOR_MENSAJE in panel._label_mensaje_actividad.style


def test_estado_error_usa_color_contraste():
    from SamanTools import panel_comentarios

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    panel._etiqueta_estado = _LabelFake()
    panel._estado("falló", error=True)
    assert panel_comentarios._COLOR_ERROR in panel._etiqueta_estado.style
    panel._estado("ok")
    assert panel._etiqueta_estado.style == ""  # sin error: vuelve al default


# ---------------------------------------------------------------------------
# Import de referencias (v1.6.4): helpers puros + worker + Read nodes
# ---------------------------------------------------------------------------


class _RespuestaRefFake:
    """Respuesta de urllib fake: `.read()` + protocolo de contexto."""

    def __init__(self, datos):
        self._datos = datos

    def read(self):
        return self._datos

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


def test_ruta_destino_refs():
    from SamanTools import panel_comentarios

    assert panel_comentarios._ruta_destino_refs("/a/b/foo.nk") == "/a/b/ref"
    assert panel_comentarios._ruta_destino_refs("foo.nk") == "ref"
    assert panel_comentarios._ruta_destino_refs("") is None
    assert panel_comentarios._ruta_destino_refs(None) is None


def test_filename_desde_url_ref():
    from SamanTools import panel_comentarios

    url = (
        "https://firebasestorage.googleapis.com/v0/b/"
        "vfxpm-be912.firebasestorage.app/o/projects%2FlxYgN96Zk8zyhsFEABOf"
        "%2Fchapters%2FK8hWolWmRruKl5bASYxM%2Fshots%2FB3W9SUJ8jgXy2f7GMlH4"
        "%2Freferences%2FHTLR_107_008_00200.jpg?alt=media&token=abc"
    )
    assert (
        panel_comentarios._filename_desde_url_ref(url) == "HTLR_107_008_00200.jpg"
    )
    # Sin token (misma URL antes del query).
    assert (
        panel_comentarios._filename_desde_url_ref(url.split("?")[0])
        == "HTLR_107_008_00200.jpg"
    )
    # Percent-encodings extra se decodifican antes del basename.
    assert (
        panel_comentarios._filename_desde_url_ref(
            "https://x/o/otra%20cosa.png?alt=media"
        )
        == "otra cosa.png"
    )
    # URLs raras (sin marcador /o/) -> fallback con el índice.
    assert panel_comentarios._filename_desde_url_ref("") == "ref_0.jpg"
    assert panel_comentarios._filename_desde_url_ref(None) == "ref_0.jpg"
    assert (
        panel_comentarios._filename_desde_url_ref(
            "https://www.example.com/sin-marcador/aqui"
        )
        == "ref_0.jpg"
    )
    assert panel_comentarios._filename_desde_url_ref("raro", 3) == "ref_3.jpg"


def test_descargar_refs_ok_y_fallos_no_cortan(tmp_path):
    from SamanTools import panel_comentarios

    urls = [
        "https://storage/o/refs%2Fbien.jpg?alt=media&token=1",
        "https://storage/o/refs%2Fmal.jpg?alt=media&token=2",
    ]

    def _abrir_fake(req, timeout=10):
        if "bien" in req.full_url:
            return _RespuestaRefFake(b"AAA")
        raise OSError("boom red")

    resultado = panel_comentarios._descargar_refs(
        urls, str(tmp_path), abrir=_abrir_fake
    )

    assert len(resultado["ok"]) == 1
    url, ruta_local, nombre = resultado["ok"][0]
    assert url == urls[0]
    assert nombre == "bien.jpg"
    assert ruta_local == str(tmp_path / "bien.jpg")
    with open(ruta_local, "rb") as f:
        assert f.read() == b"AAA"

    # El fallo de una URL NO corta las demas: queda registrado en "fallidos".
    assert len(resultado["fallidos"]) == 1
    assert resultado["fallidos"][0][0] == urls[1]
    assert "boom" in resultado["fallidos"][0][1]


def test_importar_refs_del_plano_ok(monkeypatch):
    from SamanTools import panel_comentarios

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    monkeypatch.setattr(
        panel_comentarios.vfxflow_datos,
        "resolver_plano",
        lambda datos, token, config=None: {
            "shot": {"referenceImages": ["https://x/o/refs%2Fa.jpg?alt=media&token=1"]}
        },
    )
    monkeypatch.setattr(
        panel_comentarios,
        "_descargar_refs",
        lambda urls, directorio: {
            "ok": [("u1", directorio + "/a.jpg", "a.jpg")],
            "fallidos": [("u2", "x")],
        },
    )

    panel._importar_refs_del_plano(
        {"proyecto": "HTLR", "capitulo": 107, "plano": "008_00100"},
        "TOKEN",
        "/vol/ref",
    )

    assert panel._refs_trabajo["estado"] == "ok"
    assert panel._refs_trabajo["descargados"][0][1] == "/vol/ref/a.jpg"
    assert panel._refs_trabajo["directorio"] == "/vol/ref"
    assert len(panel._refs_trabajo["fallidos"]) == 1


def test_importar_refs_del_plano_sin_reference_images(monkeypatch):
    from SamanTools import panel_comentarios

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    monkeypatch.setattr(
        panel_comentarios.vfxflow_datos,
        "resolver_plano",
        lambda datos, token, config=None: {"shot": {"referenceImages": []}},
    )
    descargado = []
    monkeypatch.setattr(
        panel_comentarios,
        "_descargar_refs",
        lambda urls, directorio: descargado.append(urls) or {"ok": [], "fallidos": []},
    )

    panel._importar_refs_del_plano(
        {"proyecto": "HTLR", "capitulo": 107, "plano": "008_00100"},
        "TOKEN",
        "/vol/ref",
    )

    # Sin images de referencia: "ok" informativo SIN error y sin descargar.
    assert panel._refs_trabajo["estado"] == "ok"
    assert panel._refs_trabajo["sin_refs"] is True
    assert panel._refs_trabajo["mensaje"] == panel_comentarios._MENSAJE_SIN_REFS
    assert descargado == []


def test_importar_refs_del_plano_error_resolucion(monkeypatch):
    from SamanTools import panel_comentarios

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    monkeypatch.setattr(
        panel_comentarios.vfxflow_datos,
        "resolver_plano",
        lambda datos, token, config=None: {
            "error": "plano_no_encontrado",
            "plano": "008_00100",
        },
    )
    descargado = []
    monkeypatch.setattr(
        panel_comentarios,
        "_descargar_refs",
        lambda urls, directorio: descargado.append(urls) or {"ok": [], "fallidos": []},
    )

    panel._importar_refs_del_plano(
        {"proyecto": "HTLR", "capitulo": 107, "plano": "008_00100"},
        "TOKEN",
        "/vol/ref",
    )

    assert panel._refs_trabajo["estado"] == "error"
    assert panel._refs_trabajo["codigo"] == "resolucion"
    assert "008_00100" in panel._refs_trabajo["mensaje"]
    assert descargado == []


def test_cargar_refs_sin_plano_no_hace_worker(monkeypatch):
    from SamanTools import panel_comentarios

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    panel._plano_activo = lambda: None
    panel._refs_trabajo_en_curso = False
    panel._etiqueta_estado = _LabelFake()
    hilos = []
    monkeypatch.setattr(
        panel_comentarios.threading,
        "Thread",
        lambda *a, **k: hilos.append(1) or None,
    )

    panel._cargar_refs_del_plano()

    assert hilos == []
    assert panel._refs_trabajo_en_curso is False
    assert (
        panel._etiqueta_estado.texto == panel_comentarios._MENSAJE_PLANO_NO_IDENTIFICADO
    )


def test_cargar_refs_sin_sesion_no_hace_worker(monkeypatch):
    from SamanTools import panel_comentarios

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    panel._plano_activo = lambda: {
        "proyecto": "HTLR",
        "capitulo": 107,
        "plano": "008_00100",
    }
    panel._id_token_actual = lambda: None
    panel._refs_trabajo_en_curso = False
    panel._etiqueta_estado = _LabelFake()
    hilos = []
    monkeypatch.setattr(
        panel_comentarios.threading,
        "Thread",
        lambda *a, **k: hilos.append(1) or None,
    )

    panel._cargar_refs_del_plano()

    assert hilos == []
    assert panel._refs_trabajo_en_curso is False
    assert panel._etiqueta_estado.texto == panel_comentarios._MENSAJE_SIN_SESION_REFS


def test_cargar_refs_comp_sin_guardar_no_hace_worker(monkeypatch):
    from SamanTools import panel_comentarios

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    panel._plano_activo = lambda: {
        "proyecto": "HTLR",
        "capitulo": 107,
        "plano": "008_00100",
    }
    panel._id_token_actual = lambda: "TOKEN"
    monkeypatch.setitem(nuke._estado, "root_name", "")  # comp sin guardar
    panel._refs_trabajo_en_curso = False
    panel._etiqueta_estado = _LabelFake()
    hilos = []
    monkeypatch.setattr(
        panel_comentarios.threading,
        "Thread",
        lambda *a, **k: hilos.append(1) or None,
    )

    panel._cargar_refs_del_plano()

    assert hilos == []
    assert panel._etiqueta_estado.texto == panel_comentarios._MENSAJE_COMP_SIN_GUARDAR


def test_cargar_refs_dispara_worker_y_poll_aplica(monkeypatch):
    from SamanTools import panel_comentarios

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    panel._plano_activo = lambda: {
        "proyecto": "HTLR",
        "capitulo": 107,
        "plano": "008_00100",
    }
    panel._id_token_actual = lambda: "TOKEN"
    panel._refs_trabajo_en_curso = False
    panel._etiqueta_estado = _LabelFake()
    monkeypatch.setitem(nuke._estado, "root_name", "/vol/HTLR/foo.nk")

    monkeypatch.setattr(panel_comentarios.threading, "Thread", _ThreadFake)
    disparos = []
    monkeypatch.setattr(
        panel_comentarios.QtCore.QTimer,
        "singleShot",
        lambda ms, cb: disparos.append((ms, cb)),
    )
    monkeypatch.setattr(
        panel_comentarios.vfxflow_datos,
        "resolver_plano",
        lambda datos, token, config=None: {
            "shot": {"referenceImages": ["https://x/o/refs%2Fa.jpg?alt=media&token=1"]}
        },
    )
    monkeypatch.setattr(
        panel_comentarios,
        "_descargar_refs",
        lambda urls, directorio: {
            "ok": [("u", directorio + "/a.jpg", "a.jpg")],
            "fallidos": [],
        },
    )
    creados = []
    monkeypatch.setattr(
        panel_comentarios.nuke,
        "createNode",
        lambda tipo: creados.append(tipo) and nuke.NodoFake(tipo),
    )

    panel._cargar_refs_del_plano()

    # El worker (sincrónico por el fake) dejó el resultado publicado.
    assert panel._refs_trabajo["estado"] == "ok"
    assert panel._refs_trabajo["descargados"][0][1] == "/vol/HTLR/ref/a.jpg"
    assert disparos  # se programó el poll

    panel._poll_refs()

    assert panel._refs_trabajo_en_curso is False
    assert creados == ["Read"]
    assert "1 referencia importada" in panel._etiqueta_estado.texto
    assert "/vol/HTLR/ref" in panel._etiqueta_estado.texto


def test_aplicar_import_refs_crea_reads_relativos(monkeypatch):
    from SamanTools import panel_comentarios

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    panel._etiqueta_estado = _LabelFake()
    creados = []
    monkeypatch.setattr(
        panel_comentarios.nuke,
        "createNode",
        lambda tipo: creados.append(nuke.NodoFake(tipo)) or creados[-1],
    )
    trabajo = {
        "estado": "ok",
        "descargados": [
            ("u", "/vol/ref/a.jpg", "a.jpg"),
            ("u2", "/vol/ref/b.png", "b.png"),
        ],
        "fallidos": [("u3", "x")],
        "directorio": "/vol/ref",
    }

    panel._aplicar_import_refs(trabajo)

    assert len(creados) == 2
    assert creados[0]["file"].valor == "ref/a.jpg"
    assert creados[1]["file"].valor == "ref/b.png"
    assert "2 referencias importadas a /vol/ref" in panel._etiqueta_estado.texto
    assert "(1 no se pudieron descargar)" in panel._etiqueta_estado.texto


def test_aplicar_import_refs_sin_refs_informativo():
    from SamanTools import panel_comentarios

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    panel._etiqueta_estado = _LabelFake()

    panel._aplicar_import_refs(
        {"estado": "ok", "sin_refs": True, "mensaje": panel_comentarios._MENSAJE_SIN_REFS}
    )

    assert panel._etiqueta_estado.texto == panel_comentarios._MENSAJE_SIN_REFS
    assert panel._etiqueta_estado.style == ""  # informativo, sin estilo de error


def test_aplicar_import_refs_error_marca_error():
    from SamanTools import panel_comentarios

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    panel._etiqueta_estado = _LabelFake()

    panel._aplicar_import_refs({"estado": "error", "mensaje": "boom"})

    assert panel._etiqueta_estado.texto == "boom"
    assert panel_comentarios._COLOR_ERROR in panel._etiqueta_estado.style


def test_poll_refs_pendiente_reprograma(monkeypatch):
    from SamanTools import panel_comentarios

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    panel._refs_trabajo_en_curso = True
    panel._refs_trabajo = {"estado": "pendiente"}
    disparos = []
    monkeypatch.setattr(
        panel_comentarios.QtCore.QTimer,
        "singleShot",
        lambda ms, cb: disparos.append((ms, cb)),
    )

    panel._poll_refs()

    assert disparos == [(panel_comentarios._COMENTARIOS_POLL_MS, panel._poll_refs)]
    assert panel._refs_trabajo_en_curso is True


# ---------------------------------------------------------------------------
# v1.6.5 — TAREA 1: ruta del nodo Read con convención del estudio
# ---------------------------------------------------------------------------


def test_ruta_read_ref_con_ep_y_carpeta():
    from SamanTools import panel_comentarios

    comp = (
        "/Volumes/wupm/2026/HTLR/COMP/EP_102/HTLR_102_023_00100_comp_SAMAN/"
        "HTLR_102_023_00100_comp_SAMAN_V01.nk"
    )
    esperado = (
        "[python {PYTHON_COMP}]/EP_102/HTLR_102_023_00100_comp_SAMAN/"
        "ref/HTLR_102_023_0100.png"
    )
    assert panel_comentarios._ruta_read_ref(comp, "HTLR_102_023_0100.png") == esperado


def test_ruta_read_ref_sin_ep_usa_capitulo_parseado():
    from SamanTools import panel_comentarios

    comp = (
        "/comp/HTLR_107_008_00100_comp_SAMAN/"
        "HTLR_107_008_00100_comp_SAMAN.nk"
    )
    ruta = panel_comentarios._ruta_read_ref(comp, "ref1.png")
    assert ruta == (
        "[python {PYTHON_COMP}]/EP_107/HTLR_107_008_00100_comp_SAMAN/ref/ref1.png"
    )


def test_ruta_read_ref_sin_comp_fallback_relativo():
    from SamanTools import panel_comentarios

    assert panel_comentarios._ruta_read_ref("", "a.png") == "ref/a.png"
    assert panel_comentarios._ruta_read_ref(None, "a.png") == "ref/a.png"
    # Ruta con directorio pero sin EP ni capítulo deducible -> relativo.
    assert panel_comentarios._ruta_read_ref("/tmp/foo.nk", "a.png") == "ref/a.png"


def test_ruta_read_ref_adjuntos():
    from SamanTools import panel_comentarios

    ruta = panel_comentarios._ruta_read_ref(
        "/Volumes/HTLR/COMP/EP_102/CarpetaX/comp.nk", "adjuntos/cap.png"
    )
    assert ruta == (
        "[python {PYTHON_COMP}]/EP_102/CarpetaX/ref/adjuntos/cap.png"
    )


def test_aplicar_import_refs_usa_convencion_estudio(monkeypatch):
    from SamanTools import panel_comentarios

    monkeypatch.setitem(
        nuke._estado,
        "root_name",
        "/Volumes/wupm/2026/HTLR/COMP/EP_102/CarpX/CarpX_V01.nk",
    )
    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    panel._etiqueta_estado = _LabelFake()
    creados = []
    monkeypatch.setattr(
        panel_comentarios.nuke,
        "createNode",
        lambda tipo: creados.append(nuke.NodoFake(tipo)) or creados[-1],
    )
    trabajo = {
        "estado": "ok",
        "descargados": [("u", "/v/ref/a.png", "a.png")],
        "fallidos": [],
        "directorio": "/v/ref",
    }

    panel._aplicar_import_refs(trabajo)

    assert creados[0]["file"].valor == (
        "[python {PYTHON_COMP}]/EP_102/CarpX/ref/a.png"
    )


# ---------------------------------------------------------------------------
# v1.6.5 — TAREA 2: adjuntos/imágenes en las cards (helpers puros)
# ---------------------------------------------------------------------------


def test_formatear_tamano_bytes():
    from SamanTools import panel_comentarios

    assert panel_comentarios._formatear_tamano_bytes(114 * 1024) == "114 KB"
    assert panel_comentarios._formatear_tamano_bytes(560) == "560 B"
    assert panel_comentarios._formatear_tamano_bytes(0) == "0 B"
    assert panel_comentarios._formatear_tamano_bytes(None) == ""
    assert panel_comentarios._formatear_tamano_bytes("no es num") == ""


def test_ruta_cache_imagen_estable(monkeypatch):
    from SamanTools import panel_comentarios

    monkeypatch.setattr(panel_comentarios, "_CACHE_ADJUNTOS_DIR", "/tmp/saman_cache")
    url = "https://firebasestorage.googleapis.com/o/x.jpg?alt=media&token=abc"
    a = panel_comentarios._ruta_cache_imagen(url)
    b = panel_comentarios._ruta_cache_imagen(url)
    assert a == b
    assert a.startswith("/tmp/saman_cache/")
    assert a.endswith(".img")
    otro = panel_comentarios._ruta_cache_imagen(
        "https://firebasestorage.googleapis.com/o/y.jpg?alt=media&token=xyz"
    )
    assert otro != a


def test_cargar_imagen_cacheada_descarga_y_reusa(tmp_path, monkeypatch):
    from SamanTools import panel_comentarios

    monkeypatch.setattr(panel_comentarios, "_CACHE_ADJUNTOS_DIR", str(tmp_path))
    url = "https://storage/o/refs%2Fcap.png?alt=media&token=1"
    pedidos = []

    def _abrir(req, timeout=10):
        pedidos.append(req)
        return _RespuestaRefFake(b"IMG")

    ruta = panel_comentarios._cargar_imagen_cacheada(url, abrir=_abrir)
    assert ruta == panel_comentarios._ruta_cache_imagen(url)
    assert os.path.exists(ruta)
    with open(ruta, "rb") as f:
        assert f.read() == b"IMG"

    # Segunda llamada: reusa la cache (sin red).
    ruta2 = panel_comentarios._cargar_imagen_cacheada(url, abrir=_abrir)
    assert ruta2 == ruta
    assert len(pedidos) == 1


def test_cargar_imagen_cacheada_fallo_devuelve_none(tmp_path, monkeypatch):
    from SamanTools import panel_comentarios

    monkeypatch.setattr(panel_comentarios, "_CACHE_ADJUNTOS_DIR", str(tmp_path))

    def _abrir(req, timeout=10):
        raise OSError("boom")

    assert (
        panel_comentarios._cargar_imagen_cacheada(
            "https://x/o/a?alt=media", abrir=_abrir
        )
        is None
    )


def test_cargar_imagenes_adjuntas_solo_imagenes(tmp_path, monkeypatch):
    from SamanTools import panel_comentarios

    monkeypatch.setattr(panel_comentarios, "_CACHE_ADJUNTOS_DIR", str(tmp_path))

    def _abrir(req, timeout=10):
        return _RespuestaRefFake(b"X")

    actividad = [
        {
            "type": "comment",
            "attachments": [
                {"type": "image", "url": "https://x/o/a.jpg?alt=media"},
                {"type": "file", "url": "https://x/o/doc.pdf?alt=media"},
            ],
        },
        {
            "type": "file_upload",
            "attachments": [{"type": "image", "url": "https://x/o/b.png?alt=media"}],
        },
    ]
    rutas = panel_comentarios._cargar_imagenes_adjuntas(actividad, abrir=_abrir)
    assert set(rutas.keys()) == {
        "https://x/o/a.jpg?alt=media",
        "https://x/o/b.png?alt=media",
    }
    assert all(os.path.exists(p) for p in rutas.values())


def test_linea_adjunto_texto():
    from SamanTools import panel_comentarios

    archivo = panel_comentarios._linea_adjunto_texto(
        {
            "type": "file",
            "name": "doc.pdf",
            "size": 114 * 1024,
            "url": "https://x/o/doc.pdf?alt=media",
        }
    )
    assert "Adjuntó: doc.pdf (114 KB)" in archivo
    assert "https://x/o/doc.pdf" in archivo
    assert panel_comentarios._linea_adjunto_texto(
        {"type": "image", "name": "cap.png"}
    ) == "[imagen] cap.png"


# ---------------------------------------------------------------------------
# v1.6.5 — TAREA 3: capa estética (helpers puros)
# ---------------------------------------------------------------------------


def test_tiempo_relativo_largo():
    from datetime import timedelta
    from SamanTools import panel_comentarios

    ahora = datetime.now(timezone.utc)

    def iso(seg):
        return (ahora - timedelta(seconds=seg)).isoformat().replace("+00:00", "Z")

    assert panel_comentarios._tiempo_relativo_largo(iso(0)) == "hace menos de un minuto"
    assert panel_comentarios._tiempo_relativo_largo(iso(59)) == "hace menos de un minuto"
    assert panel_comentarios._tiempo_relativo_largo(iso(61)) == "hace 1 minuto"
    assert panel_comentarios._tiempo_relativo_largo(iso(125)) == "hace 2 minutos"
    assert (
        panel_comentarios._tiempo_relativo_largo(iso(3600))
        == "hace alrededor de 1 hora"
    )
    assert (
        panel_comentarios._tiempo_relativo_largo(iso(7200))
        == "hace alrededor de 2 horas"
    )
    assert panel_comentarios._tiempo_relativo_largo(iso(86400)) == "hace 1 día"
    assert panel_comentarios._tiempo_relativo_largo(iso(3 * 86400)) == "hace 3 días"
    assert panel_comentarios._tiempo_relativo_largo(iso(30 * 86400)) == "hace 1 mes"
    assert panel_comentarios._tiempo_relativo_largo(iso(61 * 86400)) == "hace 2 meses"
    assert panel_comentarios._tiempo_relativo_largo(iso(365 * 86400)) == "hace 1 año"
    assert (
        panel_comentarios._tiempo_relativo_largo(iso(2 * 365 * 86400)) == "hace 2 años"
    )


def test_dentro_ventana_10min():
    from datetime import timedelta
    from SamanTools import panel_comentarios

    ahora = datetime.now(timezone.utc)

    def iso(seg):
        return (ahora - timedelta(seconds=seg)).isoformat().replace("+00:00", "Z")

    assert panel_comentarios._dentro_ventana_10min(iso(30)) is True
    assert panel_comentarios._dentro_ventana_10min(iso(60 * 9)) is True
    assert panel_comentarios._dentro_ventana_10min(iso(60 * 11)) is False
    assert panel_comentarios._dentro_ventana_10min(iso(30 * 86400)) is False
    assert panel_comentarios._dentro_ventana_10min("no valido") is False
    assert panel_comentarios._dentro_ventana_10min(None) is False


def test_es_autor():
    from SamanTools import panel_comentarios

    sesion = {"local_id": "uid1", "email": "e.b@samanestudio.com"}
    assert panel_comentarios._es_autor({"userId": "uid1", "userName": "E"}, sesion) is True
    assert panel_comentarios._es_autor({"userId": "otro"}, sesion) is False
    assert panel_comentarios._es_autor({"userName": "E.B"}, sesion) is True
    assert panel_comentarios._es_autor({"userName": "X"}, sesion) is False
    assert panel_comentarios._es_autor({"userId": "uid1"}, None) is False


def test_agrupar_actividad():
    from SamanTools import panel_comentarios

    comentario = {"id": "c1", "type": "comment"}
    comment2 = {"id": "c2", "type": "comment"}
    reply1 = {"id": "r1", "type": "reply", "parentId": "c1"}
    reply2 = {"id": "r2", "type": "reply", "parentId": "c1"}
    padres, hijas = panel_comentarios._agrupar_actividad(
        [comentario, reply1, comment2, reply2]
    )
    assert [p["id"] for p in padres] == ["c1", "c2"]
    assert [h["id"] for h in hijas["c1"]] == ["r1", "r2"]


def test_verbo_y_glifo_tipo():
    from SamanTools import panel_comentarios

    assert panel_comentarios._verbo_tipo("comment") == "comentó"
    assert panel_comentarios._verbo_tipo("desconocido") == ""
    assert panel_comentarios._glifo_tipo("status_change") == "⇄"
    assert panel_comentarios._glifo_tipo("otro") == ""


def test_cuerpo_actividad_versiones_chip_y_cita():
    from SamanTools import panel_comentarios

    r = panel_comentarios._cuerpo_actividad(
        {"type": "version_update", "previousVersion": 1, "newVersion": 2}
    )
    assert r["versiones_chip"] == ("V1", "V2")
    assert r["chips"] is None
    r2 = panel_comentarios._cuerpo_actividad(
        {"type": "batch_update", "previousVersion": 1, "newVersion": 1}
    )
    assert r2["versiones_chip"] is None
    con_cita = panel_comentarios._cuerpo_actividad(
        {
            "type": "comment",
            "content": "ok",
            "metadata": {"quotedComment": {"content": "citado", "userName": "Luis"}},
        }
    )
    assert "citado" in con_cita["cita"]
    assert "Luis" in con_cita["cita"]
    sin_cita = panel_comentarios._cuerpo_actividad({"type": "comment", "content": "ok"})
    assert sin_cita["cita"] == ""


def test_cuerpo_actividad_status_chip_ids():
    from SamanTools import panel_comentarios

    a = {
        "type": "status_change",
        "previousState": "u1",
        "previousStateName": "APROBADO",
        "newState": "u2",
        "newStateName": "ENTREGA",
    }
    r = panel_comentarios._cuerpo_actividad(a)
    assert r["chips"] == ("APROBADO", "ENTREGA")
    assert r["chip_ids"] == ("u1", "u2")


def test_color_estado_y_styles_chip_color():
    from SamanTools import panel_comentarios

    assert panel_comentarios._color_estado({"u1": "#f59e0b"}, "u1") == "#f59e0b"
    assert panel_comentarios._color_estado({}, "u1") == ""
    assert panel_comentarios._color_estado(None, "u1") == ""
    s = panel_comentarios._styles_chip_color("#f59e0b")
    assert "#f59e0b4D" in s  # alpha ~30%
    assert "#f59e0b" in s
    assert panel_comentarios._styles_chip_color("") == ""
    assert panel_comentarios._styles_chip_color("rojo") == ""


def test_publicar_actividad_pasa_colores_a_las_cards():
    panel = _panel_con_feed_falsa()
    recibidos = []
    panel._crear_card_actividad = (
        lambda actividad, colores_estados=None, imagenes=None, es_respuesta=False: (
            recibidos.append((colores_estados, imagenes)) or actividad
        )
    )
    estados = []
    panel._estado = lambda texto, error=False: estados.append(texto)

    panel._publicar_actividad(
        [{"type": "comment", "content": "a"}],
        colores_estados={"u": "#f59e0b"},
        imagenes={"u2": "/x/a.img"},
    )

    assert recibidos == [({"u": "#f59e0b"}, {"u2": "/x/a.img"})]


def test_publicar_actividad_agrupa_respuestas():
    panel = _panel_con_feed_falsa()
    estados = []
    panel._estado = lambda texto, error=False: estados.append(texto)
    bloques = []
    panel._crear_bloque_respuestas = (
        lambda hijas, colores_estados=None, imagenes=None: (
            bloques.append(hijas) or "bloque"
        )
    )
    padre = {"id": "c1", "type": "comment", "content": "padre"}
    hijo = {"id": "r1", "type": "reply", "parentId": "c1", "content": "hijo"}

    panel._publicar_actividad([padre, hijo])

    assert "bloque" in panel._layout_actividad.items
    assert bloques == [[hijo]]


def test_trabajo_comentarios_publica_colores_e_imagenes(monkeypatch):
    from SamanTools import panel_comentarios

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    monkeypatch.setattr(
        panel_comentarios.vfxflow_datos,
        "resolver_plano",
        lambda d, t, config=None: {
            "project_id": "pid",
            "shot_id": "sid",
            "chapter_id": "cid",
            "shot": {},
        },
    )
    monkeypatch.setattr(
        panel_comentarios.vfxflow_datos,
        "listar_actividad",
        lambda pid, sid, token, config=None: [
            {"type": "comment", "content": "x", "id": "c1"}
        ],
    )
    monkeypatch.setattr(
        panel_comentarios.vfxflow_datos,
        "obtener_colores_estados",
        lambda pid, token, config=None: {"u1": "#f59e0b"},
    )
    monkeypatch.setattr(
        panel_comentarios.vfxflow_datos,
        "obtener_estados",
        lambda pid, token, config=None: [
            {"id": "u1", "name": "APROBADO", "color": "#f59e0b"}
        ],
    )
    monkeypatch.setattr(
        panel_comentarios,
        "_cargar_imagenes_adjuntas",
        lambda actividad: {"https://x/o/a.jpg?alt=media": "/cache/a.img"},
    )

    panel._trabajo_comentarios(
        {"proyecto": "HTLR", "capitulo": 107, "plano": "008_00100"}, "TOKEN"
    )

    assert panel._comentarios_trabajo["estado"] == "ok"
    assert panel._comentarios_trabajo["colores_estados"] == {"u1": "#f59e0b"}
    assert panel._comentarios_trabajo["imagenes"] == {
        "https://x/o/a.jpg?alt=media": "/cache/a.img"
    }
    assert panel._comentarios_trabajo["comentarios"][0]["id"] == "c1"
    assert panel._comentarios_trabajo["estados"][0]["name"] == "APROBADO"
    assert panel._plano_resuelto["shot_id"] == "sid"

# ---------------------------------------------------------------------------
# v1.7.0 — TAREA A: botón "Importar" siempre presente por adjunto de imagen
# ---------------------------------------------------------------------------


def test_debe_mostrar_boton_importar_siempre_en_imagen():
    from SamanTools import panel_comentarios

    adj = {"type": "image", "url": "https://x/o/a.jpg?alt=media", "name": "a.jpg"}
    # Sin cache (thumbnail puede fallar) -> el botón se muestra IGUAL.
    assert panel_comentarios._debe_mostrar_boton_importar(adj, {}) is True
    assert (
        panel_comentarios._debe_mostrar_boton_importar(
            adj, {"https://x/o/a.jpg?alt=media": "/x/a.img"}
        )
        is True
    )
    assert (
        panel_comentarios._debe_mostrar_boton_importar(
            {"type": "file", "url": "https://x/o/d.pdf"}, {}
        )
        is False
    )
    assert (
        panel_comentarios._debe_mostrar_boton_importar(
            {"type": "image", "name": "a.jpg"}, {}
        )
        is False  # sin url no se puede importar
    )
    assert panel_comentarios._debe_mostrar_boton_importar(None, {}) is False


# ---------------------------------------------------------------------------
# v1.7.0 — TAREA B.1: payloads de escritura + envío de comment/reply
# ---------------------------------------------------------------------------


def test_payload_actividad_tipos_firestore():
    from SamanTools import panel_comentarios

    campos = {
        "type": "comment",
        "content": "hola",
        "isPrivate": False,
        "parentId": None,
        "createdAt": "2026-08-01T00:00:00.000Z",
        "metadata": {},
        "n": 3,
    }
    fields = panel_comentarios._payload_actividad(campos)
    assert fields["type"] == {"stringValue": "comment"}
    assert fields["content"] == {"stringValue": "hola"}
    assert fields["isPrivate"] == {"booleanValue": False}
    assert fields["parentId"] == {"nullValue": None}
    assert fields["createdAt"] == {"timestampValue": "2026-08-01T00:00:00.000Z"}
    assert fields["metadata"] == {"mapValue": {"fields": {}}}
    assert fields["n"] == {"integerValue": "3"}


def test_base_campos_actividad_desde_sesion():
    from SamanTools import panel_comentarios

    sesion = {"local_id": "uid1", "email": "ana.lopez@samanestudio.com"}
    campos = panel_comentarios._base_campos_actividad(
        "pid1", "sid1", sesion, "comment", "texto"
    )
    assert campos["type"] == "comment"
    assert campos["shotId"] == "sid1"
    assert campos["projectId"] == "pid1"
    assert campos["userId"] == "uid1"
    assert campos["userName"] == "ana.lopez"
    assert campos["userRole"] == "artist"
    assert campos["role"] == "artist"
    assert campos["isPrivate"] is False
    assert campos["metadata"] == {}


def test_campos_status_change():
    from SamanTools import panel_comentarios

    campos = panel_comentarios._campos_status_change(
        "pid", "sid", {"email": "a@b.com"}, "u1", "APROBADO", "u2", "ENTREGA"
    )
    assert campos["type"] == "status_change"
    assert campos["previousState"] == "u1"
    assert campos["previousStateName"] == "APROBADO"
    assert campos["newState"] == "u2"
    assert campos["newStateName"] == "ENTREGA"
    assert "APROBADO" in campos["content"] and "ENTREGA" in campos["content"]


def test_trabajo_crear_actividad_comment_publica_ok(monkeypatch):
    from SamanTools import panel_comentarios

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    monkeypatch.setattr(
        panel_comentarios.vfxflow_datos,
        "resolver_plano",
        lambda d, t, config=None: {
            "project_id": "pid",
            "chapter_id": "cid",
            "shot_id": "sid",
            "shot": {},
        },
    )
    creadas = []
    panel._crear_documento_actividad = (
        lambda pid, campos, token: creadas.append(pid) or {}
    )
    campos = panel_comentarios._base_campos_actividad(
        "", "", {"email": "a@b.com", "local_id": "u"}, "comment", "hola"
    )

    panel._trabajo_crear_actividad(
        {"proyecto": "HTLR", "capitulo": 107, "plano": "008_00100"}, campos, "T"
    )

    assert panel._escritura_trabajo["estado"] == "ok"
    assert panel._escritura_trabajo["mensaje"] == "Comentario publicado."
    assert creadas == ["pid"]
    assert campos["shotId"] == "sid"
    assert campos["projectId"] == "pid"


def test_payload_reply_incluye_parent_id():
    from SamanTools import panel_comentarios

    campos = panel_comentarios._base_campos_actividad(
        "pid", "sid", {"email": "a@b.com"}, "reply", "res"
    )
    campos["parentId"] = "c1"
    fields = panel_comentarios._payload_actividad(campos)
    assert fields["parentId"] == {"stringValue": "c1"}


def test_on_enviar_comentario_lanza_comment_y_reply(monkeypatch):
    from SamanTools import panel_comentarios

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    panel._input_comentario = _LineEditFake("hola")
    panel.sesion = {"email": "a@b.com", "local_id": "u", "id_token": "IT"}
    panel._plano_activo = lambda: {
        "proyecto": "HTLR",
        "capitulo": 107,
        "plano": "008_00100",
    }
    panel._id_token_actual = lambda: "TOKEN"
    panel._escritura_trabajo_en_curso = False
    panel._reply_padre_id = None
    panel.sesion = {"email": "a@b.com", "local_id": "u", "id_token": "IT"}
    lanzados = []
    panel._lanzar_escritura = (
        lambda callable_, args, mensaje: lanzados.append((callable_, args, mensaje))
    )

    panel._on_enviar_comentario()
    assert lanzados and lanzados[0][0] == panel._trabajo_crear_actividad
    campos = lanzados[0][1][1]
    assert campos["type"] == "comment"
    assert campos.get("parentId") is None

    # Modo reply: el payload lleva parentId y type reply.
    panel._reply_padre_id = "c1"
    panel._reply_padre_autor = "Ana"
    lanzados.clear()
    panel._on_enviar_comentario()
    campos = lanzados[0][1][1]
    assert campos["type"] == "reply"
    assert campos["parentId"] == "c1"

    # Texto vacío: no lanza nada.
    panel._input_comentario = _LineEditFake("   ")
    lanzados.clear()
    panel._on_enviar_comentario()
    assert lanzados == []


def test_actualizar_habilitacion_escritura():
    from SamanTools import panel_comentarios

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    panel._input_comentario = _LineEditFake()
    panel._boton_enviar = _LineEditFake()
    panel._boton_subir_imagen = _LineEditFake()
    panel._estados_combo = {}
    panel._fila_respuesta = None
    panel.sesion = {"email": "a@b.com", "id_token": "IT"}
    panel._plano_activo = lambda: {
        "proyecto": "HTLR",
        "capitulo": 107,
        "plano": "008_00100",
    }

    panel._actualizar_habilitacion_escritura()
    assert panel._input_comentario.habilitado is True
    assert panel._boton_enviar.habilitado is True
    assert panel._boton_subir_imagen.habilitado is True

    panel.sesion = None
    panel._actualizar_habilitacion_escritura()
    assert panel._input_comentario.habilitado is False
    assert panel._boton_enviar.habilitado is False


# ---------------------------------------------------------------------------
# v1.7.0 — TAREA B.2: combo de estado + cambio de estado
# ---------------------------------------------------------------------------


def test_indices_estado_anterior_siguiente():
    from SamanTools import panel_comentarios

    ids = ["e1", "e2", "e3"]
    assert panel_comentarios._indices_estado_anterior_siguiente(ids, "e1") == (None, "e2")
    assert panel_comentarios._indices_estado_anterior_siguiente(ids, "e2") == ("e1", "e3")
    assert panel_comentarios._indices_estado_anterior_siguiente(ids, "e3") == ("e2", None)
    # Único estado: ambas flechas None.
    assert panel_comentarios._indices_estado_anterior_siguiente(["e1"], "e1") == (None, None)
    # Actual fuera de la lista (o sin actual): no navegar.
    assert panel_comentarios._indices_estado_anterior_siguiente(ids, "zzz") == (None, None)
    assert panel_comentarios._indices_estado_anterior_siguiente(ids, "") == (None, None)


def test_acciones_estado_marca_actual():
    from SamanTools import panel_comentarios

    estados = [{"id": "e1", "name": "APROBADO"}, {"id": "e2", "name": "ENTREGA"}]
    combo = {str(e["id"]): e for e in estados}
    acciones = panel_comentarios._acciones_estado(["e1", "e2"], combo, "e2")
    assert acciones == [("e1", "APROBADO", False), ("e2", "✓ ENTREGA", True)]


def test_poblar_estado_selector_selecciona_actual():
    from SamanTools import panel_comentarios

    panel = _panel_con_selector()
    estados = [
        {"id": "e1", "name": "Recibido", "color": "#3B82F6", "order": 1},
        {"id": "e2", "name": "Aprobado", "color": "#22C55E", "order": 2},
    ]

    panel._poblar_estado_selector(estados, "e2")

    assert panel._estados_ordenados == ["e1", "e2"]
    assert panel._estado_actual_id == "e2"
    assert panel._estados_combo["e1"]["order"] == 1
    chip = panel._boton_estado_actual
    # El color viaja como icono dot (QToolButton no soporta rich text);
    # el texto del chip es el nombre del estado, no HTML.
    assert chip.texto == "Aprobado"
    # Actual en el último índice: siguiente deshabilitado, anterior habilitado.
    assert panel._boton_estado_siguiente.habilitado is False
    assert panel._boton_estado_anterior.habilitado is True
    assert panel._boton_estado_actual.habilitado is True


def test_poblar_estado_selector_vacio_deshabilitado():
    from SamanTools import panel_comentarios

    panel = _panel_con_selector()
    panel._poblar_estado_selector([], "")
    assert panel._estados_ordenados == []
    assert panel._boton_estado_actual.texto == "Estado"
    assert panel._boton_estado_actual.habilitado is False
    assert "Sin estados" in panel._boton_estado_actual.tooltip
    assert panel._boton_estado_anterior.habilitado is False
    assert panel._boton_estado_siguiente.habilitado is False


def test_poblar_estado_selector_sin_widgets_no_rompe():
    from SamanTools import panel_comentarios

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    panel.sesion = {"email": "a@b.com"}
    panel._poblar_estado_selector([{"id": "e", "name": "E"}], "e")
    assert panel._estados_combo == {"e": {"id": "e", "name": "E"}}
    assert panel._estados_ordenados == ["e"]


def test_selector_deshabilitado_durante_escritura():
    from SamanTools import panel_comentarios

    panel = _panel_con_selector()
    panel._poblar_estado_selector(
        [{"id": "e1", "name": "A"}, {"id": "e2", "name": "B"}], "e1"
    )
    assert panel._boton_estado_siguiente.habilitado is True
    panel._escritura_trabajo_en_curso = True
    panel._aplicar_estado_selector_enabled()
    assert panel._boton_estado_actual.habilitado is False
    assert panel._boton_estado_siguiente.habilitado is False
    assert panel._boton_estado_anterior.habilitado is False


def test_aplicar_cambio_estado_escribe_directo():
    from SamanTools import panel_comentarios

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    panel.sesion = {"email": "a@b.com", "local_id": "uid", "id_token": "IT"}
    panel._estados_combo = {
        "e1": {"id": "e1", "name": "APROBADO"},
        "e2": {"id": "e2", "name": "ENTREGA"},
    }
    panel._estados_ordenados = ["e1", "e2"]
    panel._estado_actual_id = "e1"
    panel._plano_resuelto = {
        "project_id": "pid",
        "chapter_id": "cid",
        "shot_id": "sid",
        "shot": {"stateId": "e1", "status": "APROBADO"},
    }
    panel._plano_activo = lambda: {
        "proyecto": "HTLR",
        "capitulo": 107,
        "plano": "008_00100",
    }
    panel._id_token_actual = lambda: "TOKEN"
    panel._escritura_trabajo_en_curso = False
    lanzados = []
    panel._lanzar_escritura = lambda *a, **k: lanzados.append(a)

    assert panel._aplicar_cambio_estado("e1") is False  # ya es el actual
    assert lanzados == []

    assert panel._aplicar_cambio_estado("noexiste") is False
    assert lanzados == []

    assert panel._aplicar_cambio_estado("e2") is True  # otro estado -> escribe
    assert lanzados and lanzados[0][0] == panel._trabajo_cambio_estado
    campos = lanzados[0][1][3]
    assert campos["newState"] == "e2"
    assert campos["newStateName"] == "ENTREGA"
    assert campos["previousStateName"] == "APROBADO"


def test_flechas_marcan_pendiente_sin_escribir():
    from SamanTools import panel_comentarios

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    panel._estados_ordenados = ["e1", "e2", "e3"]
    panel._estado_actual_id = "e2"
    llamado = []
    panel._establecer_estado_pendiente = lambda nuevo_id: llamado.append(nuevo_id)

    panel._on_estado_anterior()
    panel._on_estado_siguiente()
    assert llamado == ["e1", "e3"]  # NO escribe: solo marca pendiente

    # Sin anterior (primer estado) / sin siguiente (último): nada.
    panel._estado_actual_id = "e1"
    llamado.clear()
    panel._on_estado_anterior()
    assert llamado == []
    panel._on_estado_siguiente()
    assert llamado == ["e2"]


def test_establecer_estado_pendiente_ambar_y_cancelar():
    from SamanTools import panel_comentarios

    panel = _panel_con_selector()
    panel._poblar_estado_selector(
        [
            {"id": "e1", "name": "Recibido"},
            {"id": "e2", "name": "En proceso"},
            {"id": "e3", "name": "Aprobado"},
        ],
        "e1",
    )
    assert panel._estado_pendiente_id is None
    assert panel._boton_guardar_estado.visible is False

    # Elegir otro estado -> pendiente ámbar + Guardar/Undo visibles.
    panel._establecer_estado_pendiente("e2")
    assert panel._estado_pendiente_id == "e2"
    chip = panel._boton_estado_actual
    assert chip.texto == "En proceso"
    assert "#78350f" in chip.style and "#fcd34d" in chip.style
    assert "pendiente" in chip.tooltip
    assert panel._boton_guardar_estado.visible is True
    assert panel._boton_guardar_estado.habilitado is True
    assert panel._boton_cancelar_estado.visible is True
    assert panel._boton_cancelar_estado.habilitado is True

    # Re-elegir OTRO estado reemplaza el pendiente.
    panel._establecer_estado_pendiente("e3")
    assert panel._estado_pendiente_id == "e3"
    assert panel._boton_estado_actual.texto == "Aprobado"

    # Re-elegir el estado ACTUAL cancela el pendiente (vuelve al original).
    panel._establecer_estado_pendiente("e1")
    assert panel._estado_pendiente_id is None
    assert panel._boton_estado_actual.texto == "Recibido"
    assert panel._boton_estado_actual.style == ""
    assert panel._boton_guardar_estado.visible is False


def test_on_cancelar_estado_sin_red():
    from SamanTools import panel_comentarios

    panel = _panel_con_selector()
    panel._poblar_estado_selector(
        [{"id": "e1", "name": "Recibido"}, {"id": "e2", "name": "Entregado"}], "e1"
    )
    panel._establecer_estado_pendiente("e2")
    escrituras = []
    panel._aplicar_cambio_estado = lambda nuevo_id: escrituras.append(nuevo_id) or True

    panel._on_cancelar_estado()

    assert escrituras == []  # Undo es SOLO memoria, sin red
    assert panel._estado_pendiente_id is None
    assert panel._boton_estado_actual.texto == "Recibido"
    assert panel._boton_estado_actual.style == ""
    assert panel._boton_guardar_estado.visible is False


def test_on_guardar_estado_escribe_pendiente():
    from SamanTools import panel_comentarios

    panel = _panel_con_selector()
    panel._poblar_estado_selector(
        [{"id": "e1", "name": "Recibido"}, {"id": "e2", "name": "Entregado"}], "e1"
    )
    panel._establecer_estado_pendiente("e2")
    escrituras = []
    panel._aplicar_cambio_estado = lambda nuevo_id: escrituras.append(nuevo_id) or True

    panel._on_guardar_estado()

    assert escrituras == ["e2"]  # Guardar escribe SOLO con el pendiente

    # Sin pendiente / en vuelo: no escribe.
    panel._estado_pendiente_id = None
    panel._on_guardar_estado()
    panel._establecer_estado_pendiente("e2")
    panel._escritura_trabajo_en_curso = True
    panel._on_guardar_estado()
    assert escrituras == ["e2"]


def test_aplicar_estado_selector_enabled_pendiente_y_escritura():
    from SamanTools import panel_comentarios

    panel = _panel_con_selector()
    panel._poblar_estado_selector(
        [{"id": "e1", "name": "Recibido"}, {"id": "e2", "name": "Entregado"}], "e1"
    )
    panel._establecer_estado_pendiente("e2")
    assert panel._boton_guardar_estado.habilitado is True
    assert panel._boton_cancelar_estado.habilitado is True
    assert panel._boton_estado_actual.habilitado is True

    # Durante la escritura todo queda deshabilitado (los botones siguen
    # visibles para que se vea el pendiente, pero no clicables).
    panel._escritura_trabajo_en_curso = True
    panel._aplicar_estado_selector_enabled()
    assert panel._boton_guardar_estado.habilitado is False
    assert panel._boton_cancelar_estado.habilitado is False
    assert panel._boton_estado_actual.habilitado is False

    # Al cancelar (fuera de escritura) los botones se ocultan.
    panel._escritura_trabajo_en_curso = False
    panel._on_cancelar_estado()
    assert panel._boton_guardar_estado.visible is False
    assert panel._boton_cancelar_estado.visible is False


def test_trabajo_cambio_estado_patch_shot(monkeypatch):
    from SamanTools import panel_comentarios

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    campos = panel_comentarios._campos_status_change(
        "pid", "sid", {"email": "a@b.com"}, "e1", "APROBADO", "e2", "ENTREGA"
    )
    creada = []
    panel._crear_documento_actividad = (
        lambda pid, c, token: creada.append(pid) or {}
    )
    parchado = []
    panel._actualizar_estado_shot = (
        lambda resuelto, nuevo_id, nuevo_nombre, token: parchado.append(
            (nuevo_id, nuevo_nombre)
        )
        and None
    )
    resuelto = {"project_id": "pid", "chapter_id": "cid", "shot_id": "sid"}

    panel._trabajo_cambio_estado({"p": "d"}, "T", resuelto, campos)

    assert panel._escritura_trabajo["estado"] == "ok"
    assert panel._escritura_trabajo["mensaje"] == "Estado cambiado."
    assert creada == ["pid"]
    assert parchado == [("e2", "ENTREGA")]


# ---------------------------------------------------------------------------
# v1.7.0 — TAREA B.3: crop 16:9 + subida 1280×720
# ---------------------------------------------------------------------------


def test_rect_crop_central():
    from SamanTools import panel_comentarios

    # Ya 16:9 -> rect completo.
    assert panel_comentarios._rect_crop_central(1600, 900) == (0, 0, 1600, 900)
    # Horizontal 4:3 -> recorta ancho (centrado).
    assert panel_comentarios._rect_crop_central(1600, 1200) == (0, 150, 1600, 900)
    # Vertical 9:16 -> recorta alto.
    assert panel_comentarios._rect_crop_central(900, 1600) == (0, 547, 900, 506)
    # Cuadrada.
    x, y, w, h = panel_comentarios._rect_crop_central(1000, 1000)
    assert (x, w) == (0, 1000)
    assert (y, h) == (219, 562)
    # Degenerados no rompen.
    assert panel_comentarios._rect_crop_central(0, 0) == (0, 0, 0, 0)


def test_trabajo_subir_imagen_publica_ok(tmp_path, monkeypatch):
    from SamanTools import panel_comentarios

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    monkeypatch.setattr(
        panel_comentarios.vfxflow_datos,
        "resolver_plano",
        lambda d, t, config=None: {
            "project_id": "pid",
            "chapter_id": "cid",
            "shot_id": "sid",
            "shot": {},
        },
    )
    subidas = []
    monkeypatch.setattr(
        panel_comentarios.vfxflow_auth,
        "_upload_media_bearer",
        lambda url, datos, token, content_type: subidas.append(url) or {"name": "x"},
    )
    monkeypatch.setattr(
        panel_comentarios.vfxflow_auth,
        "_get_con_bearer",
        lambda url, token: {"downloadTokens": "tok1,tok2"},
    )
    creadas = []
    monkeypatch.setattr(
        panel_comentarios.vfxflow_auth,
        "_post_json_bearer",
        lambda url, payload, token: creadas.append(payload) or {"name": "doc"},
    )
    jpg = str(tmp_path / "cap.jpg")
    with open(jpg, "wb") as fh:
        fh.write(b"JPEGDATA")

    panel._trabajo_subir_imagen(
        jpg,
        {"proyecto": "HTLR", "capitulo": 107, "plano": "008_00100"},
        "T",
        "cap.jpg",
        99,
        {"email": "a@b.com", "local_id": "uid"},
    )

    assert panel._escritura_trabajo["estado"] == "ok"
    assert panel._escritura_trabajo["mensaje"] == "Imagen subida."
    assert subidas  # se llamó el upload del jpg a storage
    assert creadas  # se creó la actividad file_upload
    values = creadas[0]["fields"]["attachments"]["arrayValue"]["values"]
    adj = values[0]["mapValue"]["fields"]
    assert adj["type"] == {"stringValue": "image"}
    assert "tok1" in adj["url"]["stringValue"]
    assert adj["name"] == {"stringValue": "cap.jpg"}
    assert adj["size"] == {"integerValue": "99"}
    # El export temporal se borra al terminar el worker (ok).
    assert not os.path.exists(jpg)


def test_trabajo_subir_imagen_sin_temp_devuelve_error(monkeypatch, tmp_path):
    from SamanTools import panel_comentarios

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    panel._trabajo_subir_imagen(
        str(tmp_path / "no_existe.jpg"),
        {"proyecto": "HTLR", "capitulo": 107, "plano": "008_00100"},
        "T",
        "cap.jpg",
        99,
        {"email": "a@b.com", "local_id": "uid"},
    )

    assert panel._escritura_trabajo["estado"] == "error"
    assert "temporal" in panel._escritura_trabajo["mensaje"]


# ---------------------------------------------------------------------------
# v1.7.0 — TAREA B.4: modo respuesta
# ---------------------------------------------------------------------------


def test_modo_respuesta_flag_y_cancelar():
    from SamanTools import panel_comentarios

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    panel._input_comentario = _LineEditFake()
    panel._fila_respuesta = _WidgetFake()
    panel._label_modo_respuesta = _WidgetFake()
    panel._reply_padre_id = None
    panel._reply_padre_autor = ""

    panel._iniciar_modo_respuesta("Ana", "c1")
    assert panel._reply_padre_id == "c1"
    assert panel._reply_padre_autor == "Ana"
    assert panel._label_modo_respuesta.texto == "Respondiendo a Ana"
    assert panel._fila_respuesta.visible is True

    panel._cancelar_modo_respuesta()
    assert panel._reply_padre_id is None
    assert panel._fila_respuesta.visible is False


def test_poll_escritura_ok_recarga_y_limpia(monkeypatch):
    from SamanTools import panel_comentarios

    panel = _panel_con_feed_falsa()
    panel._input_comentario = _LineEditFake("texto")
    panel._fila_respuesta = None
    panel.sesion = {"email": "a@b.com"}
    panel._escritura_trabajo_en_curso = True
    panel._escritura_trabajo = {
        "estado": "ok",
        "mensaje": "Comentario publicado.",
        "publicado": True,
    }
    panel._estado = lambda *a, **k: None
    recargadas = []
    panel._cargar_comentarios_del_plano = lambda: recargadas.append(1)
    monster = []
    monkeypatch.setattr(
        panel_comentarios.QtCore.QTimer,
        "singleShot",
        lambda ms, cb: monster.append((ms, cb)),
    )

    panel._poll_escritura()

    assert panel._escritura_trabajo_en_curso is False
    assert panel._input_comentario._texto == ""
    assert recargadas == [1]
    assert monster == []  # no reprograma


def test_poll_escritura_pendiente_reprograma(monkeypatch):
    from SamanTools import panel_comentarios

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    panel._escritura_trabajo_en_curso = True
    panel._escritura_trabajo = {"estado": "pendiente"}
    disparos = []
    monkeypatch.setattr(
        panel_comentarios.QtCore.QTimer,
        "singleShot",
        lambda ms, cb: disparos.append((ms, cb)),
    )

    panel._poll_escritura()

    assert disparos == [(panel_comentarios._COMENTARIOS_POLL_MS, panel._poll_escritura)]
    assert panel._escritura_trabajo_en_curso is True


# ---------------------------------------------------------------------------
# Import de adjunto marcado con el comentario (Read + Text2)
# ---------------------------------------------------------------------------


class _KnobFakeV2:
    """Knob mínimo que recuerda el valor seteado."""

    def __init__(self):
        self.valor = None

    def setValue(self, valor):
        self.valor = valor


class _NodoFakeV2:
    """Nodo fake: registra knobs por nombre y los inputs que se conectan."""

    def __init__(self, cls):
        self.cls = cls
        self.knobs = {
            "file": _KnobFakeV2(),
            "label": _KnobFakeV2(),
            "message": _KnobFakeV2(),
        }
        self.inputs_llamadas = []

    def __getitem__(self, clave):
        if clave not in self.knobs:
            self.knobs[clave] = _KnobFakeV2()
        return self.knobs[clave]

    def setInput(self, *args):
        self.inputs_llamadas.append(args)


def test_label_read_adjunto():
    from SamanTools import panel_comentarios

    # autor + contenido.
    assert (
        panel_comentarios._label_read_adjunto(
            {"autor": "Ana", "contenido": "Mirá este paso"}
        )
        == "comentario de Ana: Mirá este paso"
    )
    # contenido largo se recorta a ~60 caracteres.
    largo = "Un comentario muy largo " * 6
    res = panel_comentarios._label_read_adjunto(
        {"autor": "Ana", "contenido": largo}
    )
    assert len(res) <= 60
    assert res.endswith("...")
    # sin autor.
    assert (
        panel_comentarios._label_read_adjunto({"contenido": "hola"})
        == "comentario: hola"
    )
    # sin contexto/None.
    assert panel_comentarios._label_read_adjunto({}) == "comentario"
    assert panel_comentarios._label_read_adjunto(None) == "comentario"


def test_poll_adjunto_crea_read_y_text2_con_contexto(monkeypatch):
    from SamanTools import panel_comentarios

    monkeypatch.setitem(
        nuke._estado,
        "root_name",
        "/vol/HTLR/COMP/EP_102/Carp/Carp_V01.nk",
    )
    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    panel._etiqueta_estado = _LabelFake()
    panel._adjunto_trabajo_en_curso = True
    panel._adjunto_trabajo = {
        "estado": "ok",
        "nombre": "cap.jpg",
        "directorio": "/vol/ref/adjuntos",
        "contexto": {
            "autor": "Ana",
            "contenido": "Mirá este paso",
            "comentario_id": "c1",
        },
    }
    creados = []

    def _crear(tipo):
        nodo = _NodoFakeV2(tipo)
        creados.append(nodo)
        return nodo

    monkeypatch.setattr(panel_comentarios.nuke, "createNode", _crear)
    disparos = []
    monkeypatch.setattr(
        panel_comentarios.QtCore.QTimer,
        "singleShot",
        lambda ms, cb: disparos.append((ms, cb)),
    )

    panel._poll_adjunto()

    assert panel._adjunto_trabajo_en_curso is False
    assert [c.cls for c in creados] == ["Read", "Text2"]
    read, text2 = creados
    # Read con la convención del estudio + label con el comentario.
    assert read["file"].valor == (
        "[python {PYTHON_COMP}]/EP_102/Carp/ref/adjuntos/cap.jpg"
    )
    assert read["label"].valor == "comentario de Ana: Mirá este paso"
    # Text2 suelto con el contenido del comentario.
    assert text2["message"].valor == "Mirá este paso"
    assert text2["label"].valor == "comentario de Ana"
    assert text2.inputs_llamadas == []  # NO conectado al Read
    assert disparos == []


def test_poll_adjunto_sin_texto_usa_marca(monkeypatch):
    from SamanTools import panel_comentarios

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    panel._etiqueta_estado = _LabelFake()
    panel._adjunto_trabajo_en_curso = True
    panel._adjunto_trabajo = {
        "estado": "ok",
        "nombre": "cap.jpg",
        "directorio": "/v/ref",
        "contexto": {"autor": "", "contenido": "", "comentario_id": "c1"},
    }
    creados = []
    monkeypatch.setattr(
        panel_comentarios.nuke,
        "createNode",
        lambda tipo: creados.append(_NodoFakeV2(tipo)) or creados[-1],
    )

    panel._poll_adjunto()

    text2 = creados[1]
    assert text2["message"].valor == "«sin texto»"
    assert text2["label"].valor == "comentario"
    assert panel._etiqueta_estado.texto == (
        "Adjunto importado como Read (con comentario)."
    )


def test_poll_adjunto_sin_contexto_no_rompe(monkeypatch):
    from SamanTools import panel_comentarios

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    panel._etiqueta_estado = _LabelFake()
    panel._adjunto_trabajo_en_curso = True
    panel._adjunto_trabajo = {"estado": "ok", "nombre": "cap.jpg",
                              "directorio": "/v/ref"}
    creados = []
    monkeypatch.setattr(
        panel_comentarios.nuke,
        "createNode",
        lambda tipo: creados.append(_NodoFakeV2(tipo)) or creados[-1],
    )

    panel._poll_adjunto()

    assert [c.cls for c in creados] == ["Read", "Text2"]
    assert creados[0]["label"].valor == "comentario"


# ---------------------------------------------------------------------------
# Fix identidad de la escritura (v1.7.x): user_id del refresh + perfil
# ---------------------------------------------------------------------------


def test_registrar_sesion_refresh_toma_user_id_como_local_id(monkeypatch):
    from SamanTools import panel_comentarios, sesion_vfxflow

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    guardadas = []
    monkeypatch.setattr(
        sesion_vfxflow, "guardar_sesion", lambda s: guardadas.append(s) or True
    )

    # El refresh devuelve `user_id`, NO `local_id` (bug reportado).
    panel._registrar_sesion(
        {"id_token": "ID", "refresh_token": "RT2", "expires_in": 3600,
         "user_id": "uid1"}
    )
    assert panel.sesion["local_id"] == "uid1"
    assert guardadas and guardadas[0]["local_id"] == "uid1"


def test_registrar_sesion_conserva_y_acepta_identidad(monkeypatch):
    from SamanTools import panel_comentarios, sesion_vfxflow

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    monkeypatch.setattr(sesion_vfxflow, "guardar_sesion", lambda s: True)
    panel.sesion = {
        "id_token": "ID0", "refresh_token": "RT0", "local_id": "uid0",
        "email": "a@b.co", "expira_en": 10,
        "userName": "Viejo", "userPhotoURL": "foto0", "role": "admin",
    }

    # Respuesta de refresh sin identidad: conserva la previa + user_id.
    panel._registrar_sesion(
        {"id_token": "ID1", "refresh_token": "RT1", "expires_in": 3600,
         "user_id": "uid1"}
    )
    assert panel.sesion["local_id"] == "uid1"
    assert panel.sesion["userName"] == "Viejo"
    assert panel.sesion["role"] == "admin"
    assert panel.sesion["userPhotoURL"] == "foto0"

    # Respuesta con identidad nueva: prevalece.
    panel._registrar_sesion(
        {"id_token": "ID2", "refresh_token": "RT2", "expires_in": 3600,
         "user_id": "uid2", "userName": "Nuevo", "userPhotoURL": "foto2",
         "role": "artist"}
    )
    assert panel.sesion["userName"] == "Nuevo"
    assert panel.sesion["role"] == "artist"
    assert panel.sesion["userPhotoURL"] == "foto2"


def test_fusionar_identidad_en_sesion(monkeypatch):
    from SamanTools import panel_comentarios, sesion_vfxflow

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    panel.sesion = {"local_id": "u1", "id_token": "ID",
                    "email": "a@b.co", "userName": ""}
    guardadas = []
    monkeypatch.setattr(
        sesion_vfxflow, "guardar_sesion", lambda s: guardadas.append(s) or True
    )

    panel._fusionar_identidad_en_sesion(
        {"role": "administrator", "name": "Emanuel Barriga",
         "avatarUrl": "https://x/a.png"}
    )
    assert panel.sesion["userName"] == "Emanuel Barriga"
    assert panel.sesion["role"] == "administrator"
    assert panel.sesion["userPhotoURL"] == "https://x/a.png"
    assert guardadas and guardadas[-1]["userName"] == "Emanuel Barriga"

    # Un doc sin name no pisa el userName ya fusionado.
    panel._fusionar_identidad_en_sesion({"role": "artist"})
    assert panel.sesion["userName"] == "Emanuel Barriga"
    assert panel.sesion["role"] == "artist"
    assert panel.sesion["userPhotoURL"] == "https://x/a.png"


def test_base_campos_actividad_incluye_identidad_real():
    from SamanTools import panel_comentarios

    sesion = {
        "local_id": "u1",
        "email": "e.b@samanestudio.com",
        "userName": "Emanuel Barriga",
        "role": "administrator",
        "userPhotoURL": "https://x/a.png",
    }
    campos = panel_comentarios._base_campos_actividad(
        "pid", "sid", sesion, "comment", "x"
    )
    assert campos["userId"] == "u1"
    assert campos["userName"] == "Emanuel Barriga"
    assert campos["userRole"] == "administrator"
    assert campos["role"] == "administrator"
    assert campos["userPhotoURL"] == "https://x/a.png"

    # Sin sesión: defaults actuales ("" / "artista" / "").
    vacios = panel_comentarios._base_campos_actividad(
        "pid", "sid", {}, "comment", "x"
    )
    assert vacios["userId"] == ""
    assert vacios["userName"] == "artista"
    assert vacios["userRole"] == "artist"
    assert vacios["userPhotoURL"] == ""


def test_autologin_rellena_identidad_sesion_vieja(monkeypatch):
    from SamanTools import panel_comentarios, sesion_vfxflow, vfxflow_config

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    estados = []
    panel._estado = lambda texto, error=False: estados.append(texto)
    panel._registrar_sesion = lambda respuesta, email=None: setattr(
        panel, "sesion",
        {"id_token": "ID", "refresh_token": "RT2", "local_id": "uid1",
         "email": email or "a@b.com", "expira_en": 100},
    )
    monkeypatch.setattr(vfxflow_config, "config_disco_disponible", lambda: True)
    monkeypatch.setattr(
        sesion_vfxflow, "cargar_sesion",
        lambda: {"refresh_token": "RT", "email": "a@b.com"},
    )
    monkeypatch.setattr(
        panel_comentarios.vfxflow_auth, "refrescar_id_token",
        lambda rt: {"id_token": "ID", "refresh_token": "RT2",
                    "expires_in": 3600, "user_id": "uid1"},
    )
    monkeypatch.setattr(
        panel_comentarios.vfxflow_auth, "obtener_usuario",
        lambda uid, tok: {"role": "administrator", "name": "Emanuel Barriga",
                          "avatarUrl": "https://x/a.png"},
    )
    guardadas = []
    monkeypatch.setattr(
        sesion_vfxflow, "guardar_sesion", lambda s: guardadas.append(s) or True
    )

    panel._autologin_si_hay_sesion()

    assert panel.sesion["userName"] == "Emanuel Barriga"
    assert panel.sesion["role"] == "administrator"
    assert panel.sesion["userPhotoURL"] == "https://x/a.png"
    assert any("Reconectado" in e for e in estados)


def test_autologin_no_consulta_usuario_si_ya_tiene_identidad(monkeypatch):
    from SamanTools import panel_comentarios, sesion_vfxflow, vfxflow_config

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    estados = []
    panel._estado = lambda texto, error=False: estados.append(texto)
    panel.sesion = None
    monkeypatch.setattr(vfxflow_config, "config_disco_disponible", lambda: True)
    monkeypatch.setattr(
        sesion_vfxflow, "cargar_sesion",
        lambda: {"refresh_token": "RT", "email": "a@b.com",
                 "userName": "Emanuel Barriga", "role": "admin",
                 "userPhotoURL": "f"},
    )
    monkeypatch.setattr(
        panel_comentarios.vfxflow_auth, "refrescar_id_token",
        lambda rt: {"id_token": "ID", "refresh_token": "RT2",
                    "expires_in": 3600},
    )
    consultado = []
    monkeypatch.setattr(
        panel_comentarios.vfxflow_auth, "obtener_usuario",
        lambda uid, tok: consultado.append(1) or {},
    )
    monkeypatch.setattr(sesion_vfxflow, "guardar_sesion", lambda s: True)

    panel._autologin_si_hay_sesion()

    assert consultado == []  # identidad ya presente: no consultar users/{uid}
    assert panel.sesion["userName"] == "Emanuel Barriga"
    assert any("Reconectado" in e for e in estados)


# ---------------------------------------------------------------------------
# v1.7.2 — clic en miniatura importa; doble clic abre zoom
# ---------------------------------------------------------------------------


def test_clic_importar_adjunto_importa_con_contexto():
    from SamanTools import panel_comentarios

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    panel._adjunto_trabajo_en_curso = False
    llamadas = []
    panel._importar_adjunto = (
        lambda url, nombre, contexto=None: llamadas.append((url, nombre, contexto))
    )
    adj = {"url": "https://x/o/a.jpg?alt=media", "name": "a.jpg"}
    contexto = {"autor": "Ana", "contenido": "mirá", "comentario_id": "c1"}
    objetivo = _BotonSelectorFake()

    ok = panel._clic_importar_adjunto(adj, contexto, objetivo=objetivo)

    assert ok is True
    # El clic dispara la MISMA cadena que el botón ⬇ (Read + Text2 con autor).
    assert llamadas == [("https://x/o/a.jpg?alt=media", "a.jpg", contexto)]
    assert objetivo.habilitado is False
    assert objetivo.texto == "⏳…"
    assert objetivo.tooltip == "Importando…"


def test_clic_importar_adjunto_ignora_en_vuelo():
    from SamanTools import panel_comentarios

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    panel._adjunto_trabajo_en_curso = True
    llamadas = []
    panel._importar_adjunto = (
        lambda url, nombre, contexto=None: llamadas.append((url, nombre))
    )

    ok = panel._clic_importar_adjunto({"url": "u", "name": "n"}, {})

    assert ok is False
    assert llamadas == []  # no disparar dos importaciones a la vez


def test_doble_clic_zoom_adjunto():
    from SamanTools import panel_comentarios

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    llamado = []
    panel._abrir_zoom_imagen = lambda ruta, parent=None: llamado.append(ruta)

    panel._doble_clic_zoom_adjunto("/tmp/x.jpg")

    assert llamado == ["/tmp/x.jpg"]


# ---------------------------------------------------------------------------
# Feed resiliente (una card que falla no corta el feed) + markdown + verbos
# ---------------------------------------------------------------------------


def test_intentar_card_captura_error():
    from SamanTools import panel_comentarios

    ok, err = panel_comentarios._intentar_card(lambda x: x * 2, 21)
    assert ok == 42 and err is None

    def _boom():
        raise ValueError("boom")

    ok2, err2 = panel_comentarios._intentar_card(_boom)
    assert ok2 is None and isinstance(err2, ValueError)


def test_publicar_actividad_continua_con_card_que_falla(monkeypatch):
    from SamanTools import panel_comentarios

    panel = _panel_con_feed_falsa()
    estados = []
    panel._estado = lambda texto, error=False: estados.append(texto)
    fallos = []

    def _crear(actividad, colores_estados=None, imagenes=None, es_respuesta=False):
        if actividad.get("content") == "rota":
            raise ValueError("boom render")
        return actividad

    panel._crear_card_actividad = _crear
    monkeypatch.setattr(
        panel_comentarios,
        "_reportar_card_fallida",
        lambda actividad, error: fallos.append((actividad, error)),
    )

    rota = {"id": "r1", "type": "comment", "content": "rota"}
    bien = {"id": "b1", "type": "comment", "content": "bien"}
    panel._publicar_actividad([rota, bien])

    # La card buena se pinta y el feed termina con el stretch: no corta.
    assert panel._layout_actividad.items == [bien, "stretch"]
    assert len(fallos) == 1 and isinstance(fallos[0][1], ValueError)
    assert any("1 de 2 actividades mostradas (1 con error)" in e for e in estados)


def test_verbo_tipo_alineado_a_plataforma():
    from SamanTools import panel_comentarios

    expected = {
        "comment": "comentó",
        "reply": "respondió",
        "file_upload": "subió una imagen",
        "status_change": "cambió el estado",
        "version_update": "actualizó la versión",
        "task_update": "actualizó la tarea",
        "batch_update": "actualizó el plano",
        "assignment_change": "realizó una acción",
    }
    for tipo, verbo in expected.items():
        assert panel_comentarios._verbo_tipo(tipo) == verbo, tipo
    assert panel_comentarios._verbo_tipo("desconocido") == ""


def test_markdown_bold():
    from SamanTools import panel_comentarios

    assert panel_comentarios._markdown_bold("**Entregado en V1**") == (
        "<b>Entregado en V1</b>"
    )
    assert panel_comentarios._markdown_bold("sin negrita") == "sin negrita"
    # `**` desbalanceado (sin cierre) queda literal y no rompe.
    assert panel_comentarios._markdown_bold("a ** b") == "a ** b"
    assert panel_comentarios._markdown_bold("**solo") == "**solo"
    assert panel_comentarios._markdown_bold("**") == "**"
    assert panel_comentarios._markdown_bold("") == ""


def test_escapar_y_linkificar_markdown_bold_y_urls():
    from SamanTools import panel_comentarios

    salida = panel_comentarios._escapar_y_linkificar(
        "Plano marcado como **Entregado en V1** https://x.example/v1.mov"
    )
    assert "<b>Entregado en V1</b>" in salida
    assert (
        '<a href="https://x.example/v1.mov">https://x.example/v1.mov</a>' in salida
    )
    # El XSS sigue escapado ANTES del bold.
    salida2 = panel_comentarios._escapar_y_linkificar("**<script>alert(1)</script>**")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in salida2
    assert "<b>&lt;script&gt;alert(1)&lt;/script&gt;</b>" in salida2


# ---------------------------------------------------------------------------
# v1.7.2-bis: subida por export del nodo seleccionado (subgrafo Nuke)
# ---------------------------------------------------------------------------


class _KnobExportFake:
    def __init__(self, nombre):
        self.nombre = nombre
        self.valor = None

    def setValue(self, valor):
        self.valor = valor

    def value(self):
        return self.valor


class _NodoExportFake:
    def __init__(self, cls):
        self.cls = cls
        self.inputs = []
        self.knobs = {}

    def setInput(self, indice, nodo):
        self.inputs.append((indice, nodo))

    def __getitem__(self, clave):
        if clave not in self.knobs:
            self.knobs[clave] = _KnobExportFake(clave)
        return self.knobs[clave]


class _NukeExportStub:
    """Stub de `nuke` para el export: nodos, render/execute, delete, select."""

    def __init__(self, render_disponible=True, ocio_disponible=True):
        import types as _types

        self.creados = []
        self.borrados = []
        self.renderes = []
        self.ejecutes = []
        self.selected_nodos = []
        self.root_name = ""
        self.render_disponible = render_disponible
        self.ocio_disponible = ocio_disponible
        self.nodes = _types.SimpleNamespace()
        for cls in ("Dot", "Reformat", "Crop", "OCIODisplay", "Write"):
            setattr(self.nodes, cls, self._factory(cls))
        if render_disponible:
            self.render = self._render
        self.execute = self._execute

    def _factory(self, cls):
        def factory():
            if cls == "OCIODisplay" and not self.ocio_disponible:
                raise RuntimeError("OCIODisplay no disponible")
            nodo = _NodoExportFake(cls)
            self.creados.append(nodo)
            return nodo

        return factory

    def selectedNodes(self):
        return self.selected_nodos

    def root(self):
        import types as _types

        r = _types.SimpleNamespace()
        r.name = lambda: self.root_name
        return r

    def delete(self, nodo):
        self.borrados.append(nodo)

    def _render(self, *args):
        self.renderes.append(args)
        self._escribir_archivo(args[0])

    def _execute(self, *args):
        self.ejecutes.append(args)
        self._escribir_archivo(args[0])

    def _escribir_archivo(self, write):
        with open(write["file"].valor, "wb") as fh:
            fh.write(b"JPGDATA")


def test_nombre_export_jpg():
    from SamanTools import panel_comentarios

    assert panel_comentarios._nombre_export_jpg(
        {"canonico": "HTLR_107_008_00100_V01.nk"}, "202608291230"
    ) == "HTLR_107_008_00100_V01_202608291230.jpg"
    assert panel_comentarios._nombre_export_jpg({}, "202608291230") == (
        "plano_202608291230.jpg"
    )
    assert panel_comentarios._nombre_export_jpg(None, "202608291230") == (
        "plano_202608291230.jpg"
    )


def test_exportar_nodo_jpg_crea_subgrafo_y_limpia(tmp_path, monkeypatch):
    from SamanTools import panel_comentarios

    stub = _NukeExportStub()
    monkeypatch.setattr(panel_comentarios, "nuke", stub)
    ruta = str(tmp_path / "export.jpg")
    entrada = _NodoExportFake("Entrada")

    ok = panel_comentarios._exportar_nodo_jpg(entrada, ruta)

    assert ok is True
    assert os.path.exists(ruta) and os.path.getsize(ruta) > 0
    # Subgrafo creado en orden: Dot, Reformat, Crop, OCIODisplay, Write.
    assert [n.cls for n in stub.creados] == [
        "Dot", "Reformat", "Crop", "OCIODisplay", "Write",
    ]
    dot, reformat, crop, ocio, write = stub.creados
    # Inputs encadenados.
    assert dot.inputs == [(0, entrada)]
    assert reformat.inputs == [(0, dot)]
    assert crop.inputs == [(0, reformat)]
    assert ocio.inputs == [(0, crop)]
    assert write.inputs == [(0, ocio)]
    # Knobs clave.
    assert reformat["format"].valor == "1280 720 0 0 1280 720 1 HD_720"
    assert crop["box"].valor == [0, 0, 1280, 720]
    assert write["file"].valor == ruta
    assert write["file_type"].valor == "jpeg"
    assert write["raw"].valor is True
    assert ocio["display"].valor == "sRGB - Display"
    # Se ejecutó el render del frame 1.
    assert stub.renderes == [(write, 1, 1)]
    # Limpieza SIEMPRE en orden inverso (no dejar basura en el comp).
    assert stub.borrados == list(reversed(stub.creados))


def test_exportar_nodo_jpg_sin_ociodisplay_pasa_a_crop(tmp_path, monkeypatch):
    from SamanTools import panel_comentarios

    stub = _NukeExportStub(ocio_disponible=False)
    monkeypatch.setattr(panel_comentarios, "nuke", stub)
    ruta = str(tmp_path / "export.jpg")
    entrada = _NodoExportFake("Entrada")

    ok = panel_comentarios._exportar_nodo_jpg(entrada, ruta)

    assert ok is True
    # Sin OCIODisplay: 4 nodos, el Write entra por el Crop (RAW).
    assert [n.cls for n in stub.creados] == ["Dot", "Reformat", "Crop", "Write"]
    dot, reformat, crop, write = stub.creados
    assert write.inputs == [(0, crop)]
    assert stub.borrados == list(reversed(stub.creados))


def test_exportar_nodo_jpg_usa_execute_si_no_hay_render(tmp_path, monkeypatch):
    from SamanTools import panel_comentarios

    stub = _NukeExportStub(render_disponible=False)
    monkeypatch.setattr(panel_comentarios, "nuke", stub)
    ruta = str(tmp_path / "export.jpg")
    entrada = _NodoExportFake("Entrada")

    ok = panel_comentarios._exportar_nodo_jpg(entrada, ruta)

    assert ok is True
    assert stub.renderes == []
    assert stub.ejecutes  # cayó al alias viejo nuke.execute
    assert stub.borrados == list(reversed(stub.creados))


def test_on_subir_imagen_sin_nodo_seleccionado(monkeypatch):
    from SamanTools import panel_comentarios

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    panel.sesion = {"email": "a@b.com", "id_token": "IT"}
    panel._id_token_actual = lambda: "TOKEN"
    panel._plano_activo = lambda: {
        "proyecto": "HTLR", "capitulo": 107, "plano": "008_00100",
        "canonico": "HTLR_107_008_00100_V01.nk",
    }
    panel._escritura_trabajo_en_curso = False
    estados = []
    panel._estado = lambda texto, error=False: estados.append(texto)
    stub = _NukeExportStub()
    stub.selected_nodos = []
    monkeypatch.setattr(panel_comentarios, "nuke", stub)
    lanzados = []
    panel._lanzar_escritura = lambda *a, **k: lanzados.append(a)

    panel._on_subir_imagen()

    assert lanzados == []
    assert any("Seleccioná un nodo" in e for e in estados)


def test_on_subir_imagen_exporta_y_lanza(tmp_path, monkeypatch):
    from SamanTools import panel_comentarios

    panel = panel_comentarios.PanelComentarios.__new__(
        panel_comentarios.PanelComentarios
    )
    panel.sesion = {"email": "a@b.com", "local_id": "u", "id_token": "IT"}
    panel._id_token_actual = lambda: "TOKEN"
    panel._plano_activo = lambda: {
        "proyecto": "HTLR", "capitulo": 107, "plano": "008_00100",
        "canonico": "HTLR_107_008_00100_V01.nk",
    }
    panel._escritura_trabajo_en_curso = False
    estados = []
    panel._estado = lambda texto, error=False: estados.append(texto)
    stub = _NukeExportStub()
    stub.selected_nodos = [_NodoExportFake("Sel")]
    stub.root_name = str(tmp_path / "EP_102" / "Carp" / "Carp_V01.nk")
    monkeypatch.setattr(panel_comentarios, "nuke", stub)
    exportado = []

    def _exportar(nodo, ruta):
        exportado.append((nodo, ruta))
        with open(ruta, "wb") as fh:
            fh.write(b"JPG")
        return True

    monkeypatch.setattr(panel_comentarios, "_exportar_nodo_jpg", _exportar)
    lanzados = []
    panel._lanzar_escritura = (
        lambda callable_, args, mensaje: lanzados.append((callable_, args, mensaje))
    )

    panel._on_subir_imagen()

    assert exportado  # exportó el nodo a ref/temp
    ruta_export = exportado[0][1]
    assert ruta_export.endswith(".jpg")
    assert "/ref/temp/" in ruta_export
    assert lanzados and lanzados[0][0] == panel._trabajo_subir_imagen
    jpg, plano, token, nombre, size, sesion = lanzados[0][1]
    assert jpg == ruta_export
    assert nombre.startswith("HTLR_107_008_00100_V01_")