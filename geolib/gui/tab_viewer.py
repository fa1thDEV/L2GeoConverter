# -*- coding: utf-8 -*-
"""Tab 6: 2D / 3D web viewer launcher."""

import os
import threading
import time
import webbrowser
from tkinter import (
    Frame, Label, Button, StringVar, ttk, filedialog, messagebox,
)

from ..viewer import cmd_view


class ViewerTabMixin:
    """Web Viewer tab."""

    # =========================================================================
    # TAB 6: 2D / 3D VIEWER
    # =========================================================================
    def _setup_tab_viewer(self):
        f = self.tab_viewer

        lbl1 = Label(f, text="Geodata Folder to View / Папка с геодатой для просмотра:", font=("Segoe UI", 9, "bold"))
        lbl1.pack(anchor="w", pady=(0, 2))

        in_frame = Frame(f)
        in_frame.pack(fill="x", pady=(0, 10))
        self.view_src_var = StringVar()
        e1 = ttk.Entry(in_frame, textvariable=self.view_src_var, font=("Segoe UI", 9))
        e1.pack(side="left", fill="x", expand=True, padx=(0, 6))

        btn_dir = ttk.Button(in_frame, text="Choose Geodata Folder...", command=self._browse_view_dir)
        btn_dir.pack(side="left", padx=2)

        info_box = ttk.LabelFrame(f, text=" Features / Возможности веб-просмотрщика ", padding=10)
        info_box.pack(fill="x", pady=8)

        desc = (
            "- Local embedded web server on http://127.0.0.1:8777\n"
            "- Interactive map grid: inspect 8x8 blocks & layers\n"
            "- Layer slicing: view heights, NSWE passable borders, and multilayer ceilings\n"
            "- 3D wireframe mesh overlays when pointing to client Maps/StaticMeshes\n"
            "- Works with any modern web browser"
        )
        Label(info_box, text=desc, justify="left", font=("Segoe UI", 9), fg="#333333").pack(anchor="w")

        self.btn_run_viewer = Button(
            f, text="LAUNCH VIEWER IN BROWSER / ОТКРЫТЬ В БРАУЗЕРЕ",
            font=("Segoe UI", 10, "bold"),
            bg="#17a2b8", fg="white", activebackground="#138496", activeforeground="white",
            relief="raised", padx=12, pady=8, cursor="hand2",
            command=self._execute_viewer
        )
        self.btn_run_viewer.pack(fill="x", pady=10)

    def _browse_view_dir(self):
        d = filedialog.askdirectory(title="Select Geodata Folder to View")
        if d:
            self.view_src_var.set(d)

    def _execute_viewer(self):
        d = self.view_src_var.get().strip()
        if not d or not os.path.exists(d):
            messagebox.showerror("Error", "Please select a valid folder containing geodata.")
            return

        print("\n[VIEWER] Starting local 2D/3D viewer server on http://127.0.0.1:8777 ...")
        threading.Thread(target=lambda: cmd_view(d, port=8777), daemon=True).start()

        def _open_browser():
            time.sleep(1.2)
            try:
                webbrowser.open("http://127.0.0.1:8777")
            except Exception:
                pass
        threading.Thread(target=_open_browser, daemon=True).start()
