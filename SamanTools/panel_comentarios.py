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
import threading
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
from . import vfxflow_config

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