"""
Tests de SamanTools.cambiar_colorspace: parseo de espacios de color OCIO.

El bug histórico: los nombres con '\t' (rol + descripcion) y con ','
(perfiles) se parseaban mal. El combo debe ofrecer el nombre visible
y guardar el id interno correcto.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from SamanTools.cambiar_colorspace import VentanaCambioColorSpace
from PySide6 import QtWidgets


class TestParseoCombo:
    def _combo_para(self, lista):
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        return VentanaCambioColorSpace(lista)

    def test_parseo_tab_ocio(self):
        # Formato REAL de nuke.getOcioColorSpaces: 'id_interno\tid_interno (descripcion)'
        # O sea: el ID tecnico va PRIMERO, la descripcion visible al final.
        v = self._combo_para(["scene_linear\tscene_linear (ACEScg)"])
        assert v.combo.itemText(1) == "scene_linear (ACEScg)"  # visible
        assert v.combo.itemData(1) == "scene_linear"           # id interno

    def test_parseo_coma_perfil(self):
        v = self._combo_para(["sRGB, sRGB"])
        assert v.combo.itemText(1) == "sRGB"
        assert v.combo.itemData(1) == "sRGB"

    def test_parseo_simple(self):
        v = self._combo_para(["Raw"])
        assert v.combo.itemText(1) == "Raw"
        assert v.combo.itemData(1) == "Raw"

    def test_obtener_seleccion_por_nombre_visible(self):
        v = self._combo_para(["scene_linear\tscene_linear (ACEScg)"])
        v.combo.setCurrentIndex(1)
        assert v.obtener_seleccion() == "scene_linear"

    def test_obtener_seleccion_vacia_devuelve_none(self):
        v = self._combo_para(["Raw"])
        v.combo.setCurrentIndex(0)
        assert v.obtener_seleccion() is None

    def test_busqueda_parcial(self):
        # escribir texto parcial debe resolver al id correcto
        v = self._combo_para(["scene_linear\tscene_linear (ACEScg)"])
        v.combo.setEditText("aces")
        assert v.obtener_seleccion() == "scene_linear"