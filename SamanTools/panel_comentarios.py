"""
SamanTools.panel_comentarios - Panel docked "Comentarios por Plano" (v1 login).

Ventana acoplable de Nuke que muestra el contexto del plano activo
(proyecto, capitulo, plano) parseado con `SamanTools.nombres` y permite
iniciar sesion contra VFXFlow (Firebase).

v1 = contexto del plano + login. La logica de auth REST vive en
`vfxflow_auth` (pura, testeable) y la persistencia segura del refresh token
en `sesion_vfxflow`. En v2 este panel leera/escribira comentarios por plano.

Import de PySide con el patron de `frame_manager` (try PySide2, except
PySide6) para mantener compatibilidad entre Nuke 14 y 17.
"""

import os
import time
import webbrowser

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

_ID_PANEL = "pe.saman.vfxflow.comentarios"
_NOMBRE_PANEL = "Comentarios por Plano — SamanTools"

# Sin marca de expiracion en la sesion: se refresca si el archivo se escribio
# hace mas de 50 minutos (el id_token dura 1 hora).
_VENTANA_REFRESH_SEGUNDOS = 50 * 60


class PanelComentarios(QtWidgets.QWidget):
    """Widget docked: contexto del plano activo + login a VFXFlow."""

    def __init__(self, parent=None):
        super(PanelComentarios, self).__init__(parent)
        # Estado de sesion en memoria: id_token/refresh_token/local_id/email
        # (+ expira_en: epoch aproximado de expiracion del id_token).
        self.sesion = None

        self._construir_ui()
        self._mostrar_plano_activo()
        self._autologin_si_hay_sesion()

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

        self._etiqueta_estado = QtWidgets.QLabel(self)
        self._etiqueta_estado.setWordWrap(True)
        layout.addWidget(self._etiqueta_estado)
        layout.addStretch(1)

    def _fila_contexto(self, grilla, fila, nombre):
        grilla.addWidget(QtWidgets.QLabel(nombre), fila, 0)
        valor = QtWidgets.QLabel("—")
        grilla.addWidget(valor, fila, 1)
        return valor

    # ---------------------------------------------------- contexto del plano

    def _mostrar_plano_activo(self):
        """Rellena las etiquetas de contexto desde el comp abierto.

        Sin comp guardado o sin parseo posible => '—'. Nunca lanza.
        """
        try:
            from SamanTools import entorno, nombres

            ruta = nuke.root().name() or ""
            datos = nombres.parsear_plato(ruta) if ruta else None

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
        except vfxflow_auth.VfxFlowAuthError as e:
            self._estado(str(e), error=True)
        except Exception as e:
            self._estado("Error inesperado: %s" % e, error=True)
        finally:
            self._boton_login.setEnabled(True)

    def _on_login_google(self):
        """Arranca el Device Flow de Google sin bloquear la UI de Nuke.

        Deshabilita ambos botones, pide el device_code, muestra la URL y el
        codigo al usuario (y abre el navegador si se puede) y dispara el
        polling con QTimer: un tick cada `interval` ms. El polling NUNCA
        congela Nuke. El refresh_token de Google no se toca ni se guarda.
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
        except vfxflow_auth.VfxFlowAuthError as e:
            self._estado(str(e), error=True)
        except Exception as e:
            self._estado("Error inesperado: %s" % e, error=True)
        finally:
            self._habilitar_botones_login()

    def _habilitar_botones_login(self):
        self._boton_login.setEnabled(True)
        self._boton_google.setEnabled(True)

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

        Ante CUALQUIER fallo borra la sesion y deja que el usuario inicie
        sesion de nuevo. Nunca bloquea la apertura del panel.
        """
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

    # ------------------------------------------------------------ utilidad

    def _estado(self, texto, error=False):
        self._etiqueta_estado.setStyleSheet(
            "color: #c0392b;" if error else ""
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