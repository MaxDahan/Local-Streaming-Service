const express = require("express");
const fs = require("fs");
const os = require("os");
const path = require("path");
const crypto = require("crypto");

const router = express.Router();
router.use(express.json());

const configPath = path.resolve(process.cwd(), "src/configurations/config.json");
const config = JSON.parse(fs.readFileSync(configPath, "utf8"));
const usersPath = path.resolve(process.cwd(), config.users_config || "src/configurations/users.json");
const loginPage = path.resolve(process.cwd(), "public/admin-health/login.html");
const dashboardPage = path.resolve(process.cwd(), "public/admin-health/index.html");

const SAMPLE_MS = Math.max(1500, Number(config.admin_health?.sample_ms || 2500));
const CLIENT_POLL_MS = Math.max(3000, Number(config.admin_health?.client_poll_ms || 5000));
const TOKEN_SECRET = process.env.ADMIN_PORTAL_SECRET || "change-this-admin-portal-secret";
const TOKEN_TTL_SEC = 60 * 60 * 8;

function loadUsers() {
  try { return JSON.parse(fs.readFileSync(usersPath, "utf8")).users || []; }
  catch { return []; }
}
function saveUsers(users) {
  fs.writeFileSync(usersPath, JSON.stringify({ users }, null, 2), "utf8");
}
function parseCookies(req) {
  const raw = req.headers.cookie || "";
  const out = {};
  raw.split(";").forEach(p => {
    const i = p.indexOf("=");
    if (i > -1) out[p.slice(0, i).trim()] = decodeURIComponent(p.slice(i + 1).trim());
  });
  return out;
}
function b64url(input) {
  return Buffer.from(input).toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}
function fromB64url(s) {
  s = s.replace(/-/g, "+").replace(/_/g, "/");
  while (s.length % 4) s += "=";
  return Buffer.from(s, "base64").toString("utf8");
}
function sign(payloadStr) {
  return crypto.createHmac("sha256", TOKEN_SECRET).update(payloadStr).digest("base64url");
}
function createToken(username) {
  const payload = JSON.stringify({ u: username, exp: Math.floor(Date.now() / 1000) + TOKEN_TTL_SEC });
  const body = b64url(payload);
  const sig = sign(body);
  return `${body}.${sig}`;
}
function verifyToken(token) {
  if (!token || !token.includes(".")) return null;
  const [body, sig] = token.split(".");
  if (sign(body) !== sig) return null;
  let data = null;
  try { data = JSON.parse(fromB64url(body)); } catch { return null; }
  if (!data?.u || !data?.exp || data.exp < Math.floor(Date.now() / 1000)) return null;
  return data.u;
}
function getSiteUsername(req) {
  return req.session?.user?.username || req.user?.username || req.session?.username || null;
}
function getEffectiveUser(req) {
  const users = loadUsers();

  const siteUser = getSiteUsername(req);
  if (siteUser) {
    const u = users.find(x => x.username === siteUser && x.enabled);
    if (u) return u;
  }

  const cookies = parseCookies(req);
  const tokenUser = verifyToken(cookies.admin_portal_token);
  if (tokenUser) {
    const u = users.find(x => x.username === tokenUser && x.enabled);
    if (u) return u;
  }

  return null;
}
function requireAdmin(req, res, next) {
  const u = getEffectiveUser(req);
  if (!u || !u.isAdmin) return res.status(403).json({ error: "Forbidden" });
  next();
}

// ---- low-overhead cached sampler ----
let prevCpu = null;
let cache = {};

function cpuTotals(cpus) {
  let idle = 0, total = 0;
  for (const c of cpus) {
    const t = c.times;
    idle += t.idle;
    total += t.user + t.nice + t.sys + t.irq + t.idle;
  }
  return { idle, total };
}
function sample() {
  const totalMem = os.totalmem();
  const freeMem = os.freemem();
  const usedMem = totalMem - freeMem;

  const cpus = os.cpus();
  const now = cpuTotals(cpus);

  let cpuPercent = cache.cpuPercent || 0;
  if (prevCpu) {
    const idleDelta = now.idle - prevCpu.idle;
    const totalDelta = now.total - prevCpu.total;
    if (totalDelta > 0) cpuPercent = Number((((totalDelta - idleDelta) / totalDelta) * 100).toFixed(1));
  }
  prevCpu = now;

  let disk = cache.disk || { path: config.media_root || "/", free: null, total: null, usedPercent: null };
  try {
    if (fs.statfsSync) {
      const st = fs.statfsSync(config.media_root || "/");
      const total = st.bsize * st.blocks;
      const free = st.bsize * st.bavail;
      const used = total - free;
      disk = {
        path: config.media_root || "/",
        free, total,
        usedPercent: total > 0 ? Number(((used / total) * 100).toFixed(1)) : null
      };
    }
  } catch {}

  const pm = process.memoryUsage();
  cache = {
    cpuPercent,
    cpuCores: cpus.length,
    memory: {
      total: totalMem, free: freeMem, used: usedMem,
      usedPercent: Number(((usedMem / totalMem) * 100).toFixed(1))
    },
    loadAvg: os.loadavg().map(v => Number(v.toFixed(2))),
    uptimeSec: os.uptime(),
    process: { rss: pm.rss, heapUsed: pm.heapUsed, heapTotal: pm.heapTotal },
    disk,
    hostname: os.hostname(),
    platform: os.platform(),
    timestamp: new Date().toISOString(),
    clientPollMs: CLIENT_POLL_MS
  };
}
sample();
setInterval(sample, SAMPLE_MS).unref();

// ---- routes ----
router.get("/admin/health/login", (req, res) => res.sendFile(loginPage));
router.get("/admin/health", (req, res) => {
  const u = getEffectiveUser(req);
  if (!u || !u.isAdmin) return res.redirect("/admin/health/login");
  res.sendFile(dashboardPage);
});

router.post("/api/admin/login", (req, res) => {
  const { username, password } = req.body || {};
  const u = loadUsers().find(x => x.username === username && x.enabled);
  if (!u || u.password !== password) return res.status(401).json({ error: "Invalid credentials" });
  const token = createToken(u.username);
  res.setHeader("Set-Cookie", `admin_portal_token=${encodeURIComponent(token)}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${TOKEN_TTL_SEC}`);
  res.json({ ok: true, isAdmin: !!u.isAdmin });
});

router.post("/api/admin/logout", (req, res) => {
  res.setHeader("Set-Cookie", "admin_portal_token=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0");
  res.json({ ok: true });
});

router.get("/api/admin/flag", (req, res) => {
  const u = getEffectiveUser(req);
  res.json({ isAdmin: !!u?.isAdmin, username: u?.username || null });
});

router.get("/api/admin/health", requireAdmin, (req, res) => res.json(cache));

router.get("/api/admin/users", requireAdmin, (req, res) => {
  const users = loadUsers().map(u => ({ username: u.username, isAdmin: !!u.isAdmin, enabled: !!u.enabled }));
  res.json({ users });
});

router.patch("/api/admin/users/:username", requireAdmin, (req, res) => {
  const users = loadUsers();
  const user = users.find(u => u.username === req.params.username);
  if (!user) return res.status(404).json({ error: "User not found" });

  const { isAdmin, enabled, password } = req.body || {};
  if (typeof isAdmin === "boolean") user.isAdmin = isAdmin;
  if (typeof enabled === "boolean") user.enabled = enabled;
  if (typeof password === "string" && password.length >= 4) user.password = password;

  saveUsers(users);
  res.json({ ok: true });
});

module.exports = router;
