# -*- coding: utf-8 -*-
"""Tab 2: diagnostics & auto-repair."""

import os
import threading
from tkinter import (
    Frame, Label, Button, StringVar, BooleanVar, ttk, filedialog,
    messagebox,
)

from ..diagnostics import GeoDiagnosticEngine
from ..formats import sniff_format


class DiagnoseTabMixin:
    """Diagnostics & Repair tab."""

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
                self.root.after(0, lambda e=e: messagebox.showerror("Error", f"Diagnosis error:\n{e}"))
            finally:
                self.root.after(0, lambda: self._set_running(False))

        threading.Thread(target=worker, daemon=True).start()
