"""plate_qc - Gate QC pre-render (D3/D5/D6 del design render-agente-qc).

Regla de Oro: el nodo de Nuke no se confia ciegamente. Este modulo localiza
el plate (via layouts, fecha mas reciente u override ``--plate-date``),
lo deep-probea con ffprobe (argv-list, salida JSON) y compara contra el Root
del comp y el template de entrega reportados por la PROBE del worker:

- fps plate vs root (24 vs 23.976): discrepancia ERROR, decision bloqueante.
- resolucion plate vs root format: discrepancia ERROR.
- duracion plate (duration x fps redondeado) vs root y nodos: ERROR en nodos
  de entrega, WARNING en previews (drift REC709 EP_108: 1558 vs 1665).
- naming: el id de plano normalizado del plate vs el file de cada nodo de
  entrega; si no empareja => ERROR con decision [Validar solo duracion].

El gate ON por defecto en el flujo asistido reporta (D6: JSON en
TEST_RENDER + resumen stdout) y aborta salvo ``--force-qc``; los caminos
tristes salen como decisiones estructuradas ``__DECISION__`` (D5) que el
agente convierte en pregunta 1-clic; en modo auto el CLI sale con exit code
3 ("necesita decision") tras imprimir el bloque JSON.

Solo stdlib; sin Nuke, sin rutas del estudio (test_no_fuga).
"""

import json
import os
import re
import subprocess
import time

# Roles semanticos fijos (RC-MN-01): los previews solo generan WARNING por
# drift; la reescritura (qc_set) apunta al nodo de entrega EXR.
NODOS_ENTREGA = ("DELIVERY_EXR", "DELIVERY_DWG")
NODOS_PREVIEW = ("REVIEW_REC709", "SBS_REC709")


class ProbeError(Exception):
    """Fallo de ffprobe o de parse: abort nombrando la ruta (RC-QC-02).

    Nunca un default silencioso: el mensaje lleva la ruta del plate y el
    detalle del fallo (returncode, stderr o metadata incompleta).
    """

    def __init__(self, ruta, detalle=""):
        self.ruta = ruta
        self.detalle = detalle
        mensaje = "Probe del plate fallido: %s" % ruta
        if detalle:
            mensaje += " (%s)" % detalle
        super().__init__(mensaje)


# ---------------------------------------------------------------------------
# Parseo de metadata de ffprobe (funciones puras, testables sin Nuke)
# ---------------------------------------------------------------------------


def fps_desde_racional(valor):
    """FPS float desde '24000/1001' (23.976...), '23.976' o 24.

    Cuidado con la precision: 24000/1001 NO es 23.976 exacto; la comparacion
    usa ``fps_comparable`` (redondeo a 3 decimales) para no fabricar falsos
    positivos entre el racional del plate y el float del root de Nuke.
    Devuelve None si el valor no es un fps valido (denominador 0, basura).
    """
    if valor is None:
        return None
    try:
        if isinstance(valor, (int, float)):
            return float(valor)
        texto = str(valor).strip()
        if "/" in texto:
            num, _, den = texto.partition("/")
            num = float(num)
            den = float(den)
            if not den:
                return None
            resultado = num / den
        else:
            resultado = float(texto)
        return resultado if resultado > 0 else None
    except (TypeError, ValueError):
        return None


def fps_comparable(fps):
    """FPS redondeado a 3 decimales para comparar plate vs root (23.976)."""
    val = fps_desde_racional(fps)
    return round(val, 3) if val is not None else None


def frames_desde_duracion(duration, fps):
    """Frames del plate: duracion (s) x fps redondeado (RC-QC-03).

    EP_108: 69.444375 s x 24000/1001 => 1665; el preview REC709 1558 queda
    como drift si el comp renderiza 65 s x 23.976 => 1558.
    """
    dur = float(duration)
    f = fps_desde_racional(fps)
    if dur is None or f is None or dur <= 0 or f <= 0:
        return None
    return int(round(dur * f))


def bit_depth_desde_pix_fmt(pix_fmt):
    """Bit depth desde el pix_fmt de ffprobe: 'yuv444p12le' => 12.

    None si el pix_fmt no declara profundidad (p.ej. 'yuv420p').
    """
    if not pix_fmt:
        return None
    match = re.search(r"p(\d+)le$", str(pix_fmt))
    return int(match.group(1)) if match else None


def parsear_probe(datos, ruta):
    """Convierte el JSON de ffprobe en el dict de plate (RC-QC-02).

    Levanta ProbeError si falta metadata esencial (codec, resolucion, fps,
    duracion) — jamas devuelve un dict con None a medias.
    """
    if not isinstance(datos, dict):
        raise ProbeError(ruta, "salida JSON invalida")
    streams = datos.get("streams") or []
    if not streams:
        raise ProbeError(ruta, "sin stream de video")
    st = streams[0]
    fmt = (datos or {}).get("format") or {}
    codec = st.get("codec_name") or st.get("codec_long_name") or ""
    width = int(st["width"]) if st.get("width") else None
    height = int(st["height"]) if st.get("height") else None
    fps = fps_desde_racional(st.get("r_frame_rate"))
    duration = fmt.get("duration")
    if duration is not None:
        try:
            duration = float(duration)
        except (TypeError, ValueError):
            duration = None
    frames = frames_desde_duracion(duration, fps) if duration is not None else None
    if not codec or not width or not height or fps is None or frames is None:
        raise ProbeError(
            ruta,
            "metadata incompleta (codec=%r %dx%d fps=%r frames=%r)"
            % (codec, width, height, fps, frames),
        )
    return {
        "ruta": ruta,
        "codec": codec,
        "codec_long": st.get("codec_long_name"),
        "bit_depth": bit_depth_desde_pix_fmt(st.get("pix_fmt")),
        "colorspace": st.get("color_space"),
        "width": width,
        "height": height,
        "fps": fps,
        "r_frame_rate": st.get("r_frame_rate"),
        "duration": duration,
        "frames": frames,
    }


def probar_plate(ruta):
    """ffprobe del plate: argv como lista, salida JSON parseada (RC-QC-02).

    Threat matrix 'ffprobe subprocess': jamas shell=True; la ruta viaja como
    elemento del argv (espacios/comillas inertes). Fallo de probe o de parse
    => ProbeError nombrando la ruta (nunca default silencioso).
    """
    argv = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries",
        "stream=codec_name,codec_long_name,pix_fmt,width,height,"
        "r_frame_rate,color_space",
        "-show_entries", "format=duration",
        "-of", "json", ruta,
    ]
    try:
        p = subprocess.run(
            argv, capture_output=True, text=True, timeout=60, shell=False
        )
    except OSError as e:
        raise ProbeError(ruta, "ffprobe no ejecutable (%s)" % e)
    if p.returncode != 0:
        detalle = (p.stderr or p.stdout or "").strip() or "returncode %d" % p.returncode
        raise ProbeError(ruta, detalle)
    try:
        datos = json.loads(p.stdout or "{}")
    except ValueError as e:
        raise ProbeError(ruta, "salida JSON invalida (%s)" % e)
    return parsear_probe(datos, ruta)


# ---------------------------------------------------------------------------
# Naming: id de plano normalizado (empareja plate <-> nodo de entrega)
# ---------------------------------------------------------------------------


def normalizar_id_plano(nombre):
    """Id de plano de un archivo: sin dir, sin ext, sin sufijos del pipeline.

    Quita: el numero de frame/placeholder (``.0100`` / ``.####``), la
    extension, ``_V\\d+`` y ``_comp_SAMAN(_SE)``. El resto es el id que
    empareja el plate con el file del nodo de entrega (RC-QC-03 'Naming
    broken'). Los nombres reales tipo ``HTLR_108_034_V01_0100`` NO se tocan
    (V01_0100 es parte del naming del plano, no un sufijo de pipeline).
    """
    base = os.path.basename(str(nombre))
    sin_ext = re.sub(r"\.[^./\\]+$", "", base)           # .mov / .exr / .nk
    sin_frame = re.sub(r"\.[\d#%]+$", "", sin_ext)       # .0100 / .####
    sin_v = re.sub(r"_V\d+$", "", sin_frame, flags=re.IGNORECASE)
    sin_saman = re.sub(r"_comp_SAMAN(?:_se)?$", "", sin_v, flags=re.IGNORECASE)
    return sin_saman


# ---------------------------------------------------------------------------
# Comparacion plate vs root vs nodos (RC-QC-03): severidad warning|error
# ---------------------------------------------------------------------------


def comparar(plate, root, nodos):
    """Discrepancias plate vs root del comp y vs nodos de la PROBE (RC-QC-03).

    Devuelve una lista de dicts ``{severidad, tipo, nodo, campo, esperado,
    encontrado, decision}``:

    - ``fps`` plate vs root => error (decision bloqueante 'forzar_fps').
    - ``resolucion`` plate vs root format => error.
    - ``duracion`` plate.frames vs rango del root => error; vs rango de cada
      nodo => error en entrega, warning en previews (drift no aborta).
    - ``naming`` id del plate vs file de cada nodo de entrega => error con
      decision 'validar_solo_duracion'.

    Los campos sin dato (root parcial / nodo sin file) no generan ruido.
    """
    disc = []

    root_fps = fps_comparable(root.get("fps")) if root.get("fps") is not None else None
    if root_fps is not None and root_fps != fps_comparable(plate["fps"]):
        disc.append({
            "severidad": "error", "tipo": "fps", "nodo": "root",
            "campo": "fps",
            "esperado": round(float(plate["fps"]), 3),
            "encontrado": float(root["fps"]),
            "decision": "forzar_fps",
        })

    rw, rh = root.get("width"), root.get("height")
    if rw and rh and (int(rw) != plate["width"] or int(rh) != plate["height"]):
        disc.append({
            "severidad": "error", "tipo": "resolucion", "nodo": "root",
            "campo": "format",
            "esperado": "%dx%d" % (plate["width"], plate["height"]),
            "encontrado": "%dx%d" % (int(rw), int(rh)),
            "decision": None,
        })

    root_frames = None
    if root.get("first") is not None and root.get("last") is not None:
        root_frames = int(root["last"]) - int(root["first"]) + 1
    if root_frames is not None and root_frames != plate["frames"]:
        disc.append({
            "severidad": "error", "tipo": "duracion", "nodo": "root",
            "campo": "frames",
            "esperado": plate["frames"], "encontrado": root_frames,
            "decision": None,
        })

    id_plate = normalizar_id_plano(plate.get("ruta") or "")
    for nombre, info in sorted((nodos or {}).items()):
        info = info or {}
        rango = None
        if info.get("first") is not None and info.get("last") is not None:
            rango = int(info["last"]) - int(info["first"]) + 1
        if rango is not None and rango != plate["frames"]:
            severidad = "warning" if nombre in NODOS_PREVIEW else "error"
            disc.append({
                "severidad": severidad, "tipo": "duracion", "nodo": nombre,
                "campo": "frames",
                "esperado": plate["frames"], "encontrado": rango,
                "decision": None,
            })
        if nombre in NODOS_ENTREGA and info.get("file"):
            id_nodo = normalizar_id_plano(info["file"])
            if id_plate and id_nodo != id_plate:
                disc.append({
                    "severidad": "error", "tipo": "naming", "nodo": nombre,
                    "campo": "plano",
                    "esperado": id_plate, "encontrado": id_nodo,
                    "decision": "validar_solo_duracion",
                })
    return disc


# ---------------------------------------------------------------------------
# D3/D5: resolucion del gate (puro) — abort exit 3 vs overrides no interactivos
# ---------------------------------------------------------------------------


def _problema_de(d):
    """Texto humano de una discrepancia para el bloque __DECISION__ (D5)."""
    nodo = d.get("nodo") or "root"
    return "%s (%s): esperado=%s encontrado=%s" % (
        d.get("tipo"), nodo, d.get("esperado"), d.get("encontrado")
    )


def resolver_gate(discrepancias, force_qc=False, validar_solo_duracion=False,
                  fps_forzar=None):
    """Decision del gate sobre las discrepancias (puro, D3/D5).

    - ``force_qc`` => nunca aborta (RC-QC-04): solo reporta.
    - warnings nunca abortan (drift de preview, RC-QC-03).
    - errores bloqueantes => ``{aborta: True, exit: 3, decision: {...}}``
      salvo que un override los resuelva: ``validar_solo_duracion`` (naming
      roto -> [Validar solo duracion]) y ``fps_forzar`` (fps -> [Forzar]).
    - sin errores => ``{aborta: False, exit: 0, decision: None}``.
    """
    errores = [d for d in discrepancias if d.get("severidad") == "error"]
    if not errores or force_qc:
        return {"aborta": False, "exit": 0, "decision": None}
    bloqueantes = []
    for d in errores:
        if d.get("tipo") == "naming" and validar_solo_duracion:
            continue
        if d.get("tipo") == "fps" and fps_forzar:
            continue
        bloqueantes.append(d)
    if not bloqueantes:
        return {"aborta": False, "exit": 0, "decision": None}
    primero = bloqueantes[0]
    if primero["tipo"] == "naming":
        decision = {
            "id": "naming_roto",
            "problema": _problema_de(primero),
            "opciones": ["validar_solo_duracion", "abortar"],
            "default": "abortar",
        }
    elif primero["tipo"] == "fps":
        decision = {
            "id": "fps_mismatch",
            "problema": _problema_de(primero),
            "opciones": ["forzar_fps", "cancelar"],
            "default": "cancelar",
        }
    else:
        decision = {
            "id": "discrepancia_qc",
            "problema": _problema_de(primero),
            "opciones": ["forzar_qc", "cancelar"],
            "default": "cancelar",
        }
    return {"aborta": True, "exit": 3, "decision": decision}


# ---------------------------------------------------------------------------
# D5: decision estructurada (__DECISION__ JSON; auto => None => exit 3)
# ---------------------------------------------------------------------------


def decision(dec_id, problema, opciones, default, imprimir=None, leer=None):
    """Emite ``__DECISION__{...}`` (JSON) y devuelve la eleccion (D5).

    En TTY lee la opcion por stdin; sin TTY (EOFError, modo auto) devuelve
    None y el CLI aborta con exit code 3 para que el agente pregunte y
    re-invoque con el override no interactivo.
    """
    bloque = {
        "id": dec_id,
        "problema": problema,
        "opciones": opciones,
        "default": default,
    }
    if imprimir is None:
        imprimir = print
    imprimir("__DECISION__" + json.dumps(bloque))
    if leer is None:
        leer = input
    try:
        respuesta = leer("  %s (default %s): " % (problema, default)).strip().lower()
    except EOFError:
        return None
    if respuesta in [str(o).lower() for o in opciones]:
        return respuesta
    return default


# ---------------------------------------------------------------------------
# D6: reporte JSON (TEST_RENDER/qc_<proyecto>_<ts>.json) + resumen stdout
# ---------------------------------------------------------------------------


def contenido_reporte(proyecto, planos, plates, discrepancias):
    """Payload del reporte D6 (puro): proyecto/planos/plates/discrepancias."""
    return {
        "proyecto": proyecto,
        "planos": planos,
        "plates": plates,
        "discrepancias": discrepancias,
    }


def ffprobe_reporte(plate):
    """Seccion ffprobe del reporte D6 (codec, bit_depth, colorspace, res...)."""
    return {
        "codec": plate.get("codec"),
        "bit_depth": plate.get("bit_depth"),
        "colorspace": plate.get("colorspace"),
        "res": "%dx%d" % (plate["width"], plate["height"]),
        "fps": round(float(plate["fps"]), 3),
        "frames": plate.get("frames"),
    }


def nombre_reporte(proyecto, t=None):
    """Nombre del reporte: qc_<proyecto>_<YYYYmmdd_HHMMSS>.json (D6)."""
    ts = time.strftime("%Y%m%d_%H%M%S", t or time.localtime())
    return "qc_%s_%s.json" % (proyecto, ts)


def reportar(destino_dir, payload):
    """Escribe el reporte JSON en destino (relativo a la base) y devuelve ruta.

    Convencion D6: TEST_RENDER/qc_<proyecto>_<ts>.json (misma carpeta que los
    calib_<worker>/ de CALIB). Crea el directorio si hace falta.
    """
    os.makedirs(destino_dir, exist_ok=True)
    ruta = os.path.join(destino_dir, nombre_reporte(payload.get("proyecto", "qc")))
    with open(ruta, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=True, indent=2)
    return ruta


def resumen_reporte(payload):
    """Resumen en stdout del reporte: severidad/tipo/campo esperado/encontrado."""
    disc = payload.get("discrepancias") or []
    lineas = [
        "== REPORTE QC ==",
        "  Proyecto: %s | %d plate(s) localizado(s) | %d discrepancia(s)"
        % (payload.get("proyecto"), len(payload.get("plates") or []), len(disc)),
    ]
    for d in disc:
        lineas.append(
            "  [%s] %s (%s): esperado=%s encontrado=%s"
            % (d.get("severidad"), d.get("tipo"), d.get("nodo") or "root",
               d.get("esperado"), d.get("encontrado"))
        )
    return "\n".join(lineas)


# ---------------------------------------------------------------------------
# D3/D6: QC_SET para reescribir el nodo delivery a las specs del plate
# ---------------------------------------------------------------------------


def spec_qc_set(plate, pr, fps_diana=None):
    """QC_SET del nodo DELIVERY_EXR: fps/format/duracion del plate (D3).

    Regla de Oro: el Write no se confia ciegamente; el worker mode qc_set
    aplica estas specs antes del render. El rango usa plate_first/last de la
    PROBE (autoridad del proyecto) o cae a 1..frames; fps_diana (--fps-forzar)
    domina sobre el fps del plate.
    """
    primero = pr.get("plate_first")
    ultimo = pr.get("plate_last")
    if primero is None or ultimo is None:
        primero, ultimo = 1, plate["frames"]
    fps = fps_desde_racional(fps_diana) if fps_diana else plate["fps"]
    return {
        "DELIVERY_EXR": {
            "fps": round(float(fps), 3),
            "format": "%dx%d" % (plate["width"], plate["height"]),
            "first": int(primero),
            "last": int(ultimo),
        }
    }