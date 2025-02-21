import win32gui
import win32con
import win32api
import win32process
import keyboard
from ctypes import windll
import time


class WindowTransparencyManager:
    def __init__(self):
        self.windows = {
            "ide": {"hwnd": None, "title": None, "is_active": False},
            "browser": {"hwnd": None, "title": None, "is_active": False},
        }
        self.active_opacity = 255  # Fully opaque
        self.background_opacity = 160  # More transparent for background
        self.is_running = True

    def find_windows(self):
        """Find and store IDE and browser windows."""

        def enum_window_callback(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                # IDE detection (including Cursor IDE)
                if any(
                    ide in title
                    for ide in [
                        "Visual Studio Code",
                        "PyCharm",
                        "IntelliJ",
                        "Eclipse",
                        "Sublime",
                        "Cursor",
                    ]
                ):
                    self.windows["ide"]["hwnd"] = hwnd
                    self.windows["ide"]["title"] = title
                # Browser detection
                elif any(
                    browser in title
                    for browser in ["Chrome", "Firefox", "Edge", "Opera", "Brave"]
                ):
                    self.windows["browser"]["hwnd"] = hwnd
                    self.windows["browser"]["title"] = title
            return True

        win32gui.EnumWindows(enum_window_callback, None)

        # Set initial state - IDE active, browser background
        if self.windows["ide"]["hwnd"] and self.windows["browser"]["hwnd"]:
            self.windows["ide"]["is_active"] = True
            self.apply_opacity_settings()
            return True
        return False

    def apply_opacity_settings(self):
        """Apply opacity settings based on current state."""
        for window_type, info in self.windows.items():
            if info["hwnd"]:
                opacity = (
                    self.active_opacity
                    if info["is_active"]
                    else self.background_opacity
                )
                self.set_window_transparency(info["hwnd"], opacity)

    def set_window_transparency(self, hwnd, alpha):
        """Set the transparency of a window."""
        try:
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            win32gui.SetWindowLong(
                hwnd, win32con.GWL_EXSTYLE, style | win32con.WS_EX_LAYERED
            )
            windll.user32.SetLayeredWindowAttributes(hwnd, 0, alpha, win32con.LWA_ALPHA)
        except Exception as e:
            print(f"Error setting transparency: {e}")

    def switch_active_window(self):
        """Switch which window is active/background."""
        self.windows["ide"]["is_active"] = not self.windows["ide"]["is_active"]
        self.windows["browser"]["is_active"] = not self.windows["browser"]["is_active"]

        self.apply_opacity_settings()

        active_window = "ide" if self.windows["ide"]["is_active"] else "browser"
        hwnd = self.windows[active_window]["hwnd"]

        if hwnd:
            # Forcefully bring the window to the foreground
            fg_window = win32gui.GetForegroundWindow()
            current_thread = win32api.GetCurrentThreadId()
            active_thread, _ = win32process.GetWindowThreadProcessId(fg_window)

            if active_thread != current_thread:
                win32api.AttachThreadInput(current_thread, active_thread, True)
                win32gui.SetForegroundWindow(hwnd)
                win32api.AttachThreadInput(current_thread, active_thread, False)
            else:
                win32gui.SetForegroundWindow(hwnd)

    def run(self):
        """Run the transparency manager."""
        if not self.find_windows():
            print("Could not find both IDE and browser windows!")
            return

        print("\nDetected windows:")
        for window_type, info in self.windows.items():
            print(f"- {window_type.upper()}: {info['title']}")

        print("\nControls:")
        print("- Press Alt + X to switch between IDE and browser")
        print("- Press Alt + R to refresh window detection")
        print("- Press Alt + Esc to exit")

        # Setup keyboard hooks with better key choices
        keyboard.on_press_key(
            "x", lambda _: self.handle_switch_key()
        )  # Changed from "space" to "x"
        keyboard.on_press_key("r", lambda _: self.handle_refresh_key())
        keyboard.on_press_key("esc", lambda _: self.handle_exit_key())

        while self.is_running:
            time.sleep(0.1)

    def handle_switch_key(self):
        """Handle window switch hotkey, but only trigger when not typing."""
        if (
            keyboard.is_pressed("alt")
            and not keyboard.is_pressed("ctrl")
            and not keyboard.is_pressed("shift")
        ):
            self.switch_active_window()

    def handle_refresh_key(self):
        """Handle refresh windows hotkey."""
        if keyboard.is_pressed("alt"):
            self.find_windows()

    def handle_exit_key(self):
        """Handle exit hotkey."""
        if keyboard.is_pressed("alt"):
            # Reset windows to full opacity
            for info in self.windows.values():
                if info["hwnd"]:
                    self.set_window_transparency(info["hwnd"], self.active_opacity)
            self.is_running = False


if __name__ == "__main__":
    manager = WindowTransparencyManager()
    manager.run()
