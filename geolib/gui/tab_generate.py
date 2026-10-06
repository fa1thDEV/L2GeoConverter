# -*- coding: utf-8 -*-
"""Tab 3: geodata generation from client UNR maps."""

import glob
import os
import re
import threading
from tkinter import (
    Frame, Label, Button, StringVar, BooleanVar, ttk, filedialog,
    messagebox,
)

from ..convert import l2j2l2g_file
from ..generate import cmd_generate


class GenerateTabMixin:
    """Generate from UNR tab."""

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
                self.root.after(0, lambda e=e: messagebox.showerror("Error", f"Generation error:\n{e}"))
            finally:
                self.root.after(0, lambda: self._set_running(False))

        threading.Thread(target=worker, daemon=True).start()
