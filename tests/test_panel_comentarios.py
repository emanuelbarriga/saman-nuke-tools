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
    p._crear_card_actividad = lambda actividad: actividad
    p._limpiar_feed = _limpiar
    return p


class _ThreadFake:
    """Reemplaza `threading.Thread`: `start()` corre el target sincrónico."""

    def __init__(self, target, args=(), daemon=None):
        self._target = target
        self._args = args

    def start(self):
        self._target(*self._args)


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