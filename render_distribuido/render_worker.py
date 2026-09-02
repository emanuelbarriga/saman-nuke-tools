"""Worker remoto de render distribuido (corre dentro de Nuke via -t).

Contrato de sufijos (D6): TO_SUF/COMP_SUF/FROM_SUF se leen SOLO de las
variables de entorno que el orquestador inyecta explicitamente en el argv
remoto (`env KEY='val' ...`). Variable ausente => sufijo vacio (la base sin
subdirectorio). El worker NO hardcodea rutas de estudio.
"""

import json
import os
import re
import sys
import time

import nuke
import __main__

MODE = os.environ.get("MODE", "render")
BASE = os.environ["BASE"]
COMP = os.environ.get("COMP", BASE + "/TEST_RENDER/prueba_test.nk")
WNODE = os.environ.get("WNODE", "Write1")

# Nombres REALES de Write del comp (RC-MN-01): jamas labels friendly
# ("delivery"/"preview"/"side by side") como nombres de nodo.
NODOS_RENDER = ("DELIVERY_EXR", "DELIVERY_DWG", "REVIEW_REC709", "SBS_REC709")


def sufijos_desde_env(env):
    """Sufijos TO_VFX/COMP/FROM_VFX SOLO desde env (sin fallbacks de estudio).

    `env` es el mapping de variables de entorno (os.environ en runtime).
    Devuelve un dict con las tres claves; variable ausente => sufijo vacio
    (base sin subdirectorio). Nunca rutas hardcodeadas de estudio.
    """
    return {
        "TO_SUF": env.get("TO_SUF", ""),
        "COMP_SUF": env.get("COMP_SUF", ""),
        "FROM_SUF": env.get("FROM_SUF", ""),
    }


def setear_variables(base):
    sufijos = sufijos_desde_env(os.environ)
    __main__.PYTHON_TO_VFX = base + sufijos["TO_SUF"]
    __main__.PYTHON_COMP = base + sufijos["COMP_SUF"]
    __main__.PYTHON_FROM_VFX = base + sufijos["FROM_SUF"]
    for var in ("PYTHON_TO_VFX", "PYTHON_COMP", "PYTHON_FROM_VFX"):
        try:
            nuke.tcl("set", var, getattr(__main__, var))
        except Exception:
            pass


def lotes_contiguos(lista):
    """[(a, b), ...] de rangos contiguos a partir de una lista de frames."""
    lotes = []
    if not lista:
        return lotes
    lista = sorted(set(int(x) for x in lista))
    a = b = lista[0]
    for n in lista[1:]:
        if n == b + 1:
            b = n
        else:
            lotes.append((a, b))
            a = b = n
    lotes.append((a, b))
    return lotes


def ejecutar_frames(wnode, lista):
    """Ejecuta por rangos contiguos (nuke.execute no acepta listas sueltas)."""
    total = 0
    for a, b in lotes_contiguos(lista):
        nuke.execute(wnode, a, b)
        total += b - a + 1
    return total


def emitir(datos):
    # Linea JSON unica y facil de parsear (el banner de Nuke va antes).
    print("__WORKER__" + json.dumps(datos), flush=True)


def perf_nodo(nombre):
    """performanceInfo() oficial de Nuke: {callCount, timeTakenCPU, timeTakenWall} us."""
    try:
        n = nuke.toNode(nombre)
        if n is None:
            return None
        info = n.performanceInfo(nuke.PROFILE_ENGINE)
        if not info or not info.get("callCount"):
            return None
        return {
            "callCount": info.get("callCount"),
            "wall_ms": round(info.get("timeTakenWall", 0) / 1000.0, 2),
        }
    except Exception as e:
        return {"error": str(e)}


def rango_plate():
    """Rango de frames del Read conectado al stamp/anchor llamado 'PLATE'.

    El render final debe usar los frames del proyecto: los del material
    (plate) que el estudio pide intervenir. Se busca el anchor (NoOp con knob
    title == 'PLATE'), se sigue input(0) hacia atras hasta el primer Read y se
    devuelve (first, last). None si no se encuentra.
    """
    try:
        candidato = nuke.toNode("PLATE")
        if candidato is None:
            for nodo in nuke.allNodes():
                try:
                    if "title" in nodo.knobs() and str(nodo["title"].value()) == "PLATE":
                        candidato = nodo
                        break
                except Exception:
                    continue
        if candidato is None:
            return None
        visto = set()
        n = candidato
        while n is not None and n.Class() != "Read" and id(n) not in visto:
            visto.add(id(n))
            try:
                n = n.input(0)
            except Exception:
                n = None
        if n is None or n.Class() != "Read":
            return None
        first = int(n["first"].value())
        last = int(n["last"].value())
        return first, last
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Multi-nodo (D4, RC-MN-01/02/03): descubrimiento de Write reales por nombre
# ---------------------------------------------------------------------------


def file_type_de(nodo, file_val=None):
    """Tipo de archivo de un Write: knob file_type si existe, o extension.

    La extension del file evaluado es el fallback (``.exr`` => exr, ``.mov``
    => mov); un .mov con digitos en el nombre sigue siendo mov (threat
    'Output existence classification': no confundir con secuencia EXR).
    """
    try:
        if "file_type" in nodo.knobs():
            tipo = nodo["file_type"].value()
            if tipo:
                return str(tipo)
    except Exception:
        pass
    if file_val is None:
        try:
            file_val = nodo["file"].getEvaluatedValue()
        except Exception:
            file_val = None
    if file_val:
        ext = os.path.splitext(file_val)[1].lower()
        if ext == ".exr":
            return "exr"
        if ext in (".mov", ".mp4"):
            return "mov"
        return ext.lstrip(".") or None
    return None


def info_nodo(nombre, nodo):
    """{first, last, use_limit, file, file_type} de un Write (D6, RC-MN-01).

    None si los knobs de rango no son legibles. ``use_limit`` es el knob
    real del Write: cuando esta activo, el nodo confina su propio rango.
    """
    try:
        use_limit = bool(nodo["use_limit"].value()) if "use_limit" in nodo.knobs() else False
        first = int(nodo["first"].value())
        last = int(nodo["last"].value())
    except Exception:
        return None
    try:
        file_val = nodo["file"].getEvaluatedValue()
    except Exception:
        file_val = None
    return {
        "first": first,
        "last": last,
        "use_limit": use_limit,
        "file": file_val,
        "file_type": file_type_de(nodo, file_val),
    }


def scan_write_nodes():
    """Descubre los Write reales del comp entre los nombres de NODOS_RENDER.

    Nombre -> info; solo los presentes en el comp (los ausentes no aparecen).
    Orden deterministico (alfabetico) para payloads estables.
    """
    resultado = {}
    for nombre in sorted(NODOS_RENDER):
        nodo = nuke.toNode(nombre)
        if nodo is None:
            continue
        info = info_nodo(nombre, nodo)
        if info is not None:
            resultado[nombre] = info
    return resultado


def forzar_exr_en(nodo):
    """--force-exr: reescribe un Write a secuencia EXR ####.exr (RC-MN-03).

    Conserva la duracion (first/last del nodo intactos) y la resolucion (el
    formato del Write intacto): solo se tocan los knobs file y file_type.
    Ya es EXR o secuencia => no-op (devuelve False).
    """
    try:
        if nodo is None:
            return False
        actual = nodo["file"].getEvaluatedValue()
        if not actual:
            return False
        if actual.endswith(".exr") or "#" in actual or "%0" in actual:
            return False
        base = os.path.splitext(actual)[0]
        nodo["file"].setValue(base + ".####.exr")
        if "file_type" in nodo.knobs():
            nodo["file_type"].setValue("exr")
        return True
    except Exception:
        return False


def _parsear_piggyback(valor):
    """'NAME:first:last,NAME2' -> [(nombre, first, last | None)].

    Formato del env PIGGYBACK (D6): previews que viajan en el mismo batch
    del delivery; ``NAME:first:last`` lleva el rango propio del preview
    (use_limit), ``NAME`` solo se ejecuta con los rangos del batch.
    """
    resultado = []
    for frag in (valor or "").split(","):
        frag = frag.strip()
        if not frag:
            continue
        partes = frag.split(":")
        if len(partes) == 3:
            try:
                resultado.append((partes[0], int(partes[1]), int(partes[2])))
                continue
            except ValueError:
                pass
        resultado.append((partes[0], None, None))
    return resultado


def _clip(lista, primero, ultimo):
    """Frames de la lista dentro del rango [primero..ultimo] (piggyback)."""
    return [x for x in lista if primero <= x <= ultimo]


def _root_info():
    """(fps, first, last, w, h) del root; None por campo si no es legible (D6)."""
    try:
        root = nuke.root()
        fps = float(root["fps"].value())
        first = int(root["first_frame"].value())
        last = int(root["last_frame"].value())
        partes = re.split(r"\s+", str(root["format"].value()).strip())
        w = int(partes[0]) if partes and partes[0].isdigit() else None
        h = int(partes[1]) if len(partes) > 1 and partes[1].isdigit() else None
        return fps, first, last, w, h
    except Exception:
        return None, None, None, None, None


if MODE == "probe":
    setear_variables(BASE)
    nuke.scriptOpen(COMP)
    setear_variables(BASE)
    wnode = nuke.toNode(WNODE)
    try:
        w_first = int(wnode["first"].value()) if wnode else None
        w_last = int(wnode["last"].value()) if wnode else None
    except Exception:
        w_first = w_last = None
    try:
        w_file = wnode["file"].getEvaluatedValue() if wnode else None
    except Exception:
        w_file = None
    plate = rango_plate()
    root_fps, root_first, root_last, root_w, root_h = _root_info()
    emitir(
        {
            "wnode_first": w_first,
            "wnode_last": w_last,
            "wnode_file": w_file,
            "plate_first": plate[0] if plate else None,
            "plate_last": plate[1] if plate else None,
            "root_fps": root_fps,
            "root_first": root_first,
            "root_last": root_last,
            "root_w": root_w,
            "root_h": root_h,
            "nodes": scan_write_nodes(),
        }
    )
    raise SystemExit

elif MODE == "calib":
    frames = int(os.environ.get("CALIB_FRAMES", "5"))
    lista_frames = os.environ.get("CALIB_LIST", "")
    try:
        nuke.startPerformanceTimers()
    except Exception:
        pass

    setear_variables(BASE)          # antes de abrir: Reads del comp resuelven bien
    t0 = time.time()
    nuke.scriptOpen(COMP)
    setear_variables(BASE)          # despues: gana sobre el knobChanged del nodo Rutas
    t_load = time.time() - t0

    wnode = nuke.toNode(WNODE)
    try:
        w_first = int(wnode["first"].value()) if wnode else None
        w_last = int(wnode["last"].value()) if wnode else None
    except Exception:
        w_first = w_last = None

    plate = rango_plate()
    p_first = plate[0] if plate else None
    p_last = plate[1] if plate else None

    t0 = time.time()
    if lista_frames:
        total_render = time.time() - t0
        n_muestra = 0
        t0 = time.time()
        n_muestra = ejecutar_frames(WNODE, [int(x) for x in lista_frames.split(",") if x.strip()])
        total_render = time.time() - t0
    else:
        nuke.execute(WNODE, 1, frames)
        total_render = time.time() - t0
        n_muestra = frames

    emitir(
        {
            "load_s": round(t_load, 3),
            "per_frame_s": round(total_render / n_muestra, 4),
            "frames_calib": n_muestra,
            "wnode_first": w_first,
            "wnode_last": w_last,
            "plate_first": p_first,
            "plate_last": p_last,
            "perf_write": perf_nodo(WNODE),
            "perf_read": perf_nodo("Read1"),
        }
    )
elif MODE == "check":
    # Valida profundamente frames EXR existentes: Read + execute 1 frame.
    lista = [x for x in os.environ.get("CHECK_LIST", "").split(",") if x.strip()]
    resultados = {}
    for path in lista:
        try:
            r = nuke.createNode("Read")
            r["file"].setValue(path)
            r["first"].setValue(1)
            r["last"].setValue(1)
            nuke.execute(r, 1, 1)
            resultados[path] = "ok"
            nuke.delete(r)
        except Exception as e:
            resultados[path] = "corrupto: %s" % e
            try:
                nuke.delete(r)
            except Exception:
                pass
    emitir({"check": resultados})
    raise SystemExit

else:
    first = int(os.environ.get("FIRST", "1"))
    last = int(os.environ.get("LAST", "1"))
    lista_render = [int(x) for x in os.environ.get("RENDER_LIST", "").split(",") if x.strip()]
    nodos = [x for x in os.environ.get("WNODES", "").split(",") if x.strip()] or [WNODE]
    piggybacks = _parsear_piggyback(os.environ.get("PIGGYBACK", ""))
    setear_variables(BASE)
    nuke.scriptOpen(COMP)
    setear_variables(BASE)
    t0 = time.time()
    total = 0
    for nodo in nodos:
        if os.environ.get("FORCE_EXR"):
            forzar_exr_en(nuke.toNode(nodo))
        if lista_render:
            total += ejecutar_frames(nodo, lista_render)
        else:
            nuke.execute(nodo, first, last)
            total += last - first + 1
    for pn, pfirst, plast in piggybacks:
        # Previews piggyback: mismo batch que el delivery, con su rango propio
        # (use_limit) recortado al rango de este worker (D4, RC-MN-02).
        if pfirst is not None:
            if lista_render:
                total += ejecutar_frames(pn, _clip(lista_render, pfirst, plast))
            else:
                total += ejecutar_frames(
                    pn, _clip(list(range(first, last + 1)), pfirst, plast)
                )
        elif lista_render:
            total += ejecutar_frames(pn, lista_render)
        else:
            nuke.execute(pn, first, last)
            total += last - first + 1
    dur = time.time() - t0
    emitir({"render_s": round(dur, 3), "frames": total})