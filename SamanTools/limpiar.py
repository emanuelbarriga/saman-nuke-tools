"""
SamanTools.limpiar — Sanitizador de texto .nk/.gizmo.

Elimina knobs VOLATILES de maquina que Nuke serializa en los archivos .nk y
.gizmo y que NO deberian viajar en comps compartidos ni versionados:

  - mov64_prraw_plugin <valor>: el knob solo existe si el decoder PRRAW
    (plugin propietario) esta instalado en esa maquina.
  - render_settings_schema <valor>: solo existe en versiones recientes de Nuke.
  - monitorOutNDISenderName "...": fuga de sesion del artista (salida NDI);
    es unico de cada maquina.

El formato texto de Nuke guarda los knobs en lineas separadas (knob + valor).
Al abrir el archivo en otra maquina sin el plugin (o con Nuke mas viejo),
Nuke avisa "no such knob" y el VALOR del knob inexistente (p.ej. `Standard`,
`false`) se reinterpreta como otro knob, duplicando la alerta. Este modulo
limpia esas lineas del archivo serializado SIN tocar la escena en memoria.

Es un modulo PURO (solo stdlib: os, re). NO importa `nuke` para poder
testearse con pytest fuera de Nuke y usarse tambien desde CLIs o el generador
de galerias. El caller de Nuke (registro.py) atrapa los OSError.
"""

import os
import re

PATRONES_BASURA = [
    re.compile(r"^\s*mov64_prraw_plugin\s+.*$\n?", re.MULTILINE),
    re.compile(r"^\s*render_settings_schema\s+.*$\n?", re.MULTILINE),
    re.compile(r"^\s*monitorOutNDISenderName\s+.*$\n?", re.MULTILINE),
]


def sanitizar_texto_nk(contenido: str) -> str:
    """Aplica los patrones de knobs volatiles a un texto .nk/.gizmo.

    Un patron por pasada con re.MULTILINE: elimina la linea completa del knob
    (con su salto de linea opcional) sin tocar lineas legitimas (p.ej.
    `colorspace DaVinci Intermediate WideGamut` se conserva intacta).
    """
    for patron in PATRONES_BASURA:
        contenido = patron.sub("", contenido)
    return contenido


def sanitizar_archivo(ruta: str) -> int:
    """Sanitiza un archivo .nk/.gizmo en disco; devuelve 1 si cambio, 0 si no.

    Lee el archivo con encoding="utf-8". Si el texto saneado difiere del
    original, lo reescribe (mismo encoding, conservando el salto de linea
    final tal cual estaba) y devuelve 1. Si no cambio, NO reescribe y
    devuelve 0. Es idempotente: aplicar dos veces da el mismo resultado.

    Si el archivo no existe o no se puede leer/escribir, deja propagar el
    OSError: el caller dentro de Nuke (registro.py) lo atrapa y avisa.
    """
    with open(ruta, encoding="utf-8") as f:
        original = f.read()
    limpio = sanitizar_texto_nk(original)
    if limpio == original:
        return 0
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(limpio)
    return 1