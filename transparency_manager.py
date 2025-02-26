import win32gui
import win32con
import win32process
import win32api
from pynput import keyboard
from ctypes import windll, wintypes, byref, c_bool
import psutil
import time
import json
import os
import sys
from PIL import Image, ImageTk
import tkinter as tk
from tkinter import ttk
import threading
import logging


class CodeFlowVision:
    def __init__(self):
        # Setup logging
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[logging.FileHandler("codeflow.log"), logging.StreamHandler()],
        )
        self.logger = logging.getLogger("CodeFlowVision")
        self.logger.info("Starting CodeFlow Vision")

        # Configuration with defaults
        self.config = {
            "ide_process_names": [
                "code.exe",
                "pycharm64.exe",
                "idea64.exe",
                "eclipse.exe",
                "sublime_text.exe",
                "atom.exe",
                "androidstudio64.exe",
                "webstorm64.exe",
                "cursor.exe",
            ],
            "browser_process_names": [
                "chrome.exe",
                "firefox.exe",
                "msedge.exe",
                "opera.exe",
                "brave.exe",
                "vivaldi.exe",
                "safari.exe",
                "iexplore.exe",
            ],
            "active_opacity": 255,  # 0-255 range
            "background_opacity": 160,
            "clickthrough_enabled": False,
            "window_positions": {},
            "current_preset": "code-focused",
            "presets": {
                "code-focused": {"ide": 255, "browser": 128},
                "documentation": {"ide": 192, "browser": 192},
                "presentation": {"ide": 255, "browser": 64},
            },
            "hotkeys": {
                "toggle_transparency": "<ctrl>+<alt>+<f7>",
                "swap_active": "<tab>+<shift>+<ctrl>",
                "reset_layout": "<ctrl>+<alt>+<f8>",
                "next_preset": "<ctrl>+<alt>+<f9>",
                "exit": "<ctrl>+<alt>+<f12>",
            },
            "performance_mode": True,
            "auto_start": False,
        }

        self.windows = {
            "ide": {"hwnd": None, "process": None, "active": True, "rect": None},
            "browser": {"hwnd": None, "process": None, "active": False, "rect": None},
        }

        # Simple set to track pressed keys - we'll store actual key objects, not strings
        self.pressed_keys = set()
        
        self.running = True
        self.config_path = os.path.join(
            os.path.expanduser("~"), "codeflow_vision_config.json"
        )
        self.is_fullscreen_app_running = False

        # Load or create config
        self.load_config()
        
        # Log the configured hotkeys
        self.logger.info("=== CONFIGURED HOTKEYS ===")
        for action, hotkey in self.config["hotkeys"].items():
            self.logger.info(f"{action}: {hotkey}")
        self.logger.info("=========================")

        # Initialize GUI components
        self.systray = None
        self.settings_window = None
        self.is_first_run = not os.path.exists(self.config_path)

    def load_config(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r") as f:
                    user_config = json.load(f)
                # Recursive update to preserve nested dicts
                self._update_config_recursive(self.config, user_config)
                self.logger.info("Configuration loaded from %s", self.config_path)
            except json.JSONDecodeError:
                self.logger.error("Invalid config file, using defaults")
        else:
            self.logger.info("No config file found, using defaults")
            self.save_config()

    def _update_config_recursive(self, target, source):
        for key, value in source.items():
            if (
                key in target
                and isinstance(target[key], dict)
                and isinstance(value, dict)
            ):
                self._update_config_recursive(target[key], value)
            else:
                target[key] = value

    def save_config(self):
        # Save window positions before writing config
        for window_type, window_info in self.windows.items():
            if window_info["hwnd"] and win32gui.IsWindow(window_info["hwnd"]):
                rect = win32gui.GetWindowRect(window_info["hwnd"])
                self.config["window_positions"][window_type] = rect

        with open(self.config_path, "w") as f:
            json.dump(self.config, f, indent=2)
        self.logger.info("Configuration saved to %s", self.config_path)

    def get_process_name(self, hwnd):
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            process = psutil.Process(pid)
            return process.name().lower()
        except (psutil.NoSuchProcess, win32process.error):
            return ""

    def is_valid_window(self, hwnd):
        """Check if a window is valid for our purposes"""
        if not win32gui.IsWindowVisible(hwnd):
            return False

        # Skip windows with no title
        title_length = win32gui.GetWindowTextLength(hwnd)
        if title_length == 0:
            return False

        # Skip system windows, taskbar, etc.
        window_style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
        if not (window_style & win32con.WS_OVERLAPPEDWINDOW):
            return False

        return True

    def enum_windows_callback(self, hwnd, _):
        if not self.is_valid_window(hwnd):
            return True

        process_name = self.get_process_name(hwnd)
        window_title = win32gui.GetWindowText(hwnd)

        # Check for IDE
        if not self.windows["ide"]["hwnd"]:
            for ide_name in self.config["ide_process_names"]:
                if ide_name in process_name:
                    self.windows["ide"].update(
                        {
                            "hwnd": hwnd,
                            "process": process_name,
                            "active": True,
                            "title": window_title,
                            "rect": win32gui.GetWindowRect(hwnd),
                        }
                    )
                    self.logger.info(
                        f"Found IDE window: {process_name} - {window_title}"
                    )
                    return True

        # Check for browser
        if not self.windows["browser"]["hwnd"]:
            for browser_name in self.config["browser_process_names"]:
                if browser_name in process_name:
                    self.windows["browser"].update(
                        {
                            "hwnd": hwnd,
                            "process": process_name,
                            "active": False,
                            "title": window_title,
                            "rect": win32gui.GetWindowRect(hwnd),
                        }
                    )
                    self.logger.info(
                        f"Found browser window: {process_name} - {window_title}"
                    )
                    return True

        return True

    def find_windows(self):
        """Find IDE and browser windows"""
        # Save current active states before rediscovery
        old_ide_active = self.windows["ide"]["active"]
        old_browser_active = self.windows["browser"]["active"]
        old_ide_hwnd = self.windows["ide"]["hwnd"]
        old_browser_hwnd = self.windows["browser"]["hwnd"]
        
        self.logger.info(f"Starting window discovery (Previous IDE active={old_ide_active}, Browser active={old_browser_active})")
        
        # Reset window handles
        self.windows["ide"]["hwnd"] = None
        self.windows["browser"]["hwnd"] = None
        win32gui.EnumWindows(self.enum_windows_callback, None)

        # Restore window positions if available
        for window_type, window_info in self.windows.items():
            if (
                window_info["hwnd"]
                and win32gui.IsWindow(window_info["hwnd"])
                and window_type in self.config["window_positions"]
            ):

                rect = self.config["window_positions"][window_type]
                try:
                    win32gui.MoveWindow(
                        window_info["hwnd"],
                        rect[0],
                        rect[1],
                        rect[2] - rect[0],
                        rect[3] - rect[1],
                        True,
                    )
                    self.logger.info(f"Restored position for {window_type} window")
                except Exception as e:
                    self.logger.error(f"Failed to restore window position: {e}")

        # Restore active states unless both windows changed
        if self.windows["ide"]["hwnd"] and self.windows["browser"]["hwnd"]:
            # Only preserve active states if at least one window is the same
            if (self.windows["ide"]["hwnd"] == old_ide_hwnd or self.windows["browser"]["hwnd"] == old_browser_hwnd):
                self.windows["ide"]["active"] = old_ide_active
                self.windows["browser"]["active"] = old_browser_active
                self.logger.info(f"Restored active states: IDE={old_ide_active}, Browser={old_browser_active}")
            else:
                self.logger.info("Both windows changed, using default active states")

        found_windows = all(w["hwnd"] for w in self.windows.values())
        self.logger.info(f"Window discovery complete. Found: IDE={bool(self.windows['ide']['hwnd'])}, Browser={bool(self.windows['browser']['hwnd'])}")
        return found_windows

    def set_transparency(self, hwnd, alpha):
        """Set window transparency (alpha: 0-255)"""
        if not hwnd or not win32gui.IsWindow(hwnd):
            self.logger.error(f"Cannot set transparency: Invalid hwnd {hwnd}")
            return False

        try:
            window_title = win32gui.GetWindowText(hwnd)
            self.logger.debug(f"Setting transparency for window '{window_title}' (hwnd={hwnd}) to alpha={alpha}")
            
            ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            win32gui.SetWindowLong(
                hwnd, win32con.GWL_EXSTYLE, ex_style | win32con.WS_EX_LAYERED
            )
            result = windll.user32.SetLayeredWindowAttributes(
                hwnd, 0, alpha, win32con.LWA_ALPHA
            )
            
            if not result:
                error_code = win32api.GetLastError()
                self.logger.error(f"SetLayeredWindowAttributes failed for '{window_title}' (hwnd={hwnd}): Error code {error_code}")
            else:
                self.logger.debug(f"Successfully set transparency for '{window_title}' to {alpha}")
                
            return result
        except win32gui.error as e:
            self.logger.error(f"Transparency error for hwnd {hwnd}: {e}")
            return False

    def set_clickthrough(self, hwnd, enable):
        """Make window click-through if enabled"""
        if not hwnd or not win32gui.IsWindow(hwnd):
            return False

        try:
            ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            if enable:
                new_style = ex_style | win32con.WS_EX_TRANSPARENT
            else:
                new_style = ex_style & ~win32con.WS_EX_TRANSPARENT
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, new_style)
            return True
        except win32gui.error as e:
            self.logger.error(f"Click-through error: {e}")
            return False

    def update_transparency(self):
        """Update transparency for all managed windows"""
        self.logger.info("=== Updating transparency ===")
        success = True
        rediscovery_triggered = False
        
        # First check if windows are valid
        for window_type, window_info in self.windows.items():
            if not window_info["hwnd"] or not win32gui.IsWindow(window_info["hwnd"]):
                self.logger.warning(f"{window_type} window invalid (hwnd={window_info['hwnd']}), attempting to rediscover...")
                # Save active states before rediscovery
                old_ide_active = self.windows["ide"]["active"]
                old_browser_active = self.windows["browser"]["active"]
                
                self.find_windows()
                rediscovery_triggered = True
                
                # Important: After find_windows, explicitly restore active states
                if self.windows["ide"]["hwnd"] and self.windows["browser"]["hwnd"]:
                    self.windows["ide"]["active"] = old_ide_active
                    self.windows["browser"]["active"] = old_browser_active
                    self.logger.info(f"After rediscovery, restored active states: IDE={old_ide_active}, Browser={old_browser_active}")
                break
                
        # Log current window states
        self.logger.info(f"Current window states:")
        for window_type, window_info in self.windows.items():
            self.logger.info(f"  {window_type}: active={window_info['active']}, hwnd={window_info['hwnd']}, valid={bool(window_info['hwnd'] and win32gui.IsWindow(window_info['hwnd']))}")
        
        # After potential rediscovery, process windows
        for window_type, window_info in self.windows.items():
            if window_info["hwnd"] and win32gui.IsWindow(window_info["hwnd"]):
                if window_info["active"]:
                    alpha = self.config["active_opacity"]
                    clickthrough = False
                else:
                    alpha = self.config["background_opacity"]
                    clickthrough = self.config["clickthrough_enabled"]

                self.logger.info(f"Setting {window_type} (hwnd={window_info['hwnd']}) transparency to {alpha}, clickthrough={clickthrough}")
                if not self.set_transparency(window_info["hwnd"], alpha):
                    self.logger.error(f"Failed to set transparency for {window_type}")
                    success = False
                else:
                    self.logger.info(f"Transparency successfully set for {window_type} to {alpha}")
                
                if not self.set_clickthrough(window_info["hwnd"], clickthrough):
                    self.logger.error(f"Failed to set clickthrough for {window_type}")
                    success = False
                else:
                    self.logger.debug(f"Clickthrough successfully set for {window_type} to {clickthrough}")
            else:
                self.logger.warning(f"Cannot update transparency for {window_type} - window not valid (hwnd={window_info['hwnd']})")
                success = False
        
        self.logger.info(f"Transparency update {'succeeded' if success else 'failed'}")
        return success

    def toggle_transparency(self):
        """Toggle transparency on/off"""
        # Log current state before toggling
        self.logger.info(f"Toggling transparency. Current opacity: {self.config['background_opacity']}")
        
        # Verify windows are found before updating
        valid_windows = True
        for window_type, window_info in self.windows.items():
            if not window_info["hwnd"] or not win32gui.IsWindow(window_info["hwnd"]):
                self.logger.warning(f"Can't update transparency - {window_type} window not found")
                valid_windows = False
        
        if not valid_windows:
            self.logger.info("Attempting to find windows before toggling transparency")
            if not self.find_windows():
                self.show_notification("Cannot toggle - windows not found")
                return False
        
        # Perform the toggle with clearer logic
        current_opacity = self.config["background_opacity"]
        if current_opacity > 0:
            self.config["_saved_background_opacity"] = current_opacity
            self.config["background_opacity"] = 0
            status_msg = "Transparency enabled (background windows hidden)"
        else:
            self.config["background_opacity"] = self.config.get(
                "_saved_background_opacity", 160
            )
            status_msg = f"Transparency disabled (opacity: {self.config['background_opacity']})"

        # Update the transparency
        result = self.update_transparency()
        
        # Log the results
        self.logger.info(f"Transparency toggled to {self.config['background_opacity']}")
        
        # Notify the user
        self.show_notification(status_msg)
        
        return result

    def swap_active_window(self):
        """Swap which window is active"""
        self.logger.info("Swap active window called")
        self.logger.info(f"Before swap: IDE active={self.windows['ide']['active']}, Browser active={self.windows['browser']['active']}")
        
        # Check window validity before swapping
        if not all(win_info["hwnd"] and win32gui.IsWindow(win_info["hwnd"]) for win_info in self.windows.values()):
            self.logger.warning("Cannot swap - invalid windows detected, rediscovering...")
            
            # Save current active states before rediscovery
            old_ide_active = self.windows["ide"]["active"]
            old_browser_active = self.windows["browser"]["active"]
            
            # Find windows
            self.find_windows()
            
            # Restore active states
            if self.windows["ide"]["hwnd"] and self.windows["browser"]["hwnd"]:
                self.windows["ide"]["active"] = old_ide_active
                self.windows["browser"]["active"] = old_browser_active
                self.logger.info(f"Restored active states after rediscovery: IDE={old_ide_active}, Browser={old_browser_active}")
        
        # Toggle active states
        self.windows["ide"]["active"] = not self.windows["ide"]["active"]
        self.windows["browser"]["active"] = not self.windows["browser"]["active"]
        self.logger.info(f"After swap: IDE active={self.windows['ide']['active']}, Browser active={self.windows['browser']['active']}")
        
        # Update transparency
        self.update_transparency()

        # Bring active window to front
        active_type = "ide" if self.windows["ide"]["active"] else "browser"
        try:
            win32gui.SetForegroundWindow(self.windows[active_type]["hwnd"])
            self.logger.info(f"Activated {active_type} window")
        except win32gui.error as e:
            self.logger.error(f"Failed to bring window to foreground: {e}")

    def reset_layout(self):
        """Reset window positions and layout"""
        self.find_windows()

        # Get screen dimensions
        screen_width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        screen_height = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)

        # Position windows side by side
        if self.windows["ide"]["hwnd"] and self.windows["browser"]["hwnd"]:
            # IDE on left half
            win32gui.MoveWindow(
                self.windows["ide"]["hwnd"],
                0,
                0,
                screen_width // 2,
                screen_height,
                True,
            )

            # Browser on right half
            win32gui.MoveWindow(
                self.windows["browser"]["hwnd"],
                screen_width // 2,
                0,
                screen_width // 2,
                screen_height,
                True,
            )

            self.logger.info("Window layout reset")

    def cycle_preset(self):
        """Cycle through transparency presets"""
        presets = list(self.config["presets"].keys())
        current_idx = presets.index(self.config["current_preset"])
        next_idx = (current_idx + 1) % len(presets)
        self.config["current_preset"] = presets[next_idx]

        preset = self.config["presets"][self.config["current_preset"]]
        self.config["active_opacity"] = (
            preset["ide"] if self.windows["ide"]["active"] else preset["browser"]
        )
        self.config["background_opacity"] = (
            preset["browser"] if self.windows["ide"]["active"] else preset["ide"]
        )

        self.update_transparency()
        self.logger.info(f"Switched to preset: {self.config['current_preset']}")
        return self.config["current_preset"]

    def check_fullscreen_apps(self):
        """Check if any fullscreen application is running"""
        foreground_hwnd = win32gui.GetForegroundWindow()
        if not foreground_hwnd:
            return False

        # Skip our own windows
        if foreground_hwnd in [w["hwnd"] for w in self.windows.values()]:
            return False

        foreground_rect = win32gui.GetWindowRect(foreground_hwnd)
        screen_width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        screen_height = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)

        # If window covers entire screen and has no border
        is_fullscreen = (
            foreground_rect[0] <= 0
            and foreground_rect[1] <= 0
            and foreground_rect[2] >= screen_width
            and foreground_rect[3] >= screen_height
        )

        # Check window style - fullscreen apps typically hide their title bar
        style = win32gui.GetWindowLong(foreground_hwnd, win32con.GWL_STYLE)
        has_title_bar = bool(style & win32con.WS_CAPTION)

        return is_fullscreen and not has_title_bar

    def handle_performance_mode(self):
        """Handle performance mode - disable effects when fullscreen apps are running"""
        if not self.config["performance_mode"]:
            return

        is_fullscreen = self.check_fullscreen_apps()
        if is_fullscreen != self.is_fullscreen_app_running:
            self.is_fullscreen_app_running = is_fullscreen
            if is_fullscreen:
                # Save current settings
                self.config["_saved_opacity"] = self.config["background_opacity"]
                # Make background windows fully transparent
                self.config["background_opacity"] = 0
                self.update_transparency()
                self.logger.info("Fullscreen app detected - enabling performance mode")
            else:
                # Restore settings
                if "_saved_opacity" in self.config:
                    self.config["background_opacity"] = self.config["_saved_opacity"]
                    self.update_transparency()
                    self.logger.info("Fullscreen app closed - restoring normal mode")

    def handle_key_press(self, key):
        """Simplified key press handler that focuses on reliable detection"""
        try:
            # Convert to simple string representation for debugging
            key_str = str(key).lower().replace('key.', '')
            self.logger.debug(f"Key pressed: {key_str}")
            
            # Simple approach: check for specific combinations directly
            
            # Tab+Shift+Ctrl for swap active window
            if key_str == 'tab' and keyboard.Key.shift in self.pressed_keys and keyboard.Key.ctrl in self.pressed_keys:
                self.logger.info("Detected Tab+Shift+Ctrl - Swapping active window")
                self.swap_active_window()
                return False
                
            # Ctrl+Alt+F7 for toggle transparency
            if key_str == 'f7' and keyboard.Key.alt in self.pressed_keys and keyboard.Key.ctrl in self.pressed_keys:
                self.logger.info("Detected Ctrl+Alt+F7 - Toggling transparency")
                self.toggle_transparency()
                return False
                
            # Ctrl+Alt+F8 for reset layout
            if key_str == 'f8' and keyboard.Key.alt in self.pressed_keys and keyboard.Key.ctrl in self.pressed_keys:
                self.logger.info("Detected Ctrl+Alt+F8 - Resetting layout")
                self.reset_layout()
                return False
                
            # Ctrl+Alt+F9 for cycle preset
            if key_str == 'f9' and keyboard.Key.alt in self.pressed_keys and keyboard.Key.ctrl in self.pressed_keys:
                self.logger.info("Detected Ctrl+Alt+F9 - Cycling preset")
                preset = self.cycle_preset()
                self.show_notification(f"Preset: {preset}")
                return False
                
            # Ctrl+Alt+F12 for exit
            if key_str == 'f12' and keyboard.Key.alt in self.pressed_keys and keyboard.Key.ctrl in self.pressed_keys:
                self.logger.info("Detected Ctrl+Alt+F12 - Exiting")
                self.exit_handler()
                return False
            
            # Track modifier keys directly  
            self.pressed_keys.add(key)
                
        except Exception as e:
            self.logger.error(f"Key handling error: {str(e)}", exc_info=True)
        return True

    def handle_key_release(self, key):
        """Simplified key release handler"""
        try:
            if key in self.pressed_keys:
                self.pressed_keys.remove(key)
        except Exception as e:
            self.logger.error(f"Error on key release: {str(e)}")
        return True

    def create_system_tray(self):
        """Create system tray icon and menu"""
        # Run Tkinter in the main thread only
        self.root = tk.Tk()
        self.root.title("CodeFlow Vision")
        self.root.geometry("1x1+0+0")  # Make it tiny
        self.root.withdraw()  # Hide the window
        
        # Create a temporary icon file if needed
        import tempfile
        icon_path = os.path.join(tempfile.gettempdir(), "codeflow_icon.ico")
        
        try:
            # Try to use pystray for a better system tray experience
            import pystray
            from PIL import Image
            
            # Create default icon (blue square)
            icon_img = Image.new('RGBA', (64, 64), color=(0, 120, 212))
            
            # Define menu items with proper callbacks
            def create_menu():
                items = [
                    pystray.MenuItem("Status", pystray.Menu(
                        pystray.MenuItem("IDE", lambda: None, enabled=False),
                        pystray.MenuItem("Browser", lambda: None, enabled=False)
                    )),
                    pystray.MenuItem("Find Windows", self.find_windows),
                    pystray.MenuItem("Toggle Transparency", self.toggle_transparency),
                    pystray.MenuItem("Swap Active Window", self.swap_active_window),
                    pystray.MenuItem("Reset Layout", self.reset_layout),
                    pystray.MenuItem("Debug Controls", self.show_debug_ui),
                    pystray.MenuItem("Settings", self.show_settings),
                    pystray.MenuItem("Exit", self.exit_handler)
                ]
                return pystray.Menu(*items)
            
            # Create the icon
            self.systray = pystray.Icon("CodeFlowVision")
            self.systray.icon = icon_img
            self.systray.title = "CodeFlow Vision"
            self.systray.menu = create_menu()
            
            # Run in a separate thread to avoid blocking the main app
            systray_thread = threading.Thread(target=self.systray.run)
            systray_thread.daemon = True
            systray_thread.start()
            
            self.logger.info("Created system tray icon with pystray")
            
        except ImportError:
            self.logger.warning("pystray not available, using Tkinter workaround")
            # Create a simple menu for the system tray
            self.tray_menu = tk.Menu(self.root, tearoff=0)
            self.tray_menu.add_command(label="Find Windows", command=self.find_windows)
            self.tray_menu.add_command(label="Toggle Transparency", command=self.toggle_transparency)
            self.tray_menu.add_command(label="Swap Active Window", command=self.swap_active_window)
            self.tray_menu.add_command(label="Reset Layout", command=self.reset_layout)
            self.tray_menu.add_command(label="Debug Controls", command=self.show_debug_ui)
            self.tray_menu.add_separator()
            self.tray_menu.add_command(label="Settings", command=self.show_settings)
            self.tray_menu.add_separator()
            self.tray_menu.add_command(label="Exit", command=self.exit_handler)
            
            # Without pystray, we'll use a simple icon in the taskbar
            self.root.iconify()
            self.root.title("CodeFlow Vision")
            self.root.protocol("WM_DELETE_WINDOW", self.minimize_to_tray)
            
            # Bind right-click to show the menu
            def show_menu(event):
                self.tray_menu.post(event.x_root, event.y_root)
            
            self.root.bind("<Button-3>", show_menu)
            
            self.logger.info("Created fallback system tray with Tkinter")
        
        # Show first-run tutorial if needed
        if self.is_first_run:
            self.root.after(1000, self.show_first_run_tutorial)

    def minimize_to_tray(self):
        """Minimize to system tray"""
        self.root.withdraw()

    def show_settings(self):
        """Show settings window"""
        if self.settings_window is not None:
            try:
                self.settings_window.deiconify()
                self.settings_window.lift()
                return
            except tk.TclError:
                pass  # Window was destroyed

        self.settings_window = tk.Toplevel(self.root)
        self.settings_window.title("CodeFlow Vision Settings")
        self.settings_window.geometry("400x500")
        self.settings_window.resizable(False, False)

        # Opacity settings
        ttk.Label(
            self.settings_window, text="Opacity Settings", font=("Arial", 12, "bold")
        ).pack(pady=(10, 5))

        ttk.Label(self.settings_window, text="Active Window Opacity:").pack(
            anchor="w", padx=20
        )
        active_opacity_var = tk.IntVar(value=self.config["active_opacity"])
        active_slider = ttk.Scale(
            self.settings_window,
            from_=50,
            to=255,
            orient="horizontal",
            variable=active_opacity_var,
            length=300,
        )
        active_slider.pack(pady=(0, 10), padx=20)

        ttk.Label(self.settings_window, text="Background Window Opacity:").pack(
            anchor="w", padx=20
        )
        bg_opacity_var = tk.IntVar(value=self.config["background_opacity"])
        bg_slider = ttk.Scale(
            self.settings_window,
            from_=0,
            to=255,
            orient="horizontal",
            variable=bg_opacity_var,
            length=300,
        )
        bg_slider.pack(pady=(0, 10), padx=20)

        # Click-through option
        clickthrough_var = tk.BooleanVar(value=self.config["clickthrough_enabled"])
        ttk.Checkbutton(
            self.settings_window,
            text="Enable click-through for background windows",
            variable=clickthrough_var,
        ).pack(anchor="w", padx=20, pady=(0, 10))

        # Performance mode
        perf_mode_var = tk.BooleanVar(value=self.config["performance_mode"])
        ttk.Checkbutton(
            self.settings_window,
            text="Enable performance mode (hide in fullscreen apps)",
            variable=perf_mode_var,
        ).pack(anchor="w", padx=20, pady=(0, 10))

        # Auto-start option
        autostart_var = tk.BooleanVar(value=self.config["auto_start"])
        ttk.Checkbutton(
            self.settings_window, text="Start with Windows", variable=autostart_var
        ).pack(anchor="w", padx=20, pady=(0, 10))

        # Presets section
        ttk.Label(
            self.settings_window,
            text="Transparency Presets",
            font=("Arial", 12, "bold"),
        ).pack(pady=(10, 5))

        preset_frame = ttk.Frame(self.settings_window)
        preset_frame.pack(fill="x", padx=20, pady=5)

        preset_vars = {}
        for i, (preset_name, values) in enumerate(self.config["presets"].items()):
            preset_frame = ttk.Frame(self.settings_window)
            preset_frame.pack(fill="x", padx=20, pady=2)

            ttk.Label(preset_frame, text=f"{preset_name.title()}:").pack(side="left")

            ide_var = tk.IntVar(value=values["ide"])
            ttk.Label(preset_frame, text="IDE:").pack(side="left", padx=(10, 0))
            ide_slider = ttk.Scale(
                preset_frame,
                from_=50,
                to=255,
                orient="horizontal",
                variable=ide_var,
                length=100,
            )
            ide_slider.pack(side="left", padx=(0, 10))

            browser_var = tk.IntVar(value=values["browser"])
            ttk.Label(preset_frame, text="Browser:").pack(side="left")
            browser_slider = ttk.Scale(
                preset_frame,
                from_=0,
                to=255,
                orient="horizontal",
                variable=browser_var,
                length=100,
            )
            browser_slider.pack(side="left")

            preset_vars[preset_name] = {"ide": ide_var, "browser": browser_var}

        # Save button
        def save_settings():
            self.config["active_opacity"] = active_opacity_var.get()
            self.config["background_opacity"] = bg_opacity_var.get()
            self.config["clickthrough_enabled"] = clickthrough_var.get()
            self.config["performance_mode"] = perf_mode_var.get()
            self.config["auto_start"] = autostart_var.get()

            # Update presets
            for preset_name, vars in preset_vars.items():
                self.config["presets"][preset_name]["ide"] = vars["ide"].get()
                self.config["presets"][preset_name]["browser"] = vars["browser"].get()

            # Apply changes
            self.update_transparency()
            self.save_config()

            # Toggle auto-start
            self.set_auto_start(autostart_var.get())

            self.show_notification("Settings saved")
            self.settings_window.withdraw()

        ttk.Button(self.settings_window, text="Save", command=save_settings).pack(
            pady=20
        )

    def set_auto_start(self, enable):
        """Set application to run at Windows startup"""
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE,
            )

            if enable:
                exe_path = sys.executable
                if exe_path.endswith("python.exe"):
                    # We're running from source, use script path
                    script_path = os.path.abspath(sys.argv[0])
                    winreg.SetValueEx(
                        key,
                        "CodeFlowVision",
                        0,
                        winreg.REG_SZ,
                        f'"{exe_path}" "{script_path}"',
                    )
                else:
                    # We're running from executable
                    winreg.SetValueEx(key, "CodeFlowVision", 0, winreg.REG_SZ, exe_path)
            else:
                try:
                    winreg.DeleteValue(key, "CodeFlowVision")
                except FileNotFoundError:
                    pass

            winreg.CloseKey(key)
        except Exception as e:
            self.logger.error(f"Failed to set auto-start: {e}")

    def show_notification(self, message, timeout=2000):
        """Show a notification to the user"""
        if not hasattr(self, "root") or not self.root:
            return
        
        # Skip win10toast entirely - it's causing issues
        # Use only the Tkinter fallback
        try:
            # Create a notification window
            note = tk.Toplevel(self.root)
            note.withdraw()
            
            # Position at bottom right
            screen_width = note.winfo_screenwidth()
            screen_height = note.winfo_screenheight()
            
            note.title("CodeFlow Vision")
            note.geometry(f"300x80+{screen_width-320}+{screen_height-120}")
            note.configure(background="#2d2d30")
            note.overrideredirect(True)
            note.attributes("-topmost", True)
            
            # Add notification content
            frame = tk.Frame(note, bg="#2d2d30", bd=1, relief=tk.SOLID)
            frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
            
            tk.Label(
                frame,
                text="CodeFlow Vision",
                font=("Segoe UI", 11, "bold"),
                fg="white",
                bg="#2d2d30",
            ).pack(anchor=tk.W, padx=10, pady=(10, 0))
            
            tk.Label(
                frame, text=message, font=("Segoe UI", 10), fg="white", bg="#2d2d30"
            ).pack(anchor=tk.W, padx=10, pady=(5, 10))
            
            # Fade in
            note.attributes("-alpha", 0.0)
            note.deiconify()
            
            def fade_in():
                alpha = note.attributes("-alpha")
                if alpha < 1.0:
                    note.attributes("-alpha", min(alpha + 0.1, 1.0))
                    note.after(20, fade_in)
                else:
                    note.after(timeout, fade_out)
            
            def fade_out():
                alpha = note.attributes("-alpha")
                if alpha > 0.0:
                    note.attributes("-alpha", max(alpha - 0.1, 0.0))
                    note.after(20, fade_out)
                else:
                    note.destroy()
            
            fade_in()
        except Exception as e:
            self.logger.error(f"Failed to show notification: {e}")

    def show_first_run_tutorial(self):
        """Show first-run tutorial"""
        if not self.is_first_run:
            return

        tutorial = tk.Toplevel(self.root)
        tutorial.title("Welcome to CodeFlow Vision")
        tutorial.geometry("600x400")

        ttk.Label(
            tutorial, text="Welcome to CodeFlow Vision!", font=("Arial", 16, "bold")
        ).pack(pady=(20, 10))

        ttk.Label(
            tutorial,
            text="CodeFlow Vision helps you work with your IDE and browser simultaneously.\n"
            "Here are the key shortcuts:",
            font=("Arial", 11),
        ).pack(pady=(0, 10))

        shortcuts_frame = ttk.Frame(tutorial)
        shortcuts_frame.pack(fill="both", expand=True, padx=40, pady=10)

        shortcuts = [
            ("Toggle Transparency", self.config["hotkeys"]["toggle_transparency"]),
            ("Swap Active Window", self.config["hotkeys"]["swap_active"]),
            ("Reset Window Layout", self.config["hotkeys"]["reset_layout"]),
            ("Cycle Transparency Presets", self.config["hotkeys"]["next_preset"]),
            ("Exit Application", self.config["hotkeys"]["exit"]),
        ]

        for i, (action, keys) in enumerate(shortcuts):
            ttk.Label(shortcuts_frame, text=action, font=("Arial", 10, "bold")).grid(
                row=i, column=0, sticky="w", pady=5
            )
            ttk.Label(
                shortcuts_frame, text=keys.replace("<", "").replace(">", "").title()
            ).grid(row=i, column=1, padx=20, sticky="w", pady=5)

        ttk.Label(
            tutorial,
            text="You can access settings through the system tray icon.",
            font=("Arial", 10),
        ).pack(pady=(10, 0))

        ttk.Button(tutorial, text="Get Started", command=tutorial.destroy).pack(pady=20)

    def exit_handler(self):
        """Clean up and exit"""
        self.logger.info("Exiting CodeFlow Vision")

        # Reset windows to normal state
        for window_type, window_info in self.windows.items():
            if window_info["hwnd"] and win32gui.IsWindow(window_info["hwnd"]):
                self.set_transparency(window_info["hwnd"], 255)
                self.set_clickthrough(window_info["hwnd"], False)

        # Save config
        self.save_config()

        # Signal threads to stop
        self.running = False

        # Clean up tkinter if it was initialized
        if hasattr(self, "root"):
            self.root.quit()
            self.root.destroy()

        sys.exit(0)

    def show_debug_ui(self):
        """Show a debug window with direct buttons to test functionality"""
        debug_window = tk.Toplevel(self.root)
        debug_window.title("CodeFlow Vision - Debug Controls")
        debug_window.geometry("400x750")
        debug_window.attributes("-topmost", True)
        
        # Style
        style = ttk.Style()
        style.configure("Debug.TButton", font=("Arial", 11))
        style.configure("Test.TButton", background="#e6f2ff")
        style.configure("Problem.TButton", background="#ffe6e6")
        
        ttk.Label(debug_window, text="Debug Controls", font=("Arial", 14, "bold")).pack(pady=10)
        
        # Function test section
        ttk.Label(debug_window, text="Test Functions", font=("Arial", 12, "bold")).pack(pady=(20, 10), anchor="w", padx=20)
        
        ttk.Button(debug_window, text="Toggle Transparency", command=self.toggle_transparency, style="Debug.TButton").pack(fill="x", padx=20, pady=5)
        ttk.Button(debug_window, text="Swap Active Window", command=self.swap_active_window, style="Debug.TButton").pack(fill="x", padx=20, pady=5)
        ttk.Button(debug_window, text="Reset Layout", command=self.reset_layout, style="Debug.TButton").pack(fill="x", padx=20, pady=5)
        ttk.Button(debug_window, text="Find Windows", command=self.find_windows, style="Debug.TButton").pack(fill="x", padx=20, pady=5)
        ttk.Button(debug_window, text="Cycle Preset", command=lambda: self.show_notification(f"Preset: {self.cycle_preset()}"), style="Debug.TButton").pack(fill="x", padx=20, pady=5)
        
        # Diagnostics buttons
        diag_frame = ttk.Frame(debug_window)
        diag_frame.pack(fill="x", padx=20, pady=5)
        
        ttk.Label(debug_window, text="Diagnostics", font=("Arial", 12, "bold")).pack(pady=(20, 10), anchor="w", padx=20)
        
        ttk.Button(
            diag_frame, 
            text="Test Window Detection",
            command=self.test_window_detection,
            style="Problem.TButton"
        ).pack(fill="x", pady=5)
        
        ttk.Button(
            diag_frame, 
            text="Test Hotkey Detection",
            command=self.test_hotkey_detection,
            style="Problem.TButton"
        ).pack(fill="x", pady=5)
        
        ttk.Button(
            diag_frame, 
            text="Test Transparency",
            command=self.test_transparency,
            style="Problem.TButton"
        ).pack(fill="x", pady=5)
        
        ttk.Button(
            diag_frame, 
            text="Test Swap 5 Times",
            command=self.test_swap_sequence,
            style="Problem.TButton"
        ).pack(fill="x", pady=5)
        
        # Test hotkeys section
        ttk.Label(debug_window, text="Test Hotkey Detection", font=("Arial", 12, "bold")).pack(pady=(20, 10), anchor="w", padx=20)
        
        test_frame = ttk.Frame(debug_window)
        test_frame.pack(fill="x", padx=20, pady=5)
        
        # Button to simulate pressing each hotkey
        ttk.Button(test_frame, text="Test All Hotkeys", command=self.test_all_hotkeys, style="Test.TButton").pack(fill="x", pady=5)
        
        # Add test buttons for each individual hotkey
        for action in self.config["hotkeys"]:
            hotkey_str = self.config["hotkeys"][action].replace("<", "").replace(">", "").title()
            ttk.Button(
                test_frame, 
                text=f"Test: {action.replace('_', ' ').title()} ({hotkey_str})",
                command=lambda a=action: self.test_hotkey(a)
            ).pack(fill="x", pady=2)
        
        # Window info section
        ttk.Label(debug_window, text="Window Information", font=("Arial", 12, "bold")).pack(pady=(20, 10), anchor="w", padx=20)
        
        info_frame = ttk.Frame(debug_window)
        info_frame.pack(fill="x", padx=20, pady=5)
        
        # Function to update window info
        window_labels = {}
        
        def update_info():
            for window_type, info in self.windows.items():
                label_text = f"{window_type.upper()}: "
                if info["hwnd"] and win32gui.IsWindow(info["hwnd"]):
                    label_text += f"Found - {info['title'][:30]}..."
                    label_text += f"\nActive: {info['active']}"
                    label_text += f"\nHWND: {info['hwnd']}"
                else:
                    label_text += "Not found"
                
                if window_type in window_labels:
                    window_labels[window_type].config(text=label_text)
                else:
                    window_labels[window_type] = ttk.Label(info_frame, text=label_text)
                    window_labels[window_type].pack(anchor="w", pady=5)
            
            # Schedule next update
            debug_window.after(1000, update_info)
        
        # Start updating
        update_info()
        
        # Hotkey info section
        ttk.Label(debug_window, text="Current Hotkeys", font=("Arial", 12, "bold")).pack(pady=(20, 10), anchor="w", padx=20)
        
        hotkey_frame = ttk.Frame(debug_window)
        hotkey_frame.pack(fill="x", padx=20, pady=5)
        
        for action, keys in self.key_combinations.items():
            ttk.Label(hotkey_frame, text=f"{action}: {', '.join(keys)}").pack(anchor="w", pady=2)
        
        # Close button
        ttk.Button(debug_window, text="Close", command=debug_window.destroy).pack(pady=20)

    def test_hotkey(self, action):
        """Test a specific hotkey action manually"""
        self.logger.info(f"Testing hotkey action: {action}")
        
        if action == "toggle_transparency":
            self.toggle_transparency()
            return True
        elif action == "swap_active":
            self.swap_active_window()
            return True
        elif action == "reset_layout":
            self.reset_layout()
            return True
        elif action == "next_preset":
            preset = self.cycle_preset()
            self.show_notification(f"Preset: {preset}")
            return True
        elif action == "exit":
            # Don't actually exit when testing
            self.show_notification("Exit action detected (not exiting during test)")
            return True
        return False
        
    def test_all_hotkeys(self):
        """Test all hotkey actions in sequence"""
        self.logger.info("Testing all hotkey actions")
        
        # First find windows if needed
        if not all(w["hwnd"] for w in self.windows.values()):
            self.find_windows()
            
        # Run each action except exit
        for action in self.config["hotkeys"]:
            if action != "exit":  # Skip exit
                self.test_hotkey(action)
                time.sleep(1)  # Short delay between actions
                
        self.show_notification("All hotkey tests completed")

    def test_window_detection(self):
        """Test window detection and report results"""
        self.logger.info("Testing window detection")
        self.find_windows()
        
        results = []
        for window_type, window_info in self.windows.items():
            status = {
                "type": window_type,
                "found": bool(window_info["hwnd"]),
                "hwnd": window_info["hwnd"],
                "process": window_info.get("process", "N/A"),
                "title": window_info.get("title", "N/A")
            }
            self.logger.info(f"{window_type}: HWND={status['hwnd']}, Process={status['process']}, Title={status['title']}")
            results.append(status)
            
        # Display results in GUI
        self.show_notification(f"Found windows: {sum(r['found'] for r in results)}/2")
        
        # Test transparency on found windows
        for window_type, window_info in self.windows.items():
            if window_info["hwnd"] and win32gui.IsWindow(window_info["hwnd"]):
                self.logger.info(f"Testing transparency on {window_type} window")
                self.set_transparency(window_info["hwnd"], 128)  # Half transparent
                time.sleep(1)
                self.set_transparency(window_info["hwnd"], 255)  # Back to opaque
                
        return results

    def test_transparency(self):
        """Test transparency functionality on current windows"""
        self.logger.info("Testing transparency functionality")
        
        # Test on current foreground window first
        foreground_hwnd = win32gui.GetForegroundWindow()
        if foreground_hwnd:
            self.logger.info(f"Testing on foreground window: {win32gui.GetWindowText(foreground_hwnd)}")
            for alpha in [255, 200, 150, 100, 50, 100, 150, 200, 255]:
                self.set_transparency(foreground_hwnd, alpha)
                time.sleep(0.3)
                
        # Now test on our managed windows
        for window_type, window_info in self.windows.items():
            if window_info["hwnd"] and win32gui.IsWindow(window_info["hwnd"]):
                self.logger.info(f"Testing on {window_type} window")
                
                # Flash the window to indicate which one we're testing
                win32gui.FlashWindow(window_info["hwnd"], True)
                time.sleep(0.5)
                
                # Test various opacity levels
                for alpha in [255, 200, 150, 100, 50, 100, 150, 200, 255]:
                    self.set_transparency(window_info["hwnd"], alpha)
                    time.sleep(0.3)
                    
        self.show_notification("Transparency test complete")
        return True
    
    def test_hotkey_detection(self):
        """Test hotkey detection and log results"""
        self.logger.info("===== HOTKEY DETECTION TEST =====")
        self.logger.info("Registered hotkeys:")
        for action, keys in self.key_combinations.items():
            self.logger.info(f"  {action}: {keys}")
        
        self.logger.info("Current pressed keys: " + str(self.pressed_keys))
        
        # Show a dialog to explain the test
        hw = tk.Toplevel(self.root)
        hw.title("Hotkey Test")
        hw.geometry("500x400")
        hw.attributes("-topmost", True)
        
        ttk.Label(hw, text="Testing Hotkey Detection", font=("Arial", 14, "bold")).pack(pady=(20, 10))
        
        ttk.Label(hw, text="Press keys to test detection:", font=("Arial", 12)).pack(pady=(10, 5))
        
        # Key display
        key_frame = ttk.Frame(hw)
        key_frame.pack(fill="x", padx=20, pady=10)
        
        key_var = tk.StringVar(value="Press any key...")
        key_label = ttk.Label(key_frame, textvariable=key_var, font=("Courier New", 12))
        key_label.pack(fill="x", pady=5)
        
        pressed_var = tk.StringVar(value="Current pressed keys: {}")
        pressed_label = ttk.Label(key_frame, textvariable=pressed_var, font=("Courier New", 10))
        pressed_label.pack(fill="x", pady=5)
        
        hotkeys_var = tk.StringVar(value="Checking for matches...")
        hotkeys_label = ttk.Label(key_frame, textvariable=hotkeys_var, font=("Courier New", 9))
        hotkeys_label.pack(fill="x", pady=5)
        
        message_var = tk.StringVar(value="Instructions: Press hotkey combinations to test detection")
        message_label = ttk.Label(key_frame, textvariable=message_var, font=("Arial", 10))
        message_label.pack(fill="x", pady=10)
        
        # Previous key processing function
        original_key_press = self.handle_key_press
        original_key_release = self.handle_key_release
        
        # Override key handling for test
        def test_key_press(key):
            # Do standard key processing first
            result = original_key_press(key)
            
            # Then update the UI
            try:
                # Convert key to string for display
                if hasattr(key, "char") and key.char:
                    key_str = key.char
                else:
                    key_str = str(key).replace("Key.", "")
                
                key_var.set(f"Key pressed: {key_str}")
                pressed_var.set(f"Current pressed keys: {self.pressed_keys}")
                
                # Check each hotkey
                matches = []
                for action, keys in self.key_combinations.items():
                    missing = keys - self.pressed_keys
                    if not missing:
                        matches.append(action)
                    hotkeys_var.set(f"Hotkey matches: {matches}")
                    
                    if matches:
                        message_var.set(f"MATCH FOUND! Actions: {', '.join(matches)}")
                    else:
                        message_var.set("No hotkey matches yet")
                
            except Exception as e:
                message_var.set(f"Error: {str(e)}")
                
            return result
            
        def test_key_release(key):
            # Do standard key processing first
            result = original_key_release(key)
            
            # Then update the UI
            try:
                # Convert key to string for display
                if hasattr(key, "char") and key.char:
                    key_str = key.char
                else:
                    key_str = str(key).replace("Key.", "")
                
                key_var.set(f"Key released: {key_str}")
                pressed_var.set(f"Current pressed keys: {self.pressed_keys}")
            except Exception as e:
                message_var.set(f"Error: {str(e)}")
                
            return result
        
        # Set the test handlers
        self.handle_key_press = test_key_press
        self.handle_key_release = test_key_release
        
        # Button to stop the test
        def stop_test():
            self.handle_key_press = original_key_press
            self.handle_key_release = original_key_release
            hw.destroy()
        
        ttk.Button(hw, text="Stop Test", command=stop_test).pack(pady=20)

    def test_swap_sequence(self):
        """Test repeated swapping of active windows to diagnose issues"""
        self.logger.info("===============================================")
        self.logger.info("STARTING SWAP SEQUENCE TEST (5 consecutive swaps)")
        self.logger.info("===============================================")
        
        # Make sure we have valid windows first
        if not all(win_info["hwnd"] and win32gui.IsWindow(win_info["hwnd"]) for win_info in self.windows.values()):
            self.logger.warning("Cannot run swap test - windows not valid, rediscovering...")
            self.find_windows()
            
        # Test initial state
        self.logger.info(f"Initial state: IDE active={self.windows['ide']['active']}, Browser active={self.windows['browser']['active']}")
        
        # Run 5 consecutive swaps with a slight delay between them
        for i in range(5):
            self.logger.info(f"--- SWAP {i+1} ---")
            self.swap_active_window()
            
            # Verify the swap worked
            active_type = "ide" if self.windows["ide"]["active"] else "browser"
            inactive_type = "browser" if self.windows["ide"]["active"] else "ide"
            
            # Check transparency to verify it visually changed
            if self.windows[active_type]["hwnd"] and win32gui.IsWindow(self.windows[active_type]["hwnd"]):
                hwnd = self.windows[active_type]["hwnd"]
                self.logger.info(f"Active window ({active_type}) should have opacity={self.config['active_opacity']}")
                
            if self.windows[inactive_type]["hwnd"] and win32gui.IsWindow(self.windows[inactive_type]["hwnd"]):
                hwnd = self.windows[inactive_type]["hwnd"]
                self.logger.info(f"Inactive window ({inactive_type}) should have opacity={self.config['background_opacity']}")
                
            # Wait briefly before next swap
            time.sleep(1.5)
            
        self.logger.info("===============================================")
        self.logger.info("SWAP SEQUENCE TEST COMPLETE")
        self.logger.info("===============================================")
        
        self.show_notification("Swap sequence test complete")

    def run(self):
        """Main application loop"""
        # Create system tray
        self.create_system_tray()
        
        # Find windows
        if not self.find_windows():
            self.logger.warning("Failed to find both IDE and browser windows")
            self.show_notification("Waiting for IDE and browser windows...")
        else:
            self.update_transparency()
        
        # Show first-run tutorial if needed
        self.show_first_run_tutorial()
        
        # Print simple usage instructions to console
        print("\nCodeFlow Vision is running!")
        print("=== HOTKEYS ===")
        print("Tab+Shift+Ctrl: Swap active window")
        print("Ctrl+Alt+F7: Toggle transparency")
        print("Ctrl+Alt+F8: Reset layout")
        print("Ctrl+Alt+F9: Cycle preset")
        print("Ctrl+Alt+F12: Exit")
        print("==============")
        
        # Start keyboard listener
        with keyboard.Listener(
            on_press=self.handle_key_press, on_release=self.handle_key_release
        ) as listener:
            self.logger.info("CodeFlow Vision running")
            self.show_notification("CodeFlow Vision running")
            
            # Main event loop
            while self.running:
                # Process tkinter events
                try:
                    self.root.update()
                except Exception as e:
                    self.logger.error(f"Error updating tkinter: {e}")
                
                time.sleep(0.05)  # Short sleep to reduce CPU usage
                
                # Simplified periodic check for window validity
                try:
                    for window_type, window_info in self.windows.items():
                        if window_info["hwnd"] and not win32gui.IsWindow(window_info["hwnd"]):
                            self.logger.info(f"{window_type.title()} window is no longer valid")
                            self.find_windows()
                            break
                except Exception as e:
                    self.logger.error(f"Error during window check: {e}")

                # Handle performance mode (dim when fullscreen app is running)
                self.handle_performance_mode()