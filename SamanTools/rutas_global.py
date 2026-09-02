"""
SamanTools.rutas_global - Config global de rutas VFX (panel docked).

El nodo Rutas legacy guarda rutas POR COMP (knobs que viajan en el .nk);
el panel global guarda la misma config en un JSON y aplica PYTHON_* al
arrancar y al cambiar valores, sin depender de ningún nodo en el graph.

ARQUITECTURA PARA REEMPLAZO:
  - El core de aplicacion es `rutas._aplicar_config(cfg)`: 100% config-driven.
  - El nodo legacy es un ADAPTADOR fino (rutas._aplicar_proyecto_inner) que
    arma el mismo dict desde sus knobs.
  - Para reemplazar el nodo por el panel: eliminar el adaptador y el
    knobChanged del gizmo; el panel y este módulo quedan igual.

Persistencia: JSON atómico (tmp + os.replace), tolerante a archivo corrupto.
"""

import json
import os

from SamanTools import rutas

RUTAS_CONFIG_PATH = os.path.join(
    os.path.expanduser("~"), ".config", "saman", "rutas_global.json"
)

KNOBS_CONFIG = (
    "TO_VFX_SERVER_MAC", "comp_SERVER_MAC", "FROM_VFX_SERVER_MAC",
    "TO_VFX_SERVER_WINDOWS", "comp_SERVER_WINDOWS", "FROM_VFX_SERVER_WINDOWS",
    "TO_VFX_SERVER_ARTIST", "comp_SERVER_ARTIST", "FROM_VFX_SERVER_ARTIST",
)


def config_vacia():
    """Estructura por defecto del config global. Pura."""
    return {
        "usuario_activo": "",
        "proyecto": "",
        "rutas": {k: "" for k in KNOBS_CONFIG},
    }


def cargar_config(ruta=None):
    """Carga el config global; nunca lanza (archivo ausente/corrupto -> vacio)."""
    ruta = ruta or RUTAS_CONFIG_PATH
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            datos = json.load(f)
    except Exception:
        return config_vacia()
    cfg = config_vacia()
    cfg["usuario_activo"] = str(datos.get("usuario_activo") or "")
    cfg["proyecto"] = str(datos.get("proyecto") or "")
    rutas_datos = datos.get("rutas") or {}
    for k in KNOBS_CONFIG:
        cfg["rutas"][k] = str(rutas_datos.get(k) or "")
    return cfg


def guardar_config(cfg, ruta=None):
    """Guarda el config global con escritura atomica (tmp + os.replace).
    Devuelve True si se pudo escribir."""
    ruta = ruta or RUTAS_CONFIG_PATH
    try:
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        tmp = ruta + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        os.replace(tmp, ruta)
        return True
    except Exception:
        return False


def aplicar_global(cfg=None, forzar=False):
    """Aplica la config global: escribe PYTHON_* en __main__ y refresca los
    Reads dinamicos [python ...].

    - forzar=False: recarga SOLO los Reads cuya ruta resuelta cambio.
    - forzar=True: recarga TODOS (boton "Refrescar Fuentes").

    Devuelve True si cargo scripts del proyecto, False si no (o si el
    usuario activo no es valido). Nunca lanza hacia arriba.
    """
    cfg = cfg if cfg is not None else cargar_config()
    reads = rutas._capturar_reads_dinamicos()
    resultado = rutas._aplicar_config(cfg)
    if resultado is None:
        return False
    rutas._re_evaluar_y_recargar(reads, forzar=forzar)
    return bool(resultado)


def cambiar_proyecto_global(cfg, proy):
    """Puro: reescribe el segmento de proyecto en el dict de rutas del config.

    Devuelve (cfg_nuevo, cambios). `cfg` no se muta: si hay cambios se
    devuelve una copia con el proyecto actualizado; si no, la misma config.
    """
    nuevos, cambios = rutas._reescribir_proyecto_en_rutas(cfg.get("rutas") or {}, proy)
    if cambios:
        cfg = dict(cfg)
        cfg["proyecto"] = str(proy)
        cfg["rutas"] = nuevos
    return cfg, cambios


def importar_desde_nodo(cfg, nodo):
    """Vuelca los valores de un nodo Rutas legacy al config global.

    Copia UsuarioActivo + las 9 rutas del nodo (solo knobs existentes).
    Tolerante a None y a nodos sin knobs. Pura en lo posible: el unico
    contacto con Nuke es leer el nodo que recibe.
    """
    nuevo = dict(cfg)
    nuevo["rutas"] = dict(cfg.get("rutas") or {})
    if nodo is None:
        return nuevo
    try:
        if "UsuarioActivo" in nodo.knobs():
            nuevo["usuario_activo"] = str(nodo["UsuarioActivo"].value())
    except Exception:
        pass
    for k in KNOBS_CONFIG:
        try:
            if k in nodo.knobs():
                nuevo["rutas"][k] = str(nodo[k].value())
        except Exception:
            continue
    return nuevo