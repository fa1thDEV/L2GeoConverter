# -*- coding: utf-8 -*-
"""Tab 7: geo editor & batch operations."""

import os
import threading
from tkinter import (
    Frame, Label, Button, StringVar, IntVar, ttk, filedialog, messagebox,
)

from ..formats import sniff_format, region_of, parse_region
from ..editor import (
    shift_z_blocks, shift_xy_blocks, delete_z_range_blocks,
    recalculate_slope_flags, save_edited_region, L2ClientMemoryScanner
)


class EditorTabMixin:
    """Geo Editor tab."""

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
                self.root.after(0, lambda e=e: messagebox.showerror("Error", f"Editor failed:\n{e}"))
            finally:
                self.root.after(0, lambda: self._set_running(False))

        threading.Thread(target=worker, daemon=True).start()
