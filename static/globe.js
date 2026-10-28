/* Lagebild-Globus: dreh- und zoombare Erdkugel mit Ebenen für Konflikte, Meerengen, Wahlen und Flugzeugträger.
   Wird erst beim Öffnen des Reiters geladen. Braucht d3.min.js und world.json (liegen daneben). */
(function () {
  "use strict";

  const COL = {
    ocean1: "#17375a", ocean2: "#08131f", land: "#24384d", border: "rgba(130,170,215,.55)", grid: "rgba(130,170,220,.10)",
    conflict: "255,77,61", unrest: "176,124,255", elect: "77,163,255", ok: "#3ddc97", warn: "#ffb020", bad: "#ff4d3d", ink: "#e8eef6",
  };
  const LEVEL = [["normal", COL.ok], ["gestört", COL.warn], ["stark eingeschränkt", COL.bad]];

  async function loadAssets() {
    if (!window.d3) {
      await new Promise((res, rej) => {
        const s = document.createElement("script");
        s.src = "d3.min.js";
        s.onload = res;
        s.onerror = () => rej(new Error("d3.min.js konnte nicht geladen werden"));
        document.head.append(s);
      });
    }
    if (!window.__world) {
      const r = await fetch("world.json");
      if (!r.ok) throw new Error("world.json: HTTP " + r.status);
      window.__world = await r.json();
    }
    return window.__world;
  }

  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

  function mount(root, X) {
    const { h, store } = X;
    const DATA = X.DATA, geo = DATA.geo || {}, world = window.__world;
    const names = geo.names || {};
    const nameOf = (f) => names[f.id] || f.properties.name;
    const featById = new Map(world.features.map(f => [f.id, f]));
    // Beschriftungspunkt: Mittelpunkt des größten Teilgebiets (sonst wandert z. B. Frankreich wegen Französisch-Guayana)
    const labelInfo = world.features.map(f => {
      const polys = f.geometry.type === "Polygon" ? [f.geometry.coordinates] : f.geometry.coordinates;
      let best = null, bestArea = -1;
      for (const coordinates of polys) {
        const g = { type: "Polygon", coordinates }, a = d3.geoArea(g);
        if (a > bestArea) { bestArea = a; best = g; }
      }
      return { f, area: d3.geoArea(f), c: d3.geoCentroid(best) };
    }).sort((a, b) => b.area - a.area);
    const centroid = new Map(labelInfo.map(li => [li.f.id, li.c]));

    // Suchbegriffe, mit denen Meldungen einem Land zugeordnet werden (ISO-Nummer des Landes)
    const STEMS = {
      643: ["russland", "russisch", "kreml"], 804: ["ukrain", "kiew"], 376: ["israel"], 275: ["palästin", "gaza", "westjordan"],
      364: ["iran", "teheran"], 887: ["jemen", "huthi"], 840: ["usa", "u.s.", "trump", "us-", "vereinigte staaten"],
      156: ["china", "chines", "peking"], 158: ["taiwan"], 760: ["syrien", "syrisch"], 422: ["libanon", "hisbollah"],
      368: ["irak"], 729: ["sudan"], 180: ["kongo"], 104: ["myanmar"], 408: ["nordkorea"], 410: ["südkorea"],
      586: ["pakistan"], 4: ["afghanistan"], 792: ["türkei", "türkisch"], 250: ["frankreich", "französisch"],
      826: ["großbritannien", "britisch", "london"], 276: ["deutschland", "deutsch"], 356: ["indien", "indisch"],
      392: ["japan"], 682: ["saudi"], 818: ["ägypten"], 434: ["libyen"], 466: ["mali"], 566: ["nigeria"], 862: ["venezuela"],
    };
    const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    function storiesFor(f) {
      const de = (names[f.id] || f.properties.name).toLowerCase(), en = f.properties.name.toLowerCase();
      const stems = STEMS[f.id] || [de, en];
      const pats = stems.map(s => s.length < 5 ? new RegExp("(^|[^a-zäöüß])" + esc(s) + "([^a-zäöüß]|$)") : null);
      return DATA.stories.filter(s => { const t = s.title.toLowerCase(); return stems.some((st, i) => pats[i] ? pats[i].test(t) : t.includes(st)); }).slice(0, 4);
    }

    const defaults = { borders: true, names: true, labels: true, conflict: true, unrest: true, chokes: true, elections: true, carriers: true, quakes: true, minConf: 0, minUnrest: 0, elDays: 90, minMag: 5, quakeDays: 7, spin: 2 };
    let S = { ...defaults };
    try { S = { ...defaults, ...JSON.parse(store.get("globe") || "{}") }; } catch {}
    const save = () => store.set("globe", JSON.stringify(S));

    // ---------- Daten aufbereiten
    const conflict = geo.conflict || { points: [], unrest: [], countries: [], days: [] };
    const unrestPoints = conflict.unrest || [];
    const warCountries = conflict.countries.filter(c => c.level === "war");
    const unrestCountries = conflict.countries.filter(c => c.level === "unrest");
    const maxW = Math.max(1, ...conflict.points.map(p => p.w));
    const maxU = Math.max(1, ...unrestPoints.map(p => p.w));
    const confCountry = new Map(conflict.countries.map(c => [c.id, c]));
    const maxCW = Math.max(1, ...warCountries.map(c => c.w));
    const unrestShown = () => unrestPoints.filter(p => p.w >= maxU * (S.minUnrest / 100) ** 2);
    const cps = geo.chokepoints || [];
    const quakeData = (geo.quakes && geo.quakes.items) || [];
    const nowSec = () => Date.now() / 1000;
    const quakesShown = () => quakeData.filter(q => q.mag >= S.minMag && nowSec() - q.t <= S.quakeDays * 86400);
    const magText = (m) => m.toFixed(1).replace(".", ",");
    const strongest = quakeData.reduce((a, q) => (!a || q.mag > a.mag ? q : a), null);
    const carriers = (geo.carriers && geo.carriers.ships || []).filter(s => s.lat != null);
    const elections = (geo.elections || []).slice().sort((a, b) => a.date.localeCompare(b.date));
    const confShown = () => conflict.points.filter(p => p.w >= maxW * (S.minConf / 100) ** 2);
    const elShown = () => elections.filter(e => e.days <= S.elDays);
    const elByCountry = () => { const m = new Map(); for (const e of elShown()) if (!m.has(e.id)) m.set(e.id, e); return m; };

    // ---------- Aufbau der Oberfläche
    const canvas = h("canvas", { class: "gcanvas", "aria-label": "Globus" });
    const g2 = canvas.getContext("2d");
    const tip = h("div", { class: "gtip" });
    const legend = h("div", { class: "glegend" },
      [["255,77,61", "Krieg / bewaffneter Konflikt"], ["176,124,255", "Unruhen & Spannungen"], ["77,163,255", "Wahl"], ["255,190,70", "Erdbeben"]]
        .map(([c, t]) => h("span", {}, h("i", { style: `background:rgb(${c})` }), t)));
    const stage = h("div", { class: "gstage" }, canvas, tip, legend,
      h("div", { class: "gbtns" },
        h("button", { onclick: () => { zoomTo(zoom * 1.4); }, "aria-label": "Vergrößern" }, "+"),
        h("button", { onclick: () => { zoomTo(zoom / 1.4); }, "aria-label": "Verkleinern" }, "−"),
        h("button", { onclick: () => { selected = null; info.replaceChildren(introNode()); flyTo(35, 25, 1); }, "aria-label": "Zurücksetzen", title: "Zurücksetzen" }, "⌂")));
    const info = h("div", { class: "ginfo" });
    const lists = h("div", { class: "glists" });

    const sw = (key, label, sub) => {
      const input = h("input", { type: "checkbox", checked: S[key] || null, onchange: (e) => { S[key] = e.target.checked; save(); renderLists(); } });
      return h("label", { class: "sw" }, input, h("span", { class: "tr" }), h("span", { class: "tx" }, label, sub && h("small", {}, sub)));
    };
    const slider = (key, label, min, max, step, fmt, onchange) => {
      const out = h("output", {}, fmt(S[key]));
      const input = h("input", { type: "range", min, max, step, value: S[key], oninput: (e) => {
        S[key] = Number(e.target.value); out.textContent = fmt(S[key]); save(); dirty = true; if (onchange) onchange();
      } });
      return h("div", { class: "rg" }, h("div", {}, h("span", {}, label), out), input);
    };
    const when = (iso) => iso ? new Date(iso).toLocaleDateString("de-DE", { day: "numeric", month: "short" }) : "";
    const cDays = (conflict.days || []).slice().reverse().map(d => when(d + "T12:00:00")).join(" und ");
    const cpDate = cps.length ? when(cps[0].date + "T12:00:00") : "";
    const stale = (x) => x && x.stale ? " (alter Stand)" : "";
    const controls = h("div", { class: "gctl" },
      h("h3", {}, "Ebenen"),
      sw("conflict", "Kriege & Kampfhandlungen", `${warCountries.length} Länder, ${cDays || "keine Daten"}${stale(conflict)}`),
      sw("unrest", "Unruhen & Spannungen", `${unrestCountries.length} Länder: Proteste, Krawalle, Gewalt`),
      sw("chokes", "Meerengen & Seewege", `${cps.length} Engstellen, Daten bis ${cpDate}`),
      sw("elections", "Wahlen", `${elections.length} in den nächsten 12 Monaten`),
      sw("carriers", "Flugzeugträger (USA)", geo.carriers ? `Tracker vom ${geo.carriers.as_of}${stale(geo.carriers)}` : "keine Daten"),
      sw("quakes", "Erdbeben", quakeData.length ? `${quakeData.length} ab Stärke 4,5 in 7 Tagen${strongest ? ", stärkstes M " + magText(strongest.mag) : ""}${stale(geo.quakes)}` : "keine Daten"),
      sw("borders", "Ländergrenzen"),
      sw("names", "Ländernamen", "mehr Namen beim Hineinzoomen"),
      sw("labels", "Beschriftung der Punkte"),
      h("h3", {}, "Regler"),
      slider("minConf", "Kämpfe: Mindest-Intensität", 0, 90, 5, v => v + " %", () => renderLists()),
      slider("minUnrest", "Unruhen: Mindest-Intensität", 0, 90, 5, v => v + " %", () => renderLists()),
      slider("elDays", "Wahlen: Zeitraum voraus", 7, 365, 1, v => v + " Tage", () => renderLists()),
      slider("minMag", "Erdbeben: Mindest-Stärke", 4.5, 7.5, 0.1, v => "M " + magText(v), () => renderLists()),
      slider("quakeDays", "Erdbeben: letzte Tage", 1, 7, 1, v => v + (v === 1 ? " Tag" : " Tage"), () => renderLists()),
      slider("spin", "Drehung", 0, 10, 0.5, v => v === 0 ? "aus" : v + " °/s"));

    // ---------- Projektion und Zeichnen
    const proj = d3.geoOrthographic().clipAngle(90).precision(0.6);
    const path = d3.geoPath(proj, g2);
    const graticule = d3.geoGraticule10();
    const sphere = { type: "Sphere" };
    const allLand = { type: "FeatureCollection", features: world.features };
    let W = 0, H = 0, dpr = 1, rot = [-35, -25], zoom = 1, dirty = true, selected = null, hits = [];
    let alive = true, lastInteract = 0, flying = false;

    function resize() {
      const w = Math.round(stage.getBoundingClientRect().width);
      if (!w) return;
      W = w; H = Math.round(Math.min(w, Math.max(320, innerHeight * 0.8)));
      dpr = Math.min(2.5, window.devicePixelRatio || 1);
      canvas.width = W * dpr; canvas.height = H * dpr; canvas.style.height = H + "px"; dirty = true;
    }

    function draw() {
      if (!W) return;
      g2.setTransform(dpr, 0, 0, dpr, 0, 0);
      g2.clearRect(0, 0, W, H);
      proj.translate([W / 2, H / 2]).scale(Math.min(W, H) / 2 * 0.92 * zoom).rotate(rot);
      const R = proj.scale(), cx = W / 2, cy = H / 2, center = [-rot[0], -rot[1]];
      const vis = (lon, lat) => d3.geoDistance([lon, lat], center) < 1.45;
      hits = [];

      // Atmosphäre und Ozean
      const glow = g2.createRadialGradient(cx, cy, R * 0.98, cx, cy, R * 1.1);
      glow.addColorStop(0, "rgba(110,170,255,.28)"); glow.addColorStop(1, "rgba(110,170,255,0)");
      g2.fillStyle = glow; g2.beginPath(); g2.arc(cx, cy, R * 1.1, 0, 2 * Math.PI); g2.fill();
      const ocean = g2.createRadialGradient(cx - R * 0.35, cy - R * 0.35, R * 0.1, cx, cy, R);
      ocean.addColorStop(0, COL.ocean1); ocean.addColorStop(1, COL.ocean2);
      g2.beginPath(); path(sphere); g2.fillStyle = ocean; g2.fill();
      g2.beginPath(); path(graticule); g2.strokeStyle = COL.grid; g2.lineWidth = 0.6; g2.stroke();

      // Land, Konflikt- und Wahlländer
      g2.beginPath(); path(allLand); g2.fillStyle = COL.land; g2.fill();
      // Einfärbung: Rot nur für Krieg und bewaffnete Konflikte, Violett für Unruhen und Spannungen
      for (const c of conflict.countries) {
        const war = c.level === "war";
        if (!(war ? S.conflict : S.unrest)) continue;
        const f = featById.get(c.id); if (!f) continue;
        g2.beginPath(); path(f);
        g2.fillStyle = war ? `rgba(${COL.conflict},${(0.2 + 0.4 * Math.sqrt(c.w / maxCW)).toFixed(3)})` : `rgba(${COL.unrest},0.24)`;
        g2.fill();
      }
      const elMap = elByCountry();
      if (S.elections) {
        for (const [id, e] of elMap) {
          const f = featById.get(id); if (!f) continue;
          const near = 1 - Math.min(1, e.days / Math.max(S.elDays, 30));
          g2.beginPath(); path(f); g2.fillStyle = `rgba(${COL.elect},${(0.22 + 0.4 * near).toFixed(3)})`; g2.fill();
        }
      }
      if (S.borders) { g2.beginPath(); path(allLand); g2.strokeStyle = COL.border; g2.lineWidth = 0.55; g2.stroke(); }
      if (selected && selected.country) {
        const f = featById.get(selected.country);
        if (f) { g2.beginPath(); path(f); g2.strokeStyle = "#fff"; g2.lineWidth = 1.6; g2.stroke(); }
      }
      g2.beginPath(); path(sphere); g2.strokeStyle = "rgba(160,200,255,.4)"; g2.lineWidth = 1; g2.stroke();

      const halo = (txt, x, y, color, size, align) => {
        g2.font = `600 ${size}px system-ui, sans-serif`; g2.textAlign = align || "left"; g2.lineWidth = 3;
        g2.strokeStyle = "rgba(5,10,18,.85)"; g2.strokeText(txt, x, y); g2.fillStyle = color; g2.fillText(txt, x, y);
      };

      // Ländernamen: große Länder zuerst, kleine erst beim Hineinzoomen; überlappende werden ausgelassen
      if (S.names) {
        const taken = [], R2 = R * R;
        const place = (li, force) => {
          const dist = d3.geoDistance(li.c, center);
          if (dist > 1.3) return;
          const px = li.area * R2, size = clamp(9.5 + Math.sqrt(px) / 46, 10, 17), text = nameOf(li.f);
          const [x, y] = proj(li.c), w = text.length * size * 0.58;
          const box = [x - w / 2 - 3, y - size / 2 - 2, x + w / 2 + 3, y + size / 2 + 2];
          if (!force && taken.some(b => box[0] < b[2] && box[2] > b[0] && box[1] < b[3] && box[3] > b[1])) return;
          taken.push(box);
          g2.globalAlpha = clamp((1.3 - dist) / 0.4, 0.15, 1);
          halo(text, x, y + size * 0.35, force ? "#fff" : "rgba(222,234,247,.92)", size, "center");
          g2.globalAlpha = 1;
        };
        const sel = selected && selected.country ? labelInfo.find(li => li.f.id === selected.country) : null;
        if (sel) place(sel, true);
        for (const li of labelInfo) { if (li.area * R2 < 2400) break; if (li !== sel) place(li, false); }
      }
      const isSel = (type, item) => selected && selected.type === type && selected.item === item;

      // Konfliktorte
      if (S.conflict) {
        for (const p of confShown()) {
          if (!vis(p.lon, p.lat)) continue;
          const [x, y] = proj([p.lon, p.lat]);
          const r = (4 + 18 * Math.sqrt(p.w / maxW)) * Math.min(1.7, Math.max(0.8, zoom * 0.9));
          const rg = g2.createRadialGradient(x, y, 0, x, y, r);
          rg.addColorStop(0, `rgba(${COL.conflict},.85)`); rg.addColorStop(0.45, `rgba(${COL.conflict},.35)`); rg.addColorStop(1, `rgba(${COL.conflict},0)`);
          g2.fillStyle = rg; g2.beginPath(); g2.arc(x, y, r, 0, 2 * Math.PI); g2.fill();
          g2.fillStyle = "#ffd9d4"; g2.beginPath(); g2.arc(x, y, 1.8, 0, 2 * Math.PI); g2.fill();
          if (isSel("conflict", p)) { g2.strokeStyle = "#fff"; g2.lineWidth = 1.5; g2.beginPath(); g2.arc(x, y, r * 0.7 + 3, 0, 2 * Math.PI); g2.stroke(); }
          hits.push({ x, y, r: Math.max(12, r * 0.6), type: "conflict", item: p });
        }
      }
      // Unruhen und Spannungen: kleinere violette Punkte
      if (S.unrest) {
        for (const p of unrestShown()) {
          if (!vis(p.lon, p.lat)) continue;
          const [x, y] = proj([p.lon, p.lat]);
          const r = (3 + 8 * Math.sqrt(p.w / maxU)) * Math.min(1.5, Math.max(0.8, zoom * 0.85));
          const rg = g2.createRadialGradient(x, y, 0, x, y, r);
          rg.addColorStop(0, `rgba(${COL.unrest},.75)`); rg.addColorStop(0.5, `rgba(${COL.unrest},.28)`); rg.addColorStop(1, `rgba(${COL.unrest},0)`);
          g2.fillStyle = rg; g2.beginPath(); g2.arc(x, y, r, 0, 2 * Math.PI); g2.fill();
          g2.strokeStyle = `rgba(${COL.unrest},.9)`; g2.lineWidth = 1.2; g2.beginPath(); g2.arc(x, y, Math.max(2.2, r * 0.32), 0, 2 * Math.PI); g2.stroke();
          if (isSel("unrest", p)) { g2.strokeStyle = "#fff"; g2.lineWidth = 1.5; g2.beginPath(); g2.arc(x, y, r * 0.7 + 3, 0, 2 * Math.PI); g2.stroke(); }
          hits.push({ x, y, r: Math.max(11, r * 0.6), type: "unrest", item: p });
        }
      }
      // Erdbeben: Ringe nach Stärke, neuere kräftiger; Meeresbeben (Tsunami-Flag der USGS) mit blauem Außenring
      if (S.quakes) {
        const t = nowSec();
        for (const q of quakesShown()) {
          if (!vis(q.lon, q.lat)) continue;
          const [x, y] = proj([q.lon, q.lat]);
          const age = (t - q.t) / 86400, a = age < 1 ? 0.95 : age < 3 ? 0.75 : 0.55;
          const r = (3 + Math.pow(q.mag - 4.4, 1.35) * 3.6) * Math.min(1.6, Math.max(0.8, zoom * 0.85));
          g2.beginPath(); g2.arc(x, y, r, 0, 2 * Math.PI);
          g2.fillStyle = `rgba(255,176,32,${(a * 0.22).toFixed(2)})`; g2.fill();
          g2.strokeStyle = `rgba(255,196,70,${a})`; g2.lineWidth = 1.7; g2.stroke();
          if (q.tsunami) { g2.beginPath(); g2.arc(x, y, r + 4, 0, 2 * Math.PI); g2.strokeStyle = "rgba(90,195,255,.85)"; g2.lineWidth = 1.2; g2.setLineDash([3, 3]); g2.stroke(); g2.setLineDash([]); }
          if (isSel("quake", q)) { g2.strokeStyle = "#fff"; g2.lineWidth = 1.6; g2.beginPath(); g2.arc(x, y, r + 7, 0, 2 * Math.PI); g2.stroke(); }
          if (S.labels && q.mag >= 6.3 && zoom > 0.9) halo("M " + magText(q.mag), x + r + 5, y + 4, "#ffd27a", 11);
          hits.push({ x, y, r: Math.max(11, r), type: "quake", item: q });
        }
      }
      // Wahlen: Beschriftung am Landesmittelpunkt
      if (S.elections && S.labels && zoom > 1.15) {
        for (const [id, e] of elMap) {
          const c = centroid.get(id); if (!c || !vis(c[0], c[1])) continue;
          const [x, y] = proj(c);
          halo("Wahl " + new Date(e.date + "T12:00:00").toLocaleDateString("de-DE", { day: "numeric", month: "numeric" }) + ".", x, y, "#9ccbff", 11, "center");
        }
      }
      // Meerengen
      if (S.chokes) {
        for (const c of cps) {
          if (!vis(c.lon, c.lat)) continue;
          const [x, y] = proj([c.lon, c.lat]);
          const col = LEVEL[c.level][1], s = c.level ? 7 : 5;
          g2.beginPath(); g2.moveTo(x, y - s); g2.lineTo(x + s, y); g2.lineTo(x, y + s); g2.lineTo(x - s, y); g2.closePath();
          g2.fillStyle = col; g2.fill(); g2.strokeStyle = "#0a1420"; g2.lineWidth = 1.5; g2.stroke();
          if (isSel("chokepoint", c)) { g2.strokeStyle = "#fff"; g2.lineWidth = 1.5; g2.beginPath(); g2.arc(x, y, s + 5, 0, 2 * Math.PI); g2.stroke(); }
          if (S.labels && (zoom > 1.25 || c.level)) halo(c.name.split(" / ")[0], x + s + 4, y + 4, c.level ? "#fff" : "#bcd0e6", 11);
          hits.push({ x, y, r: 16, type: "chokepoint", item: c });
        }
      }
      // Flugzeugträger
      if (S.carriers) {
        for (const s of carriers) {
          if (!vis(s.lon, s.lat)) continue;
          const [x, y] = proj([s.lon, s.lat]);
          g2.beginPath(); g2.moveTo(x, y - 8); g2.lineTo(x + 6, y + 6); g2.lineTo(x - 6, y + 6); g2.closePath();
          g2.fillStyle = "#fff"; g2.fill(); g2.strokeStyle = "#0a1420"; g2.lineWidth = 1.5; g2.stroke();
          if (isSel("carrier", s)) { g2.strokeStyle = "#fff"; g2.lineWidth = 1.5; g2.beginPath(); g2.arc(x, y, 13, 0, 2 * Math.PI); g2.stroke(); }
          if (S.labels && zoom > 0.9) halo(s.hull, x + 10, y + 4, "#fff", 11);
          hits.push({ x, y, r: 16, type: "carrier", item: s });
        }
      }
    }

    // ---------- Bedienung
    const pointers = new Map();
    let pinch = null, down = null;
    const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
    const local = (e) => { const r = canvas.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };

    canvas.addEventListener("pointerdown", (e) => {
      canvas.setPointerCapture(e.pointerId);
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      lastInteract = performance.now(); flying = false;
      if (pointers.size === 1) down = { x: e.clientX, y: e.clientY, t: performance.now(), moved: 0 };
      if (pointers.size === 2) { const [a, b] = [...pointers.values()]; pinch = { d: dist(a, b), z: zoom }; down = null; }
    });
    canvas.addEventListener("pointermove", (e) => {
      const p = pointers.get(e.pointerId);
      if (!p) { hover(e); return; }
      const dx = e.clientX - p.x, dy = e.clientY - p.y;
      p.x = e.clientX; p.y = e.clientY; lastInteract = performance.now();
      if (pointers.size === 1) {
        if (down) down.moved += Math.abs(dx) + Math.abs(dy);
        const k = 0.28 / zoom;
        rot = [rot[0] + dx * k, clamp(rot[1] - dy * k, -88, 88)];
      } else if (pinch && pointers.size === 2) {
        const [a, b] = [...pointers.values()];
        zoom = clamp(pinch.z * dist(a, b) / pinch.d, 0.8, 9);
      }
      dirty = true;
    });
    const up = (e) => {
      pointers.delete(e.pointerId);
      if (pointers.size < 2) pinch = null;
      if (down && e.type === "pointerup" && down.moved < 8 && performance.now() - down.t < 600) tap(...local(e));
      if (!pointers.size) down = null;
    };
    canvas.addEventListener("pointerup", up);
    canvas.addEventListener("pointercancel", up);
    canvas.addEventListener("wheel", (e) => { e.preventDefault(); zoomTo(zoom * (e.deltaY < 0 ? 1.15 : 1 / 1.15)); lastInteract = performance.now(); }, { passive: false });

    function zoomTo(z) { zoom = clamp(z, 0.8, 9); dirty = true; }
    function nearest(x, y) {
      let best = null, bd = 1e9;
      for (const hit of hits) { const d = Math.hypot(hit.x - x, hit.y - y); if (d <= hit.r + 6 && d < bd) { best = hit; bd = d; } }
      return best;
    }
    function hover(e) {
      if (e.pointerType === "touch") return;
      const [x, y] = local(e), hit = nearest(x, y);
      canvas.style.cursor = hit ? "pointer" : "grab";
      if (hit) {
        tip.textContent = hit.type === "unrest" ? `Unruhen: ${hit.item.name}` : hit.type === "quake" ? `M ${magText(hit.item.mag)} · ${hit.item.place}`
          : hit.type === "carrier" ? hit.item.name + " (" + hit.item.hull + ")" : hit.item.name;
        tip.style.left = x + 12 + "px"; tip.style.top = y + 12 + "px"; tip.classList.add("on");
      } else tip.classList.remove("on");
    }
    function tap(x, y) {
      const hit = nearest(x, y);
      if (hit) { select(hit.type, hit.item); return; }
      const ll = proj.invert([x, y]);
      if (!ll) return;
      const f = world.features.find(f => d3.geoContains(f, ll));
      if (f) select("country", f);
    }

    function flyTo(lon, lat, z) {
      const r0 = rot.slice(), z0 = zoom, z1 = z || Math.max(zoom, 1.7);
      const dl = ((-lon - r0[0] + 540) % 360) - 180, dp = clamp(-lat, -85, 85) - r0[1];
      const t0 = performance.now(); flying = true;
      (function step(now) {
        if (!flying) return;
        const t = Math.min(1, (now - t0) / 900), e = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
        rot = [r0[0] + dl * e, r0[1] + dp * e]; zoom = z0 + (z1 - z0) * e; dirty = true;
        if (t < 1) requestAnimationFrame(step); else flying = false;
      })(t0);
    }

    // ---------- Infofeld und Listen
    const num = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 1 });
    const pct = (v) => v == null ? "–" : (v > 0 ? "+" : "") + num.format(v) + " %";
    const link = (t, u) => h("a", { href: u }, t);
    const introNode = () => h("div", {}, h("h3", {}, "Lagebild"), h("p", { class: "note" }, "Tippe auf einen Punkt, ein Land oder einen Eintrag in den Listen. Ziehen dreht die Erde, zwei Finger oder das Mausrad zoomen."));
    function spark(series) {
      const NS = "http://www.w3.org/2000/svg", w = 220, ht = 44, svg = document.createElementNS(NS, "svg");
      svg.setAttribute("viewBox", `0 0 ${w} ${ht}`); svg.setAttribute("class", "gspark");
      const max = Math.max(...series, 1), pl = document.createElementNS(NS, "polyline");
      pl.setAttribute("points", series.map((v, i) => `${(i / (series.length - 1) * w).toFixed(1)},${(ht - 2 - (v / max) * (ht - 4)).toFixed(1)}`).join(" "));
      pl.setAttribute("fill", "none"); pl.setAttribute("stroke", "currentColor"); pl.setAttribute("stroke-width", "1.6");
      svg.append(pl); return svg;
    }

    // Schlagzeilen zum Land: erst die gezielt zum Konflikt gesuchten, sonst die passenden aus den gesammelten Meldungen
    function newsBlock(conflictNews, stories, title) {
      const rows = conflictNews
        ? conflictNews.map(n => h("p", { class: "nl" }, link(n.title, n.url), n.source && h("small", {}, " · " + n.source)))
        : stories.map(s => h("p", { class: "nl" }, link(s.title, s.url), h("small", {}, " · " + (s.sources[0] ? s.sources[0].name : ""))));
      if (!rows.length) return null;
      return h("div", {}, h("h4", {}, title), rows,
        conflictNews ? h("p", { class: "note" }, "Hinweis auf den Hintergrund, kein geprüfter Befund. Die Schlagzeilen stammen aus einer Nachrichtensuche zu Krieg, Angriff und Militär.") : null);
    }

    function select(type, item) {
      selected = { type, item, country: type === "country" ? item.id : null };
      let lon, lat, node;
      if (type === "conflict") {
        lon = item.lon; lat = item.lat;
        const f = item.cid && featById.get(item.cid), cc = item.cid && confCountry.get(item.cid);
        const cname = f ? nameOf(f) : "";
        node = h("div", {}, h("h3", {}, item.name), h("div", { class: "gtag bad" }, "Kampfhandlungen laut Nachrichten"),
          h("p", {}, `${item.n} Ereignisse mit ${item.w} Medienmeldungen in den letzten 2 Tagen. Das ist die Zahl der Meldungen, kein Maß für Opfer oder Ausmaß.`),
          f && newsBlock(cc && cc.news && cc.news.length ? cc.news : null, storiesFor(f), `Anlass: aktuelle Meldungen zu ${cname}`),
          h("p", { class: "note" }, "Maschinell aus Nachrichten gewonnen (GDELT). Orte können falsch zugeordnet sein. Die Schlagzeilen gehören zum ganzen Land, nicht nur zu diesem Ort."));
      } else if (type === "unrest") {
        lon = item.lon; lat = item.lat;
        const f = item.cid && featById.get(item.cid), cc = item.cid && confCountry.get(item.cid);
        node = h("div", {}, h("h3", {}, item.name), h("div", { class: "gtag", style: `background:rgb(${COL.unrest});color:#14061f` }, "Unruhen & Spannungen"),
          h("p", {}, `${item.n} Ereignisse (Proteste, Krawalle, Gewalt) mit ${item.w} Medienmeldungen in den letzten 2 Tagen.`),
          f && newsBlock(cc && cc.news && cc.news.length ? cc.news : null, storiesFor(f), `Hintergrund: aktuelle Meldungen zu ${nameOf(f)}`),
          h("p", { class: "note" }, "Maschinell aus Nachrichten gewonnen (GDELT). Die Einstufung ist eine Schätzung, kein Urteil über die Lage."));
      } else if (type === "chokepoint") {
        lon = item.lon; lat = item.lat;
        const [lvl, col] = LEVEL[item.level];
        node = h("div", {}, h("h3", {}, item.name), h("div", { class: "gtag", style: `background:${col};color:#06121e` }, lvl),
          h("p", {}, `Schiffe pro Tag (Schnitt der letzten 7 Tage): ${num.format(item.last7)}`, h("br"),
            item.base != null ? `${item.base_label}: ${num.format(item.base)} (${pct(item.pct)})` : "Kein Vergleichswert"),
          h("div", { class: "gsp", style: `color:${col}` }, spark(item.history), h("small", {}, "letzte 60 Tage, Stand " + new Date(item.date + "T12:00:00").toLocaleDateString("de-DE", { day: "numeric", month: "short" }))),
          item.news.length ? h("div", {}, h("h4", {}, "Meldungen"), item.news.map(n => h("p", { class: "nl" }, link(n.title, n.url)))) : h("p", { class: "note" }, "Keine aktuelle Meldung in den gesammelten Nachrichten."),
          h("p", { class: "note" }, "Zahlen: IMF PortWatch (Satelliten-Schiffsortung), Verzögerung etwa 3 Tage. Die Einstufung ist eine Schätzung aus dem Verkehr und den Nachrichten, keine amtliche Sperrung."));
      } else if (type === "quake") {
        lon = item.lon; lat = item.lat;
        const when = new Date(item.t * 1000), hours = Math.round((nowSec() - item.t) / 3600);
        const depthText = item.depth < 70 ? "flach" : item.depth < 300 ? "mittlere Tiefe" : "tief";
        node = h("div", {}, h("h3", {}, `Erdbeben M ${magText(item.mag)}`), h("div", { class: "gtag", style: "background:#ffb020;color:#1a1200" }, item.place),
          item.tsunami ? h("div", { class: "gtag", style: "background:#3a9fd6;color:#fff;margin-left:6px" }, "Meeresgebiet") : null,
          h("p", {}, `${when.toLocaleString("de-DE", { weekday: "long", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" })} Uhr (vor ${hours < 48 ? hours + " Std." : Math.round(hours / 24) + " Tagen"})`, h("br"),
            `Tiefe: ${item.depth} km (${depthText}). Je flacher, desto stärker die Erschütterung an der Oberfläche.`,
            item.felt ? h("span", {}, h("br"), `${item.felt} Wahrnehmungsmeldungen von Menschen`) : null),
          item.tsunami ? h("p", { class: "note" }, "Das Flag „Meeresgebiet“ bedeutet nur, dass die Tsunami-Warnzentren informiert werden. Ein Tsunami ist damit nicht bestätigt.") : null,
          h("p", {}, link("Details bei der USGS", item.url)),
          h("p", { class: "note" }, "Quelle: USGS, alle Beben ab Stärke 4,5 der letzten 7 Tage. Stärke und Ort sind anfangs vorläufig und werden oft korrigiert."));
      } else if (type === "carrier") {
        lon = item.lon; lat = item.lat;
        const c = geo.carriers;
        node = h("div", {}, h("h3", {}, item.name), h("div", { class: "gtag" }, item.hull),
          h("p", {}, "Region: " + item.where), h("p", { class: "note" }, `Position nur grob (Region), Stand des Trackers: ${c.as_of}. Die Marine veröffentlicht keine genauen Positionen.`),
          h("p", {}, link("USNI Fleet Tracker öffnen", c.url)));
      } else {
        const f = item, c = confCountry.get(f.id), e = elByCountry().get(f.id) || elections.find(x => x.id === f.id);
        const ll = centroid.get(f.id); lon = ll[0]; lat = ll[1];
        node = h("div", {}, h("h3", {}, nameOf(f)),
          c && c.level === "war" ? [h("div", { class: "gtag bad" }, "Krieg / bewaffneter Konflikt"),
            h("p", {}, `${c.n} Kampfereignisse mit ${c.w} Medienmeldungen in den letzten 2 Tagen, davon ${c.heavy} schwere Gefechte (Schusswaffen, Artillerie, Luftangriffe).`)]
            : c ? [h("div", { class: "gtag", style: `background:rgb(${COL.unrest});color:#14061f` }, "Unruhen & Spannungen"),
              h("p", {}, `${c.share} % der Ereignisse sind Gewalt oder Zwang${c.protests ? `, ${c.protests} Proteste` : ""}${c.riots ? `, ${c.riots} Krawalle` : ""} in den letzten 2 Tagen.`)]
            : h("p", { class: "note" }, "Keine auffälligen Kampfhandlungen oder Unruhen in den Daten."),
          newsBlock(c && c.news && c.news.length ? c.news : null, storiesFor(f), c ? (c.level === "war" ? "Anlass: aktuelle Meldungen zum Konflikt" : "Hintergrund: aktuelle Meldungen") : "Meldungen zu diesem Land"),
          e ? h("p", {}, h("b", {}, "Wahl: "), `${new Date(e.date + "T12:00:00").toLocaleDateString("de-DE", { weekday: "long", day: "numeric", month: "long", year: "numeric" })} (in ${e.days} Tagen), ${e.what} `, link("Wikipedia", e.url)) : h("p", { class: "note" }, "Keine Wahl in den nächsten 12 Monaten im Kalender."));
        lon = ll[0]; lat = ll[1];
      }
      info.replaceChildren(node);
      flyTo(lon, lat, type === "country" ? Math.max(zoom, 1.5) : Math.max(zoom, 2));
      info.scrollIntoView({ block: "nearest", behavior: "smooth" });
      dirty = true;
    }

    function renderLists() {
      const row = (label, sub, color, onclick) => h("button", { class: "grow", onclick },
        color && h("i", { style: `background:${color}` }), h("span", {}, label, sub && h("small", {}, sub)));
      const warList = warCountries.filter(c => c.w >= maxCW * (S.minConf / 100) ** 2).slice(0, 8);
      const unrestList = unrestCountries.slice(0, 8);
      const sorted = cps.slice().sort((a, b) => b.level - a.level || (a.pct ?? 0) - (b.pct ?? 0));
      const els = elShown().slice(0, 10);
      const qs = quakesShown().sort((a, b) => b.mag - a.mag).slice(0, 8);
      lists.replaceChildren(
        S.conflict && h("div", {}, h("h3", {}, "Kriege & Kampfhandlungen"),
          warList.length ? warList.map(c => row(c.name_de, `${c.n} Kampfereignisse, ${c.w} Meldungen`, `rgb(${COL.conflict})`, () => select("country", featById.get(c.id)))) : h("p", { class: "note" }, "Nichts über der Schwelle.")),
        S.unrest && h("div", {}, h("h3", {}, "Unruhen & Spannungen"),
          unrestList.length ? unrestList.map(c => row(c.name_de, c.protests ? `${c.protests} Proteste, ${c.share} % Gewaltanteil` : `${c.share} % Gewaltanteil`, `rgb(${COL.unrest})`, () => select("country", featById.get(c.id)))) : h("p", { class: "note" }, "Nichts auffällig.")),
        S.chokes && h("div", {}, h("h3", {}, "Meerengen"),
          sorted.map(c => row(c.name, c.pct == null ? "" : `Verkehr ${pct(c.pct)} ggü. ${c.base_label}`, LEVEL[c.level][1], () => select("chokepoint", c)))),
        S.elections && h("div", {}, h("h3", {}, "Wahlen"),
          els.length ? els.map(e => row(e.name_de, `${new Date(e.date + "T12:00:00").toLocaleDateString("de-DE", { day: "numeric", month: "short" })}, ${e.what}`, `rgb(${COL.elect})`, () => select("country", featById.get(e.id)))) : h("p", { class: "note" }, "Keine Wahl im gewählten Zeitraum.")),
        S.quakes && h("div", {}, h("h3", {}, "Erdbeben"),
          qs.length ? qs.map(q => row(`M ${magText(q.mag)} · ${q.place}`, `vor ${Math.round((nowSec() - q.t) / 3600) < 48 ? Math.round((nowSec() - q.t) / 3600) + " Std." : Math.round((nowSec() - q.t) / 86400) + " Tagen"}, ${q.depth} km tief`, "#ffb020", () => select("quake", q)))
            : h("p", { class: "note" }, "Keine Beben mit diesen Einstellungen.")),
        S.carriers && geo.carriers && h("div", {}, h("h3", {}, "Flugzeugträger"),
          carriers.map(s => row(`${s.name} (${s.hull})`, s.where, "#fff", () => select("carrier", s))),
          (geo.carriers.headlines || []).length ? h("div", {}, h("h4", {}, "Aktuelle Meldungen"), geo.carriers.headlines.slice(0, 4).map(n => h("p", { class: "nl" }, link(n.title, n.url)))) : null));
      dirty = true;
    }

    const notes = Object.entries(geo.notes || {}).map(([k, v]) => `${k}: ${v}`).join("; ");
    const foot = h("p", { class: "note gfoot" },
      "Quellen: GDELT (Konflikte, maschinell aus Nachrichten, Fehler möglich), IMF PortWatch (Schiffsverkehr), Wikipedia (Wahlen), USNI News Fleet Tracker (wöchentlich, grobe Positionen), Natural Earth (Grenzen, vereinfacht, gemeinfrei). Das ist eine Informationsübersicht und keine amtliche Lagebeurteilung."
      + (notes ? " Hinweis: " + notes : ""));

    root.replaceChildren(h("div", { class: "globe-wrap" },
      stage, h("div", { class: "gside" }, info, controls, lists), foot));
    info.replaceChildren(introNode());
    renderLists();

    // ---------- Schleife
    let last = performance.now();
    function frame(now) {
      if (!alive || !root.isConnected) { alive = false; return; }
      const dt = Math.min(0.1, (now - last) / 1000); last = now;
      if (!document.hidden) {
        if (S.spin > 0 && !flying && !selected && !pointers.size && now - lastInteract > 3500) { rot = [rot[0] + S.spin * dt, rot[1]]; dirty = true; }
        if (dirty) { dirty = false; draw(); }
      }
      requestAnimationFrame(frame);
    }
    const ro = new ResizeObserver(resize); ro.observe(stage);
    resize();
    requestAnimationFrame(frame);
    const api = { destroy() { alive = false; ro.disconnect(); }, state: () => ({ zoom, rot, W, H, selected: !!selected }) };
    window.MegoGlobe.current = api;
    return api;
  }

  window.MegoGlobe = { loadAssets, mount };
})();
