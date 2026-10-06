# -*- coding: utf-8 -*-
"""Shared GUI helpers: optional Pillow, application root, stdout redirector."""

import os
import re

try:
    from PIL import Image as PILImage, ImageTk
    HAS_PIL = True
except Exception:
    PILImage = ImageTk = None
    HAS_PIL = False

# Repository / bundle root (where assets/ and docs/ live): two levels above
# this package (geolib/gui -> repo root).
APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))


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
