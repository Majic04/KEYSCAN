/* ================================================================ écran du code PIN
   Étapes : choose (qui êtes-vous ?) → pin (saisie) | setup1/setup2 (création) | change-old/new/confirm (changement) */
let L = null;
let profilesCache = [], updatedTo = null;
let idleMs = 30 * 60 * 1000, lastInput = Date.now();

async function boot(){
  let sess;
  try{ sess = await api("/api/session"); }catch{ return; }
  profilesCache = sess.profiles; idleMs = sess.idle_minutes * 60 * 1000;
  state.settings.operators = sess.profiles.map(p => p.name);
  if(sess.owner){ currentOp = sess.owner; await load(true); }
  else showLock({step:"choose"});
}
async function lockNow(){
  try{ await fetch("/api/lock", {method:"POST"}); }catch{}
  showLock({step:"choose"});
}
async function showLock(opts){
  closeMenu(); if($("#mwrap").classList.contains("on")) closeModal(null);
  if(opts.step === "choose" || !opts.cancelable){
    clearTimeout(pollTimer);
    ["#view", "#rail"].forEach(s => { $(s).innerHTML = ""; $(s)._html = ""; });
    $("#railSum").textContent = ""; state.dossiers = []; state.keywords = [];   // rien ne reste visible derrière
  }
  try{ const sess = await (await fetch("/api/session")).json(); profilesCache = sess.profiles; updatedTo = sess.updated_to; state.settings.operators = sess.profiles.map(p => p.name); }catch{}
  L = {buf:"", msg:"", err:false, ...opts};
  if(L.step === "pin" && !L.len){ const pr = profilesCache.find(x => x.name === L.owner); L.len = pr && pr.pin_len; }
  drawLock();
  const el = $("#lock"); el.classList.add("on"); el.setAttribute("aria-hidden", "false");
}
function hideLock(){ L = null; const el = $("#lock"); el.classList.remove("on"); el.setAttribute("aria-hidden", "true"); }

const LOCK_TEXT = {
  pin:              ["Votre code", ""],
  setup1:           ["Créez votre code", "4 à 8 chiffres, demandés à chaque ouverture de votre profil"],
  setup2:           ["Saisissez-le une seconde fois", ""],
  "change-old":     ["Code actuel", ""],
  "change-new":     ["Nouveau code", "4 à 8 chiffres"],
  "change-confirm": ["Saisissez-le une seconde fois", ""],
};
function drawLock(){
  const el = $("#lock");
  if(L.step === "choose"){
    el.innerHTML = `<div class="lock-in"><div class="brand big"><img src="/static/logo.svg" alt="">KeyScan</div><h2>Qui ouvre KeyScan ?</h2>
      ${updatedTo ? `<p class="update">KeyScan est passé à la version ${esc(updatedTo)}. Pour la sécurité, chaque profil choisit un nouveau code. Les dossiers et mots-clés sont conservés.</p>` : ""}
      <div class="people-pick">${profilesCache.map(p => `<button class="pick" data-pick="${esc(p.name)}">
        <span class="ini" style="${profStyle(p.name)}">${esc(initials(p.name))}</span><span><b>${esc(p.name)}</b>
        <small>${p.has_pin ? plural(p.dossiers, "dossier") : "Code à créer"}</small></span></button>`).join("")}</div></div>`;
    return;
  }
  const [title, hint] = LOCK_TEXT[L.step];
  const fixed = (L.step === "pin" || L.step === "change-old") ? L.len : (L.step === "setup2" || L.step === "change-confirm") ? L.first.length : 0;
  const n = fixed || Math.max(4, L.buf.length);
  const showOk = !fixed;
  el.innerHTML = `<div class="lock-in">
    <div class="brand big"><img src="/static/logo.svg" alt="">KeyScan</div>
    <h2>${esc(title)}</h2><p class="msub ${L.err ? "err" : ""}">${esc(L.msg || hint || L.owner)}</p>
    <div class="dots" id="dots">${Array.from({length:n}, (_, i) => `<i class="${i < L.buf.length ? "on" : ""}"></i>`).join("")}</div>
    <div class="pad">${[1, 2, 3, 4, 5, 6, 7, 8, 9].map(k => `<button class="key" data-key="${k}">${k}</button>`).join("")}
      <button class="key txt" data-key="back">${L.cancelable ? "Annuler" : "Retour"}</button><button class="key" data-key="0">0</button>
      ${showOk && L.buf.length >= 4 ? `<button class="key txt" data-key="ok" style="color:var(--pen)">Valider</button>` : `<button class="key txt" data-key="del" aria-label="Effacer" ${L.buf ? "" : "disabled"}>${ic("del")}</button>`}</div>
    ${L.step === "pin" ? `<p style="margin-top:18px"><button class="textlink" data-key="forgot">Code oublié</button></p>
      <p class="forgot" id="forgot">Fermez KeyScan puis, sur cet ordinateur, lancez dans un Terminal :
      <code>${navigator.platform.startsWith("Win") ? `"%LOCALAPPDATA%\\Programs\\KeyScan\\KeyScan.exe"` : "/Applications/KeyScan.app/Contents/MacOS/KeyScan"} --reset-pin "${esc(L.owner)}"</code>
      Avec Python : <code>python app.py --reset-pin "${esc(L.owner)}"</code>Un nouveau code sera demandé à la prochaine ouverture.</p>` : ""}
  </div>`;
}
function lockError(msg){
  L.buf = ""; L.msg = msg; L.err = true; drawLock();
  const d = $("#dots"); d.classList.remove("shake"); void d.offsetWidth; d.classList.add("shake");
}
async function lockKey(k){
  if(!L) return;
  if(k === "forgot"){ $("#forgot").classList.toggle("on"); return; }
  if(k === "back"){ if(L.cancelable){ hideLock(); return; } return showLock({step:"choose"}); }
  if(k === "del"){ L.buf = L.buf.slice(0, -1); L.err = false; L.msg = ""; return drawLock(); }
  const fixed = (L.step === "pin" || L.step === "change-old") ? L.len : (L.step === "setup2" || L.step === "change-confirm") ? L.first.length : 0;
  if(k === "ok"){ if(!fixed && L.buf.length >= 4) return lockSubmit(); return; }
  if(!/^\d$/.test(k) || L.buf.length >= (fixed || 8)) return;
  L.buf += k; L.err = false; L.msg = ""; drawLock();
  if(fixed && L.buf.length === fixed) setTimeout(lockSubmit, 120);   // saisie complète : validation automatique
}
async function lockSubmit(){
  const pin = L.buf;
  const post = (url, body) => api(url, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body), quiet:true});
  try{
    if(L.step === "pin"){ await post("/api/unlock", {owner:L.owner, pin}); return enterProfile(L.owner); }
    if(L.step === "setup1"){ L.first = pin; L.buf = ""; L.step = "setup2"; return drawLock(); }
    if(L.step === "setup2"){
      if(pin !== L.first){ L.step = "setup1"; L.first = null; return lockError("Les deux codes sont différents, recommencez"); }
      await post("/api/pin/setup", {owner:L.owner, pin}); toast("Code créé"); return enterProfile(L.owner);
    }
    if(L.step === "change-old"){ L.old = pin; L.buf = ""; L.step = "change-new"; return drawLock(); }
    if(L.step === "change-new"){ L.first = pin; L.buf = ""; L.step = "change-confirm"; return drawLock(); }
    if(L.step === "change-confirm"){
      if(pin !== L.first){ L.step = "change-new"; L.first = null; return lockError("Les deux codes sont différents, recommencez"); }
      await post("/api/pin/change", {old:L.old, new:pin}); hideLock(); toast("Code modifié"); return;
    }
  }catch(e){
    if(e.message === "verrouillé") return;
    if(L.step === "change-confirm"){ L.step = "change-old"; L.old = L.first = null; }   // ancien code faux : on recommence
    lockError(e.status === 403 ? (L.step === "change-old" ? "Code actuel incorrect" : "Code incorrect") : e.message);
  }
}
document.addEventListener("click", e => {
  const pick = clickTarget(e, "[data-pick]");
  if(pick){ const pr = profilesCache.find(x => x.name === pick.dataset.pick);
    return showLock({step: pr.has_pin ? "pin" : "setup1", owner: pr.name, len: pr.pin_len, cancelable: false}); }
  const key = clickTarget(e, "#lock [data-key]");
  if(key) lockKey(key.dataset.key);
});
document.addEventListener("keydown", e => {
  if(!L || L.step === "choose") return;
  if(/^\d$/.test(e.key)) lockKey(e.key);
  else if(e.key === "Backspace") lockKey("del");
  else if(e.key === "Enter") lockKey("ok");
  else if(e.key === "Escape") lockKey("back");
  else return;
  e.preventDefault(); e.stopPropagation();
}, true);
/* verrouillage automatique après inactivité */
["pointerdown", "keydown", "wheel", "touchstart", "pointermove"].forEach(ev => addEventListener(ev, () => { lastInput = Date.now(); }, {passive:true}));
setInterval(() => { if(!L && currentOp && Date.now() - lastInput > idleMs) lockNow(); }, 15000);
