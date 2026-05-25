const { app, BrowserWindow, globalShortcut } = require('electron');
const path = require('path');

// Disk cache is enabled normally. If access denied occurs, fix folder permissions instead of disabling cache, which breaks POST requests in Electron.

let mainWindow;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    transparent: true,
    frame: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false
    }
  });

  // Make the window click-through initially, except for opaque elements.
  // Actually, we'll let it be interactive, but if the user wants they can toggle it.
  mainWindow.setIgnoreMouseEvents(false);

  // Load the FastAPI server with retry logic
  const loadWithRetry = () => {
    mainWindow.loadURL('http://127.0.0.1:8000').catch(() => {
      console.log('Backend not ready, retrying in 2s...');
      setTimeout(loadWithRetry, 2000);
    });
  };
  
  loadWithRetry();
  
  // Toggle visibility shortcut
  globalShortcut.register('CommandOrControl+Shift+J', () => {
    if (mainWindow.isVisible()) {
      mainWindow.hide();
    } else {
      mainWindow.show();
    }
  });

  // Toggle click-through (Ghost Mode)
  let isGhost = false;
  globalShortcut.register('CommandOrControl+Shift+K', () => {
    isGhost = !isGhost;
    mainWindow.setIgnoreMouseEvents(isGhost, { forward: true });
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

app.whenReady().then(createWindow);

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('activate', () => {
  if (mainWindow === null) {
    createWindow();
  }
});
