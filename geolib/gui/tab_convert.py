# -*- coding: utf-8 -*-
"""Tab 1: format converter."""

import os
import threading
from pathlib import Path
from tkinter import (
    Frame, Label, Button, StringVar, ttk, filedialog, messagebox,
)

from ..convert import (
    l2g2l2j_file, l2j2l2g_file, l2g2pts_file, pts2l2g_file, convert_file,
    l2j2pts_bytes,
)
from ..formats import sniff_format, region_of, PROTO_GD


class ConvertTabMixin:
    """Format Converter tab."""

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
                            Path(out_path).write_bytes(Path(f).read_bytes())
                    elif target_fmt == "l2g":
                        out_path = os.path.join(dst, f"{base_name}.l2g")
                        if os.path.abspath(f) == os.path.abspath(out_path):
                            print(f"  ⚠ Skipping {fname}: source and destination are the same file.")
                            continue
                        if in_fmt == "l2g":
                            Path(out_path).write_bytes(Path(f).read_bytes())
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
                            Path(out_path).write_bytes(Path(f).read_bytes())
                        elif in_fmt == "l2g":
                            l2g2pts_file(f, out_path, rx, ry)
                        elif in_fmt == "l2j":
                            data = Path(f).read_bytes()
                            pts_bytes, _, _, _ = l2j2pts_bytes(data, rx, ry, PROTO_GD)
                            Path(out_path).write_bytes(pts_bytes)

                    print(f"  ✓ Converted: {fname} -> {os.path.basename(out_path)}")
                    success += 1

                if self.stop_event.is_set():
                    self.root.after(0, lambda: messagebox.showwarning("Cancelled", f"Conversion stopped by user.\n{success} files saved in:\n{dst}"))
                else:
                    print(f"\n[CONVERTER] Finished! {success} files converted successfully to: {dst}\n")
                    self.root.after(0, lambda: messagebox.showinfo("Success", f"Conversion completed!\n{success} files saved in:\n{dst}"))
            except Exception as e:
                print(f"[ERROR] Conversion failed: {e}")
                self.root.after(0, lambda e=e: messagebox.showerror("Error", f"Conversion error:\n{e}"))
            finally:
                self.root.after(0, lambda: self._set_running(False))

        threading.Thread(target=worker, daemon=True).start()
