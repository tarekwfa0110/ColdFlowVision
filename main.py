#!/usr/bin/env python
"""
CodeFlow Vision - Transparency Manager for Developer Workflows
Helps developers work with multiple windows (IDE, browser) simultaneously by managing window transparency.
"""
import argparse
import sys
import traceback
import logging
import os
from transparency_manager import CodeFlowVision

def parse_arguments():
    parser = argparse.ArgumentParser(description="CodeFlow Vision - Window Transparency Manager")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--minimized", action="store_true", help="Start minimized to system tray")
    parser.add_argument("--reset-config", action="store_true", help="Reset configuration to defaults")
    return parser.parse_args()

def main():
    try:
        # Parse command line arguments
        args = parse_arguments()
        
        # Setup logging level based on arguments
        log_level = logging.DEBUG if args.debug else logging.INFO
        log_path = os.path.join(os.getenv('APPDATA'), 'CodeFlowVision', 'codeflow.log')
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[logging.FileHandler(log_path), logging.StreamHandler()]
        )
        
        # Initialize the application
        app = CodeFlowVision()
        
        # Run the main loop (which will handle Tkinter)
        app.run()
        
    except Exception as e:
        logging.error(f"Error: {e}", exc_info=True)
        print(traceback.format_exc())
        
        # Try to show error in GUI if possible
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("CodeFlow Vision Error", f"An error occurred: {e}\n\nSee log file for details.")
            root.destroy()
        except:
            pass
            
        return 1    
    return 0

if __name__ == "__main__":
    sys.exit(main())                            