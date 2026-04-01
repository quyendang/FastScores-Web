/* edu_ui.js — Interactive logic for Newbie Mode educational layer */

// ── Tooltip System ────────────────────────────────────────────────────────────
function initEduTooltips(snapData) {
  const tooltip = document.getElementById("edu-tooltip");
  if (!tooltip) return;

  document.querySelectorAll(".edu-tip-btn").forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const tipKey = btn.dataset.tip;
      const tip = EDU_TIPS[tipKey];
      if (!tip) return;

      let saysText = "";
      if (tipKey === "rsi")         saysText = tip.says_fn(snapData.rsi_14 || 50);
      else if (tipKey === "macd")   saysText = tip.says_fn(snapData.macd_hist || 0, snapData.macd_rising);
      else if (tipKey === "adx")    saysText = tip.says_fn(snapData.adx_14 || 0);
      else if (tipKey === "bollinger") saysText = tip.says_fn(snapData.bb_pct);
      else if (tipKey === "ema")    saysText = tip.says_fn(snapData.price, snapData.ema200);
      else if (tipKey === "sr")     saysText = tip.says_fn();
      else if (tipKey === "buy_score") saysText = tip.says_fn(snapData.buy_score || 0);

      tooltip.querySelector(".edu-tooltip-name").textContent = tip.name;
      tooltip.querySelector(".edu-tooltip-what-text").textContent = tip.what;
      tooltip.querySelector(".edu-tooltip-says-text").textContent = saysText;
      tooltip.querySelector(".edu-tooltip-action-text").textContent = tip.action;

      tooltip.removeAttribute("hidden");
      const rect = btn.getBoundingClientRect();
      const tW = tooltip.offsetWidth, tH = tooltip.offsetHeight;
      let top  = rect.bottom + 8 + window.scrollY;
      let left = rect.left  + window.scrollX;
      if (left + tW > window.innerWidth - 16) left = window.innerWidth - tW - 16;
      if (top + tH > window.scrollY + window.innerHeight - 16)
        top = rect.top - tH - 8 + window.scrollY;
      tooltip.style.top  = top + "px";
      tooltip.style.left = left + "px";
    });
  });

  document.addEventListener("click", () => tooltip.setAttribute("hidden", ""));
  const closeBtn = tooltip.querySelector(".edu-tooltip-close");
  if (closeBtn) closeBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    tooltip.setAttribute("hidden", "");
  });
}

// ── Signal Explanation Expand/Collapse ───────────────────────────────────────
function initSignalExpand() {
  document.querySelectorAll(".edu-signal-toggle").forEach(btn => {
    btn.addEventListener("click", () => {
      const bodyId = btn.getAttribute("aria-controls");
      const body = document.getElementById(bodyId);
      if (!body) return;
      const expanded = btn.getAttribute("aria-expanded") === "true";
      btn.setAttribute("aria-expanded", String(!expanded));
      body.toggleAttribute("hidden");
      btn.textContent = expanded ? "Xem lý do ▼" : "Thu gọn ▲";
    });
  });
}

// ── Confidence Gauge (SVG arc) ────────────────────────────────────────────────
function initEduGauge(confidencePct) {
  const fill = document.getElementById("edu-gauge-fill");
  if (!fill) return;
  const totalDash  = 251;
  const fillAmount = (confidencePct / 100) * totalDash;
  const offset     = totalDash - fillAmount;
  const color      = confidencePct >= 70 ? "#3fb950" : confidencePct >= 40 ? "#d29922" : "#f85149";
  requestAnimationFrame(() => {
    fill.style.stroke            = color;
    fill.style.strokeDashoffset  = offset;
  });
}

// ── Pre-trade Checklist ───────────────────────────────────────────────────────
function initEduChecklist() {
  const inputs = document.querySelectorAll(".edu-check-input");
  const fillEl = document.getElementById("edu-check-fill");
  const textEl = document.getElementById("edu-check-text");
  const ctaEl  = document.getElementById("edu-checklist-cta");
  if (!inputs.length) return;

  function update() {
    const checked = document.querySelectorAll(".edu-check-input:checked").length;
    const total   = inputs.length;
    const pct     = Math.round(checked / total * 100);
    if (fillEl) fillEl.style.width = pct + "%";
    if (textEl) textEl.textContent = `${checked}/${total} hoàn thành`;
    if (ctaEl)  ctaEl.toggleAttribute("hidden", checked < total);
    inputs.forEach(inp =>
      inp.closest(".edu-check-item")?.classList.toggle("checked", inp.checked)
    );
  }

  inputs.forEach(inp => inp.addEventListener("change", update));
  update();
}

// ── Mini-lesson Widget ────────────────────────────────────────────────────────
function initEduLessons() {
  const widget   = document.getElementById("edu-lesson-widget");
  const bodyEl   = document.getElementById("eduLessonBody");
  const dotsEl   = document.getElementById("eduLessonDots");
  const btnNext  = document.getElementById("eduLessonNext");
  const btnDismiss = document.getElementById("eduLessonDismiss");
  if (!widget || typeof EDU_LESSONS === "undefined") return;

  if (sessionStorage.getItem("edu_widget_dismissed")) {
    widget.classList.add("edu-widget-hidden");
    return;
  }

  let idx = parseInt(localStorage.getItem("edu_lesson_idx") || "0");
  if (idx >= EDU_LESSONS.length) idx = 0;

  dotsEl.innerHTML = EDU_LESSONS.map((_, i) =>
    `<div class="edu-lesson-dot${i === idx ? " active" : ""}" data-idx="${i}" role="button" tabindex="0" aria-label="Bài ${i+1}"></div>`
  ).join("");

  function show(i) {
    const lesson = EDU_LESSONS[i];
    const tagColorClass = `edu-lesson-tag-${lesson.tagColor}`;
    bodyEl.innerHTML = `
      <span class="edu-lesson-tag ${tagColorClass}">${lesson.tag}</span>
      <strong style="display:block;font-size:13px;color:#e6edf3;margin:6px 0 8px">${lesson.title}</strong>
      ${lesson.content}
    `;
    dotsEl.querySelectorAll(".edu-lesson-dot").forEach((d, j) =>
      d.classList.toggle("active", j === i)
    );
    localStorage.setItem("edu_lesson_idx", i);
    idx = i;
  }

  show(idx);

  let autoTimer = setInterval(() => show((idx + 1) % EDU_LESSONS.length), 12000);

  btnNext?.addEventListener("click", () => {
    clearInterval(autoTimer);
    show((idx + 1) % EDU_LESSONS.length);
  });

  dotsEl?.addEventListener("click", (e) => {
    const d = e.target.closest(".edu-lesson-dot");
    if (d) { clearInterval(autoTimer); show(parseInt(d.dataset.idx)); }
  });

  btnDismiss?.addEventListener("click", () => {
    sessionStorage.setItem("edu_widget_dismissed", "1");
    widget.classList.add("edu-widget-hidden");
  });
}
