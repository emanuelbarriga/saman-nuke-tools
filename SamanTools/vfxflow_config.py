"""
SamanTools.vfxflow_config - Config publica del cliente REST de VFXFlow.

VFXFlow es la app web (proyecto Firebase `vfxpm-be912`) que administra los
planos del estudio. Este panel de Nuke se conecta a su backend igual que el
navegador: la config de Firebase de una app web vive en su bundle JS y es
PUBLICA por diseno (modelo de Firebase: la seguridad real la dan las Firebase
Rules + la autenticacion, NO la api key). Por eso estos valores estan
versionados.

    api_key         key de la app Firebase (publica por diseno).
    project_id      id del proyecto Firebase (vfxpm-be912).
    auth_domain     dominio de autenticacion email/password.
    storage_bucket  bucket de almacenamiento (no usado en v1, por completitud).
    google_client_id  client_id OAuth de Google para "Continuar con Google"
                      (Device Flow). Tambien es PUBLICO por diseno: viaja en
                      el bundle JS de cualquier app web y Google lo disena
                      para ser expuesto (el secreto real de una OAuth app es
                      el client_secret, que aca NO se usa). Crearlo en
                      Google Cloud Console > APIs & Services > Credentials >
                      Create Credentials > OAuth client ID > "TVs and Limited
                      Input devices". Se deja vacio hasta que el admin del
                      proyecto lo rellene; el codigo falla con un error claro
                      si falta.

Si algun dia hiciera falta un secreto de SERVICIO, ese va en config_local.py
(ignorado por git), NUNCA aca.
"""

VFXFLOW_CONFIG = {
    "api_key": "AIzaSyARni3zruIfFx7ZTmKq8bDPsCkH6nhP0Bo",
    "project_id": "vfxpm-be912",
    "auth_domain": "vfxpm-be912.firebaseapp.com",
    "storage_bucket": "vfxpm-be912.firebasestorage.app",
    # Rellenar en Google Cloud Console > Credentials > OAuth client ID
    # ("TVs and Limited Input devices"). Publico por diseno (no es secreto).
    "google_client_id": "",
}