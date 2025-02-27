import PyInstaller.__main__
import os

# Get the directory containing build.py
current_dir = os.path.dirname(os.path.abspath(__file__))

PyInstaller.__main__.run([
    'main.py',
    '--onefile',
    '--windowed',
    '--icon=icon.ico',  # Optional: Add this if you have an icon file
    '--name=CodeFlowVision',
    '--add-data=requirements.txt;.',
    '--noconsole',
    f'--workpath={os.path.join(current_dir, "build")}',
    f'--distpath={os.path.join(current_dir, "dist")}',
    '--clean'
]) 