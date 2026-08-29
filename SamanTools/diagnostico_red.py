"""
SamanTools.diagnostico_red - Diagnostico de conectividad para el login VFXFlow.

Uso desde el Script Editor de Nuke:

    from SamanTools import diagnostico_red
    diagnostico_red.ejecutar()

Prueba cada dominio que necesita el panel con timeout corto y muestra la
EXCEPCION real (clase + mensaje), ademas de si se detecto proxy. Eso permite
distinguir: DNS roto, conexion rechazada (firewall), timeout (red que deja
caer paquetes), error SSL, o proxy no encontrado.

No modifica nada y nunca lanza hacia afuera: imprime resultados.
"""

import os
import platform
import sys
import urllib.error
import urllib.request

# Dominios que el panel necesita (orden de uso).
DOMINIOS = (
    "https://oauth2.googleapis.com/token",
    "https://identitytoolkit.googleapis.com/",
    "https://securetoken.googleapis.com/",
    "https://firestore.googleapis.com/",
    "https://accounts.google.com/",
)

TIMEOUT_SEGUNDOS = 5


def _probar_url(url):
    """Devuelve (ok, detalle). ok=True si responde HTTP; detalle es texto."""
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SEGUNDOS) as respuesta:
            return True, "HTTP %s" % respuesta.status
    except urllib.error.HTTPError as e:
        # 4xx/5xx = llego al servidor (red OK) pero la URL dio error HTTP.
        return True, "HTTPError %s" % e.code
    except urllib.error.URLError as e:
        return False, "URLError: %r" % (e.reason,)
    except Exception as e:  # socket.timeout y otros
        return False, "%s: %r" % (type(e).__name__, e)


def _proxy_detectado():
    """Devuelve el proxy que usaria el panel (str) o texto de 'no hay'."""
    try:
        from SamanTools import vfxflow_auth

        return vfxflow_auth._proxy_configurado()
    except Exception as e:
        return "ERROR al detectar proxy: %r" % e


def ejecutar():
    """Imprime el diagnostico completo."""
    print("=" * 60)
    print("Diagnostico de red VFXFlow")
    print("Python :", sys.version.split()[0])
    print("SO     :", platform.system(), platform.release())
    print("Proxy env:", {k: v for k, v in os.environ.items() if "proxy" in k.lower()})
    print("Proxy detectado por el panel:", _proxy_detectado())
    print("-" * 60)
    for url in DOMINIOS:
        ok, detalle = _probar_url(url)
        marca = "OK " if ok else "FAIL"
        print("%s  %-55s %s" % (marca, url, detalle))
    print("=" * 60)
    print(
        "- FAIL con 'Connection refused'/'Network is unreachable' => firewall/red"
        "\n  o regla del firewall de Nuke todavia bloqueando."
        "\n- FAIL con timeout (cuelga 5s) => la red deja caer paquetes sin RST."
        "\n- FAIL con 'Name or service not known'/'socket.gaierror' => DNS."
        "\n- Proxy detectado = None pero el navegador SI llega => proxy del sistema"
        "\n  que urllib no usa; define VFXFLOW_LOCAL_CONFIG['proxy'] en config_local."
    )


if __name__ == "__main__":
    ejecutar()