"""Accessible GUI for Stream Watcher — Settings and Status windows.

Built with wxPython for native screen-reader support (VoiceOver on macOS,
JAWS/NVDA on Windows).  wxPython uses native Cocoa widgets on macOS and
Win32 on Windows, which automatically participate in the OS accessibility
hierarchy.

All controls have explicit accessible names, keyboard shortcuts, logical
tab order, and high-contrast colours that meet WCAG 2.2 AA requirements.

Includes a press-to-record hotkey capture widget so users can define
any keyboard shortcut by pressing the keys rather than typing combo strings.
"""

import logging
import os
from typing import TYPE_CHECKING

import wx

from acb_sync.config import (
    COLLISION_OVERWRITE,
    COLLISION_RENAME,
    COLLISION_SKIP,
    DEFAULT_RENAME_PATTERN,
    RENAME_PATTERN_HELP,
    get_log_path,
)
from acb_sync.platform_utils import (
    get_super_modifier_label,
    open_file_in_default_app,
)

if TYPE_CHECKING:
    from acb_sync.app import App

logger = logging.getLogger(__name__)

_SUPER_MOD = get_super_modifier_label()  # "command" on macOS, "win" elsewhere

# ---- Accessible colour palette (WCAG 2.2 AA contrast >= 4.5:1) ----
ERROR_FG = "#C4001A"
SUCCESS_FG = "#0A6E0A"

# Human-readable collision mode labels
_COLLISION_LABELS = {
    COLLISION_RENAME: "Rename (add number)",
    COLLISION_SKIP: "Skip (do not copy)",
    COLLISION_OVERWRITE: "Overwrite existing",
}
_COLLISION_VALUES = list(_COLLISION_LABELS.keys())

# wx keycode → human-readable modifier name
_WX_MOD_KEYCODES: dict[int, str] = {
    wx.WXK_CONTROL: "ctrl",
    wx.WXK_RAW_CONTROL: "ctrl",
    wx.WXK_SHIFT: "shift",
    wx.WXK_ALT: "alt",
    wx.WXK_WINDOWS_LEFT: _SUPER_MOD,
    wx.WXK_WINDOWS_RIGHT: _SUPER_MOD,
    wx.WXK_COMMAND: _SUPER_MOD,
}

# Special keycodes → name
_WX_SPECIAL_KEYS: dict[int, str] = {
    wx.WXK_F1: "f1",
    wx.WXK_F2: "f2",
    wx.WXK_F3: "f3",
    wx.WXK_F4: "f4",
    wx.WXK_F5: "f5",
    wx.WXK_F6: "f6",
    wx.WXK_F7: "f7",
    wx.WXK_F8: "f8",
    wx.WXK_F9: "f9",
    wx.WXK_F10: "f10",
    wx.WXK_F11: "f11",
    wx.WXK_F12: "f12",
    wx.WXK_SPACE: "space",
    wx.WXK_TAB: "tab",
    wx.WXK_RETURN: "enter",
    wx.WXK_BACK: "backspace",
    wx.WXK_DELETE: "delete",
    wx.WXK_HOME: "home",
    wx.WXK_END: "end",
    wx.WXK_PAGEUP: "pageup",
    wx.WXK_PAGEDOWN: "pagedown",
    wx.WXK_UP: "up",
    wx.WXK_DOWN: "down",
    wx.WXK_LEFT: "left",
    wx.WXK_RIGHT: "right",
    wx.WXK_INSERT: "insert",
    wx.WXK_NUMPAD0: "num0",
    wx.WXK_NUMPAD1: "num1",
    wx.WXK_NUMPAD2: "num2",
    wx.WXK_NUMPAD3: "num3",
    wx.WXK_NUMPAD4: "num4",
    wx.WXK_NUMPAD5: "num5",
    wx.WXK_NUMPAD6: "num6",
    wx.WXK_NUMPAD7: "num7",
    wx.WXK_NUMPAD8: "num8",
    wx.WXK_NUMPAD9: "num9",
}


def _keycode_to_name(keycode: int) -> str:
    """Convert a wx keycode to a human-readable key name."""
    if keycode in _WX_SPECIAL_KEYS:
        return _WX_SPECIAL_KEYS[keycode]
    # Printable ASCII
    if 33 <= keycode <= 126:
        return chr(keycode).lower()
    return ""


# ======================================================================
# Hotkey recorder widget
# ======================================================================


class HotkeyRecorder:
    """An accessible press-to-record control for capturing keyboard shortcuts.

    The user clicks "Record" (or presses Enter on it), then presses their
    desired key combination.  The captured combo is written in ``keyboard``
    library format (e.g. ``ctrl+shift+f9``).

    A "Clear" button removes any assigned hotkey.
    """

    def __init__(
        self,
        parent: wx.Window,
        sizer: wx.FlexGridSizer,
        label_text: str,
        initial_value: str = "",
    ):
        """Create a hotkey recorder row in *parent*, added to *sizer*."""
        self._value = initial_value
        self._recording = False
        self._pressed_mods: set[str] = set()
        self._pressed_key: str = ""
        self._parent = parent

        label = wx.StaticText(parent, label=label_text)
        sizer.Add(label, flag=wx.ALIGN_CENTER_VERTICAL | wx.LEFT, border=10)

        row_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self._display = wx.TextCtrl(
            parent,
            value=initial_value,
            size=(160, -1),
            style=wx.TE_READONLY,
        )
        self._display.SetName(label_text)
        row_sizer.Add(self._display, flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=5)

        self._rec_btn = wx.Button(parent, label="Record", size=(70, -1))
        self._rec_btn.Bind(wx.EVT_BUTTON, self._on_toggle_record)
        row_sizer.Add(self._rec_btn, flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=5)

        self._clr_btn = wx.Button(parent, label="Clear", size=(60, -1))
        self._clr_btn.Bind(wx.EVT_BUTTON, self._on_clear)
        row_sizer.Add(self._clr_btn, flag=wx.ALIGN_CENTER_VERTICAL)

        sizer.Add(row_sizer, flag=wx.EXPAND | wx.RIGHT, border=10)

    def GetValue(self) -> str:
        """Return the current hotkey combo string."""
        return self._value

    def _on_toggle_record(self, event: wx.CommandEvent) -> None:
        if self._recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self) -> None:
        self._recording = True
        self._pressed_mods.clear()
        self._pressed_key = ""
        self._rec_btn.SetLabel("Stop")
        self._display.SetValue("Press keys\u2026")
        top = self._parent.GetTopLevelParent()
        top.Bind(wx.EVT_CHAR_HOOK, self._on_key_press)

    def _stop_recording(self) -> None:
        self._recording = False
        self._rec_btn.SetLabel("Record")
        top = self._parent.GetTopLevelParent()
        top.Unbind(wx.EVT_CHAR_HOOK)
        combo = self._build_combo()
        self._value = combo
        self._display.SetValue(combo)

    def _on_clear(self, event: wx.CommandEvent) -> None:
        if self._recording:
            self._stop_recording()
        self._value = ""
        self._display.SetValue("")

    def _on_key_press(self, event: wx.KeyEvent) -> None:
        keycode = event.GetKeyCode()

        if keycode in _WX_MOD_KEYCODES:
            self._pressed_mods.add(_WX_MOD_KEYCODES[keycode])
            # Don't skip — consume the event
            return

        if keycode == wx.WXK_ESCAPE:
            self._value = ""
            self._display.SetValue("")
            self._stop_recording()
            return

        # Also capture modifiers from event state
        if event.ControlDown():
            self._pressed_mods.add("ctrl")
        if event.AltDown():
            self._pressed_mods.add("alt")
        if event.ShiftDown():
            self._pressed_mods.add("shift")
        if event.MetaDown() or event.CmdDown():
            self._pressed_mods.add(_SUPER_MOD)

        name = _keycode_to_name(keycode)
        if name:
            self._pressed_key = name
            self._stop_recording()
        # Don't call event.Skip() — consume all keys while recording

    def _build_combo(self) -> str:
        parts: list[str] = []
        for mod in ("ctrl", "alt", "shift", _SUPER_MOD):
            if mod in self._pressed_mods:
                parts.append(mod)
        if self._pressed_key:
            parts.append(self._pressed_key)
        return "+".join(parts) if parts else ""


# ======================================================================
# Settings window
# ======================================================================


class SettingsWindow:
    """Accessible settings dialog for configuring Stream Watcher."""

    def __init__(self, app: "App"):
        """Create the settings window (hidden until ``show`` is called)."""
        self._app = app
        self._win: wx.Dialog | None = None

    def show(self) -> None:
        """Show or focus the settings window."""
        if self._win is not None:
            self._win.Raise()
            self._win.SetFocus()
            return
        self._build()

    def _build(self) -> None:
        cfg = self._app.config

        self._win = wx.Dialog(
            None,
            title="Stream Watcher \u2014 Settings",
            size=(720, 780),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self._win.SetMinSize((620, 680))
        self._win.Bind(wx.EVT_CLOSE, self._on_close_event)
        self._win.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)

        # Scrollable content area
        scrolled = wx.ScrolledWindow(self._win, style=wx.VSCROLL)
        scrolled.SetScrollRate(0, 20)

        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # ---- Header ----
        header = wx.StaticText(scrolled, label="Settings")
        header_font = header.GetFont()
        header_font.SetPointSize(14)
        header_font.MakeBold()
        header.SetFont(header_font)
        main_sizer.Add(header, flag=wx.ALL, border=10)

        # ============ Folders ============
        folder_box = wx.StaticBox(scrolled, label="Folders")
        folder_sizer = wx.StaticBoxSizer(folder_box, wx.VERTICAL)
        folder_grid = wx.FlexGridSizer(cols=3, vgap=6, hgap=5)
        folder_grid.AddGrowableCol(1, 1)

        # Source folder
        lbl = wx.StaticText(scrolled, label="Source folder:")
        folder_grid.Add(lbl, flag=wx.ALIGN_CENTER_VERTICAL | wx.LEFT, border=10)
        self._source_ctrl = wx.TextCtrl(scrolled, value=cfg.source_folder)
        self._source_ctrl.SetName("Source folder")
        folder_grid.Add(self._source_ctrl, flag=wx.EXPAND)
        browse_src = wx.Button(scrolled, label="Browse\u2026")
        browse_src.Bind(wx.EVT_BUTTON, self._browse_source)
        folder_grid.Add(browse_src, flag=wx.RIGHT, border=10)

        # Destination folder
        lbl = wx.StaticText(scrolled, label="Destination folder:")
        folder_grid.Add(lbl, flag=wx.ALIGN_CENTER_VERTICAL | wx.LEFT, border=10)
        self._dest_ctrl = wx.TextCtrl(scrolled, value=cfg.destination_folder)
        self._dest_ctrl.SetName("Destination folder")
        folder_grid.Add(self._dest_ctrl, flag=wx.EXPAND)
        browse_dst = wx.Button(scrolled, label="Browse\u2026")
        browse_dst.Bind(wx.EVT_BUTTON, self._browse_dest)
        folder_grid.Add(browse_dst, flag=wx.RIGHT, border=10)

        folder_sizer.Add(folder_grid, flag=wx.EXPAND | wx.ALL, border=4)

        self._subdirs_cb = wx.CheckBox(scrolled, label="Include subdirectories")
        self._subdirs_cb.SetValue(cfg.copy_subdirectories)
        self._subdirs_cb.SetName("Include subdirectories")
        folder_sizer.Add(self._subdirs_cb, flag=wx.LEFT | wx.BOTTOM, border=10)

        main_sizer.Add(
            folder_sizer,
            flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            border=10,
        )

        # ============ Timing ============
        timing_box = wx.StaticBox(scrolled, label="Timing")
        timing_sizer = wx.StaticBoxSizer(timing_box, wx.VERTICAL)
        timing_grid = wx.FlexGridSizer(cols=2, vgap=6, hgap=5)
        timing_grid.AddGrowableCol(1, 1)

        lbl = wx.StaticText(scrolled, label="Check interval (seconds):")
        timing_grid.Add(lbl, flag=wx.ALIGN_CENTER_VERTICAL | wx.LEFT, border=10)
        self._interval_spin = wx.SpinCtrl(
            scrolled, value=str(cfg.check_interval), min=5, max=3600, size=(100, -1)
        )
        self._interval_spin.SetName("Check interval seconds")
        timing_grid.Add(self._interval_spin, flag=wx.RIGHT, border=10)

        lbl = wx.StaticText(scrolled, label="Stable time before copy (seconds):")
        timing_grid.Add(lbl, flag=wx.ALIGN_CENTER_VERTICAL | wx.LEFT, border=10)
        self._stable_spin = wx.SpinCtrl(
            scrolled, value=str(cfg.stable_time), min=0, max=3600, size=(100, -1)
        )
        self._stable_spin.SetName("Stable time seconds")
        timing_grid.Add(self._stable_spin, flag=wx.RIGHT, border=10)

        timing_sizer.Add(timing_grid, flag=wx.EXPAND | wx.ALL, border=4)
        main_sizer.Add(
            timing_sizer,
            flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            border=10,
        )

        # ============ File Filters & Gating ============
        filter_box = wx.StaticBox(scrolled, label="File Filters")
        filter_sizer = wx.StaticBoxSizer(filter_box, wx.VERTICAL)
        filter_grid = wx.FlexGridSizer(cols=2, vgap=6, hgap=5)
        filter_grid.AddGrowableCol(1, 1)

        lbl = wx.StaticText(
            scrolled,
            label="File extensions (comma-separated, blank=all):",
        )
        filter_grid.Add(lbl, flag=wx.ALIGN_CENTER_VERTICAL | wx.LEFT, border=10)
        self._ext_ctrl = wx.TextCtrl(scrolled, value=", ".join(cfg.file_extensions))
        self._ext_ctrl.SetName("File extensions")
        filter_grid.Add(self._ext_ctrl, flag=wx.EXPAND | wx.RIGHT, border=10)

        lbl = wx.StaticText(
            scrolled,
            label="Include patterns (comma-separated globs, blank=all):",
        )
        filter_grid.Add(lbl, flag=wx.ALIGN_CENTER_VERTICAL | wx.LEFT, border=10)
        self._include_ctrl = wx.TextCtrl(
            scrolled, value=", ".join(cfg.include_patterns)
        )
        self._include_ctrl.SetName("Include patterns")
        filter_grid.Add(self._include_ctrl, flag=wx.EXPAND | wx.RIGHT, border=10)

        # Hint
        filter_grid.AddSpacer(0)
        hint = wx.StaticText(scrolled, label="e.g.  ACB_*, *_stream_*.mp4")
        hint.SetForegroundColour(wx.Colour(110, 110, 110))
        filter_grid.Add(hint, flag=wx.LEFT | wx.RIGHT, border=10)

        lbl = wx.StaticText(scrolled, label="Exclude patterns (comma-separated globs):")
        filter_grid.Add(lbl, flag=wx.ALIGN_CENTER_VERTICAL | wx.LEFT, border=10)
        self._exclude_ctrl = wx.TextCtrl(
            scrolled, value=", ".join(cfg.exclude_patterns)
        )
        self._exclude_ctrl.SetName("Exclude patterns")
        filter_grid.Add(self._exclude_ctrl, flag=wx.EXPAND | wx.RIGHT, border=10)

        # Hint
        filter_grid.AddSpacer(0)
        hint = wx.StaticText(scrolled, label="e.g.  *.tmp, ~*, thumbs.db")
        hint.SetForegroundColour(wx.Colour(110, 110, 110))
        filter_grid.Add(hint, flag=wx.LEFT | wx.RIGHT, border=10)

        lbl = wx.StaticText(scrolled, label="Minimum file size (bytes, 0=none):")
        filter_grid.Add(lbl, flag=wx.ALIGN_CENTER_VERTICAL | wx.LEFT, border=10)
        self._min_size_spin = wx.SpinCtrl(
            scrolled, value=str(cfg.min_file_size), min=0, max=999999999, size=(140, -1)
        )
        self._min_size_spin.SetName("Minimum file size bytes")
        filter_grid.Add(self._min_size_spin, flag=wx.RIGHT, border=10)

        lbl = wx.StaticText(scrolled, label="Maximum file size (bytes, 0=none):")
        filter_grid.Add(lbl, flag=wx.ALIGN_CENTER_VERTICAL | wx.LEFT, border=10)
        self._max_size_spin = wx.SpinCtrl(
            scrolled, value=str(cfg.max_file_size), min=0, max=999999999, size=(140, -1)
        )
        self._max_size_spin.SetName("Maximum file size bytes")
        filter_grid.Add(self._max_size_spin, flag=wx.RIGHT, border=10)

        filter_sizer.Add(filter_grid, flag=wx.EXPAND | wx.ALL, border=4)
        main_sizer.Add(
            filter_sizer,
            flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            border=10,
        )

        # ============ Collision Protection ============
        col_box = wx.StaticBox(scrolled, label="Collision Protection")
        col_sizer = wx.StaticBoxSizer(col_box, wx.VERTICAL)
        col_grid = wx.FlexGridSizer(cols=2, vgap=6, hgap=5)
        col_grid.AddGrowableCol(1, 1)

        lbl = wx.StaticText(scrolled, label="When destination file exists:")
        col_grid.Add(lbl, flag=wx.ALIGN_CENTER_VERTICAL | wx.LEFT, border=10)
        collision_labels = list(_COLLISION_LABELS.values())
        current_label = _COLLISION_LABELS.get(
            cfg.collision_mode, _COLLISION_LABELS[COLLISION_RENAME]
        )
        self._collision_choice = wx.Choice(scrolled, choices=collision_labels)
        self._collision_choice.SetName("Collision mode")
        if current_label in collision_labels:
            idx = collision_labels.index(current_label)
        else:
            idx = 0
        self._collision_choice.SetSelection(idx)
        col_grid.Add(self._collision_choice, flag=wx.RIGHT, border=10)

        lbl = wx.StaticText(scrolled, label="Rename pattern:")
        col_grid.Add(lbl, flag=wx.ALIGN_CENTER_VERTICAL | wx.LEFT, border=10)
        self._rename_ctrl = wx.TextCtrl(scrolled, value=cfg.rename_pattern)
        self._rename_ctrl.SetName("Rename pattern")
        col_grid.Add(self._rename_ctrl, flag=wx.EXPAND | wx.RIGHT, border=10)

        # Help text spanning both columns
        col_grid.AddSpacer(0)
        help_lbl = wx.StaticText(scrolled, label=RENAME_PATTERN_HELP)
        help_lbl.Wrap(400)
        col_grid.Add(help_lbl, flag=wx.LEFT | wx.RIGHT, border=10)

        col_sizer.Add(col_grid, flag=wx.EXPAND | wx.ALL, border=4)
        main_sizer.Add(
            col_sizer,
            flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            border=10,
        )

        # ============ Verification & Retry ============
        ver_box = wx.StaticBox(scrolled, label="Copy Verification & Retry")
        ver_sizer = wx.StaticBoxSizer(ver_box, wx.VERTICAL)
        ver_grid = wx.FlexGridSizer(cols=2, vgap=6, hgap=5)
        ver_grid.AddGrowableCol(1, 1)

        self._verify_cb = wx.CheckBox(
            scrolled, label="Verify copies with SHA-256 checksum"
        )
        self._verify_cb.SetValue(cfg.verify_copies)
        self._verify_cb.SetName("Verify copies with SHA-256 checksum")
        ver_sizer.Add(self._verify_cb, flag=wx.LEFT | wx.TOP, border=10)

        lbl = wx.StaticText(scrolled, label="Retry count on failure:")
        ver_grid.Add(lbl, flag=wx.ALIGN_CENTER_VERTICAL | wx.LEFT, border=10)
        self._retry_spin = wx.SpinCtrl(
            scrolled, value=str(cfg.retry_count), min=0, max=10, size=(80, -1)
        )
        self._retry_spin.SetName("Retry count")
        ver_grid.Add(self._retry_spin, flag=wx.RIGHT, border=10)

        lbl = wx.StaticText(scrolled, label="Retry delay (seconds):")
        ver_grid.Add(lbl, flag=wx.ALIGN_CENTER_VERTICAL | wx.LEFT, border=10)
        self._retry_delay_spin = wx.SpinCtrl(
            scrolled, value=str(cfg.retry_delay), min=1, max=300, size=(80, -1)
        )
        self._retry_delay_spin.SetName("Retry delay seconds")
        ver_grid.Add(self._retry_delay_spin, flag=wx.RIGHT, border=10)

        ver_sizer.Add(ver_grid, flag=wx.EXPAND | wx.ALL, border=4)
        main_sizer.Add(
            ver_sizer,
            flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            border=10,
        )

        # ============ Notifications ============
        notif_box = wx.StaticBox(scrolled, label="Notifications")
        notif_sizer = wx.StaticBoxSizer(notif_box, wx.VERTICAL)

        self._sound_cb = wx.CheckBox(
            scrolled, label="Play system sound on copy failure"
        )
        self._sound_cb.SetValue(cfg.play_sound_on_error)
        self._sound_cb.SetName("Play system sound on copy failure")
        notif_sizer.Add(self._sound_cb, flag=wx.ALL, border=10)

        main_sizer.Add(
            notif_sizer,
            flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            border=10,
        )

        # ============ Global Hotkeys ============
        hk_box = wx.StaticBox(
            scrolled,
            label="Global Hotkeys  (click Record, then press your shortcut)",
        )
        hk_sizer = wx.StaticBoxSizer(hk_box, wx.VERTICAL)
        hk_grid = wx.FlexGridSizer(cols=2, vgap=6, hgap=5)
        hk_grid.AddGrowableCol(1, 1)

        self._hk_pause = HotkeyRecorder(
            scrolled, hk_grid, "Pause / Resume:", cfg.hotkey_pause_resume
        )
        self._hk_copy = HotkeyRecorder(
            scrolled, hk_grid, "Copy Now:", cfg.hotkey_copy_now
        )
        self._hk_status = HotkeyRecorder(
            scrolled, hk_grid, "Show Status:", cfg.hotkey_status
        )
        self._hk_settings = HotkeyRecorder(
            scrolled, hk_grid, "Show Settings:", cfg.hotkey_settings
        )
        self._hk_quit = HotkeyRecorder(
            scrolled, hk_grid, "Quit Application:", cfg.hotkey_quit
        )

        hk_sizer.Add(hk_grid, flag=wx.EXPAND | wx.ALL, border=4)
        main_sizer.Add(
            hk_sizer,
            flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            border=10,
        )

        # ============ Startup ============
        startup_box = wx.StaticBox(scrolled, label="Startup")
        startup_sizer = wx.StaticBoxSizer(startup_box, wx.VERTICAL)

        self._minimized_cb = wx.CheckBox(scrolled, label="Start minimized to tray")
        self._minimized_cb.SetValue(cfg.start_minimized)
        self._minimized_cb.SetName("Start minimized to tray")
        startup_sizer.Add(self._minimized_cb, flag=wx.LEFT | wx.TOP, border=10)

        self._startup_cb = wx.CheckBox(scrolled, label="Start at login")
        self._startup_cb.SetValue(cfg.start_with_windows)
        self._startup_cb.SetName("Start at login")
        startup_sizer.Add(self._startup_cb, flag=wx.LEFT | wx.BOTTOM, border=10)

        main_sizer.Add(
            startup_sizer,
            flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            border=10,
        )

        # ---- Buttons ----
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        save_btn = wx.Button(scrolled, label="Save")
        save_btn.Bind(wx.EVT_BUTTON, self._on_save)
        btn_sizer.Add(save_btn, flag=wx.RIGHT, border=8)

        cancel_btn = wx.Button(scrolled, label="Cancel")
        cancel_btn.Bind(wx.EVT_BUTTON, lambda e: self._on_close())
        btn_sizer.Add(cancel_btn)

        main_sizer.Add(
            btn_sizer, flag=wx.ALIGN_CENTER_HORIZONTAL | wx.TOP | wx.BOTTOM, border=12
        )

        scrolled.SetSizer(main_sizer)

        # Outer sizer for the dialog to hold the scrolled window
        dlg_sizer = wx.BoxSizer(wx.VERTICAL)
        dlg_sizer.Add(scrolled, proportion=1, flag=wx.EXPAND)
        self._win.SetSizer(dlg_sizer)

        self._win.Show()
        wx.CallAfter(self._win.Raise)

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self._on_close()
        else:
            event.Skip()

    # ---- browse helpers ----

    def _browse_source(self, event: wx.CommandEvent) -> None:
        dlg = wx.DirDialog(
            self._win,
            "Select Source Folder",
            defaultPath=self._source_ctrl.GetValue() or "",
        )
        if dlg.ShowModal() == wx.ID_OK:
            self._source_ctrl.SetValue(dlg.GetPath())
        dlg.Destroy()

    def _browse_dest(self, event: wx.CommandEvent) -> None:
        dlg = wx.DirDialog(
            self._win,
            "Select Destination Folder",
            defaultPath=self._dest_ctrl.GetValue() or "",
        )
        if dlg.ShowModal() == wx.ID_OK:
            self._dest_ctrl.SetValue(dlg.GetPath())
        dlg.Destroy()

    # ---- save / cancel ----

    def _on_save(self, event: wx.CommandEvent) -> None:
        source = self._source_ctrl.GetValue().strip()
        dest = self._dest_ctrl.GetValue().strip()

        if not source:
            wx.MessageBox(
                "Source folder is required.",
                "Validation Error",
                wx.OK | wx.ICON_ERROR,
                self._win,
            )
            return
        if not dest:
            wx.MessageBox(
                "Destination folder is required.",
                "Validation Error",
                wx.OK | wx.ICON_ERROR,
                self._win,
            )
            return
        if not os.path.isdir(source):
            wx.MessageBox(
                f"Source folder does not exist:\n{source}",
                "Validation Error",
                wx.OK | wx.ICON_ERROR,
                self._win,
            )
            return

        interval = self._interval_spin.GetValue()
        stable = self._stable_spin.GetValue()
        min_size = self._min_size_spin.GetValue()
        max_size = self._max_size_spin.GetValue()
        retry_count = self._retry_spin.GetValue()
        retry_delay = self._retry_delay_spin.GetValue()

        # Check for duplicate hotkey assignments
        hotkeys: dict[str, str] = {}
        hk_fields = {
            "Pause / Resume": self._hk_pause.GetValue().strip(),
            "Copy Now": self._hk_copy.GetValue().strip(),
            "Show Status": self._hk_status.GetValue().strip(),
            "Show Settings": self._hk_settings.GetValue().strip(),
            "Quit": self._hk_quit.GetValue().strip(),
        }
        for label, key in hk_fields.items():
            if not key or key == "Press keys\u2026":
                continue
            if key in hotkeys:
                wx.MessageBox(
                    f'Duplicate hotkey "{key}" assigned to both '
                    f'"{hotkeys[key]}" and "{label}".',
                    "Validation Error",
                    wx.OK | wx.ICON_ERROR,
                    self._win,
                )
                return
            hotkeys[key] = label

        # Resolve collision mode from label back to value
        collision_sel = self._collision_choice.GetSelection()
        if collision_sel != wx.NOT_FOUND:
            collision_mode = _COLLISION_VALUES[collision_sel]
        else:
            collision_mode = COLLISION_RENAME

        cfg = self._app.config
        cfg.source_folder = source
        cfg.destination_folder = dest
        cfg.check_interval = interval
        cfg.stable_time = stable
        cfg.file_extensions = [
            e.strip() for e in self._ext_ctrl.GetValue().split(",") if e.strip()
        ]
        cfg.include_patterns = [
            p.strip() for p in self._include_ctrl.GetValue().split(",") if p.strip()
        ]
        cfg.exclude_patterns = [
            p.strip() for p in self._exclude_ctrl.GetValue().split(",") if p.strip()
        ]
        cfg.copy_subdirectories = self._subdirs_cb.GetValue()
        cfg.start_minimized = self._minimized_cb.GetValue()
        cfg.start_with_windows = self._startup_cb.GetValue()
        cfg.collision_mode = collision_mode
        cfg.rename_pattern = (
            self._rename_ctrl.GetValue().strip()
            or DEFAULT_RENAME_PATTERN
        )
        cfg.verify_copies = self._verify_cb.GetValue()
        cfg.min_file_size = min_size
        cfg.max_file_size = max_size
        cfg.retry_count = retry_count
        cfg.retry_delay = retry_delay
        cfg.play_sound_on_error = self._sound_cb.GetValue()
        # Hotkeys — normalise "Press keys..." placeholder to empty
        cfg.hotkey_pause_resume = (
            "" if self._hk_pause.GetValue() == "Press keys\u2026"
            else self._hk_pause.GetValue()
        )
        cfg.hotkey_copy_now = (
            "" if self._hk_copy.GetValue() == "Press keys\u2026"
            else self._hk_copy.GetValue()
        )
        cfg.hotkey_status = (
            "" if self._hk_status.GetValue() == "Press keys\u2026"
            else self._hk_status.GetValue()
        )
        cfg.hotkey_settings = (
            "" if self._hk_settings.GetValue() == "Press keys\u2026"
            else self._hk_settings.GetValue()
        )
        cfg.hotkey_quit = (
            "" if self._hk_quit.GetValue() == "Press keys\u2026"
            else self._hk_quit.GetValue()
        )
        cfg.save()

        # Restart the watcher with new settings
        self._app.restart_sync()

        wx.MessageBox(
            "Settings saved successfully.",
            "Settings Saved",
            wx.OK | wx.ICON_INFORMATION,
            self._win,
        )
        self._on_close()

    def _on_close_event(self, event: wx.CloseEvent) -> None:
        self._on_close()

    def _on_close(self) -> None:
        if self._win:
            self._win.Destroy()
            self._win = None


# ======================================================================
# Status window
# ======================================================================


class StatusWindow:
    """Accessible status window showing current sync state, stats, and copy history."""

    def __init__(self, app: "App"):
        """Create the status window (hidden until ``show`` is called)."""
        self._app = app
        self._win: wx.Frame | None = None
        self._status_label: wx.StaticText | None = None
        self._stats_label: wx.StaticText | None = None
        self._list_ctrl: wx.ListCtrl | None = None
        self._timer: wx.Timer | None = None
        self._sync_btn: wx.Button | None = None

    def show(self) -> None:
        """Show or focus the status window."""
        if self._win is not None:
            self._win.Raise()
            self._win.SetFocus()
            return
        self._build()

    def _build(self) -> None:
        self._win = wx.Frame(
            None,
            title="Stream Watcher \u2014 Status",
            size=(780, 580),
            style=wx.DEFAULT_FRAME_STYLE,
        )
        self._win.SetMinSize((600, 440))
        self._win.Bind(wx.EVT_CLOSE, self._on_close_event)
        self._win.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)

        panel = wx.Panel(self._win)
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # ---- Header ----
        header = wx.StaticText(panel, label="Sync Status")
        header_font = header.GetFont()
        header_font.SetPointSize(14)
        header_font.MakeBold()
        header.SetFont(header_font)
        main_sizer.Add(header, flag=wx.ALL, border=10)

        # ---- Status summary ----
        self._status_label = wx.StaticText(panel, label="Initializing\u2026")
        self._status_label.SetName("Sync status")
        main_sizer.Add(
            self._status_label,
            flag=wx.LEFT | wx.RIGHT | wx.BOTTOM,
            border=10,
        )

        self._stats_label = wx.StaticText(panel, label="")
        self._stats_label.SetName("Copy statistics")
        main_sizer.Add(
            self._stats_label,
            flag=wx.LEFT | wx.RIGHT | wx.BOTTOM,
            border=10,
        )

        # ---- Hotkey hint ----
        self._hint_label = wx.StaticText(panel, label="")
        self._hint_label.SetForegroundColour(wx.Colour(110, 110, 110))
        main_sizer.Add(self._hint_label, flag=wx.LEFT | wx.RIGHT | wx.BOTTOM, border=10)
        self._update_hint()

        # ---- Copy history label ----
        history_label = wx.StaticText(panel, label="Copy History:")
        main_sizer.Add(history_label, flag=wx.LEFT | wx.RIGHT, border=10)

        # ---- Copy history table ----
        self._list_ctrl = wx.ListCtrl(
            panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_SUNKEN
        )
        self._list_ctrl.SetName("Copy history")
        self._list_ctrl.InsertColumn(0, "Time", width=130)
        self._list_ctrl.InsertColumn(1, "Status", width=60)
        self._list_ctrl.InsertColumn(2, "Source File", width=200)
        self._list_ctrl.InsertColumn(3, "Destination", width=200)
        self._list_ctrl.InsertColumn(4, "Size", width=80)
        self._list_ctrl.InsertColumn(5, "Verified", width=65)

        main_sizer.Add(
            self._list_ctrl,
            proportion=1,
            flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            border=10,
        )

        # ---- Buttons ----
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self._sync_btn = wx.Button(panel, label="Pause Sync")
        self._sync_btn.Bind(wx.EVT_BUTTON, self._on_toggle_sync)
        btn_sizer.Add(self._sync_btn, flag=wx.RIGHT, border=8)

        copy_btn = wx.Button(panel, label="Copy Now")
        copy_btn.Bind(wx.EVT_BUTTON, self._on_copy_now)
        btn_sizer.Add(copy_btn, flag=wx.RIGHT, border=8)

        log_btn = wx.Button(panel, label="View Log")
        log_btn.Bind(wx.EVT_BUTTON, self._on_open_log)
        btn_sizer.Add(log_btn, flag=wx.RIGHT, border=8)

        settings_btn = wx.Button(panel, label="Settings")
        settings_btn.Bind(wx.EVT_BUTTON, lambda e: self._app.on_open_settings())
        btn_sizer.Add(settings_btn, flag=wx.RIGHT, border=8)

        close_btn = wx.Button(panel, label="Close")
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self._on_close())
        btn_sizer.Add(close_btn)

        main_sizer.Add(
            btn_sizer,
            flag=wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM,
            border=10,
        )

        panel.SetSizer(main_sizer)

        # Start periodic update timer
        self._timer = wx.Timer(self._win)
        self._win.Bind(wx.EVT_TIMER, self._on_timer, self._timer)
        self._timer.Start(2000)

        # Initial refresh
        self._refresh()

        self._win.Show()
        wx.CallAfter(self._win.Raise)

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self._on_close()
        else:
            event.Skip()

    # ---- periodic refresh ----

    def _on_timer(self, event: wx.TimerEvent) -> None:
        self._refresh()

    def _update_hint(self) -> None:
        """Build and display the hotkey hint line from current config."""
        cfg = self._app.config
        parts: list[str] = []
        if cfg.hotkey_pause_resume:
            parts.append(f"Pause/Resume = {cfg.hotkey_pause_resume}")
        if cfg.hotkey_copy_now:
            parts.append(f"Copy Now = {cfg.hotkey_copy_now}")
        if cfg.hotkey_status:
            parts.append(f"Status = {cfg.hotkey_status}")
        if cfg.hotkey_settings:
            parts.append(f"Settings = {cfg.hotkey_settings}")
        if cfg.hotkey_quit:
            parts.append(f"Quit = {cfg.hotkey_quit}")
        text = "Hotkeys:  " + "  |  ".join(parts) if parts else "No hotkeys configured."
        if self._hint_label:
            self._hint_label.SetLabel(text)

    def _refresh(self) -> None:
        if not self._win:
            return

        cfg = self._app.config
        enabled = cfg.sync_enabled
        configured = cfg.is_configured()

        # Status text and colour
        if not configured:
            status = (
                "Not configured \u2014 open Settings"
                " to set source and destination folders."
            )
            colour = wx.Colour(196, 0, 26)  # ERROR_FG
        elif enabled:
            status = "Sync is ACTIVE \u2014 watching for new files."
            colour = wx.Colour(10, 110, 10)  # SUCCESS_FG
        else:
            status = "Sync is PAUSED."
            colour = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT)

        if self._status_label:
            self._status_label.SetLabel(status)
            self._status_label.SetForegroundColour(colour)

        # Stats
        copier = self._app.copier
        watcher = self._app.watcher
        parts: list[str] = []
        if copier:
            s = copier.stats
            parts.append(f"Copied: {s.total_copied}")
            if s.total_verified:
                parts.append(f"Verified: {s.total_verified}")
            if s.total_failed:
                parts.append(f"Failed: {s.total_failed}")
            if s.total_skipped:
                parts.append(f"Skipped: {s.total_skipped}")
            if copier.active_copies:
                parts.append(f"In progress: {copier.active_copies}")
        if watcher:
            pending = watcher.pending_count
            if pending:
                parts.append(f"Stabilising: {pending}")

        if self._stats_label:
            self._stats_label.SetLabel(" | ".join(parts) if parts else "No stats yet.")

        # Sync button label
        if self._sync_btn:
            self._sync_btn.SetLabel("Pause Sync" if enabled else "Resume Sync")

        # History table
        self._update_history()

    def _update_history(self) -> None:
        copier = self._app.copier
        if not copier or not self._list_ctrl:
            return

        self._list_ctrl.DeleteAllItems()

        for rec in reversed(copier.stats.history[-200:]):
            if rec.skipped:
                st = "Skip"
            elif rec.success:
                st = "OK"
            else:
                st = "FAIL"

            src_name = os.path.basename(rec.source)
            dst_name = os.path.basename(rec.destination) if rec.destination else ""
            size_str = f"{rec.size_bytes:,}" if rec.size_bytes else ""
            ver = (
                "Yes"
                if rec.verified
                else ("N/A" if rec.skipped else ("No" if rec.success else ""))
            )

            idx = self._list_ctrl.InsertItem(
                self._list_ctrl.GetItemCount(),
                rec.timestamp_str,
            )
            self._list_ctrl.SetItem(idx, 1, st)
            self._list_ctrl.SetItem(idx, 2, src_name)
            self._list_ctrl.SetItem(idx, 3, dst_name)
            self._list_ctrl.SetItem(idx, 4, size_str)
            self._list_ctrl.SetItem(idx, 5, ver)

    # ---- actions ----

    def _on_toggle_sync(self, event: wx.CommandEvent) -> None:
        self._app.on_toggle_sync()
        self._refresh()

    def _on_copy_now(self, event: wx.CommandEvent) -> None:
        self._app.on_copy_now()

    def _on_open_log(self, event: wx.CommandEvent) -> None:
        """Open the log file in the default text editor."""
        log_path = get_log_path()
        if log_path.exists():
            open_file_in_default_app(log_path)
        else:
            wx.MessageBox(
                "No log file exists yet.",
                "Log File",
                wx.OK | wx.ICON_INFORMATION,
                self._win,
            )

    def _on_close_event(self, event: wx.CloseEvent) -> None:
        self._on_close()

    def _on_close(self) -> None:
        if self._timer:
            self._timer.Stop()
            self._timer = None
        if self._win:
            self._win.Destroy()
            self._win = None
