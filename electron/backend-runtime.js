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

const DEFAULT_PORT = 8000;

function isPortFree(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once('error', () => resolve(false));
    server.listen({ port, host: '127.0.0.1', exclusive: true }, () => server.close(() => resolve(true)));
  });
}

async function assertPortAvailable(port = DEFAULT_PORT) {
  if (!await isPortFree(port)) {
    throw new Error(
      `端口 ${port} 已被占用，请先关闭其他 Echo 或后端实例。 / Port ${port} is in use; close the other Echo or backend instance.`
    );
  }
}

/** First free port among ``candidates`` (duplicates and junk skipped), or null. */
async function pickFreePort(candidates, isFree = isPortFree) {
  const seen = new Set();
  for (const raw of candidates) {
    const port = Number(raw);
    if (!Number.isInteger(port) || port < 1024 || port > 65535 || seen.has(port)) continue;
    seen.add(port);
    if (await isFree(port)) return port;
  }
  return null;
}

class BackendRuntime {
  constructor({ logPath, port = DEFAULT_PORT, onUnexpectedExit = () => {}, spawnProcess = spawn, fetchUrl = fetch,
    checkPort = () => assertPortAvailable(port), pollMs = 250, terminateProcess = terminateOwnedProcess }) {
    Object.assign(this, { logPath, port, onUnexpectedExit, spawnProcess, fetchUrl, checkPort, pollMs, terminateProcess });
    this.baseUrl = `http://127.0.0.1:${port}`;
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
      cwd, env: { ...env, ECHO_DESKTOP_INSTANCE_ID: this.instanceId, ECHO_PORT: String(this.port), PYTHONUTF8: '1' },
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
        const response = await this.fetchUrl(`${this.baseUrl}/`, {
          signal: AbortSignal.timeout(Math.max(1, Math.min(1000, deadline - Date.now())))
        });
        if (response.ok) {
          const payload = await response.json();
          if (payload.desktop_instance_id !== this.instanceId) {
            this.fail(`端口 ${this.port} 上的服务不是本次启动的后端 / Another service owns port ${this.port}.`);
            throw this.failure;
          }
          if (this.failure) throw this.failure;
          const page = await this.fetchUrl(`${this.baseUrl}/app/`, {
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

module.exports = { BackendRuntime, assertPortAvailable, pickFreePort, DEFAULT_PORT };
