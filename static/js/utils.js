/* ================================================================ outils
   Petites fonctions utilisées partout :
     $(sélecteur)     le premier élément de la page qui correspond
     esc(texte)       texte sans danger à insérer dans du HTML (un nom de fichier ne peut rien casser)
     plural, kwN      « 3 dossiers », « 1 mot-clé »
     ic(nom)          une icône (dessin SVG au trait)
     api(url)         appel au serveur ; si le profil est verrouillé, l'écran du code apparaît
     jpost(url, data) envoi de données au serveur (JSON) */
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const plural = (n, w) => `${n} ${w}${n > 1 ? "s" : ""}`;
const kwN = n => `${n} ${n > 1 ? "mots-clés" : "mot-clé"}`;
const store = { get(k, d){ try{ const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); }catch{ return d; } },
                set(k, v){ try{ localStorage.setItem(k, JSON.stringify(v)); }catch{} } };
const ICON = {
  plus:'<path d="M12 5v14M5 12h14"/>', back:'<path d="M15 5l-7 7 7 7"/>', chev:'<path d="M9.5 6l6 6-6 6"/>',
  more:'<circle cx="6" cy="12" r=".7"/><circle cx="12" cy="12" r=".7"/><circle cx="18" cy="12" r=".7"/>',
  upload:'<path d="M12 16V5M7 10l5-5 5 5M5 19h14"/>', download:'<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
  refresh:'<path d="M20 12a8 8 0 1 1-2.6-5.9M20 4v5h-5"/>', x:'<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
  info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>', swap:'<path d="M4 8h13l-3-3M20 16H7l3 3"/>',
  check:'<path d="M5 12.5l4.5 4.5L19 7.5"/>', lock:'<rect x="5" y="11" width="14" height="9" rx="2.5"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
  del:'<path d="M20 6H9l-6 6 6 6h11a1 1 0 0 0 1-1V7a1 1 0 0 0-1-1zM12 9.5l5 5M17 9.5l-5 5"/>', edit:'<path d="M4 20h4L19 9l-4-4L4 16z"/>',
  trash:'<path d="M4 7h16M9 7V4h6v3M6.5 7l1 13h9l1-13"/>', tag:'<path d="M3.5 12.2V5.5a2 2 0 0 1 2-2h6.7l8.3 8.3a2 2 0 0 1 0 2.8l-5.9 5.9a2 2 0 0 1-2.8 0z"/><circle cx="8" cy="8" r="1.4"/>',
  eye:'<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>',
  sliders:'<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
  folder:'<path d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2.2h7a2 2 0 0 1 2 2v7.8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
  grid:'<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><path d="M3.5 9.5h17M9 9.5v10"/>'
};
const ic = (n, cls = "") => `<svg class="i ${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICON[n]}</svg>`;
document.querySelector('[data-action="new"]').innerHTML = ic("plus") + "Nouveau";
/* les quatre décisions : leur nom, et la couleur du surligneur (ok = vert, rev = jaune, doubt = pointillé) */
const LONG  = {present:"Présent", a_verifier:"À vérifier", absent:"Absent", absent_douteux:"Absence incertaine"};
const HL    = {present:"ok", a_verifier:"rev", absent_douteux:"doubt", absent:""};
const STATUS = {en_attente:["En attente",""], en_cours:["Analyse en cours","run"], ok:["Lu",""], erreur:["Illisible","err"]};
const calm = matchMedia("(prefers-reduced-motion:reduce)");

function toast(msg){ const t = $("#toast"); t.textContent = msg; t.classList.add("on"); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("on"), 2800); }
async function api(url, opts = {}){
  const r = await fetch(url, opts);
  if(r.status === 401){ showLock({step:"choose"}); throw new Error("verrouillé"); }   // session expirée ou verrouillée
  if(!r.ok){
    const msg = (await r.text()).replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
    const m = msg.match(/(?:Bad Request|Forbidden|Conflict|Not Found|Too Many Requests)\s+(.*)/);
    const e = new Error((m ? m[1] : msg).slice(0, 140)); e.status = r.status;
    if(!opts.quiet) toast(e.message);
    throw e;
  }
  return r.json();
}
const jpost = (url, body, method = "POST") => api(url, {method, headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)});
const initials = s => (s || "?").replace(/[_-]+/g, " ").trim().split(/\s+/).slice(0, 2).map(w => w[0]).join("").toUpperCase();
/* une couleur d'encre par profil, pour voir d'un coup d'œil qui est connecté */
const INKS = ["#2B4ACB", "#0F7A5C", "#8A3FB0", "#B4502B"];
const profStyle = o => `--pa:${INKS[Math.max(0, (state.settings.operators || []).indexOf(o)) % INKS.length]}`;
