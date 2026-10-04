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
    Tk, Frame, Label, Button, Entry, StringVar, BooleanVar, ttk,
    filedialog, messagebox, Text, Scrollbar, Canvas, PhotoImage
)

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

        self._init_header()
        self._init_tabs()
        self._init_console()

        # Redirect standard output to console log
        self.redirector = TextRedirector(self.console, self.root)
        sys.stdout = self.redirector
        sys.stderr = self.redirector

        print("L2 Geodata Converter initialized.")
        print("Ready. Select a tab above to begin.")

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

        # Action Button
        self.btn_run_conv = Button(
            f, text="START CONVERSION / НАЧАТЬ КОНВЕРТАЦИЮ",
            font=("Segoe UI", 10, "bold"),
            bg="#28a745", fg="white", activebackground="#218838", activeforeground="white",
            relief="raised", padx=12, pady=6, cursor="hand2",
            command=self._execute_conversion
        )
        self.btn_run_conv.pack(fill="x", pady=4)

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

        self.btn_run_conv.config(state="disabled")

        def worker():
            try:
                os.makedirs(dst, exist_ok=True)
                files = [src] if os.path.isfile(src) else [
                    os.path.join(src, f) for f in os.listdir(src) if sniff_format(f)
                ]
                print(f"\n[CONVERTER] Processing {len(files)} files -> Target: {target_fmt.upper()} ...")

                success = 0
                for f in sorted(files):
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

                print(f"\n[CONVERTER] Finished! {success} files converted successfully to: {dst}\n")
                self.root.after(0, lambda: messagebox.showinfo("Success", f"Conversion completed!\n{success} files saved in:\n{dst}"))
            except Exception as e:
                print(f"[ERROR] Conversion failed: {e}")
                self.root.after(0, lambda: messagebox.showerror("Error", f"Conversion error:\n{e}"))
            finally:
                self.root.after(0, lambda: self.btn_run_conv.config(state="normal"))

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

        # Action Button
        self.btn_run_diag = Button(
            f, text="RUN DIAGNOSTICS & REPAIR / ЗАПУСТИТЬ ПРОВЕРКУ И РЕМОНТ",
            font=("Segoe UI", 10, "bold"),
            bg="#007acc", fg="white", activebackground="#005999", activeforeground="white",
            relief="raised", padx=12, pady=6, cursor="hand2",
            command=self._execute_diagnostics
        )
        self.btn_run_diag.pack(fill="x", pady=4)

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

        self.btn_run_diag.config(state="disabled")

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
                    rep = engine.analyze(f)
                    st = rep["stats"]
                    total_cliffs += st["cliff_errors"]
                    total_asym += st["asymmetry_errors"]

                    print(f"\n  Region: {st['region']} ({st['format'].upper()})")
                    print(f"    • Hazardous Cliff Falls (Fall under map): {st['cliff_errors']}")
                    print(f"    • Asymmetric One-Way Walls: {st['asymmetry_errors']}")
                    print(f"    • Layer Squeeze Traps: {st['layer_squeeze_errors']}")

                    if do_fix:
                        os.makedirs(dst, exist_ok=True)
                        fixed_file = os.path.join(dst, os.path.basename(f))
                        res = engine.repair_and_save(f, fixed_file)
                        total_fixed_cliffs += res["cliffs_sealed"]
                        total_fixed_walls += res["asymmetries_repaired"]
                        print(f"    ✓ Auto-repaired & saved -> {fixed_file}")

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
                self.root.after(0, lambda: self.btn_run_diag.config(state="normal"))

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

        # Action Button
        self.btn_run_gen = Button(
            f, text="GENERATE GEODATA / СГЕНЕРИРОВАТЬ ГЕОДАТУ",
            font=("Segoe UI", 10, "bold"),
            bg="#6f42c1", fg="white", activebackground="#59359a", activeforeground="white",
            relief="raised", padx=12, pady=6, cursor="hand2",
            command=self._execute_generation
        )
        self.btn_run_gen.pack(fill="x", pady=4)

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

        self.btn_run_gen.config(state="disabled")

        def worker():
            try:
                os.makedirs(dst, exist_ok=True)
                print(f"\n[GENERATOR] Starting geodata generation from: {src}")
                print(f"  Target: {target_fmt.upper()}, Region: {region or 'ALL'}, Terrain Only: {terrain_only}")

                internal_fmt = "pts" if target_fmt == "pts" else "l2j"
                regions = [region] if region else None

                cmd_generate(
                    src, dst, regions=regions,
                    terrain_only=terrain_only,
                    out_fmt=internal_fmt,
                    jobs=None
                )

                # If target was Lucera 2 .l2g, encrypt generated .l2j
                if target_fmt == "l2g":
                    print("[GENERATOR] Encrypting generated .l2j to Lucera 2 .l2g ...")
                    for l2j_file in glob.glob(os.path.join(dst, "*.l2j")):
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
                self.root.after(0, lambda: self.btn_run_gen.config(state="normal"))

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

        # Button
        self.btn_run_diff = Button(
            f, text="RUN PACK COMPARISON / СРАВНИТЬ ПАКИ",
            font=("Segoe UI", 10, "bold"),
            bg="#d39e00", fg="black", activebackground="#b98800", activeforeground="black",
            relief="raised", padx=12, pady=6, cursor="hand2",
            command=self._execute_diff
        )
        self.btn_run_diff.pack(fill="x", pady=6)

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

        self.btn_run_diff.config(state="disabled")

        def worker():
            try:
                print(f"\n[DIFF] Comparing Pack A ({da}) vs Pack B ({db}) ...")
                if reg:
                    print(f"  Focusing on region: {reg}")
                ret = cmd_diff(da, db, region=reg)
                print(f"\n[DIFF] Finished with exit code: {ret}\n")
                self.root.after(0, lambda: messagebox.showinfo("Diff Completed", "Pack comparison finished. Check Live Activity Log for full details."))
            except Exception as e:
                print(f"[ERROR] Diff failed: {e}")
                self.root.after(0, lambda: messagebox.showerror("Error", f"Diff error:\n{e}"))
            finally:
                self.root.after(0, lambda: self.btn_run_diff.config(state="normal"))

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

        # Button
        self.btn_run_spawn = Button(
            f, text="VALIDATE NPC SPAWNS / ПРОВЕРИТЬ ТОЧКИ СПАВНА",
            font=("Segoe UI", 10, "bold"),
            bg="#20c997", fg="white", activebackground="#1aa179", activeforeground="white",
            relief="raised", padx=12, pady=6, cursor="hand2",
            command=self._execute_spawncheck
        )
        self.btn_run_spawn.pack(fill="x", pady=6)

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

        self.btn_run_spawn.config(state="disabled")

        def worker():
            try:
                print(f"\n[SPAWNCHECK] Validating spawns in {npc} against geodata {geo} ...")
                ret = cmd_spawncheck(geo, npc, out_json=out)
                print(f"\n[SPAWNCHECK] Validation completed (exit code: {ret})\n")
                msg = "Spawn check completed! Check the Live Activity Log for warning pins."
                if out:
                    msg += f"\nDetailed JSON report saved to:\n{out}"
                self.root.after(0, lambda: messagebox.showinfo("Validation Finished", msg))
            except Exception as e:
                print(f"[ERROR] Spawncheck failed: {e}")
                self.root.after(0, lambda: messagebox.showerror("Error", f"Spawncheck error:\n{e}"))
            finally:
                self.root.after(0, lambda: self.btn_run_spawn.config(state="normal"))

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
    # CONSOLE & STATUS LOG
    # =========================================================================
    def _init_console(self):
        console_frame = ttk.LabelFrame(self.root, text=" Live Activity & Status Log / Журнал событий ", padding=6)
        console_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.console = Text(
            console_frame,
            wrap="word",
            bg="#1e1e1e",
            fg="#d4d4d4",
            insertbackground="white",
            font=("Consolas", 9),
            height=9
        )
        scrollbar = ttk.Scrollbar(console_frame, orient="vertical", command=self.console.yview)
        self.console.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        self.console.pack(side="left", fill="both", expand=True)


def main():
    root = Tk()
    app = L2GeoConverterGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
