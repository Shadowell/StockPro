const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');
const { execSync } = require('child_process');

// 启动Python后端服务
let pythonServerProcess = null;

function createWindow() {
  const win = new BrowserWindow({
    width: 1400,
    height: 900,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js')
    },
    icon: path.join(__dirname, 'public/icon.png') // 如果有图标的话
  });

  // 在开发环境中加载Vite服务器，在生产环境中加载构建后的文件
  if (process.env.NODE_ENV === 'development') {
    win.loadURL('http://localhost:5173'); // Vite默认端口
  } else {
    win.loadFile(path.join(__dirname, 'dist', 'index.html'));
  }

  // 打开开发者工具
  if (process.env.NODE_ENV === 'development') {
    win.webContents.openDevTools();
  }
}

// 启动Python后端服务
function startPythonBackend() {
  try {
    // 这里启动您的FastAPI后端
    const backendDir = path.join(__dirname, '..', 'backend');
    pythonServerProcess = require('child_process').spawn('uvicorn', [
      'app.main:app',
      '--host', '127.0.0.1',
      '--port', '8000',
      '--reload'
    ], {
      cwd: backendDir,
      stdio: 'inherit',
      env: { ...process.env, PYTHONPATH: backendDir }
    });

    pythonServerProcess.on('error', (err) => {
      console.error('Python server error:', err);
    });

    pythonServerProcess.on('close', (code) => {
      console.log(`Python server exited with code ${code}`);
    });

    console.log('Python backend started on http://127.0.0.1:8000');
  } catch (error) {
    console.error('Failed to start Python backend:', error);
  }
}

// 应用准备就绪时创建窗口并启动后端
app.whenReady().then(() => {
  startPythonBackend();
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

// 关闭应用时终止Python后端
app.on('window-all-closed', () => {
  if (pythonServerProcess) {
    pythonServerProcess.kill();
  }
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

// IPC处理程序
ipcMain.handle('get-app-path', () => {
  return app.getPath('userData');
});