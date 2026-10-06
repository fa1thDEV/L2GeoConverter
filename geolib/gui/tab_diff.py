# -*- coding: utf-8 -*-
"""Tab 4: pack comparison (diff)."""

import os
import threading
from tkinter import (
    Frame, Label, Button, StringVar, ttk, filedialog, messagebox,
)

from ..diff import cmd_diff


class DiffTabMixin:
    """Pack Diff tab."""

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
                self.root.after(0, lambda e=e: messagebox.showerror("Error", f"Diff error:\n{e}"))
            finally:
                self.root.after(0, lambda: self._set_running(False))

        threading.Thread(target=worker, daemon=True).start()
