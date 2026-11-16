"""Manifiesto único de lo que integra la distribución verificable.

Las rutas son relativas al repositorio para que el generador pueda validarlas y
copiarlas sin depender de la máquina donde se ejecute.
"""

COMPONENTES = (
    {
        "id": "fspy",
        "etiqueta": "fSpy",
        "modulos": ("SamanTools/fspy.py", "SamanTools/fspy_core.py"),
        "assets": ("SamanTools/nodos/fSpy.gizmo", "SamanTools/fSpy.svg"),
        "tests": ("tests/test_fspy_core.py", "tests/test_fspy_nodos.py"),
        "activo": True,
    },
    {
        "id": "colorspace",
        "etiqueta": "Cambio de espacio de color",
        "modulos": ("SamanTools/cambiar_colorspace.py",),
        "assets": ("SamanTools/ChangeColorSpace.svg",),
        "tests": ("tests/test_cambiar_colorspace.py",),
        "activo": True,
    },
    {
        "id": "rutas",
        "etiqueta": "Nodo Rutas",
        "modulos": ("SamanTools/rutas.py",),
        "assets": ("SamanTools/nodos/Rutas.gizmo", "SamanTools/nodos/Rutas.nk"),
        "tests": ("tests/test_rutas.py", "tests/test_gestion_rutas.py", "tests/test_entorno.py"),
        "activo": True,
    },
    {
        "id": "breakdown",
        "etiqueta": "Breakdown",
        "modulos": ("SamanTools/breakdown_datos.py", "SamanTools/frame_manager.py"),
        "assets": ("SamanTools/nodos/Breakdown.gizmo",),
        "tests": ("tests/test_breakdown_datos.py", "tests/test_breakdown_knobs.py", "tests/test_breakdown_columnas.py"),
        "activo": True,
    },
    {
        "id": "acerca_de",
        "etiqueta": "Acerca de SamanTools",
        "modulos": ("SamanTools/registro.py",),
        "assets": (),
        "tests": ("tests/test_menu.py", "tests/test_registro.py"),
        "activo": True,
    },
    {
        "id": "actualizacion",
        "etiqueta": "Actualización",
        "modulos": ("bootstrap/menu.py",),
        "assets": (),
        "tests": ("tests/test_bootstrap_menu.py",),
        "activo": True,
    },
    {
        "id": "nodos_proyecto",
        "etiqueta": "Nodos por proyecto",
        "modulos": ("SamanTools/proyecto.py",),
        "assets": (),
        "tests": ("tests/test_proyecto.py",),
        "activo": True,
    },
)

EXCLUIDOS = {
    "SamanTools/panel_comentarios.py": "Panel VFXFlow fuera del alcance verificado.",
    "SamanTools/vfxflow_auth.py": "Autenticación VFXFlow fuera del alcance verificado.",
    "SamanTools/vfxflow_config.py": "Configuración VFXFlow fuera del alcance verificado.",
    "SamanTools/vfxflow_datos.py": "Datos VFXFlow fuera del alcance verificado.",
    "SamanTools/sesion_vfxflow.py": "Sesión VFXFlow fuera del alcance verificado.",
    "SamanTools/diagnostico_red.py": "Diagnóstico de red fuera del alcance verificado.",
    "render_distribuido/": "Render distribuido fuera del alcance verificado.",
}
