"""
Tests de SamanTools.fspy_core — lector de proyectos .fspy.

No necesitan Nuke ni la app fSpy: el archivo se sintetiza en el test con una
cámara calculada a mano, así los números esperados se pueden verificar sin
depender de ningún binario externo.

Cámara del fixture (a mano, sin trigonometría):
    posición (0, 1, 5), sin rotación, mirando hacia -Z
    f_rel = 2.0, imagen 3000x2000 (a = 1.5), punto principal (0, 0)
    el origen del mundo (0,0,0) cae en el rayo (0, -1, -5)
      s   = f_rel / 5 = 0.4
      u   = 0 + 0.4 * 0   = 0.0        -> x normalizada = 0.5
      ṽ   = 0 + 0.4 * -1  = -0.4
      v   = ṽ * a         = -0.6       -> y = (1 - v) / 2 = 0.8
"""

import json
import math
import os
import struct

import pytest

from SamanTools import fspy_core

F_REL = 2.0
ANCHO, ALTO = 3000, 2000
ORIGEN_X, ORIGEN_Y = 0.5, 0.8
CAMERA_TRANSFORM = [[1, 0, 0, 0], [0, 1, 0, 1], [0, 0, 1, 5], [0, 0, 0, 1]]
VIEW_TRANSFORM = [[1, 0, 0, 0], [0, 1, 0, -1], [0, 0, 1, -5], [0, 0, 0, 1]]


def estado(preset=True):
    """Estado de proyecto mínimo pero completo, con la cámara del docstring."""
    camera_data = {"presetId": None, "customSensorWidth": 50, "customSensorHeight": 25}
    if preset:
        camera_data = {
            "presetId": "test",
            "presetData": {"sensorWidth": 36.0, "sensorHeight": 24.0},
            "customSensorWidth": 50,
            "customSensorHeight": 25,
        }
    return {
        "globalSettings": {"calibrationMode": "TwoVanishingPoints"},
        "calibrationSettingsBase": {
            "cameraData": camera_data,
            "referenceDistance": 0.2,
            "referenceDistanceUnit": "Meters",
        },
        "controlPointsStateBase": {
            "principalPoint": {"x": 0.5, "y": 0.5},
            "origin": {"x": ORIGEN_X, "y": ORIGEN_Y},
        },
        "cameraParameters": {
            "relativeFocalLength": F_REL,
            "imageWidth": ANCHO,
            "imageHeight": ALTO,
            "principalPoint": {"x": 0, "y": 0},
            "viewTransform": {"rows": VIEW_TRANSFORM},
            "cameraTransform": {"rows": CAMERA_TRANSFORM},
            "vanishingPoints": [{"x": -3.0, "y": 0.5}, {"x": 0.5, "y": -2.0}, {"x": 1.0, "y": 1.0}],
        },
    }


def escribir(destino, datos=None, version=1, magia=b"fspy", imagen=b"\xff\xd8\xff\xd9"):
    """Escribe un .fspy con la estructura del formato oficial."""
    cuerpo = json.dumps(datos if datos is not None else estado()).encode("utf-8")
    contenido = magia + struct.pack("<III", version, len(cuerpo), len(imagen)) + cuerpo + imagen
    ruta = destino / "proyecto.fspy"
    ruta.write_bytes(contenido)
    return str(ruta)


# ------------------------------------------------------------------ lectura
def test_lee_identidad_y_optica(tmp_path):
    cam = fspy_core.read(escribir(tmp_path))

    assert cam["mode"] == "TwoVanishingPoints"
    assert (cam["width"], cam["height"]) == (ANCHO, ALTO)
    assert cam["aspect"] == pytest.approx(1.5)
    assert cam["f_rel"] == pytest.approx(F_REL)
    assert cam["sensor_w_mm"] == pytest.approx(36.0)
    assert cam["sensor_h_mm"] == pytest.approx(24.0)
    assert cam["focal_mm"] == pytest.approx(F_REL * 36.0 / 2.0)
    assert cam["fov_h_deg"] == pytest.approx(math.degrees(2 * math.atan(1 / F_REL)))
    assert cam["fov_v_deg"] == pytest.approx(math.degrees(2 * math.atan(1 / (1.5 * F_REL))))
    assert cam["principal_point"] == (0.0, 0.0)


def test_usa_sensor_custom_si_no_hay_preset(tmp_path):
    cam = fspy_core.read(escribir(tmp_path, estado(preset=False)))

    assert cam["sensor_w_mm"] == pytest.approx(50.0)
    assert cam["sensor_h_mm"] == pytest.approx(25.0)
    assert cam["focal_mm"] == pytest.approx(F_REL * 50.0 / 2.0)


def test_posicion_de_camara_y_escala(tmp_path):
    cam = fspy_core.read(escribir(tmp_path))

    assert cam["camera_position"] == pytest.approx((0.0, 1.0, 5.0))
    # T_view traslada el origen del mundo (0, -1, -5); λ = |t| / f_rel
    assert cam["scale"] == pytest.approx(math.sqrt(26.0) / F_REL)


def test_matriz_plana_en_orden_fila(tmp_path):
    cam = fspy_core.read(escribir(tmp_path))

    assert fspy_core.matrix_flat(cam) == tuple(float(v) for fila in CAMERA_TRANSFORM for v in fila)


# ------------------------------------------------- el test que vale: reproyección
def test_origen_se_reproyecta_sobre_si_mismo(tmp_path):
    cam = fspy_core.read(escribir(tmp_path))

    ok, esperado, obtenido = fspy_core.selftest(cam)

    assert ok is True
    assert esperado == pytest.approx((0.0, -0.6))
    assert obtenido == pytest.approx(esperado, abs=1e-12)


def test_punto_detras_de_la_camara_no_proyecta(tmp_path):
    cam = fspy_core.read(escribir(tmp_path))

    assert fspy_core.project_world_point(cam, (0.0, 1.0, 100.0)) is None


# ------------------------------------------------------------------- errores
def test_rechaza_archivo_que_no_es_fspy(tmp_path):
    with pytest.raises(ValueError, match="fspy"):
        fspy_core.read(escribir(tmp_path, magia=b"zip!"))


def test_rechaza_version_desconocida(tmp_path):
    with pytest.raises(ValueError, match="versión"):
        fspy_core.read(escribir(tmp_path, version=2))


def test_rechaza_proyecto_sin_solucion_de_camara(tmp_path):
    datos = estado()
    datos["cameraParameters"] = None
    with pytest.raises(ValueError, match="no tiene solución de cámara"):
        fspy_core.read(escribir(tmp_path, datos))


def test_rechaza_archivo_truncado(tmp_path):
    ruta = escribir(tmp_path)
    with open(ruta, "wb") as fh:
        fh.write(b"fspy" + struct.pack("<III", 1, 500, 0) + b"{}")

    with pytest.raises(ValueError, match="truncado"):
        fspy_core.read(ruta)


def test_no_importa_nuke():
    """fspy_core debe ser puro stdlib: es lo que permite testearlo fuera de Nuke."""
    assert "nuke" not in fspy_core.__dict__


# ------------------------------------------- imagen embebida (el .fspy la lleva adentro)
def test_extrae_la_imagen_embebida(tmp_path):
    ruta = escribir(tmp_path)
    cam = fspy_core.read(ruta)

    destino = fspy_core.extraer_imagen(cam, tmp_path / "cache")

    with open(destino, "rb") as fh:
        assert fh.read() == b"\xff\xd8\xff\xd9"
    assert destino.endswith(".jpg")


def test_extraccion_idempotente_y_por_contenido(tmp_path):
    ruta = escribir(tmp_path)
    cam = fspy_core.read(ruta)

    primero = fspy_core.extraer_imagen(cam, tmp_path / "cache")
    segundo = fspy_core.extraer_imagen(cam, tmp_path / "cache")

    assert primero == segundo
    assert len(os.listdir(tmp_path / "cache")) == 1


def test_extension_segun_cabecera():
    assert fspy_core.extension_imagen(b"\xff\xd8\xff\xe0") == ".jpg"
    assert fspy_core.extension_imagen(b"\x89PNG\r\n\x1a\n") == ".png"
    assert fspy_core.extension_imagen(b"RIFFxxxxWEBP") == ".webp"
    assert fspy_core.extension_imagen(b"????") == ""


def test_error_si_el_proyecto_no_tiene_imagen(tmp_path):
    ruta = escribir(tmp_path, imagen=b"")
    cam = fspy_core.read(ruta)

    with pytest.raises(ValueError, match="no tiene imagen embebida"):
        fspy_core.extraer_imagen(cam, tmp_path / "cache")


def test_error_si_la_imagen_esta_truncada(tmp_path):
    ruta = escribir(tmp_path)
    cam = fspy_core.read(ruta)
    cam["image_size"] = 100  # el header dice 100, el archivo tiene 4

    with pytest.raises(ValueError, match="truncada"):
        fspy_core.extraer_imagen(cam, tmp_path / "cache")


def test_error_si_la_imagen_no_es_reconocible(tmp_path):
    ruta = escribir(tmp_path, imagen=b"NOPE0000")
    cam = fspy_core.read(ruta)

    with pytest.raises(ValueError, match="no reconocido"):
        fspy_core.extraer_imagen(cam, tmp_path / "cache")
