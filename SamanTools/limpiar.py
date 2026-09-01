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

La sanitizacion de archivos es SEGURA y nunca corrompe: se lee en BYTES, se
conserva el BOM UTF-8 y los saltos de linea CRLF, se recodifica con el MISMO
encoding usado al decodificar (utf-8 o latin-1, que es 1:1 byte<->codepoint) y
se reescribe de forma ATOMICA (temporal en el mismo directorio + os.replace).
`sanitizar_carpeta` extiende esa seguridad a arboles enteros de carpetas,
procesando cada archivo en su propio try/except y devolviendo un resumen.
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

    Seguridad a prueba de corrupcion:
      - Lee el archivo en BYTES y conserva el BOM UTF-8 si lo trae.
      - Decodifica con utf-8 y, si falla, con latin-1 (1:1 byte<->codepoint),
        asi el contenido NO UTF-8 se conserva intacto al recodificar.
      - Reescritura ATOMICA: escribe a un temporal en el MISMO directorio y
        hace os.replace() solo si todo salio bien; ante cualquier error de
        escritura el original queda INTACTO.

    Devuelve 1 si el texto cambio, 0 si no (en ese caso NO reescribe y no crea
    temporal). Es idempotente: aplicar dos veces da el mismo resultado.

    Si el archivo no existe o no se puede leer, deja propagar el OSError: el
    caller dentro de Nuke (registro.py) lo atrapa y avisa.
    """
    with open(ruta, "rb") as f:
        raw = f.read()

    bom = b""
    if raw.startswith(b"\xef\xbb\xbf"):
        bom = b"\xef\xbb\xbf"
        raw = raw[3:]

    encoding = "utf-8"
    try:
        contenido = raw.decode("utf-8")
    except UnicodeDecodeError:
        encoding = "latin-1"
        contenido = raw.decode("latin-1")

    limpio = sanitizar_texto_nk(contenido)
    if limpio == contenido:
        return 0

    salida = bom + limpio.encode(encoding)

    tmp = ruta + ".limpiar_tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(salida)
        os.replace(tmp, ruta)
    finally:
        # Si algo fallo (permisos, disco lleno, os.replace), el original queda
        # intacto y el temporal se limpia; el OSError se propaga al caller.
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    return 1


def sanitizar_carpeta(ruta, extensiones=(".nk", ".gizmo")):
    """Limpia recursivamente .nk/.gizmo de una carpeta (seguro).

    Recorre os.walk SIN seguir symlinks (default). Solo toca archivos cuya
    extension (case-insensitive) este en `extensiones`. Devuelve un dict:
        {"limpiados": int, "sin_cambios": int, "errores": [(ruta, str)]}
    Nunca lanza: cada archivo se procesa en su propio try/except (tambien
    contrapermisos leidos como errores con ruta + mensaje).
    """
    extensiones = tuple(ext.lower() for ext in extensiones)
    limpiados = 0
    sin_cambios = 0
    errores = []
    for raiz, directorios, archivos in os.walk(ruta):
        # No se siguen symlinks: no descender en enlaces de directorios.
        directorios[:] = [d for d in directorios if not os.path.islink(os.path.join(raiz, d))]
        for nombre in archivos:
            if not nombre.lower().endswith(extensiones):
                continue
            archivo = os.path.join(raiz, nombre)
            try:
                resultado = sanitizar_archivo(archivo)
            except OSError as e:
                errores.append((archivo, str(e)))
                continue
            if resultado == 1:
                limpiados += 1
            else:
                sin_cambios += 1
    return {"limpiados": limpiados, "sin_cambios": sin_cambios, "errores": errores}