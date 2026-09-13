/* ============================================================
   Networkat Academy — interactions
   ============================================================ */
(function () {
  "use strict";

  /* ---------- sticky nav ---------- */
  const nav = document.querySelector(".nav");
  const onScroll = () => nav && nav.classList.toggle("scrolled", window.scrollY > 24);
  onScroll();
  window.addEventListener("scroll", onScroll, { passive: true });

  /* ---------- mobile menu ---------- */
  const burger = document.querySelector(".nav__burger");
  const links = document.querySelector(".nav__links");
  if (burger && links) {
    burger.addEventListener("click", () => {
      links.classList.toggle("open");
      burger.classList.toggle("active");
    });
    links.querySelectorAll("a").forEach((a) =>
      a.addEventListener("click", () => { links.classList.remove("open"); burger.classList.remove("active"); })
    );
  }

  /* ---------- language toggle (AR <-> EN) ---------- */
  const langBtn = document.querySelector(".lang-toggle");
  const STORE = "netkat-lang";
  function applyLang(lang) {
    const isEN = lang === "en";
    document.documentElement.lang = isEN ? "en" : "ar";
    document.body.dir = isEN ? "ltr" : "rtl";
    document.querySelectorAll("[data-ar]").forEach((el) => {
      const v = isEN ? el.getAttribute("data-en") : el.getAttribute("data-ar");
      if (v !== null) el.innerHTML = v;
    });
    document.querySelectorAll("[data-ar-ph]").forEach((el) => {
      const v = isEN ? el.getAttribute("data-en-ph") : el.getAttribute("data-ar-ph");
      if (v !== null) el.setAttribute("placeholder", v);
    });
    if (langBtn) langBtn.textContent = isEN ? "عربي" : "EN";
    try { localStorage.setItem(STORE, lang); } catch (e) {}
  }
  let saved = "ar";
  try { saved = localStorage.getItem(STORE) || "ar"; } catch (e) {}
  applyLang(saved);
  if (langBtn) langBtn.addEventListener("click", () => applyLang(document.body.dir === "rtl" ? "en" : "ar"));

  /* ---------- scroll reveal ---------- */
  const io = new IntersectionObserver(
    (entries) => entries.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } }),
    { threshold: 0.12 }
  );
  document.querySelectorAll(".reveal").forEach((el, i) => { el.style.transitionDelay = (i % 4) * 70 + "ms"; io.observe(el); });

  /* ---------- count-up stats ---------- */
  const counters = document.querySelectorAll("[data-count]");
  const cio = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      if (!e.isIntersecting) return;
      const el = e.target, target = parseFloat(el.getAttribute("data-count"));
      const suffix = el.getAttribute("data-suffix") || "";
      let start = 0; const dur = 1400, t0 = performance.now();
      const tick = (now) => {
        const p = Math.min((now - t0) / dur, 1);
        const val = Math.floor((1 - Math.pow(1 - p, 3)) * target);
        el.textContent = val.toLocaleString("en-US") + suffix;
        if (p < 1) requestAnimationFrame(tick);
        else el.textContent = target.toLocaleString("en-US") + suffix;
      };
      requestAnimationFrame(tick);
      cio.unobserve(el);
    });
  }, { threshold: 0.6 });
  counters.forEach((c) => cio.observe(c));

  /* ---------- FAQ ---------- */
  document.querySelectorAll(".faq__q").forEach((q) => {
    q.addEventListener("click", () => {
      const item = q.closest(".faq");
      const ans = item.querySelector(".faq__a");
      const open = item.classList.toggle("open");
      ans.style.maxHeight = open ? ans.scrollHeight + "px" : "0";
    });
  });

  /* ---------- hero network canvas ---------- */
  const canvas = document.querySelector(".hero__canvas");
  if (canvas && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    const ctx = canvas.getContext("2d");
    let w, h, nodes = [], DPR = Math.min(window.devicePixelRatio || 1, 2);
    const LINK = 150;

    function size() {
      const r = canvas.getBoundingClientRect();
      w = r.width; h = r.height;
      canvas.width = w * DPR; canvas.height = h * DPR;
      ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
      const count = Math.min(64, Math.floor((w * h) / 16000));
      nodes = Array.from({ length: count }, () => ({
        x: Math.random() * w, y: Math.random() * h,
        vx: (Math.random() - 0.5) * 0.28, vy: (Math.random() - 0.5) * 0.28,
        r: Math.random() * 1.6 + 1
      }));
    }

    function frame() {
      ctx.clearRect(0, 0, w, h);
      for (let i = 0; i < nodes.length; i++) {
        const n = nodes[i];
        n.x += n.vx; n.y += n.vy;
        if (n.x < 0 || n.x > w) n.vx *= -1;
        if (n.y < 0 || n.y > h) n.vy *= -1;
        for (let j = i + 1; j < nodes.length; j++) {
          const m = nodes[j], dx = n.x - m.x, dy = n.y - m.y;
          const d = Math.hypot(dx, dy);
          if (d < LINK) {
            const a = (1 - d / LINK) * 0.28;
            ctx.strokeStyle = "rgba(41,224,216," + a + ")";
            ctx.lineWidth = 1;
            ctx.beginPath(); ctx.moveTo(n.x, n.y); ctx.lineTo(m.x, m.y); ctx.stroke();
          }
        }
      }
      for (const n of nodes) {
        ctx.beginPath(); ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(120,220,235,0.85)"; ctx.fill();
      }
      requestAnimationFrame(frame);
    }
    size(); frame();
    let rt; window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(size, 200); });
  }

  /* ---------- footer year ---------- */
  const yr = document.querySelector("[data-year]");
  if (yr) yr.textContent = new Date().getFullYear();

  /* ---------- contact form (WhatsApp handoff) ---------- */
  const form = document.querySelector("#contact-form");
  if (form) {
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const name = form.querySelector("[name=name]").value.trim();
      const prog = form.querySelector("[name=program]").value;
      const msg = form.querySelector("[name=message]").value.trim();
      const isEN = document.body.dir === "ltr";
      const text = isEN
        ? `Hi Networkat! I'm ${name}. Interested in: ${prog}. ${msg}`
        : `مرحباً Networkat! أنا ${name}. مهتم بـ: ${prog}. ${msg}`;
      window.open("https://wa.me/201129778191?text=" + encodeURIComponent(text), "_blank");
    });
  }

  // copy install command
  document.querySelectorAll(".copy-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var target = document.querySelector(btn.getAttribute("data-copy"));
      if (!target) return;
      var text = target.textContent.trim();
      var done = function () {
        var isEN = document.body.dir === "ltr";
        var old = btn.textContent;
        btn.textContent = isEN ? "Copied ✓" : "تم النسخ ✓";
        setTimeout(function () { btn.textContent = old; }, 1800);
      };
      if (navigator.clipboard) { navigator.clipboard.writeText(text).then(done).catch(done); }
      else { done(); }
    });
  });
})();
