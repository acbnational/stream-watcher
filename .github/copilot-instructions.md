# Copilot Instructions — Stream Watcher

## Project Overview

Stream Watcher is a **cross-platform** (Windows, macOS, Linux) system-tray application that monitors a source folder for new archived streaming content and automatically copies stable files to a configured destination. Built for the **ACB (American Council of the Blind) Media team**.

Package name: `acb_sync`  
Entry point: `python -m acb_sync`  
Python version: **3.13+**

## Architecture

```
acb_sync/
├── __init__.py          # Package metadata (__version__, __app_name__)
├── __main__.py          # CLI entry point (GUI vs service mode)
├── app.py               # Main controller — ties all modules together
├── config.py            # JSON config manager (DEFAULT_CONFIG, Config class)
├── copier.py            # Background threaded file copy engine
├── hotkeys.py           # Global keyboard shortcuts (keyboard library)
├── notify.py            # Screen reader / speech notifications
├── platform_utils.py    # Cross-platform OS detection & helpers
├── service.py           # Background service/daemon (Win/macOS/Linux)
├── tray.py              # System tray icon (pystray)
├── ui.py                # Accessible tkinter Settings & Status windows
└── watcher.py           # File system watcher (watchdog + stability tracking)
```

## Critical Rules

### Accessibility First
This application serves **blind and low-vision users**. Every change MUST:
- Add explicit text labels to ALL UI controls (no icon-only indicators)
- Maintain full keyboard navigation (Tab, Enter, Escape)
- Preserve WCAG 2.2 AA colour contrast (≥ 4.5:1 ratio)
- Keep screen reader compatibility (accessible_output2 on Windows, `say` on macOS)
- Use the accessible colour palette defined in `ui.py` (`BG_COLOR`, `FG_COLOR`, etc.)
- Announce user actions via `notifier.speak()` from `notify.py`

### Cross-Platform Awareness
- **Never** use `os.startfile()` directly — use `platform_utils.open_file_in_default_app()`
- **Never** hardcode Windows paths (e.g. `%APPDATA%`) — use `platform_utils.get_config_dir()`
- **Never** hardcode font names — use `platform_utils.get_system_font()`
- **Never** use `winsound` directly — use `platform_utils.play_error_sound()`
- Guard Windows-only imports (`pywin32`, `accessible_output2`, `winsound`, `winreg`) behind `IS_WINDOWS` checks
- Use the flags `IS_WINDOWS`, `IS_MACOS`, `IS_LINUX` from `platform_utils`

### Configuration
- All user settings live in `config.py` → `DEFAULT_CONFIG` dict
- Every new setting needs: a `DEFAULT_CONFIG` entry, a `@property` accessor on `Config`, and a UI control in `ui.py`
- Config is stored as JSON at the platform-appropriate path (see `platform_utils.get_config_dir()`)
- Property names use snake_case; JSON keys match the dict keys

### Coding Conventions
- Type hints on all public function signatures
- Module-level `logger = logging.getLogger(__name__)`
- Docstrings on all public classes and functions
- Background work on daemon threads (`daemon=True`)
- Thread-safe access to shared state via `threading.Lock`
- UI updates always via `self._root.after(0, callback)` for thread safety

### File Copy Pipeline
The copy pipeline flows: **watcher → stability tracker → copier**
1. `watcher.py` detects new/modified files via watchdog
2. Files enter `_StabilityTracker` — must remain unchanged for `stable_time` seconds
3. Stable files are handed to `copier.py` which runs copies on background threads
4. Copier handles: size gating → collision resolution → shutil.copy2 → SHA-256 verification → retry on failure
5. `CopyRecord` results flow back to `app.py` via the `on_copy_complete` callback

### Hotkeys
- Five user-configurable global hotkey slots via `keyboard` library
- Hotkeys are captured via `HotkeyRecorder` press-to-record widget in `ui.py`
- Stored as `keyboard`-format strings (e.g. `ctrl+shift+f9`)
- On macOS, "command" replaces "ctrl" as the super modifier

### Testing Changes
- Run `python -m acb_sync` to launch the GUI and verify tray icon appears
- Run `python -m acb_sync --service` to test service/daemon mode
- Test with a screen reader (NVDA on Windows or VoiceOver on macOS) when changing UI

## Dependencies

| Package | Purpose | Platform |
| --- | --- | --- |
| watchdog | File system events | All |
| pystray | System tray icon | All |
| Pillow | Icon image generation | All |
| keyboard | Global hotkeys | All (macOS needs Accessibility perms) |
| pywin32 | Windows service | Windows only |
| accessible_output2 | Screen reader speech | Windows only |

## Code Quality

All code must pass the CI quality gate before merging. The gate runs **ruff** (lint + format) and **pyright** (type check).

### Local setup (one-time)
```bash
pip install -r requirements-dev.txt
pre-commit install
```

After this, every `git commit` automatically runs lint and format checks via pre-commit hooks.

### Manual checks
```bash
# Lint
python -m ruff check acb_sync/

# Auto-fix lint issues
python -m ruff check acb_sync/ --fix

# Format
python -m ruff format acb_sync/

# Type check
pyright acb_sync/
```

### Rules
- Line length limit: **88 characters** (ruff/black standard)
- All public functions, methods, and classes must have docstrings (pydocstyle D rules)
- Imports must be sorted (isort via ruff)
- No unused imports or variables
- Configuration is in `pyproject.toml` — do not add separate `.flake8`, `.isort.cfg`, etc.

## Common Tasks

### Adding a new config setting
1. Add key + default to `DEFAULT_CONFIG` in `config.py`
2. Add `@property` and `@setter` on `Config` class
3. Add UI control in `SettingsWindow._build()` in `ui.py`
4. Read the property in `app.py` where needed
5. Pass through to copier/watcher if applicable

### Adding a new hotkey slot
1. Add `hotkey_<name>` to `DEFAULT_CONFIG` and `Config` properties
2. Add slot to `GlobalHotkeys.__init__()` in `hotkeys.py`
3. Add `HotkeyRecorder` row in `SettingsWindow._build()` in `ui.py`
4. Wire callback in `App.__init__()` in `app.py`

### Adding platform-specific behaviour
1. Add a helper function in `platform_utils.py`
2. Import and call from the consuming module
3. Never scatter `sys.platform` checks across modules
