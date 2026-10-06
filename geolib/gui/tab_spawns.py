# -*- coding: utf-8 -*-
"""Tab 5: spawn validator."""

import os
import threading
from tkinter import (
    Frame, Label, Button, StringVar, ttk, filedialog, messagebox,
)

from ..spawncheck import cmd_spawncheck


class SpawnsTabMixin:
    """Spawn Validator tab."""

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
                self.root.after(0, lambda e=e: messagebox.showerror("Error", f"Spawncheck error:\n{e}"))
            finally:
                self.root.after(0, lambda: self._set_running(False))

        threading.Thread(target=worker, daemon=True).start()
