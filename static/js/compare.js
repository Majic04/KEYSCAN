/* ================================================================ page « Comparer »
   Tous les dossiers du prof dans un seul tableau : une ligne par candidat, une colonne par mot-clé.
   On coche des dossiers pour agir sur tous à la fois : ajouter ou retirer des mots-clés, relire, exporter, supprimer.
   Les dossiers n'ont pas forcément les mêmes mots-clés : une case vide veut dire « pas recherché dans ce dossier ».
   Un clic sur une case ouvre la preuve ; un clic sur un mot-clé (en haut d'une colonne) propose de trier ou de le retirer. */
const selected = new Set();      // numéros des dossiers cochés
let compareSort = null;          // mot-clé (forme simplifiée) qui trie le tableau, ou null : ordre habituel
let compareFilter = "";

/* même mot-clé = mêmes lettres, sans tenir compte des accents ni des majuscules (comme le serveur) */
const normTerm = t => t.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/\s+/g, " ").trim();
const RANK = {present:0, a_verifier:1, absent_douteux:2, absent:3};

/* les colonnes : les mots-clés de tous les dossiers, les plus partagés d'abord */
function compareColumns(D){
  const cols = new Map();
  D.forEach(d => d.keywords.forEach(k => {
    const norm = normTerm(k.term), col = cols.get(norm) || {norm, term:k.term, n:0};
    col.n++; cols.set(norm, col);
  }));
  return [...cols.values()].sort((a, b) => b.n - a.n || a.term.localeCompare(b.term, "fr"));
}
/* la case d'un dossier pour un mot-clé : {k, c} (mot-clé et décision), ou null s'il n'y est pas recherché */
function cellOf(d, norm){
  const k = d.keywords.find(x => normTerm(x.term) === norm);
  return k ? {k, c:d.cells[k.id]} : null;
}
function sortRank(d, norm){
  const x = cellOf(d, norm);
  if(!x) return 9;
  if(!x.c || !d.documents.some(doc => doc.status === "ok")) return 8;
  return RANK[x.c.decision] * 1000 - x.c.score;      // à décision égale, le meilleur score d'abord
}

PAGES.comparer = () => {
  const all = state.dossiers;
  [...selected].forEach(id => { if(!all.some(d => d.id === id)) selected.delete(id); });   // dossiers supprimés entre-temps
  if(!all.length) return `<div class="welcome"><h1>Comparer les dossiers</h1>
      <p>Ici, tous vos dossiers seront côte à côte : une ligne par candidat, une colonne par mot-clé. Commencez par importer les dossiers de vos candidats.</p>
      <div class="welcome-acts"><button class="btn pen" data-action="import">${ic("folder")}Importer plusieurs candidats</button>
      <button class="btn" data-action="new">${ic("plus")}Créer un dossier</button></div></div>`;
  const q = compareFilter.trim().toLowerCase();
  let D = all.filter(d => !q || d.name.toLowerCase().includes(q));
  if(compareSort) D = [...D].sort((a, b) => sortRank(a, compareSort) - sortRank(b, compareSort));
  const cols = compareColumns(all);
  const allChecked = D.length && D.every(d => selected.has(d.id));
  return `<div class="page wide">
    <h1 class="ptitle">Comparer les dossiers</h1>
    <p class="plead">${plural(all.length, "dossier")}${all.some(d => d.pending) ? `, lecture en cours (${plural(all.reduce((a, d) => a + d.pending, 0), "document")})` : ""}. Cochez des dossiers pour agir sur plusieurs à la fois.</p>
    ${batchBar()}
    <div class="grid-tools">
      <label for="compareSearch" class="sr">Filtrer les candidats</label>
      <input class="search" id="compareSearch" placeholder="Filtrer les candidats" value="${esc(compareFilter)}" autocomplete="off">
      <div class="legend"><span class="hl ok">présent</span><span class="hl rev">à vérifier</span><span class="hl doubt">incertain</span>
        <span><i class="mk no"></i>absent</span><span><i class="mk na"></i>pas recherché</span></div>
    </div>
    <div class="grid-wrap" data-keep-scroll><table class="grid">
      <thead><tr>
        <th class="tick"><input type="checkbox" data-select-all aria-label="Tout cocher" ${allChecked ? "checked" : ""}></th>
        <th class="who-col" scope="col">Candidat</th>
        ${cols.map(c => `<th class="col" scope="col"><button data-col="${esc(c.norm)}" ${compareSort === c.norm ? 'aria-sort="ascending"' : ""} title="${esc(c.term)} : trier, ou retirer ce mot-clé"><span>${esc(c.term)}</span></button></th>`).join("")}
        <th class="sum-col" scope="col">Trouvés</th></tr></thead>
      <tbody>${D.map(d => gridRow(d, cols)).join("")}</tbody>
      <tfoot><tr><td></td><th scope="row">Présent dans</th>${cols.map(c => {
          const searched = D.filter(d => cellOf(d, c.norm)), found = searched.filter(d => (cellOf(d, c.norm).c || {}).decision === "present");
          return `<td>${searched.length ? `${found.length}<small>/${searched.length}</small>` : ""}</td>`; }).join("")}<td></td></tr></tfoot>
    </table></div>
    ${D.length ? "" : `<p class="note">Aucun candidat ne correspond à « ${esc(compareFilter)} ».</p>`}
  </div>`;
};

function gridRow(d, cols){
  const ready = d.documents.some(x => x.status === "ok"), {c} = summary(d), q = prog(d);
  let sub = !d.documents.length ? "Aucun document"
    : d.pending ? `<span data-pg="g${d.id}">${q.total ? `${q.done} pages lues sur ${q.total}` : "En attente de lecture"}</span>`
    : !ready ? "Aucun document lisible" : plural(d.documents.length, "document");
  if(d.unread.length) sub += `, <span class="bad">${d.unread.length} illisible${d.unread.length > 1 ? "s" : ""}</span>`;
  const cells = cols.map(col => {
    const x = cellOf(d, col.norm);
    if(!x) return `<td><i class="mk na" title="Pas recherché dans ce dossier"></i></td>`;
    if(!ready || !x.c) return d.pending ? `<td><i class="mk wait" title="Lecture en cours"></i></td>` : "<td></td>";
    const cls = {present:"ok", a_verifier:"rev", absent_douteux:"doubt", absent:"no"}[x.c.decision];
    return `<td><button class="mk ${cls}" data-kw="${x.k.id}" data-dossier="${d.id}" title="${esc(x.k.term)} : ${LONG[x.c.decision]}${x.c.count ? `, ${Math.round(x.c.score)} %` : ""}">
      <span class="sr">${esc(x.k.term)} : ${LONG[x.c.decision]}</span></button></td>`;
  }).join("");
  return `<tr class="${selected.has(d.id) ? "on" : ""}" data-row="${d.id}">
    <td class="tick"><input type="checkbox" data-select="${d.id}" aria-label="Cocher ${esc(d.name)}" ${selected.has(d.id) ? "checked" : ""}></td>
    <th scope="row" class="who-col"><a href="#/dossier/${d.id}">${esc(d.name)}</a><small>${sub}</small></th>
    ${cells}
    <td class="sum-col">${ready && d.keywords.length ? `${c.present}<small>/${d.keywords.length}</small>${c.a_verifier ? `<span class="warn">${c.a_verifier} à vérifier</span>` : ""}` : ""}</td></tr>`;
}

/* la barre d'actions : apparaît dès qu'un dossier est coché */
function batchBar(){
  const n = selected.size;
  if(!n) return `<div class="batch idle"><span>Aucun dossier coché.</span>
    <button class="btn plain" data-action="import">${ic("folder")}Importer plusieurs candidats</button>
    <button class="btn plain" data-action="export">${ic("download")}Tout exporter (CSV)</button></div>`;
  return `<div class="batch" role="toolbar" aria-label="Actions sur les dossiers cochés">
    <b>${plural(n, "dossier")} coché${n > 1 ? "s" : ""}</b>
    <button class="btn" data-batch="add_keywords">${ic("plus")}Ajouter des mots-clés</button>
    ${state.keywords.length ? `<button class="btn" data-batch="copy_default">${ic("tag")}Ajouter la liste par défaut</button>` : ""}
    <button class="btn" data-batch="reread">${ic("refresh")}Relire</button>
    <button class="btn" data-batch="export">${ic("download")}Exporter</button>
    <button class="btn plain del" data-batch="delete">${ic("trash")}Supprimer</button>
    <button class="btn plain" data-batch="none">Tout décocher</button></div>`;
}

/* cocher ou décocher sans redessiner tout le tableau (on garde la position de défilement) */
function refreshSelection(){
  document.querySelectorAll("[data-select]").forEach(box => {
    const on = selected.has(+box.dataset.select);
    box.checked = on; box.closest("tr").classList.toggle("on", on);
  });
  const all = $("[data-select-all]"), boxes = [...document.querySelectorAll("[data-select]")];
  if(all){ all.checked = boxes.length && boxes.every(b => b.checked); all.indeterminate = !all.checked && boxes.some(b => b.checked); }
  const bar = $(".batch"); if(bar) bar.outerHTML = batchBar();
  $("#view")._html = PAGES.comparer(route());          // le prochain rafraîchissement ne verra pas de différence
}

document.addEventListener("change", e => {
  const t = e.target;
  if(t.dataset.select){ t.checked ? selected.add(+t.dataset.select) : selected.delete(+t.dataset.select); refreshSelection(); }
  if("selectAll" in t.dataset){
    document.querySelectorAll("[data-select]").forEach(b => t.checked ? selected.add(+b.dataset.select) : selected.delete(+b.dataset.select));
    refreshSelection();
  }
});
document.addEventListener("input", e => {
  if(e.target.id !== "compareSearch") return;
  compareFilter = e.target.value;
  const pos = e.target.selectionStart;
  paint($("#view"), PAGES.comparer(route()), true);
  const s = $("#compareSearch"); s.focus(); s.setSelectionRange(pos, pos);
});

/* menu d'une colonne : trier, retirer le mot-clé des dossiers cochés */
function openColumnMenu(btn, norm){
  const col = compareColumns(state.dossiers).find(c => c.norm === norm); if(!col) return;
  const targets = targetsFor(norm);
  $("#menu").innerHTML = `<button data-sort="${esc(norm)}">${ic("sliders")}${compareSort === norm ? "Revenir à l'ordre habituel" : "Trier : présents d'abord"}</button>
    <hr><button class="del" data-col-remove="${esc(norm)}" ${targets.length ? "" : "disabled"}>${ic("x")}Retirer « ${esc(col.term)} » ${selected.size ? `des dossiers cochés (${targets.length})` : `de tous les dossiers (${targets.length})`}</button>`;
  place($("#menu"), btn);
}
/* les dossiers concernés par une action : ceux qui sont cochés, ou tous si aucun ne l'est */
function targetsFor(norm){
  const D = selected.size ? state.dossiers.filter(d => selected.has(d.id)) : state.dossiers;
  return norm ? D.filter(d => cellOf(d, norm)) : D;
}

async function runBatch(action, extra = {}){
  const ids = [...selected], n = ids.length;
  const send = async body => { const r = await jpost("/api/dossiers/batch", {ids, action, ...body}); await load(false); return r; };
  if(action === "none"){ selected.clear(); return refreshSelection(); }
  if(action === "export") return exportCsv(`/export.csv?ids=${ids.join(",")}`);
  if(action === "add_keywords"){
    const terms = await ask({title:"Ajouter des mots-clés", text:`Ils seront cherchés dans les ${plural(n, "dossier")} coché${n > 1 ? "s" : ""}. Plusieurs mots-clés : séparez-les par des virgules.`, input:"", ok:"Ajouter"});
    if(!terms || !terms.trim()) return;
    const r = await send({terms});
    return toast(r.changed ? `${kwN(r.changed)} ajouté${r.changed > 1 ? "s" : ""} au total` : "Ils y étaient déjà");
  }
  if(action === "copy_default"){ const r = await send({}); return toast(r.changed ? `Liste par défaut ajoutée (${kwN(r.changed)})` : "Elle y était déjà"); }
  if(action === "reread"){
    if(!await ask({title:`Relire ${plural(n, "dossier")} ?`, text:"Tous leurs documents sont relus. Les résultats se mettent à jour au fur et à mesure.", ok:"Relire"})) return;
    const r = await send({}); return toast(`${plural(r.changed, "document")} remis en lecture`);
  }
  if(action === "delete"){
    const names = state.dossiers.filter(d => selected.has(d.id)).map(d => d.name);
    if(!await ask({title:`Supprimer ${plural(n, "dossier")} ?`, text:`${names.slice(0, 4).join(", ")}${names.length > 4 ? "…" : ""} : les dossiers et leurs documents seront supprimés.`, ok:"Supprimer", danger:true})) return;
    await send({}); selected.clear(); return toast(`${plural(n, "dossier")} supprimé${n > 1 ? "s" : ""}`);
  }
  if(action === "remove_keywords"){
    const D = targetsFor(extra.norm), col = compareColumns(state.dossiers).find(c => c.norm === extra.norm);
    if(!await ask({title:`Retirer « ${col.term} » ?`, text:`Il ne sera plus cherché dans ${plural(D.length, "dossier")}.`, ok:"Retirer", danger:true})) return;
    const spellings = [...new Set(D.map(d => cellOf(d, extra.norm).k.term))];     // « thèse », « These »… : le même mot-clé
    const r = await jpost("/api/dossiers/batch", {ids:D.map(d => d.id), action, terms:spellings.join("\n")});
    await load(false); return toast(`Retiré de ${plural(r.changed, "dossier")}`);
  }
}

document.addEventListener("click", e => {
  const col = clickTarget(e, "[data-col]");
  if(col) return $("#menu").classList.contains("on") ? closeMenu() : openColumnMenu(col, col.dataset.col);
  const sort = clickTarget(e, "[data-sort]");
  if(sort){ compareSort = compareSort === sort.dataset.sort ? null : sort.dataset.sort; closeMenu(); return render(true); }
  const remove = clickTarget(e, "[data-col-remove]");
  if(remove){ closeMenu(); return runBatch("remove_keywords", {norm:remove.dataset.colRemove}); }
  const batch = clickTarget(e, "[data-batch]");
  if(batch) return runBatch(batch.dataset.batch);
});
