#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L2 Geodata Converter - Graphical User Interface
(c) fa1thDEV & L2GeoConverter Contributors
"""

import glob
import os
import re
import sys
import threading
import time
import webbrowser
from tkinter import (
    Tk, Toplevel, Frame, Label, Button, Entry, StringVar, BooleanVar, ttk,
    filedialog, messagebox, Text, Scrollbar, Canvas, PhotoImage
)

try:
    from PIL import Image as PILImage, ImageTk
    HAS_PIL = True
except Exception:
    HAS_PIL = False

# Ensure geolib can be imported
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from geolib.convert import (
    cmd_convert, cmd_l2j2pts, cmd_l2g2l2j, cmd_l2j2l2g,
    cmd_l2g2pts, cmd_pts2l2g, l2g2l2j_file, l2j2l2g_file,
    l2g2pts_file, pts2l2g_file, convert_file, l2j2pts_bytes
)
from geolib.diagnostics import GeoDiagnosticEngine
from geolib.diff import cmd_diff
from geolib.formats import sniff_format, region_of, PROTO_GD
from geolib.generate import cmd_generate
from geolib.spawncheck import cmd_spawncheck
from geolib.viewer import cmd_view
from geolib.editor import (
    shift_z_blocks, shift_xy_blocks, delete_z_range_blocks,
    recalculate_slope_flags, save_edited_region, L2ClientMemoryScanner
)
from geolib.formats import parse_region


class TextRedirector:
    """Redirects stdout to a Tkinter Text widget safely across threads."""
    def __init__(self, widget, root):
        self.widget = widget
        self.root = root

    def write(self, text):
        clean_text = re.sub(r'\x1b\[[0-9;]*[mK]', '', text)
        clean_text = clean_text.replace('\r', '')
        if clean_text:
            self.root.after(0, self._append, clean_text)

    def _append(self, text):
        try:
            self.widget.insert("end", text)
            self.widget.see("end")
        except Exception:
            pass

    def flush(self):
        pass


class L2GeoConverterGUI:
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

        # Load logo if available (support standard execution & PyInstaller _MEIPASS)
        base_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.realpath(__file__)))
        logo_path = os.path.join(base_dir, "assets", "logo.png")
        if not os.path.exists(logo_path):
            logo_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "assets", "logo.png")
        if not os.path.exists(logo_path):
            logo_path = os.path.join(os.getcwd(), "assets", "logo.png")

        if os.path.exists(logo_path):
            try:
                raw_img = PhotoImage(file=logo_path)
                self.root.iconphoto(True, raw_img)
                # Downsample image cleanly to fit header
                sub_x = max(1, raw_img.width() // 280)
                sub_y = max(1, raw_img.height() // 95)
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

    def _open_guide_window(self):
        guide_win = Toplevel(self.root)
        guide_win.title("L2 Geodata Converter - Visual Guide & Mechanics")
        guide_win.geometry("1020x780")
        guide_win.minsize(860, 640)
        guide_win._cached_images = []

        # Header banner in guide window
        top_bar = Frame(guide_win, bg="#1a1e24", pady=10, padx=16)
        top_bar.pack(fill="x")
        Label(
            top_bar,
            text="Geodata Engineering & Mechanics Guide",
            font=("Segoe UI", 13, "bold"),
            fg="#61afef", bg="#1a1e24"
        ).pack(anchor="w")
        Label(
            top_bar,
            text="Visual reference: NSWE collision flags, creating invisible walls, cliff drops, and block structures.",
            font=("Segoe UI", 9),
            fg="#abb2bf", bg="#1a1e24"
        ).pack(anchor="w", pady=(2, 0))

        # Notebook for topics
        guide_nb = ttk.Notebook(guide_win)
        guide_nb.pack(fill="both", expand=True, padx=10, pady=8)

        # Helper to create a scrollable tab
        def create_scroll_tab(parent, tab_title):
            tab = ttk.Frame(parent, padding=6)
            parent.add(tab, text=tab_title)

            canvas = Canvas(tab, bg="#181a1f", highlightthickness=0)
            scrollbar = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview)
            scroll_frame = Frame(canvas, bg="#181a1f", padx=10, pady=10)

            scroll_frame.bind(
                "<Configure>",
                lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
            )
            cw = canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
            canvas.bind("<Configure>", lambda e: canvas.itemconfig(cw, width=e.width))

            canvas.configure(yscrollcommand=scrollbar.set)
            scrollbar.pack(side="right", fill="y")
            canvas.pack(side="left", fill="both", expand=True)

            def _on_mousewheel(event):
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            canvas.bind("<MouseWheel>", _on_mousewheel)
            scroll_frame.bind("<MouseWheel>", _on_mousewheel)

            return scroll_frame

        # Helper to add image
        def add_diagram_image(frame, filename):
            base_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.realpath(__file__)))
            img_path = os.path.join(base_dir, "assets", filename)
            if not os.path.exists(img_path):
                img_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "assets", filename)
            if not os.path.exists(img_path):
                img_path = os.path.join(os.getcwd(), "assets", filename)
            if not os.path.exists(img_path):
                img_path = os.path.join(os.getcwd(), "docs", "images", filename)

            if os.path.exists(img_path) and HAS_PIL:
                try:
                    pil_img = PILImage.open(img_path)
                    max_w = 940
                    if pil_img.width > max_w:
                        ratio = max_w / pil_img.width
                        new_h = int(pil_img.height * ratio)
                        pil_img = pil_img.resize((max_w, new_h), PILImage.Resampling.LANCZOS)
                    photo = ImageTk.PhotoImage(pil_img)
                    guide_win._cached_images.append(photo)
                    lbl = Label(frame, image=photo, bg="#181a1f")
                    lbl.pack(pady=(4, 12))
                except Exception as e:
                    Label(frame, text=f"[Image preview unavailable: {e}]", font=("Segoe UI", 9), fg="#e06c75", bg="#181a1f").pack()

        # TAB 1: Invisible Barriers
        t1 = create_scroll_tab(guide_nb, " 1. Invisible Barriers & NSWE / Невидимые стены ")
        add_diagram_image(t1, "guide_barriers.png")
        desc_card1 = ttk.LabelFrame(t1, text=" How to Create Invisible Walls in Lineage 2 ", padding=10)
        desc_card1.pack(fill="x", pady=6)
        text_b1 = (
            "1. Directional Invisible Wall (Flat Ground):\n"
            "   • Keep ground height identical on both cells (e.g. Z = 100).\n"
            "   • On Cell A (gx, gy): remove FLAG_EAST (0x01): nswe &= ~0x01\n"
            "   • On Cell B (gx+1, gy): remove FLAG_WEST (0x02): nswe &= ~0x02\n"
            "   • Result: The client draws flat open ground, but the server collision matrix halts character packets.\n\n"
            "2. Solid Column / Impenetrable Area (16x16):\n"
            "   • Set target cell NSWE = 0x00 (FLAG_NONE).\n"
            "   • Characters cannot enter this cell from North, South, East, or West. Ideal for arenas and props.\n\n"
            "3. One-Way Wall Bug (NSWE_ASYMMETRY):\n"
            "   • If Cell A permits East entry but Cell B denies West return, players become trapped inside Cell B.\n"
            "   • Run Diagnostics with Auto-Repair enabled to fix all asymmetric traps automatically."
        )
        Label(desc_card1, text=text_b1, justify="left", font=("Segoe UI", 9), fg="#d4d4d4", bg="#1e1e24").pack(anchor="w")

        # TAB 2: Cliff Drops & Arches
        t2 = create_scroll_tab(guide_nb, " 2. Cliff Falls & Archways / Обрывы и арки ")
        add_diagram_image(t2, "guide_cliffs.png")
        desc_card2 = ttk.LabelFrame(t2, text=" Elevation Drops & Archway Preservation (Giran Fix) ", padding=10)
        desc_card2.pack(fill="x", pady=6)
        text_b2 = (
            "1. Hazardous Cliff Drops (|ΔZ| > 48):\n"
            "   • Adjacent cells with a drop over 48 units and open passage flags cause characters to plummet through geometry into the ocean.\n"
            "   • The repair engine seals the directional flag on the upper cell facing the drop.\n\n"
            "2. City Arches & Doorways (The Giran Bug Fix):\n"
            "   • Under archways (Giran luxury gate, Dion arches), cells have multiple layers: Ground (Z=96) and Arch Roof (Z=384).\n"
            "   • The outdoor street cell only has Ground (Z=96).\n"
            "   • Naive tools compare closest layers (384 vs 96 = drop 288u) and strip passage on BOTH cells, bricking the gate!\n"
            "   • L2GeoConverter applies cliff blocking strictly to the higher layer towards the drop.\n"
            "   • Ground level (Z=96 <-> Z=96) retains full bidirectional walkability!"
        )
        Label(desc_card2, text=text_b2, justify="left", font=("Segoe UI", 9), fg="#d4d4d4", bg="#1e1e24").pack(anchor="w")

        # TAB 3: Block Architecture
        t3 = create_scroll_tab(guide_nb, " 3. Block Formats & Clearance / Структура блоков ")
        add_diagram_image(t3, "guide_blocks.png")
        desc_card3 = ttk.LabelFrame(t3, text=" Block Types & Layer Clearance Rules ", padding=10)
        desc_card3.pack(fill="x", pady=6)
        text_b3 = (
            "• Type 0 (Flat): 1 height for all 64 cells. 2 bytes per block on disk. Used for plains and calm water.\n"
            "• Type 1 (Complex): 64 independent cells, each with 16-bit Z and 4-bit NSWE (128 bytes per block).\n"
            "• Type 2 (Multilayer): Variable layers per cell (bridges, castles, multi-floor dungeons).\n"
            "• Vertical Clearance Rule: Consecutive layers must have >= 32 units gap to avoid camera clipping and stuck rubberbanding.\n"
            "• Supported formats: Lucera 2 (.l2g), standard L2J (.l2j), and official PTS / L2Off (_conv.dat gd/286)."
        )
        Label(desc_card3, text=text_b3, justify="left", font=("Segoe UI", 9), fg="#d4d4d4", bg="#1e1e24").pack(anchor="w")

        # TAB 4: Workflow
        t4 = create_scroll_tab(guide_nb, " 4. Workflow & Controls / Инструкция ")
        add_diagram_image(t4, "guide_workflow.png")
        desc_card4 = ttk.LabelFrame(t4, text=" Execution Pipeline & Stop Controls ", padding=10)
        desc_card4.pack(fill="x", pady=6)
        text_b4 = (
            "• Format Converter: Select files or whole folders and convert between .l2g, .l2j, and PTS.\n"
            "• Diagnostics & Auto-Repair: Scans and neutralizes cliff falls and asymmetric walls in place.\n"
            "• UNR Generator: Extracts heightmaps and 3D mesh collisions directly from client Maps/XX_YY.unr packages.\n"
            "• Pack Diff: Analyzes elevation differences and directional divergence between two packs.\n"
            "• Spawn Validator: Verifies npcpos.txt fixed coordinates and territories against solid ground.\n"
            "• STOP Button: Safely cancels any background task without corrupting target files."
        )
        Label(desc_card4, text=text_b4, justify="left", font=("Segoe UI", 9), fg="#d4d4d4", bg="#1e1e24").pack(anchor="w")

        # Bottom Bar with buttons
        bot_bar = Frame(guide_win, bg="#1a1e24", pady=8, padx=12)
        bot_bar.pack(fill="x")

        def _open_github():
            webbrowser.open("https://github.com/fa1thDEV/L2GeoConverter")

        def _open_local():
            guide_md = os.path.join(os.path.dirname(os.path.realpath(__file__)), "docs", "GUIDE.md")
            if os.path.exists(guide_md):
                if sys.platform == "win32":
                    os.startfile(guide_md)
                else:
                    webbrowser.open(f"file://{guide_md}")
            else:
                _open_github()

        btn_gh = ttk.Button(bot_bar, text="Open Online GitHub Guide", command=_open_github)
        btn_gh.pack(side="left", padx=4)

        btn_loc = ttk.Button(bot_bar, text="Open Local GUIDE.md", command=_open_local)
        btn_loc.pack(side="left", padx=4)

        btn_close = Button(
            bot_bar, text="Close / Закрыть",
            font=("Segoe UI", 9, "bold"),
            bg="#3e4451", fg="white", activebackground="#4b5263", activeforeground="white",
            relief="raised", padx=14, pady=2, cursor="hand2",
            command=guide_win.destroy
        )
        btn_close.pack(side="right", padx=4)

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
    # TAB 1: FORMAT CONVERTER
    # =========================================================================
    def _setup_tab_convert(self):
        f = self.tab_convert

        # Source input
        lbl1 = Label(f, text="Source Geodata (File or Folder) / Исходные файлы или папка:", font=("Segoe UI", 9, "bold"))
        lbl1.pack(anchor="w", pady=(0, 2))

        in_frame = Frame(f)
        in_frame.pack(fill="x", pady=(0, 8))
        self.conv_src_var = StringVar()
        e1 = ttk.Entry(in_frame, textvariable=self.conv_src_var, font=("Segoe UI", 9))
        e1.pack(side="left", fill="x", expand=True, padx=(0, 6))

        btn_file = ttk.Button(in_frame, text="Choose File...", command=self._browse_conv_file)
        btn_file.pack(side="left", padx=2)
        btn_dir = ttk.Button(in_frame, text="Choose Folder...", command=self._browse_conv_dir)
        btn_dir.pack(side="left", padx=2)

        # Target Format Selection
        fmt_frame = ttk.LabelFrame(f, text=" Target Format / Целевой формат ", padding=8)
        fmt_frame.pack(fill="x", pady=6)

        self.conv_target_fmt = StringVar(value="l2j")
        rb1 = ttk.Radiobutton(fmt_frame, text="Lucera 2 (.l2g) — Encrypted server format", variable=self.conv_target_fmt, value="l2g")
        rb1.pack(anchor="w", pady=2)
        rb2 = ttk.Radiobutton(fmt_frame, text="L2J (.l2j) — Standard Java emulator format", variable=self.conv_target_fmt, value="l2j")
        rb2.pack(anchor="w", pady=2)
        rb3 = ttk.Radiobutton(fmt_frame, text="PTS / L2Off (_conv.dat) — Official NCSoft format", variable=self.conv_target_fmt, value="pts")
        rb3.pack(anchor="w", pady=2)

        # Destination folder
        lbl2 = Label(f, text="Output Directory / Папка сохранения:", font=("Segoe UI", 9, "bold"))
        lbl2.pack(anchor="w", pady=(8, 2))

        out_frame = Frame(f)
        out_frame.pack(fill="x", pady=(0, 10))
        self.conv_dst_var = StringVar()
        e2 = ttk.Entry(out_frame, textvariable=self.conv_dst_var, font=("Segoe UI", 9))
        e2.pack(side="left", fill="x", expand=True, padx=(0, 6))
        btn_out = ttk.Button(out_frame, text="Browse...", command=self._browse_conv_out)
        btn_out.pack(side="left")

        # Action Buttons
        btn_box = Frame(f)
        btn_box.pack(fill="x", pady=4)

        self.btn_run_conv = Button(
            btn_box, text="START CONVERSION / НАЧАТЬ КОНВЕРТАЦИЮ",
            font=("Segoe UI", 10, "bold"),
            bg="#28a745", fg="white", activebackground="#218838", activeforeground="white",
            relief="raised", padx=12, pady=6, cursor="hand2",
            command=self._execute_conversion
        )
        self.btn_run_conv.pack(side="left", fill="x", expand=True, padx=(0, 4))

        btn_stop_conv = Button(
            btn_box, text="■ STOP / СТОП",
            font=("Segoe UI", 10, "bold"),
            bg="#5c6370", fg="white", activebackground="#e06c75", activeforeground="white",
            state="disabled", relief="raised", padx=14, pady=6, cursor="hand2",
            command=self._request_stop
        )
        btn_stop_conv.pack(side="right")
        self._stop_buttons.append(btn_stop_conv)

    def _browse_conv_file(self):
        f = filedialog.askopenfilename(
            title="Select Geodata File",
            filetypes=[("Lineage 2 Geodata", "*.l2g;*.l2j;*_conv.dat;*.dat"), ("All Files", "*.*")]
        )
        if f:
            self.conv_src_var.set(f)
            if not self.conv_dst_var.get():
                self.conv_dst_var.set(os.path.join(os.path.dirname(f), "converted"))

    def _browse_conv_dir(self):
        d = filedialog.askdirectory(title="Select Geodata Folder")
        if d:
            self.conv_src_var.set(d)
            if not self.conv_dst_var.get():
                self.conv_dst_var.set(os.path.join(d, "converted"))

    def _browse_conv_out(self):
        d = filedialog.askdirectory(title="Select Output Folder")
        if d:
            self.conv_dst_var.set(d)

    def _execute_conversion(self):
        src = self.conv_src_var.get().strip()
        dst = self.conv_dst_var.get().strip()
        target_fmt = self.conv_target_fmt.get()

        if not src or not os.path.exists(src):
            messagebox.showerror("Error", "Please select a valid source file or folder.")
            return
        if not dst:
            dst = os.path.join(os.path.dirname(src) if os.path.isfile(src) else src, "converted")
            self.conv_dst_var.set(dst)

        self._set_running(True, "Conversion")

        def worker():
            try:
                os.makedirs(dst, exist_ok=True)
                files = [src] if os.path.isfile(src) else [
                    os.path.join(src, f) for f in os.listdir(src) if sniff_format(f)
                ]
                print(f"\n[CONVERTER] Processing {len(files)} files -> Target: {target_fmt.upper()} ...")

                success = 0
                for f in sorted(files):
                    if self.stop_event.is_set():
                        print(f"\n[CONVERTER] Conversion cancelled by user ({success}/{len(files)} files completed).")
                        break
                    fname = os.path.basename(f)
                    base_name = os.path.splitext(fname)[0].replace('_conv', '')
                    in_fmt = sniff_format(fname)
                    if not in_fmt:
                        continue

                    # Direct / intermediate conversion
                    if target_fmt == "l2j":
                        out_path = os.path.join(dst, f"{base_name}.l2j")
                        if os.path.abspath(f) == os.path.abspath(out_path):
                            print(f"  ⚠ Skipping {fname}: source and destination are the same file.")
                            continue
                        if in_fmt == "l2g":
                            l2g2l2j_file(f, out_path)
                        elif in_fmt == "pts":
                            convert_file(f, out_path)
                        elif in_fmt == "l2j":
                            open(out_path, 'wb').write(open(f, 'rb').read())
                    elif target_fmt == "l2g":
                        out_path = os.path.join(dst, f"{base_name}.l2g")
                        if os.path.abspath(f) == os.path.abspath(out_path):
                            print(f"  ⚠ Skipping {fname}: source and destination are the same file.")
                            continue
                        if in_fmt == "l2g":
                            open(out_path, 'wb').write(open(f, 'rb').read())
                        elif in_fmt == "l2j":
                            l2j2l2g_file(f, out_path)
                        elif in_fmt == "pts":
                            rx, ry = region_of(f)
                            pts2l2g_file(f, out_path, rx, ry)
                    elif target_fmt == "pts":
                        out_path = os.path.join(dst, f"{base_name}_conv.dat")
                        if os.path.abspath(f) == os.path.abspath(out_path):
                            print(f"  ⚠ Skipping {fname}: source and destination are the same file.")
                            continue
                        rx, ry = region_of(f)
                        if in_fmt == "pts":
                            open(out_path, 'wb').write(open(f, 'rb').read())
                        elif in_fmt == "l2g":
                            l2g2pts_file(f, out_path, rx, ry)
                        elif in_fmt == "l2j":
                            data = open(f, 'rb').read()
                            pts_bytes, _, _, _ = l2j2pts_bytes(data, rx, ry, PROTO_GD)
                            open(out_path, 'wb').write(pts_bytes)

                    print(f"  ✓ Converted: {fname} -> {os.path.basename(out_path)}")
                    success += 1

                if self.stop_event.is_set():
                    self.root.after(0, lambda: messagebox.showwarning("Cancelled", f"Conversion stopped by user.\n{success} files saved in:\n{dst}"))
                else:
                    print(f"\n[CONVERTER] Finished! {success} files converted successfully to: {dst}\n")
                    self.root.after(0, lambda: messagebox.showinfo("Success", f"Conversion completed!\n{success} files saved in:\n{dst}"))
            except Exception as e:
                print(f"[ERROR] Conversion failed: {e}")
                self.root.after(0, lambda: messagebox.showerror("Error", f"Conversion error:\n{e}"))
            finally:
                self.root.after(0, lambda: self._set_running(False))

        threading.Thread(target=worker, daemon=True).start()

    # =========================================================================
    # TAB 2: DIAGNOSTICS & REPAIR
    # =========================================================================
    def _setup_tab_diagnose(self):
        f = self.tab_diagnose

        lbl1 = Label(f, text="Geodata to Analyze / Файлы геодаты для проверки:", font=("Segoe UI", 9, "bold"))
        lbl1.pack(anchor="w", pady=(0, 2))

        in_frame = Frame(f)
        in_frame.pack(fill="x", pady=(0, 8))
        self.diag_src_var = StringVar()
        e1 = ttk.Entry(in_frame, textvariable=self.diag_src_var, font=("Segoe UI", 9))
        e1.pack(side="left", fill="x", expand=True, padx=(0, 6))

        btn_file = ttk.Button(in_frame, text="Choose File...", command=self._browse_diag_file)
        btn_file.pack(side="left", padx=2)
        btn_dir = ttk.Button(in_frame, text="Choose Folder...", command=self._browse_diag_dir)
        btn_dir.pack(side="left", padx=2)

        # Options
        opt_frame = ttk.LabelFrame(f, text=" Repair Options / Настройки исправления ", padding=8)
        opt_frame.pack(fill="x", pady=6)

        self.diag_fix_var = BooleanVar(value=True)
        cb_fix = ttk.Checkbutton(
            opt_frame,
            text="Auto-Repair detected issues (Seals cliff falls, fixes asymmetric walls) / Исправлять найденные ошибки",
            variable=self.diag_fix_var
        )
        cb_fix.pack(anchor="w", pady=2)

        lbl2 = Label(f, text="Repaired Geodata Output Directory / Папка для исправленных файлов:", font=("Segoe UI", 9, "bold"))
        lbl2.pack(anchor="w", pady=(8, 2))

        out_frame = Frame(f)
        out_frame.pack(fill="x", pady=(0, 10))
        self.diag_dst_var = StringVar()
        e2 = ttk.Entry(out_frame, textvariable=self.diag_dst_var, font=("Segoe UI", 9))
        e2.pack(side="left", fill="x", expand=True, padx=(0, 6))
        btn_out = ttk.Button(out_frame, text="Browse...", command=self._browse_diag_out)
        btn_out.pack(side="left")

        # Action Buttons
        btn_box = Frame(f)
        btn_box.pack(fill="x", pady=4)

        self.btn_run_diag = Button(
            btn_box, text="RUN DIAGNOSTICS & REPAIR / ЗАПУСТИТЬ ПРОВЕРКУ И РЕМОНТ",
            font=("Segoe UI", 10, "bold"),
            bg="#007acc", fg="white", activebackground="#005999", activeforeground="white",
            relief="raised", padx=12, pady=6, cursor="hand2",
            command=self._execute_diagnostics
        )
        self.btn_run_diag.pack(side="left", fill="x", expand=True, padx=(0, 4))

        btn_stop_diag = Button(
            btn_box, text="■ STOP / СТОП",
            font=("Segoe UI", 10, "bold"),
            bg="#5c6370", fg="white", activebackground="#e06c75", activeforeground="white",
            state="disabled", relief="raised", padx=14, pady=6, cursor="hand2",
            command=self._request_stop
        )
        btn_stop_diag.pack(side="right")
        self._stop_buttons.append(btn_stop_diag)

    def _browse_diag_file(self):
        f = filedialog.askopenfilename(
            title="Select Geodata to Diagnose",
            filetypes=[("Lineage 2 Geodata", "*.l2g;*.l2j;*_conv.dat;*.dat"), ("All Files", "*.*")]
        )
        if f:
            self.diag_src_var.set(f)
            if not self.diag_dst_var.get():
                self.diag_dst_var.set(os.path.join(os.path.dirname(f), "repaired"))

    def _browse_diag_dir(self):
        d = filedialog.askdirectory(title="Select Geodata Folder")
        if d:
            self.diag_src_var.set(d)
            if not self.diag_dst_var.get():
                self.diag_dst_var.set(os.path.join(d, "repaired"))

    def _browse_diag_out(self):
        d = filedialog.askdirectory(title="Select Output Folder")
        if d:
            self.diag_dst_var.set(d)

    def _execute_diagnostics(self):
        src = self.diag_src_var.get().strip()
        dst = self.diag_dst_var.get().strip()
        do_fix = self.diag_fix_var.get()

        if not src or not os.path.exists(src):
            messagebox.showerror("Error", "Please select a valid geodata file or folder.")
            return

        self._set_running(True, "Diagnostics")

        def worker():
            try:
                engine = GeoDiagnosticEngine(cliff_threshold=48)
                files = [src] if os.path.isfile(src) else [
                    os.path.join(src, f) for f in os.listdir(src) if sniff_format(f)
                ]

                print(f"\n[DIAGNOSTICS] Analyzing {len(files)} geodata regions...")
                total_cliffs = 0
                total_asym = 0
                total_fixed_cliffs = 0
                total_fixed_walls = 0

                for f in sorted(files):
                    if self.stop_event.is_set():
                        print("\n[DIAGNOSTICS] Analysis stopped by user.")
                        break

                    rep = engine.analyze(f, stop_event=self.stop_event)
                    if self.stop_event.is_set():
                        print("\n[DIAGNOSTICS] Analysis stopped by user.")
                        break

                    st = rep["stats"]
                    total_cliffs += st["cliff_errors"]
                    total_asym += st["asymmetry_errors"]

                    print(f"\n  Region: {st['region']} ({st['format'].upper()})")
                    print(f"    • Hazardous Cliff Falls (Fall under map): {st['cliff_errors']}")
                    print(f"    • Asymmetric One-Way Walls: {st['asymmetry_errors']}")
                    print(f"    • Layer Squeeze Traps: {st['layer_squeeze_errors']}")

                    if do_fix:
                        if self.stop_event.is_set():
                            print("\n[DIAGNOSTICS] Repair stopped by user.")
                            break
                        os.makedirs(dst, exist_ok=True)
                        fixed_file = os.path.join(dst, os.path.basename(f))
                        res = engine.repair_and_save(f, fixed_file, stop_event=self.stop_event)
                        total_fixed_cliffs += res.get("cliffs_sealed", 0)
                        total_fixed_walls += res.get("asymmetries_repaired", 0)
                        if not res.get("stopped", False):
                            print(f"    ✓ Auto-repaired & saved -> {fixed_file}")

                if self.stop_event.is_set():
                    self.root.after(0, lambda: messagebox.showwarning("Cancelled", "Diagnostics stopped by user."))
                else:
                    summary_msg = (
                        f"Diagnostics Completed!\n\n"
                        f"• Dangerous Cliff Falls: {total_cliffs}\n"
                        f"• Asymmetric Walls: {total_asym}\n"
                    )
                    if do_fix:
                        summary_msg += (
                            f"\nRepair Results:\n"
                            f"✓ Cliffs Sealed: {total_fixed_cliffs}\n"
                            f"✓ Walls Fixed: {total_fixed_walls}\n"
                            f"Saved in: {dst}"
                        )

                    print("\n[DIAGNOSTICS] Summary:")
                    print(summary_msg)
                    self.root.after(0, lambda: messagebox.showinfo("Diagnosis Complete", summary_msg))
            except Exception as e:
                print(f"[ERROR] Diagnostics failed: {e}")
                self.root.after(0, lambda: messagebox.showerror("Error", f"Diagnosis error:\n{e}"))
            finally:
                self.root.after(0, lambda: self._set_running(False))

        threading.Thread(target=worker, daemon=True).start()

    # =========================================================================
    # TAB 3: GENERATE FROM UNR / CLIENT
    # =========================================================================
    def _setup_tab_generate(self):
        f = self.tab_generate

        lbl1 = Label(f, text="Select Client Maps/XX_YY.unr OR Client Root Folder:", font=("Segoe UI", 9, "bold"))
        lbl1.pack(anchor="w", pady=(0, 2))

        in_frame = Frame(f)
        in_frame.pack(fill="x", pady=(0, 8))
        self.gen_src_var = StringVar()
        e1 = ttk.Entry(in_frame, textvariable=self.gen_src_var, font=("Segoe UI", 9))
        e1.pack(side="left", fill="x", expand=True, padx=(0, 6))

        btn_unr = ttk.Button(in_frame, text="Choose .UNR File...", command=self._browse_gen_unr)
        btn_unr.pack(side="left", padx=2)
        btn_dir = ttk.Button(in_frame, text="Choose Client Dir...", command=self._browse_gen_dir)
        btn_dir.pack(side="left", padx=2)

        # Region specification
        reg_frame = Frame(f)
        reg_frame.pack(fill="x", pady=4)
        Label(reg_frame, text="Region Name (e.g. 20_20, or leave empty for all):", font=("Segoe UI", 9)).pack(side="left", padx=(0, 6))
        self.gen_region_var = StringVar()
        e_reg = ttk.Entry(reg_frame, textvariable=self.gen_region_var, width=15, font=("Segoe UI", 9))
        e_reg.pack(side="left")

        # Options
        opt_frame = ttk.LabelFrame(f, text=" Generation Options / Настройки генерации ", padding=8)
        opt_frame.pack(fill="x", pady=6)

        self.gen_terrain_only = BooleanVar(value=False)
        cb_ter = ttk.Checkbutton(
            opt_frame,
            text="Terrain only (heightmap relief only, skips 3D static meshes)",
            variable=self.gen_terrain_only
        )
        cb_ter.pack(anchor="w", pady=2)

        self.gen_target_fmt = StringVar(value="l2j")
        f_sub = Frame(opt_frame)
        f_sub.pack(fill="x", pady=4)
        Label(f_sub, text="Format:").pack(side="left", padx=(0, 8))
        ttk.Radiobutton(f_sub, text="L2J (.l2j)", variable=self.gen_target_fmt, value="l2j").pack(side="left", padx=6)
        ttk.Radiobutton(f_sub, text="Lucera 2 (.l2g)", variable=self.gen_target_fmt, value="l2g").pack(side="left", padx=6)
        ttk.Radiobutton(f_sub, text="PTS (_conv.dat)", variable=self.gen_target_fmt, value="pts").pack(side="left", padx=6)

        # Output Directory
        lbl2 = Label(f, text="Output Directory / Папка сохранения:", font=("Segoe UI", 9, "bold"))
        lbl2.pack(anchor="w", pady=(8, 2))

        out_frame = Frame(f)
        out_frame.pack(fill="x", pady=(0, 10))
        self.gen_dst_var = StringVar()
        e2 = ttk.Entry(out_frame, textvariable=self.gen_dst_var, font=("Segoe UI", 9))
        e2.pack(side="left", fill="x", expand=True, padx=(0, 6))
        btn_out = ttk.Button(out_frame, text="Browse...", command=self._browse_gen_out)
        btn_out.pack(side="left")

        # Action Buttons
        btn_box = Frame(f)
        btn_box.pack(fill="x", pady=4)

        self.btn_run_gen = Button(
            btn_box, text="GENERATE GEODATA / СГЕНЕРИРОВАТЬ ГЕОДАТУ",
            font=("Segoe UI", 10, "bold"),
            bg="#6f42c1", fg="white", activebackground="#59359a", activeforeground="white",
            relief="raised", padx=12, pady=6, cursor="hand2",
            command=self._execute_generation
        )
        self.btn_run_gen.pack(side="left", fill="x", expand=True, padx=(0, 4))

        btn_stop_gen = Button(
            btn_box, text="■ STOP / СТОП",
            font=("Segoe UI", 10, "bold"),
            bg="#5c6370", fg="white", activebackground="#e06c75", activeforeground="white",
            state="disabled", relief="raised", padx=14, pady=6, cursor="hand2",
            command=self._request_stop
        )
        btn_stop_gen.pack(side="right")
        self._stop_buttons.append(btn_stop_gen)

    def _browse_gen_unr(self):
        f = filedialog.askopenfilename(
            title="Select Client Map (.unr)",
            filetypes=[("Unreal Level Map", "*.unr"), ("All Files", "*.*")]
        )
        if f:
            self.gen_src_var.set(f)
            # Infer region name from filename (e.g. 20_20.unr -> 20_20)
            fname = os.path.basename(f)
            m = re.match(r'^(\d+_\d+)', fname)
            if m:
                self.gen_region_var.set(m.group(1))

            # Infer client folder (parent of Maps)
            parent = os.path.dirname(os.path.abspath(f))
            if os.path.basename(parent).lower() == "maps":
                client_root = os.path.dirname(parent)
                self.gen_src_var.set(client_root)
            else:
                self.gen_src_var.set(parent)

            if not self.gen_dst_var.get():
                self.gen_dst_var.set(os.path.join(os.path.dirname(f), "generated_geodata"))

    def _browse_gen_dir(self):
        d = filedialog.askdirectory(title="Select Client Folder (Containing Maps, Textures, StaticMeshes)")
        if d:
            self.gen_src_var.set(d)
            if not self.gen_dst_var.get():
                self.gen_dst_var.set(os.path.join(d, "generated_geodata"))

    def _browse_gen_out(self):
        d = filedialog.askdirectory(title="Select Output Folder")
        if d:
            self.gen_dst_var.set(d)

    def _execute_generation(self):
        src = self.gen_src_var.get().strip()
        dst = self.gen_dst_var.get().strip()
        region = self.gen_region_var.get().strip() or None
        target_fmt = self.gen_target_fmt.get()
        terrain_only = self.gen_terrain_only.get()

        if not src or not os.path.exists(src):
            messagebox.showerror("Error", "Please select a valid Client or Maps directory.")
            return
        if not dst:
            dst = os.path.join(src, "generated_geodata")
            self.gen_dst_var.set(dst)

        self._set_running(True, "Generation")

        def worker():
            try:
                os.makedirs(dst, exist_ok=True)
                print(f"\n[GENERATOR] Starting geodata generation from: {src}")
                print(f"  Target: {target_fmt.upper()}, Region: {region or 'ALL'}, Terrain Only: {terrain_only}")

                internal_fmt = "pts" if target_fmt == "pts" else "l2j"
                regions = [region] if region else None

                cmd_generate(
                    src, dst, maps=regions,
                    terrain_only=terrain_only,
                    out_fmt=internal_fmt,
                    jobs=None,
                    stop_event=self.stop_event
                )

                if self.stop_event.is_set():
                    print("\n[GENERATOR] Generation stopped by user.\n")
                    self.root.after(0, lambda: messagebox.showwarning("Cancelled", "Geodata generation stopped by user."))
                else:
                    # If target was Lucera 2 .l2g, encrypt generated .l2j
                    if target_fmt == "l2g":
                        print("[GENERATOR] Encrypting generated .l2j to Lucera 2 .l2g ...")
                        for l2j_file in glob.glob(os.path.join(dst, "*.l2j")):
                            if self.stop_event.is_set():
                                break
                            base = os.path.splitext(l2j_file)[0]
                            l2g_path = base + ".l2g"
                            l2j2l2g_file(l2j_file, l2g_path)
                            os.remove(l2j_file)
                            print(f"  ✓ Encrypted: {os.path.basename(l2g_path)}")

                    print(f"\n[GENERATOR] Generation finished! Output saved in: {dst}\n")
                    self.root.after(0, lambda: messagebox.showinfo("Complete", f"Geodata generation completed!\nFiles saved in:\n{dst}"))
            except Exception as e:
                print(f"[ERROR] Generation failed: {e}")
                self.root.after(0, lambda: messagebox.showerror("Error", f"Generation error:\n{e}"))
            finally:
                self.root.after(0, lambda: self._set_running(False))

        threading.Thread(target=worker, daemon=True).start()

    # =========================================================================
    # TAB 4: PACK COMPARISON (DIFF)
    # =========================================================================
    def _setup_tab_diff(self):
        f = self.tab_diff

        # Pack A
        lbl_a = Label(f, text="Pack A Directory (Baseline / Official) / Папка геодаты A:", font=("Segoe UI", 9, "bold"))
        lbl_a.pack(anchor="w", pady=(0, 2))

        frame_a = Frame(f)
        frame_a.pack(fill="x", pady=(0, 6))
        self.diff_a_var = StringVar()
        e_a = ttk.Entry(frame_a, textvariable=self.diff_a_var, font=("Segoe UI", 9))
        e_a.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(frame_a, text="Browse Folder...", command=self._browse_diff_a).pack(side="left")

        # Pack B
        lbl_b = Label(f, text="Pack B Directory (Comparison / Target) / Папка геодаты B:", font=("Segoe UI", 9, "bold"))
        lbl_b.pack(anchor="w", pady=(4, 2))

        frame_b = Frame(f)
        frame_b.pack(fill="x", pady=(0, 6))
        self.diff_b_var = StringVar()
        e_b = ttk.Entry(frame_b, textvariable=self.diff_b_var, font=("Segoe UI", 9))
        e_b.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(frame_b, text="Browse Folder...", command=self._browse_diff_b).pack(side="left")

        # Optional region filter
        reg_frame = Frame(f)
        reg_frame.pack(fill="x", pady=4)
        Label(reg_frame, text="Region Name (e.g. 20_20, or leave empty for full pack summary):", font=("Segoe UI", 9)).pack(side="left", padx=(0, 6))
        self.diff_region_var = StringVar()
        e_reg = ttk.Entry(reg_frame, textvariable=self.diff_region_var, width=15, font=("Segoe UI", 9))
        e_reg.pack(side="left")

        info_box = ttk.LabelFrame(f, text=" Comparison Details / Особенности сравнения ", padding=8)
        info_box.pack(fill="x", pady=6)
        desc = (
            "• Compares all .l2j, .l2g (Lucera 2), and _conv.dat (PTS) files between both packs.\n"
            "• Analyzes surface height differences (|Δh| <= 16 as match, > 64 as terrain deviation).\n"
            "• If a specific region is given, prints a full 32x32 ASCII mismatch map and NSWE directional divergence."
        )
        Label(info_box, text=desc, justify="left", font=("Segoe UI", 9), fg="#333333").pack(anchor="w")

        # Action Buttons
        btn_box = Frame(f)
        btn_box.pack(fill="x", pady=6)

        self.btn_run_diff = Button(
            btn_box, text="RUN PACK COMPARISON / СРАВНИТЬ ПАКИ",
            font=("Segoe UI", 10, "bold"),
            bg="#d39e00", fg="black", activebackground="#b98800", activeforeground="black",
            relief="raised", padx=12, pady=6, cursor="hand2",
            command=self._execute_diff
        )
        self.btn_run_diff.pack(side="left", fill="x", expand=True, padx=(0, 4))

        btn_stop_diff = Button(
            btn_box, text="■ STOP / СТОП",
            font=("Segoe UI", 10, "bold"),
            bg="#5c6370", fg="white", activebackground="#e06c75", activeforeground="white",
            state="disabled", relief="raised", padx=14, pady=6, cursor="hand2",
            command=self._request_stop
        )
        btn_stop_diff.pack(side="right")
        self._stop_buttons.append(btn_stop_diff)

    def _browse_diff_a(self):
        d = filedialog.askdirectory(title="Select Geodata Pack A")
        if d:
            self.diff_a_var.set(d)

    def _browse_diff_b(self):
        d = filedialog.askdirectory(title="Select Geodata Pack B")
        if d:
            self.diff_b_var.set(d)

    def _execute_diff(self):
        da = self.diff_a_var.get().strip()
        db = self.diff_b_var.get().strip()
        reg = self.diff_region_var.get().strip() or None

        if not da or not os.path.exists(da):
            messagebox.showerror("Error", "Please select a valid folder for Pack A.")
            return
        if not db or not os.path.exists(db):
            messagebox.showerror("Error", "Please select a valid folder for Pack B.")
            return

        self._set_running(True, "Diff")

        def worker():
            try:
                print(f"\n[DIFF] Comparing Pack A ({da}) vs Pack B ({db}) ...")
                if reg:
                    print(f"  Focusing on region: {reg}")
                ret = cmd_diff(da, db, region=reg, stop_event=self.stop_event)
                if self.stop_event.is_set():
                    print("\n[DIFF] Comparison stopped by user.\n")
                    self.root.after(0, lambda: messagebox.showwarning("Cancelled", "Pack comparison stopped by user."))
                else:
                    print(f"\n[DIFF] Finished with exit code: {ret}\n")
                    self.root.after(0, lambda: messagebox.showinfo("Diff Completed", "Pack comparison finished. Check Live Activity Log for full details."))
            except Exception as e:
                print(f"[ERROR] Diff failed: {e}")
                self.root.after(0, lambda: messagebox.showerror("Error", f"Diff error:\n{e}"))
            finally:
                self.root.after(0, lambda: self._set_running(False))

        threading.Thread(target=worker, daemon=True).start()

    # =========================================================================
    # TAB 5: SPAWN VALIDATOR (SPAWNCHECK)
    # =========================================================================
    def _setup_tab_spawns(self):
        f = self.tab_spawns

        # Geodata dir
        lbl_geo = Label(f, text="Geodata Folder (.l2j, .l2g, _conv.dat) / Папка с геодатой:", font=("Segoe UI", 9, "bold"))
        lbl_geo.pack(anchor="w", pady=(0, 2))

        frame_geo = Frame(f)
        frame_geo.pack(fill="x", pady=(0, 6))
        self.spawn_geo_var = StringVar()
        e_geo = ttk.Entry(frame_geo, textvariable=self.spawn_geo_var, font=("Segoe UI", 9))
        e_geo.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(frame_geo, text="Browse Folder...", command=self._browse_spawn_geo).pack(side="left")

        # npcpos.txt file
        lbl_npc = Label(f, text="NPC Spawns File (npcpos.txt) / Файл со спавнами npcpos.txt:", font=("Segoe UI", 9, "bold"))
        lbl_npc.pack(anchor="w", pady=(4, 2))

        frame_npc = Frame(f)
        frame_npc.pack(fill="x", pady=(0, 6))
        self.spawn_npcpos_var = StringVar()
        e_npc = ttk.Entry(frame_npc, textvariable=self.spawn_npcpos_var, font=("Segoe UI", 9))
        e_npc.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(frame_npc, text="Browse File...", command=self._browse_spawn_npcpos).pack(side="left")

        # Optional JSON output report
        lbl_out = Label(f, text="Export JSON Report (Optional) / Экспорт отчета в JSON (опционально):", font=("Segoe UI", 9))
        lbl_out.pack(anchor="w", pady=(4, 2))

        frame_out = Frame(f)
        frame_out.pack(fill="x", pady=(0, 6))
        self.spawn_out_var = StringVar()
        e_out = ttk.Entry(frame_out, textvariable=self.spawn_out_var, font=("Segoe UI", 9))
        e_out.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(frame_out, text="Browse Save Path...", command=self._browse_spawn_out).pack(side="left")

        info_box = ttk.LabelFrame(f, text=" Validation Scope / Что проверяется ", padding=8)
        info_box.pack(fill="x", pady=6)
        desc = (
            "• Scans all fixed XYZ spawn coordinates and polygonal territories from npcpos.txt.\n"
            "• Validates that each spawn point lands on a solid geodata layer within tolerable Z.\n"
            "• Detects 'hole' (falling into ocean/void), 'near_z' (elevation offset), and 'wrong_floor' (spawning inside walls/underground)."
        )
        Label(info_box, text=desc, justify="left", font=("Segoe UI", 9), fg="#333333").pack(anchor="w")

        # Action Buttons
        btn_box = Frame(f)
        btn_box.pack(fill="x", pady=6)

        self.btn_run_spawn = Button(
            btn_box, text="VALIDATE NPC SPAWNS / ПРОВЕРИТЬ ТОЧКИ СПАВНА",
            font=("Segoe UI", 10, "bold"),
            bg="#20c997", fg="white", activebackground="#1aa179", activeforeground="white",
            relief="raised", padx=12, pady=6, cursor="hand2",
            command=self._execute_spawncheck
        )
        self.btn_run_spawn.pack(side="left", fill="x", expand=True, padx=(0, 4))

        btn_stop_spawn = Button(
            btn_box, text="■ STOP / СТОП",
            font=("Segoe UI", 10, "bold"),
            bg="#5c6370", fg="white", activebackground="#e06c75", activeforeground="white",
            state="disabled", relief="raised", padx=14, pady=6, cursor="hand2",
            command=self._request_stop
        )
        btn_stop_spawn.pack(side="right")
        self._stop_buttons.append(btn_stop_spawn)

    def _browse_spawn_geo(self):
        d = filedialog.askdirectory(title="Select Geodata Folder")
        if d:
            self.spawn_geo_var.set(d)

    def _browse_spawn_npcpos(self):
        f = filedialog.askopenfilename(
            title="Select npcpos.txt",
            filetypes=[("Text Spawn Files", "*.txt"), ("All Files", "*.*")]
        )
        if f:
            self.spawn_npcpos_var.set(f)

    def _browse_spawn_out(self):
        f = filedialog.asksaveasfilename(
            title="Save Spawn Report JSON",
            defaultextension=".json",
            filetypes=[("JSON Reports", "*.json"), ("All Files", "*.*")]
        )
        if f:
            self.spawn_out_var.set(f)

    def _execute_spawncheck(self):
        geo = self.spawn_geo_var.get().strip()
        npc = self.spawn_npcpos_var.get().strip()
        out = self.spawn_out_var.get().strip() or None

        if not geo or not os.path.exists(geo):
            messagebox.showerror("Error", "Please select a valid geodata folder.")
            return
        if not npc or not os.path.isfile(npc):
            messagebox.showerror("Error", "Please select a valid npcpos.txt file.")
            return

        self._set_running(True, "SpawnCheck")

        def worker():
            try:
                print(f"\n[SPAWNCHECK] Validating spawns in {npc} against geodata {geo} ...")
                ret = cmd_spawncheck(geo, npc, out_json=out, stop_event=self.stop_event)
                if self.stop_event.is_set():
                    print("\n[SPAWNCHECK] Validation stopped by user.\n")
                    self.root.after(0, lambda: messagebox.showwarning("Cancelled", "Spawn validation stopped by user."))
                else:
                    print(f"\n[SPAWNCHECK] Validation completed (exit code: {ret})\n")
                    msg = "Spawn check completed! Check the Live Activity Log for warning pins."
                    if out:
                        msg += f"\nDetailed JSON report saved to:\n{out}"
                    self.root.after(0, lambda: messagebox.showinfo("Validation Finished", msg))
            except Exception as e:
                print(f"[ERROR] Spawncheck failed: {e}")
                self.root.after(0, lambda: messagebox.showerror("Error", f"Spawncheck error:\n{e}"))
            finally:
                self.root.after(0, lambda: self._set_running(False))

        threading.Thread(target=worker, daemon=True).start()

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

        print(f"\n[VIEWER] Starting local 2D/3D viewer server on http://127.0.0.1:8777 ...")
        threading.Thread(target=lambda: cmd_view(d, port=8777), daemon=True).start()

        def _open_browser():
            time.sleep(1.2)
            try:
                webbrowser.open("http://127.0.0.1:8777")
            except Exception:
                pass
        threading.Thread(target=_open_browser, daemon=True).start()

    # =========================================================================
    # TAB 7: GEO EDITOR & BATCH OPERATIONS (HD GeoEditor / DRiN)
    # =========================================================================
    def _setup_tab_editor(self):
        f = self.tab_editor

        # Source input
        lbl1 = Label(f, text="Source Geodata (File or Folder) / Исходные файлы или папка:", font=("Segoe UI", 9, "bold"))
        lbl1.pack(anchor="w", pady=(0, 2))

        in_frame = Frame(f)
        in_frame.pack(fill="x", pady=(0, 6))
        self.edit_src_var = StringVar()
        e1 = ttk.Entry(in_frame, textvariable=self.edit_src_var, font=("Segoe UI", 9))
        e1.pack(side="left", fill="x", expand=True, padx=(0, 6))

        btn_f = ttk.Button(in_frame, text="Choose File...", command=self._browse_edit_file)
        btn_f.pack(side="left", padx=2)
        btn_d = ttk.Button(in_frame, text="Choose Folder...", command=self._browse_edit_dir)
        btn_d.pack(side="left", padx=2)

        # Output folder
        lbl2 = Label(f, text="Destination Folder / Папка сохранения:", font=("Segoe UI", 9, "bold"))
        lbl2.pack(anchor="w", pady=(4, 2))

        out_frame = Frame(f)
        out_frame.pack(fill="x", pady=(0, 8))
        self.edit_dst_var = StringVar()
        e2 = ttk.Entry(out_frame, textvariable=self.edit_dst_var, font=("Segoe UI", 9))
        e2.pack(side="left", fill="x", expand=True, padx=(0, 6))
        btn_out = ttk.Button(out_frame, text="Browse...", command=self._browse_edit_out)
        btn_out.pack(side="left")

        # Operations Box
        ops_box = ttk.LabelFrame(f, text=" Select Operation / Выберите операцию ", padding=8)
        ops_box.pack(fill="x", pady=4)

        self.edit_op_var = StringVar(value="shift_z")

        # OP 1: Shift Z
        row1 = Frame(ops_box)
        row1.pack(fill="x", pady=2)
        ttk.Radiobutton(row1, text="Shift Z (Elevation ΔZ):", variable=self.edit_op_var, value="shift_z").pack(side="left", padx=(0, 8))
        self.edit_shift_z_val = IntVar(value=50)
        sp_z = ttk.Spinbox(row1, from_=-16000, to=16000, textvariable=self.edit_shift_z_val, width=8)
        sp_z.pack(side="left", padx=4)
        Label(row1, text="Layer:", fg="#666").pack(side="left", padx=(10, 4))
        self.edit_shift_z_layer = StringVar(value="all")
        ttk.Combobox(row1, textvariable=self.edit_shift_z_layer, values=["all", "0"], width=6, state="readonly").pack(side="left")

        # OP 2: Shift XY
        row2 = Frame(ops_box)
        row2.pack(fill="x", pady=2)
        ttk.Radiobutton(row2, text="Shift XY (Translate Matrix):", variable=self.edit_op_var, value="shift_xy").pack(side="left", padx=(0, 8))
        Label(row2, text="ΔBX:").pack(side="left")
        self.edit_shift_bx = IntVar(value=0)
        ttk.Spinbox(row2, from_=-255, to=255, textvariable=self.edit_shift_bx, width=6).pack(side="left", padx=4)
        Label(row2, text="ΔBY:").pack(side="left", padx=(8, 0))
        self.edit_shift_by = IntVar(value=0)
        ttk.Spinbox(row2, from_=-255, to=255, textvariable=self.edit_shift_by, width=6).pack(side="left", padx=4)

        # OP 3: Delete Z-Range
        row3 = Frame(ops_box)
        row3.pack(fill="x", pady=2)
        ttk.Radiobutton(row3, text="Delete Z-Range (Prune layers):", variable=self.edit_op_var, value="delete_z").pack(side="left", padx=(0, 8))
        Label(row3, text="MinZ:").pack(side="left")
        self.edit_del_min_z = IntVar(value=500)
        ttk.Spinbox(row3, from_=-16000, to=16000, textvariable=self.edit_del_min_z, width=8).pack(side="left", padx=4)
        Label(row3, text="MaxZ:").pack(side="left", padx=(8, 0))
        self.edit_del_max_z = IntVar(value=1000)
        ttk.Spinbox(row3, from_=-16000, to=16000, textvariable=self.edit_del_max_z, width=8).pack(side="left", padx=4)

        # OP 4: Recalculate Slope
        row4 = Frame(ops_box)
        row4.pack(fill="x", pady=2)
        ttk.Radiobutton(row4, text="Recalculate Slope (Z-Wizard):", variable=self.edit_op_var, value="slope").pack(side="left", padx=(0, 8))
        Label(row4, text="Max Climb Z:").pack(side="left")
        self.edit_slope_climb = IntVar(value=24)
        ttk.Spinbox(row4, from_=8, to=128, textvariable=self.edit_slope_climb, width=6).pack(side="left", padx=4)

        # Target format
        fmt_bar = Frame(f)
        fmt_bar.pack(fill="x", pady=4)
        Label(fmt_bar, text="Target Format:").pack(side="left", padx=(0, 6))
        self.edit_fmt_var = StringVar(value="auto")
        ttk.Combobox(fmt_bar, textvariable=self.edit_fmt_var, values=["auto", "l2j", "l2g", "pts"], width=8, state="readonly").pack(side="left")

        # Action Buttons
        btn_box = Frame(f)
        btn_box.pack(fill="x", pady=6)

        self.btn_run_editor = Button(
            btn_box, text="APPLY OPERATION / ПРИМЕНИТЬ ОПЕРАЦИЮ",
            font=("Segoe UI", 10, "bold"),
            bg="#28a745", fg="white", activebackground="#218838", activeforeground="white",
            relief="raised", padx=12, pady=6, cursor="hand2",
            command=self._execute_editor
        )
        self.btn_run_editor.pack(side="left", fill="x", expand=True, padx=(0, 4))

        btn_stop_edit = Button(
            btn_box, text="■ STOP / СТОП",
            font=("Segoe UI", 10, "bold"),
            bg="#5c6370", fg="white", activebackground="#e06c75", activeforeground="white",
            state="disabled", relief="raised", padx=14, pady=6, cursor="hand2",
            command=self._request_stop
        )
        btn_stop_edit.pack(side="right")
        self._stop_buttons.append(btn_stop_edit)

        # Live Client Scanner Box
        scan_box = ttk.LabelFrame(f, text=" L2 Live Process Scanner (HD GeoEditor Hook) ", padding=8)
        scan_box.pack(fill="x", pady=6)

        scan_bar = Frame(scan_box)
        scan_bar.pack(fill="x")
        self.btn_scan_l2 = ttk.Button(scan_bar, text="Scan Running L2.bin Process", command=self._scan_l2_coords)
        self.btn_scan_l2.pack(side="left", padx=(0, 10))

        self.scan_status_var = StringVar(value="Status: Ready (Click scan when Lineage II client is open)")
        lbl_scan = Label(scan_bar, textvariable=self.scan_status_var, font=("Segoe UI", 9), fg="#666")
        lbl_scan.pack(side="left")

    def _browse_edit_file(self):
        f = filedialog.askopenfilename(
            title="Select Geodata File",
            filetypes=[("All Geodata", "*.l2j;*.l2g;*.dat"), ("L2J Geodata", "*.l2j"), ("Lucera 2", "*.l2g"), ("PTS Geodata", "*_conv.dat")]
        )
        if f:
            self.edit_src_var.set(f)
            if not self.edit_dst_var.get():
                self.edit_dst_var.set(os.path.join(os.path.dirname(f), "edited"))

    def _browse_edit_dir(self):
        d = filedialog.askdirectory(title="Select Geodata Folder")
        if d:
            self.edit_src_var.set(d)
            if not self.edit_dst_var.get():
                self.edit_dst_var.set(os.path.join(d, "edited"))

    def _browse_edit_out(self):
        d = filedialog.askdirectory(title="Select Output Folder")
        if d:
            self.edit_dst_var.set(d)

    def _scan_l2_coords(self):
        scanner = L2ClientMemoryScanner()
        try:
            if not scanner.find_and_attach():
                self.scan_status_var.set("L2.bin process not found. Please launch the Lineage II client first.")
                return
            coords = scanner.read_player_coords()
            if not coords:
                coords = scanner.read_player_coords(use_stat=True)
            if coords:
                wx, wy, wz = coords
                geo_info = scanner.world_to_geo_coords(wx, wy, wz)
                msg = f"World: ({wx:.1f}, {wy:.1f}, {wz:.1f}) -> Region: {geo_info['rx']}_{geo_info['ry']} (Block: {geo_info['bx']},{geo_info['by']}, Cell: {geo_info['cx']},{geo_info['cy']})"
                self.scan_status_var.set(msg)
                print(f"[SCANNER] {msg}")
            else:
                self.scan_status_var.set("Found L2.bin, but could not read player coordinate pointers.")
        finally:
            scanner.close()

    def _execute_editor(self):
        src = self.edit_src_var.get().strip()
        dst = self.edit_dst_var.get().strip()
        op = self.edit_op_var.get()
        target_fmt = self.edit_fmt_var.get()

        if not src or not os.path.exists(src):
            messagebox.showerror("Error", "Please select a valid source geodata file or folder.")
            return
        if not dst:
            messagebox.showerror("Error", "Please select an output folder.")
            return

        self._set_running(True, "Editor")

        def worker():
            try:
                os.makedirs(dst, exist_ok=True)
                files = [src] if os.path.isfile(src) else [
                    os.path.join(src, f) for f in os.listdir(src) if sniff_format(f)
                ]
                print(f"\n[EDITOR] Executing operation '{op}' on {len(files)} regions...")

                for f in sorted(files):
                    if self.stop_event.is_set():
                        print("\n[EDITOR] Operation stopped by user.")
                        break

                    rx, ry = region_of(f)
                    src_fmt = sniff_format(f)
                    out_fmt = src_fmt if target_fmt == "auto" else target_fmt

                    base_stem = os.path.basename(f)
                    if base_stem.endswith(".l2j"):
                        base_stem = base_stem[:-4]
                    elif base_stem.endswith(".l2g"):
                        base_stem = base_stem[:-4]
                    elif base_stem.endswith("_conv.dat"):
                        base_stem = base_stem[:-len("_conv.dat")]

                    ext_map = {"l2j": ".l2j", "l2g": ".l2g", "pts": "_conv.dat"}
                    out_file = os.path.join(dst, f"{base_stem}{ext_map.get(out_fmt, '.l2j')}")

                    blocks = parse_region(f)

                    if op == "shift_z":
                        dz = self.edit_shift_z_val.get()
                        lm = self.edit_shift_z_layer.get()
                        t_idx = 0 if lm == "0" else 0
                        n_mod = shift_z_blocks(blocks, dz, layer_mode="all" if lm == "all" else "specific", target_layer_idx=t_idx)
                        print(f"  • {os.path.basename(f)}: Shifted Z by {dz:+d}u ({n_mod} layers updated)")

                    elif op == "shift_xy":
                        dbx = self.edit_shift_bx.get()
                        dby = self.edit_shift_by.get()
                        res = shift_xy_blocks(blocks, dbx, dby)
                        print(f"  • {os.path.basename(f)}: Shifted XY by ({dbx:+d}, {dby:+d}) blocks ({res['shifted_blocks']} moved, {res['void_filled']} void filled)")

                    elif op == "delete_z":
                        min_z = self.edit_del_min_z.get()
                        max_z = self.edit_del_max_z.get()
                        res = delete_z_range_blocks(blocks, min_z, max_z)
                        print(f"  • {os.path.basename(f)}: Deleted Z-range [{min_z}..{max_z}] ({res['deleted_layers']} layers removed, {res['converted_blocks']} blocks compacted)")

                    elif op == "slope":
                        climb = self.edit_slope_climb.get()
                        res = recalculate_slope_flags(blocks, max_climb_z=climb)
                        print(f"  • {os.path.basename(f)}: Recalculated slope (climb limit: {climb}u) -> {res['sealed_passages']} passages sealed")

                    save_edited_region(blocks, out_file, target_format=out_fmt, rx=rx, ry=ry)
                    print(f"    -> Saved: {out_file}")

                if self.stop_event.is_set():
                    self.root.after(0, lambda: messagebox.showwarning("Cancelled", "Operation stopped by user."))
                else:
                    self.root.after(0, lambda: messagebox.showinfo("Finished", f"Operation '{op}' successfully completed on {len(files)} files!"))

            except Exception as e:
                print(f"[ERROR] Editor operation failed: {e}")
                self.root.after(0, lambda: messagebox.showerror("Error", f"Editor failed:\n{e}"))
            finally:
                self.root.after(0, lambda: self._set_running(False))

        threading.Thread(target=worker, daemon=True).start()

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
    app = L2GeoConverterGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
