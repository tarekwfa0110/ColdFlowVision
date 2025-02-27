# CodeFlowVision

A Windows utility that enhances developer workflow by managing window transparency between IDE and browser windows. Perfect for referencing documentation while coding.

## Features

- **Smart Window Detection**: Automatically detects and manages IDE and browser windows
- **Dynamic Transparency Control**: Toggle transparency with customizable hotkeys
- **Multiple IDE Support**: Works with:
  - Visual Studio Code
  - PyCharm
  - Eclipse
  - Sublime Text
  - Atom
  - WebStorm
  - Cursor

- **Browser Compatibility**: Supports:
  - Chrome
  - Firefox
  - Edge
  - Opera
  - Brave
  - Vivaldi
  - Safari
  - Internet Explorer

## Installation (Windows)

1. Download the latest release from the releases page
2. Run `CodeFlowVision.exe`
3. The app will start in your system tray

## Installation (For developers)

Clone the repository:
git clone https://github.com/yourusername/CodeFlowVision.git

Install dependencies:
pip install -r requirements.txt

Run the application:
python main.py

## Default Hotkeys

- `Ctrl + Alt + F7`: Toggle transparency
- `Alt + F1`: Swap active window
- `Ctrl + Alt + F8`: Reset layout
- `Ctrl + Alt + F9`: Cycle presets
- `Ctrl + Alt + F12`: Exit application

## Building from Source

Install PyInstaller:
pip install pyinstaller

Build the executable:
python build.py

The executable will be created in the `dist` folder.

## Configuration

The application creates a configuration file at:
%APPDATA%/CodeFlowVision/config.json

You can modify:
- Process names for window detection
- Transparency presets
- Hotkey combinations

## Requirements

- Windows OS
- For development:
  - Python 3.8+
  - Dependencies listed in requirements.txt

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- Built using Win32 API for window management
- Uses Tkinter for GUI elements