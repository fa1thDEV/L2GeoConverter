#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Desktop GUI builds every tab and the guide window (needs Tk + a display)."""

import io
import os
import sys
import unittest

try:
    import tkinter
except ImportError:  # python built without Tk
    tkinter = None


def _display_available():
    if tkinter is None:
        return False
    if sys.platform.startswith('linux') and not os.environ.get('DISPLAY'):
        return False
    try:
        tkinter.Tk().destroy()
        return True
    except tkinter.TclError:
        return False


@unittest.skipUnless(_display_available(), 'Tkinter or a display is not available')
class GuiSmokeTests(unittest.TestCase):
    def setUp(self):
        from geolib.gui import L2GeoConverterGUI
        self._stdout, self._stderr = sys.stdout, sys.stderr
        self.root = tkinter.Tk()
        self.root.withdraw()
        self.app = L2GeoConverterGUI(self.root)
        self.root.update_idletasks()

    def tearDown(self):
        sys.stdout, sys.stderr = self._stdout, self._stderr
        self.root.destroy()

    def test_all_tabs_built(self):
        tabs = self.app.notebook.tabs()
        self.assertEqual(len(tabs), 7)
        self.assertIn('Geo Editor', self.app.notebook.tab(tabs[-1], 'text'))

    def test_stdout_redirected_to_console(self):
        print('smoke-marker')
        self.root.update()
        self.assertIn('smoke-marker', self.app.console.get('1.0', 'end'))

    def test_guide_window_opens(self):
        self.app._open_guide_window()
        self.root.update_idletasks()

    def test_error_dialog_lambda_keeps_exception(self):
        # Worker threads report errors via root.after(lambda e=e: ...); the
        # exception must still be bound when the callback runs.
        shown = []
        from geolib.gui import tab_diff
        orig = tab_diff.messagebox.showerror
        tab_diff.messagebox.showerror = lambda title, msg: shown.append(msg)
        orig_cmd = tab_diff.cmd_diff
        tab_diff.cmd_diff = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom'))
        try:
            here = os.path.dirname(os.path.abspath(__file__))
            self.app.diff_a_var.set(here)
            self.app.diff_b_var.set(here)
            self.app._execute_diff()
            # Tk calls from the worker thread need the main thread in mainloop.
            deadline = [200]

            def poll():
                deadline[0] -= 1
                if shown or deadline[0] <= 0:
                    self.root.quit()
                else:
                    self.root.after(10, poll)
            self.root.after(10, poll)
            self.root.mainloop()
        finally:
            tab_diff.messagebox.showerror = orig
            tab_diff.cmd_diff = orig_cmd
        self.assertTrue(shown and 'boom' in shown[0], shown)


if __name__ == '__main__':
    unittest.main()
