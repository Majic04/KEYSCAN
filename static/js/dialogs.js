/* ================================================================ fenêtres
   openModal(html)          une boîte au centre (ou un volet à droite avec kind = "sheet")
   ask({...})               remplace confirm() et prompt() : renvoie la réponse, ou null si on annule
   openNew()                nouveau dossier
   openImport()             plusieurs candidats d'un coup (un dossier par candidat)
   openKwEditor(dossier)    les mots-clés d'un dossier
   showEvidence(...)        la preuve d'un mot-clé : extraits et images des pages
   openDocViewer(document)  un document page par page, mots surlignés
   openWho, openMenu        les petits menus (profil, actions d'un dossier) */
let modalResolve = null;
function openModal(html, kind = "box"){
  const m = $("#modal"); m.className = kind; m.innerHTML = html; m.scrollTop = 0;
  $("#mwrap").classList.add("on"); $("#mwrap").setAttribute("aria-hidden", "false");
  setTimeout(() => { const f = m.querySelector("[autofocus]") || m.querySelector(".x"); f && f.focus(); }, 60);
}
function closeModal(val){
  $("#mwrap").classList.remove("on"); $("#mwrap").setAttribute("aria-hidden", "true");
  if(kwEditing){ kwEditing = null; load(false); }        // les résultats tiennent compte des nouveaux mots-clés
  if(modalResolve){ const r = modalResolve; modalResolve = null; r(val ?? null); }
}
const closeX = `<button class="icon x" data-close aria-label="Fermer">${ic("x")}</button>`;
/* boîte de dialogue maison (remplace confirm/prompt) */
function ask({title, text = "", input = null, ok = "Valider", danger = false, secret = false}){
  openModal(`<h3>${esc(title)}</h3>${text ? `<p class="msub">${esc(text)}</p>` : ""}
    <form id="askForm">${input !== null ? `<input class="field mt" id="askInput" value="${esc(input)}" ${secret ? 'type="password" inputmode="numeric" autocomplete="off"' : ""} autofocus>` : ""}
    <div class="actions"><button type="button" class="btn plain" data-close>Annuler</button>
    <button class="btn ${danger ? "danger" : "pen"}" type="submit" ${input === null ? "autofocus" : ""}>${esc(ok)}</button></div></form>`);
  return new Promise(res => { modalResolve = res; });
}

/* nouveau dossier : nom, mots-clés de départ, documents */
let newFiles = [], newKwSrc = "default";
function openNew(){
  newFiles = [];
  const nDef = state.keywords.length, others = state.dossiers.filter(d => d.keywords.length);
  newKwSrc = nDef ? "default" : "none";
  const opt = (v, label) => `<button type="button" data-kwsrc="${v}" aria-pressed="${newKwSrc === v}">${label}</button>`;
  openModal(`${closeX}<h3>Nouveau dossier</h3><p class="msub">Il sera rangé dans les dossiers de ${esc(currentOp || "")}.</p>
    <form id="newForm" autocomplete="off">
      <label class="flabel" for="newName">Nom du candidat</label>
      <input class="field" id="newName" autofocus>
      <span class="flabel">Mots-clés recherchés</span>
      <div class="choice" role="group" aria-label="Mots-clés de départ">${nDef ? opt("default", `Liste par défaut (${nDef})`) : ""}${others.length ? opt("copy", "Copier un dossier") : ""}${opt("none", "Aucun")}</div>
      ${others.length ? `<select class="field mt" id="kwCopy" hidden aria-label="Dossier à copier">${others.map(d => `<option value="${d.id}">${esc(d.name)} (${kwN(d.keywords.length)})</option>`).join("")}</select>` : ""}
      <input class="field mt" id="newTerms" placeholder="${nDef || others.length ? "Mots-clés en plus" : "Mots-clés"}, séparés par des virgules" aria-label="Mots-clés en plus">
      <button type="button" class="drop" data-drop="new">${ic("upload")}<span id="newHint">Déposez ses documents (facultatif)</span></button>
      <div class="files" id="newFiles"></div>
      <div class="actions"><button type="button" class="btn plain" data-action="import">${ic("folder")}Plusieurs candidats d'un coup</button>
        <button class="btn pen" type="submit" id="newOk" disabled>Créer le dossier</button></div>
    </form>`);
}
function showNewFiles(){
  $("#newFiles").textContent = newFiles.map(f => f.name).join(", ");
  $("#newHint").textContent = newFiles.length ? `${plural(newFiles.length, "fichier")} prêt${newFiles.length > 1 ? "s" : ""}, cliquez pour en ajouter` : "Déposez ses documents (facultatif)";
}

/* plusieurs candidats d'un coup : un dossier qui contient un sous-dossier par candidat (ou un .zip) */
function openImport(){
  const nDef = state.keywords.length;
  openModal(`${closeX}<h3>Importer plusieurs candidats</h3>
    <p class="msub">Choisissez le dossier qui contient un sous-dossier par candidat. Chaque sous-dossier devient un dossier KeyScan ${nDef ? `avec votre liste par défaut (${kwN(nDef)})` : "(sans mot-clé : ajoutez-les ensuite depuis « Comparer »)"}, et tous les documents sont lus en parallèle.</p>
    <div class="tree" aria-hidden="true"><span>${ic("folder")}Candidats</span>
      <span class="sub">${ic("folder")}Dupont Marie<small>cv.pdf, relevé de notes.jpg</small></span>
      <span class="sub">${ic("folder")}Martin Paul<small>lettre manuscrite.pdf</small></span></div>
    <button type="button" class="drop big" data-drop="import" id="importDrop">${ic("folder")}Déposez le dossier ici<span>ou cliquez pour le choisir</span></button>
    <p class="note" id="importNote">Vous avez un fichier .zip ? <button class="textlink" data-action="import-zip">Choisir le .zip</button></p>`);
}

/* mots-clés d'un dossier */
let kwEditing = null;
async function openKwEditor(did){
  const d = state.dossiers.find(x => x.id === did); if(!d) return;
  kwEditing = did;
  const others = state.dossiers.filter(x => x.id !== did && x.keywords.length);
  openModal(`${closeX}<h3>Mots-clés du dossier</h3><p class="msub">${esc(d.name)}. Cette liste ne concerne que ce dossier.</p>
    <form class="addline" id="dkwForm" autocomplete="off" style="margin-top:18px">
      <label for="dkwInput" class="sr">Nouveau mot-clé</label><input id="dkwInput" placeholder="Ajouter un mot-clé" autofocus>
      <button class="btn pen" type="submit">Ajouter</button></form>
    <div class="terms" id="dchips">${d.keywords.map(k => tagHtml(k, false, "del-dkw")).join("")}</div>
    <p class="count" id="dcount">${d.keywords.length ? kwN(d.keywords.length) : "Collez une liste pour tout ajouter d'un coup."}</p>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:18px">
      ${state.keywords.length ? `<button class="btn" data-action="kw-default">${ic("plus")}Ajouter la liste par défaut (${state.keywords.length})</button>` : ""}
      ${others.length ? `<select class="field" id="kwFrom" style="width:auto;max-width:260px;height:36px" aria-label="Dossier à copier">
          ${others.map(x => `<option value="${x.id}">${esc(x.name)} (${kwN(x.keywords.length)})</option>`).join("")}</select>
        <button class="btn" data-action="kw-copy">${ic("swap")}Copier ses mots-clés</button>` : ""}</div>
    <div class="actions"><button class="btn pen" data-close>Terminé</button></div>`);
}
async function refreshKwEditor(){
  const list = await api(`/api/keywords?dossier=${kwEditing}`);
  const box = $("#dchips"); if(!box) return;
  const have = new Set([...box.children].map(c => c.dataset.id));
  box.innerHTML = list.map(k => tagHtml(k, !have.has(String(k.id)), "del-dkw")).join("");
  $("#dcount").textContent = list.length ? kwN(list.length) : "Aucun mot-clé : rien ne sera recherché dans ce dossier.";
}
async function addDossierKeywords(text){
  if(!text.trim()) return;
  const r = await jpost("/api/keywords", {terms:text, dossier:kwEditing});
  toast(r.added.length ? `${kwN(r.added.length)} ajouté${r.added.length > 1 ? "s" : ""}` : "Déjà dans la liste");
  await refreshKwEditor();
}

/* preuve d'un mot-clé : volet à droite */
async function showEvidence(did, kid, docId){
  const d = state.dossiers.find(x => x.id === did), k = d.keywords.find(x => x.id === kid);
  const c = await api(`/api/dossiers/${did}/keyword/${kid}`);
  const s = state.settings, found = c.count > 0;
  const occ = docId ? [...c.occurrences.filter(o => o.doc_id === docId), ...c.occurrences.filter(o => o.doc_id !== docId)] : c.occurrences;
  const why = {
    present: `Lu tel quel dans les documents. Présent à partir de ${s.present_thr} %.`,
    a_verifier: "Un mot proche a été lu, ou la lecture est incertaine. Regardez l'image pour trancher.",
    absent_douteux: c.count ? "" : "Rien n'a été trouvé, mais la lecture d'un document est incertaine (scan difficile, écriture manuscrite, document illisible ou mot très court).",
    absent: `Rien n'a été trouvé, et les documents sont bien lus (qualité ${Math.round(c.reliability)} %).`,
  }[c.decision];
  const src = o => o.source === "manuscrit" ? "écriture manuscrite" : o.source === "ocr" ? "lu sur l'image" : "texte du PDF";
  openModal(`${closeX}<h3>${esc(k.term)}</h3><p class="msub">${esc(d.name)}</p>
    <div class="ev-top"><span class="big">${found ? Math.round(c.score) : 0} %</span>
      <span class="dec">${HL[c.decision] ? `<span class="hl ${HL[c.decision]}">${LONG[c.decision]}</span>` : LONG[c.decision]}</span></div>
    ${why ? `<p class="ev-why">${why}</p>` : ""}
    ${occ.map(o => `<div class="occ">
      <p class="ctx">… ${esc(o.context).replace(/\[\[(.*?)\]\]/, (m, w) => `<span class="hl ${o.certain === false || o.score * 100 < s.present_thr ? "rev" : "ok"}">${w}</span>`)} …</p>
      ${o.certain === false ? `<p class="read">Lu : « ${esc(o.text)} », proche de « ${esc(k.term)} » sans être identique.</p>` : ""}
      <p class="meta">${esc(o.filename)}, page ${o.page}, ${src(o)}, ${Math.round(o.score * 100)} %</p>
      <figure><img class="zoom" loading="lazy" src="/api/documents/${o.doc_id}/page/${o.page}.png?kw=${kid}&crop=${o.box.map(v => v.toFixed(4)).join(",")}" alt="Le mot dans le document, page ${o.page}">
        <img class="full" loading="lazy" src="/api/documents/${o.doc_id}/page/${o.page}.png?kw=${kid}" alt="Page ${o.page} de ${esc(o.filename)}"></figure>
      <button class="textlink" data-wide>Voir la page entière</button></div>`).join("")}`, "sheet");
}

/* un document, page par page, avec tous les mots trouvés encadrés et nommés */
function openDocViewer(docId){
  const d = state.dossiers.find(x => x.documents.some(y => y.id === docId)); if(!d) return;
  const x = d.documents.find(y => y.id === docId), byPage = {};
  x.hits.forEach(h => h.pages.forEach(p => (byPage[p] = byPage[p] || []).push(h)));
  const pages = Object.keys(byPage).map(Number).sort((a, b) => a - b);
  openModal(`${closeX}<h3>${esc(x.filename)}</h3><p class="msub">${esc(d.name)}</p>
    <div class="legend"><span class="hl ok">présent</span><span class="hl rev">à vérifier</span></div>
    ${pages.map(p => `<div class="pageview"><h4>Page ${p}</h4>
      <div class="hits">${byPage[p].map(h => `<button data-kw="${h.kid}" data-dossier="${d.id}" data-doc="${x.id}"><span class="hl ${h.review ? "rev" : "ok"}">${esc(h.term)}</span></button>`).join("")}</div>
      <figure><img loading="lazy" src="/api/documents/${x.id}/page/${p}.png?all=1" alt="Page ${p}, mots-clés encadrés"></figure></div>`).join("")}`, "sheet");
}

/* menus */
function openWho(btn){
  const m = $("#menu"), ops = state.settings.operators || [], own = state.owners || {};
  m.innerHTML = ops.map(o => `<button data-switch="${esc(o)}" role="menuitemradio" aria-checked="${o === currentOp}">
      <span class="ini" style="${profStyle(o)}">${esc(initials(o))}</span><span class="whoami">${esc(o)}<small>${plural(own[o] || 0, "dossier")}</small></span>
      ${o === currentOp ? ic("check", "check") : ""}</button>`).join("") +
    `<hr><button data-go="#/reglages">${ic("sliders")}Réglages</button><button data-action="lock">${ic("lock")}Verrouiller</button>`;
  place(m, btn);
}
function place(m, btn){
  const r = btn.getBoundingClientRect();
  m.style.top = (r.bottom + 6) + "px";
  m.style.right = Math.max(10, innerWidth - r.right) + "px";
  m.classList.add("on");
}
async function switchTo(o){
  closeMenu();
  if(o === currentOp) return;
  await flushSettings();                                          // les réglages en cours vont au bon profil
  const sess = await api("/api/session");
  const pr = sess.profiles.find(x => x.name === o);
  if(!pr) return;
  showLock({step: pr.has_pin ? "pin" : "setup1", owner: o, len: pr.pin_len, cancelable: true});
}
async function enterProfile(o){
  currentOp = o; store.set("ks_op", o);
  hideLock();
  toast(`Profil de ${o}`);
  if(route().page === "dossier") location.hash = "#/dossiers";   // le dossier ouvert appartenait à l'autre profil
  lastPage = null; state.settings = {operators: state.settings.operators};
  await load(true);
}
function openMenu(btn, id){
  const m = $("#menu");
  m.innerHTML = `<button data-action="rename" data-id="${id}">${ic("edit")}Renommer</button>
    <button data-action="edit-kw" data-id="${id}">${ic("tag")}Mots-clés du dossier</button>
    ${(state.settings.operators || []).filter(o => o !== currentOp).map(o =>
      `<button data-action="give" data-id="${id}" data-to="${esc(o)}">${ic("swap")}Confier à ${esc(o)}</button>`).join("")}
    <hr><button class="del" data-action="delete" data-id="${id}">${ic("trash")}Supprimer le dossier</button>`;
  place(m, btn);
}
function closeMenu(){ $("#menu").classList.remove("on"); }
