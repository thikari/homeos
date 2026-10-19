/* Einkaufsliste – Eingabe-Toolbar: Tippen · Sprechen · Foto · Barcode.
   Wird von index.html (Tab Einkauf) und der Handy-Seite /einkauf/ geladen.
   initEinkauf({ mount, base, onUpdate })  – base = Pfad bis zum Token, z. B. "/abc123" */
(function () {
  const ZXING = "https://cdn.jsdelivr.net/npm/@zxing/library@0.21.3/umd/index.min.js";
  const css = `
  .ek-bar { display: flex; gap: .5em; flex-wrap: wrap; margin: .2em 0 1em; }
  .ek-bar button { flex: 1 1 auto; justify-content: center; font: inherit; font-weight: 700; font-size: .95em; padding: .75em 1em; border: 1.5px solid var(--line, #d9e3ee); border-radius: 14px; background: #fff; color: var(--fg, #0f2a4a); cursor: pointer; display: flex; align-items: center; gap: .5em; touch-action: manipulation; }
  .ek-bar button svg { width: 1.25em; height: 1.25em; stroke: currentColor; fill: none; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
  .ek-bar button[disabled] { opacity: .4; cursor: default; }
  .ek-bar button.aktiv { background: var(--fg, #0f2a4a); color: #fff; border-color: var(--fg, #0f2a4a); }
  .ek-panel { display: none; margin: 0 0 1em; padding: 1em; border: 1.5px solid var(--line, #d9e3ee); border-radius: 16px; background: var(--soft, #edf3f9); }
  .ek-panel.offen { display: block; }
  .ek-panel form { display: flex; gap: .5em; }
  .ek-panel input[type=text] { flex: 1; font: inherit; font-size: 1.1em; padding: .7em .9em; border: 1.5px solid var(--line, #d9e3ee); border-radius: 12px; min-width: 0; }
  .ek-panel .ek-ok { font: inherit; font-weight: 700; padding: .7em 1.1em; border: 0; border-radius: 12px; background: var(--fg, #0f2a4a); color: #fff; }
  .ek-panel .ek-status { color: var(--muted, #5f7691); font-size: .9em; margin-top: .6em; min-height: 1.2em; }
  .ek-panel .ek-status b { color: var(--fg, #0f2a4a); }
  .ek-panel video { width: 100%; max-height: 42vh; border-radius: 12px; background: #000; display: block; }
  .ek-vorschlag { display: flex; flex-wrap: wrap; gap: .5em; margin-top: .7em; }
  .ek-vorschlag button { font: inherit; font-weight: 600; padding: .55em .9em; border-radius: 999px; border: 1.5px solid var(--good, #16a35a); background: #fff; color: var(--good, #16a35a); }
  .ek-vorschlag button.weg { opacity: .35; text-decoration: line-through; }
  .ek-sprech { font-size: 1.25em; font-weight: 600; min-height: 1.5em; }
  .ek-wer { display: flex; align-items: center; gap: .4em; flex-wrap: wrap; margin: 0 0 .6em; font-size: .85em; color: var(--muted, #5f7691); }
  .ek-wer button { font: inherit; font-weight: 700; padding: .35em .8em; border-radius: 999px; border: 1.5px solid var(--line, #d9e3ee); background: #fff; color: var(--muted, #5f7691); cursor: pointer; }
  .ek-wer button.on { background: var(--fg, #0f2a4a); border-color: var(--fg, #0f2a4a); color: #fff; }
  .ek-wer .ek-r { margin-left: auto; display: flex; gap: .4em; }
  .ek-wer .ek-claim { display: inline-flex; align-items: center; gap: .4em; border-radius: 999px; font-size: 1em; }
  .ek-wer .ek-claim svg { width: 1.1em; height: 1.1em; stroke: currentColor; fill: none; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
  .ek-wer .ek-claim.on { background: var(--good, #16a35a); border-color: var(--good, #16a35a); color: #fff; }
  .ek-wer .ek-share { margin-left: 0; display: inline-flex; align-items: center; gap: .4em; width: auto; height: auto; border-radius: 999px; font-size: 1em; }
  .ek-wer .ek-share svg { width: 1.1em; height: 1.1em; stroke: currentColor; fill: none; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
  `;
  const I = {
    type: '<svg viewBox="0 0 24 24"><rect x="3" y="6" width="18" height="12" rx="2"/><path d="M7 10h.01M11 10h.01M15 10h.01M7 14h10"/></svg>',
    mic: '<svg viewBox="0 0 24 24"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>',
    cam: '<svg viewBox="0 0 24 24"><path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/></svg>',
    bar: '<svg viewBox="0 0 24 24"><path d="M4 6v12M8 6v12M11 6v12M14 6v12M18 6v12M21 6v12"/></svg>',
    cart: '<svg viewBox="0 0 24 24"><path d="M3 4h2l2.4 11h11.2L21 8H7"/><circle cx="9" cy="19" r="1.3"/><circle cx="17" cy="19" r="1.3"/></svg>',
    share: '<svg viewBox="0 0 24 24"><path d="M12 3v12M8 7l4-4 4 4M5 13v6h14v-6"/></svg>',
  };

  async function post(base, path, body, json) {
    const r = await fetch(base + path, { method: "POST", headers: { "Content-Type": json ? "application/json" : "application/x-www-form-urlencoded" }, body: json ? JSON.stringify(body) : body });
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }
  function loadScript(src) { return new Promise((res, rej) => { if (document.querySelector(`script[src="${src}"]`)) return res(); const s = document.createElement("script"); s.src = src; s.onload = res; s.onerror = rej; document.head.appendChild(s); }); }

  const getWer = () => { try { return localStorage.getItem("ek-wer") || ""; } catch (e) { return ""; } };
  const setWer = (w) => { try { localStorage.setItem("ek-wer", w); } catch (e) {} };
  window.einkaufWer = getWer;
  window.einkaufText = function (j) {
    const KAT = { vorrat: "Vorrat · Discounter", frisch: "Frisch · Markt", drogerie: "Drogerie & Haushalt" };
    const lines = ["🛒 Einkaufsliste " + new Date().toLocaleDateString("de-DE", { weekday: "short", day: "numeric", month: "short" })];
    for (const k of ["vorrat", "frisch", "drogerie"]) {
      const its = (j.items || []).filter(i => (i.kat || "vorrat") === k); if (!its.length) continue;
      const ue = (j.uebernahme || {})[k];
      lines.push("", KAT[k].toUpperCase() + (ue ? " – " + ue.wer : ""));
      for (const i of its) { const best = (i.offers || []).filter(o => !o.soon)[0]; lines.push("• " + i.name + (best ? ` (${best.store} ${best.price.toLocaleString("de-DE", { minimumFractionDigits: 2 })} €)` : "")); }
    }
    return lines.join("\n");
  };

  window.initEinkauf = function ({ mount, base, onUpdate, getData }) {
    if (!document.getElementById("ek-css")) { const st = document.createElement("style"); st.id = "ek-css"; st.textContent = css; document.head.appendChild(st); }
    const hasSpeech = !!(window.SpeechRecognition || window.webkitSpeechRecognition);
    const hasCam = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
    const personen = (window.EINKAUF_PERSONEN || ["Tobi", "Julia"]);
    mount.innerHTML = `
      <div class="ek-wer">Ich bin: ${personen.map(p => `<button data-w="${p}" class="${getWer() === p ? "on" : ""}">${p}</button>`).join("")}<span class="ek-r"><button class="ek-claim" title="Ich gehe einkaufen – alle Gruppen übernehmen">${I.cart} <span>Einkauf übernehmen</span></button><button class="ek-share" title="Liste als Text teilen">${I.share} Teilen</button></span></div>
      <div class="ek-bar">
        <button data-m="type">${I.type} Tippen</button>
        <button data-m="mic" ${hasSpeech ? "" : "disabled title='Spracherkennung in diesem Browser nicht verfügbar'"}>${I.mic} Sprechen</button>
        <button data-m="cam">${I.cam} Foto</button>
        <button data-m="bar" ${hasCam ? "" : "disabled"}>${I.bar} Barcode</button>
      </div>
      <div class="ek-panel" id="ek-panel"></div>`;
    const panel = mount.querySelector("#ek-panel");
    let aktiv = null, stopFn = null;

    const add = async (text, sprache) => { const j = await post(base, "/einkauf/add", "text=" + encodeURIComponent(text) + (sprache ? "&sprache=1" : "") + "&wer=" + encodeURIComponent(getWer())); onUpdate && onUpdate(j); return j.reply; };
    mount.querySelectorAll(".ek-wer button[data-w]").forEach(b => b.addEventListener("click", () => { setWer(getWer() === b.dataset.w ? "" : b.dataset.w); mount.querySelectorAll(".ek-wer button[data-w]").forEach(x => x.classList.toggle("on", getWer() === x.dataset.w)); }));
    const claimBtn = mount.querySelector(".ek-claim");
    window.einkaufClaimState = (j) => { const ue = (j && j.uebernahme) || {}; const wer = ["vorrat", "frisch", "drogerie"].map(k => ue[k] && ue[k].wer).filter(Boolean); const alle = wer.length === 3 && new Set(wer).size === 1; claimBtn.classList.toggle("on", alle); claimBtn.querySelector("span").textContent = alle ? wer[0] + " kauft ein" : "Einkauf übernehmen"; };
    claimBtn.addEventListener("click", async () => {
      const w = getWer(); if (!w) { alert("Erst oben auf deinen Namen tippen."); return; }
      const j = await post(base, "/einkauf/claim", "kat=alle&wer=" + encodeURIComponent(w)); onUpdate && onUpdate(j);
    });
    mount.querySelector(".ek-share").addEventListener("click", async () => {
      let j = getData ? getData() : null;
      if (!j) { try { j = await (await fetch(base + "/einkauf.json", { cache: "no-store" })).json(); } catch (e) { return; } }
      const text = window.einkaufText(j);
      if (navigator.share) { try { await navigator.share({ title: "Einkaufsliste", text }); return; } catch (e) { if (e.name === "AbortError") return; } }
      try { await navigator.clipboard.writeText(text); alert("Liste in die Zwischenablage kopiert."); } catch (e) { prompt("Liste kopieren:", text); }
    });
    const close = () => { if (stopFn) { try { stopFn(); } catch (e) {} stopFn = null; } panel.className = "ek-panel"; panel.innerHTML = ""; aktiv = null; mount.querySelectorAll(".ek-bar button").forEach(b => b.classList.remove("aktiv")); };
    const open = (m, html) => { close(); aktiv = m; panel.innerHTML = html; panel.className = "ek-panel offen"; mount.querySelector(`[data-m="${m}"]`).classList.add("aktiv"); };
    const status = (t) => { const s = panel.querySelector(".ek-status"); if (s) s.innerHTML = t; };
    const vorschlaege = (names, quelle) => {
      const v = panel.querySelector(".ek-vorschlag") || panel.appendChild(Object.assign(document.createElement("div"), { className: "ek-vorschlag" }));
      v.innerHTML = "";
      for (const n of names) { const b = document.createElement("button"); b.textContent = "+ " + n; b.onclick = async () => { b.classList.add("weg"); b.disabled = true; status(await add(n)); }; v.appendChild(b); }
      status(names.length ? `Erkannt (${quelle}) – antippen zum Hinzufügen:` : `Nichts erkannt (${quelle}).`);
    };

    // --- Tippen ---
    const modeType = () => {
      open("type", `<form><input type="text" placeholder="Milch, Eier, Windeln …" autocomplete="off" enterkeyhint="done"><button class="ek-ok">Dazu</button></form><div class="ek-status">Mehrere Artikel mit Komma trennen · <b>x Milch</b> hakt ab · <b>frisch: Käse</b> legt die Gruppe fest</div>`);
      const inp = panel.querySelector("input"); inp.focus();
      panel.querySelector("form").onsubmit = async (e) => { e.preventDefault(); const v = inp.value.trim(); if (!v) return; inp.value = ""; status("…"); status(await add(v)); inp.focus(); };
    };
    // --- Sprechen ---
    const modeMic = () => {
      open("mic", `<div class="ek-sprech">Ich höre …</div><div class="ek-status">Sag z. B. „Milch, Eier und Windeln“ – nach einer kurzen Pause wird es übernommen.</div>`);
      const SR = window.SpeechRecognition || window.webkitSpeechRecognition; const r = new SR();
      r.lang = "de-DE"; r.interimResults = true; r.continuous = false; r.maxAlternatives = 1;
      const out = panel.querySelector(".ek-sprech"); let text = "", done = false, still = null;
      const stop = () => { clearTimeout(still); try { r.stop(); } catch (e) {} };
      const fertig = async () => {
        if (done) return; done = true; stop();
        try { r.abort(); } catch (e) {}
        const txt = text.trim().replace(/[.!?]+$/, "");
        if (txt) { out.textContent = txt; status("…"); status(await add(txt, true)); setTimeout(() => { if (aktiv === "mic") close(); }, 1500); }
        else { status("Nichts verstanden – nochmal auf Sprechen tippen."); mount.querySelector('[data-m="mic"]').classList.remove("aktiv"); aktiv = null; }
      };
      r.onresult = (e) => {
        let t = ""; for (const res of e.results) t += res[0].transcript;
        text = t; out.textContent = t || "Ich höre …";
        clearTimeout(still); still = setTimeout(stop, 1800);           // 1,8 s Pause → fertig
        if (e.results[e.results.length - 1].isFinal) stop();
      };
      r.onerror = (e) => { if (e.error !== "aborted" && e.error !== "no-speech") status("Spracherkennung: " + e.error); fertig(); };
      r.onend = fertig;
      stopFn = () => { done = true; stop(); try { r.abort(); } catch (e) {} };
      r.start();
      still = setTimeout(stop, 8000);                                     // nie länger als 8 s offen
    };
    // --- Foto ---
    const modeCam = () => {
      open("cam", `<input type="file" accept="image/*" capture="environment" hidden><div class="ek-status">Foto vom Produkt oder vom leeren Regal im Kühlschrank – ich erkenne, was fehlt.</div>`);
      const inp = panel.querySelector("input"); inp.onchange = async () => {
        const f = inp.files[0]; if (!f) return; status("Bild wird analysiert …");
        const b64 = await new Promise((res) => { const img = new Image(); img.onload = () => { const c = document.createElement("canvas"); const s = Math.min(1, 1024 / Math.max(img.width, img.height)); c.width = img.width * s; c.height = img.height * s; c.getContext("2d").drawImage(img, 0, 0, c.width, c.height); res(c.toDataURL("image/jpeg", 0.8).split(",")[1]); }; img.src = URL.createObjectURL(f); });
        try { const j = await post(base, "/einkauf/photo", { image: b64 }, true); if (j.error) status(j.error); else vorschlaege(j.items || [], "Foto"); } catch (e) { status("Fehler: " + e.message); }
      };
      inp.click();
    };
    // --- Barcode ---
    const modeBar = async () => {
      open("bar", `<video playsinline muted autoplay></video><div class="ek-status">Lade Scanner …</div>`);
      try { await loadScript(ZXING); } catch (e) { status("Scanner konnte nicht geladen werden."); return; }
      const video = panel.querySelector("video");
      const hints = new Map();
      hints.set(ZXing.DecodeHintType.POSSIBLE_FORMATS, [ZXing.BarcodeFormat.EAN_13, ZXing.BarcodeFormat.EAN_8, ZXing.BarcodeFormat.UPC_A, ZXing.BarcodeFormat.UPC_E, ZXing.BarcodeFormat.CODE_128, ZXing.BarcodeFormat.QR_CODE]);
      hints.set(ZXing.DecodeHintType.TRY_HARDER, true);
      const reader = new ZXing.BrowserMultiFormatReader(hints, 300);
      stopFn = () => reader.reset();
      status("Kamera wird gestartet …");
      let busy = false, last = "";
      const onResult = async (result) => {
        if (!result || busy) return;
        const code = result.getText(); if (code === last) return; busy = true; last = code;
        if (navigator.vibrate) navigator.vibrate(60);
        status(`<b>${code}</b> – suche Produkt …`);
        try { const j = await (await fetch(base + "/einkauf/ean/" + encodeURIComponent(code))).json(); vorschlaege(j.name ? [j.name] : [], "Barcode " + code); if (!j.name) status(`Barcode <b>${code}</b> ist nicht in der Datenbank – bitte tippen.`); }
        catch (e) { status("Suche fehlgeschlagen."); }
        setTimeout(() => { busy = false; }, 3000);
      };
      try {
        // Rückkamera erzwingen (iPhone nimmt sonst die Frontkamera)
        await reader.decodeFromConstraints({ audio: false, video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 720 } } }, video, onResult);
        status("Barcode in die Mitte halten, 15–25 cm Abstand, ruhig halten …");
      } catch (e) { status("Kamera nicht verfügbar: " + (e.message || e) + " – Safari ▸ Einstellungen ▸ Kamera erlauben"); }
    };

    mount.querySelectorAll(".ek-bar button").forEach(b => b.addEventListener("click", () => {
      if (b.disabled) return;
      if (aktiv === b.dataset.m) { close(); return; }
      ({ type: modeType, mic: modeMic, cam: modeCam, bar: modeBar })[b.dataset.m]();
    }));
  };
})();
