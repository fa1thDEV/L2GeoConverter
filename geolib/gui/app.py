# -*- coding: utf-8 -*-
"""Main window: header, tab notebook and live console.

Each tab lives in its own module (tab_*.py) as a mixin; this class wires
them together and owns the shared state (stop event, running flag, console).
"""

import os
import sys
import threading
from tkinter import Tk, Frame, Label, Button, StringVar, ttk, Text, PhotoImage

from .common import APP_DIR, HAS_PIL, PILImage, ImageTk, TextRedirector

from .guide import GuideWindowMixin
from .tab_convert import ConvertTabMixin
from .tab_diagnose import DiagnoseTabMixin
from .tab_generate import GenerateTabMixin
from .tab_diff import DiffTabMixin
from .tab_spawns import SpawnsTabMixin
from .tab_viewer import ViewerTabMixin
from .tab_editor import EditorTabMixin


class L2GeoConverterGUI(
    GuideWindowMixin,
    ConvertTabMixin,
    DiagnoseTabMixin,
    GenerateTabMixin,
    DiffTabMixin,
    SpawnsTabMixin,
    ViewerTabMixin,
    EditorTabMixin,
):
    def __init__(self, root):
        self.root = root
        self.root.title("L2 Geodata Converter")
        self.root.geometry("920x760")
        self.root.minsize(820, 620)

        # On Windows, hide background terminal window when launched as GUI
        if sys.platform == "win32":
            try:
                import ctypes
                hwnd = ctypes.windll.kernel32.GetConsoleWindow()
                if hwnd:
                    ctypes.windll.user32.ShowWindow(hwnd, 0)
            except Exception:
                pass

        # Apply ttk modern style
        self.style = ttk.Style()
        try:
            self.style.theme_use('clam')
        except Exception:
            pass

        self.stop_event = threading.Event()
        self.is_running = False
        self._action_buttons = []
        self._stop_buttons = []

        self._init_header()
        self._init_tabs()
        self._init_console()

        self._action_buttons = [
            self.btn_run_conv,
            self.btn_run_diag,
            self.btn_run_gen,
            self.btn_run_diff,
            self.btn_run_spawn
        ]

        # Redirect standard output to console log
        self.redirector = TextRedirector(self.console, self.root)
        sys.stdout = self.redirector
        sys.stderr = self.redirector

        print("L2 Geodata Converter initialized.")
        print("Ready. Select a tab above to begin.")

    def _set_running(self, running: bool, task_name: str = ""):
        self.is_running = running
        if running:
            self.stop_event.clear()
            self.status_var.set(f"● Running ({task_name})...")
            self.lbl_status.config(fg="#e5c07b")
            self.btn_stop.config(state="normal", bg="#e06c75")
            for b in self._stop_buttons:
                b.config(state="normal", bg="#e06c75")
            for b in self._action_buttons:
                b.config(state="disabled")
        else:
            self.stop_event.clear()
            self.status_var.set("● Ready")
            self.lbl_status.config(fg="#98c379")
            self.btn_stop.config(state="disabled", bg="#5c6370")
            for b in self._stop_buttons:
                b.config(state="disabled", bg="#5c6370")
            for b in self._action_buttons:
                b.config(state="normal")

    def _request_stop(self):
        if self.is_running:
            self.stop_event.set()
            self.status_var.set("● Stopping...")
            self.lbl_status.config(fg="#e06c75")
            self.btn_stop.config(state="disabled", bg="#5c6370")
            for b in self._stop_buttons:
                b.config(state="disabled", bg="#5c6370")
            print("\n[STOP] Stop requested by user. Finishing current step and aborting...")

    def _clear_console(self):
        self.console.delete("1.0", "end")

    def _init_header(self):
        header_frame = Frame(self.root, bg="#1a1e24", pady=10)
        header_frame.pack(fill="x")

        # Load icon & logo if available (support standard execution & PyInstaller _MEIPASS)
        base_dir = getattr(sys, '_MEIPASS', APP_DIR)
        ico_path = os.path.join(base_dir, "assets", "icon.ico")
        if not os.path.exists(ico_path):
            ico_path = os.path.join(APP_DIR, "assets", "icon.ico")
        if not os.path.exists(ico_path):
            ico_path = os.path.join(os.getcwd(), "assets", "icon.ico")

        if os.path.exists(ico_path):
            try:
                self.root.iconbitmap(default=ico_path)
            except Exception:
                pass

        logo_path = os.path.join(base_dir, "assets", "logo.png")
        if not os.path.exists(logo_path):
            logo_path = os.path.join(APP_DIR, "assets", "logo.png")
        if not os.path.exists(logo_path):
            logo_path = os.path.join(os.getcwd(), "assets", "logo.png")

        if os.path.exists(logo_path):
            try:
                if HAS_PIL:
                    pil_logo = PILImage.open(logo_path).convert("RGBA")
                    resized = pil_logo.resize((72, 72), PILImage.Resampling.LANCZOS)
                    self.logo_img = ImageTk.PhotoImage(resized)
                    self.icon_photo = ImageTk.PhotoImage(pil_logo.resize((64, 64), PILImage.Resampling.LANCZOS))
                    self.root.iconphoto(True, self.icon_photo)
                else:
                    raw_img = PhotoImage(file=logo_path)
                    self.root.iconphoto(True, raw_img)
                    sub_x = max(1, raw_img.width() // 80)
                    sub_y = max(1, raw_img.height() // 80)
                    self.logo_img = raw_img.subsample(sub_x, sub_y)

                logo_lbl = Label(header_frame, image=self.logo_img, bg="#1a1e24")
                logo_lbl.pack(pady=(0, 4))
            except Exception:
                pass

        title_lbl = Label(
            header_frame,
            text="L2 Geodata Converter",
            font=("Segoe UI", 13, "bold"),
            fg="#61afef",
            bg="#1a1e24"
        )
        title_lbl.pack()

        sub_lbl = Label(
            header_frame,
            text="Lucera 2 (.l2g) · L2J (.l2j) · PTS (_conv.dat) · UNR Maps",
            font=("Segoe UI", 9),
            fg="#abb2bf",
            bg="#1a1e24"
        )
        sub_lbl.pack()

        # Guide & Documentation button
        btn_guide = Button(
            header_frame,
            text="📖 User Guide & Visual Examples / Руководство / Guía",
            font=("Segoe UI", 9, "bold"),
            bg="#2c313a", fg="#61afef", activebackground="#3e4451", activeforeground="#98c379",
            relief="groove", padx=12, pady=3, cursor="hand2",
            command=self._open_guide_window
        )
        btn_guide.pack(pady=(6, 0))


    def _init_tabs(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=8)

        # Tab 1: Converter
        self.tab_convert = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(self.tab_convert, text=" Format Converter / Конвертер ")
        self._setup_tab_convert()

        # Tab 2: Diagnostics & Auto-Repair
        self.tab_diagnose = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(self.tab_diagnose, text=" Diagnostics & Repair / Диагностика ")
        self._setup_tab_diagnose()

        # Tab 3: UNR / Client Generator
        self.tab_generate = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(self.tab_generate, text=" Generate from UNR / Генератор ")
        self._setup_tab_generate()

        # Tab 4: Pack Comparison (Diff)
        self.tab_diff = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(self.tab_diff, text=" Pack Diff / Сравнение ")
        self._setup_tab_diff()

        # Tab 5: Spawn Validator (SpawnCheck)
        self.tab_spawns = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(self.tab_spawns, text=" Spawn Validator / Спавны ")
        self._setup_tab_spawns()

        # Tab 6: 2D/3D Viewer
        self.tab_viewer = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(self.tab_viewer, text=" Web Viewer / Просмотрщик ")
        self._setup_tab_viewer()

        # Tab 7: Geo Editor Tools (Shift Z, Shift XY, Delete Z-Range, Slope, Live Scanner)
        self.tab_editor = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(self.tab_editor, text=" Geo Editor / Редактор ")
        self._setup_tab_editor()


    # =========================================================================
    # CONSOLE & STATUS LOG
    # =========================================================================
    def _init_console(self):
        console_frame = ttk.LabelFrame(self.root, text=" Live Activity & Status Log / Журнал событий ", padding=6)
        console_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # Activity control toolbar
        toolbar = Frame(console_frame, bg="#2d3139", pady=3, padx=6)
        toolbar.pack(fill="x", side="top", pady=(0, 4))

        self.status_var = StringVar(value="● Ready")
        self.lbl_status = Label(
            toolbar, textvariable=self.status_var,
            font=("Segoe UI", 9, "bold"), fg="#98c379", bg="#2d3139"
        )
        self.lbl_status.pack(side="left")

        self.btn_stop = Button(
            toolbar, text="■ STOP / СТОП",
            font=("Segoe UI", 9, "bold"),
            bg="#5c6370", fg="white", activebackground="#e06c75", activeforeground="white",
            state="disabled", relief="flat", padx=10, pady=1, cursor="hand2",
            command=self._request_stop
        )
        self.btn_stop.pack(side="right", padx=(4, 0))

        btn_clear = ttk.Button(toolbar, text="Clear Log", command=self._clear_console)
        btn_clear.pack(side="right", padx=4)

        text_frame = Frame(console_frame)
        text_frame.pack(fill="both", expand=True)

        self.console = Text(
            text_frame,
            wrap="word",
            bg="#1e1e1e",
            fg="#d4d4d4",
            insertbackground="white",
            font=("Consolas", 9),
            height=9
        )
        scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=self.console.yview)
        self.console.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        self.console.pack(side="left", fill="both", expand=True)


def main():
    root = Tk()
    L2GeoConverterGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
