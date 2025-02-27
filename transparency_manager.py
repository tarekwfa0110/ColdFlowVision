import os
import json
import logging
from tkinter import Tk, Toplevel, Label, Entry, Button, messagebox
from pynput import keyboard
import win32gui
import win32con
import win32api
import win32process
import psutil
from collections import defaultdict
import sys

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Default configuration
DEFAULT_CONFIG = {
    "ide_process_names": ["code.exe", "pycharm64.exe", "eclipse.exe", "sublime_text.exe", "atom.exe", "webstorm64.exe", "cursor.exe"],
    "browser_process_names": ["chrome.exe", "firefox.exe", "msedge.exe", "opera.exe", "brave.exe", "vivaldi.exe", "safari.exe", "iexplore.exe"],
    "current_preset": "dynamic",
    "presets": {
        "dynamic": {"active": 160, "background": 255},  # Active (top) transparent, background (behind) opaque
        "code-focused": {"ide": 255, "browser": 128},
        "documentation": {"ide": 192, "browser": 192},
        "presentation": {"ide": 255, "browser": 64}
    },
    "clickthrough_enabled": False,
    "hotkeys": {
        "toggle_transparency": "<ctrl>+<alt>+<f7>",
        "swap_active": "<alt>+<f1>",  # Changed to <Alt>+<F1>
        "reset_layout": "<ctrl>+<alt>+<f8>",
        "next_preset": "<ctrl>+<alt>+<f9>",
        "exit": "<ctrl>+<alt>+<f12>"
    },
    "performance_mode": True,
    "auto_start": False
}

# Helper function to get process name from window handle
def get_process_name(hwnd):
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        process = psutil.Process(pid)
        return process.name().lower()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None

class CodeFlowVision:
    def __init__(self):
        """Initialize the CodeFlowVision application."""
        self.config = self.load_config()
        self.ide_window = None
        self.browser_window = None
        self.active_window = None
        self.transparency_enabled = False
        self.hotkey_listener = None
        self.tray_hwnd = None
        self.root = Tk()
        self.root.withdraw()  # Hide the main Tkinter window
        self.detect_windows()
        if self.ide_window and self.browser_window:
            self.active_window = self.ide_window
        self.setup_hotkeys()
        self.create_tray_icon()
        config_path = os.path.join(os.getenv('APPDATA'), 'CodeFlowVision', 'config.json')
        if not os.path.exists(config_path):
            messagebox.showinfo(
                "Welcome to CodeFlowVision",
                "Press <Ctrl>+<Alt>+<F7> to toggle transparency\n"
                "<Alt>+<F1> to swap active window\n"
                "<Ctrl>+<Alt>+<F8> to reset layout\n"
                "<Ctrl>+<Alt>+<F9> to cycle presets\n"
                "<Ctrl>+<Alt>+<F12> to exit"
            )

    def load_config(self):
        """Load configuration from JSON file or use default."""
        config_path = os.path.join(os.getenv('APPDATA'), 'CodeFlowVision', 'config.json')
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    config = json.load(f)
                # Ensure all default keys are present
                for key in DEFAULT_CONFIG:
                    if key not in config:
                        config[key] = DEFAULT_CONFIG[key]
                return config
            except json.JSONDecodeError:
                logging.error("Invalid config file, using defaults")
        return DEFAULT_CONFIG.copy()

    def save_config(self):
        """Save current configuration to JSON file."""
        config_path = os.path.join(os.getenv('APPDATA'), 'CodeFlowVision', 'config.json')
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, 'w') as f:
            json.dump(self.config, f, indent=4)

    def detect_windows(self):
        """Detect IDE and browser windows."""
        def enum_windows_callback(hwnd, _):
            if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
                process_name = get_process_name(hwnd)
                if process_name in self.config["ide_process_names"] and self.ide_window is None:
                    self.ide_window = hwnd
                    logging.info(f"IDE detected: {process_name} (hwnd: {hwnd}, title: {win32gui.GetWindowText(hwnd)})")
                elif process_name in self.config["browser_process_names"] and self.browser_window is None:
                    self.browser_window = hwnd
                    logging.info(f"Browser detected: {process_name} (hwnd: {hwnd}, title: {win32gui.GetWindowText(hwnd)})")

        win32gui.EnumWindows(enum_windows_callback, None)
        logging.info(f"Detected IDE window: {self.ide_window}, Browser window: {self.browser_window}")

    def set_transparency(self, hwnd, opacity, clickthrough=False):
        """Set transparency and click-through for a window."""
        if not hwnd or not win32gui.IsWindow(hwnd):
            return
        try:
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            new_style = style | win32con.WS_EX_LAYERED
            if clickthrough:
                new_style |= win32con.WS_EX_TRANSPARENT
            else:
                new_style &= ~win32con.WS_EX_TRANSPARENT
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, new_style)
            win32gui.SetLayeredWindowAttributes(hwnd, 0, int(opacity), win32con.LWA_ALPHA)
        except Exception as e:
            logging.error(f"Failed to set transparency for window {hwnd}: {e}")

    def apply_transparency(self):
        """Apply transparency based on current state and preset."""
        if not self.ide_window or not self.browser_window:
            self.detect_windows()
            if not self.ide_window or not self.browser_window:
                return

        if not self.transparency_enabled:
            self.set_transparency(self.ide_window, 255, False)
            self.set_transparency(self.browser_window, 255, False)
            return

        preset = self.config["presets"][self.config["current_preset"]]
        if self.config["current_preset"] == "dynamic":
            active_opacity = preset["active"]  # Transparent for top window
            background_opacity = preset["background"]  # Opaque for behind window
            if self.active_window == self.ide_window:
                self.set_transparency(self.ide_window, active_opacity, False)
                self.set_transparency(self.browser_window, background_opacity, self.config["clickthrough_enabled"])
            else:
                self.set_transparency(self.ide_window, background_opacity, self.config["clickthrough_enabled"])
                self.set_transparency(self.browser_window, active_opacity, False)
        else:
            self.set_transparency(self.ide_window, preset["ide"], False)
            self.set_transparency(self.browser_window, preset["browser"], False)

    def toggle_transparency(self):
        """Toggle transparency on/off."""
        self.transparency_enabled = not self.transparency_enabled
        self.apply_transparency()
        state = "enabled" if self.transparency_enabled else "disabled"
        logging.info(f"Transparency {state}")

    def swap_active_window(self):
        """Swap the active window, make the top window transparent, and ensure it stays on top."""
        if not self.ide_window or not self.browser_window:
            logging.error("IDE or browser window not detected.")
            return

        if self.config["current_preset"] == "dynamic":
            # Swap the active window
            self.active_window = self.browser_window if self.active_window == self.ide_window else self.ide_window
            background_window = self.browser_window if self.active_window == self.ide_window else self.ide_window

            # Apply transparency: active (top) is transparent, background (behind) is opaque
            self.apply_transparency()

            # If transparency is enabled, adjust the Z-order
            if self.transparency_enabled:
                try:
                    # Restore windows if minimized
                    if win32gui.IsIconic(self.active_window):
                        win32gui.ShowWindow(self.active_window, win32con.SW_RESTORE)
                    if win32gui.IsIconic(background_window):
                        win32gui.ShowWindow(background_window, win32con.SW_RESTORE)

                    # Ensure the background (opaque) window is behind
                    win32gui.SetWindowPos(
                        background_window,
                        win32con.HWND_BOTTOM,  # Push it to the bottom of the Z-order
                        0, 0, 0, 0,
                        win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
                    )
                    # Bring the active (transparent) window to the top
                    win32gui.SetWindowPos(
                        self.active_window,
                        win32con.HWND_TOP,  # Place it at the top of the Z-order
                        0, 0, 0, 0,
                        win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
                    )
                    logging.info(
                        f"Z-order set: {win32gui.GetWindowText(self.active_window)} (transparent) "
                        f"on top of {win32gui.GetWindowText(background_window)} (opaque)"
                    )
                except Exception as e:
                    logging.error(f"Failed to set Z-order: {e}")

            logging.info(f"Active window swapped to: {win32gui.GetWindowText(self.active_window)}")
        else:
            # Handle non-dynamic mode
            target = self.browser_window if self.active_window == self.ide_window else self.ide_window
            try:
                win32gui.SetForegroundWindow(target)
                self.active_window = target
                logging.info(f"Foreground set to: {win32gui.GetWindowText(target)}")
            except Exception as e:
                logging.error(f"Failed to set foreground window: {e}")

    def reset_layout(self):
        """Reset windows to side-by-side layout."""
        if not self.ide_window or not self.browser_window:
            return
        screen_width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        screen_height = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
        win32gui.SetWindowPos(self.ide_window, win32con.HWND_TOP, 0, 0, screen_width // 2, screen_height, 0)
        win32gui.SetWindowPos(self.browser_window, win32con.HWND_TOP, screen_width // 2, 0, screen_width // 2, screen_height, 0)
        logging.info("Window layout reset to side-by-side")

    def cycle_preset(self):
        """Cycle through transparency presets."""
        preset_names = list(self.config["presets"].keys())
        current_index = preset_names.index(self.config["current_preset"])
        next_index = (current_index + 1) % len(preset_names)
        self.config["current_preset"] = preset_names[next_index]
        self.apply_transparency()
        logging.info(f"Preset changed to {self.config['current_preset']}")

    def setup_hotkeys(self):
        """Set up global hotkeys."""
        hotkeys = {k: lambda a=v: self.on_hotkey(a) for v, k in self.config["hotkeys"].items()}
        try:
            self.hotkey_listener = keyboard.GlobalHotKeys(hotkeys)
            self.hotkey_listener.start()
            logging.info("Hotkeys set up successfully")
        except Exception as e:
            logging.error(f"Failed to set up hotkeys: {e}")

    def on_hotkey(self, action):
        """Handle hotkey actions."""
        actions = {
            "toggle_transparency": self.toggle_transparency,
            "swap_active": self.swap_active_window,
            "reset_layout": self.reset_layout,
            "next_preset": self.cycle_preset,
            "exit": self.root.quit
        }
        if action in actions:
            actions[action]()

    def create_tray_icon(self):
        """Create system tray icon with context menu."""
        wc = win32gui.WNDCLASS()
        wc.hInstance = win32api.GetModuleHandle(None)
        wc.lpszClassName = 'CodeFlowVisionTray'
        wc.style = win32con.CS_VREDRAW | win32con.CS_HREDRAW
        wc.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)
        wc.hbrBackground = win32con.COLOR_WINDOW
        wc.lpfnWndProc = self.tray_window_proc
        try:
            class_atom = win32gui.RegisterClass(wc)
        except Exception as e:
            logging.error(f"Failed to register tray class: {e}")
            return

        self.tray_hwnd = win32gui.CreateWindow(
            class_atom, 'CodeFlowVisionTray', 0, 0, 0, 0, 0, 0, 0, wc.hInstance, None
        )

        # Load icon
        try:
            if getattr(sys, 'frozen', False):
                # If running as exe
                icon_path = os.path.join(sys._MEIPASS, 'icon.ico')
            else:
                # If running as script
                icon_path = os.path.join(os.path.dirname(__file__), 'icon.ico')
            hicon = win32gui.LoadIcon(0, icon_path)
        except:
            hicon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)
        nid = (self.tray_hwnd, 0, win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP,
               win32con.WM_USER + 20, hicon, 'CodeFlowVision')
        try:
            win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, nid)
        except Exception as e:
            logging.error(f"Failed to add tray icon: {e}")

        self.tray_menu = win32gui.CreatePopupMenu()
        win32gui.AppendMenu(self.tray_menu, win32con.MF_STRING, 1001, 'Settings')
        win32gui.AppendMenu(self.tray_menu, win32con.MF_STRING, 1002, 'Toggle Transparency')
        win32gui.AppendMenu(self.tray_menu, win32con.MF_STRING, 1003, 'Redetect Windows')
        win32gui.AppendMenu(self.tray_menu, win32con.MF_STRING, 1004, 'Exit')

    def tray_window_proc(self, hwnd, msg, wparam, lparam):
        """Handle tray icon messages."""
        if msg == win32con.WM_USER + 20:
            if lparam == win32con.WM_RBUTTONUP:
                pos = win32gui.GetCursorPos()
                win32gui.SetForegroundWindow(self.tray_hwnd)
                win32gui.TrackPopupMenu(self.tray_menu, win32con.TPM_LEFTALIGN, pos[0], pos[1], 0, self.tray_hwnd, None)
                win32gui.PostMessage(self.tray_hwnd, win32con.WM_NULL, 0, 0)
            elif lparam == win32con.WM_LBUTTONDBLCLK:
                self.show_settings()
        elif msg == win32con.WM_COMMAND:
            if wparam == 1001:
                self.show_settings()
            elif wparam == 1002:
                self.toggle_transparency()
            elif wparam == 1003:
                self.ide_window = self.browser_window = self.active_window = None
                self.detect_windows()
                if self.ide_window and self.browser_window:
                    self.active_window = self.ide_window
                self.apply_transparency()
            elif wparam == 1004:
                self.root.quit()
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def show_settings(self):
        """Show settings dialog."""
        settings_window = Toplevel(self.root)
        settings_window.title("CodeFlowVision Settings")
        settings_window.geometry("300x200")

        Label(settings_window, text="Dynamic Active Opacity (0-255):").grid(row=0, column=0, padx=5, pady=5)
        active_opacity_entry = Entry(settings_window)
        active_opacity_entry.grid(row=0, column=1)
        active_opacity_entry.insert(0, str(self.config["presets"]["dynamic"]["active"]))

        Label(settings_window, text="Dynamic Background Opacity (0-255):").grid(row=1, column=0, padx=5, pady=5)
        background_opacity_entry = Entry(settings_window)
        background_opacity_entry.grid(row=1, column=1)
        background_opacity_entry.insert(0, str(self.config["presets"]["dynamic"]["background"]))

        def save_settings():
            try:
                active = int(active_opacity_entry.get())
                background = int(background_opacity_entry.get())
                if 0 <= active <= 255 and 0 <= background <= 255:
                    self.config["presets"]["dynamic"]["active"] = active
                    self.config["presets"]["dynamic"]["background"] = background
                    self.save_config()
                    self.apply_transparency()
                    settings_window.destroy()
                else:
                    messagebox.showerror("Error", "Opacity values must be between 0 and 255")
            except ValueError:
                messagebox.showerror("Error", "Please enter valid integer values")

        Button(settings_window, text="Save", command=save_settings).grid(row=2, column=0, columnspan=2, pady=10)

    def run(self):
        """Run the main application loop."""
        def pump_messages():
            win32gui.PumpWaitingMessages()
            self.root.after(100, pump_messages)

        def check_windows():
            if self.ide_window and not win32gui.IsWindow(self.ide_window):
                self.ide_window = None
            if self.browser_window and not win32gui.IsWindow(self.browser_window):
                self.browser_window = None
            if (self.ide_window is None or self.browser_window is None) and self.transparency_enabled:
                self.detect_windows()
                if self.ide_window and self.browser_window and self.active_window is None:
                    self.active_window = self.ide_window
                self.apply_transparency()
            self.root.after(5000, check_windows)  # Check every 5 seconds

        self.apply_transparency()
        self.root.after(100, pump_messages)
        self.root.after(5000, check_windows)
        self.root.mainloop()

if __name__ == "__main__":
    app = CodeFlowVision()
    app.run()