/* ================================================================ état & navigation
   « state » contient tout ce que le serveur a envoyé (/api/results) : les dossiers du prof, leurs documents,
   leurs mots-clés et les décisions. L'adresse dans la barre (#/dossier/12, #/comparer…) dit quelle page afficher.
   Après chaque changement, load() redemande les résultats puis render() redessine ce qui a changé. */
let state = {keywords:[], dossiers:[], settings:{}};
let currentOp = store.get("ks_op", null);
let dossierTab = "kw";
let pollTimer = null, lastPage = null, lastDossier = null, railFilter = "";

function route(){
  const [p, id] = location.hash.replace(/^#\/?/, "").split("/");
  if(p === "dossier" && id) return {page:"dossier", id:+id};
  if(p === "mots-cles" || p === "reglages" || p === "comparer") return {page:p};
  return {page:"dossiers"};
}
const go = h => { if(location.hash === h) render(true); else location.hash = h; };
window.addEventListener("hashchange", () => { closeMenu(); render(true); });

async function load(animate, passive){
  clearTimeout(pollTimer);
  try{ state = await api("/api/results", passive ? {headers:{"X-Passive":"1"}} : {}); }
  catch(e){ return; }
  currentOp = state.settings.profile || currentOp;
  render(animate);
  // pendant une analyse : rafraîchissement discret (ne compte pas comme activité pour le verrouillage auto)
  if(state.dossiers.some(d => d.pending)) pollTimer = setTimeout(() => load(false, true), 1500);
}

/* Clics fiables : si on appuie sur un bouton et qu'on relâche juste à côté, le navigateur envoie le clic
   au parent. On retient l'élément sous le doigt au moment de l'appui et on le reprend si besoin.
   Le rafraîchissement automatique attend aussi la fin d'un appui (sinon le bouton disparaît sous le doigt). */
let pressed = null, pressT = 0, pointerDown = false, deferredRender = false;
document.addEventListener("pointerdown", e => { pressed = e.target; pressT = performance.now(); pointerDown = true; }, {capture:true, passive:true});
const releasePointer = () => { pointerDown = false; if(deferredRender){ deferredRender = false; setTimeout(() => render(false), 0); } };
document.addEventListener("pointerup", releasePointer, {capture:true, passive:true});
document.addEventListener("pointercancel", releasePointer, {capture:true, passive:true});
function clickTarget(e, sel){
  const t = e.target.closest(sel);
  if(t) return t;
  if(pressed && pressed.isConnected && performance.now() - pressT < 800){
    const p = pressed.closest(sel);
    if(p && (p.contains(e.target) || e.target.contains(p))) return p;
  }
  return null;
}

/* mise à jour d'une zone : rien si rien n'a changé ; si seuls les compteurs d'avancement ont bougé, on les patche
   sur place (les barres glissent, pas de clignotement) ; sinon on remplace le contenu */
const stripProgress = h => h.replace(/(data-pg="[^"]+">)[^<]*</g, "$1<").replace(/--p:[\d.]+/g, "--p:_");
function paint(el, html, force){
  if(!force && html === el._html) return false;
  if(!force && el._html && stripProgress(html) === stripProgress(el._html)){
    const t = document.createElement("template"); t.innerHTML = html;
    t.content.querySelectorAll("[data-pg]").forEach(n => { const o = el.querySelector(`[data-pg="${n.dataset.pg}"]`); if(o) o.textContent = n.textContent; });
    t.content.querySelectorAll("[data-bar]").forEach(n => { const o = el.querySelector(`[data-bar="${n.dataset.bar}"]`); if(o) o.style.setProperty("--p", n.style.getPropertyValue("--p")); });
    el._html = html; return false;
  }
  el._html = html; el.innerHTML = html; return true;
}

function render(animate){
  const r = route();
  if(!animate && pointerDown){ deferredRender = true; return; }
  renderChrome(r);
  const desk = $("#desk");
  desk.classList.toggle("full", r.page === "mots-cles" || r.page === "reglages" || r.page === "comparer");
  desk.classList.toggle("open", r.page === "dossier");
  paint($("#rail"), railHtml(r));
  $("#railSum").textContent = railSummary();
  // les pages de saisie ne sont pas redessinées par le rafraîchissement automatique (on ne perd pas la frappe)
  if(!animate && r.page === lastPage && (r.page === "mots-cles" || r.page === "reglages")) return;
  const v = $("#view");
  const opening = r.page === "dossier" && (animate || lastDossier !== r.id);
  const wide = v.querySelector("[data-keep-scroll]"), scrollLeft = wide ? wide.scrollLeft : 0;   // tableau large : on garde sa position
  const changed = paint(v, PAGES[r.page](r), animate);
  if(changed && !animate && scrollLeft){ const w = v.querySelector("[data-keep-scroll]"); if(w) w.scrollLeft = scrollLeft; }
  if(changed && (animate || opening)) v.scrollTop = 0;
  if(changed && opening && !calm.matches){ v.classList.remove("reveal"); void v.offsetWidth; v.classList.add("reveal"); }
  lastPage = r.page; lastDossier = r.page === "dossier" ? r.id : null;
}

const fmtEta = s => s == null ? "" : s < 50 ? "moins d'une minute" : `environ ${Math.round(s / 60)} min`;
function prog(d){   // avancement cumulé des documents d'un dossier
  let done = 0, total = 0, eta = null;
  d.documents.forEach(x => { if(x.progress){ done += x.progress.done; total += x.progress.total; if(x.progress.eta != null) eta = Math.max(eta || 0, x.progress.eta); } });
  return {done, total, eta, p: total ? done / total : 0};
}

function renderChrome(r){
  const active = r.page === "dossier" ? "dossiers" : r.page;
  document.querySelectorAll(".nav a").forEach(a => {
    if(a.dataset.tab === active) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  const av = $("#avatar");
  const html = `<span>${esc(currentOp || "")}</span><span class="ini" style="${profStyle(currentOp)}">${esc(initials(currentOp))}</span>`;
  if(av._html !== html){ av._html = html; av.innerHTML = html; }
  av.title = "Changer de profil ou verrouiller";
}

/* ================================================================ résumé d'un dossier
   summary(d) compte les décisions d'un dossier ; tally(d) dessine la petite bande colorée (une case par mot-clé). */
function summary(d){
  const ready = d.documents.some(x => x.status === "ok");
  const c = {present:0, a_verifier:0, absent:0, absent_douteux:0};
  if(ready) d.keywords.forEach(k => { const x = d.cells[k.id]; if(x) c[x.decision]++; });
  return {ready, c, total:d.keywords.length};
}
function tally(d){
  const {ready} = summary(d);
  const cells = d.keywords.map(k => d.cells[k.id]).filter(Boolean).sort((a, b) => order(a.decision) - order(b.decision));
  return `<span class="tally" aria-hidden="true">${(ready ? cells : d.keywords).map(c => `<i class="${ready ? HL[c.decision] : ""}"></i>`).join("")}</span>`;
}
const order = dec => ({present:0, a_verifier:1, absent_douteux:2, absent:3}[dec]);
function verdictText(d){
  const {ready, c, total} = summary(d);
  if(!total) return "Aucun mot-clé à rechercher.";
  if(!ready) return d.pending ? "Lecture des documents en cours." : d.documents.length ? "Aucun document lisible." : "Aucun document pour l'instant.";
  let s = `${c.present} ${c.present > 1 ? "mots-clés trouvés" : "mot-clé trouvé"} sur ${total}`;
  if(c.a_verifier) s += `, ${c.a_verifier} à vérifier`;
  return s + ".";
}

/* ================================================================ colonne des dossiers (à gauche) */
function railSummary(){
  const D = state.dossiers, p = D.reduce((a, d) => a + d.pending, 0);
  if(!D.length) return "";
  return `${plural(D.length, "dossier")}` + (p ? `, ${plural(p, "document")} en lecture` : "");
}
function railHtml(r){
  const q = railFilter.trim().toLowerCase();
  const D = state.dossiers.filter(d => !q || d.name.toLowerCase().includes(q));
  if(!state.dossiers.length) return `<p class="note" style="padding:0 6px">Les dossiers créés apparaîtront ici.</p>`;
  if(!D.length) return `<p class="note" style="padding:0 6px">Aucun candidat ne correspond à « ${esc(railFilter)} ».</p>`;
  return D.map(d => {
    const {ready, c} = summary(d), q2 = prog(d);
    let sub;
    if(d.pending) sub = `<span data-pg="r${d.id}">${q2.total ? `Lecture : ${q2.done} pages sur ${q2.total}` : "En attente de lecture"}</span>`;
    else if(!d.documents.length) sub = "Aucun document";
    else if(!ready) sub = "Aucun document lisible";
    else sub = `${c.present} sur ${d.keywords.length}` + (c.a_verifier ? `, <span class="warn">${c.a_verifier} à vérifier</span>` : "");
    if(d.unread.length) sub += `, <span class="bad">${d.unread.length} illisible${d.unread.length > 1 ? "s" : ""}</span>`;
    return `<a class="item" href="#/dossier/${d.id}" ${r.page === "dossier" && r.id === d.id ? 'aria-current="page"' : ""}>
      <b>${esc(d.name)}</b><small>${sub}</small>
      ${d.pending ? `<span class="pbar"><i data-bar="r${d.id}" style="--p:${q2.p.toFixed(3)}"></i></span>` : tally(d)}</a>`;
  }).join("");
}
