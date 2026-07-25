"""
gui.py -- GUI phase. The wxPython WIDGET layer.

Run with:  python3 -m orange_fur.gui

One window, four tabs (Generate / Echo / Library / Advanced), with the
command preview, Render/Cancel, and a live log pane persistent at the
bottom. All decisions live in guilib.py; this file only wires widgets to
that logic. The GUI runs the CLI as a subprocess -- what you see in the
command preview is exactly what runs, and any command here can be pasted
into a terminal (and vice versa: paste any manifest's replay token into the
Generate tab).

wxPython is an OPTIONAL dependency of this module only; the CLI never
imports it. Install: pip3 install wxPython
"""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

try:
    import wx
except ImportError:
    raise SystemExit(
        "orange-fur GUI needs wxPython:  pip3 install wxPython\n"
        "(macOS: prebuilt wheels exist for python.org Python 3.9-3.12; if "
        "pip starts a long source build, install python.org Python 3.11 "
        "and retry with that python3)")

from . import echocfg, guilib
from .guilib import CATS, GenState, Library


# --------------------------------------------------------------- helpers
def _row(parent, sizer, label, ctrl, tip=""):
    h = wx.BoxSizer(wx.HORIZONTAL)
    st = wx.StaticText(parent, label=label, size=(150, -1))
    h.Add(st, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
    h.Add(ctrl, 1, wx.EXPAND)
    if tip:
        ctrl.SetToolTip(tip)
    sizer.Add(h, 0, wx.EXPAND | wx.ALL, 3)
    return ctrl


def _spin(parent, lo, hi, val, digits=0, inc=1):
    if digits:
        c = wx.SpinCtrlDouble(parent, min=lo, max=hi, initial=val, inc=inc)
        c.SetDigits(digits)
        return c
    return wx.SpinCtrl(parent, min=int(lo), max=int(hi), initial=int(val))


class MainFrame(wx.Frame):
    def __init__(self):
        super().__init__(None, title="orange-fur", size=(880, 760))
        self.state = GenState()
        self.spec = echocfg.EchoConfig()
        self.library = Library()
        self.proc = None

        panel = wx.Panel(self)
        outer = wx.BoxSizer(wx.VERTICAL)
        self.nb = wx.Notebook(panel)
        self.nb.AddPage(self._generate_tab(self.nb), "Generate")
        self.nb.AddPage(self._echo_tab(self.nb), "Echo")
        self.nb.AddPage(self._library_tab(self.nb), "Library")
        self.nb.AddPage(self._advanced_tab(self.nb), "Advanced")
        outer.Add(self.nb, 1, wx.EXPAND | wx.ALL, 4)

        self.cmdview = wx.TextCtrl(panel, style=wx.TE_READONLY | wx.TE_MULTILINE,
                                   size=(-1, 46))
        outer.Add(wx.StaticText(panel, label="Command (paste-able):"),
                  0, wx.LEFT, 8)
        outer.Add(self.cmdview, 0, wx.EXPAND | wx.ALL, 4)

        btns = wx.BoxSizer(wx.HORIZONTAL)
        self.render_btn = wx.Button(panel, label="Render")
        self.cancel_btn = wx.Button(panel, label="Cancel")
        self.cancel_btn.Disable()
        self.token_lbl = wx.TextCtrl(panel, style=wx.TE_READONLY)
        copy_btn = wx.Button(panel, label="Copy token")
        btns.Add(self.render_btn, 0, wx.RIGHT, 6)
        btns.Add(self.cancel_btn, 0, wx.RIGHT, 18)
        btns.Add(wx.StaticText(panel, label="Last token:"),
                 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        btns.Add(self.token_lbl, 1, wx.RIGHT, 4)
        btns.Add(copy_btn, 0)
        outer.Add(btns, 0, wx.EXPAND | wx.ALL, 4)

        self.log = wx.TextCtrl(panel, style=wx.TE_READONLY | wx.TE_MULTILINE
                               | wx.TE_DONTWRAP, size=(-1, 200))
        self.log.SetFont(wx.Font(wx.FontInfo(10).Family(wx.FONTFAMILY_TELETYPE)))
        outer.Add(self.log, 1, wx.EXPAND | wx.ALL, 4)

        panel.SetSizer(outer)
        self.render_btn.Bind(wx.EVT_BUTTON, self.on_render)
        self.cancel_btn.Bind(wx.EVT_BUTTON, self.on_cancel)
        copy_btn.Bind(wx.EVT_BUTTON, self.on_copy_token)
        self.refresh_cmd()

    # ------------------------------------------------------- Generate tab
    def _generate_tab(self, nb):
        # The Generate page outgrew the window (the log pane below the
        # notebook was getting squeezed) -- it now lives in a
        # ScrolledWindow with a right-hand scrollbar; the notebook keeps
        # its share of the frame and the render log keeps its height.
        p = wx.ScrolledWindow(nb, style=wx.VSCROLL)
        p.SetScrollRate(0, 12)
        v = wx.BoxSizer(wx.VERTICAL)

        # THE PREVIEW WINDOW, prioritized per Tim: first group on the tab.
        box = wx.StaticBoxSizer(wx.VERTICAL, p,
                                "Preview window (render only minutes "
                                "in..out of the piece -- spot-check long "
                                "compositions cheaply)")
        h = wx.BoxSizer(wx.HORIZONTAL)
        self.w_from = wx.TextCtrl(p, size=(70, -1))
        self.w_to = wx.TextCtrl(p, size=(70, -1))
        h.Add(wx.StaticText(p, label="minute in:"),
              0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        h.Add(self.w_from, 0, wx.RIGHT, 12)
        h.Add(wx.StaticText(p, label="minute out:"),
              0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        h.Add(self.w_to, 0, wx.RIGHT, 12)
        h.Add(wx.StaticText(
            p, label="(empty = full piece; pairs with a replay token)"),
            0, wx.ALIGN_CENTER_VERTICAL)
        box.Add(h, 0, wx.ALL, 4)
        v.Add(box, 0, wx.EXPAND | wx.ALL, 4)

        self.g_replay = _row(p, v, "Replay token", wx.TextCtrl(p),
                             "paste a token from a report/manifest to "
                             "regenerate that piece")
        self.g_nodes = _row(p, v, "Nodes", _spin(p, 2, 300, 24))
        self.g_dur = _row(p, v, "Duration (min)",
                          _spin(p, 0.2, 120, 5.0, digits=1, inc=0.5))
        self.g_sections = _row(p, v, "Sections (0=auto)", _spin(p, 0, 64, 0))
        self.g_space = _row(p, v, "Space", _spin(p, 0, 1, 0.5, 2, 0.05))
        self.g_air = _row(p, v, "Air", _spin(p, 0, 1, 0.25, 2, 0.05))
        self.g_wetdry = _row(p, v, "Wet/dry", _spin(p, 0, 1, 0.35, 2, 0.05))
        self.g_subset = _row(p, v, "Subset %", _spin(p, 10, 100, 50))
        self.g_state = _row(p, v, "State", wx.TextCtrl(p, value=""),
                            "Phase 22 hidden-weather consumers. Remix knob "
                            "(shares the replay token); empty = off")
        _sh = wx.StaticText(p, label="  options: fields, density, register, "
                                     "air, rooms -- or the word 'all' "
                                     "(comma-separated)")
        _sh.SetForegroundColour(wx.Colour(96, 96, 96))
        v.Add(_sh, 0, wx.LEFT | wx.BOTTOM, 6)
        self.g_morph = _row(p, v, "Morph", _spin(p, 0, 1, 0.0, 2, 0.05),
                            "Phase 23 continuous-morph form family: how "
                            "readily section boundaries become crossfaded "
                            "morph joints instead of clean cuts; 0 = off. "
                            "Remix knob (shares the replay token)")
        self.g_dynamics = _row(p, v, "Dynamics",
                               wx.Choice(p, choices=["default", "quiet",
                                                     "mid", "limited"]),
                               "Phase 21 preset: remix knob, one token four "
                               "dynamic readings; no limiter anywhere")
        self.g_dynamics.SetSelection(0)
        self.g_surface = _row(p, v, "Surface %", _spin(p, 0, 100, 0),
                              "Phase 20 SURFACE category (crackle/dust/hiss/"
                              "transients) target share of terminals; 0 = "
                              "off. GENERATION param: must match for replay")
        self.g_tension = _row(p, v, "Tension", _spin(p, 0, 1, 0.0, 2, 0.05),
                              "roughness-trajectory strength 0-1: sections "
                              "draw a sensory-dissonance target and harmony "
                              "bends toward it; 0 = off")
        self.g_spectral = _row(p, v, "Spectral %", _spin(p, 0, 100, 0),
                               "percent of sections drawing spectral "
                               "(true-partial) harmony")
        self.g_echo = _row(p, v, "Echo scale", _spin(p, 0, 3, 1.0, 2, 0.1))
        self.g_fields = wx.CheckBox(p, label="Harmonic fields")
        self.g_fields.SetValue(True)
        v.Add(self.g_fields, 0, wx.ALL, 4)
        self.g_draft = wx.CheckBox(p, label="Draft (48k -- the working mode)")
        self.g_draft.SetValue(True)
        v.Add(self.g_draft, 0, wx.ALL, 4)
        self.g_tag = _row(p, v, "Filename tag", wx.TextCtrl(p))
        self.g_out = _row(p, v, "Output folder", wx.TextCtrl(p))

        for c in (self.w_from, self.w_to, self.g_replay, self.g_tag,
                  self.g_out):
            c.Bind(wx.EVT_TEXT, lambda e: self.refresh_cmd())
        for c in (self.g_nodes, self.g_dur, self.g_sections, self.g_space,
                  self.g_air, self.g_wetdry, self.g_subset, self.g_spectral,
                  self.g_tension, self.g_surface, self.g_dynamics,
                  self.g_state, self.g_morph,
                  self.g_echo):
            c.Bind(wx.EVT_SPINCTRL, lambda e: self.refresh_cmd())
            c.Bind(wx.EVT_SPINCTRLDOUBLE, lambda e: self.refresh_cmd())
        self.g_fields.Bind(wx.EVT_CHECKBOX, lambda e: self.refresh_cmd())
        self.g_draft.Bind(wx.EVT_CHECKBOX, lambda e: self.refresh_cmd())
        p.SetSizer(v)
        v.FitInside(p)          # virtual size for the scrollbar
        return p

    # ----------------------------------------------------------- Echo tab
    def _echo_tab(self, nb):
        p = wx.ScrolledWindow(nb)
        p.SetScrollRate(0, 12)
        v = wx.BoxSizer(wx.VERTICAL)
        self.e_widgets = {}

        def wtable(title, d, key):
            box = wx.StaticBoxSizer(wx.VERTICAL, p, title)
            for k, val in d.items():
                if isinstance(val, bool):
                    c = wx.CheckBox(p, label=k)
                    c.SetValue(val)
                elif isinstance(val, list):
                    h = wx.BoxSizer(wx.HORIZONTAL)
                    lo = _spin(p, 0, 64, val[0], 2, 0.05)
                    hi = _spin(p, 0, 64, val[1], 2, 0.05)
                    h.Add(wx.StaticText(p, label=k, size=(110, -1)), 0,
                          wx.ALIGN_CENTER_VERTICAL)
                    h.Add(lo, 0, wx.RIGHT, 4)
                    h.Add(hi, 0)
                    box.Add(h, 0, wx.ALL, 2)
                    self.e_widgets[(key, k)] = (lo, hi)
                    continue
                else:
                    c = _spin(p, 0, 100, float(val), 2, 0.05)
                if not isinstance(val, list):
                    h = wx.BoxSizer(wx.HORIZONTAL)
                    h.Add(wx.StaticText(p, label=k, size=(110, -1)), 0,
                          wx.ALIGN_CENTER_VERTICAL)
                    h.Add(c, 0)
                    box.Add(h, 0, wx.ALL, 2)
                    self.e_widgets[(key, k)] = c
            v.Add(box, 0, wx.EXPAND | wx.ALL, 4)

        so = wx.RadioBox(p, label="second order (echoes of echoes)",
                         choices=["off", "drawn", "always"])
        v.Add(so, 0, wx.ALL, 4)
        self.e_so = so
        wtable("timing family weights", self.spec.timing, "timing")
        wtable("uniform", self.spec.uniform, "uniform")
        wtable("multitap", self.spec.multitap, "multitap")
        wtable("euclid", self.spec.euclid, "euclid")
        wtable("ramp", self.spec.ramp, "ramp")
        wtable("pitch modes", self.spec.modes, "modes")
        wtable("pan", self.spec.pan, "pan")
        wtable("rotation", self.spec.rotation, "rotation")
        wtable("tail gestures", self.spec.gestures, "gestures")
        wtable("varispeed (tape-speed automation on echoes/loops)",
               self.spec.varispeed, "varispeed")

        h = wx.BoxSizer(wx.HORIZONTAL)
        load_b = wx.Button(p, label="Load .toml")
        save_b = wx.Button(p, label="Save .toml + use")
        clear_b = wx.Button(p, label="No spec (P9-P11 defaults)")
        h.Add(load_b, 0, wx.RIGHT, 6)
        h.Add(save_b, 0, wx.RIGHT, 6)
        h.Add(clear_b, 0)
        v.Add(h, 0, wx.ALL, 6)
        load_b.Bind(wx.EVT_BUTTON, self.on_spec_load)
        save_b.Bind(wx.EVT_BUTTON, self.on_spec_save)
        clear_b.Bind(wx.EVT_BUTTON, self.on_spec_clear)
        p.SetSizer(v)
        return p

    def _spec_from_widgets(self):
        ec = echocfg.EchoConfig()
        ec.second_order = ["off", "drawn", "always"][self.e_so.GetSelection()]
        for (key, k), w in self.e_widgets.items():
            d = getattr(ec, key)
            if isinstance(w, tuple):
                d[k] = [w[0].GetValue(), w[1].GetValue()]
            elif isinstance(w, wx.CheckBox):
                d[k] = w.GetValue()
            else:
                d[k] = float(w.GetValue())
        return ec

    def _widgets_from_spec(self, ec):
        self.e_so.SetSelection(["off", "drawn", "always"]
                               .index(ec.second_order))
        for (key, k), w in self.e_widgets.items():
            val = getattr(ec, key)[k]
            if isinstance(w, tuple):
                w[0].SetValue(val[0])
                w[1].SetValue(val[1])
            elif isinstance(w, wx.CheckBox):
                w.SetValue(bool(val))
            else:
                w.SetValue(float(val))

    # -------------------------------------------------------- Library tab
    def _library_tab(self, nb):
        p = wx.Panel(nb)
        v = wx.BoxSizer(wx.VERTICAL)
        self.lib_list = wx.ListCtrl(p, style=wx.LC_REPORT)
        for i, (name, wdt) in enumerate(
                [("keep", 50), ("date", 150), ("token", 190),
                 ("note", 180), ("output", 240)]):
            self.lib_list.InsertColumn(i, name, width=wdt)
        v.Add(self.lib_list, 1, wx.EXPAND | wx.ALL, 4)
        h = wx.BoxSizer(wx.HORIZONTAL)
        keep_b = wx.Button(p, label="Toggle keep")
        note_b = wx.Button(p, label="Edit note")
        replay_b = wx.Button(p, label="Load into Generate")
        prune_b = wx.Button(p, label="Prune non-keepers")
        for b in (keep_b, note_b, replay_b, prune_b):
            h.Add(b, 0, wx.RIGHT, 6)
        v.Add(h, 0, wx.ALL, 4)
        keep_b.Bind(wx.EVT_BUTTON, self.on_lib_keep)
        note_b.Bind(wx.EVT_BUTTON, self.on_lib_note)
        replay_b.Bind(wx.EVT_BUTTON, self.on_lib_replay)
        prune_b.Bind(wx.EVT_BUTTON, self.on_lib_prune)
        p.SetSizer(v)
        self.refresh_library()
        return p

    def refresh_library(self):
        self.lib_list.DeleteAllItems()
        for e in self.library.entries:
            i = self.lib_list.InsertItem(self.lib_list.GetItemCount(),
                                         "*" if e["keep"] else "")
            self.lib_list.SetItem(i, 1, e["date"])
            self.lib_list.SetItem(i, 2, e["token"])
            self.lib_list.SetItem(i, 3, e.get("note", ""))
            self.lib_list.SetItem(i, 4, e.get("out", ""))

    def _lib_sel(self):
        i = self.lib_list.GetFirstSelected()
        return self.library.entries[i] if i >= 0 else None

    def on_lib_keep(self, _):
        e = self._lib_sel()
        if e:
            self.library.set_keep(e["token"], not e["keep"])
            self.refresh_library()

    def on_lib_note(self, _):
        e = self._lib_sel()
        if e:
            dlg = wx.TextEntryDialog(self, "Note:", value=e.get("note", ""))
            if dlg.ShowModal() == wx.ID_OK:
                self.library.set_note(e["token"], dlg.GetValue())
                self.refresh_library()

    def on_lib_replay(self, _):
        e = self._lib_sel()
        if e:
            self.g_replay.SetValue(e["token"])
            self.nb.SetSelection(0)
            self.refresh_cmd()

    def on_lib_prune(self, _):
        n = self.library.prune()
        self.refresh_library()
        wx.MessageBox(f"removed {n} non-keeper entries")

    # ------------------------------------------------------- Advanced tab
    def _advanced_tab(self, nb):
        p = wx.Panel(nb)
        v = wx.BoxSizer(wx.VERTICAL)
        box = wx.StaticBoxSizer(wx.VERTICAL, p,
                                "Per-category subset %% (0 = inherit "
                                "global subset; generation parameter -- "
                                "must match for replay)")
        self.a_cats = {}
        for name in CATS:
            c = _spin(p, 0, 100, 0)
            _row(p, box, name, c)
            c.Bind(wx.EVT_SPINCTRL, lambda e: self.refresh_cmd())
            self.a_cats[name] = c
        v.Add(box, 0, wx.EXPAND | wx.ALL, 4)
        self.a_scl = _row(p, v, ".scl file", wx.TextCtrl(p))
        self.a_basefreq = _row(p, v, "Base freq", wx.TextCtrl(p))
        self.a_basekey = _row(p, v, "Base key", wx.TextCtrl(p))
        self.a_costcap = _row(p, v, "Cost cap", wx.TextCtrl(p))
        self.a_csound = _row(p, v, "csound binary", wx.TextCtrl(p))
        for c in (self.a_scl, self.a_basefreq, self.a_basekey,
                  self.a_costcap, self.a_csound):
            c.Bind(wx.EVT_TEXT, lambda e: self.refresh_cmd())
        p.SetSizer(v)
        return p

    # -------------------------------------------------------- state sync
    def _pull_state(self) -> GenState:
        s = GenState(
            nodes=self.g_nodes.GetValue(),
            duration=float(self.g_dur.GetValue()),
            sections=self.g_sections.GetValue(),
            space=float(self.g_space.GetValue()),
            air=float(self.g_air.GetValue()),
            wetdry=float(self.g_wetdry.GetValue()),
            subset=float(self.g_subset.GetValue()),
            spectral=float(self.g_spectral.GetValue()),
            tension=float(self.g_tension.GetValue()),
            surface=float(self.g_surface.GetValue()),
            dynamics=["default", "quiet", "mid", "limited"][
                max(0, self.g_dynamics.GetSelection())],
            state=self.g_state.GetValue(),
            morph=float(self.g_morph.GetValue()),
            fields=self.g_fields.GetValue(),
            echo=float(self.g_echo.GetValue()),
            echo_spec=self.state.echo_spec,
            draft=self.g_draft.GetValue(),
            tag=self.g_tag.GetValue(),
            out_dir=self.g_out.GetValue(),
            replay=self.g_replay.GetValue(),
            win_from=self.w_from.GetValue(),
            win_to=self.w_to.GetValue(),
            scl=self.a_scl.GetValue(),
            basefreq=self.a_basefreq.GetValue(),
            basekey=self.a_basekey.GetValue(),
            cost_cap=self.a_costcap.GetValue(),
            csound=self.a_csound.GetValue(),
        )
        s.subset_cat = {n: float(c.GetValue())
                        for n, c in self.a_cats.items() if c.GetValue()}
        return s

    def refresh_cmd(self):
        self.state = self._pull_state()
        errs = self.state.validate()
        self.cmdview.SetValue(
            ("!! " + "; ".join(errs)) if errs else self.state.display())
        self.render_btn.Enable(not errs)

    # --------------------------------------------------------- rendering
    def on_render(self, _):
        self.refresh_cmd()
        if not self.render_btn.IsEnabled():
            return
        self.log.SetValue("")
        self.render_btn.Disable()
        self.cancel_btn.Enable()
        argv = self.state.argv()
        self._out_txt = []
        self.proc = subprocess.Popen(argv, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True)
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        for line in self.proc.stdout:
            self._out_txt.append(line)
            wx.CallAfter(self.log.AppendText, line)
        rc = self.proc.wait()
        wx.CallAfter(self._done, rc)

    def _done(self, rc):
        self.render_btn.Enable()
        self.cancel_btn.Disable()
        text = "".join(self._out_txt)
        tok = self.library.find_token(text)
        if tok:
            self.token_lbl.SetValue(tok)
        if rc == 0 and tok:
            out = ""
            for ln in text.splitlines():
                if ln.strip().startswith("output"):
                    out = ln.split(None, 1)[1].strip()
            self.library.record(tok, self.state.display(), out)
            self.refresh_library()
        self.log.AppendText(f"\n[exit {rc}]\n")

    def on_cancel(self, _):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.log.AppendText("\n[cancelled]\n")

    def on_copy_token(self, _):
        tok = self.token_lbl.GetValue()
        if tok and wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(tok))
            wx.TheClipboard.Close()

    # -------------------------------------------------------- spec files
    # wx wildcard strings MUST be "description|pattern" -- a bare
    # "*.toml" is malformed and wxOSX asserts when applying the filter,
    # killing the handler AFTER the native panel closes: the save dialog
    # appeared, the file never did. (The manual checklist caught this;
    # both handlers now also surface ANY exception instead of letting the
    # event loop swallow it.)
    _WILDCARD = "TOML files (*.toml)|*.toml|All files (*.*)|*.*"

    def on_spec_save(self, _):
        dlg = wx.FileDialog(self, "Save echo spec", wildcard=self._WILDCARD,
                            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
        if dlg.ShowModal() != wx.ID_OK:
            return
        try:
            written = guilib.save_spec(self._spec_from_widgets(),
                                       dlg.GetPath())
            self.state.echo_spec = written
            self.refresh_cmd()
        except SystemExit as e:
            wx.MessageBox(str(e), "spec invalid")
        except Exception as e:              # never silent in a handler
            wx.MessageBox(f"{type(e).__name__}: {e}", "save failed")

    def on_spec_load(self, _):
        dlg = wx.FileDialog(self, "Load echo spec", wildcard=self._WILDCARD)
        if dlg.ShowModal() != wx.ID_OK:
            return
        try:
            ec = echocfg.load(dlg.GetPath())
            self.spec = ec
            self._widgets_from_spec(ec)
            self.state.echo_spec = dlg.GetPath()
            self.refresh_cmd()
        except SystemExit as e:
            wx.MessageBox(str(e), "spec invalid")
        except Exception as e:
            wx.MessageBox(f"{type(e).__name__}: {e}", "load failed")

    def on_spec_clear(self, _):
        self.spec = echocfg.EchoConfig()
        self._widgets_from_spec(self.spec)
        self.state.echo_spec = ""
        self.refresh_cmd()


def main():
    app = wx.App()
    MainFrame().Show()
    app.MainLoop()


if __name__ == "__main__":
    main()
