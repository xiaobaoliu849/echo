const fs = require('node:fs');
const path = require('node:path');
const net = require('node:net');
const { randomUUID } = require('node:crypto');
const { spawn, execFileSync } = require('node:child_process');

function terminateOwnedProcess(child) {
  if (process.platform === 'win32') {
    try {
      execFileSync(path.join(process.env.SystemRoot, 'System32', 'taskkill.exe'),
        ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true, timeout: 5000, stdio: 'ignore' });
      return;
    } catch { /* Fall back to terminating the owned backend if taskkill fails. */ }
  }
  child.kill();
}

const BACKEND_URL = 'http://127.0.0.1:8000';

async function assertPortAvailable() {
  await new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', () => reject(new Error(
      '端口 8000 已被占用，请先关闭其他 Echo 或后端实例。 / Port 8000 is in use; close the other Echo or backend instance.'
    )));
    server.listen({ port: 8000, host: '127.0.0.1', exclusive: true }, () => server.close(resolve));
  });
}

class BackendRuntime {
  constructor({ logPath, onUnexpectedExit = () => {}, spawnProcess = spawn, fetchUrl = fetch,
    checkPort = assertPortAvailable, pollMs = 250, terminateProcess = terminateOwnedProcess }) {
    Object.assign(this, { logPath, onUnexpectedExit, spawnProcess, fetchUrl, checkPort, pollMs, terminateProcess });
    this.child = null;
    this.failure = null;
    this.ready = false;
    this.stopping = false;
    this.instanceId = randomUUID();
  }

  log(message) {
    try {
      fs.appendFileSync(this.logPath, `${new Date().toISOString()} ${message}\n`);
    } catch (error) {
      console.error('Cannot write desktop log:', error.message);
    }
  }

  async start(command, args, { cwd, env }) {
    fs.mkdirSync(path.dirname(this.logPath), { recursive: true });
    if (fs.existsSync(this.logPath) && fs.statSync(this.logPath).size > 2 * 1024 * 1024) {
      fs.copyFileSync(this.logPath, `${this.logPath}.previous`);
      fs.truncateSync(this.logPath);
    }
    await this.checkPort();
    this.log(`Starting backend: ${command}`);
    this.child = this.spawnProcess(command, args, {
      cwd, env: { ...env, ECHO_DESKTOP_INSTANCE_ID: this.instanceId, PYTHONUTF8: '1' },
      windowsHide: true, shell: false, stdio: ['ignore', 'pipe', 'pipe']
    });
    this.child.stdout?.on('data', (data) => this.log(data.toString().trim()));
    this.child.stderr?.on('data', (data) => this.log(data.toString().trim()));
    this.child.once('error', (err) => this.fail(`Backend launch failed: ${err.message}`));
    this.child.once('exit', (code, signal) => {
      this.child = null;
      if (!this.stopping) this.fail(`Backend exited (code ${code}, signal ${signal}).`);
    });
  }

  fail(message) {
    this.failure = new Error(`${message}\n请查看启动日志 / See startup log: ${this.logPath}`);
    this.log(message);
    if (this.ready && !this.stopping) this.onUnexpectedExit(this.failure.message);
  }

  async waitUntilReady(timeoutMs = 60000) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (this.failure) throw this.failure;
      try {
        const response = await this.fetchUrl(`${BACKEND_URL}/`, {
          signal: AbortSignal.timeout(Math.max(1, Math.min(1000, deadline - Date.now())))
        });
        if (response.ok) {
          const payload = await response.json();
          if (payload.desktop_instance_id !== this.instanceId) {
            this.fail('端口 8000 上的服务不是本次启动的后端 / Another service owns port 8000.');
            throw this.failure;
          }
          if (this.failure) throw this.failure;
          const page = await this.fetchUrl(`${BACKEND_URL}/app/`, {
            signal: AbortSignal.timeout(Math.max(1, Math.min(1000, deadline - Date.now())))
          });
          const html = await page.text();
          if (!page.ok || !html.includes('<div id="root">')) {
            this.fail('前端资源缺失，请重新安装 / Frontend resources are missing; reinstall Echo.');
            throw this.failure;
          }
          if (this.failure) throw this.failure;
          this.ready = true;
          this.log('Backend and frontend ready.');
          return;
        }
      } catch (error) {
        if (this.failure) throw this.failure;
        this.lastError = error;
      }
      await new Promise((resolve) => setTimeout(resolve, this.pollMs));
    }
    throw new Error(`后端启动超时 / Backend startup timed out. ${this.lastError?.message || ''}\nLog: ${this.logPath}`);
  }

  stop() {
    this.stopping = true;
    const child = this.child;
    this.child = null;
    if (!child?.pid || child.exitCode !== null) return;
    // Include owned ffmpeg children. Synchronous cleanup completes before
    // Electron exits, and an already-exited backend is never targeted.
    try { this.terminateProcess(child); } catch (error) { this.log(`Backend cleanup failed: ${error.message}`); }
  }
}

module.exports = { BackendRuntime, assertPortAvailable };
