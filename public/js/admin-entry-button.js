(async () => {
  try {
    const r = await fetch("/api/admin/flag", { cache: "no-store" });
    if (!r.ok) return;
    const { isAdmin } = await r.json();
    if (!isAdmin) return;

    const a = document.createElement("a");
    a.href = "/admin/health";
    a.textContent = "Admin Health";
    a.style.cssText =
      "position:fixed;right:16px;bottom:16px;z-index:99999;padding:10px 14px;border-radius:999px;color:#fff;text-decoration:none;font:600 13px Inter,system-ui,sans-serif;background:linear-gradient(135deg,#3f79ff,#6cb2ff);box-shadow:0 10px 30px rgba(0,0,0,.35)";
    document.body.appendChild(a);
  } catch {}
})();
