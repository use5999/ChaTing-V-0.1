import sys
import os
import subprocess
import re
import webbrowser

# --- Importaciones de PyQt6 ---
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QTextEdit, QLineEdit, QPushButton, QTreeView,
    QFileDialog, QMessageBox, QInputDialog, QSplitter, QFrame,
    QToolBar, QStatusBar
)
from PyQt6.QtGui import (
    QFont, QAction, QColor, QSyntaxHighlighter, QTextCharFormat, QIcon,
    QFileSystemModel
)
from PyQt6.QtCore import QThread, pyqtSignal, QDir, Qt, QProcess

# --- Módulos Opcionales ---
try:
    import google.generativeai as genai
except ImportError:
    genai = None

try:
    import qtawesome as qta
except ImportError:
    qta = None

# --- Hojas de Estilo (QSS) para los Temas ---
LIGHT_STYLE_SHEET = """
    /* ... (El estilo no cambia) ... */
    QMainWindow, QToolBar { background-color: #f0f0f0; }
    QTextEdit, QTreeView, QLineEdit { background-color: #ffffff; border: 1px solid #cccccc; border-radius: 6px; font-size: 11pt; color: #3d3d3d; }
    QTreeView { padding: 5px; }
    QTextEdit:focus, QTreeView:focus, QLineEdit:focus { border: 1px solid #3584e4; }
    QPushButton { background-color: #e8e7e6; border: 1px solid #b7b5b3; border-radius: 6px; padding: 8px; font-size: 10pt; color: #3d3d3d; }
    QPushButton:hover { background-color: #f2f2f2; }
    QSplitter::handle { background-color: #d0ced9; }
    QFrame#SidePanel { background-color: #e8e7e6; border-right: 1px solid #cccccc; }
    #SendButton { background-color: #3584e4; color: white; border: none; }
    #TerminalOutput { background-color: #ffffff; color: #3d3d3d; font-family: 'Monospace'; }
"""
DARK_STYLE_SHEET = """
    /* ... (El estilo no cambia) ... */
    QMainWindow, QToolBar { background-color: #2b2b2b; }
    QTextEdit, QTreeView, QLineEdit { background-color: #3c3f41; border: 1px solid #555555; border-radius: 6px; font-size: 11pt; color: #dcdcdc; }
    QTreeView { padding: 5px; }
    QTextEdit:focus, QTreeView:focus, QLineEdit:focus { border: 1px solid #0d61a9; }
    QPushButton { background-color: #4a4d50; border: 1px solid #666666; border-radius: 6px; padding: 8px; font-size: 10pt; color: #dcdcdc; }
    QPushButton:hover { background-color: #5a5d60; }
    QSplitter::handle { background-color: #555555; }
    QFrame#SidePanel { background-color: #313335; border-right: 1px solid #444444; }
    #SendButton { background-color: #0d61a9; color: white; border: none; }
    #TerminalOutput { background-color: #2b2b2b; color: #dcdcdc; font-family: 'Monospace'; border-top: 1px solid #444444; }
"""

# --- Resaltador de Sintaxis ---
class GenericSyntaxHighlighter(QSyntaxHighlighter):
    def __init__(self, parent):
        super().__init__(parent)
        self.highlighting_rules = []
        keyword_format = QTextCharFormat(); keyword_format.setForeground(QColor("#569cd6")); keyword_format.setFontWeight(QFont.Weight.Bold)
        keywords = ["and", "as", "assert", "break", "class", "continue", "def", "del", "elif", "else", "except", "False", "finally", "for", "from", "global", "if", "import", "in", "is", "lambda", "None", "nonlocal", "not", "or", "pass", "raise", "return", "True", "try", "while", "with", "yield"]
        self.highlighting_rules += [(fr'\b{word}\b', keyword_format) for word in keywords]
        string_format = QTextCharFormat(); string_format.setForeground(QColor("#ce9178"))
        self.highlighting_rules.append((r'"[^"\\]*(\\.[^"\\]*)*"', string_format)); self.highlighting_rules.append((r"'[^'\\]*(\\.[^'\\]*)*'", string_format))
        comment_format = QTextCharFormat(); comment_format.setForeground(QColor("#6a9955")); self.highlighting_rules.append((r'#[^\n]*', comment_format))
        tag_format = QTextCharFormat(); tag_format.setForeground(QColor("#4ec9b0")); self.highlighting_rules.append((r'<[a-zA-Z0-9_!/]+', tag_format)); self.highlighting_rules.append((r'>', tag_format))
    def highlightBlock(self, text):
        for pattern, format in self.highlighting_rules:
            for match in re.finditer(pattern, text): self.setFormat(match.start(), match.end() - match.start(), format)

# --- Hilos de Tareas ---
class CodeExecutorThread(QThread):
    output_ready = pyqtSignal(str)
    def __init__(self, command_parts): super().__init__(); self.command_parts = command_parts
    def run(self):
        process = QProcess(); process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(lambda: self.output_ready.emit(process.readAllStandardOutput().data().decode(errors='ignore')))
        process.start(self.command_parts[0], self.command_parts[1:]); process.waitForFinished(-1)

class GeminiThread(QThread):
    response_ready = pyqtSignal(str); error_occurred = pyqtSignal(str)
    def __init__(self, prompt, model): super().__init__(); self.prompt = prompt; self.model = model
    def run(self):
        if not self.model: self.error_occurred.emit("El modelo de Gemini no está configurado."); return
        try: response = self.model.generate_content(self.prompt); self.response_ready.emit(response.text.strip())
        except Exception as e: self.error_occurred.emit(f"Error en la API de Gemini: {e}")

# --- Ventana Principal ---
class SanixIDE(QMainWindow):
    EDIT_KEYWORDS = ['edit', 'edita', 'corrige', 'mejora', 'optimiza', 'refactoriza', 'añade', 'agrega', 'cambia', 'modifica', 'traduce', 'documenta', 'explica']
    def __init__(self):
        super().__init__()
        self.current_file_path = None; self.api_configured = False; self.gemini_model = None
        self.is_dark_mode = False; self.is_terminal_visible = False

        self.setWindowTitle("SANIX IDE") # Título de la app cambiado
        self.setGeometry(100, 100, 1400, 900)

        self.create_widgets(); self.create_layout(); self.create_connections(); self.toggle_theme()
        if genai: self.prompt_for_api_key()

    def create_widgets(self):
        self.toolbar = QToolBar("Main Toolbar"); self.addToolBar(self.toolbar)
        self.action_new_file = QAction("Nuevo Archivo", self)
        self.action_save = QAction("Guardar", self)
        self.action_run = QAction("Ejecutar / Abrir", self)
        self.action_api = QAction("Cambiar API", self)
        self.action_toggle_terminal = QAction("Terminal", self) # Botón para la terminal
        self.action_toggle_theme = QAction("Cambiar Tema", self)
        self.toolbar.addAction(self.action_new_file); self.toolbar.addAction(self.action_save); self.toolbar.addAction(self.action_run); self.toolbar.addAction(self.action_api); self.toolbar.addAction(self.action_toggle_terminal); self.toolbar.addAction(self.action_toggle_theme)
        
        self.folder_button = QPushButton(" Abrir Carpeta")
        self.file_tree = QTreeView(); self.file_system_model = QFileSystemModel(); self.file_system_model.setRootPath(QDir.rootPath()); self.file_tree.setModel(self.file_system_model)
        for i in range(1, self.file_system_model.columnCount()): self.file_tree.setColumnHidden(i, True)
        self.file_tree.setHeaderHidden(True)
        self.editor = QTextEdit(); self.editor.setFont(QFont("Monospace", 11)); self.highlighter = GenericSyntaxHighlighter(self.editor.document())
        self.terminal = QTextEdit(); self.terminal.setObjectName("TerminalOutput"); self.terminal.setReadOnly(True) # Terminal re-añadida
        self.prompt_input = QLineEdit(); self.prompt_input.setPlaceholderText("Crea código nuevo o pide una mejora para el código actual...")
        self.send_button = QPushButton(); self.send_button.setObjectName("SendButton")
        self.statusBar = QStatusBar(); self.setStatusBar(self.statusBar)

    def create_layout(self):
        side_panel = QFrame(); side_panel.setObjectName("SidePanel"); side_panel_layout = QVBoxLayout(side_panel)
        side_panel.setFixedWidth(250); side_panel_layout.addWidget(self.folder_button); side_panel_layout.addWidget(self.file_tree)
        right_panel = QWidget(); right_panel_layout = QVBoxLayout(right_panel); right_panel_layout.setContentsMargins(0,0,0,0); right_panel_layout.setSpacing(0)
        
        # Splitter vertical re-añadido para la terminal
        self.editor_splitter = QSplitter(Qt.Orientation.Vertical)
        self.editor_splitter.addWidget(self.editor)
        self.editor_splitter.addWidget(self.terminal)
        self.editor_splitter.setSizes([700, 200])

        prompt_layout = QHBoxLayout(); prompt_layout.addWidget(self.prompt_input); prompt_layout.addWidget(self.send_button)
        right_panel_layout.addWidget(self.editor_splitter); right_panel_layout.addLayout(prompt_layout)
        
        self.terminal.hide() # La terminal empieza oculta

        main_splitter = QSplitter(Qt.Orientation.Horizontal); main_splitter.addWidget(side_panel); main_splitter.addWidget(right_panel); main_splitter.setSizes([250, 1150])
        self.setCentralWidget(main_splitter)

    def create_connections(self):
        self.action_new_file.triggered.connect(self.new_file)
        self.action_save.triggered.connect(self.save_file)
        self.action_run.triggered.connect(self.execute_or_open_file)
        self.action_api.triggered.connect(self.prompt_for_api_key)
        self.action_toggle_terminal.triggered.connect(self.toggle_terminal) # Conexión del botón
        self.action_toggle_theme.triggered.connect(self.toggle_theme)
        self.folder_button.clicked.connect(self.open_folder)
        self.file_tree.clicked.connect(self.file_selected)
        self.send_button.clicked.connect(self.generate_or_edit_code)

    def toggle_terminal(self):
        """Muestra u oculta la terminal."""
        self.is_terminal_visible = not self.is_terminal_visible
        self.terminal.setVisible(self.is_terminal_visible)

    def toggle_theme(self):
        self.is_dark_mode = not self.is_dark_mode
        self.setStyleSheet(DARK_STYLE_SHEET if self.is_dark_mode else LIGHT_STYLE_SHEET); self.update_icons()

    def update_icons(self):
        icon_color = '#dcdcdc' if self.is_dark_mode else '#3d3d3d'
        def get_icon(name): return qta.icon(name, color=icon_color) if qta else QIcon()
        self.action_new_file.setIcon(get_icon('fa5s.file'))
        self.action_save.setIcon(get_icon('fa5s.save')); self.action_run.setIcon(get_icon('fa5s.play')); self.action_api.setIcon(get_icon('fa5s.key'))
        self.action_toggle_terminal.setIcon(get_icon('fa5s.terminal'))
        self.action_toggle_theme.setIcon(get_icon('fa5s.sun') if self.is_dark_mode else get_icon('fa5s.moon'))
        self.folder_button.setIcon(get_icon('fa5s.folder-open')); self.send_button.setIcon(qta.icon('fa5s.arrow-right', color='white') if qta else QIcon())

    def new_file(self):
        if not self.check_for_unsaved_changes(): return
        self.editor.clear(); self.current_file_path = None
        self.setWindowTitle("SANIX IDE - Untitled") # Título actualizado
        self.editor.document().setModified(False); self.statusBar.showMessage("Nuevo archivo creado.", 3000)

    def file_selected(self, index):
        if not self.check_for_unsaved_changes(): return
        file_path = self.file_system_model.filePath(index)
        if os.path.isfile(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f: self.editor.setPlainText(f.read())
                self.current_file_path = file_path
                self.setWindowTitle(f"SANIX IDE - {os.path.basename(file_path)}") # Título actualizado
                self.editor.document().setModified(False)
            except Exception as e: self.show_message("Error de Lectura", f"No se pudo leer el archivo:\n{e}")
    
    def check_for_unsaved_changes(self):
        if not self.editor.document().isModified(): return True
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Warning)
        msg_box.setText(f"¿Quieres guardar los cambios en {os.path.basename(self.current_file_path or 'Untitled')}?")
        msg_box.setStandardButtons(QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        msg_box.setDefaultButton(QMessageBox.StandardButton.Save)
        reply = msg_box.exec()
        if reply == QMessageBox.StandardButton.Save: return self.save_file()
        elif reply == QMessageBox.StandardButton.Cancel: return False
        return True

    def save_file(self):
        path_to_save = self.current_file_path
        if not path_to_save: path_to_save, _ = QFileDialog.getSaveFileName(self, "Guardar Archivo", "", "Todos los Archivos (*)")
        if path_to_save:
            try:
                with open(path_to_save, 'w', encoding='utf-8') as f: f.write(self.editor.toPlainText())
                self.current_file_path = path_to_save; self.statusBar.showMessage(f"Archivo guardado: {path_to_save}", 3000)
                self.setWindowTitle(f"SANIX IDE - {os.path.basename(path_to_save)}"); self.editor.document().setModified(False) # Título actualizado
                return True
            except Exception as e: self.show_message("Error de Escritura", f"No se pudo guardar el archivo:\n{e}"); return False
        return False

    def execute_or_open_file(self):
        if not self.current_file_path: self.show_message("Archivo no guardado", "Guarda el archivo antes."); return
        self.save_file(); _root, extension = os.path.splitext(self.current_file_path); extension = extension.lower()
        if extension == '.py': self.run_in_app_terminal([sys.executable, self.current_file_path])
        elif extension == '.js': self.run_in_app_terminal(['node', self.current_file_path])
        elif extension in ['.html', '.htm', '.xml', '.svg']: self.open_in_browser()
        else: self.open_with_default_app()

    def run_in_app_terminal(self, command_parts):
        """Ejecuta un comando en la terminal integrada, mostrándola si es necesario."""
        if not self.is_terminal_visible: # Apertura automática
            self.toggle_terminal()
        self.terminal.clear(); self.terminal.append(f"> {' '.join(command_parts)}\n")
        self.executor_thread = CodeExecutorThread(command_parts)
        self.executor_thread.output_ready.connect(lambda out: self.terminal.insertPlainText(out))
        self.executor_thread.finished.connect(lambda: self.terminal.append("\n> Proceso finalizado.")); self.executor_thread.start()

    def generate_or_edit_code(self):
        if not self.api_configured: self.show_message("API no configurada", "Configura tu API Key para usar la IA."); return
        user_prompt = self.prompt_input.text().lower(); current_code = self.editor.toPlainText()
        if not user_prompt: return
        is_edit_request = any(keyword in user_prompt for keyword in self.EDIT_KEYWORDS) and current_code.strip()
        if is_edit_request:
            self.statusBar.showMessage("Editando código con Gemini...")
            prompt = (f"Realiza la siguiente acción en el código: '{user_prompt}'.\n\nCódigo actual:\n```\n{current_code}\n```\n\nDevuelve únicamente el bloque de código completo y modificado.")
            self.run_gemini_task(prompt, self.replace_editor_content)
        else:
            self.statusBar.showMessage("Generando código con Gemini...")
            prompt = (f"Genera un fragmento de código para: '{user_prompt}'. Responde únicamente con el bloque de código.")
            self.run_gemini_task(prompt, self.insert_editor_content)

    def run_gemini_task(self, prompt, on_complete_slot):
        self.gemini_thread = GeminiThread(prompt, self.gemini_model)
        self.gemini_thread.response_ready.connect(on_complete_slot)
        self.gemini_thread.error_occurred.connect(lambda err: self.show_message("Error de IA", err)); self.gemini_thread.start()
        
    def insert_editor_content(self, code):
        self.editor.textCursor().insertText(self.clean_response_code(code))
        self.statusBar.showMessage("Código nuevo insertado.", 3000); self.prompt_input.clear()

    def replace_editor_content(self, code):
        self.editor.setPlainText(self.clean_response_code(code))
        self.statusBar.showMessage("Código actualizado por la IA.", 3000); self.prompt_input.clear()
        
    def clean_response_code(self, code):
        match = re.search(r'```(?:\w*\n)?(.*)```', code, re.DOTALL)
        return match.group(1).strip() if match else code.strip()

    def open_folder(self):
        if not self.check_for_unsaved_changes(): return
        try:
            folder_path = QFileDialog.getExistingDirectory(self, "Seleccionar Carpeta")
            if folder_path: self.file_tree.setRootIndex(self.file_system_model.index(folder_path))
        except Exception as e: self.show_message("Error Inesperado", f"No se pudo abrir la carpeta: {e}")

    def open_in_browser(self):
        try:
            file_url = 'file:///' + os.path.abspath(self.current_file_path).replace('\\', '/'); webbrowser.open(file_url)
            self.statusBar.showMessage(f"Abriendo {os.path.basename(self.current_file_path)} en el navegador...", 3000)
        except Exception as e: self.show_message("Error", f"No se pudo abrir el archivo en el navegador: {e}")

    def open_with_default_app(self):
        self.statusBar.showMessage(f"Intentando abrir {os.path.basename(self.current_file_path)}...", 3000)
        try:
            if sys.platform == "win32": os.startfile(self.current_file_path)
            elif sys.platform == "darwin": subprocess.run(["open", self.current_file_path])
            else: subprocess.run(["xdg-open", self.current_file_path])
        except Exception as e: self.show_message("Error", f"No se pudo abrir el archivo.\nError: {e}")

    def prompt_for_api_key(self):
        if not genai: self.show_message("Función no disponible", "'google-generativeai' no está instalado."); return
        api_key, ok = QInputDialog.getText(self, "Configurar API Key", "Introduce tu API Key de Gemini:", QLineEdit.EchoMode.Password)
        if ok and api_key: self.configure_gemini(api_key)

    def configure_gemini(self, api_key):
        try:
            genai.configure(api_key=api_key); self.gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest')
            self.gemini_model.generate_content("test", request_options={'timeout': 10}); self.api_configured = True
            self.send_button.setEnabled(True); self.statusBar.showMessage("API de Gemini configurada correctamente.", 5000)
        except Exception as e:
            self.api_configured = False; self.gemini_model = None; self.send_button.setEnabled(False)
            self.show_message("Error de API", f"No se pudo configurar la API.\nError: {e}")

    def show_message(self, title, message):
        QMessageBox.information(self, title, message)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    if not qta: print("ADVERTENCIA: qtawesome no está instalado (pip install qtawesome), los iconos no se mostrarán.")
    if not genai: print("ADVERTENCIA: google-generativeai no está instalado, las funciones de IA están deshabilitadas.")
    editor = SanixIDE()
    editor.show()
    sys.exit(app.exec())