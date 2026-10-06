# -*- coding: utf-8 -*-
"""Interactive mechanics guide window."""

import os
import sys
import webbrowser
from tkinter import Toplevel, Frame, Label, Button, ttk, Canvas

from .common import APP_DIR, HAS_PIL, PILImage, ImageTk


class GuideWindowMixin:
    """Help / mechanics guide pop-up."""

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
            base_dir = getattr(sys, '_MEIPASS', APP_DIR)
            img_path = os.path.join(base_dir, "assets", filename)
            if not os.path.exists(img_path):
                img_path = os.path.join(APP_DIR, "assets", filename)
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
            guide_md = os.path.join(APP_DIR, "docs", "GUIDE.md")
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
