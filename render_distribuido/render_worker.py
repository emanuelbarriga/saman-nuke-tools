"""Worker remoto de render distribuido (corre dentro de Nuke via -t).

Contrato de sufijos (D6): TO_SUF/COMP_SUF/FROM_SUF se leen SOLO de las
variables de entorno que el orquestador inyecta explicitamente en el argv
remoto (`env KEY='val' ...`). Variable ausente => sufijo vacio (la base sin
subdirectorio). El worker NO hardcodea rutas de estudio.
"""

import json
import os
import sys
import time

import nuke
import __main__

MODE = os.environ.get("MODE", "render")
BASE = os.environ["BASE"]
COMP = os.environ.get("COMP", BASE + "/TEST_RENDER/prueba_test.nk")
WNODE = os.environ.get("WNODE", "Write1")


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
    emitir(
        {
            "wnode_first": w_first,
            "wnode_last": w_last,
            "wnode_file": w_file,
            "plate_first": plate[0] if plate else None,
            "plate_last": plate[1] if plate else None,
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
    lista_render = [x for x in os.environ.get("RENDER_LIST", "").split(",") if x.strip()]
    setear_variables(BASE)
    nuke.scriptOpen(COMP)
    setear_variables(BASE)
    t0 = time.time()
    if lista_render:
        n_frames = ejecutar_frames(WNODE, [int(x) for x in lista_render])
    else:
        nuke.execute(WNODE, first, last)
        n_frames = last - first + 1
    dur = time.time() - t0
    emitir({"render_s": round(dur, 3), "frames": n_frames})