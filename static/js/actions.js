/* ================================================================ actions
   Tout ce qui se passe quand on clique, tape, colle ou dépose un fichier. Les boutons portent un attribut
   « data-… » qui dit ce qu'ils font (data-action="new", data-kw="12"…) : un seul gestionnaire de clics
   lit cet attribut et appelle la bonne fonction. */
function pickFiles(cb){
  const inp = document.createElement("input"); inp.type = "file"; inp.multiple = true;
  inp.accept = ".pdf,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp"; inp.onchange = () => cb([...inp.files]); inp.click();
}
/* choisir un dossier entier (avec ses sous-dossiers), ou un .zip ; le résultat va à sendImport() */
function pickFolder(cb){
  const inp = document.createElement("input"); inp.type = "file"; inp.multiple = true; inp.webkitdirectory = true;
  inp.onchange = () => cb([...inp.files].map(f => ({file:f, path:f.webkitRelativePath || f.name}))); inp.click();
}
function pickZip(cb){
  const inp = document.createElement("input"); inp.type = "file"; inp.accept = ".zip";
  inp.onchange = () => inp.files[0] && cb([{file:inp.files[0], path:inp.files[0].name}]); inp.click();
}
/* un dossier glissé-déposé : on parcourt ses sous-dossiers pour retrouver chaque fichier et son chemin */
async function filesFromDrop(dataTransfer){
  const entries = [...dataTransfer.items].map(i => i.webkitGetAsEntry && i.webkitGetAsEntry()).filter(Boolean);
  if(!entries.length) return [...dataTransfer.files].map(f => ({file:f, path:f.name}));
  const found = [];
  async function walk(entry, folder){
    if(entry.isFile){ const f = await new Promise((ok, ko) => entry.file(ok, ko)); found.push({file:f, path:folder + f.name}); return; }
    const reader = entry.createReader();
    for(let batch; (batch = await new Promise((ok, ko) => reader.readEntries(ok, ko))).length; )   // par paquets de 100
      for(const child of batch) await walk(child, folder + entry.name + "/");
  }
  for(const entry of entries) await walk(entry, "");
  return found;
}
/* envoi au serveur : un .zip seul, ou les fichiers d'un dossier avec leur chemin (« Candidats/Dupont Marie/cv.pdf ») */
async function sendImport(files){
  if(!files.length) return;
  const zip = files.length === 1 && /\.zip$/i.test(files[0].path);
  if(!zip && !files.some(f => f.path.includes("/")))
    return toast("Déposez le dossier qui contient un sous-dossier par candidat (ou un .zip)");
  const fd = new FormData();
  if(zip) fd.append("archive", files[0].file);
  else files.forEach(f => { fd.append("files", f.file); fd.append("paths", f.path); });
  const drop = $("#importDrop"); if(drop){ drop.disabled = true; drop.innerHTML = `<span class="spin"></span>Envoi de ${plural(files.length, "fichier")}…`; }
  let r;
  try{ r = await api(zip ? "/api/import-zip" : "/api/import-folder", {method:"POST", body:fd}); }
  catch(e){ if(e.status === 413) toast("Trop volumineux pour un seul envoi : importez les candidats en plusieurs fois"); return closeModal(); }
  closeModal();
  if(!r.ids.length) return toast("Aucun document lisible trouvé (PDF ou images)");
  let msg = `${plural(r.ids.length, "dossier")} créé${r.ids.length > 1 ? "s" : ""}`;
  if(r.rejected.length) msg += `, ${r.rejected.length} fichier${r.rejected.length > 1 ? "s" : ""} ignoré${r.rejected.length > 1 ? "s" : ""} (format)`;
  if(r.duplicates.length) msg += `, ${plural(r.duplicates.length, "doublon")} ignoré${r.duplicates.length > 1 ? "s" : ""}`;
  toast(msg + ". Lecture en cours.");
  selected.clear(); r.ids.forEach(id => selected.add(id));     // les nouveaux dossiers sont cochés : prêts pour une action groupée
  await load(false); go("#/comparer");
}
async function uploadTo(did, files){
  if(!files.length) return;
  const fd = new FormData(); files.forEach(f => fd.append("files", f));
  const r = await api(`/api/dossiers/${did}/files`, {method:"POST", body:fd});
  const dup = r.duplicates || [];
  let msg = `${plural(r.added.length, "document")} ajouté${r.added.length > 1 ? "s" : ""}`;
  if(r.rejected.length) msg += `, ${r.rejected.length} refusé${r.rejected.length > 1 ? "s" : ""} (format non pris en charge)`;
  if(dup.length) msg += dup.length > 1 ? `, ${dup.length} doublons ignorés` : `, doublon ignoré (identique à ${dup[0].same_as})`;
  toast(msg);
  dossierTab = "docs";
  await load(false);
}
async function addKeywords(text){
  if(!text.trim()) return;
  const r = await jpost("/api/keywords", {terms:text});
  toast(r.added.length ? `${kwN(r.added.length)} ajouté${r.added.length > 1 ? "s" : ""}` : "Déjà dans la liste");
  state = await api("/api/results");
  const box = $("#chips"), have = new Set([...box.children].map(c => c.dataset.id));
  box.innerHTML = state.keywords.map(k => tagHtml(k, !have.has(String(k.id)), "del-kw")).join("");
  const cnt = document.querySelector(".count"); if(cnt) cnt.textContent = `${kwN(state.keywords.length)}. Les accents et les majuscules ne comptent pas dans la recherche.`;
}
/* application de bureau : les téléchargements passent par le système (« Enregistrer sous », application par défaut) */
const desktop = () => !!(window.pywebview && window.pywebview.api);
async function exportCsv(url = "/export.csv"){
  if(!desktop()){ location.href = url; return toast(url.includes("ids=") ? "Export des dossiers cochés" : `Export des dossiers de ${currentOp}`); }
  const r = await fetch(url);
  if(!r.ok) return toast("Export impossible");
  const name = (r.headers.get("Content-Disposition") || "").match(/filename="?([^";]+)/);
  const ok = await window.pywebview.api.save_file(name ? name[1] : "keyscan.csv", await r.text());
  if(ok) toast("Export enregistré");
}
async function openDocument(url, filename){
  const r = await fetch(url);
  if(!r.ok) return toast("Document introuvable");
  const bytes = new Uint8Array(await r.arrayBuffer());
  let bin = ""; for(let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  await window.pywebview.api.open_file(filename, btoa(bin));
}
document.addEventListener("click", e => {
  const a = e.target.closest('a[href^="/api/documents/"][target="_blank"]');
  if(a && desktop()){ e.preventDefault(); openDocument(a.getAttribute("href"), a.textContent.trim()); }
}, true);

async function saveOps(ops, pin){
  try{ state.settings = await jpost("/api/settings", {operators:ops, pin}); }
  catch{ return; }
  if(!ops.includes(currentOp)){ currentOp = ops[0]; store.set("ks_op", currentOp); }
  await load(false); lastPage = null; render(false); toast("Équipe mise à jour");
}
let saveT = null, pending = null;
function saveSettings(patch){
  Object.assign(state.settings, patch);
  const {present_thr, review_thr, min_quality} = state.settings;
  pending = {owner: currentOp, present_thr, review_thr, min_quality};   // le profil est fixé au moment du réglage
  clearTimeout(saveT); saveT = setTimeout(flushSettings, 450);
}
async function flushSettings(){
  clearTimeout(saveT);
  if(!pending) return;
  const body = pending; pending = null;
  await jpost("/api/settings", body);
  toast(`Seuils de ${body.owner} enregistrés`);
}

const SEL = "[data-go],[data-action],[data-kw],[data-dtab],[data-del-kw],[data-del-doc],[data-re-doc],[data-drop],[data-del-op],[data-close],[data-switch],[data-kwsrc],[data-del-dkw],[data-view-doc],[data-wide]";
document.addEventListener("click", async e => {
  const t = clickTarget(e, SEL);
  if(!e.target.closest("#menu") && !e.target.closest("[data-action=menu],[data-action=who],[data-col]")) closeMenu();
  if(!t){   // lien appuyé mais relâché juste à côté : on le suit quand même
    const link = clickTarget(e, "a[href^='#']");
    if(link && !link.contains(e.target)) go(link.getAttribute("href"));
    return;
  }
  const ds = t.dataset;
  if("close" in ds){ e.preventDefault(); return closeModal(null); }
  if(ds.switch) return switchTo(ds.switch);
  if(ds.go){ e.preventDefault(); closeModal(); closeMenu(); return go(ds.go); }
  if(ds.dtab){
    if(dossierTab === ds.dtab) return;
    dossierTab = ds.dtab;
    t.parentElement.querySelectorAll("[data-dtab]").forEach(b => b.setAttribute("aria-pressed", b === t));
    const d = state.dossiers.find(x => x.id === route().id), list = $("#dlist");
    list.innerHTML = dossierTab === "kw" ? kwList(d) : docList(d);
    $("#view")._html = PAGES.dossier(route());
    return;
  }
  if(ds.kw) return showEvidence(+ds.dossier, +ds.kw, ds.doc ? +ds.doc : null);
  if(ds.viewDoc) return openDocViewer(+ds.viewDoc);
  if("wide" in ds){ const o = t.closest(".occ"); o.classList.toggle("wide"); t.textContent = o.classList.contains("wide") ? "Revenir au mot" : "Voir la page entière"; return; }
  if(ds.kwsrc){
    newKwSrc = ds.kwsrc;
    t.parentElement.querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", b === t));
    const sel = $("#kwCopy"); if(sel) sel.hidden = newKwSrc !== "copy";
    return;
  }
  if(ds.drop){
    if(ds.drop === "new") return pickFiles(f => { newFiles.push(...f); showNewFiles(); });
    if(ds.drop === "import") return pickFolder(sendImport);
    return pickFiles(f => uploadTo(+ds.drop, f));
  }
  if(ds.delKw || ds.delDkw){
    const c = t.closest(".term-tag"); c.classList.add("leaving");
    await api(`/api/keywords/${ds.delKw || ds.delDkw}`, {method:"DELETE"});
    if(ds.delDkw) return setTimeout(refreshKwEditor, 180);
    setTimeout(() => { c.remove(); state.keywords = state.keywords.filter(k => k.id != ds.delKw);
      const cnt = document.querySelector(".count"); if(cnt) cnt.textContent = `${kwN(state.keywords.length)}. Les accents et les majuscules ne comptent pas dans la recherche.`; }, 180);
    return;
  }
  if(ds.reDoc){ await api(`/api/documents/${ds.reDoc}/reanalyse`, {method:"POST"}); toast("Document remis en lecture"); return load(false); }
  if(ds.delDoc){
    if(await ask({title:"Retirer ce document ?", text:ds.name, ok:"Retirer", danger:true})){
      await api(`/api/documents/${ds.delDoc}`, {method:"DELETE"}); toast("Document retiré"); load(false);
    } return;
  }
  if(ds.delOp){
    const n = (state.owners || {})[ds.delOp] || 0;
    if(n) return toast(`${ds.delOp} a encore ${plural(n, "dossier")} : confiez-les d'abord à quelqu'un d'autre`);
    const sess = await api("/api/session"), pr = sess.profiles.find(x => x.name === ds.delOp);
    const needPin = ds.delOp !== currentOp && pr && pr.has_pin;
    const ans = await ask({title:`Retirer ${ds.delOp} ?`, text: needPin ? `Son profil, ses mots-clés et ses réglages seront supprimés. Saisissez le code de ${ds.delOp}.` : "Son profil, ses mots-clés et ses réglages seront supprimés.", input: needPin ? "" : null, secret: true, ok:"Retirer", danger:true});
    if(!ans) return;
    return saveOps((state.settings.operators || []).filter(o => o !== ds.delOp), needPin ? ans : undefined);
  }
  switch(ds.action){
    case "new": closeMenu(); return openNew();
    case "import": closeMenu(); return openImport();
    case "import-folder": return pickFolder(sendImport);
    case "import-zip": return pickZip(sendImport);
    case "menu": return $("#menu").classList.contains("on") ? closeMenu() : openMenu(t, ds.id);
    case "who": return $("#menu").classList.contains("on") ? closeMenu() : openWho(t);
    case "copy-kw": {
      const r = await jpost("/api/keywords/copy", {from:ds.from});
      toast(r.added ? `${kwN(r.added)} repris de ${ds.from}` : "Vous les avez déjà tous");
      lastPage = null; return load(true);
    }
    case "lock": closeMenu(); return lockNow();
    case "edit-kw": closeMenu(); return openKwEditor(+ds.id);
    case "kw-default": { const r = await jpost("/api/keywords/copy", {dossier:kwEditing, source:"default"});
      toast(r.added ? `${kwN(r.added)} ajouté${r.added > 1 ? "s" : ""}` : "Ils y sont déjà tous"); return refreshKwEditor(); }
    case "kw-copy": { const r = await jpost("/api/keywords/copy", {dossier:kwEditing, source:+$("#kwFrom").value});
      toast(r.added ? `${kwN(r.added)} copié${r.added > 1 ? "s" : ""}` : "Ils y sont déjà tous"); return refreshKwEditor(); }
    case "change-pin": {
      const sess = await api("/api/session"), pr = sess.profiles.find(x => x.name === currentOp);
      return showLock({step:"change-old", owner: currentOp, len: pr && pr.pin_len, cancelable: true});
    }
    case "give": {
      closeMenu();
      await jpost(`/api/dossiers/${ds.id}`, {owner:ds.to}, "PATCH");
      toast(`Dossier confié à ${ds.to}`); await load(false); return go("#/dossiers");
    }
    case "export": return exportCsv();
    case "add-docs": closeMenu(); return pickFiles(f => uploadTo(+ds.id, f));
    case "rename": {
      closeMenu(); const d = state.dossiers.find(x => x.id == ds.id);
      const n = await ask({title:"Renommer le dossier", input:d.name, ok:"Renommer"});
      if(n && n.trim()){ await jpost(`/api/dossiers/${ds.id}`, {name:n.trim()}, "PATCH"); toast("Dossier renommé"); load(false); }
      return;
    }
    case "delete": {
      closeMenu(); const d = state.dossiers.find(x => x.id == ds.id);
      if(await ask({title:"Supprimer ce dossier ?", text:`${d.name} et ses ${plural(d.documents.length, "document")} seront supprimés.`, ok:"Supprimer", danger:true})){
        await api(`/api/dossiers/${ds.id}`, {method:"DELETE"}); toast("Dossier supprimé"); await load(false); go("#/dossiers");
      }
      return;
    }
  }
});

document.addEventListener("submit", async e => {
  e.preventDefault();
  const f = e.target;
  if(f.id === "kwForm"){ const i = $("#kwInput"); const v = i.value; i.value = ""; await addKeywords(v); i.focus(); }
  else if(f.id === "dkwForm"){ const i = $("#dkwInput"); const v = i.value; i.value = ""; await addDossierKeywords(v); i.focus(); }
  else if(f.id === "opForm"){
    const v = $("#opInput").value.trim(); if(!v) return;
    const ops = [...(state.settings.operators || [])]; if(!ops.includes(v)) ops.push(v);
    await saveOps(ops); $("#opInput") && $("#opInput").focus();
  }
  else if(f.id === "askForm"){ closeModal($("#askInput") ? $("#askInput").value : true); }
  else if(f.id === "newForm"){
    const name = $("#newName").value.trim(); if(!name) return;
    $("#newOk").disabled = true;
    const src = newKwSrc === "copy" ? +$("#kwCopy").value : newKwSrc;
    const r = await jpost("/api/dossiers", {name, keywords_from: src, terms: $("#newTerms").value});
    const files = newFiles; closeModal();
    dossierTab = files.length ? "docs" : "kw";
    if(files.length){
      const fd = new FormData(); files.forEach(x => fd.append("files", x));
      await api(`/api/dossiers/${r.id}/files`, {method:"POST", body:fd});
    }
    toast("Dossier créé"); await load(false); go(`#/dossier/${r.id}`);
  }
});
document.addEventListener("input", e => {
  const t = e.target;
  if(t.id === "newName") $("#newOk").disabled = !t.value.trim();
  if(t.id === "railSearch"){ railFilter = t.value; paint($("#rail"), railHtml(route())); }
  if(t.type === "range"){
    let v = +t.value;
    if(t.id === "sReview" && v >= state.settings.present_thr){ v = state.settings.present_thr - 1; t.value = v; }
    if(t.id === "sPresent" && v <= state.settings.review_thr){ v = state.settings.review_thr + 1; t.value = v; }
    t.style.setProperty("--v", v); $("#" + t.id + "V").textContent = v + " %";
    saveSettings({[{sPresent:"present_thr", sReview:"review_thr", sQuality:"min_quality"}[t.id]]: v});
  }
});
document.addEventListener("paste", e => {
  if(e.target.id !== "kwInput" && e.target.id !== "dkwInput") return;
  const txt = e.clipboardData.getData("text");
  if(/[\n;,]/.test(txt)){ e.preventDefault(); (e.target.id === "kwInput" ? addKeywords : addDossierKeywords)(txt); }
});
document.addEventListener("keydown", e => {
  if(e.key === "Escape"){ closeMenu(); if($("#mwrap").classList.contains("on")) closeModal(null); }
});
["dragover", "dragleave", "drop"].forEach(ev => document.addEventListener(ev, e => {
  const z = e.target.closest && e.target.closest("[data-drop]");
  if(!z){ if(ev !== "dragleave") e.preventDefault(); return; }
  e.preventDefault();
  z.classList.toggle("over", ev === "dragover");
  if(ev === "drop"){
    if(z.dataset.drop === "import") return filesFromDrop(e.dataTransfer).then(sendImport);
    const files = [...e.dataTransfer.files];
    if(z.dataset.drop === "new"){ newFiles.push(...files); showNewFiles(); }
    else uploadTo(+z.dataset.drop, files);
  }
}));
