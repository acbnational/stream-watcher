"""Accessible GUI for Stream Watcher — Settings and Status windows.

Built with tkinter for maximum screen-reader compatibility (JAWS / NVDA).
All controls have explicit labels, keyboard shortcuts, logical tab order,
and high-contrast colours that meet WCAG 2.2 AA contrast requirements.

Includes a press-to-record hotkey capture widget so users can define
any keyboard shortcut by pressing the keys rather than typing combo strings.
"""

import logging
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING, Any, cast
from collections.abc import Callable

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
    get_system_font,
    open_file_in_default_app,
)

if TYPE_CHECKING:
    from acb_sync.app import App

logger = logging.getLogger(__name__)

# ---- Detect platform font ----
_FONT = get_system_font()
_SUPER_MOD = get_super_modifier_label()  # "command" on macOS, "win" elsewhere

# ---- Accessible colour palette (WCAG 2.2 AA contrast >= 4.5:1) ----
BG_COLOR = "#FFFFFF"
FG_COLOR = "#1A1A1A"
ACCENT = "#0058A3"
ERROR_FG = "#C4001A"
SUCCESS_FG = "#0A6E0A"
FIELD_BG = "#FFFFFF"
FIELD_FG = "#1A1A1A"
BUTTON_BG = "#0058A3"
BUTTON_FG = "#FFFFFF"
DISABLED_BG = "#E0E0E0"
DISABLED_FG = "#6E6E6E"
FOCUS_RING = "#005A9E"
RECORDING_BG = "#FFF3CD"  # pale yellow while recording a hotkey

# Human-readable collision mode labels
_COLLISION_LABELS = {
    COLLISION_RENAME: "Rename (add number)",
    COLLISION_SKIP: "Skip (do not copy)",
    COLLISION_OVERWRITE: "Overwrite existing",
}
_COLLISION_VALUES = list(_COLLISION_LABELS.keys())

# Modifier key names to normalise
_MODIFIER_NAMES = {
    "Control_L",
    "Control_R",
    "Shift_L",
    "Shift_R",
    "Alt_L",
    "Alt_R",
    "Win_L",
    "Win_R",
    "Meta_L",
    "Meta_R",
}
_MOD_MAP = {
    "Control_L": "ctrl",
    "Control_R": "ctrl",
    "Shift_L": "shift",
    "Shift_R": "shift",
    "Alt_L": "alt",
    "Alt_R": "alt",
    "Win_L": _SUPER_MOD,
    "Win_R": _SUPER_MOD,
    "Meta_L": _SUPER_MOD,
    "Meta_R": _SUPER_MOD,
}


def _apply_theme(root: tk.Tk | tk.Toplevel) -> None:
    """Apply high-contrast, accessible styling to the window and ttk widgets."""
    root.configure(bg=BG_COLOR)
    style = ttk.Style(root)
    style.theme_use("default")
    style.configure("TFrame", background=BG_COLOR)
    style.configure(
        "TLabel", background=BG_COLOR, foreground=FG_COLOR, font=(_FONT, 10)
    )
    style.configure(
        "TLabelframe", background=BG_COLOR, foreground=FG_COLOR, font=(_FONT, 10)
    )
    style.configure(
        "TLabelframe.Label",
        background=BG_COLOR,
        foreground=FG_COLOR,
        font=(_FONT, 10, "bold"),
    )
    style.configure(
        "Header.TLabel",
        background=BG_COLOR,
        foreground=FG_COLOR,
        font=(_FONT, 13, "bold"),
    )
    style.configure(
        "Status.TLabel", background=BG_COLOR, foreground=FG_COLOR, font=(_FONT, 10)
    )
    style.configure(
        "Success.TLabel",
        background=BG_COLOR,
        foreground=SUCCESS_FG,
        font=(_FONT, 10, "bold"),
    )
    style.configure(
        "Error.TLabel",
        background=BG_COLOR,
        foreground=ERROR_FG,
        font=(_FONT, 10, "bold"),
    )
    style.configure(
        "Hint.TLabel", background=BG_COLOR, foreground=DISABLED_FG, font=(_FONT, 9)
    )
    style.configure(
        "TButton",
        background=BUTTON_BG,
        foreground=BUTTON_FG,
        font=(_FONT, 10),
        padding=(12, 6),
    )
    style.map(
        "TButton",
        background=[("active", "#004080"), ("disabled", DISABLED_BG)],
        foreground=[("disabled", DISABLED_FG)],
    )
    style.configure(
        "TEntry", fieldbackground=FIELD_BG, foreground=FIELD_FG, font=(_FONT, 10)
    )
    style.configure(
        "TCheckbutton", background=BG_COLOR, foreground=FG_COLOR, font=(_FONT, 10)
    )
    style.configure(
        "TSpinbox", fieldbackground=FIELD_BG, foreground=FIELD_FG, font=(_FONT, 10)
    )
    style.configure(
        "TCombobox", fieldbackground=FIELD_BG, foreground=FIELD_FG, font=(_FONT, 10)
    )
    style.configure("Treeview", font=(_FONT, 10), rowheight=24)
    style.configure("Treeview.Heading", font=(_FONT, 10, "bold"))


def _make_label_entry_row(
    parent: tk.Misc,
    row: int,
    label_text: str,
    variable: tk.Variable,
    width: int = 50,
    browse: bool = False,
    browse_callback: Callable[..., Any] | None = None,
) -> ttk.Entry:
    """Create an accessible Label + Entry (+ optional Browse button) row."""
    label = ttk.Label(parent, text=label_text)
    label.grid(row=row, column=0, sticky="w", padx=(10, 5), pady=6)

    entry = ttk.Entry(parent, textvariable=variable, width=width)
    entry.grid(row=row, column=1, sticky="we", padx=5, pady=6)

    if browse:
        cb = browse_callback if browse_callback is not None else (lambda: None)
        btn = ttk.Button(parent, text="Browse\u2026", command=cb)
        btn.grid(row=row, column=2, sticky="w", padx=(5, 10), pady=6)

    return entry


# ======================================================================
# Hotkey recorder widget
# ======================================================================


class HotkeyRecorder:
    """An accessible press-to-record control for capturing keyboard shortcuts.

    The user clicks "Record" (or presses Enter on it), then presses their
    desired key combination.  The captured combo is written into the linked
    StringVar in ``keyboard`` library format (e.g. ``ctrl+shift+f9``).

    A "Clear" button removes any assigned hotkey.
    """

    def __init__(
        self,
        parent: tk.Misc,
        row: int,
        label_text: str,
        variable: tk.StringVar,
    ):
        """Create a hotkey recorder row in *parent* at *row*."""
        self._var = variable
        self._recording = False
        self._pressed_mods: set[str] = set()
        self._pressed_key: str = ""

        ttk.Label(parent, text=label_text).grid(
            row=row, column=0, sticky="w", padx=(10, 5), pady=6
        )

        # Display of current value
        self._display = ttk.Entry(
            parent, textvariable=variable, width=22, state="readonly"
        )
        self._display.grid(row=row, column=1, sticky="w", padx=5, pady=6)

        btn_frame = ttk.Frame(parent)
        btn_frame.grid(row=row, column=2, sticky="w", padx=(5, 10), pady=6)

        self._rec_btn = ttk.Button(
            btn_frame, text="Record", command=self._toggle_record, width=8
        )
        self._rec_btn.pack(side="left", padx=(0, 4))

        self._clr_btn = ttk.Button(
            btn_frame, text="Clear", command=self._clear, width=7
        )
        self._clr_btn.pack(side="left")

    def _toggle_record(self) -> None:
        if self._recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self) -> None:
        self._recording = True
        self._pressed_mods.clear()
        self._pressed_key = ""
        self._rec_btn.configure(text="Stop")
        self._display.configure(state="normal")
        self._var.set("Press keys\u2026")
        self._display.configure(state="readonly")
        # Bind to the toplevel window to capture keys even if entry not focused
        top = self._display.winfo_toplevel()
        top.bind("<KeyPress>", self._on_key_press)
        top.bind("<KeyRelease>", self._on_key_release)

    def _stop_recording(self) -> None:
        self._recording = False
        self._rec_btn.configure(text="Record")
        top = self._display.winfo_toplevel()
        top.unbind("<KeyPress>")
        top.unbind("<KeyRelease>")
        # Build the combo string
        combo = self._build_combo()
        self._display.configure(state="normal")
        self._var.set(combo)
        self._display.configure(state="readonly")

    def _clear(self) -> None:
        if self._recording:
            self._stop_recording()
        self._display.configure(state="normal")
        self._var.set("")
        self._display.configure(state="readonly")

    def _on_key_press(self, event: tk.Event) -> str:
        keysym = event.keysym
        if keysym in _MODIFIER_NAMES:
            self._pressed_mods.add(_MOD_MAP[keysym])
        elif keysym == "Escape":
            # Cancel recording
            self._display.configure(state="normal")
            self._var.set("")
            self._display.configure(state="readonly")
            self._stop_recording()
        else:
            self._pressed_key = keysym.lower()
            # Auto-stop once a non-modifier key is captured
            self._stop_recording()
        return "break"

    def _on_key_release(self, event: tk.Event) -> str:
        return "break"

    def _build_combo(self) -> str:
        parts: list[str] = []
        # Deterministic modifier order
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
        self._win: tk.Misc | None = None

    def show(self) -> None:
        """Show or focus the settings window."""
        if self._win is not None and self._win.winfo_exists():
            self._win.lift()
            self._win.focus_force()
            return
        self._build()

    def _build(self) -> None:
        cfg = self._app.config

        self._win = tk.Toplevel()
        self._win.title("Stream Watcher \u2014 Settings")
        self._win.geometry("720x780")
        self._win.minsize(620, 680)
        self._win.resizable(True, True)
        _apply_theme(self._win)

        self._win.grab_set()
        self._win.protocol("WM_DELETE_WINDOW", self._on_close)
        self._win.bind("<Escape>", lambda e: self._on_close())

        # Scrollable canvas for all settings
        canvas = tk.Canvas(self._win, bg=BG_COLOR, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self._win, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        main = ttk.Frame(canvas, padding=10)
        canvas.create_window((0, 0), window=main, anchor="nw")
        main.columnconfigure(1, weight=1)

        def _on_frame_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))

        main.bind("<Configure>", _on_frame_configure)

        # Allow mouse-wheel scrolling
        def _on_mousewheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        row = 0

        # ---- Header ----
        ttk.Label(main, text="Settings", style="Header.TLabel").grid(
            row=row, column=0, columnspan=3, sticky="w", padx=10, pady=(5, 12)
        )
        row += 1

        # ============ Folders ============
        folder_frame = ttk.LabelFrame(main, text="Folders", padding=8)
        folder_frame.grid(
            row=row, column=0, columnspan=3, sticky="we", padx=10, pady=(0, 8)
        )
        folder_frame.columnconfigure(1, weight=1)
        row += 1

        self._source_var = tk.StringVar(value=cfg.source_folder)
        _make_label_entry_row(
            folder_frame,
            0,
            "Source folder:",
            self._source_var,
            browse=True,
            browse_callback=self._browse_source,
        )

        self._dest_var = tk.StringVar(value=cfg.destination_folder)
        _make_label_entry_row(
            folder_frame,
            1,
            "Destination folder:",
            self._dest_var,
            browse=True,
            browse_callback=self._browse_dest,
        )

        self._subdirs_var = tk.BooleanVar(value=cfg.copy_subdirectories)
        ttk.Checkbutton(
            folder_frame, text="Include subdirectories", variable=self._subdirs_var
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=10, pady=4)

        # ============ Timing ============
        timing_frame = ttk.LabelFrame(main, text="Timing", padding=8)
        timing_frame.grid(
            row=row, column=0, columnspan=3, sticky="we", padx=10, pady=(0, 8)
        )
        timing_frame.columnconfigure(1, weight=1)
        row += 1

        ttk.Label(timing_frame, text="Check interval (seconds):").grid(
            row=0, column=0, sticky="w", padx=(10, 5), pady=6
        )
        self._interval_var = tk.StringVar(value=str(cfg.check_interval))
        ttk.Spinbox(
            timing_frame, from_=5, to=3600, textvariable=self._interval_var, width=8
        ).grid(row=0, column=1, sticky="w", padx=5, pady=6)

        ttk.Label(timing_frame, text="Stable time before copy (seconds):").grid(
            row=1, column=0, sticky="w", padx=(10, 5), pady=6
        )
        self._stable_var = tk.StringVar(value=str(cfg.stable_time))
        ttk.Spinbox(
            timing_frame, from_=0, to=3600, textvariable=self._stable_var, width=8
        ).grid(row=1, column=1, sticky="w", padx=5, pady=6)

        # ============ File Filters & Gating ============
        filter_frame = ttk.LabelFrame(main, text="File Filters", padding=8)
        filter_frame.grid(
            row=row, column=0, columnspan=3, sticky="we", padx=10, pady=(0, 8)
        )
        filter_frame.columnconfigure(1, weight=1)
        row += 1

        ttk.Label(
            filter_frame, text="File extensions (comma-separated, blank=all):"
        ).grid(row=0, column=0, sticky="w", padx=(10, 5), pady=6)
        self._ext_var = tk.StringVar(value=", ".join(cfg.file_extensions))
        ttk.Entry(filter_frame, textvariable=self._ext_var, width=30).grid(
            row=0, column=1, sticky="we", padx=5, pady=6
        )

        ttk.Label(
            filter_frame, text="Include patterns (comma-separated globs, blank=all):"
        ).grid(row=1, column=0, sticky="w", padx=(10, 5), pady=6)
        self._include_var = tk.StringVar(value=", ".join(cfg.include_patterns))
        ttk.Entry(filter_frame, textvariable=self._include_var, width=30).grid(
            row=1, column=1, sticky="we", padx=5, pady=6
        )
        ttk.Label(
            filter_frame,
            text="e.g.  ACB_*, *_stream_*.mp4",
            style="Hint.TLabel",
        ).grid(row=2, column=1, sticky="w", padx=5, pady=(0, 4))

        ttk.Label(filter_frame, text="Exclude patterns (comma-separated globs):").grid(
            row=3, column=0, sticky="w", padx=(10, 5), pady=6
        )
        self._exclude_var = tk.StringVar(value=", ".join(cfg.exclude_patterns))
        ttk.Entry(filter_frame, textvariable=self._exclude_var, width=30).grid(
            row=3, column=1, sticky="we", padx=5, pady=6
        )
        ttk.Label(
            filter_frame, text="e.g.  *.tmp, ~*, thumbs.db", style="Hint.TLabel"
        ).grid(row=4, column=1, sticky="w", padx=5, pady=(0, 4))

        ttk.Label(filter_frame, text="Minimum file size (bytes, 0=none):").grid(
            row=5, column=0, sticky="w", padx=(10, 5), pady=6
        )
        self._min_size_var = tk.StringVar(value=str(cfg.min_file_size))
        ttk.Spinbox(
            filter_frame,
            from_=0,
            to=999999999999,
            textvariable=self._min_size_var,
            width=14,
        ).grid(row=5, column=1, sticky="w", padx=5, pady=6)

        ttk.Label(filter_frame, text="Maximum file size (bytes, 0=none):").grid(
            row=6, column=0, sticky="w", padx=(10, 5), pady=6
        )
        self._max_size_var = tk.StringVar(value=str(cfg.max_file_size))
        ttk.Spinbox(
            filter_frame,
            from_=0,
            to=999999999999,
            textvariable=self._max_size_var,
            width=14,
        ).grid(row=6, column=1, sticky="w", padx=5, pady=6)

        # ============ Collision Protection ============
        col_frame = ttk.LabelFrame(main, text="Collision Protection", padding=8)
        col_frame.grid(
            row=row, column=0, columnspan=3, sticky="we", padx=10, pady=(0, 8)
        )
        col_frame.columnconfigure(1, weight=1)
        row += 1

        ttk.Label(col_frame, text="When destination file exists:").grid(
            row=0, column=0, sticky="w", padx=(10, 5), pady=6
        )
        current_label = _COLLISION_LABELS.get(
            cfg.collision_mode, _COLLISION_LABELS[COLLISION_RENAME]
        )
        self._collision_var = tk.StringVar(value=current_label)
        combo = ttk.Combobox(
            col_frame,
            textvariable=self._collision_var,
            values=list(_COLLISION_LABELS.values()),
            state="readonly",
            width=24,
        )
        combo.grid(row=0, column=1, sticky="w", padx=5, pady=6)

        ttk.Label(col_frame, text="Rename pattern:").grid(
            row=1, column=0, sticky="w", padx=(10, 5), pady=6
        )
        self._rename_var = tk.StringVar(value=cfg.rename_pattern)
        ttk.Entry(col_frame, textvariable=self._rename_var, width=30).grid(
            row=1, column=1, sticky="we", padx=5, pady=6
        )
        ttk.Label(col_frame, text=RENAME_PATTERN_HELP, wraplength=400).grid(
            row=2, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 4)
        )

        # ============ Verification & Retry ============
        ver_frame = ttk.LabelFrame(main, text="Copy Verification & Retry", padding=8)
        ver_frame.grid(
            row=row, column=0, columnspan=3, sticky="we", padx=10, pady=(0, 8)
        )
        ver_frame.columnconfigure(1, weight=1)
        row += 1

        self._verify_var = tk.BooleanVar(value=cfg.verify_copies)
        ttk.Checkbutton(
            ver_frame,
            text="Verify copies with SHA-256 checksum",
            variable=self._verify_var,
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=10, pady=4)

        ttk.Label(ver_frame, text="Retry count on failure:").grid(
            row=1, column=0, sticky="w", padx=(10, 5), pady=6
        )
        self._retry_var = tk.StringVar(value=str(cfg.retry_count))
        ttk.Spinbox(
            ver_frame, from_=0, to=10, textvariable=self._retry_var, width=6
        ).grid(row=1, column=1, sticky="w", padx=5, pady=6)

        ttk.Label(ver_frame, text="Retry delay (seconds):").grid(
            row=2, column=0, sticky="w", padx=(10, 5), pady=6
        )
        self._retry_delay_var = tk.StringVar(value=str(cfg.retry_delay))
        ttk.Spinbox(
            ver_frame, from_=1, to=300, textvariable=self._retry_delay_var, width=6
        ).grid(row=2, column=1, sticky="w", padx=5, pady=6)

        # ============ Notifications ============
        notif_frame = ttk.LabelFrame(main, text="Notifications", padding=8)
        notif_frame.grid(
            row=row, column=0, columnspan=3, sticky="we", padx=10, pady=(0, 8)
        )
        notif_frame.columnconfigure(1, weight=1)
        row += 1

        self._sound_var = tk.BooleanVar(value=cfg.play_sound_on_error)
        ttk.Checkbutton(
            notif_frame,
            text="Play system sound on copy failure",
            variable=self._sound_var,
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=10, pady=4)

        # ============ Global Hotkeys ============
        hk_frame = ttk.LabelFrame(
            main,
            text="Global Hotkeys  (click Record, then press your shortcut)",
            padding=8,
        )
        hk_frame.grid(
            row=row, column=0, columnspan=3, sticky="we", padx=10, pady=(0, 8)
        )
        hk_frame.columnconfigure(1, weight=1)
        row += 1

        self._hk_pause_var = tk.StringVar(value=cfg.hotkey_pause_resume)
        HotkeyRecorder(hk_frame, 0, "Pause / Resume:", self._hk_pause_var)

        self._hk_copy_var = tk.StringVar(value=cfg.hotkey_copy_now)
        HotkeyRecorder(hk_frame, 1, "Copy Now:", self._hk_copy_var)

        self._hk_status_var = tk.StringVar(value=cfg.hotkey_status)
        HotkeyRecorder(hk_frame, 2, "Show Status:", self._hk_status_var)

        self._hk_settings_var = tk.StringVar(value=cfg.hotkey_settings)
        HotkeyRecorder(hk_frame, 3, "Show Settings:", self._hk_settings_var)

        self._hk_quit_var = tk.StringVar(value=cfg.hotkey_quit)
        HotkeyRecorder(hk_frame, 4, "Quit Application:", self._hk_quit_var)

        # ============ Startup ============
        startup_frame = ttk.LabelFrame(main, text="Startup", padding=8)
        startup_frame.grid(
            row=row, column=0, columnspan=3, sticky="we", padx=10, pady=(0, 8)
        )
        startup_frame.columnconfigure(1, weight=1)
        row += 1

        self._minimized_var = tk.BooleanVar(value=cfg.start_minimized)
        ttk.Checkbutton(
            startup_frame, text="Start minimized to tray", variable=self._minimized_var
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=10, pady=4)

        self._startup_var = tk.BooleanVar(value=cfg.start_with_windows)
        ttk.Checkbutton(
            startup_frame, text="Start at login", variable=self._startup_var
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=10, pady=4)

        # ---- Buttons ----
        btn_frame = ttk.Frame(main)
        btn_frame.grid(row=row, column=0, columnspan=3, pady=(12, 5))
        row += 1

        ttk.Button(btn_frame, text="Save", command=self._on_save).pack(
            side="left", padx=8
        )
        ttk.Button(btn_frame, text="Cancel", command=self._on_close).pack(
            side="left", padx=8
        )

        win = self._win
        if win:
            win.after(100, lambda w=win: w.focus_force())

    # ---- browse helpers ----

    def _browse_source(self) -> None:
        folder = filedialog.askdirectory(
            title="Select Source Folder",
            initialdir=self._source_var.get() or None,
        )
        if folder:
            self._source_var.set(folder)

    def _browse_dest(self) -> None:
        folder = filedialog.askdirectory(
            title="Select Destination Folder",
            initialdir=self._dest_var.get() or None,
        )
        if folder:
            self._dest_var.set(folder)

    # ---- save / cancel ----

    def _on_save(self) -> None:
        source = self._source_var.get().strip()
        dest = self._dest_var.get().strip()

        if not source:
            messagebox.showerror(
                "Validation Error",
                "Source folder is required.",
                parent=cast(tk.Misc, self._win),
            )
            return
        if not dest:
            messagebox.showerror(
                "Validation Error",
                "Destination folder is required.",
                parent=cast(tk.Misc, self._win),
            )
            return
        if not os.path.isdir(source):
            messagebox.showerror(
                "Validation Error",
                f"Source folder does not exist:\n{source}",
                parent=cast(tk.Misc, self._win),
            )
            return

        try:
            interval = int(self._interval_var.get())
            if interval < 5:
                raise ValueError
        except ValueError:
            messagebox.showerror(
                "Validation Error",
                "Check interval must be a number of at least 5 seconds.",
                parent=cast(tk.Misc, self._win),
            )
            return

        try:
            stable = int(self._stable_var.get())
            if stable < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror(
                "Validation Error",
                "Stable time must be a non-negative number.",
                parent=cast(tk.Misc, self._win),
            )
            return

        try:
            min_size = int(self._min_size_var.get())
            max_size = int(self._max_size_var.get())
        except ValueError:
            messagebox.showerror(
                "Validation Error",
                "File size limits must be numbers.",
                parent=cast(tk.Misc, self._win),
            )
            return

        try:
            retry_count = int(self._retry_var.get())
            retry_delay = int(self._retry_delay_var.get())
        except ValueError:
            messagebox.showerror(
                "Validation Error",
                "Retry count and delay must be numbers.",
                parent=cast(tk.Misc, self._win),
            )
            return

        # Check for duplicate hotkey assignments
        hotkeys = {}
        hk_fields = {
            "Pause / Resume": self._hk_pause_var.get().strip(),
            "Copy Now": self._hk_copy_var.get().strip(),
            "Show Status": self._hk_status_var.get().strip(),
            "Show Settings": self._hk_settings_var.get().strip(),
            "Quit": self._hk_quit_var.get().strip(),
        }
        for label, key in hk_fields.items():
            if not key or key == "Press keys\u2026":
                continue
            if key in hotkeys:
                messagebox.showerror(
                    "Validation Error",
                    f'Duplicate hotkey "{key}" assigned to both '
                    f'"{hotkeys[key]}" and "{label}".',
                    parent=cast(tk.Misc, self._win),
                )
                return
            hotkeys[key] = label

        # Resolve collision mode from label back to value
        collision_label = self._collision_var.get()
        collision_mode = COLLISION_RENAME
        for key, label in _COLLISION_LABELS.items():
            if label == collision_label:
                collision_mode = key
                break

        cfg = self._app.config
        cfg.source_folder = source
        cfg.destination_folder = dest
        cfg.check_interval = interval
        cfg.stable_time = stable
        cfg.file_extensions = [
            e.strip() for e in self._ext_var.get().split(",") if e.strip()
        ]
        cfg.include_patterns = [
            p.strip() for p in self._include_var.get().split(",") if p.strip()
        ]
        cfg.exclude_patterns = [
            p.strip() for p in self._exclude_var.get().split(",") if p.strip()
        ]
        cfg.copy_subdirectories = self._subdirs_var.get()
        cfg.start_minimized = self._minimized_var.get()
        cfg.start_with_windows = self._startup_var.get()
        cfg.collision_mode = collision_mode
        cfg.rename_pattern = self._rename_var.get().strip() or DEFAULT_RENAME_PATTERN
        cfg.verify_copies = self._verify_var.get()
        cfg.min_file_size = min_size
        cfg.max_file_size = max_size
        cfg.retry_count = retry_count
        cfg.retry_delay = retry_delay
        cfg.play_sound_on_error = self._sound_var.get()
        # Hotkeys — normalise "Press keys…" placeholder to empty
        cfg.hotkey_pause_resume = (
            ""
            if self._hk_pause_var.get() == "Press keys\u2026"
            else self._hk_pause_var.get()
        )
        cfg.hotkey_copy_now = (
            ""
            if self._hk_copy_var.get() == "Press keys\u2026"
            else self._hk_copy_var.get()
        )
        cfg.hotkey_status = (
            ""
            if self._hk_status_var.get() == "Press keys\u2026"
            else self._hk_status_var.get()
        )
        cfg.hotkey_settings = (
            ""
            if self._hk_settings_var.get() == "Press keys\u2026"
            else self._hk_settings_var.get()
        )
        cfg.hotkey_quit = (
            ""
            if self._hk_quit_var.get() == "Press keys\u2026"
            else self._hk_quit_var.get()
        )
        cfg.save()

        # Restart the watcher with new settings
        self._app.restart_sync()

        messagebox.showinfo(
            "Settings Saved",
            "Settings saved successfully.",
            parent=cast(tk.Misc, self._win),
        )
        self._on_close()

    def _on_close(self) -> None:
        if self._win:
            # Unbind mousewheel to avoid errors after window closed
            try:
                canvas_widget = self._win.winfo_children()[1]  # canvas
                canvas_widget.unbind_all("<MouseWheel>")
            except Exception:
                pass
            self._win.grab_release()
            self._win.destroy()
            self._win = None


# ======================================================================
# Status window
# ======================================================================


class StatusWindow:
    """Accessible status window showing current sync state, stats, and copy history."""

    def __init__(self, app: "App"):
        """Create the status window (hidden until ``show`` is called)."""
        self._app = app
        self._win: tk.Toplevel | None = None
        self._status_label: ttk.Label | None = None
        self._stats_label: ttk.Label | None = None
        self._detail_text: tk.Text | None = None
        self._tree: ttk.Treeview | None = None
        self._update_job: str | None = None

    def show(self) -> None:
        """Show or focus the status window."""
        if self._win is not None and self._win.winfo_exists():
            self._win.lift()
            self._win.focus_force()
            return
        self._build()

    def _build(self) -> None:
        self._win = tk.Toplevel()
        self._win.title("Stream Watcher \u2014 Status")
        self._win.geometry("780x580")
        self._win.minsize(600, 440)
        self._win.resizable(True, True)
        _apply_theme(self._win)

        self._win.protocol("WM_DELETE_WINDOW", self._on_close)
        self._win.bind("<Escape>", lambda e: self._on_close())

        main = ttk.Frame(self._win, padding=10)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(4, weight=1)

        # ---- Header ----
        ttk.Label(main, text="Sync Status", style="Header.TLabel").grid(
            row=0, column=0, sticky="w", padx=10, pady=(5, 8)
        )

        # ---- Status summary ----
        self._status_label = ttk.Label(
            main, text="Initializing\u2026", style="Status.TLabel"
        )
        self._status_label.grid(row=1, column=0, sticky="w", padx=10, pady=4)

        self._stats_label = ttk.Label(main, text="", style="Status.TLabel")
        self._stats_label.grid(row=2, column=0, sticky="w", padx=10, pady=4)

        # ---- Hotkey hint ----
        self._hint_label = ttk.Label(main, text="", style="Hint.TLabel")
        self._hint_label.grid(row=3, column=0, sticky="w", padx=10, pady=(2, 6))
        self._update_hint()

        # ---- Copy history table ----
        ttk.Label(main, text="Copy History:").grid(
            row=4, column=0, sticky="nw", padx=10, pady=(4, 2)
        )

        tree_frame = ttk.Frame(main)
        tree_frame.grid(row=5, column=0, sticky="nsew", padx=10, pady=(0, 6))
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        main.rowconfigure(5, weight=1)

        columns = ("time", "status", "source", "destination", "size", "verified")
        self._tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
            height=12,
        )
        self._tree.heading("time", text="Time")
        self._tree.heading("status", text="Status")
        self._tree.heading("source", text="Source File")
        self._tree.heading("destination", text="Destination")
        self._tree.heading("size", text="Size")
        self._tree.heading("verified", text="Verified")

        self._tree.column("time", width=130, minwidth=100)
        self._tree.column("status", width=60, minwidth=50)
        self._tree.column("source", width=200, minwidth=120)
        self._tree.column("destination", width=200, minwidth=120)
        self._tree.column("size", width=80, minwidth=60)
        self._tree.column("verified", width=65, minwidth=55)

        self._tree.grid(row=0, column=0, sticky="nsew")

        tree_scroll = ttk.Scrollbar(
            tree_frame, orient="vertical", command=self._tree.yview
        )
        tree_scroll.grid(row=0, column=1, sticky="ns")
        self._tree.configure(yscrollcommand=tree_scroll.set)

        # ---- Buttons ----
        btn_frame = ttk.Frame(main)
        btn_frame.grid(row=6, column=0, pady=(8, 5))

        self._sync_btn = ttk.Button(
            btn_frame, text="Pause Sync", command=self._toggle_sync
        )
        self._sync_btn.pack(side="left", padx=8)

        ttk.Button(btn_frame, text="Copy Now", command=self._copy_now).pack(
            side="left", padx=8
        )

        ttk.Button(btn_frame, text="View Log", command=self._open_log).pack(
            side="left", padx=8
        )

        ttk.Button(btn_frame, text="Settings", command=self._app.on_open_settings).pack(
            side="left", padx=8
        )

        ttk.Button(btn_frame, text="Close", command=self._on_close).pack(
            side="left", padx=8
        )

        # Start periodic update
        self._schedule_update()
        win = self._win
        if win:
            win.after(100, lambda w=win: w.focus_force())

    # ---- periodic refresh ----

    def _schedule_update(self) -> None:
        if self._win and self._win.winfo_exists():
            self._refresh()
            self._update_job = self._win.after(2000, self._schedule_update)

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
            self._hint_label.configure(text=text)

    def _refresh(self) -> None:
        if not self._win or not self._win.winfo_exists():
            return

        cfg = self._app.config
        enabled = cfg.sync_enabled
        configured = cfg.is_configured()

        # Status text
        if not configured:
            status = (
                "Not configured \u2014 open Settings"
                " to set source and destination folders."
            )
            style = "Error.TLabel"
        elif enabled:
            status = "Sync is ACTIVE \u2014 watching for new files."
            style = "Success.TLabel"
        else:
            status = "Sync is PAUSED."
            style = "Status.TLabel"

        if self._status_label:
            self._status_label.configure(text=status, style=style)

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
            self._stats_label.configure(
                text=" | ".join(parts) if parts else "No stats yet."
            )

        # Sync button label
        if self._sync_btn:
            self._sync_btn.configure(text="Pause Sync" if enabled else "Resume Sync")

        # History table
        self._update_history()

    def _update_history(self) -> None:
        copier = self._app.copier
        if not copier or not self._tree:
            return

        # Clear existing
        for item in self._tree.get_children():
            self._tree.delete(item)

        # Insert most recent first
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

            self._tree.insert(
                "",
                "end",
                values=(rec.timestamp_str, st, src_name, dst_name, size_str, ver),
            )

    # ---- actions ----

    def _toggle_sync(self) -> None:
        self._app.on_toggle_sync()
        self._refresh()

    def _copy_now(self) -> None:
        self._app.on_copy_now()

    def _open_log(self) -> None:
        """Open the log file in the default text editor."""
        log_path = get_log_path()
        if log_path.exists():
            open_file_in_default_app(log_path)
        else:
            messagebox.showinfo(
                "Log File", "No log file exists yet.", parent=cast(tk.Misc, self._win)
            )

    def _on_close(self) -> None:
        if self._update_job and self._win:
            self._win.after_cancel(self._update_job)
        if self._win:
            self._win.destroy()
            self._win = None
