# Stream Watcher

Cross-platform automated file sync tool for the ACB Media team. Watches a source folder for new archived streaming content and copies stable files to a configured destination for attribution and policy compliance.

Works on **Windows**, **macOS**, and **Linux**.

## Features

- **Folder watching** — monitors a source folder for new files using OS-level file system events (watchdog)
- **Stability gate** — files must remain unchanged for a configurable duration before copying, ensuring archives are fully written
- **File size gating** — optional minimum and maximum file-size filters to skip tiny lock files or oversized dumps
- **Exclude patterns** — glob-based filename patterns (e.g. `*.tmp`, `._*`) to skip unwanted files
- **Collision protection** — three modes when a destination file already exists:
  - **Overwrite** — replace the existing file
  - **Rename** — auto-rename using a configurable token pattern
  - **Skip** — leave the existing file untouched
- **Rename tokens** — powerful naming pattern for collision renames:
  `{name}`, `{ext}`, `{n}` (counter), `{date}`, `{time}`, `{datetime}`, `{ts}` (Unix timestamp)
- **Copy verification** — optional SHA-256 checksum comparison between source and destination after every copy
- **Retry on failure** — configurable retry count and delay for failed copies
- **Copy Now** — trigger an immediate sweep-and-copy of all pending stable files via menu, hotkey, or status window
- **Background copying** — copies run in background threads; the UI stays responsive
- **System tray** — lives in the system tray with dynamic status, copy counts, and quick access to all controls
- **Status window** — shows sync state, copy/failure/skip/verified counts, and a scrollable history table with timestamps
- **Pause / Resume** — toggle sync on and off without closing the app
- **Global hotkeys** — five system-wide keyboard shortcuts (pause/resume, copy now, status, settings, quit) — all user-configurable via a press-to-record widget
- **Screen reader notifications** — spoken alerts via accessible_output2 (Windows: JAWS / NVDA / Narrator) or the `say` command (macOS: VoiceOver-compatible)
- **Error sound** — optional system alert sound on copy failures
- **Log rotation** — automatic rotating log files with configurable size and backup count
- **Start at login** — optional auto-start via the Windows registry, macOS LaunchAgent, or Linux XDG autostart
- **Background service / daemon** — headless mode via Windows service (pywin32), macOS launchd agent, or Linux foreground daemon
- **Accessible** — fully keyboard navigable, screen-reader friendly, WCAG 2.2 AA compliant colours (≥ 4.5:1)

## Requirements

| Platform | Minimum Version |
| --- | --- |
| **Python** | 3.13+ |
| **Windows** | 10 / 11 |
| **macOS** | 12 Monterey+ |
| **Linux** | Any modern distro with Python 3.13 and tkinter |

### Platform-specific notes

- **Windows** — install the optional `[windows]` extras for full service and screen-reader support:
  `pip install -e ".[windows]"` or `pip install pywin32 accessible_output2`
- **macOS** — the `keyboard` library requires **Accessibility** permissions.
  Go to *System Settings → Privacy & Security → Accessibility* and add your terminal or Python executable.
  Speech notifications use the built-in `say` command (VoiceOver-compatible).
- **Linux** — `tkinter` must be available (e.g. `sudo apt install python3-tk`).
  Global hotkeys via `keyboard` require `sudo` or appropriate `uinput` permissions.

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Run the application

```bash
python -m acb_sync
```

On first launch, the Settings window opens automatically so you can configure:

| Setting | Description |
| --- | --- |
| **Source folder** | The folder to watch for new files |
| **Destination folder** | Where to copy files (can be a different drive, network path, etc.) |
| **Check interval** | How often the stability tracker polls files (default: 30 s) |
| **Stable time** | How long a file must remain unchanged before it is copied (default: 60 s) |
| **File extensions** | Comma-separated list of extensions to watch (blank = all files) |
| **Exclude patterns** | Comma-separated glob patterns to skip (e.g. `*.tmp, ._*`) |
| **Min file size** | Minimum file size in bytes to copy (0 = no minimum) |
| **Max file size** | Maximum file size in bytes to copy (0 = no maximum) |
| **Collision mode** | What to do when a file already exists: **Overwrite**, **Rename**, or **Skip** |
| **Rename pattern** | Token-based pattern for collision renames (see below) |
| **Verify copies** | SHA-256 checksum verification after each copy |
| **Retry count** | Number of retry attempts for failed copies (default: 2) |
| **Retry delay** | Seconds to wait between retry attempts (default: 5) |
| **Include subdirectories** | Whether to watch and replicate sub-folder structure |
| **Start minimized** | Whether the app starts minimized to the system tray |
| **Start at login** | Register the app to start automatically at login |
| **Enable notifications** | Spoken screen-reader or speech alerts |
| **Play sound on error** | System alert sound when a copy fails |

### 3. Use the system tray

Right-click the tray icon for:

- **Stream Watcher — Status** — shows current state and copy counts (informational)
- **Status Window** — see full history table and statistics
- **Settings** — change configuration
- **Pause Sync / Resume Sync** — toggle watching on/off
- **Copy All Now** — immediately copy all pending stable files
- **Quit** — exit the application

The tray icon colour indicates status:

- 🟢 **Green** — sync is active
- ⚫ **Grey** — sync is paused
- 🔴 **Red** — not configured or error

## Collision Protection & Rename Tokens

When the destination already contains a file with the same name, the **collision mode** setting controls behaviour. In **Rename** mode, a new filename is generated using the **rename pattern** with these tokens:

| Token | Expands to | Example |
| --- | --- | --- |
| `{name}` | Original filename (no extension) | `recording` |
| `{ext}` | Original extension (no dot) | `mp4` |
| `{n}` | Auto-incrementing counter | `1`, `2`, `3`… |
| `{date}` | Current date | `2025-01-15` |
| `{time}` | Current time | `14-30-05` |
| `{datetime}` | Date and time | `20250115_143005` |
| `{ts}` | Unix timestamp | `1736956205` |

**Default pattern:** `{name}_{n}.{ext}` → `recording_1.mp4`, `recording_2.mp4`, …

**Other examples:**

- `{name}_{datetime}.{ext}` → `recording_20250115_143005.mp4`
- `{name}_copy{n}_{date}.{ext}` → `recording_copy1_2025-01-15.mp4`

## Copy Verification

When **Verify copies** is enabled, after each file is copied the tool computes the SHA-256 checksum of both the source and destination files. If the checksums do not match the copy is flagged as failed and logged. The status window shows a ✓ or ✗ in the Verified column for each entry.

## Global Hotkeys

Five system-wide keyboard shortcuts work even when the app is minimized or in the background. All are configurable via a **press-to-record** widget in Settings:

| Default Shortcut | Action |
| --- | --- |
| **Ctrl+Shift+F9** | Pause / Resume sync |
| **Ctrl+Shift+F10** | Copy All Now |
| **Ctrl+Shift+F11** | Open Status Window |
| **Ctrl+Shift+F12** | Open Settings |
| *(unset)* | Quit application |

> **macOS:** Use **Cmd** in place of **Ctrl** for modifier keys. The recorder widget adapts automatically.

## Screen Reader & Speech Support

Every user-initiated action (pause, resume, copy, settings saved) triggers a spoken notification:

### Windows

Uses **accessible_output2** which works with:

- **JAWS** (Freedom Scientific)
- **NVDA** (NV Access)
- **Windows Narrator** (built-in)

If no screen reader is running the notifications are silently discarded.

### macOS

Uses the built-in **`say`** command for speech synthesis. Works with VoiceOver and is audible even without a screen reader running.

### Linux

Speech notifications are not currently supported. Enable **Play sound on error** for audible feedback (where available).

## Keyboard Navigation

| Key | Action |
| --- | --- |
| **Tab** | Move between controls |
| **Enter** | Activate buttons |
| **Escape** | Close current window |
| **Alt+F4** / **Cmd+Q** | Close window |
| Global hotkeys | See table above (configurable in Settings) |

All controls have explicit text labels that screen readers will announce.

## Background Service / Daemon

Running a headless service lets sync run without the GUI.

### Windows — Windows Service

```bash
# Install the service (as Administrator)
python -m acb_sync.service install

# Start / stop / remove
python -m acb_sync.service start
python -m acb_sync.service stop
python -m acb_sync.service remove
```

Or run `install_service.bat` **as Administrator**.

### macOS — launchd Agent

```bash
# Create the LaunchAgent plist
python -m acb_sync.service install

# Load / unload the agent
python -m acb_sync.service start
python -m acb_sync.service stop

# Remove the plist
python -m acb_sync.service remove

# Or run in the foreground
python -m acb_sync.service run
```

The plist is installed to `~/Library/LaunchAgents/com.acbmedia.streamwatcher.plist`.

### Linux — Foreground Daemon

```bash
python -m acb_sync.service start
# Runs until Ctrl-C or SIGTERM
```

> **Note:** Configure the application via the GUI (`python -m acb_sync`) *before* installing the service. The service reads the same config file but has no UI, hotkeys, or speech announcements.

## Configuration File

Settings are stored in JSON. The config and log paths are platform-dependent:

| Platform | Config directory |
| --- | --- |
| **Windows** | `%APPDATA%\StreamWatcher\` |
| **macOS** | `~/Library/Application Support/StreamWatcher/` |
| **Linux** | `~/.config/StreamWatcher/` (or `$XDG_CONFIG_HOME`) |

Within that directory:

- `config.json` — all settings
- `stream_watcher.log` — current log (auto-rotated)

## Architecture

```text
acb_sync/
├── __init__.py          App metadata
├── __main__.py          Entry point
├── app.py               Main controller (ties everything together)
├── config.py            JSON configuration manager
├── copier.py            Background file copy engine with retry, collision & verification
├── hotkeys.py           Global keyboard shortcuts (keyboard library)
├── notify.py            Screen reader / speech notifications (cross-platform)
├── platform_utils.py    OS detection, paths, fonts, sounds, autostart helpers
├── service.py           Background service / daemon (Windows, macOS, Linux)
├── tray.py              System tray icon with status display (pystray)
├── ui.py                Accessible tkinter settings & status windows
└── watcher.py           File system watcher (watchdog + stability tracking)
```

## Accessibility Notes

This application is designed for use by the ACB (American Council of the Blind) Media team:

- All UI controls have explicit, descriptive labels
- Full keyboard navigation via Tab, Enter, and Escape
- Five global hotkeys — all user-configurable with a press-to-record widget
- Spoken alerts on every user action (accessible_output2 on Windows, `say` on macOS)
- High-contrast colour palette meeting WCAG 2.2 AA (≥ 4.5:1 contrast ratio)
- Compatible with JAWS, NVDA, Windows Narrator, and macOS VoiceOver
- Platform-native fonts for comfortable reading on each OS
- tkinter is used for its broad cross-platform accessibility support
- Status updates use text labels (no icon-only indicators)
- File dialog boxes are standard OS dialogs (fully accessible)
- History table is a tkinter Treeview (keyboard navigable)

## License

Internal tool for ACB Media.
