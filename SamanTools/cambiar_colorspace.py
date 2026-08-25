import nuke

# Compatibilidad para Nuke antiguo (PySide2) y Nuke moderno (PySide6)
try:
    from PySide2 import QtWidgets, QtCore
except ImportError:
    from PySide6 import QtWidgets, QtCore

class VentanaCambioColorSpace(QtWidgets.QDialog):
    def __init__(self, lista_colores_raw, parent=None):
        super(VentanaCambioColorSpace, self).__init__(parent)
        
        self.setWindowTitle('Cambiar Espacio de Color')
        self.setMinimumWidth(500)  # Un poco más ancho para leer cómodamente los nombres de OCIO
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)
        
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(15, 15, 15, 15)
        
        label = QtWidgets.QLabel("Buscar y seleccionar espacio de color:")
        layout.addWidget(label)
        
        # --- DROPDOWN DE BÚSQUEDA ---
        self.combo = QtWidgets.QComboBox(self)
        self.combo.setEditable(True)
        self.combo.addItem("", None)  # Casilla en blanco al inicio
        
        for item in lista_colores_raw:
            # SOLUCIÓN ERROR 1: Parseo unificado para limpiar Roles de OCIO y perfiles estándar
            if '\t' in item:
                partes = [p.strip() for p in item.split('\t') if p.strip()]
                nombre_visible = partes[-1]  # Texto largo descriptivo: "scene_linear (ACEScg)"
                id_interno = partes[0]       # ID técnico que entiende el nodo: "scene_linear"
            elif ',' in item:
                partes = [p.strip() for p in item.split(',') if p.strip()]
                nombre_visible = partes[0]
                id_interno = partes[0]
            else:
                nombre_visible = item
                id_interno = item
            
            self.combo.addItem(nombre_visible, id_interno)
        
        self.combo.setCurrentIndex(0)
        
        completer = self.combo.completer()
        completer.setFilterMode(QtCore.Qt.MatchContains) 
        completer.setCompletionMode(QtWidgets.QCompleter.PopupCompletion)
        
        layout.addWidget(self.combo)
        
        botones = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            QtCore.Qt.Horizontal, self
        )
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        layout.addWidget(botones)
        
    def obtener_seleccion(self):
        texto_ingresado = self.combo.currentText().strip()
        if not texto_ingresado:
            return None
            
        idx = self.combo.findText(texto_ingresado, QtCore.Qt.MatchFixedString)
        if idx != -1:
            return self.combo.itemData(idx) 
            
        for i in range(self.combo.count()):
            nombre_visible = self.combo.itemText(i)
            if texto_ingresado.lower() in nombre_visible.lower():
                return self.combo.itemData(i)
                
        return None


def ejecutar_cambio_colorespace_reads():
    nodos_read = [n for n in nuke.selectedNodes() if n.Class() == 'Read']
    
    if not nodos_read:
        nuke.message("Por favor, selecciona primero los nodos de tipo 'Read' que deseas modificar.")
        return

    # Detección automática del backend de color activo
    if nuke.usingOcio():
        lista_colores_raw = nuke.getOcioColorSpaces()
    else:
        lista_colores_raw = nodos_read[0]['colorspace'].values()
    
    parent_win = QtWidgets.QApplication.activeWindow()
    ventana = VentanaCambioColorSpace(lista_colores_raw, parent=parent_win)
    
    if ventana.exec():
        id_destino = ventana.obtener_seleccion()
        
        if not id_destino:
            nuke.message("Operación cancelada: No se seleccionó ningún espacio de color válido.")
            return
            
        nodos_modificados = 0
        
        for nodo in nodos_read:
            if 'colorspace' in nodo.knobs():
                # SOLUCIÓN ERROR 2: Usamos .fromScript() para simular una carga nativa por texto.
                # Esto obliga a OCIO a revalidar y levantar el LUT correcto de inmediato sin romper el visor.
                nodo['colorspace'].fromScript(id_destino)
                
                # Forzamos la actualización del caché de lectura por seguridad
                nodo['reload'].execute() 
                nodos_modificados += 1
                
        nuke.message(f"¡Éxito! Se actualizaron {nodos_modificados} nodo(s) Read al espacio:\n{id_destino}")

# Para ejecutar la herramienta en el Script Editor:
# ejecutar_cambio_colorespace_reads()