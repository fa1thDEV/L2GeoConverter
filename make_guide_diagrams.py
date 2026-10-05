#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generates high-resolution technical diagrams for L2GeoConverter documentation and GUI guide.
(c) fa1thDEV
"""

import os
from PIL import Image, ImageDraw, ImageFont

def get_font(size, bold=False):
    font_name = "segoeuib.ttf" if bold else "segoeui.ttf"
    font_path = os.path.join("C:/Windows/Fonts", font_name)
    if os.path.exists(font_path):
        return ImageFont.truetype(font_path, size)
    return ImageFont.load_default()

def get_mono_font(size):
    font_path = "C:/Windows/Fonts/consola.ttf"
    if os.path.exists(font_path):
        return ImageFont.truetype(font_path, size)
    return ImageFont.load_default()

def draw_rounded_rect(draw, bbox, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(bbox, radius=radius, fill=fill, outline=outline, width=width)

# -----------------------------------------------------------------------------
# DIAGRAM 1: WORKFLOW & ARCHITECTURE
# -----------------------------------------------------------------------------
def make_workflow_diagram(out_paths):
    W, H = 1040, 560
    img = Image.new("RGBA", (W, H), "#16191f")
    draw = ImageDraw.Draw(img)

    # Title Banner
    draw_rounded_rect(draw, (20, 20, W - 20, 75), 8, fill="#1f232b", outline="#2d3340", width=1)
    f_title = get_font(20, bold=True)
    f_sub = get_font(12, bold=False)
    f_lbl = get_font(13, bold=True)
    f_text = get_font(11, bold=False)
    f_mono = get_mono_font(11)

    draw.text((36, 30), "L2GeoConverter - Pipeline & Tool Architecture", font=f_title, fill="#61afef")
    draw.text((36, 52), "Multi-format geodata engine, diagnostics, UNR map generation and real-time GUI controls", font=f_sub, fill="#abb2bf")

    # 4 Main Columns
    col_w = 225
    y_top = 95
    y_bot = 535
    cols = [
        ("1. Input Sources", "#21252b", "#3e4451", [
            ("Lucera 2 (.l2g)", "Proprietary XOR + differential signed checksum", "#98c379"),
            ("L2J Format (.l2j)", "Standard 64k raw blocks (Type 0, 1, 2)", "#61afef"),
            ("PTS / L2Off (_conv.dat)", "NCSoft official formats (gd & 286 protocols)", "#e5c07b"),
            ("Client Maps (.unr)", "Unreal Level packages + static meshes", "#c678dd"),
            ("Spawn Files (npcpos.txt)", "XYZ coordinates & polygonal territories", "#e06c75"),
        ]),
        ("2. Core Processing", "#1e222a", "#3e4451", [
            ("Bi-directional Converter", "Instant conversion across all formats", "#98c379"),
            ("Diagnostic Engine", "Cliff drops, NSWE asymmetry, layer clearance", "#e06c75"),
            ("Auto-Repair Engine", "Seals voids & restores 2-way passable ramps", "#61afef"),
            ("Pack Diffing Engine", "Per-cell height/NSWE divergence matrix", "#e5c07b"),
            ("UNR Mesh Raycaster", "Heightmap relief + 3D mesh slicing", "#c678dd"),
        ]),
        ("3. UI & Control Layer", "#21252b", "#3e4451", [
            ("Desktop Tkinter GUI", "Clean multi-tab interface for all operations", "#61afef"),
            ("Interactive CLI Menu", "Console launcher (geotool.py / .bat)", "#abb2bf"),
            ("STOP Cancellation Button", "Graceful thread event interrupt (no corrupt files)", "#e06c75"),
            ("Live Activity Console", "Detailed per-cell logs & execution telemetry", "#98c379"),
            ("2D/3D Web Viewer", "Embedded HTTP server (:8777) with layer slicing", "#56b6c2"),
        ]),
        ("4. Output Deliverables", "#1e222a", "#3e4451", [
            ("Clean Repaired Geodata", "Optimized .l2g / .l2j / _conv.dat files", "#98c379"),
            ("Pathnode Matrices", "pathnode.bin & pathnode.idx (64-bit)", "#61afef"),
            ("Audit Reports", "Machine-readable JSON coordinates & logs", "#e5c07b"),
            ("Comparison Maps", "32x32 ASCII mismatch topology maps", "#abb2bf"),
            ("Spawn Pins", "Tagged invalid/stuck NPC spawn points", "#e06c75"),
        ])
    ]

    for i, (col_title, bg_card, border_card, items) in enumerate(cols):
        x1 = 20 + i * (col_w + 25)
        x2 = x1 + col_w
        draw_rounded_rect(draw, (x1, y_top, x2, y_bot), 8, fill=bg_card, outline=border_card, width=1)

        # Header of column
        draw_rounded_rect(draw, (x1, y_top, x2, y_top + 34), 8, fill="#2c313a", outline=border_card, width=1)
        draw.text((x1 + 12, y_top + 9), col_title, font=f_lbl, fill="#ffffff")

        # Items
        curr_y = y_top + 46
        for title, desc, tag_color in items:
            draw_rounded_rect(draw, (x1 + 8, curr_y, x2 - 8, curr_y + 68), 6, fill="#181a1f", outline="#2d3340", width=1)
            draw.rectangle((x1 + 10, curr_y + 8, x1 + 14, curr_y + 60), fill=tag_color)
            draw.text((x1 + 22, curr_y + 7), title, font=get_font(11, bold=True), fill=tag_color)
            draw.text((x1 + 22, curr_y + 26), desc, font=get_font(10), fill="#abb2bf")
            curr_y += 76

        # Draw connecting arrows between columns
        if i < 3:
            ax = x2 + 5
            ay = y_top + (y_bot - y_top) // 2
            draw.polygon([(ax, ay - 6), (ax + 14, ay), (ax, ay + 6)], fill="#5c6370")

    for p in out_paths:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        img.save(p, "PNG")
    print(f"  [OK] Saved workflow diagram to {out_paths[0]}")

# -----------------------------------------------------------------------------
# DIAGRAM 2: INVISIBLE BARRIERS & NSWE FLAGS
# -----------------------------------------------------------------------------
def make_barriers_diagram(out_paths):
    W, H = 1040, 680
    img = Image.new("RGBA", (W, H), "#16191f")
    draw = ImageDraw.Draw(img)

    f_title = get_font(20, bold=True)
    f_sub = get_font(12, bold=False)
    f_h2 = get_font(14, bold=True)
    f_lbl = get_font(12, bold=True)
    f_body = get_font(11, bold=False)
    f_mono = get_mono_font(11)
    f_mono_b = get_mono_font(12)

    # Title Banner
    draw_rounded_rect(draw, (20, 20, W - 20, 75), 8, fill="#1f232b", outline="#2d3340", width=1)
    draw.text((36, 30), "How Lineage 2 NSWE Directional Flags & Invisible Barriers Work", font=f_title, fill="#98c379")
    draw.text((36, 52), "Understanding cell-level directional movement bits (0x01..0x08) and constructing impassable barriers", font=f_sub, fill="#abb2bf")

    # LEFT PANEL: NSWE Bitmask Specification
    draw_rounded_rect(draw, (20, 90, 420, 660), 8, fill="#1e222a", outline="#2d3340", width=1)
    draw_rounded_rect(draw, (20, 90, 420, 126), 8, fill="#2c313a", outline="#2d3340", width=1)
    draw.text((36, 99), "1. NSWE 4-Bit Collision Bitmask", font=f_h2, fill="#61afef")

    desc_lines = [
        "In Lineage 2, the world is subdivided into:",
        " • Region: 2048 x 2048 cells (e.g. 20_20)",
        " • Block: 8 x 8 cells (64 cells total)",
        " • Cell: 16 x 16 world coordinates",
        "",
        "Each cell encodes a Height Z and a 4-bit NSWE flag:",
    ]
    y_txt = 138
    for line in desc_lines:
        draw.text((36, y_txt), line, font=f_body, fill="#abb2bf")
        y_txt += 18

    # Table of bits
    table_y = y_txt + 8
    draw_rounded_rect(draw, (32, table_y, 408, table_y + 175), 6, fill="#181a1f", outline="#3e4451", width=1)
    draw.rectangle((32, table_y, 408, table_y + 26), fill="#282c34")
    draw.text((42, table_y + 6), "Flag", font=get_font(10, bold=True), fill="#ffffff")
    draw.text((100, table_y + 6), "Bitmask", font=get_font(10, bold=True), fill="#ffffff")
    draw.text((170, table_y + 6), "Movement Evaluation", font=get_font(10, bold=True), fill="#ffffff")

    flag_data = [
        ("EAST", "0x01 (bit 0)", "Allows movement East (+X)", "#98c379"),
        ("WEST", "0x02 (bit 1)", "Allows movement West (-X)", "#98c379"),
        ("SOUTH", "0x04 (bit 2)", "Allows movement South (+Y)", "#98c379"),
        ("NORTH", "0x08 (bit 3)", "Allows movement North (-Y)", "#98c379"),
        ("ALL", "0x0F (bits 0-3)", "Fully open in all directions", "#61afef"),
        ("NONE", "0x00 (0 bits)", "Fully blocked (Solid column)", "#e06c75")
    ]
    r_y = table_y + 30
    for name, bmask, eval_txt, color in flag_data:
        draw.text((42, r_y), name, font=get_font(10, bold=True), fill=color)
        draw.text((100, r_y), bmask, font=f_mono, fill="#abb2bf")
        draw.text((170, r_y), eval_txt, font=f_body, fill="#d4d4d4")
        r_y += 23

    # Compass Rose Diagram in Left Panel
    compass_y = r_y + 18
    draw_rounded_rect(draw, (32, compass_y, 408, 645), 6, fill="#181a1f", outline="#3e4451", width=1)
    cx, cy = 220, compass_y + 75
    draw.ellipse((cx - 50, cy - 50, cx + 50, cy + 50), outline="#3e4451", width=2)
    # North
    draw.line((cx, cy, cx, cy - 42), fill="#61afef", width=3)
    draw.polygon([(cx, cy - 48), (cx - 5, cy - 38), (cx + 5, cy - 38)], fill="#61afef")
    draw.text((cx - 24, cy - 65), "N (0x08)", font=f_lbl, fill="#61afef")
    # South
    draw.line((cx, cy, cx, cy + 42), fill="#61afef", width=3)
    draw.polygon([(cx, cy + 48), (cx - 5, cy + 38), (cx + 5, cy + 38)], fill="#61afef")
    draw.text((cx - 22, cy + 52), "S (0x04)", font=f_lbl, fill="#61afef")
    # West
    draw.line((cx, cy, cx - 42, cy), fill="#61afef", width=3)
    draw.polygon([(cx - 48, cy), (cx - 38, cy - 5), (cx - 38, cy + 5)], fill="#61afef")
    draw.text((cx - 95, cy - 8), "W (0x02)", font=f_lbl, fill="#61afef")
    # East
    draw.line((cx, cy, cx + 42, cy), fill="#61afef", width=3)
    draw.polygon([(cx + 48, cy), (cx + 38, cy - 5), (cx + 38, cy + 5)], fill="#61afef")
    draw.text((cx + 52, cy - 8), "E (0x01)", font=f_lbl, fill="#61afef")

    # RIGHT PANEL: Creating Invisible Walls & Practical Examples
    draw_rounded_rect(draw, (440, 90, W - 20, 660), 8, fill="#1e222a", outline="#2d3340", width=1)
    draw_rounded_rect(draw, (440, 90, W - 20, 126), 8, fill="#2c313a", outline="#2d3340", width=1)
    draw.text((456, 99), "2. How to Create Invisible Barriers in Geodata", font=f_h2, fill="#e5c07b")

    # Example 1: Directional Invisible Wall
    y_ex = 138
    draw_rounded_rect(draw, (455, y_ex, W - 35, y_ex + 155), 6, fill="#181a1f", outline="#3e4451", width=1)
    draw.text((470, y_ex + 8), "Scenario A: Directional Invisible Wall (Flat Ground)", font=f_lbl, fill="#98c379")
    draw.text((470, y_ex + 26), "Both cells have the same height Z=100. By removing the boundary flags, a solid invisible wall is born.", font=f_body, fill="#abb2bf")

    # Draw two cells side by side
    c1_x, c1_y = 480, y_ex + 52
    c2_x, c2_y = 660, y_ex + 52
    cw = 120
    ch = 80
    # Cell A
    draw_rounded_rect(draw, (c1_x, c1_y, c1_x + cw, c1_y + ch), 4, fill="#21252b", outline="#61afef", width=2)
    draw.text((c1_x + 12, c1_y + 10), "Cell A (gx, gy)", font=get_font(11, bold=True), fill="#ffffff")
    draw.text((c1_x + 12, c1_y + 30), "Z = 100", font=f_mono_b, fill="#61afef")
    draw.text((c1_x + 12, c1_y + 50), "NSWE = ~FLAG_EAST", font=f_mono, fill="#e06c75")

    # Cell B
    draw_rounded_rect(draw, (c2_x, c2_y, c2_x + cw, c2_y + ch), 4, fill="#21252b", outline="#61afef", width=2)
    draw.text((c2_x + 12, c2_y + 10), "Cell B (gx+1, gy)", font=get_font(11, bold=True), fill="#ffffff")
    draw.text((c2_x + 12, c2_y + 30), "Z = 100", font=f_mono_b, fill="#61afef")
    draw.text((c2_x + 12, c2_y + 50), "NSWE = ~FLAG_WEST", font=f_mono, fill="#e06c75")

    # Barrier line between them
    bx = (c1_x + cw + c2_x) // 2
    draw.line((bx, c1_y - 4, bx, c1_y + ch + 4), fill="#e06c75", width=4)
    draw.text((bx - 44, c1_y + 24), "NO EAST", font=get_font(9, bold=True), fill="#e06c75")
    draw.text((bx + 8, c1_y + 24), "NO WEST", font=get_font(9, bold=True), fill="#e06c75")
    draw.text((c2_x + cw + 18, c1_y + 15), "Result: Characters hit an", font=f_body, fill="#ffffff")
    draw.text((c2_x + cw + 18, c1_y + 33), "impermeable border.", font=get_font(11, bold=True), fill="#e06c75")
    draw.text((c2_x + cw + 18, c1_y + 52), "Visually 100% transparent!", font=f_body, fill="#98c379")

    # Example 2: Solid Column Obstacle
    y_ex2 = y_ex + 168
    draw_rounded_rect(draw, (455, y_ex2, W - 35, y_ex2 + 155), 6, fill="#181a1f", outline="#3e4451", width=1)
    draw.text((470, y_ex2 + 8), "Scenario B: Solid Invisible Column (Blocking a 16x16 Area)", font=f_lbl, fill="#e5c07b")
    draw.text((470, y_ex2 + 26), "Setting NSWE = 0x00 on a cell creates an impenetrable column preventing entry from any angle.", font=f_body, fill="#abb2bf")

    # 3x3 grid illustration
    grid_x = 510
    grid_y = y_ex2 + 50
    gw = 36
    for row in range(3):
        for col in range(3):
            cell_x = grid_x + col * (gw + 4)
            cell_y = grid_y + row * (gw + 4)
            is_center = (row == 1 and col == 1)
            bg = "#e06c75" if is_center else "#282c34"
            border = "#d19a66" if is_center else "#3e4451"
            draw_rounded_rect(draw, (cell_x, cell_y, cell_x + gw, cell_y + gw), 3, fill=bg, outline=border, width=1)
            if is_center:
                draw.text((cell_x + 6, cell_y + 10), "0x00", font=f_mono_b, fill="#ffffff")
            else:
                draw.text((cell_x + 6, cell_y + 10), "0x0F", font=f_mono, fill="#98c379")

    draw.text((grid_x + 140, grid_y + 8), "Center Cell: NSWE = 0x00 (FLAG_NONE)", font=get_font(11, bold=True), fill="#e06c75")
    draw.text((grid_x + 140, grid_y + 28), "• Denies entry from North, South, East, and West.", font=f_body, fill="#abb2bf")
    draw.text((grid_x + 140, grid_y + 46), "• Ideal for blocking decorative client props, invisible arenas,", font=f_body, fill="#abb2bf")
    draw.text((grid_x + 140, grid_y + 64), "  event zone perimeters, or dangerous traps.", font=f_body, fill="#abb2bf")

    # Example 3: The Asymmetry Trap (One-Way Wall Bug)
    y_ex3 = y_ex2 + 168
    draw_rounded_rect(draw, (455, y_ex3, W - 35, y_ex3 + 170), 6, fill="#181a1f", outline="#e06c75", width=1)
    draw.text((470, y_ex3 + 8), "Scenario C: Asymmetric Wall Bug (NSWE_ASYMMETRY)", font=f_lbl, fill="#e06c75")
    draw.text((470, y_ex3 + 26), "Accidental one-way bug: Cell A permits East entry, but Cell B blocks West return.", font=f_body, fill="#abb2bf")

    asym_x1 = 480
    asym_y = y_ex3 + 52
    draw_rounded_rect(draw, (asym_x1, asym_y, asym_x1 + 140, asym_y + 60), 4, fill="#21252b", outline="#98c379", width=2)
    draw.text((asym_x1 + 10, asym_y + 8), "Cell A: Open East", font=get_font(10, bold=True), fill="#98c379")
    draw.text((asym_x1 + 10, asym_y + 26), "Allows -> East step", font=f_body, fill="#abb2bf")

    asym_x2 = asym_x1 + 190
    draw_rounded_rect(draw, (asym_x2, asym_y, asym_x2 + 140, asym_y + 60), 4, fill="#21252b", outline="#e06c75", width=2)
    draw.text((asym_x2 + 10, asym_y + 8), "Cell B: Blocked West", font=get_font(10, bold=True), fill="#e06c75")
    draw.text((asym_x2 + 10, asym_y + 26), "Blocks <- West return", font=f_body, fill="#abb2bf")

    # One-way arrow
    arr_y = asym_y + 26
    draw.line((asym_x1 + 145, arr_y, asym_x2 - 10, arr_y), fill="#98c379", width=3)
    draw.polygon([(asym_x2 - 6, arr_y), (asym_x2 - 16, arr_y - 5), (asym_x2 - 16, arr_y + 5)], fill="#98c379")
    draw.text((asym_x1 + 152, arr_y - 18), "WALK IN", font=get_font(8, bold=True), fill="#98c379")

    # Blocked return cross
    draw.line((asym_x1 + 155, arr_y + 14, asym_x2 - 20, arr_y + 14), fill="#e06c75", width=2)
    draw.text((asym_x1 + 152, arr_y + 16), "TRAPPED!", font=get_font(8, bold=True), fill="#e06c75")

    draw.text((470, y_ex3 + 125), "L2GeoConverter Auto-Repair detects and neutralizes asymmetries:", font=get_font(10, bold=True), fill="#61afef")
    draw.text((470, y_ex3 + 143), "• If elevation is walkable (|ΔZ| <= 32): opens bidirectional flags.", font=f_body, fill="#abb2bf")

    for p in out_paths:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        img.save(p, "PNG")
    print(f"  [OK] Saved barriers diagram to {out_paths[0]}")

# -----------------------------------------------------------------------------
# DIAGRAM 3: CLIFF DROPS & ARCHWAY REPAIR
# -----------------------------------------------------------------------------
def make_cliffs_diagram(out_paths):
    W, H = 1040, 620
    img = Image.new("RGBA", (W, H), "#16191f")
    draw = ImageDraw.Draw(img)

    f_title = get_font(20, bold=True)
    f_sub = get_font(12, bold=False)
    f_h2 = get_font(14, bold=True)
    f_lbl = get_font(12, bold=True)
    f_body = get_font(11, bold=False)
    f_mono = get_mono_font(11)
    f_mono_b = get_mono_font(12)

    # Title Banner
    draw_rounded_rect(draw, (20, 20, W - 20, 75), 8, fill="#1f232b", outline="#2d3340", width=1)
    draw.text((36, 30), "Cliff Falls Detection (|ΔZ| > 48) and Archway Doorway Preservation", font=f_title, fill="#e06c75")
    draw.text((36, 52), "Preventing players falling under terrain without destroying walkability through city gates and portals", font=f_sub, fill="#abb2bf")

    # LEFT PANEL: Standard Cliff Drop into Abyss
    draw_rounded_rect(draw, (20, 90, 505, 600), 8, fill="#1e222a", outline="#2d3340", width=1)
    draw_rounded_rect(draw, (20, 90, 505, 126), 8, fill="#2c313a", outline="#2d3340", width=1)
    draw.text((36, 99), "Case 1: Open Cliff Drop (Fatal Fall into Void)", font=f_h2, fill="#e06c75")

    draw.text((36, 140), "When two adjacent cells have an elevation difference |ΔZ| > 48:", font=f_body, fill="#abb2bf")

    # Cliff profile drawing
    draw_rounded_rect(draw, (36, 175, 485, 420), 6, fill="#181a1f", outline="#3e4451", width=1)
    # High plateau
    draw.rectangle((56, 210, 210, 310), fill="#282c34", outline="#61afef", width=2)
    draw.text((70, 225), "High Plateau Cell", font=get_font(11, bold=True), fill="#ffffff")
    draw.text((70, 248), "Z = +100", font=f_mono_b, fill="#61afef")
    draw.text((70, 275), "Walkable terrain", font=f_body, fill="#98c379")

    # Cliff vertical drop
    draw.line((210, 210, 210, 370), fill="#e06c75", width=3)
    draw.text((220, 275), "ΔZ = 350u (> 48)", font=get_font(10, bold=True), fill="#e06c75")

    # Abyss bottom
    draw.rectangle((210, 370, 465, 405), fill="#21252b", outline="#5c6370", width=1)
    draw.text((230, 380), "Abyss / Water / Void (Z = -250)", font=f_body, fill="#abb2bf")

    # Player falling
    draw.ellipse((195, 195, 215, 215), fill="#e5c07b")
    draw.line((205, 215, 205, 240), fill="#e5c07b", width=2)
    draw.line((215, 230, 260, 330), fill="#e06c75", width=2) # drop path
    draw.polygon([(262, 335), (252, 328), (262, 320)], fill="#e06c75")
    draw.text((275, 320), "FATAL FALL!", font=get_font(11, bold=True), fill="#e06c75")

    # Solution explanation
    draw_rounded_rect(draw, (36, 435, 485, 580), 6, fill="#181a1f", outline="#98c379", width=1)
    draw.text((50, 448), "Automatic Repair Solution:", font=f_lbl, fill="#98c379")
    draw.text((50, 472), "1. Diagnostic scans detect cliff drop: |Z1 - Z2| > 48 AND Z1 > Z2.", font=f_body, fill="#abb2bf")
    draw.text((50, 492), "2. Seals FLAG_EAST on the upper cell (Plateau -> Void).", font=f_body, fill="#ffffff")
    draw.text((50, 512), "3. Result: Player cannot walk off into the void. Safe!", font=get_font(11, bold=True), fill="#98c379")
    draw.text((50, 535), "4. Low ground entry from void is unaffected.", font=f_body, fill="#abb2bf")

    # RIGHT PANEL: The Archway Bug & Correct Fix
    draw_rounded_rect(draw, (535, 90, W - 20, 600), 8, fill="#1e222a", outline="#2d3340", width=1)
    draw_rounded_rect(draw, (535, 90, W - 20, 126), 8, fill="#2c313a", outline="#2d3340", width=1)
    draw.text((551, 99), "Case 2: City Arches & Doorways (Giran Fix)", font=f_h2, fill="#61afef")

    draw.text((551, 140), "Multilayer arch structure: Ground floor + High ceiling arch roof:", font=f_body, fill="#abb2bf")

    # Arch drawing
    draw_rounded_rect(draw, (551, 175, W - 35, 420), 6, fill="#181a1f", outline="#3e4451", width=1)

    # Inside Archway Cell (Multilayer)
    draw_rounded_rect(draw, (575, 195, 735, 260), 4, fill="#282c34", outline="#e5c07b", width=2)
    draw.text((585, 205), "Arch Roof (Layer 1)", font=get_font(10, bold=True), fill="#e5c07b")
    draw.text((585, 226), "Z = 384 (High Arch)", font=f_mono, fill="#e5c07b")

    draw_rounded_rect(draw, (575, 335, 735, 400), 4, fill="#21252b", outline="#98c379", width=2)
    draw.text((585, 345), "Arch Ground (Layer 0)", font=get_font(10, bold=True), fill="#98c379")
    draw.text((585, 366), "Z = 96 (Street Level)", font=f_mono, fill="#98c379")

    # Outside Doorway Cell (Single layer)
    draw_rounded_rect(draw, (835, 335, 995, 400), 4, fill="#21252b", outline="#61afef", width=2)
    draw.text((845, 345), "Outside Street Cell", font=get_font(10, bold=True), fill="#61afef")
    draw.text((845, 366), "Z = 96 (Single Layer)", font=f_mono, fill="#61afef")

    # Ground level connection (Walkway)
    draw.line((740, 368, 830, 368), fill="#98c379", width=3)
    draw.polygon([(825, 363), (833, 368), (825, 373)], fill="#98c379")
    draw.polygon([(745, 363), (737, 368), (745, 373)], fill="#98c379")
    draw.text((750, 348), "WALKABLE", font=get_font(8, bold=True), fill="#98c379")

    # High arch pairing with ground
    draw.line((740, 226, 830, 335), fill="#e06c75", width=2)
    draw.text((752, 260), "ΔZ = 288u", font=get_font(9, bold=True), fill="#e06c75")

    # The Contrast
    draw_rounded_rect(draw, (551, 435, W - 35, 580), 6, fill="#181a1f", outline="#61afef", width=1)
    draw.text((565, 448), "Naive Repair Bug vs fa1thDEV Fix:", font=f_lbl, fill="#61afef")
    draw.text((565, 470), "• Naive Bug: Blocks BOTH cells (~FLAG_EAST and ~FLAG_WEST).", font=f_body, fill="#e06c75")
    draw.text((565, 488), "  This strips the ground flag on the outside cell, BRICKING the gate!", font=get_font(10, bold=True), fill="#e06c75")
    draw.text((565, 510), "• fa1thDEV Fix: Only seals NSWE on the HIGHER layer towards drop.", font=f_body, fill="#98c379")
    draw.text((565, 528), "  Ground level (Z=96 <-> Z=96) retains 100% bidirectional walkability.", font=get_font(10, bold=True), fill="#98c379")
    draw.text((565, 550), "  Arches in Giran, Dion, Aden and castle gates remain perfectly open!", font=f_body, fill="#abb2bf")

    for p in out_paths:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        img.save(p, "PNG")
    print(f"  [OK] Saved cliffs diagram to {out_paths[0]}")

# -----------------------------------------------------------------------------
# DIAGRAM 4: BLOCK TYPES & MULTILAYER CLEARANCE
# -----------------------------------------------------------------------------
def make_blocks_diagram(out_paths):
    W, H = 1040, 560
    img = Image.new("RGBA", (W, H), "#16191f")
    draw = ImageDraw.Draw(img)

    f_title = get_font(20, bold=True)
    f_sub = get_font(12, bold=False)
    f_h2 = get_font(13, bold=True)
    f_body = get_font(11, bold=False)
    f_mono = get_mono_font(11)

    # Title Banner
    draw_rounded_rect(draw, (20, 20, W - 20, 75), 8, fill="#1f232b", outline="#2d3340", width=1)
    draw.text((36, 30), "Geodata Block Architecture & Multilayer Clearance Rules", font=f_title, fill="#c678dd")
    draw.text((36, 52), "Block Type 0 (Flat), Block Type 1 (Complex), Block Type 2 (Multilayer) and vertical clearance", font=f_sub, fill="#abb2bf")

    # 3 Columns for Block Types
    card_w = 315
    y_top = 95
    y_bot = 535
    b_types = [
        ("Type 0: Flat Block", "#1e222a", "#3e4451", "#98c379", [
            ("Structure", "Single 16-bit Height Z for all 64 cells"),
            ("Size on Disk", "2 bytes (Ultra compact)"),
            ("NSWE State", "Implicitly 0x0F (100% passable)"),
            ("Where Used", "Oceans, flat plains, large plateaus"),
            ("Optimization", "Redundant complex blocks flattened to Type 0"),
        ]),
        ("Type 1: Complex Block", "#21252b", "#3e4451", "#61afef", [
            ("Structure", "64 independent cells (each with Z + NSWE)"),
            ("Size on Disk", "128 bytes (2 bytes per cell)"),
            ("NSWE State", "Individual 4-bit mask per cell"),
            ("Where Used", "Hills, mountains, roads, slopes, walls"),
            ("Optimization", "Can represent cliffs and directional walls"),
        ]),
        ("Type 2: Multilayer Block", "#1e222a", "#3e4451", "#e5c07b", [
            ("Structure", "Variable layers per cell (header + N layers)"),
            ("Size on Disk", "Dynamic (sum of all cell layer arrays)"),
            ("NSWE State", "Each layer has its own Z + NSWE mask"),
            ("Where Used", "Bridges, castle gates, towers, caves"),
            ("Clearance Rule", "Mandatory clearance gap >= 32 units"),
        ])
    ]

    for i, (b_title, bg_card, border_card, tag_color, specs) in enumerate(b_types):
        x1 = 20 + i * (card_w + 22)
        x2 = x1 + card_w
        draw_rounded_rect(draw, (x1, y_top, x2, y_bot), 8, fill=bg_card, outline=border_card, width=1)

        draw_rounded_rect(draw, (x1, y_top, x2, y_top + 34), 8, fill="#2c313a", outline=border_card, width=1)
        draw.text((x1 + 14, y_top + 9), b_title, font=f_h2, fill=tag_color)

        curr_y = y_top + 48
        for prop, val in specs:
            draw_rounded_rect(draw, (x1 + 10, curr_y, x2 - 10, curr_y + 54), 6, fill="#181a1f", outline="#2d3340", width=1)
            draw.text((x1 + 18, curr_y + 6), prop, font=get_font(10, bold=True), fill=tag_color)
            draw.text((x1 + 18, curr_y + 26), val, font=f_body, fill="#abb2bf")
            curr_y += 62

        # Bottom visual sketch for each type
        sketch_y = curr_y + 10
        draw_rounded_rect(draw, (x1 + 10, sketch_y, x2 - 10, y_bot - 12), 6, fill="#16181d", outline="#3e4451", width=1)
        if i == 0:
            draw.text((x1 + 20, sketch_y + 12), "Single Z for all 64 cells:", font=f_body, fill="#ffffff")
            draw.rectangle((x1 + 20, sketch_y + 36, x2 - 20, sketch_y + 54), fill="#282c34", outline="#98c379")
            draw.text((x1 + 60, sketch_y + 38), "Z = 120 (All cells flat)", font=f_mono, fill="#98c379")
        elif i == 1:
            draw.text((x1 + 20, sketch_y + 12), "64 independent cells:", font=f_body, fill="#ffffff")
            for c in range(5):
                draw.rectangle((x1 + 20 + c * 38, sketch_y + 36, x1 + 52 + c * 38, sketch_y + 54), fill="#282c34", outline="#61afef")
                draw.text((x1 + 23 + c * 38, sketch_y + 38), f"Z{c}", font=f_mono, fill="#61afef")
        elif i == 2:
            draw.text((x1 + 20, sketch_y + 8), "Multilayer Bridge Clearance:", font=f_body, fill="#ffffff")
            draw.rectangle((x1 + 20, sketch_y + 26, x2 - 20, sketch_y + 40), fill="#282c34", outline="#e5c07b")
            draw.text((x1 + 30, sketch_y + 27), "Bridge Deck Z=450", font=f_mono, fill="#e5c07b")
            draw.rectangle((x1 + 20, sketch_y + 52, x2 - 20, sketch_y + 66), fill="#282c34", outline="#98c379")
            draw.text((x1 + 30, sketch_y + 53), "Ground Z=100 (Gap=350u >= 32)", font=f_mono, fill="#98c379")

    for p in out_paths:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        img.save(p, "PNG")
    print(f"  [OK] Saved blocks diagram to {out_paths[0]}")

if __name__ == "__main__":
    make_workflow_diagram([
        "docs/images/01_workflow.png",
        "assets/guide_workflow.png"
    ])
    make_barriers_diagram([
        "docs/images/02_invisible_barriers.png",
        "assets/guide_barriers.png"
    ])
    make_cliffs_diagram([
        "docs/images/03_cliff_repair.png",
        "assets/guide_cliffs.png"
    ])
    make_blocks_diagram([
        "docs/images/04_block_types.png",
        "assets/guide_blocks.png"
    ])
    print("\nAll 4 diagrams generated successfully!")
