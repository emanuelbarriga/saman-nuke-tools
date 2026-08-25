"""
menu.py — Bootstrap de SamanTools para Nuke (multiplataforma).

Estilos de despliegue soportados por este archivo:

  A) Copiar este menu.py (y SamanTools/) a ~/.nuke  -> funciona tal cual.
  B) Clonar el repo en cualquier carpeta y setear
     NUKE_PATH=<carpeta del repo> en las variables de entorno del usuario.
     Este menu.py detecta su propia ubicacion y carga el paquete desde ahi,
     sin hardcodear rutas absolutas ni depender del OS.

No modifiques rutas absolutas aqui: el repo se resuelve con __file__.
"""

import nuke
import os
import sys
import traceback

# Carpeta donde vive este menu.py (la raiz del repo o ~/.nuke).
REPO_DIR = os.path.dirname(os.path.abspath(__file__))

# El paquete SamanTools vive en <REPO_DIR>/SamanTools (y tambien en el
# plugin path de nodos para que nuke.createNode encuentre los .gizmo).
if REPO_DIR not in sys.path:
    sys.path.append(REPO_DIR)

# Exponer los nodos (Breakdown.gizmo, Review.gizmo, Rutas.*) para que
# nuke.createNode('Breakdown') los encuentre en el buscador TAB.
NODOS_DIR = os.path.join(REPO_DIR, "SamanTools", "nodos")
if os.path.isdir(NODOS_DIR):
    nuke.pluginAddPath(NODOS_DIR, addToMenuBar=False)

try:
    from SamanTools.registro import instalar
    instalar()

except Exception:
    if nuke.GUI:
        nuke.message(
            "ATENCIÓN: Error al cargar SamanTools:\n\n%s" % traceback.format_exc()
        )
    else:
        traceback.print_exc()
