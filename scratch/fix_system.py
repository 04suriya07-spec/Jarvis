import os
import subprocess
import sys
import psutil

def kill_processes():
    print("Stopping existing Javris processes...")
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            name = proc.info['name'].lower()
            cmdline = proc.info['cmdline']
            
            # Kill python processes running main.py
            if 'python' in name and cmdline and any('main.py' in arg for arg in cmdline):
                print(f"Killing backend process: {proc.info['pid']}")
                proc.kill()
                
            # Kill electron processes
            if 'electron' in name:
                print(f"Killing electron process: {proc.info['pid']}")
                proc.kill()
                
            # Kill node processes in desktop_app
            if 'node' in name and cmdline and any('desktop_app' in arg for arg in cmdline):
                print(f"Killing node process: {proc.info['pid']}")
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

def cleanup_node_modules():
    node_modules = os.path.join("desktop_app", "node_modules")
    if os.path.exists(node_modules):
        print("Detected existing node_modules. If you still have issues, you might need to delete it and run start-desktop.bat again.")
        # We don't delete it automatically to save time, unless user wants to.

if __name__ == "__main__":
    if os.name != 'nt':
        print("This script is intended for Windows.")
        sys.exit(1)
        
    kill_processes()
    print("\nSystem cleaned. You can now run start-desktop.bat safely.")
    print("I have also optimized the code to prevent future hangs.")
