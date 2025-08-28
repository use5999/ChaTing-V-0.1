import sys
import os
import subprocess
import re
import webbrowser

# --- Importaciones de PyQt6 ---
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QTextEdit, QLabel, QFileDialog, QMessageBox,
    QSplitter, QFrame, QToolBar, QStatusBar, QDockWidget,
    QListWidget, QListWidgetItem, QInputDialog
)
from PyQt6.QtGui import (
    QFont, QAction, QColor, QSyntaxHighlighter, QTextCharFormat, QIcon
)
from PyQt6.QtCore import Qt, QProcess, QUrl, QStandardPaths, QSize

# --- Módulo Web Opcional ---
try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView  # type: ignore
    WEB_ENGINE_AVAILABLE = True
except ImportError:
    WEB_ENGINE_AVAILABLE = False

# --- Estilos ---
LIGHT_STYLE_SHEET = """
    QMainWindow, QToolBar { background-color: #f0f0f0; }
    QTextEdit { background-color: #ffffff; border: 1px solid #cccccc; border-radius: 6px; font-size: 11pt; color: #3d3d3d; }
    QLabel#ProjectsLabel { font-size: 14pt; font-weight: bold; color: #1a4fa3; padding: 6px; }
    QListWidget { border: none; }
"""
DARK_STYLE_SHEET = """
    QMainWindow, QToolBar { background-color: #2b2b2b; }
    QTextEdit { background-color: #3c3f41; border: 1px solid #555555; border-radius: 6px; font-size: 11pt; color: #dcdcdc; }
    QLabel#ProjectsLabel { font-size: 14pt; font-weight: bold; color: #4a90e2; padding: 6px; }
    QListWidget { border: none; }
"""

# --- Resaltador de Sintaxis ---
class GenericSyntaxHighlighter(QSyntaxHighlighter):
    def __init__(self, parent):
        super().__init__(parent)
        self.highlighting_rules = []

        keyword_format = QTextCharFormat()
        keyword_format.setForeground(QColor("#569cd6"))
        keyword_format.setFontWeight(QFont.Weight.Bold)
        keywords = ["and","as","assert","break","class","continue","def","del","elif","else",
                    "except","False","finally","for","from","global","if","import","in",
                    "is","lambda","None","nonlocal","not","or","pass","raise","return",
                    "True","try","while","with","yield"]
        self.highlighting_rules += [(fr'\b{word}\b', keyword_format) for word in keywords]

        string_format = QTextCharFormat()
        string_format.setForeground(QColor("#ce9178"))
        self.highlighting_rules.append((r'"[^"\\]*(\\.[^"\\]*)*"', string_format))
        self.highlighting_rules.append((r"'[^'\\]*(\\.[^'\\]*)*'", string_format))

        comment_format = QTextCharFormat()
        comment_format.setForeground(QColor("#6a9955"))
        self.highlighting_rules.append((r'#[^\n]*', comment_format))

    def highlightBlock(self, text):
        for pattern, fmt in self.highlighting_rules:
            for match in re.finditer(pattern, text):
                self.setFormat(match.start(), match.end() - match.start(), fmt)

# --- IDE Principal ---
class SanixIDE(QMainWindow):
    def __init__(self):
        super().__init__()
        self.current_file_path = None
        self.current_project_path = None
        self.is_dark_mode = False
        self.is_terminal_visible = False
        self.executor_process = None

        self.setWindowTitle("SANIX IDE")
        self.setGeometry(100, 100, 1400, 900)

        self.workspace_path = self._setup_workspace()
        self.create_widgets()
        self.create_layout()
        self.create_connections()
        self.toggle_theme()

    def _setup_workspace(self):
        docs_path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        workspace = os.path.join(docs_path, "SANIX_IDE_Projects")
        os.makedirs(workspace, exist_ok=True)
        return workspace

    def create_widgets(self):
        # Toolbar
        self.toolbar = QToolBar("Main Toolbar")
        self.addToolBar(self.toolbar)
        self.action_new_file = QAction("Nuevo", self)
        self.action_save = QAction("Guardar", self)
        self.action_run = QAction("Ejecutar", self)
        self.action_toggle_gemini = QAction("Gemini", self)
        self.action_toggle_chatgpt = QAction("ChatGPT", self)
        self.action_toggle_terminal = QAction("Terminal", self)
        self.action_toggle_theme = QAction("Tema", self)
        self.toolbar.addActions([
            self.action_new_file, self.action_save, self.action_run,
            self.action_toggle_gemini, self.action_toggle_chatgpt,
            self.action_toggle_terminal, self.action_toggle_theme
        ])

        # Menú de proyectos
        self.projects_label = QLabel("Tus Proyectos")
        self.projects_label.setObjectName("ProjectsLabel")
        self.project_menu = QListWidget()
        self.project_menu.setViewMode(QListWidget.ViewMode.IconMode)
        self.project_menu.setIconSize(QSize(64, 64))
        self.project_menu.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.project_menu.setSpacing(20)
        self.load_projects()

        # Editor
        self.editor = QTextEdit()
        self.editor.setFont(QFont("Courier", 11))
        self.highlighter = GenericSyntaxHighlighter(self.editor.document())
        self.editor.textChanged.connect(self.auto_format_live)  # Formato en vivo

        # Terminal
        self.terminal = QTextEdit()
        self.terminal.setReadOnly(True)
        self.terminal.hide()

        # Status bar
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)

        # Web docks (IA)
        if WEB_ENGINE_AVAILABLE:
            self.chatgpt_dock = QDockWidget("Asistente ChatGPT", self)
            self.chatgpt_web = QWebEngineView()
            self.chatgpt_web.setUrl(QUrl("https://chat.openai.com/"))
            self.chatgpt_dock.setWidget(self.chatgpt_web)
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.chatgpt_dock)
            self.chatgpt_dock.hide()

            self.gemini_dock = QDockWidget("Asistente Gemini", self)
            self.gemini_web = QWebEngineView()
            self.gemini_web.setUrl(QUrl("https://gemini.google.com/"))
            self.gemini_dock.setWidget(self.gemini_web)
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.gemini_dock)
            self.gemini_dock.hide()

    def load_projects(self):
        self.project_menu.clear()
        new_item = QListWidgetItem(QIcon.fromTheme("list-add"), "+")
        new_item.setToolTip("Nuevo Proyecto")
        self.project_menu.addItem(new_item)
        for name in os.listdir(self.workspace_path):
            path = os.path.join(self.workspace_path, name)
            if os.path.isdir(path):
                item = QListWidgetItem(QIcon.fromTheme("folder"), name)
                self.project_menu.addItem(item)

    def show_project_files(self, project_path):
        self.project_menu.clear()
        back_item = QListWidgetItem("⬅ Volver")
        self.project_menu.addItem(back_item)

        for filename in os.listdir(project_path):
            path = os.path.join(project_path, filename)
            if os.path.isfile(path):
                icon = QIcon.fromTheme("text-x-generic")
                file_item = QListWidgetItem(icon, filename)
                file_item.setToolTip(path)
                self.project_menu.addItem(file_item)

        self.current_project_path = project_path

    def create_layout(self):
        left_panel = QFrame()
        layout = QVBoxLayout(left_panel)
        layout.addWidget(self.projects_label)
        layout.addWidget(self.project_menu)

        right_panel = QSplitter(Qt.Orientation.Vertical)
        right_panel.addWidget(self.editor)
        right_panel.addWidget(self.terminal)
        right_panel.setSizes([700, 200])

        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter.addWidget(left_panel)
        main_splitter.addWidget(right_panel)
        main_splitter.setSizes([400, 1000])

        self.setCentralWidget(main_splitter)

    def create_connections(self):
        self.action_new_file.triggered.connect(self.new_file)
        self.action_save.triggered.connect(self.save_file)
        self.action_run.triggered.connect(self.execute_or_open_file)
        self.action_toggle_theme.triggered.connect(self.toggle_theme)
        self.action_toggle_terminal.triggered.connect(self.toggle_terminal)
        if WEB_ENGINE_AVAILABLE:
            self.action_toggle_gemini.triggered.connect(self.toggle_gemini_panel)
            self.action_toggle_chatgpt.triggered.connect(self.toggle_chatgpt_panel)
        self.project_menu.itemClicked.connect(self.project_menu_clicked)

    # --- Menú de proyectos y archivos ---
    def project_menu_clicked(self, item):
        if item.text() == "+":
            name, ok = QInputDialog.getText(self, "Nuevo Proyecto", "Nombre del proyecto:")
            if ok and name.strip():
                path = os.path.join(self.workspace_path, name.strip())
                os.makedirs(path, exist_ok=True)
                self.load_projects()
        elif item.text() == "⬅ Volver":
            self.load_projects()
        else:
            file_path = item.toolTip()
            if file_path and os.path.isfile(file_path):
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        self.editor.setPlainText(f.read())
                    self.current_file_path = file_path
                    lang = self.detect_language(file_path)
                    self.setWindowTitle(f"SANIX IDE - {os.path.basename(file_path)} [{lang}]")
                except Exception as e:
                    self.show_message("Error", f"No se pudo abrir el archivo: {e}")
            else:
                project_path = os.path.join(self.workspace_path, item.text())
                if os.path.isdir(project_path):
                    self.show_project_files(project_path)

    # --- IA ---
    def toggle_chatgpt_panel(self):
        self.chatgpt_dock.setVisible(not self.chatgpt_dock.isVisible())
        if self.chatgpt_dock.isVisible():
            self.gemini_dock.hide()

    def toggle_gemini_panel(self):
        self.gemini_dock.setVisible(not self.gemini_dock.isVisible())
        if self.gemini_dock.isVisible():
            self.chatgpt_dock.hide()

    # --- Archivo y editor ---
    def detect_language(self, file_path):
        _, ext = os.path.splitext(file_path)
        ext = ext.lower()
        if ext == ".py": return "Python"
        if ext in [".html", ".htm"]: return "HTML"
        if ext == ".js": return "JavaScript"
        if ext == ".css": return "CSS"
        return "Texto plano"

    def normalize_indentation(self, text):
        return text.replace("\t", "    ")

    def auto_format_code(self, code, language):
        code = self.normalize_indentation(code)
        try:
            if language == "Python":
                import black
                return black.format_str(code, mode=black.Mode())
            elif language in ["JavaScript", "HTML", "CSS"]:
                import jsbeautifier
                return jsbeautifier.beautify(code)
        except Exception as e:
            self.statusBar.showMessage(f"No se pudo autoformatear: {e}", 3000)
        return code

    def auto_format_live(self):
        if not self.current_file_path:
            return
        lang = self.detect_language(self.current_file_path)
        cursor = self.editor.textCursor()
        pos = cursor.position()
        raw_code = self.editor.toPlainText()
        formatted = self.auto_format_code(raw_code, lang)
        if formatted != raw_code:
            self.editor.blockSignals(True)
            self.editor.setPlainText(formatted)
            cursor.setPosition(min(pos, len(formatted)))
            self.editor.setTextCursor(cursor)
            self.editor.blockSignals(False)

    def new_file(self):
        self.editor.clear()
        self.current_file_path = None
        self.setWindowTitle("SANIX IDE - Untitled")
        self.editor.document().setModified(False)

    def save_file(self):
        if not self.current_project_path:
            self.show_message("Error", "Debes seleccionar un proyecto antes de guardar.")
            return False

        if not self.current_file_path:
            name, ok = QInputDialog.getText(self, "Guardar archivo", "Nombre del archivo:")
            if not ok or not name.strip():
                return False
            self.current_file_path = os.path.join(self.current_project_path, name.strip())

        lang = self.detect_language(self.current_file_path)
        raw_code = self.editor.toPlainText()
        formatted_code = self.auto_format_code(raw_code, lang)
        with open(self.current_file_path, 'w', encoding='utf-8') as f:
            f.write(formatted_code)
        self.setWindowTitle(f"SANIX IDE - {os.path.basename(self.current_file_path)} [{lang}]")
        self.editor.document().setModified(False)
        self.statusBar.showMessage(f"Archivo guardado en {self.current_project_path}", 3000)
        return True

    def execute_or_open_file(self):
        if not self.current_file_path:
            self.show_message("Archivo no guardado", "Guarda el archivo antes de ejecutar.")
            return
        self.save_file()
        _, extension = os.path.splitext(self.current_file_path)
        extension = extension.lower()
        if extension == ".py":
            self.run_in_app_terminal([sys.executable, self.current_file_path])
        elif extension == ".js":
            self.run_in_app_terminal(["node", self.current_file_path])
        elif extension in [".html", ".htm"]:
            webbrowser.open("file:///" + os.path.abspath(self.current_file_path))

    def run_in_app_terminal(self, command_parts):
        if not self.is_terminal_visible:
            self.toggle_terminal()
        self.terminal.clear()
        self.terminal.append(f"> {' '.join(command_parts)}\n")
        self.executor_process = QProcess(self)
        self.executor_process.readyReadStandardOutput.connect(
            lambda: self.terminal.insertPlainText(
                self.executor_process.readAllStandardOutput().data().decode(errors='ignore')))
        self.executor_process.readyReadStandardError.connect(
            lambda: self.terminal.insertPlainText(
                self.executor_process.readAllStandardError().data().decode(errors='ignore')))
        self.executor_process.start(command_parts[0], command_parts[1:])

    # --- Apariencia ---
    def toggle_theme(self):
        self.is_dark_mode = not self.is_dark_mode
        self.setStyleSheet(DARK_STYLE_SHEET if self.is_dark_mode else LIGHT_STYLE_SHEET)

    def toggle_terminal(self):
        self.is_terminal_visible = not self.is_terminal_visible
        self.terminal.setVisible(self.is_terminal_visible)

    def show_message(self, title, message):
        QMessageBox.information(self, title, message)

# --- Punto de entrada ---
if __name__ == "__main__":
    app = QApplication(sys.argv)
    editor = SanixIDE()
    editor.show()
    sys.exit(app.exec())
