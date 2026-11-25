/* ================= Alpha GIS Platform — app.js =================
   الإصدار 1.3: مفتاح إظهار/إخفاء أسماء المدارس (مخفية افتراضيًا)، أيقونات متجهة بالكامل،
   تحميل Chart.js عند الحاجة، وتحديثات أخفّ للواجهة. نفس الوظائف السابقة، بعد إعادة تنظيمها:
   - محرك طبقات واحد (بدل نسختين متطابقتين) مع تحميل متوازٍ وبلا طلبات مكررة
   - ترتيب رسم صحيح (الرسترات تحت المتجهات، وزر «إلى الأمام» يعمل)
   - لا إعادة رسم لكل الشجرة عند إظهار طبقة، ولا تحميل لما لا يراه المستخدم (الجدول/المؤشرات)
   - كل نص قادم من البيانات يمر عبر esc() */
"use strict";

/* ------------------------------------------------ state */
const S = {
  cat: null, lang: LANG, city: "nasr", tab: "layers",
  map: null, basemap: null,
  byId: new Map(),            // id -> layer meta (متجهة أو رستر)
  rasterIds: new Set(),
  layers: new Map(),          // id -> {meta, llayer, on}
  dataP: new Map(),           // id -> Promise<GeoJSON> (ذاكرة مؤقتة + إزالة التكرار)
  apiCache: new Map(),        // نتائج POST المتكررة (لوحة المؤشرات)
  k: new Map(),               // id -> شفافية يضبطها المستخدم
  opOpen: new Set(),          // الطبقات التي أُظهر لها منزلق الشفافية
  closedGroups: new Set(),
  activeMap: null,
  analysisLayer: null, anSeq: 0,
  results: { nasr: {}, ps: {} },   // نتيجة التحليل الأخيرة لكل مدينة: طبقة + شارة + مؤشرات + بطاقة
  stats: null, dashKey: null,
  measure: null, tool: null, identify: false,
  edit: { layer: null, mode: null, log: [], pick: null },
  charts: {},
  showNames: false,           // أسماء المدارس مخفية عند كل تحميل للصفحة
};

/* ------------------------------------------------ أسماء المدارس
   الحقول التي تحمل اسم مدرسة. تُخفى من الخريطة والنوافذ والجدول ونتائج «أقرب مدرسة»
   حتى يفعّلها المستخدم؛ التصدير يبقى كاملًا لأنه طلب صريح للبيانات. */
const NAME_FIELDS = new Set(["name_ar", "nearest_name"]);
const nameHidden = (field) => NAME_FIELDS.has(field) && !S.showNames;

const $ = (s, r) => (r || document).querySelector(s);
const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const title = (m) => (S.lang === "ar" ? m.title_ar : m.title_en) || m.id;
const num = (v, d) => (v == null || v !== v ? "—" :
  Number(v).toLocaleString(S.lang === "ar" ? "ar-EG" : "en-US", { maximumFractionDigits: d == null ? 1 : d }));
const cityName = (c) => tt(S.cat.cities[c]);

async function api(path, opt) {
  let r;
  try { r = await fetch(path, opt); }
  catch (e) { throw new Error(T("تعذّر الاتصال بالخادم. تأكد أنه يعمل ثم أعد المحاولة.", "Couldn't reach the server. Check that it is running and try again.")); }
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (e) {}
    throw new Error(msg);
  }
  return r.json();
}
const post = (p, body) => api(p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
function postCached(p, body) {
  const key = p + JSON.stringify(body);
  if (!S.apiCache.has(key)) {
    const pr = post(p, body);
    pr.catch(() => S.apiCache.delete(key));
    S.apiCache.set(key, pr);
  }
  return S.apiCache.get(key);
}

let toastTimer = null;
function toast(msg, kind) {
  const el = $("#toast");
  el.textContent = msg;
  el.className = "show" + (kind ? " " + kind : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.className = ""), 2800);
}
/* شريط تقدّم رفيع بدل حجب الشاشة كلها؛ العدّاد يمنع إخفاءه مبكرًا عند تداخل الطلبات */
let busyCount = 0;
function loading(on) {
  busyCount = Math.max(0, busyCount + (on ? 1 : -1));
  $("#progress").hidden = busyCount === 0;
}
const raf = (fn) => requestAnimationFrame(fn);
const idle = (fn) => (window.requestIdleCallback ? requestIdleCallback(fn, { timeout: 2500 }) : setTimeout(fn, 600));
function debounce(fn, ms) { let h; return (...a) => { clearTimeout(h); h = setTimeout(() => fn(...a), ms); }; }
const isNarrow = () => window.matchMedia("(max-width:820px)").matches;
function revealMap() { if (isNarrow()) $("#panel").classList.add("collapsed"); }
function setPressed(group, test) {
  $$("button", group).forEach(b => { const on = !!test(b); b.classList.toggle("active", on); b.setAttribute("aria-pressed", on); });
}
const ic = (name) => `<svg class="ic"><use href="#i-${name}"/></svg>`;

/* ------------------------------------------------ i18n */
function applyI18n() {
  document.documentElement.lang = S.lang;
  document.documentElement.dir = S.lang === "ar" ? "rtl" : "ltr";
  $$("[data-i18n]").forEach(el => { el.innerHTML = t(el.dataset.i18n); });
  $$("[data-i18n-ph]").forEach(el => { el.placeholder = t(el.dataset.i18nPh); });
  setPressed($("#langSeg"), b => b.dataset.lang === S.lang);
  const cb = $$("#citySeg button");
  cb[0].textContent = T("مدينة نصر", "Nasr City");
  cb[1].textContent = T("بورسعيد", "Port Said");
  placeZoomControl();
  updateWalk();
  updateNamesButton();
  if (!S.cat) return;
  drawLayerTree();
  renderMapList();
  renderTableSel();
  renderEditSel();
  renderLog();
  if (!hasResult()) showAnalysisEmpty();
  if (S.activeMap) showPresetChrome(S.cat.maps.find(m => m.id === S.activeMap));
  S.dashKey = null; renderDashboard();
  renderLegend();
}

/* ------------------------------------------------ map init */
const BASEMAPS = {
  osm: { url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png", opt: { maxZoom: 19, attribution: "© OpenStreetMap" } },
  sat: { url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", opt: { maxZoom: 18, attribution: "Esri" } },
  topo: { url: "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", opt: { maxZoom: 17, attribution: "© OpenTopoMap" } },
  none: null,
};

function initMap() {
  S.map = L.map("map", {
    zoomControl: false, attributionControl: false,
    renderer: L.canvas({ padding: 0.5 }),      // هامش أكبر = إعادة رسم أقل أثناء السحب
    zoomSnap: 0.5, wheelPxPerZoomLevel: 90,
  }).setView([30.06, 31.35], 12);
  // الرسترات في طبقة خاصة تحت المتجهات، فلا تغطي المدارس والحدود
  S.map.createPane("rasters").style.zIndex = 395;
  // أيقونات SVG للتكبير والتصغير (بدل رموز النص) وعلامة افتراضية متجهة بدل صور PNG
  S.zoomCtl = L.control.zoom({ position: "bottomleft", zoomInText: ic("plus"), zoomOutText: ic("minus") }).addTo(S.map);
  L.control.attribution({ prefix: false, position: "bottomright" }).addTo(S.map);
  L.Marker.prototype.options.icon = schoolIcon("#12355B");
  setBasemap("osm");
  const coords = $("#coords");
  let pending = null;                                  // آخر موضع للمؤشر؛ يُرسم مرة واحدة لكل إطار
  S.map.on("mousemove", e => {
    const first = !pending; pending = e.latlng;
    if (first) raf(() => { coords.textContent = pending.lat.toFixed(5) + ", " + pending.lng.toFixed(5); pending = null; });
  });
  const onZoom = () => {
    const z = S.map.getZoom();
    $("#scaleNote").textContent = "zoom " + z;
    S.map.getContainer().classList.toggle("labels-low", z < 13);   // لا تسميات للشياخات عند التصغير
  };
  S.map.on("zoomend", onZoom); onZoom();
  placeZoomControl();
}
/* أزرار التكبير في الركن المقابل لمفتاح الخريطة حتى لا يتداخلا في أي اتجاه */
function placeZoomControl() {
  if (!S.zoomCtl) return;
  S.zoomCtl.setPosition(S.lang === "ar" ? "bottomleft" : "bottomright");
  const c = S.zoomCtl;
  if (c._zoomInButton) { c._zoomInButton.title = c._zoomInButton.ariaLabel = t("zoom_in"); }
  if (c._zoomOutButton) { c._zoomOutButton.title = c._zoomOutButton.ariaLabel = t("zoom_out"); }
}
function setBasemap(key) {
  if (S.basemap) { S.map.removeLayer(S.basemap); S.basemap = null; }
  const b = BASEMAPS[key];
  if (b) { S.basemap = L.tileLayer(b.url, Object.assign({ keepBuffer: 3 }, b.opt)).addTo(S.map); S.basemap.setZIndex(0); }
}

/* ------------------------------------------------ styling (ألوان QGIS كما هي) */
function colorOf(style, props) {
  if (style.type === "graduated" || style.type === "graduated_point" || style.type === "graduated_line") {
    const v = props[style.field];
    if (v == null) return "#cccccc";
    for (const c of style.classes) if (v >= c[0] && v < c[1]) return c[4];
    return "#cccccc";
  }
  if (style.type === "categorized") return style.palette[String(props[style.field])] || style.default || "#999999";
  return style.color || style.fill || "#3388ff";
}
const userK = (meta) => (S.k.has(meta.id) ? S.k.get(meta.id) : (isRaster(meta) ? (meta.opacity != null ? meta.opacity : 0.75) : 1));
const isRaster = (meta) => S.rasterIds.has(meta.id);

function featStyle(meta) {
  const st = meta.style || {};
  const k = userK(meta);
  const base = meta.opacity != null ? meta.opacity : 1;
  return function (feature) {
    const p = (feature && feature.properties) || {};
    if (meta.geom === "point" || st.type === "point" || st.type === "graduated_point") {
      return { fillColor: st.type === "graduated_point" ? colorOf(st, p) : (st.color || "#b3121b"),
               color: st.stroke || "#fff", weight: st.weight || 1, opacity: k, fillOpacity: base * k };
    }
    if (st.type === "graduated_line") return { color: colorOf(st, p), weight: st.weight || 2, opacity: base * k };
    if (meta.geom === "line" || st.type === "line") {
      const o = { color: st.color, weight: st.weight || 1, opacity: (st.opacity != null ? st.opacity : 1) * k, fill: false };
      if (st.dash) o.dashArray = st.dash;
      if (st.fill && st.fill !== "transparent") { o.fill = true; o.fillColor = st.fill; o.fillOpacity = (st.fillOpacity != null ? st.fillOpacity : 0.2) * k; }
      return o;
    }
    if (st.type === "graduated" || st.type === "categorized") {
      return { fillColor: colorOf(st, p), color: st.stroke || "#fff", weight: st.weight || (st.type === "graduated" ? 0.6 : 0.5),
               opacity: k, fillOpacity: base * k, fill: true };
    }
    const o = { fillColor: st.fill || "#3388ff", fillOpacity: (st.fillOpacity != null ? st.fillOpacity : 0.2) * k,
                color: st.stroke || "#333", weight: st.weight || 1, opacity: k };
    if (st.dash) o.dashArray = st.dash;
    return o;
  };
}
/* دبوس المدرسة: شكل الخرائط العالمية (قطرة بلون واحد، حدّ أبيض، ظل ناعم، قبعة تخرّج بيضاء) */
const SCHOOLS_ID = "schools_32636";
const isSchoolLayer = (m) => m && m.id === SCHOOLS_ID;
function schoolPinSvg(color, w, h, cls) {
  const c = esc(color || "#B3121B");
  return `<svg class="${cls || ""}" viewBox="0 0 32 40" width="${w}" height="${h}" aria-hidden="true">
    <path d="M16 38.5S29 25.6 29 15.5a13 13 0 0 0-26 0C3 25.6 16 38.5 16 38.5Z" fill="${c}" stroke="#fff" stroke-width="2" stroke-linejoin="round"/>
    <g transform="translate(8.6 8.2) scale(.6)" fill="#fff"><path d="M5 13.18v4L12 21l7-3.82v-4L12 17l-7-3.82zM12 3 1 9l11 6 9-4.91V17h2V9L12 3z"/></g></svg>`;
}
const schoolIcon = (color) => L.divIcon({ className: "", iconSize: [32, 40], iconAnchor: [16, 38], popupAnchor: [0, -34], tooltipAnchor: [0, -2],
  html: schoolPinSvg(color, 32, 40, "school-pin") });
const STAR_PATH = "M12 1.6l3.1 6.9 7.4.7-5.6 5 1.7 7.3L12 17.7 5.4 21.5l1.7-7.3-5.6-5 7.4-.7z";
const starSvg = (color, size, cls) => `<svg class="${cls || ""}" viewBox="0 0 24 24" width="${size}" height="${size}" aria-hidden="true"><path d="${STAR_PATH}" fill="${esc(color)}" stroke="#fff" stroke-width="1.2" stroke-linejoin="round"/></svg>`;
function starIcon(color) {
  return L.divIcon({ className: "", iconSize: [26, 26], iconAnchor: [13, 13], html: starSvg(color, 26) });
}
const maskedValue = () => `<span class="masked">${ic("lock")}${t("names_masked")}</span>`;
function propsTable(props, fields) {
  const keys = fields && fields.length ? fields.filter(f => f in props) : Object.keys(props).slice(0, 8);
  return "<table>" + keys.map(f => {
    let v = props[f];
    v = nameHidden(f) ? maskedValue() : v == null ? "—" : typeof v === "number" ? num(v, 2) : esc(v);
    return `<tr><td>${esc(f)}</td><td>${v}</td></tr>`;
  }).join("") + "</table>";
}
const popupHtml = (meta, props) => `<div><b>${esc(title(meta))}</b>${propsTable(props, meta.popup_fields)}</div>`;

/* ------------------------------------------------ محرك الطبقات */
const getRec = (meta) => S.layers.get(meta.id);
const isOn = (meta) => { const r = getRec(meta); return !!(r && r.on); };

function getFc(meta) {
  let p = S.dataP.get(meta.id);
  if (!p) {
    const src = meta.source ? "?source=" + encodeURIComponent(meta.source) : "";
    p = api("/api/layers/" + encodeURIComponent(meta.id) + src);
    p.catch(() => S.dataP.delete(meta.id));
    S.dataP.set(meta.id, p);
  }
  return p;
}
const rasterP = new Map();
function getRasterInfo(meta) {
  if (!rasterP.has(meta.id)) {
    const p = api("/api/raster/" + encodeURIComponent(meta.id));
    p.catch(() => rasterP.delete(meta.id));
    rasterP.set(meta.id, p);
  }
  return rasterP.get(meta.id);
}

function buildVector(meta, fc) {
  const st = meta.style || {};
  const lbl = st.label && st.label.field;
  const school = isSchoolLayer(meta);
  // مدارس المدينة المختارة فقط (إن كانت البيانات تحمل حقل المدينة)
  const hasCity = school && fc.features.some(f => f.properties && f.properties.city);
  const layer = L.geoJSON(fc, {
    style: featStyle(meta),
    filter: hasCity ? (f => f.properties.city === cityPlaceName()) : undefined,
    pointToLayer: (f, ll) => {
      // المدارس دبابيس DOM في طبقة العلامات (فوق كل canvas: الطرق والتحليلات) وبأعلى zIndexOffset
      if (school) return L.marker(ll, { icon: schoolIcon(st.color), keyboard: false, riseOnHover: true, zIndexOffset: 1000 });
      if (st.type === "star") return L.marker(ll, { icon: starIcon(st.color), keyboard: false, zIndexOffset: 500 });
      const grad = st.type === "graduated_point";
      return L.circleMarker(ll, { radius: grad ? (st.radius || 8) : (st.radius || 6), weight: st.weight || 1 });
    },
    onEachFeature: lbl ? (f, l) => {
      const v = (f.properties || {})[lbl];
      if (v == null) return;
      l.__label = String(v);                                  // الاسم محفوظ هنا ولا يُرسم إلا عند السماح
      if (!nameHidden(lbl)) bindLabel(meta, l);
    } : undefined,
  });
  // مستمع واحد على المجموعة بدل نافذة منبثقة لكل معلم — أخف بكثير مع آلاف المباني
  layer.on("click", e => onFeatureClick(meta, e));
  return layer;
}
function bindLabel(meta, l) {
  const pin = l instanceof L.Marker;
  l.bindTooltip(l.__label, { permanent: true, direction: pin ? "bottom" : "center", offset: pin ? [0, 4] : [0, 0], opacity: 1,
    className: meta.geom === "point" ? "school-label" : "zone-label" });
}
function onFeatureClick(meta, e) {
  if (S.tool) return;                       // أثناء القياس/الرسم/التحرير لا نوافذ
  const l = e.layer, f = l && l.feature;
  if (!f) return;
  if (S.identify) showFeatureModal(meta, f, l);
  else L.popup({ maxWidth: 320 }).setLatLng(e.latlng).setContent(popupHtml(meta, f.properties || {})).openOn(S.map);
}
function openFeaturePopup(meta, l) {
  const ll = l.getLatLng ? l.getLatLng() : l.getBounds().getCenter();
  L.popup({ maxWidth: 320 }).setLatLng(ll).setContent(popupHtml(meta, (l.feature && l.feature.properties) || {})).openOn(S.map);
}

/* ينشئ طبقة Leaflet عند أول طلب (وسيطًا واحدًا لكل الطلبات المتزامنة) */
const building = new Map();
function ensureLayer(meta) {
  const rec = getRec(meta);
  if (rec && rec.llayer) return Promise.resolve(rec);
  if (building.has(meta.id)) return building.get(meta.id);
  const p = (async () => {
    let llayer;
    if (isRaster(meta)) {
      const d = await getRasterInfo(meta);
      llayer = L.imageOverlay(d.png, d.bounds, { opacity: userK(meta), interactive: false, pane: "rasters" });
    } else {
      llayer = buildVector(meta, await getFc(meta));
    }
    const r = getRec(meta) || { meta, on: false };
    r.llayer = llayer; r.meta = meta;
    S.layers.set(meta.id, r);
    return r;
  })();
  building.set(meta.id, p);
  p.finally(() => building.delete(meta.id));
  return p;
}

/* إظهار: مع استدعاء واحد لإعادة الترتيب بعد كل دفعة */
async function showLayers(metas, opts) {
  opts = opts || {};
  const recs = await Promise.all(metas.map(ensureLayer));
  for (const r of recs) {
    if (r.on && S.map.hasLayer(r.llayer)) continue;
    r.on = true; r.llayer.addTo(S.map);
  }
  restack();
  metas.forEach(syncItem);
  if (!opts.noLegend) renderLegend();
  return recs;
}
function hideLayer(meta) {
  const r = getRec(meta);
  if (r && r.on) { r.on = false; if (r.llayer) S.map.removeLayer(r.llayer); }
}
function hideAll(filter) {
  for (const [, r] of S.layers) if (r.on && (!filter || filter(r))) { r.on = false; S.map.removeLayer(r.llayer); }
}
/* الرسم على canvas يتبع ترتيب الإضافة لا z-index؛ نعيد الترتيب حسب z من الكتالوج */
function restack() {
  const on = [...S.layers.values()].filter(r => r.on && r.llayer);
  on.filter(r => isRaster(r.meta)).forEach(r => r.llayer.setZIndex(r.meta.z || 40));
  on.filter(r => !isRaster(r.meta) && r.llayer.bringToFront)
    .sort((a, b) => (a.meta.z || 30) - (b.meta.z || 30))
    .forEach(r => r.llayer.bringToFront());
  if (S.analysisLayer && S.analysisLayer.bringToFront) S.analysisLayer.bringToFront();
}
async function toggleLayer(meta, on) {
  if (on) {
    loading(true);
    try {
      await showLayers([meta]);
      toast(`${t("d_shown")}: ${title(meta)}`, "ok");
    } catch (e) { console.error(e); toast(e.message, "err"); syncItem(meta); }
    finally { loading(false); }
  } else { hideLayer(meta); syncItem(meta); renderLegend(); }
}
function raiseLayer(meta) {
  meta.z = Math.max(...[...S.byId.values()].map(m => m.z || 0)) + 1;
  restack();
  toast(`${title(meta)} — ${t("to_front")}`);
}
function setOpacity(meta, v) {
  S.k.set(meta.id, v);
  const r = getRec(meta);
  if (!r || !r.llayer) return;
  if (isRaster(meta)) { r.llayer.setOpacity(v); return; }
  const sf = featStyle(meta);
  r.llayer.eachLayer(x => { if (x.setStyle) x.setStyle(sf(x.feature)); else if (x.setOpacity) x.setOpacity(v); });
}
async function zoomToLayer(meta) {
  let r = getRec(meta);
  if (!r || !r.llayer || !r.on) { await toggleLayer(meta, true); r = getRec(meta); }
  try {
    const b = r.llayer.getBounds && r.llayer.getBounds();
    if (b && b.isValid()) S.map.fitBounds(b.pad(0.12));
  } catch (e) {}
  revealMap();
}
/* بعد التحرير: تُبنى الطبقة من جديد بالبيانات المحدّثة */
async function refreshLayer(meta) {
  const was = isOn(meta);
  const r = getRec(meta);
  if (r && r.llayer) S.map.removeLayer(r.llayer);
  S.layers.delete(meta.id); S.dataP.delete(meta.id); S.apiCache.clear();
  if (was) await showLayers([meta]);
}

/* ------------------------------------------------ مفتاح الخريطة (صفوف الرموز) */
function legendRows(meta) {
  const st = meta.style || {};
  const row = (box, label) => `<div class="row">${box}<span>${esc(label)}</span></div>`;
  const sw = (bg, extra) => `<span class="box" style="background:${esc(bg)};${extra || ""}"></span>`;
  if (["graduated", "graduated_point", "graduated_line"].includes(st.type))
    return st.classes.map(c => row(sw(c[4]), S.lang === "ar" ? c[3] : c[2])).join("");
  if (st.type === "categorized") {
    const labels = S.lang === "ar" ? st.labels_ar : st.labels_en;
    return Object.entries(st.palette).map(([k, col]) => {
      let lab = labels ? labels[k] : k;
      if (!labels && st.label_tpl_en) lab = (S.lang === "ar" ? st.label_tpl_ar : st.label_tpl_en).replace("%d", k);
      return row(sw(col), lab);
    }).join("");
  }
  if (isRaster(meta)) {
    const ramp = meta.ramp ? `linear-gradient(90deg,${meta.ramp.join(",")})` : "#888";
    return row(`<span class="box ramp" style="background:${ramp}"></span>`, S.lang === "ar" ? meta.legend_ar : meta.legend_en);
  }
  if (meta.geom === "line" || st.type === "line")
    return row(`<span class="box line" style="color:${esc(st.color || "#999")};height:${Math.min(4, st.weight || 2)}px"></span>`, title(meta));
  if (st.type === "star") return row(`<span class="pin-sw">${starSvg(st.color, 16)}</span>`, title(meta));
  if (isSchoolLayer(meta)) return row(`<span class="pin-sw">${schoolPinSvg(st.color, 15, 19)}</span>`, title(meta));
  const col = st.fill || st.color || "#3388ff";
  return row(sw(col, `opacity:${st.fillOpacity != null ? Math.max(.35, st.fillOpacity) : 1}`), title(meta));
}
const PIN_STAR_RX = /مدرس|school/i;
const isThemed = (meta) => isRaster(meta) || ["graduated", "categorized", "graduated_point", "graduated_line"].includes((meta.style || {}).type);

function renderLegend() {
  if (S.activeMap) return;                                 // الخريطة الأصلية تعرض مفتاحها الخاص
  const on = [...S.layers.values()].filter(r => r.on).map(r => r.meta).sort((a, b) => (b.z || 0) - (a.z || 0));
  if (!on.length) { $("#legend").hidden = true; return; }
  $("#legendBody").innerHTML = on.map(m => (isThemed(m) ? `<div class="grp">${esc(title(m))}</div>` : "") + legendRows(m)).join("");
  $("#legend").hidden = false;
}

/* ------------------------------------------------ شجرة الطبقات */
const treeItems = (g) => {
  if (g.id === "raster") return S.cat.rasters.filter(r => !r.city || r.city === S.city);
  if (g.id === "edu") return S.cat.edu_layers;
  return S.cat.layers.filter(l => l.group === g.id && (l.city == null || l.city === S.city));
};
function swatchHtml(meta) {
  const st = meta.style || {};
  if (isSchoolLayer(meta)) return `<span class="lg-swatch pin">${schoolPinSvg(st.color, 15, 19)}</span>`;
  if (isRaster(meta)) return `<span class="lg-swatch ramp" style="background:linear-gradient(90deg,${(meta.ramp || ["#fff", "#888"]).join(",")})"></span>`;
  if (meta.geom === "point" || st.type === "point" || st.type === "graduated_point" || st.type === "star") {
    const c = st.type === "graduated_point" ? (st.classes[0] || [])[4] : st.color;
    return `<span class="lg-swatch dot" style="background:${esc(c || "#3388ff")}"></span>`;
  }
  if (meta.geom === "line" || st.type === "line" || st.type === "graduated_line") {
    const c = st.type === "graduated_line" ? (st.classes[0] || [])[4] : st.color;
    return `<span class="lg-swatch line" style="color:${esc(c || "#3388ff")}"></span>`;
  }
  if (st.type === "graduated") return `<span class="lg-swatch" style="background:${esc((st.classes[0] || [])[4] || "#3388ff")}"></span>`;
  if (st.type === "categorized") return `<span class="lg-swatch" style="background:${esc(Object.values(st.palette || {})[0] || "#3388ff")}"></span>`;
  return `<span class="lg-swatch" style="background:${esc(st.fill || "#3388ff")};opacity:${st.fillOpacity != null ? Math.min(1, st.fillOpacity + .3) : .6}"></span>`;
}
function opacityRow(meta) {
  const v = Math.round(userK(meta) * 100);
  return `<div class="lg-opacity"><span>${t("opacity")}</span><input type="range" min="5" max="100" step="5" value="${v}" aria-label="${t("opacity")}"><output>${v}%</output></div>`;
}
function itemHtml(meta) {
  const on = isOn(meta);
  const op = on && S.opOpen.has(meta.id);
  return `<div class="lg-item${on ? "" : " is-off"}" data-lid="${esc(meta.id)}">
    <div class="lg-row">
      <input type="checkbox" ${on ? "checked" : ""} aria-label="${esc(title(meta))}">
      ${swatchHtml(meta)}
      <button class="lg-name" data-act="name">${esc(title(meta))}<small>${esc(meta.id)}</small></button>
      <span class="lg-tools">
        <button data-act="opacity" aria-pressed="${op}" title="${t("opacity")}" aria-label="${t("opacity")}">${ic("opacity")}</button>
        <button data-act="front" title="${t("to_front")}" aria-label="${t("to_front")}">${ic("front")}</button>
        <button data-act="zoom" title="${t("zoom_to")}" aria-label="${t("zoom_to")}">${ic("focus")}</button>
      </span>
    </div>
    ${op ? opacityRow(meta) : ""}
    ${on && isThemed(meta) ? `<div class="lg-legend">${legendRows(meta)}</div>` : ""}
  </div>`;
}
const scheduleTree = (() => { let pending = false; return () => { if (pending) return; pending = true; raf(() => { pending = false; drawLayerTree(); }); }; })();
function drawLayerTree() {
  if (!S.cat) return;
  const q = ($("#lyrFilter").value || "").trim().toLowerCase();
  let html = "";
  for (const g of S.cat.groups) {
    const items = treeItems(g).filter(l => !q || ((l.title_en || "") + " " + (l.title_ar || "") + " " + l.id).toLowerCase().includes(q));
    if (!items.length) continue;
    const closed = S.closedGroups.has(g.id) && !q;
    const nOn = items.filter(isOn).length;
    html += `<section class="lg-group${closed ? " closed" : ""}" data-g="${esc(g.id)}">
      <h4><button data-act="group" aria-expanded="${!closed}"><span>${esc(S.lang === "ar" ? g.ar : g.en)}</span>
        <span class="meta"><span class="cnt">${nOn ? nOn + " / " : ""}${items.length}</span>${ic("chev")}</span></button></h4>
      <div class="lg-items">${items.map(itemHtml).join("")}</div></section>`;
  }
  $("#layerTree").innerHTML = html || `<div class="empty"><b>${T("لا نتائج", "No results")}</b>${t("layers_empty")}</div>`;
}
/* تحديث صف واحد في مكانه (يحفظ التركيز ولا يعيد رسم القائمة) */
function syncItem(meta) {
  const el = $(`.lg-item[data-lid="${CSS.escape(meta.id)}"]`);
  if (!el) return;
  const on = isOn(meta);
  $("input[type=checkbox]", el).checked = on;
  el.classList.toggle("is-off", !on);
  const lg = $(".lg-legend", el);
  if (on && isThemed(meta) && !lg) el.insertAdjacentHTML("beforeend", `<div class="lg-legend">${legendRows(meta)}</div>`);
  else if ((!on || !isThemed(meta)) && lg) lg.remove();
  const row = $(".lg-opacity", el), wantOp = on && S.opOpen.has(meta.id);
  if (wantOp && !row) $(".lg-row", el).insertAdjacentHTML("afterend", opacityRow(meta));
  else if (!wantOp && row) row.remove();
  $('[data-act="opacity"]', el).setAttribute("aria-pressed", wantOp);
  const grp = el.closest(".lg-group");
  if (grp) {
    const g = S.cat.groups.find(x => x.id === grp.dataset.g);
    if (g) {
      const items = treeItems(g), nOn = items.filter(isOn).length;
      const m = $("h4 .cnt", grp);
      if (m) m.textContent = (nOn ? nOn + " / " : "") + items.length;
    }
  }
}
const opPending = new Map();
function wireTree() {
  const tree = $("#layerTree");
  const metaOf = (el) => { const it = el.closest(".lg-item"); return it ? S.byId.get(it.dataset.lid) : null; };
  tree.addEventListener("change", e => {
    if (e.target.type !== "checkbox") return;
    const m = metaOf(e.target); if (m) toggleLayer(m, e.target.checked);
  });
  tree.addEventListener("input", e => {
    if (e.target.type !== "range") return;
    const m = metaOf(e.target); if (!m) return;
    const v = +e.target.value / 100;
    e.target.nextElementSibling.textContent = e.target.value + "%";
    S.k.set(m.id, v);                                          // إعادة التلوين مرة واحدة لكل إطار حتى مع آلاف المباني
    if (!opPending.has(m.id)) opPending.set(m.id, raf(() => { opPending.delete(m.id); setOpacity(m, S.k.get(m.id)); }));
  });
  tree.addEventListener("click", e => {
    const b = e.target.closest("[data-act]"); if (!b) return;
    const act = b.dataset.act;
    if (act === "group") {
      const g = b.closest(".lg-group"), id = g.dataset.g;
      const closed = g.classList.toggle("closed");
      closed ? S.closedGroups.add(id) : S.closedGroups.delete(id);
      b.setAttribute("aria-expanded", !closed);
      return;
    }
    const m = metaOf(b); if (!m) return;
    if (act === "name") { isOn(m) ? zoomToLayer(m) : toggleLayer(m, true); }
    else if (act === "zoom") zoomToLayer(m);
    else if (act === "front") raiseLayer(m);
    else if (act === "opacity") { S.opOpen.has(m.id) ? S.opOpen.delete(m.id) : S.opOpen.add(m.id); syncItem(m); }
  });
}

/* ------------------------------------------------ الخرائط الأصلية */
const fillTpl = (s) => String(s).replace("{city}", cityName(S.city)).replace("{c}", cityName(S.city));
const presetTitle = (m) => fillTpl(S.lang === "ar" ? m.title_ar : m.title_en);
function renderMapList() {
  if (!S.cat) return;
  const list = $("#mapList"), list2 = $("#mapListExtra");
  list.innerHTML = ""; list2.innerHTML = "";
  for (const m of S.cat.maps) {
    const chips = (m.legend || []).map(l => {
      if (l.sym === "ramp") return `<i style="background:linear-gradient(90deg,${l.color.join(",")})"></i>`;
      if (l.sym === "classes") return (l.classes || []).map(c => `<i style="background:${esc(c[2])}"></i>`).join("");
      if (l.sym === "cats") return (l.cats || []).map(c => `<i style="background:${esc(c[3])}"></i>`).join("");
      return `<i style="background:${esc(l.color)}"></i>`;
    }).join("");
    const b = document.createElement("button");
    b.type = "button";
    b.className = "map-card" + (S.activeMap === m.id ? " active" : "");
    b.setAttribute("aria-pressed", S.activeMap === m.id);
    b.innerHTML = `<div class="mt">${m.id}. ${esc(presetTitle(m))}</div><div class="ms">${esc(S.lang === "ar" ? m.sub_ar : m.sub_en)}</div><div class="thumbs">${chips}</div>`;
    b.addEventListener("click", () => applyMapPreset(m.id));
    (m.city === false || m.id === 7 ? list2 : list).appendChild(b);
  }
}
function showPresetChrome(m) {
  if (!m) return;
  $("#mbTitle").textContent = presetTitle(m);
  $("#mbSub").textContent = S.lang === "ar" ? m.sub_ar : m.sub_en;
  $("#mapBanner").hidden = false;
  const rows = [];
  for (const l of (m.legend || [])) {
    const lab = S.lang === "ar" ? l.ar : l.en;
    const row = (box, label) => `<div class="row">${box}<span>${esc(label)}</span></div>`;
    if (l.sym === "ramp") rows.push(row(`<span class="box ramp" style="background:linear-gradient(90deg,${l.color.join(",")})"></span>`, lab));
    else if (l.sym === "classes") l.classes.forEach(c => rows.push(row(`<span class="box" style="background:${esc(c[2])}"></span>`, S.lang === "ar" ? c[1] : c[0])));
    else if (l.sym === "cats") l.cats.forEach(c => rows.push(row(`<span class="box" style="background:${esc(c[3])}"></span>`, S.lang === "ar" ? c[2] : c[1])));
    else if (l.sym === "line") rows.push(row(`<span class="box line" style="color:${esc(l.color)}"></span>`, lab));
    else if (l.sym === "point" && PIN_STAR_RX.test(l.ar + " " + l.en)) rows.push(row(`<span class="pin-sw">${schoolPinSvg(l.color, 15, 19)}</span>`, lab));
    else if (l.sym === "star") rows.push(row(`<span class="pin-sw">${starSvg(l.color, 16)}</span>`, lab));
    else rows.push(row(`<span class="box" style="background:${esc(l.color)}"></span>`, lab));
  }
  $("#legendBody").innerHTML = rows.join("");
  $("#legend").hidden = false;
  if (isNarrow()) $("#legend").classList.add("collapsed");   // على الجوال يبدأ المفتاح مطويًا
}
const presetIds = (m) => (m.on || m.layers).map(x => x.replace("{c}", S.city).replace("{city}", S.city));

async function applyMapPreset(id) {
  const m = S.cat.maps.find(x => x.id === id);
  if (!m) return;
  if (m.city === true) setCity(S.city, true);
  S.activeMap = id;
  loading(true);
  try {
    hideAll();
    const metas = presetIds(m).map(x => S.byId.get(x)).filter(Boolean);
    await showLayers(metas, { noLegend: true });      // تحميل متوازٍ ثم إضافة بترتيب z
    showPresetChrome(m);
    fitBoundsOf(metas);
    renderMapList();
    metas.forEach(syncItem);
    toast(`${t("d_map_on")} ${presetTitle(m)}`, "ok");
    revealMap();
  } catch (e) { console.error(e); toast(e.message, "err"); }
  finally { loading(false); }
}
function fitBoundsOf(metas) {
  const b = L.latLngBounds([]);
  for (const meta of metas) {
    const r = getRec(meta);
    if (r && r.llayer && !isRaster(meta) && r.llayer.getBounds) { const bb = r.llayer.getBounds(); if (bb.isValid()) b.extend(bb); }
  }
  if (b.isValid()) S.map.fitBounds(b.pad(0.06));
}
function leavePreset() {
  S.activeMap = null;
  $("#mapBanner").hidden = true;
  renderMapList(); renderLegend();
}

/* ------------------------------------------------ تبديل المدينة */
const cityMetas = () => S.cat.layers.filter(l => l.city == null || l.city === S.city);
function setCity(city, keep) {
  if (S.city === city && !keep) return;
  if (!keep) { clearTool(); detachResults(); }       // نتيجة المدينة السابقة تبقى محفوظة وتختفي من الخريطة
  const changed = S.city !== city;
  S.city = city;
  setPressed($("#citySeg"), b => b.dataset.city === city);
  const ids = new Set(cityMetas().map(l => l.id));
  hideAll(r => !ids.has(r.meta.id) && r.meta.group !== "edu");
  if (changed) rebuildSchools();                      // دبابيس مدارس المدينة المختارة فقط
  if (!keep) {
    leavePreset(); paintResults();
    S.dashKey = null;
    loadCityDefaults();
    if (S.tab === "dash") renderDashboard();
    if (S.tab === "table") renderTableSel();
    if (S.tab === "edit") renderEditSel();
  }
  drawLayerTree(); renderLegend();
}
function rebuildSchools() {
  const rec = S.layers.get(SCHOOLS_ID);
  if (!rec || !rec.llayer) return;
  const was = rec.on;
  S.map.removeLayer(rec.llayer);
  S.layers.delete(SCHOOLS_ID);
  if (was) showLayers([rec.meta], { noLegend: true }).then(() => renderLegend());
}
async function loadCityDefaults() {
  loading(true);
  try {
    const want = S.cat.layers.filter(l => l.city === S.city && l.default_on);
    await showLayers(want, { noLegend: true });
    const b = getRec(S.byId.get(S.city + "_boundary_32636"));
    if (b && b.llayer.getBounds && b.llayer.getBounds().isValid()) S.map.fitBounds(b.llayer.getBounds().pad(0.05));
    renderLegend();
  } catch (e) { console.error(e); toast(e.message, "err"); }
  finally { loading(false); }
}

/* ------------------------------------------------ التحليل: مساعدات */
const HS = {
  "Hot 99%": ["#b30000", "Hot spot 99% (high coverage)", "نقاط ساخنة 99% (تغطية عالية)"],
  "Hot 95%": ["#fc8d59", "Hot spot 95%", "نقاط ساخنة 95%"],
  "Not significant": ["#e8e8e8", "Not significant", "غير دال"],
  "Cold 95%": ["#91bfdb", "Cold spot 95%", "نقاط باردة 95%"],
  "Cold 99%": ["#045a8d", "Cold spot 99% (low coverage)", "نقاط باردة 99% (تغطية منخفضة)"],
};
const OVERLAP_PAL = { 2: "#1f78b4", 3: "#33a02c", 4: "#ff7f00", 5: "#e31a1c", 6: "#6a3d9a", 7: "#b15928", 8: "#fb9a99", 9: "#a6cee3", 10: "#b2df8a" };
const AMBER = "#C8811A";
const cityPlaceName = () => (S.city === "nasr" ? "Nasr City" : "Port Said");
const kv = (label, value) => `<div class="kv"><span>${label}</span><b>${value}</b></div>`;

function threshold() {
  const seg = $("#thSeg button.active");
  if (!seg || seg.dataset.th !== "custom") return parseInt(seg ? seg.dataset.th : "800", 10);
  return Math.min(5000, Math.max(50, parseInt($("#thCustom").value || "1000", 10) || 1000));
}
/* 5 كم/س هي سرعة المشي المفترضة في التقرير — نُظهر ما يعنيه الرقم بالدقائق */
function updateWalk() {
  const el = $("#thWalk"); if (!el) return;
  el.textContent = t("d_walk").replace("{m}", num(Math.round(threshold() / 5000 * 60), 0));
}
function setBusy(btn, on) { btn.classList.toggle("busy", on); btn.disabled = on; }

/* كل مدينة تحتفظ بنتيجتها: تشغيل تحليل وأنت على نصر يظهر في نصر، وعند التبديل إلى بورسعيد
   تظهر نتيجتها هي (أو بطاقة فارغة)، وعند العودة تعود نتيجة نصر كما تركتها. */
const R = () => S.results[S.city];
const hasResult = () => !!R().box;
function showAnalysisEmpty() {
  const box = $("#anResult");
  box.hidden = false; box.className = "empty";
  box.innerHTML = `<b>${t("an_empty_t")}</b>${t("an_empty")}`;
}
function showAnalysisResult(html, ttl, rebuild) {
  const box = $("#anResult"), r = R();
  r.rebuild = rebuild || null;            // نتائج تحمل أسماء مدارس تُبنى من جديد عند تغيير المفتاح
  r.box = `<h4>${esc(ttl || t("d_analysis"))}</h4>` + html;
  r.title = ttl;
  box.hidden = false; box.className = "result-box";
  box.innerHTML = r.box;
  box.scrollTop = 0;
}
function setBadge(text) { R().badge = text; $("#anBadgeText").textContent = text; $("#anBadge").hidden = false; }
function setChips(html) { const r = R(), strip = $("#kpiStrip"); r.chips = html; strip.innerHTML = html; strip.hidden = !html; }
/* يعرض نتيجة المدينة الحالية (طبقة + شارة + مؤشرات + بطاقة) أو يفرغ الواجهة */
function paintResults() {
  const r = R();
  if (r.layer && !S.map.hasLayer(r.layer)) r.layer.addTo(S.map);
  S.analysisLayer = r.layer || null;
  $("#anBadgeText").textContent = r.badge || ""; $("#anBadge").hidden = !r.badge;
  const strip = $("#kpiStrip"); strip.innerHTML = r.chips || ""; strip.hidden = !r.chips;
  const box = $("#anResult");
  if (r.rebuild) r.box = `<h4>${esc(r.title || t("d_analysis"))}</h4>` + r.rebuild();
  if (r.box) { box.hidden = false; box.className = "result-box"; box.innerHTML = r.box; } else showAnalysisEmpty();
  restack();
}
function detachResults() { const r = R(); if (r.layer) S.map.removeLayer(r.layer); S.analysisLayer = null; }
function dropResults(city) {
  const r = S.results[city]; if (r && r.layer) S.map.removeLayer(r.layer);
  S.results[city] = {};
}
function clearAnalysis(all) {
  S.anSeq++;
  if (all) { dropResults("nasr"); dropResults("ps"); } else dropResults(S.city);
  S.analysisLayer = null;
  paintResults();
  clearTool(); $("#measureOut").hidden = true;
}
function setAnalysisLayer(layer, label, fit) {
  const r = R();
  if (r.layer) S.map.removeLayer(r.layer);
  r.layer = layer.addTo(S.map); S.analysisLayer = r.layer;
  try { const b = layer.getBounds(); if (fit !== false && b.isValid()) S.map.fitBounds(b.pad(0.08)); } catch (e) {}
  setBadge(label);
}
function geoAnalysisLayer(fc, styleFn) {
  return L.geoJSON(fc, { style: styleFn, onEachFeature: (f, l) => l.bindPopup(() => propsTable(f.properties || {})) });
}
/* كل تحليل: زر مشغول → هيكل انتظار → نتيجة. الرمز anSeq يمنع ظهور نتيجة قديمة بعد نتيجة أحدث */
async function runAnalysis(sel, fetcher, render) {
  const btn = $(sel);
  if (btn.disabled) return;
  const my = ++S.anSeq, city = S.city;
  setBusy(btn, true);
  const box = $("#anResult");
  box.hidden = false; box.className = "result-box";
  box.innerHTML = `<h4>${t("d_running")}</h4><div class="skel" style="height:14px;margin:10px 0"></div><div class="skel" style="height:14px;width:70%"></div>`;
  try {
    const data = await fetcher();
    if (my !== S.anSeq) return;
    if (city !== S.city) { toast(T("اكتمل التحليل للمدينة الأخرى. أعد تشغيله هنا ليظهر فورًا.", "The analysis finished for the other city. Run it again here to show it."), "ok"); return; }
    render(data);
    toast(t("d_done"), "ok");
    revealMap();
  } catch (e) {
    console.error(e);
    if (my === S.anSeq) { box.innerHTML = `<h4>${t("d_failed")}</h4><p class="hint">${esc(e.message)}</p>`; }
    toast(e.message, "err");
  } finally { setBusy(btn, false); }
}

/* ------------------------------------------------ التحليلات */
function runServiceArea() {
  const th = threshold(), ttl = t("d_svc_title").replace("{t}", th);
  runAnalysis("#anService", () => postCached("/api/analysis/service-area", { city: S.city, threshold: th }), fc => {
    if (!fc.features.length) { showAnalysisResult(`<p class="hint">${T("لا توجد مقاطع شبكة ضمن هذه المسافة.", "No network segments fall within this distance.")}</p>`, ttl); return; }
    setAnalysisLayer(geoAnalysisLayer(fc, () => ({ color: "#14532d", weight: 1.4, fillColor: "#2e7d4f", fillOpacity: 0.35 })), ttl);
    showAnalysisResult(
      kv(T("المسافة المختارة", "Chosen distance"), `${num(th, 0)} m`) +
      kv(T("زمن المشي التقريبي", "Approx. walking time"), t("d_walk").replace("{m}", num(Math.round(th / 5000 * 60), 0))) +
      `<p class="hint">${T("المضلع هو اتحاد مقاطع الشبكة التي تقع ضمن هذه المسافة من أقرب مدرسة، مع هامش 25 م حولها (نفس منهجية QGIS).",
        "The polygon is the union of network segments within this distance of the nearest school, with a 25 m buffer (same method as QGIS).")}</p>`, ttl);
  });
}

function runCoverage() {
  const th = threshold(), ttl = t("d_cov_title").replace("{t}", th);
  runAnalysis("#anCoverage", () => postCached("/api/analysis/coverage", { city: S.city, threshold: th }), r => {
    setChips(
      `<div class="chip green"><b>${esc(r.buildings.pct)}%</b><span>${t("d_buildings")}</span></div>` +
      `<div class="chip amber"><b>${esc(r.population.pct)}%</b><span>${T("سكان", "people")}</span></div>` +
      `<div class="chip"><b>${esc(r.area_km2.pct)}%</b><span>${T("مساحة", "area")}</span></div>`);
    let zrows = "";
    if (r.zones && r.zones.length) {
      zrows = `<h4 style="margin-top:12px">${T("أعلى 15 شياخة بعدد المباني", "Top 15 shiakhas by buildings")}</h4>
        <table><thead><tr><th>${T("الشياخة", "Shiakha")}</th><th class="num">${t("d_buildings")}</th><th class="num">${t("d_within")}</th><th class="num">%</th></tr></thead><tbody>` +
        r.zones.slice(0, 15).map(z => `<tr><td>${esc(z.shiakha)}</td><td class="num">${num(z.n_bldg, 0)}</td><td class="num">${num(z.within, 0)}</td><td class="num">${esc(z.pct_bldg)}</td></tr>`).join("") + "</tbody></table>";
    }
    showAnalysisResult(
      kv(t("d_buildings"), `${num(r.buildings.within, 0)} / ${num(r.buildings.total, 0)} — ${esc(r.buildings.pct)}%`) +
      kv(t("d_population"), `${num(r.population.within, 0)} / ${num(r.population.total, 0)} — ${esc(r.population.pct)}%`) +
      kv(t("d_area"), `${esc(r.area_km2.within)} / ${esc(r.area_km2.total)} — ${esc(r.area_km2.pct)}%`) +
      kv(t("d_avg"), `${num(r.avg_dist_m, 0)} m`) + kv(t("d_med"), `${num(r.median_dist_m, 0)} m`) + zrows, ttl);
  });
}

function runOverlap() {
  const th = threshold(), ttl = t("d_ovl_title").replace("{t}", th);
  runAnalysis("#anOverlap", () => postCached("/api/analysis/overlap", { city: S.city, threshold: th }), fc => {
    if (!fc.features.length) { showAnalysisResult(`<p class="hint">${T("لا توجد مناطق متداخلة عند هذه المسافة.", "No overlapping areas at this distance.")}</p>`, ttl); return; }
    setAnalysisLayer(geoAnalysisLayer(fc, f => ({ fillColor: OVERLAP_PAL[f.properties.n_schools] || "#999999", color: "#fff", weight: 0.6, fillOpacity: 0.92 })), ttl);
    const agg = {};
    for (const f of fc.features) agg[f.properties.n_schools] = (agg[f.properties.n_schools] || 0) + (f.properties.area_km2 || 0);
    const rows = Object.keys(agg).sort((a, b) => a - b).map(k =>
      `<tr><td><span class="pill" style="background:${OVERLAP_PAL[k] || "#999"}">${k}</span> ${T("مدارس", "schools")}</td><td class="num">${agg[k].toFixed(3)} km²</td></tr>`).join("");
    showAnalysisResult(`<table><thead><tr><th>${T("عدد المدارس المغطية", "Schools covering")}</th><th class="num">${T("المساحة", "Area")}</th></tr></thead><tbody>${rows}</tbody></table>
      <p class="hint">${T("شبكة بدقة 10 م ثم تحويل إلى مضلعات — نفس منهجية QGIS.", "10 m raster, then polygonised — same method as QGIS.")}</p>`, ttl);
  });
}

function runHotspot() {
  const th = threshold(), ttl = t("d_hs_title").replace("{t}", th);
  runAnalysis("#anHotspot", () => postCached("/api/analysis/hotspot", { city: S.city, threshold: th, cell: 250, band: 1000, min_bldg: 5 }), r => {
    setAnalysisLayer(geoAnalysisLayer(r, f => ({ fillColor: (HS[f.properties.class] || HS["Not significant"])[0], color: "#fff", weight: 0.4, fillOpacity: 0.95 })), ttl);
    const rows = Object.keys(HS).map(k => `<tr><td><span class="pill${k === "Not significant" || k === "Cold 95%" ? " light" : ""}" style="background:${HS[k][0]}">${esc(S.lang === "ar" ? HS[k][2] : HS[k][1])}</span></td><td class="num">${num((r.counts || {})[k] || 0, 0)}</td></tr>`).join("");
    showAnalysisResult(`<table><thead><tr><th>${t("hot_classes")}</th><th class="num">${T("خلايا", "Cells")}</th></tr></thead><tbody>${rows}</tbody></table>
      <p class="hint">${T("Getis-Ord Gi* على خلايا 250 م بنطاق 1000 م — الخوارزمية نفسها في distribution.py.", "Getis-Ord Gi* on 250 m cells with a 1000 m band — same algorithm as distribution.py.")}</p>`, ttl);
  });
}

function runDistribution() {
  const ttl = t("d_dist_title");
  runAnalysis("#anDist", () => postCached("/api/analysis/distribution", { city: S.city }), r => {
    const g = L.featureGroup([
      L.geoJSON(r.std_ellipse, { style: () => ({ color: "#7b5ea7", weight: 2.5, fillColor: "#7b5ea7", fillOpacity: 0.1 }) }),
      L.geoJSON(r.std_distance, { style: () => ({ color: "#1b4e7a", weight: 2.5, fill: false }) }),
      L.geoJSON(r.mean_center, { pointToLayer: (f, ll) => L.circleMarker(ll, { radius: 8, fillColor: "#1b3a5c", color: "#fff", weight: 1.5, fillOpacity: 1 }) }),
    ]);
    setAnalysisLayer(g, ttl);
    const s = r.stats;
    showAnalysisResult(
      kv(T("عدد المدارس", "Schools (n)"), num(s.n, 0)) +
      kv(T("المركز المتوسط", "Mean center"), `<bdi>${num(s.mean_x, 0)} , ${num(s.mean_y, 0)}</bdi>`) +
      kv(t("std_dist"), `${num(s.std_dist_m, 0)} m`) + kv("sx / sy", `${num(s.sx, 0)} / ${num(s.sy, 0)} m`) +
      kv(T("اتجاه الإهليلج", "Ellipse angle"), `${esc(s.theta_deg)}°`) +
      kv(T("متوسط أقرب جار", "NN mean"), `${num(s.nn_mean_m, 0)} m`) + kv(T("المتوقع عشوائيًا", "NN expected"), `${num(s.nn_expected_m, 0)} m`) +
      kv(`${t("nn_ratio")} (z)`, `${esc(s.nn_ratio)} (${esc(s.nn_z)})`) +
      `<p class="hint">${s.nn_ratio < 1
        ? T("المدارس متجمّعة: هي أقرب لبعضها مما يتوقع التوزيع العشوائي.", "The schools are clustered: closer together than a random pattern would give.")
        : T("التوزيع عشوائي أو متباعد.", "The pattern is random or dispersed.")}</p>`, ttl);
  });
}

function runKde() {
  const th = threshold(), ttl = t("d_kde_title");
  runAnalysis("#anKde", () => postCached("/api/analysis/kde", { city: S.city, bandwidth: th, pixel: 50 }), r => {
    const img = L.imageOverlay(r.png, r.bounds, { opacity: 0.75, pane: "rasters" });
    setAnalysisLayer(img, ttl, false);
    S.map.fitBounds(L.latLngBounds(r.bounds).pad(0.1));
    showAnalysisResult(
      kv(T("نطاق النواة", "Bandwidth"), `${num(r.bandwidth, 0)} m`) + kv(T("حجم البكسل", "Pixel size"), `${num(r.pixel, 0)} m`) +
      kv(T("أقصى كثافة", "Max density"), esc(r.vmax)) +
      `<p class="hint">${T("نواة رباعية (quartic) بنفس معاملات خريطة الحرارة في QGIS.", "Quartic kernel with the same parameters as the QGIS heatmap.")}</p>`, ttl);
  });
}

/* ------------------------------------------------ أدوات القياس والرسم */
function clearTool() {
  if (S.measure) { S.map.removeLayer(S.measure); S.measure = null; }
  if (S._h) { S.map.off("click", S._h.click); if (S._h.dbl) S.map.off("dblclick", S._h.dbl); S._h = null; }
  S.map.getContainer().style.cursor = "";
  S.map.doubleClickZoom.enable();
  clearPick();
  S.tool = null;
  ["#toolMeasure", "#toolArea", "#toolBuffer"].forEach(s => $(s).setAttribute("aria-pressed", "false"));
  setBusy($("#anNearest"), false);
}
function startTool(name, btnSel) {
  clearTool();
  S.tool = name;
  if (btnSel) $(btnSel).setAttribute("aria-pressed", "true");
  S.map.getContainer().style.cursor = "crosshair";
  revealMap();
}
const fmtLen = (m) => (m < 1000 ? num(m, 1) + " m" : num(m / 1000, 2) + " km");
const fmtArea = (a) => (a < 1e6 ? num(a, 1) + " m²" : num(a / 1e6, 3) + " km²");
function geodesicArea(pts) {
  const R = 6378137; let a = 0;
  for (let i = 0; i < pts.length; i++) {
    const p1 = pts[i], p2 = pts[(i + 1) % pts.length];
    a += (p2.lng - p1.lng) * Math.PI / 180 * (2 + Math.sin(p1.lat * Math.PI / 180) + Math.sin(p2.lat * Math.PI / 180));
  }
  return Math.abs(a * R * R / 2);
}
function startMeasure(mode) {
  const isArea = mode === "area";
  startTool(isArea ? "area" : "measure", isArea ? "#toolArea" : "#toolMeasure");
  const out = $("#measureOut"), head = isArea ? t("tool_area") : t("tool_measure");
  out.hidden = false;
  out.innerHTML = `<h4>${head}</h4><p class="hint">${isArea ? t("d_area_hint") : t("d_measure_hint")}</p>`;
  const grp = L.layerGroup().addTo(S.map); S.measure = grp;
  const pts = [], dots = []; let shape = null;
  S.map.doubleClickZoom.disable();
  const redraw = () => {
    if (shape) { grp.removeLayer(shape); shape = null; }
    if (pts.length > 1) shape = (isArea && pts.length > 2 ? L.polygon(pts, { color: AMBER, weight: 2, fillOpacity: 0.15 }) : L.polyline(pts, { color: AMBER, weight: 2.5 })).addTo(grp);
    let res = "";
    if (!isArea && pts.length > 1) { let m = 0; for (let i = 1; i < pts.length; i++) m += pts[i - 1].distanceTo(pts[i]); res = kv(t("d_measure_total"), fmtLen(m)); }
    if (isArea && pts.length > 2) res = kv(t("d_area_total"), fmtArea(geodesicArea(pts)));
    if (res) out.innerHTML = `<h4>${head}</h4>` + res;
  };
  S._h = {
    click: e => { pts.push(e.latlng); dots.push(L.circleMarker(e.latlng, { radius: 4, color: AMBER, fillColor: AMBER, fillOpacity: 1 }).addTo(grp)); redraw(); },
    dbl: () => {                                  // النقرة المزدوجة تُضيف نقطة زائدة: نحذفها وننهي الرسم
      if (pts.length > 1) { pts.pop(); grp.removeLayer(dots.pop()); }
      redraw();
      S.map.off("click", S._h.click); S.map.off("dblclick", S._h.dbl);
      S.map.getContainer().style.cursor = ""; S.map.doubleClickZoom.enable(); S.tool = null;
      $(isArea ? "#toolArea" : "#toolMeasure").setAttribute("aria-pressed", "false");
    },
  };
  S.map.on("click", S._h.click); S.map.on("dblclick", S._h.dbl);
}

function startBuffer() {
  startTool("buffer", "#toolBuffer");
  const out = $("#measureOut");
  out.hidden = false;
  out.innerHTML = `<h4>${t("tool_buffer")}</h4><p class="hint">${t("d_buffer_hint")}</p>
    <div class="kv"><span>${t("d_buffer_dist")}</span><b><input id="bufR" type="number" value="800" min="50" max="5000" step="50" style="width:96px" aria-label="${t("d_buffer_dist")}"></b></div>
    <div id="bufOut"></div>`;
  S._h = {
    click: e => {
      const r = Math.max(10, parseFloat($("#bufR").value || "800"));
      if (S.measure) S.map.removeLayer(S.measure);
      S.measure = L.circle(e.latlng, { radius: r, color: "#14532d", weight: 2, fillColor: "#2e7d4f", fillOpacity: 0.25 }).addTo(S.map);
      const a = Math.PI * r * r;
      $("#bufOut").innerHTML = kv(t("d_buffer_ok"), `${num(r, 0)} m`) + kv(t("d_area_total"), `${num(a, 0)} m² (${num(a / 1e6, 3)} km²)`);
    },
  };
  S.map.on("click", S._h.click);
}

function startNearest() {
  const btn = $("#anNearest");
  if (btn.disabled) { clearTool(); return; }
  startTool("nearest");
  setBusy(btn, true);
  const box = $("#anResult"); box.hidden = false; box.className = "result-box";
  box.innerHTML = `<h4>${t("d_nearest_title")}</h4><p class="hint">${t("d_nearest_hint")}</p>`;
  S._h = {
    click: async e => {
      S.map.off("click", S._h.click); S._h = null;
      S.map.getContainer().style.cursor = ""; S.tool = null;
      loading(true);
      try {
        const [r, sc] = await Promise.all([
          post("/api/analysis/nearest-from-point", { city: S.city, lng: e.latlng.lng, lat: e.latlng.lat }),
          getFc(S.byId.get("schools_32636")).catch(() => null),
        ]);
        const coords = {};
        if (sc) for (const f of sc.features) if (f.properties.city === cityPlaceName()) coords[f.properties.school_id] = f.geometry.coordinates;
        const grp = L.featureGroup();
        L.circleMarker(e.latlng, { radius: 6, color: AMBER, fillColor: AMBER, fillOpacity: 1 }).addTo(grp);
        const top = r.schools.slice(0, 10);
        top.forEach((s, i) => {
          const c = coords[s.school_id];
          if (c) L.polyline([e.latlng, [c[1], c[0]]], { color: i === 0 ? "#1E7B4F" : "#999", weight: i === 0 ? 2.4 : 1, opacity: i === 0 ? 1 : .6, dashArray: i === 0 ? null : "5 4" }).addTo(grp);
        });
        if (S.measure) S.map.removeLayer(S.measure);
        S.measure = grp.addTo(S.map);
        try { S.map.fitBounds(grp.getBounds().pad(0.2)); } catch (err) {}
        // اسم المدرسة يظهر فقط عند تفعيل المفتاح؛ وإلا يظهر رقمها (school_id) فيبقى الجدول مفيدًا
        const html = () => kv(T("المسافة إلى أقرب نقطة على الشبكة", "Distance to the nearest network point"), `${num(r.snap_gap_m, 0)} m`) +
          `<table><thead><tr><th>#</th><th>${t("d_schools")}</th><th class="num">${T("مسافة الشبكة", "Network")}</th></tr></thead><tbody>` +
          top.map((s, i) => `<tr><td>${i + 1}</td><td>${S.showNames ? esc(s.name_ar || s.school_id) : `<bdi class="school-id">${esc(s.school_id)}</bdi>`}</td><td class="num">${num(s.dist_m, 0)} m</td></tr>`).join("") +
          `</tbody></table>`;
        showAnalysisResult(html(), t("d_nearest_title"), html);
        toast(t("d_done"), "ok");
      } catch (err) { console.error(err); toast(err.message, "err"); showAnalysisEmpty(); }
      finally { loading(false); setBusy(btn, false); }
    },
  };
  S.map.on("click", S._h.click);
}

function toggleIdentify() {
  S.identify = !S.identify;
  $("#toolIdentify").setAttribute("aria-pressed", S.identify);
  toast(S.identify ? t("d_identify_on") : t("d_identify_off"));
  if (S.identify) revealMap();
}
function showFeatureModal(meta, f, l) {
  $("#fmTitle").textContent = title(meta);
  $("#fmBody").innerHTML = propsTable(f.properties || {});
  const foot = $("#fmFoot"); foot.innerHTML = "";
  if (meta.editable) {
    const b = document.createElement("button");
    b.className = "primary"; b.textContent = t("ed_modify");
    b.onclick = () => { $("#featModal").close(); selectTab("edit"); $("#editLayerSel").value = meta.id; updateEditForm(); openEditForm(meta, f, l, false); };
    foot.appendChild(b);
  }
  const z = document.createElement("button");
  z.textContent = t("zoom");
  z.onclick = () => { try { S.map.fitBounds(l.getBounds().pad(0.3)); } catch (e) { try { S.map.setView(l.getLatLng(), 17); } catch (e2) {} } $("#featModal").close(); };
  foot.appendChild(z);
  $("#featModal").showModal();
}

/* ------------------------------------------------ جدول الخصائص */
const TBL = { rows: [], cols: [], view: [], sort: null, dir: 1, limit: 300, meta: null };
function renderTableSel() {
  if (!S.cat) return;
  const sel = $("#tableLayerSel"), cur = sel.value;
  const items = cityMetas();
  sel.innerHTML = items.map(l => `<option value="${esc(l.id)}">${esc(title(l))}</option>`).join("");
  if (cur && items.some(l => l.id === cur)) sel.value = cur;
  if (S.tab === "table") loadTable();               // لا نحمّل بيانات الجدول إلا إن كان ظاهرًا
}
async function loadTable() {
  const id = $("#tableLayerSel").value, meta = S.byId.get(id);
  if (!meta) return;
  TBL.meta = meta; TBL.sort = null; TBL.limit = 300;
  $("#tblInfo").textContent = t("loading");
  loading(true);
  try {
    const fc = await getFc(meta);
    if ($("#tableLayerSel").value !== id) return;    // المستخدم بدّل الطبقة أثناء التحميل
    TBL.rows = fc.features.map(f => Object.assign({ __fid: f.id }, f.properties));
    TBL.cols = Object.keys(TBL.rows[0] || {}).filter(k => k !== "__fid");
    drawTable();
  } catch (e) { toast(e.message, "err"); $("#tblInfo").textContent = ""; }
  finally { loading(false); }
}
const tblFiltered = () => {
  const q = ($("#tblSearch").value || "").trim().toLowerCase();
  const cols = TBL.cols.filter(c => !nameHidden(c));          // لا بحث داخل أعمدة مخفية، حتى لا تُكشف بالتخمين
  let rows = q ? TBL.rows.filter(r => cols.some(c => String(r[c] == null ? "" : r[c]).toLowerCase().includes(q))) : TBL.rows;
  if (TBL.sort) {
    const k = TBL.sort, d = TBL.dir;
    rows = rows.slice().sort((a, b) => {
      const x = a[k], y = b[k];
      if (x == null) return 1; if (y == null) return -1;
      return (x > y ? 1 : x < y ? -1 : 0) * d;
    });
  }
  return rows;
};
function drawTable() {
  const rows = tblFiltered(), max = Math.min(rows.length, TBL.limit);
  TBL.view = rows.slice(0, max);
  const empty = $("#tblEmpty"), wrap = $("#tblWrap");
  empty.hidden = rows.length > 0; wrap.hidden = rows.length === 0;
  if (!rows.length) { empty.innerHTML = `<b>${t("d_no_rows")}</b>${t("tbl_empty")}`; $("#tblInfo").textContent = ""; return; }
  $("#attrTable thead").innerHTML = "<tr>" + TBL.cols.map(c => nameHidden(c)
    ? `<th data-c="${esc(c)}" class="is-masked" title="${esc(t("names_masked"))}">${esc(c)}${ic("lock")}</th>`
    : `<th data-c="${esc(c)}">${esc(c)}${TBL.sort === c ? ic(TBL.dir > 0 ? "arrow-up" : "arrow-down") : ""}</th>`).join("") + "</tr>";
  $("#attrTable tbody").innerHTML = TBL.view.map((r, i) => `<tr data-i="${i}">` + TBL.cols.map(c => {
    const v = r[c], isNum = typeof v === "number";
    if (nameHidden(c)) return `<td class="masked-cell">${v == null ? "" : "••••"}</td>`;
    return `<td class="${isNum ? "num" : ""}" title="${esc(v)}">${v == null ? "" : isNum ? num(v, 2) : esc(v)}</td>`;
  }).join("") + "</tr>").join("");
  const info = $("#tblInfo");
  info.innerHTML = `<span>${num(max, 0)} / ${num(rows.length, 0)} ${t("d_rows")} — ${t("d_click_row")}</span>` +
    (rows.length > max ? `<button id="tblMore">${t("tbl_more")}</button>` : "");
}
async function focusFeature(fid) {
  const meta = TBL.meta; if (!meta) return;
  await showLayers([meta]);
  const r = getRec(meta);
  let hit = null;
  r.llayer.eachLayer(l => { if (!hit && l.feature && String(l.feature.id) === String(fid)) hit = l; });
  if (!hit) return;
  try { if (hit.getBounds) S.map.fitBounds(hit.getBounds().pad(0.4)); else S.map.setView(hit.getLatLng(), Math.max(S.map.getZoom(), 16)); } catch (e) {}
  openFeaturePopup(meta, hit);
  revealMap();
}
function exportCsv() {
  const rows = tblFiltered();
  const q = (v) => `"${String(v == null ? "" : v).replace(/"/g, '""')}"`;
  const csv = "\uFEFF" + [TBL.cols.map(q).join(",")].concat(rows.map(r => TBL.cols.map(c => q(r[c])).join(","))).join("\n");
  download(csv, $("#tableLayerSel").value + ".csv", "text/csv");
  toast(t("d_exported"), "ok");
}
async function exportGeo(id) {
  id = id || $("#tableLayerSel").value;
  const meta = S.byId.get(id);
  loading(true);
  try {
    const src = meta && meta.source ? "&source=" + encodeURIComponent(meta.source) : "";
    const fc = await api("/api/layers/" + encodeURIComponent(id) + "?full=true" + src);
    download(JSON.stringify(fc), id + ".geojson", "application/geo+json");
    toast(t("d_exported"), "ok");
  } catch (e) { toast(e.message, "err"); }
  finally { loading(false); }
}
function download(data, name, mime) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([data], { type: mime }));
  a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}

/* ------------------------------------------------ لوحة المؤشرات */
let chartLoad = null;                                           // Chart.js (200 KB) لا يُحمَّل إلا حين تُحتاج الرسوم
function loadChart() {
  if (window.Chart) return Promise.resolve();
  if (!chartLoad) chartLoad = new Promise((ok, fail) => {
    const el = document.createElement("script");
    el.src = "/static/vendor/chart.umd.min.js";
    el.onload = ok;
    el.onerror = () => { chartLoad = null; fail(new Error(T("تعذّر تحميل مكتبة الرسوم.", "Couldn't load the charting library."))); };
    document.head.appendChild(el);
  });
  return chartLoad;
}
async function loadStats() {
  if (S.stats) return S.stats;
  try { S.stats = await api("/api/stats"); } catch (e) { console.error(e); }
  return S.stats;
}
const stat = (label, val, sub, cls) => `<div class="stat"><div><div class="s-l">${label}</div>${sub ? `<div class="s-c">${sub}</div>` : ""}</div><div class="s-v ${cls || ""}">${val}</div></div>`;
function chartBase(extra) {
  const rtl = S.lang === "ar";
  return Object.assign({
    responsive: true, maintainAspectRatio: false, animation: { duration: 250 },
    plugins: { legend: { position: "bottom", rtl, labels: { boxWidth: 10, boxHeight: 10, font: { size: 11 } } }, tooltip: { rtl, textDirection: rtl ? "rtl" : "ltr" } },
  }, extra || {});
}
function newChart(id, cfg) {
  const ctx = $("#" + id);
  if (!ctx) return null;
  const old = Chart.getChart(ctx); if (old) old.destroy();
  return new Chart(ctx, cfg);
}
async function renderDashboard() {
  if (S.tab !== "dash" || !S.cat) return;
  const key = S.city + "|" + S.lang;
  if (S.dashKey === key) return;                      // مرسومة بالفعل بنفس المدينة واللغة
  S.dashKey = key;
  const kpi = $("#kpiCards");
  if (!S.stats) kpi.innerHTML = `<div class="stat-card"><div class="skel" style="height:150px;margin:10px 0"></div></div>`;
  const st = await loadStats();
  if (S.dashKey !== key) return;                      // تغيّرت المدينة/اللغة أثناء التحميل
  const sum = st && st.summary_stats, dist = st && st.distribution_stats;
  if (!sum) { kpi.innerHTML = `<div class="empty">${t("dash_empty")}</div>`; S.dashKey = null; return; }
  const n = sum.nasr, p = sum.ps, cur = S.city === "nasr" ? n : p, other = S.city === "nasr" ? p : n;
  const otherLbl = S.city === "nasr" ? t("cmp_ps") : t("cmp_nasr");
  try { await loadChart(); } catch (e) { toast(e.message, "err"); }
  if (S.dashKey !== key) return;
  const d = dist && dist[S.city];
  kpi.innerHTML = `<div class="stat-card">` +
    stat(t("kpi_served_b"), cur.buildings_pct["800"] + "%", `${otherLbl}: ${other.buildings_pct["800"]}%`, "ok") +
    stat(t("kpi_served_p"), cur.pop_pct_covered_proxy["800"] + "%", `${otherLbl}: ${other.pop_pct_covered_proxy["800"]}%`, "warn") +
    stat(t("kpi_avgd"), num(cur.avg_dist_m, 0) + " m", `${t("cmp_nasr")}: ${num(n.avg_dist_m, 0)} · ${t("cmp_ps")}: ${num(p.avg_dist_m, 0)}`) +
    (d ? stat(t("kpi_nn"), d.nn_ratio, `z = ${d.nn_z}`) : "") +
    stat(t("d_schools"), num(cur.n_schools_total, 0), `${T("حكومية (تقدير)", "government (est.)")}: ${num(cur.n_schools_gov_proxy, 0)}`) +
    stat(t("zones_covered"), S.city === "nasr" ? "8 / 41" : "5 / 31", T("شياخات بها مدرسة من العينة", "shiakhas with a sample school")) + `</div>`;

  if (!window.Chart) { if (d) renderDistStats(d); S.dashKey = null; return; }
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  Chart.defaults.color = "#5b6877"; Chart.defaults.borderColor = "#e4e8ee";
  Chart.defaults.elements.bar.borderRadius = 4; Chart.defaults.elements.bar.borderSkipped = false;
  const ths = ["400", "800", "1200"];
  S.charts.c1 = newChart("chartCoverage", { type: "bar", options: chartBase({ scales: { y: { beginAtZero: true, max: 100, title: { display: true, text: "%" } } } }),
    data: { labels: ths.map(x => x + " m"), datasets: [
      { label: `${cityName("nasr")} — ${t("d_buildings")}`, data: ths.map(x => n.buildings_pct[x]), backgroundColor: "#12355B" },
      { label: `${cityName("nasr")} — ${T("سكان", "people")}`, data: ths.map(x => n.pop_pct_covered_proxy[x]), backgroundColor: "#5B87B0" },
      { label: `${cityName("ps")} — ${t("d_buildings")}`, data: ths.map(x => p.buildings_pct[x]), backgroundColor: "#C8811A" },
      { label: `${cityName("ps")} — ${T("سكان", "people")}`, data: ths.map(x => p.pop_pct_covered_proxy[x]), backgroundColor: "#E8B36A" } ] } });
  S.charts.c2 = newChart("chartCities", { type: "bar", options: chartBase(),
    data: { labels: [t("cmp_nasr"), t("cmp_ps")], datasets: [
      { label: t("bldg_covered") + " 800m", data: [n.buildings_within["800"], p.buildings_within["800"]], backgroundColor: "#12355B" },
      { label: t("pop_covered") + " 800m", data: [n.pop2017_covered_proxy["800"], p.pop2017_covered_proxy["800"]], backgroundColor: "#C8811A" },
      { label: t("d_schools"), data: [n.n_schools_total, p.n_schools_total], backgroundColor: "#B3202B" } ] } });
  if (d) renderDistStats(d);
  // الحسابان الثقيلان يعملان بالتوازي وتُخزَّن نتائجهما في الذاكرة (والخادم) فلا يتكرران
  const [hs, cov] = await Promise.allSettled([
    postCached("/api/analysis/hotspot", { city: S.city, threshold: 800, cell: 250, band: 1000, min_bldg: 5 }),
    postCached("/api/analysis/coverage", { city: S.city, threshold: 800 }),
  ]);
  if (S.dashKey !== key) return;
  if (hs.status === "fulfilled" && hs.value.counts) {
    const labels = Object.keys(HS).filter(k => k in hs.value.counts);
    S.charts.c3 = newChart("chartHotspot", { type: "bar", options: chartBase({ plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, title: { display: true, text: T("خلايا", "cells") } } } }),
      data: { labels: labels.map(k => S.lang === "ar" ? HS[k][2].replace(/ \(.*\)/, "") : HS[k][1].replace(/ \(.*\)/, "")), datasets: [{ data: labels.map(k => hs.value.counts[k]), backgroundColor: labels.map(k => HS[k][0]), borderColor: "#cfd6df", borderWidth: labels.map(k => k === "Not significant" ? 1 : 0) }] } });
  }
  if (cov.status === "fulfilled") {
    const z = (cov.value.zones || []).slice(0, 10);
    S.charts.c4 = newChart("chartZones", { type: "bar", options: chartBase({ indexAxis: "y" }),
      data: { labels: z.map(x => x.shiakha.length > 22 ? x.shiakha.slice(0, 21) + "…" : x.shiakha), datasets: [
        { label: t("d_total"), data: z.map(x => x.n_bldg), backgroundColor: "#d5dbe3" },
        { label: t("d_within") + " 800m", data: z.map(x => x.within), backgroundColor: "#1E7B4F" } ] } });
    renderZoneTable(cov.value.zones || []);
  }
}
function renderZoneTable(zones) {
  $("#zoneTable").innerHTML = `<details><summary>${T("جدول الشياخات الكامل", "Full shiakha table")} (${zones.length})</summary>
    <div class="scroll"><table><thead><tr><th>${T("الشياخة", "Shiakha")}</th><th class="num">${t("d_buildings")}</th><th class="num">800m</th><th class="num">%</th></tr></thead>
    <tbody>${zones.map(z => `<tr><td>${esc(z.shiakha)}</td><td class="num">${num(z.n_bldg, 0)}</td><td class="num">${num(z.within, 0)}</td><td class="num">${esc(z.pct_bldg)}</td></tr>`).join("")}</tbody></table></div></details>`;
}
function renderDistStats(d) {
  $("#distStats").innerHTML =
    kv(T("المركز المتوسط", "Mean center"), `<bdi>${num(d.mean_x, 0)}, ${num(d.mean_y, 0)}</bdi>`) +
    kv(t("std_dist"), `${num(d.std_dist_m, 0)} m`) + kv("sx / sy", `${num(d.sx, 0)} / ${num(d.sy, 0)} m`) +
    kv(T("اتجاه الإهليلج", "Ellipse angle"), `${esc(d.theta_deg)}°`) +
    kv(T("أقرب جار: الفعلي / المتوقع", "NN mean / expected"), `${num(d.nn_mean_m, 0)} / ${num(d.nn_expected_m, 0)} m`) +
    kv(`${t("nn_ratio")} (z)`, `${esc(d.nn_ratio)} (${esc(d.nn_z)})`) +
    kv(T("التفسير", "Reading"), d.nn_ratio < 0.8 ? T("متجمّع", "Clustered") : T("عشوائي أو متباعد", "Random or dispersed"));
}

/* ------------------------------------------------ التحرير */
function renderEditSel() {
  if (!S.cat) return;
  const sel = $("#editLayerSel"), cur = sel.value;
  const items = cityMetas().filter(l => l.editable);
  sel.innerHTML = items.length
    ? items.map(l => `<option value="${esc(l.id)}">${esc(title(l))}</option>`).join("")
    : `<option value="">${t("ed_no_layers")}</option>`;
  if (cur && items.some(l => l.id === cur)) sel.value = cur;
  S.edit.layer = sel.value || null;
  updateEditForm();
}
const resetEditUi = () => { S.edit.mode = null; $$(".edit-actions button").forEach(b => b.classList.remove("active")); };
function editMeta() {
  const id = $("#editLayerSel").value;
  if (!id) { toast(t("d_pick_layer"), "err"); return null; }
  const meta = S.byId.get(id);
  if (!meta || !meta.editable) { toast(t("d_not_editable"), "err"); return null; }
  return meta;
}
function setEditMode(mode) {
  const meta = editMeta(); if (!meta) return;
  clearTool(); resetEditUi();
  S.edit.layer = meta.id; S.edit.mode = mode;
  const btn = { add: "#edAdd", modify: "#edModify", delete: "#edDelete" }[mode];
  $(btn).classList.add("active");
  if (mode === "add") { $("#edStatus").textContent = meta.geom === "point" ? t("d_draw_point") : T("انقر لإضافة النقاط، ونقرتان متتاليتان للإنهاء.", "Click to add points; double-click to finish."); startAddFeature(meta); }
  else {
    $("#edStatus").textContent = mode === "delete" ? T("انقر المعلم الذي تريد حذفه.", "Click the feature you want to delete.") : T("انقر المعلم الذي تريد تعديله.", "Click the feature you want to modify.");
    enablePick(meta, mode === "delete" ? "delete" : "update");
  }
}
function startAddFeature(meta) {
  startTool("add");
  const isPoint = meta.geom === "point", pts = [], dots = [];
  if (!isPoint) S.map.doubleClickZoom.disable();
  const grp = L.layerGroup().addTo(S.map); S.measure = grp;
  const done = (geo) => { clearTool(); openEditForm(meta, { properties: defaultProps(meta), geometry: geo }, null, true); };
  S._h = {
    click: e => {
      if (isPoint) { done({ type: "Point", coordinates: [e.latlng.lng, e.latlng.lat] }); return; }
      pts.push([e.latlng.lng, e.latlng.lat]);
      dots.push(L.circleMarker(e.latlng, { radius: 3.5, color: AMBER, fillColor: AMBER, fillOpacity: 1 }).addTo(grp));
      $("#edStatus").textContent = `${T("نقاط", "Points")}: ${pts.length} — ${T("نقرتان متتاليتان للإنهاء", "double-click to finish")}`;
    },
    dbl: isPoint ? null : () => {
      if (pts.length > 1) pts.pop();
      if (pts.length < (meta.geom === "line" ? 2 : 3)) return;
      done(meta.geom === "line" ? { type: "LineString", coordinates: pts } : { type: "Polygon", coordinates: [pts.concat([pts[0]])] });
    },
  };
  S.map.on("click", S._h.click);
  if (S._h.dbl) S.map.on("dblclick", S._h.dbl);
}
const defaultProps = (meta) => Object.fromEntries((meta.fields || []).map(f => [f, null]));
function enablePick(meta, action) {
  startTool("pick");
  showLayers([meta]).then(([rec]) => {
    if (S.tool !== "pick") return;                       // أُلغي أثناء التحميل
    S.edit.pick = rec;
    rec.llayer.eachLayer(l => {
      l.__editH = (ev) => {
        L.DomEvent.stop(ev);
        if (action === "delete") doDelete(meta, l.feature);
        else openEditForm(meta, l.feature, l, false);
      };
      l.on("click", l.__editH);
    });
  }).catch(e => toast(e.message, "err"));
}
function clearPick() {
  const rec = S.edit && S.edit.pick;
  if (rec && rec.llayer) rec.llayer.eachLayer(l => { if (l.__editH) { l.off("click", l.__editH); l.__editH = null; } });
  if (S.edit) S.edit.pick = null;
}
function openEditForm(meta, f, layerRef, isNew) {
  const p = f.properties || {}, fields = (meta.fields || []).slice(0, 40);
  const box = $("#edForm");
  box.hidden = false;
  box.innerHTML = `<b>${isNew ? t("ed_add") : t("ed_modify")} — ${esc(title(meta))}</b>
    <div class="row2" style="margin-top:8px">${fields.map(fl => `<div class="fld"><label>${esc(fl)}</label><input data-f="${esc(fl)}" value="${esc(p[fl])}"></div>`).join("")}</div>
    <div class="form-actions"><button class="ok" id="edSave">${t("save")}</button><button id="edDiscard">${t("ed_cancel")}</button></div>`;
  $("#edSave").onclick = async () => {
    const props = {};
    $$("#edForm input[data-f]").forEach(i => {
      const orig = p[i.dataset.f];
      let v = i.value;
      if (v === "") v = null; else if (typeof orig === "number") v = Number(v);
      props[i.dataset.f] = v;
    });
    await doSave(meta, isNew ? "create" : "update", { type: "Feature", properties: props, geometry: f.geometry }, isNew ? null : f.id);
    box.hidden = true;
  };
  $("#edDiscard").onclick = () => { box.hidden = true; clearTool(); resetEditUi(); updateEditForm(); };
  box.scrollIntoView({ behavior: "smooth", block: "nearest" });
}
async function doSave(meta, action, feature, fid) {
  loading(true);
  try {
    await post("/api/edit", { layer: meta.id, action, feature, fid });
    pushLog(action, meta.id, fid || "new");
    toast(action === "create" ? t("d_added") : action === "delete" ? t("d_deleted") : t("d_updated"), "ok");
    clearTool();
    await refreshLayer(meta);
    if (S.tab === "table") loadTable();
  } catch (e) { toast(e.message, "err"); }
  finally { loading(false); resetEditUi(); updateEditForm(); }
}
async function doDelete(meta, f) {
  if (!confirm(t("confirm_delete"))) return;
  await doSave(meta, "delete", null, f.id);
}
function pushLog(action, layer, fid) {
  const tag = action === "create" ? "add" : action === "delete" ? "del" : "";
  const label = action === "create" ? t("d_added") : action === "delete" ? t("d_deleted") : t("d_updated");
  S.edit.log.unshift({ layer, fid, label, tag, time: new Date().toLocaleTimeString(S.lang === "ar" ? "ar-EG" : "en-GB") });
  renderLog();
}
function renderLog() {
  $("#edLog").innerHTML = S.edit.log.map(e =>
    `<li><span>${esc(e.layer)} <small>#${esc(e.fid)}</small></span><span><span class="tag ${e.tag}">${esc(e.label)}</span> ${esc(e.time)}</span></li>`).join("");
}
function updateEditForm() {
  const meta = S.byId.get($("#editLayerSel").value);
  $("#edForm").hidden = true;
  $("#edStatus").textContent = meta ? `${T("الطبقة", "Layer")}: ${title(meta)} — ${meta.editable ? t("edit_layer_rw") : t("edit_layer_ro")}` : "";
  ["#edAdd", "#edModify", "#edDelete"].forEach(s => { $(s).disabled = !meta; });
}

/* ------------------------------------------------ مفتاح أسماء المدارس */
function updateNamesButton() {
  const b = $("#btnNames"); if (!b) return;
  b.setAttribute("aria-checked", S.showNames);
  b.title = S.showNames ? t("names_hide") : t("names_show");
  b.querySelector("use").setAttribute("href", S.showNames ? "#i-eye" : "#i-eye-off");
}
function setShowNames(on, silent) {
  S.showNames = !!on;
  document.documentElement.dataset.names = S.showNames ? "on" : "off";
  updateNamesButton();
  // تسميات الخريطة: تُربط أو تُفكّ دون إعادة بناء الطبقات
  for (const [, r] of S.layers) {
    const lbl = r.llayer && r.meta.style && r.meta.style.label && r.meta.style.label.field;
    if (!lbl || !NAME_FIELDS.has(lbl)) continue;
    r.llayer.eachLayer(l => { if (l.__label == null) return; if (S.showNames) bindLabel(r.meta, l); else l.unbindTooltip(); });
  }
  if (S.map) S.map.closePopup();                                  // نافذة مفتوحة قد تحمل اسمًا
  if (TBL.sort && nameHidden(TBL.sort)) TBL.sort = null;
  if (S.tab === "table" && TBL.meta) drawTable();
  if (S.cat && R().rebuild) paintResults();
  if (!silent) toast(S.showNames ? t("names_shown_toast") : t("names_hidden_toast"), "ok");
}

/* ------------------------------------------------ مساعدة */
function openHelp() {
  const ar = S.lang === "ar", nMaps = S.cat.maps.length;
  $("#helpBody").innerHTML = ar ? `
    <h4>ما هذه المنصة؟</h4>
    <p>منصة ويب لعرض طبقات مشروع «روضات جيل ألفا» وتحريرها وتحليلها، بنفس عناوين وألوان خرائط QGIS الأصلية (${nMaps} خرائط) ونفس التحليلات، مع أدوات إضافية.</p>
    <h4>التبويبات</h4>
    <ul>
      <li><b>الطبقات</b> — إظهار وإخفاء، شفافية، ترتيب، وتكبير، مع مفتاح ألوان لكل طبقة.</li>
      <li><b>الخرائط</b> — الخرائط الأصلية وخريطة المدينة التعليمية بعناوينها وطبقاتها.</li>
      <li><b>التحليل</b> — نطاقات الخدمة، التغطية، التداخل، Gi*، التوزيع المكاني، KDE، وأقرب مدرسة من أي نقطة، مع أدوات القياس والبفر.</li>
      <li><b>الجدول</b> — جدول الخصائص بالفرز والبحث والتصدير إلى CSV وGeoJSON.</li>
      <li><b>المؤشرات</b> — أرقام ورسوم من تقرير المشروع.</li>
      <li><b>التحرير</b> — إضافة وتعديل وحذف المعلم؛ يُحفظ في <code>alpha_accessibility_edited.gpkg</code>.</li>
    </ul>
    <h4>ملاحظات من التقرير</h4>
    <ul>${S.cat.limitations.map(l => `<li>${esc(l.ar)}</li>`).join("")}</ul>`
  : `
    <h4>What is this?</h4>
    <p>A web GIS to view, edit and analyse the Alpha Generation KG-schools layers, with the same titles and colours as the original QGIS maps (${nMaps} maps), the same analyses, and a few extra tools.</p>
    <h4>Tabs</h4>
    <ul>
      <li><b>Layers</b> — show/hide, opacity, order and zoom, with a legend for each layer.</li>
      <li><b>Maps</b> — the original maps and the Education City map with their titles and layers.</li>
      <li><b>Analysis</b> — service areas, coverage, overlaps, Gi*, spatial distribution, KDE and nearest school from any point, plus measuring and buffer tools.</li>
      <li><b>Table</b> — attribute table with sorting, search and CSV/GeoJSON export.</li>
      <li><b>Insights</b> — figures and charts from the project report.</li>
      <li><b>Edit</b> — add, modify and delete features; saved to <code>alpha_accessibility_edited.gpkg</code>.</li>
    </ul>
    <h4>Caveats from the report</h4>
    <ul>${S.cat.limitations.map(l => `<li>${esc(l.en)}</li>`).join("")}</ul>`;
  $("#helpModal").showModal();
}

/* ------------------------------------------------ التبويبات واللوحة */
function selectTab(name) {
  const same = S.tab === name, panel = $("#panel");
  S.tab = name;
  $$("#tabs button").forEach(b => { const on = b.dataset.tab === name; b.classList.toggle("active", on); b.setAttribute("aria-selected", on); b.tabIndex = on ? 0 : -1; });
  $$(".tab-page").forEach(p => p.classList.toggle("active", p.dataset.page === name));
  if (isNarrow()) panel.classList.toggle("collapsed", same && !panel.classList.contains("collapsed"));
  if (name === "table") renderTableSel();
  if (name === "edit") renderEditSel();
  if (name === "dash") renderDashboard();
}

/* ------------------------------------------------ الربط */
function wire() {
  $("#tabs").addEventListener("click", e => { const b = e.target.closest("button[data-tab]"); if (b) selectTab(b.dataset.tab); });
  $("#tabs").addEventListener("keydown", e => {                 // أسهم لوحة المفاتيح بين التبويبات
    const keys = { ArrowDown: 1, ArrowUp: -1, Home: "first", End: "last" };
    if (!(e.key in keys)) return;
    const tabs = $$("#tabs button"), i = tabs.indexOf(document.activeElement);
    if (i < 0) return;
    e.preventDefault();
    const k = keys[e.key], j = k === "first" ? 0 : k === "last" ? tabs.length - 1 : (i + k + tabs.length) % tabs.length;
    tabs[j].focus(); selectTab(tabs[j].dataset.tab);
  });
  $("#tabs [data-tab=dash]").addEventListener("pointerenter", () => loadChart().catch(() => {}), { once: true });
  $("#btnNames").onclick = () => setShowNames(!S.showNames);
  $("#panelToggle").onclick = () => $("#panel").classList.toggle("collapsed");
  $("#citySeg").addEventListener("click", e => { const b = e.target.closest("button[data-city]"); if (b) setCity(b.dataset.city); });
  $("#langSeg").addEventListener("click", e => {
    const b = e.target.closest("button[data-lang]"); if (!b || b.dataset.lang === S.lang) return;
    S.lang = b.dataset.lang; LANG = S.lang; localStorage.setItem("alpha_lang", S.lang);
    if (S.cat && (hasResult() || R().layer)) clearAnalysis(true);
    applyI18n();
  });
  $("#basemapSel").onchange = e => setBasemap(e.target.value);

  wireTree();
  $("#lyrAllOn").onclick = async () => {
    loading(true);
    try { await showLayers(S.cat.layers.filter(l => l.city === S.city && l.default_on)); } catch (e) { toast(e.message, "err"); } finally { loading(false); }
  };
  $("#lyrAllOff").onclick = () => { hideAll(); S.layers.forEach(r => syncItem(r.meta)); renderLegend(); if (S.activeMap) leavePreset(); };
  $("#lyrFilter").oninput = debounce(drawLayerTree, 120);
  $("#mbClose").onclick = leavePreset;
  $("#legendHead").onclick = () => { const c = $("#legend").classList.toggle("collapsed"); $("#legendHead").setAttribute("aria-expanded", !c); };
  $("#anBadgeClose").onclick = clearAnalysis;

  $("#thSeg").addEventListener("click", e => {
    const b = e.target.closest("button[data-th]"); if (!b) return;
    setPressed($("#thSeg"), x => x === b);
    $("#thCustom").hidden = b.dataset.th !== "custom";
    updateWalk();
  });
  $("#thCustom").oninput = updateWalk;
  $("#anService").onclick = runServiceArea; $("#anCoverage").onclick = runCoverage; $("#anOverlap").onclick = runOverlap;
  $("#anHotspot").onclick = runHotspot; $("#anDist").onclick = runDistribution; $("#anKde").onclick = runKde;
  $("#anNearest").onclick = startNearest;
  $("#anClear").onclick = () => { clearAnalysis(); toast(t("d_clear")); };
  $("#toolMeasure").onclick = () => (S.tool === "measure" ? clearTool() : startMeasure("dist"));
  $("#toolArea").onclick = () => (S.tool === "area" ? clearTool() : startMeasure("area"));
  $("#toolBuffer").onclick = () => (S.tool === "buffer" ? clearTool() : startBuffer());
  $("#toolIdentify").onclick = toggleIdentify;

  $("#tableLayerSel").onchange = loadTable;
  $("#tblSearch").oninput = debounce(() => { TBL.limit = 300; drawTable(); }, 150);
  $("#tblCsv").onclick = exportCsv; $("#tblGeo").onclick = () => exportGeo();
  $("#attrTable thead").addEventListener("click", e => {
    const th = e.target.closest("th"); if (!th) return;
    const c = th.dataset.c;
    if (nameHidden(c)) return;                                  // الفرز بعمود مخفي يكشف الترتيب
    if (TBL.sort === c) TBL.dir *= -1; else { TBL.sort = c; TBL.dir = 1; }
    drawTable();
  });
  $("#attrTable tbody").addEventListener("click", e => {
    const tr = e.target.closest("tr"); if (!tr) return;
    $$("#attrTable tr.sel").forEach(x => x.classList.remove("sel"));
    tr.classList.add("sel");
    const r = TBL.view[+tr.dataset.i]; if (r) focusFeature(r.__fid);
  });
  $("#tblInfo").addEventListener("click", e => { if (e.target.id === "tblMore") { TBL.limit += 300; drawTable(); } });

  $("#editLayerSel").onchange = () => { clearTool(); resetEditUi(); updateEditForm(); };
  $("#edAdd").onclick = () => setEditMode("add");
  $("#edModify").onclick = () => setEditMode("modify");
  $("#edDelete").onclick = () => setEditMode("delete");
  $("#edCancel").onclick = () => { clearTool(); resetEditUi(); $("#edForm").hidden = true; updateEditForm(); };
  $("#edExport").onclick = () => { const id = $("#editLayerSel").value; if (!id) toast(t("d_pick_layer"), "err"); else exportGeo(id); };

  $("#fmClose").onclick = () => $("#featModal").close();
  $("#helpClose").onclick = () => $("#helpModal").close();
  for (const d of $$("dialog")) d.addEventListener("click", e => { if (e.target === d) d.close(); });   // النقر على الخلفية يغلق
  $("#btnHelp").onclick = openHelp;
  $("#btnPrint").onclick = () => window.print();
  document.addEventListener("keydown", e => { if (e.key === "Escape" && !$("dialog[open]")) clearTool(); });
  let rs; window.addEventListener("resize", () => { clearTimeout(rs); rs = setTimeout(() => S.map.invalidateSize(), 120); });
}

/* ------------------------------------------------ الإقلاع */
async function boot() {
  initMap();
  wire();
  setShowNames(false, true);                         // الافتراضي: الأسماء مخفية
  applyI18n();
  showAnalysisEmpty();
  $$("#tabs button").forEach(b => { b.tabIndex = b.classList.contains("active") ? 0 : -1; });
  if (isNarrow()) $("#panel").classList.add("collapsed");
  loading(true);
  try {
    S.cat = await api("/api/catalog");
    S.rasterIds = new Set(S.cat.rasters.map(r => r.id));
    for (const m of [...S.cat.layers, ...S.cat.edu_layers, ...S.cat.rasters]) if (!S.byId.has(m.id)) S.byId.set(m.id, m);
    drawLayerTree(); renderMapList(); renderEditSel();
    renderTableSel();                                   // يملأ القائمة فقط؛ البيانات تُحمَّل عند فتح التبويب
    loadCityDefaults().then(prefetchLikely);            // الواجهة تعمل من الآن؛ والتحضير يتم وقت الفراغ
  } catch (e) {
    console.error(e);
    toast(e.message, "err");
  } finally { loading(false); }
}
/* وقت فراغ المتصفح: مكتبة الرسوم ونتائج لوحة المؤشرات الافتراضية، فيفتح التبويب والتحليل فورًا */
function prefetchLikely() {
  if (navigator.connection && navigator.connection.saveData) return;
  idle(() => {
    loadChart().catch(() => {});
    postCached("/api/analysis/hotspot", { city: S.city, threshold: 800, cell: 250, band: 1000, min_bldg: 5 }).catch(() => {});
    postCached("/api/analysis/coverage", { city: S.city, threshold: 800 }).catch(() => {});
  });
}
document.addEventListener("DOMContentLoaded", boot);
