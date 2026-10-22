// Test funkcjonalny end-to-end na każdym systemie (Windows, Linux, macOS): Node uruchamia procesy Pythona.
// Użycie (z katalogu repo):  cd tests/e2e && npm i && cd ../.. && node tests/e2e/run.js
// Zmienne: PYTHON (domyślnie python lub python3), WEB_PORT (8765), DEV_PORT (9123).
const {spawn, spawnSync} = require('child_process');
const fs = require('fs'), os = require('os'), path = require('path');

const root = path.resolve(__dirname, '..', '..');
const py = [process.env.PYTHON, 'python', 'python3', 'py'].filter(Boolean)
  .find(c => !spawnSync(c, ['--version'], {stdio: 'ignore'}).error);
if (!py) { console.error('Nie znaleziono Pythona (ustaw zmienną PYTHON).'); process.exit(2); }
const WEB = process.env.WEB_PORT || '8765', DEVP = process.env.DEV_PORT || '9123';
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'zn-e2e-'));
const env = {...process.env, DATABASE: path.join(tmp, 'zn.db'), SECRET_KEY: 'e2e', DEVICE_BASE: `http://127.0.0.1:${DEVP}`,
  PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1'};
delete env.RUN_SCHEDULER;  // silnik uruchamia admin przyciskiem, żeby wynik był przewidywalny
const logFile = path.join(tmp, 'server.log'), procs = [];

function start(args) {
  const out = fs.openSync(logFile, 'a');
  const p = spawn(py, args, {cwd: root, env, stdio: ['ignore', out, out]});
  procs.push(p);
  return p;
}
function stop() {
  for (const p of procs) try { p.kill(); } catch (e) { /* już zakończony */ }
}
process.on('exit', stop);
process.on('SIGINT', () => process.exit(130));

async function waitFor(url, ms = 20000) {
  const t = Date.now();
  while (Date.now() - t < ms) {
    try { const r = await fetch(url); if (r.status < 500) return true; } catch (e) { /* jeszcze nie działa */ }
    await new Promise(r => setTimeout(r, 200));
  }
  return false;
}

(async () => {
  const seed = spawnSync(py, ['-m', 'flask', '--app', 'zniesione', 'seed-demo'], {cwd: root, env, encoding: 'utf-8'});
  if (seed.status !== 0) { console.error(seed.stdout, seed.stderr); process.exit(2); }
  start([path.join('tools', 'fake_device.py'), DEVP]);
  start(['-m', 'flask', '--app', 'zniesione', 'run', '--host', '127.0.0.1', '--port', WEB, '--no-reload']);
  const ok = await waitFor(`http://127.0.0.1:${WEB}/healthz`) && await waitFor(`http://127.0.0.1:${DEVP}/state`);
  if (!ok) { console.error('Serwer nie wystartował:\n' + fs.readFileSync(logFile, 'utf-8')); process.exit(2); }
  process.env.BASE = `http://127.0.0.1:${WEB}`;
  process.env.DEV = `http://127.0.0.1:${DEVP}`;
  process.on('exit', code => { if (code) console.error('\nLog serwera: ' + logFile); });
  require('./e2e.js');
})();
