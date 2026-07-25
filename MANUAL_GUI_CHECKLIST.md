# Manual GUI checklist (widget layer)

The logic layer (command building, validation, TOML round-trip, library
store) is machine-tested in tests/test_gui.py. The widget layer cannot be
tested in the development sandbox (no display), so this checklist is the
verification for it. One pass on your machine covers it. Expected time:
~10 minutes plus one short render.

## 0. Install & launch

    pip3 install wxPython
    # (if pip starts compiling from source for a long time: install
    #  python.org Python 3.11, then use ITS pip3 and python3 below)
    cd ~/path/to/orange_fur_gui
    python3 -m orange_fur.gui

- [ ] Window opens: four tabs, command line visible at the bottom,
      Render/Cancel buttons, empty log pane.
- [ ] The command reads exactly:
      `python3 -m orange_fur --nodes 24 --duration 5 --space 0.5
       --air 0.25 --wetdry 0.35 --subset 50 --draft`

## 1. Generate tab

- [ ] The FIRST group on the tab is the Preview window (minute in / out).
- [ ] Type `1` into minute-in only -> command area shows an error and
      Render disables. Add `2` to minute-out -> `--from 1 --to 2`
      appears, Render enables.
- [ ] Clear both -> flags disappear.
- [ ] Move any spinner (nodes, spectral, echo scale) -> command updates
      immediately.
- [ ] Untick "Harmonic fields" -> `--fields 0` appears.

## 2. First render

- [ ] Set duration 2, nodes 12, leave draft ticked. Press Render.
- [ ] Log pane streams the CLI report live (orchestra line, fields line,
      density, render progress).
- [ ] On completion: `[exit 0]` in the log; the replay token appears in
      "Last token"; "Copy token" puts it on the clipboard (paste into
      TextEdit to confirm).
- [ ] Press Render again and press Cancel mid-render -> `[cancelled]`,
      buttons return to idle.

## 3. Library tab

- [ ] The completed render(s) appear, newest first, with date + token.
- [ ] Select one -> "Toggle keep" puts `*` in the keep column.
- [ ] "Edit note" stores a note; quit the GUI, relaunch: entry, keep
      marker, and note persist.
- [ ] "Load into Generate" fills the replay field and switches tabs; the
      command shows `--replay <token>`. Render -> report shows the SAME
      token (regenerated piece).
- [ ] "Prune non-keepers" removes only unmarked rows.

## 4. Echo tab

- [ ] Change ramp weight to 1.0 and the other three family weights to 0.
- [ ] "Save .toml + use" -> pick a path (typing a bare name without
      `.toml` is fine; the extension is added) -> command gains
      `--echo-spec <path>`, and the file exists in the chosen folder.
- [ ] Any failure in save/load now raises a visible error dialog --
      silent no-ops are themselves a bug; report them.
- [ ] Open the saved file in a text editor: readable TOML, `schema = 1`,
      your weights under `[echo.timing.weights]`.
- [ ] Render a 2-minute piece -> the echoes report line shows `ramp`
      treatments.
- [ ] "Load .toml" on examples/echo-spec.toml -> widgets repopulate.
- [ ] "No spec" -> `--echo-spec` leaves the command.

## 5. Advanced tab

- [ ] Set GONG to 100 and CLOUD to 10 -> command gains
      `--subset-cat GONG=100,CLOUD=10` (order may differ).
- [ ] Render -> orchestra line reflects the skew (subset count changes).
- [ ] Reset both to 0 -> flag disappears.

## 6. Round-trip with the terminal

- [ ] Copy the full command from the command area, paste into Terminal,
      run it there: identical behavior. (The GUI is a front-end, not a
      second implementation -- this check is the proof.)

Anything that fails here is a widget-layer bug: report the checklist line
and what happened instead.

## P23 additions
- [ ] Generate tab shows a right-hand scrollbar when the window is short;
      scrolling reaches every control; the render log below the notebook
      keeps a usable height (no longer squished).
- [ ] Under the State field, gray helper text lists the options: fields,
      density, register, air, rooms -- or the word 'all'.
- [ ] Mouse-wheel scrolls the Generate page (macOS: two-finger scroll).
