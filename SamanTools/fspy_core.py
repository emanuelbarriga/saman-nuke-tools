"""Lector de proyectos .fspy y matemática de cámara. NO importa nuke.

Formato (spec oficial, stuffmatic/fSpy project_file_format.md):
    uint8[4]  b"fspy"   uint32 version   uint32 state_size   uint32 image_size
    state_size bytes de JSON   image_size bytes de imagen
Todo uint32 little endian. Verificado contra example.fspy (16+2973+6517301 = 6520290).
"""
import json
import math
import struct

FILE_ID = b"fspy"
SUPPORTED_VERSION = 1


def read(path):
    """Devuelve un dict con lo que Nuke necesita. Lanza ValueError si el archivo no es .fspy v1."""
    with open(path, "rb") as fh:
        head = fh.read(16)
        if len(head) < 16:
            raise ValueError(f"{path}: demasiado corto para ser un .fspy")
        file_id, version, state_size, image_size = struct.unpack("<4sIII", head)
        if file_id != FILE_ID:
            raise ValueError(f"{path}: no empieza con 'fspy' ({file_id!r})")
        if version != SUPPORTED_VERSION:
            raise ValueError(f"{path}: versión {version} no soportada (solo {SUPPORTED_VERSION})")
        raw = fh.read(state_size)
        if len(raw) != state_size:
            raise ValueError(f"{path}: estado truncado ({len(raw)} de {state_size} bytes)")
    state = json.loads(raw)
    cam = state.get("cameraParameters")
    if not cam:
        raise ValueError(
            f"{path}: el proyecto no tiene solución de cámara "
            "(los puntos de fuga son inválidos o el proyecto está a medio calibrar)"
        )

    cal = state["calibrationSettingsBase"]
    camdata = cal["cameraData"]
    sensor_w, sensor_h = _sensor_size(camdata)

    f_rel = float(cam["relativeFocalLength"])
    width, height = int(cam["imageWidth"]), int(cam["imageHeight"])
    pp = cam["principalPoint"]

    view_t = _rows(cam["viewTransform"])
    cam_t = _rows(cam["cameraTransform"])

    return {
        "path": path,
        "version": version,
        "state_size": state_size,
        "image_size": image_size,
        "mode": state["globalSettings"]["calibrationMode"],
        "width": width,
        "height": height,
        "aspect": width / float(height),
        "f_rel": f_rel,
        "focal_mm": f_rel * sensor_w / 2.0,
        "fov_h_deg": math.degrees(2.0 * math.atan(1.0 / f_rel)),
        "fov_v_deg": math.degrees(2.0 * math.atan(1.0 / (f_rel * width / float(height)))),
        "sensor_w_mm": sensor_w,
        "sensor_h_mm": sensor_h,
        "principal_point": (float(pp["x"]), float(pp["y"])),
        "view_transform": view_t,
        "camera_transform": cam_t,
        "camera_position": (cam_t[0][3], cam_t[1][3], cam_t[2][3]),
        "reference_distance": float(cal.get("referenceDistance") or 0.0),
        "reference_unit": cal.get("referenceDistanceUnit") or "",
        # el origen del mundo expresado en espacio de cámara: T_view * (0,0,0,1)
        "world_origin_in_camera": (view_t[0][3], view_t[1][3], view_t[2][3]),
        "scale": _length((view_t[0][3], view_t[1][3], view_t[2][3])) / max(f_rel, 1e-9),
        "vanishing_points": [(float(v["x"]), float(v["y"])) for v in cam["vanishingPoints"]],
        "state": state,
    }


def _sensor_size(camdata):
    """Preset si hay presetId con datos; si no, los valores custom. Offsets en mm."""
    preset = camdata.get("presetData") or {}
    if camdata.get("presetId") and preset.get("sensorWidth"):
        return float(preset["sensorWidth"]), float(preset.get("sensorHeight") or 0.0)
    return float(camdata.get("customSensorWidth") or 36.0), float(
        camdata.get("customSensorHeight") or 24.0
    )


MAGIAS_IMAGEN = (
    (b"\xff\xd8\xff", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"GIF8", ".gif"),
    (b"II*\x00", ".tif"),
    (b"MM\x00*", ".tif"),
    (b"RIFF", ".webp"),
)


def extension_imagen(cabecera):
    """Extensión según la cabecera del blob. '' si no se reconoce."""
    for magia, extension in MAGIAS_IMAGEN:
        if cabecera.startswith(magia):
            return extension
    return ""


def extraer_imagen(cam, carpeta):
    """Escribe la imagen embebida en `carpeta` y devuelve su ruta.

    El .fspy no guarda una ruta a la foto: la lleva adentro. Extraerla hace que
    el Read no dependa de que el artista no mueva el archivo original.
    El nombre es el sha1 del contenido, así dos proyectos con la misma placa
    comparten el archivo y re-extraer no duplica nada.
    """
    import hashlib
    import os

    if not cam.get("image_size"):
        raise ValueError("el proyecto .fspy no tiene imagen embebida (image_size = 0)")

    with open(cam["path"], "rb") as fh:
        fh.seek(16 + cam["state_size"])
        blob = fh.read(cam["image_size"])
    if len(blob) != cam["image_size"]:
        raise ValueError(
            "imagen truncada: %d de %d bytes" % (len(blob), cam["image_size"])
        )

    extension = extension_imagen(blob[:16])
    if not extension:
        raise ValueError(
            "imagen embebida con formato no reconocido (cabecera %s)" % blob[:8].hex()
        )

    os.makedirs(carpeta, exist_ok=True)
    destino = os.path.join(carpeta, "plate_%s%s" % (hashlib.sha1(blob).hexdigest()[:12], extension))
    if not os.path.exists(destino) or os.path.getsize(destino) != len(blob):
        with open(destino, "wb") as fh:
            fh.write(blob)
    return destino


def _rows(node):
    return [[float(x) for x in row] for row in node["rows"]]


def _length(v):
    return math.sqrt(sum(c * c for c in v))


def matrix_flat(cam):
    """Las 16 componentes de cameraTransform (cámara -> mundo), fila por fila."""
    return tuple(x for row in cam["camera_transform"] for x in row)


def project_world_point(cam, point):
    """Proyecta un punto del mundo a coordenadas normalizadas de imagen (u, v) en [-1, 1].

    Sirve de autotest: el origen (0,0,0) tiene que volver al origen que el usuario
    marcó en fSpy. Usa solo el archivo, sin Nuke.
    """
    vt = cam["view_transform"]
    x, y, z, w = point[0], point[1], point[2], 1.0
    px = vt[0][0] * x + vt[0][1] * y + vt[0][2] * z + vt[0][3] * w  # espacio de cámara
    py = vt[1][0] * x + vt[1][1] * y + vt[1][2] * z + vt[1][3] * w
    pz = vt[2][0] * x + vt[2][1] * y + vt[2][2] * z + vt[2][3] * w
    if pz >= -1e-9:
        return None  # detrás del centro óptico
    s = cam["f_rel"] / (-pz)
    u0, v0 = cam["principal_point"]
    u = u0 + s * px
    v_tilde = v0 + s * py
    return u, v_tilde * cam["aspect"]


def selftest(cam):
    """Comprueba que el origen marcado en el proyecto se reproyecta sobre sí mismo."""
    origin = cam["state"]["controlPointsStateBase"]["origin"]
    expected = (2.0 * origin["x"] - 1.0, 1.0 - 2.0 * origin["y"])
    got = project_world_point(cam, (0.0, 0.0, 0.0))
    if got is None:
        return False, expected, None
    err = max(abs(got[0] - expected[0]), abs(got[1] - expected[1]))
    return err < 1e-9, expected, got
