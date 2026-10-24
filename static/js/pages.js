/* ================================================================ pages
   Chaque page est une fonction qui reçoit la route et rend du HTML :
     PAGES.dossiers       accueil : ce qu'il faut regarder en priorité
     PAGES.dossier        un dossier : ses mots-clés (par décision) et ses documents
     PAGES["mots-cles"]   la liste par défaut du prof
     PAGES.reglages       seuils, équipe, code PIN
     PAGES.comparer       (fichier compare.js) tous les dossiers dans un tableau */
const PAGES = {};

PAGES.dossiers = () => {
  const D = state.dossiers;
  if(!D.length) return `<div class="welcome">
      <h1>Premier dossier</h1>
      <p>Créez le dossier d'un candidat, choisissez les mots-clés à y chercher et déposez ses documents : PDF, scans, photos ou lettres manuscrites. KeyScan les lit et surligne ce qu'il trouve.</p>
      <div class="welcome-acts"><button class="btn pen" data-action="new">${ic("plus")}Créer un dossier</button>
      <button class="btn" data-action="import">${ic("folder")}Importer plusieurs candidats</button></div></div>`;
  const all = D.map(summary);
  const pend = D.filter(d => d.pending), unread = D.filter(d => d.unread.length);
  const check = D.map((d, i) => ({d, n: all[i].c.a_verifier})).filter(x => x.n).sort((a, b) => b.n - a.n);
  let line = `${plural(D.length, "dossier")}`;
  line += pend.length ? `, dont ${pend.length} en cours de lecture.` : ", tous lus.";
  const todo = [...check.map(({d, n}) => `<li><a class="textlink" href="#/dossier/${d.id}">${esc(d.name)}</a> : <span class="hl rev">${n} à vérifier</span></li>`),
                ...unread.filter(d => !check.some(x => x.d === d)).map(d => `<li><a class="textlink" href="#/dossier/${d.id}">${esc(d.name)}</a> : document illisible</li>`)];
  return `<div class="welcome">
    <h1>Dossiers de ${esc(currentOp || "")}</h1>
    <p>${line} ${todo.length ? "À regarder en priorité :" : "Aucun mot n'est à vérifier pour l'instant."}</p>
    ${todo.length ? `<ul class="todo">${todo.join("")}</ul>` : ""}
    <div class="welcome-acts"><a class="btn pen" href="#/comparer">${ic("grid")}Comparer les dossiers</a>
    <button class="btn" data-action="import">${ic("folder")}Importer plusieurs candidats</button>
    <button class="btn plain" data-action="export">${ic("download")}Exporter (CSV)</button></div></div>`;
};

PAGES.dossier = r => {
  const d = state.dossiers.find(x => x.id === r.id);
  if(!d) return `<div class="welcome"><h1>Dossier introuvable</h1><p>Il a été supprimé ou confié à une autre personne.</p>
    <a class="btn" href="#/dossiers">Retour aux dossiers</a></div>`;
  const q = prog(d), nDocs = d.documents.length;
  const head = `<div class="dhead">
      <a class="icon back" href="#/dossiers" aria-label="Retour à la liste">${ic("back")}</a>
      <h1>${esc(d.name)}</h1>
      <div class="acts"><button class="btn" data-action="add-docs" data-id="${d.id}">${ic("upload")}Ajouter des documents</button>
      <button class="icon" data-action="menu" data-id="${d.id}" aria-label="Autres actions">${ic("more")}</button></div></div>
    <p class="verdict">${verdictText(d)}</p>
    ${d.pending ? `<div class="running"><span class="spin"></span><span data-pg="h${d.id}">${q.total ? `${q.done} pages lues sur ${q.total}` : `${plural(d.pending, "document")} en attente`}</span>
      <span class="pbar"><i data-bar="h${d.id}" style="--p:${q.p.toFixed(3)}"></i></span><span data-pg="h${d.id}e">${q.eta != null ? fmtEta(q.eta) : ""}</span></div>` : ""}
    ${d.unread.length ? `<div class="alert" role="alert">${ic("info")}<span><b>${d.unread.length > 1 ? `${d.unread.length} documents n'ont pas pu être lus` : "Un document n'a pas pu être lu"}</b> (${d.unread.map(esc).join(", ")}). Tant qu'il n'est pas remplacé, aucun mot n'est déclaré absent.</span></div>` : ""}`;
  if(!nDocs) return `<div class="page">${head}
    <button class="drop big" data-drop="${d.id}">${ic("upload")}Déposez les documents du candidat<span>ou cliquez pour les choisir</span></button>
    <p class="note">Mots-clés recherchés : ${d.keywords.length ? d.keywords.map(k => esc(k.term)).join(", ") : "aucun pour l'instant"}. <button class="textlink" data-action="edit-kw" data-id="${d.id}">Modifier</button></p></div>`;
  const tabs = `<div class="tabs" role="tablist">
    <button data-dtab="kw" aria-pressed="${dossierTab === "kw"}">Mots-clés<small>${d.keywords.length}</small></button>
    <button data-dtab="docs" aria-pressed="${dossierTab === "docs"}">Documents<small>${nDocs}</small></button>
    <span class="end"><button class="btn plain" data-action="edit-kw" data-id="${d.id}">${ic("edit")}Modifier les mots-clés</button></span></div>`;
  return `<div class="page">${head}${tabs}<div id="dlist">${dossierTab === "kw" ? kwList(d) : docList(d)}</div></div>`;
};

function kwList(d){
  const K = d.keywords;
  if(!K.length) return `<p class="note">Aucun mot-clé n'est recherché dans ce dossier. <button class="textlink" data-action="edit-kw" data-id="${d.id}">Choisir les mots-clés</button></p>`;
  if(!d.documents.some(x => x.status === "ok")) return `<p class="note">${d.pending ? "Les résultats apparaîtront dès que les documents seront lus." : "Aucun document n'a pu être lu."}</p>`;
  const cells = K.map(k => ({k, c:d.cells[k.id]})).filter(x => x.c);
  const where = c => { const f = {}; (c.where || []).forEach(w => (f[w.file] = f[w.file] || []).push(w.page)); return Object.entries(f).map(([n, p]) => `${n}, p. ${p.join(", ")}`).join(" ; "); };
  let n = 0;
  const rows = list => list.sort((a, b) => b.c.score - a.c.score).map(({k, c}) => `
    <button class="row" data-kw="${k.id}" data-dossier="${d.id}">
      <span class="term"><span class="hl ${HL[c.decision]}" style="--n:${n++}">${esc(k.term)}</span></span>
      <span class="score">${Math.round(c.score)} %</span>
      <span class="where">${esc(where(c)) || plural(c.count, "occurrence")}</span>${ic("chev")}</button>`).join("");
  const by = dec => cells.filter(x => x.c.decision === dec);
  const grp = (dec, title, hint) => { const L = by(dec); return L.length ? `<section class="group"><h2>${title}<small>${L.length}${hint ? `, ${hint}` : ""}</small></h2>${rows(L)}</section>` : ""; };
  const words = (L, cls) => `<div class="absents">${L.map(({k}) => `<button data-kw="${k.id}" data-dossier="${d.id}"><span class="${cls}">${esc(k.term)}</span></button>`).join("")}</div>`;
  const doubt = by("absent_douteux"), absent = by("absent");
  const doubtFound = doubt.filter(x => x.c.count), doubtNone = doubt.filter(x => !x.c.count);
  return grp("present", "Présents") + grp("a_verifier", "À vérifier", "un mot proche a été lu, regardez la preuve")
    + (doubt.length ? `<section class="group"><h2>Absence incertaine<small>${doubt.length}, rien de sûr n'a été lu, mais la lecture ne permet pas d'affirmer l'absence</small></h2>
        ${doubtFound.length ? rows(doubtFound) : ""}${doubtNone.length ? words(doubtNone, "hl doubt") : ""}</section>` : "")
    + (absent.length ? `<section class="group"><h2>Absents<small>${absent.length}</small></h2>${words(absent, "")}</section>` : "");
}

function docList(d){
  return d.documents.map(x => {
    const [lab, cls] = x.duplicate_of ? ["Doublon ignoré", "err"] : STATUS[x.status], pg = x.progress;
    const label = x.status === "en_cours" && pg && pg.total > 1 ? `Page ${Math.min(pg.done + 1, pg.total)} sur ${pg.total}` : lab;
    const hwl = x.pages.reduce((a, p) => a + (p.manuscrit || 0), 0);
    const info = x.duplicate_of ? `Identique à ${esc(x.duplicate_of)}, compté une seule fois`
      : x.status === "erreur" ? `<span title="${esc(x.error || "")}">Fichier corrompu ou protégé par un mot de passe : KeyScan ne peut pas l'ouvrir. Remplacez-le par une autre copie.</span>`
      : x.status === "ok" ? `${plural(x.pages.length, "page")}, lecture ${Math.round(x.quality)} %${hwl ? `, ${plural(hwl, "ligne")} manuscrite${hwl > 1 ? "s" : ""}` : ""}`
      : pg && pg.total ? `${plural(pg.total, "page")}${pg.eta != null ? `, ${fmtEta(pg.eta)}` : ""}` : "";
    return `<div class="doc">
      <div><a class="name" href="/api/documents/${x.id}/file" target="_blank">${esc(x.filename)}</a>
        <small data-pg="x${x.id}i">${info}</small>
        ${pg && pg.total ? `<span class="pbar" style="max-width:260px"><i data-bar="x${x.id}" style="--p:${(pg.done / pg.total).toFixed(3)}"></i></span>` : ""}
        ${x.status === "ok" && !x.duplicate_of && x.hits.length ? docHits(d, x) : ""}</div>
      <span class="state ${cls}" data-pg="x${x.id}t">${label}</span>
      <span class="acts">
        ${x.status === "ok" && x.hits.length ? `<button class="icon" data-view-doc="${x.id}" aria-label="Voir les mots surlignés dans le document" title="Voir les mots surlignés">${ic("eye")}</button>` : ""}
        <button class="icon" data-re-doc="${x.id}" aria-label="Relire ce document" title="Relire">${ic("refresh")}</button>
        <button class="icon del" data-del-doc="${x.id}" data-name="${esc(x.filename)}" aria-label="Retirer ${esc(x.filename)}" title="Retirer">${ic("x")}</button>
      </span></div>`;
  }).join("") + `<button class="drop" data-drop="${d.id}">${ic("upload")}Ajouter des documents<span>PDF ou images</span></button>`;
}
/* dans un document : les mots à vérifier un par un (avec leur page), les mots sûrs résumés */
function docHits(d, x){
  const rev = x.hits.filter(h => h.review), sure = x.hits.filter(h => !h.review);
  return `<div class="hits">${rev.map(h => `<button data-kw="${h.kid}" data-dossier="${d.id}" data-doc="${x.id}" title="Voir où est « ${esc(h.term)} »"><span class="hl rev">${esc(h.term)}</span><small>p. ${h.pages.join(", ")}</small></button>`).join("")}
    ${sure.length ? `<button class="more" data-view-doc="${x.id}">${sure.length > 1 ? `${sure.length} mots présents` : "1 mot présent"}, voir dans le document</button>` : ""}</div>`;
}

/* ---------------------------------------------------------------- liste par défaut */
PAGES["mots-cles"] = () => {
  const K = state.keywords, counts = state.keyword_counts || {};
  const others = (state.settings.operators || []).filter(o => o !== currentOp && counts[o]);
  return `<div class="page">
    <h1 class="ptitle">Liste par défaut</h1>
    <p class="plead">Ces mots-clés sont proposés à chaque nouveau dossier de ${esc(currentOp || "")}. Chaque dossier garde ensuite sa propre liste, que l'on modifie depuis le dossier.</p>
    <form class="addline" id="kwForm" autocomplete="off">
      <label for="kwInput" class="sr">Nouveau mot-clé</label>
      <input id="kwInput" placeholder="Ajouter un mot-clé ou coller une liste">
      <button class="btn pen" type="submit">Ajouter</button></form>
    <div class="terms" id="chips">${K.map(k => tagHtml(k, false, "del-kw")).join("")}</div>
    <p class="count">${K.length ? `${kwN(K.length)}. Les accents et les majuscules ne comptent pas dans la recherche.` : "Collez une liste pour tout ajouter d'un coup : un mot-clé par ligne, ou séparés par des virgules."}</p>
    ${others.map(o => `<p class="note"><button class="textlink" data-action="copy-kw" data-from="${esc(o)}">Reprendre les ${kwN(counts[o])} de ${esc(o)}</button></p>`).join("")}</div>`;
};
const tagHtml = (k, isNew, attr) => `<span class="term-tag${isNew ? " new" : ""}" data-id="${k.id}">${esc(k.term)}
  <button class="icon del" data-${attr}="${k.id}" aria-label="Retirer ${esc(k.term)}">${ic("x")}</button></span>`;

/* ---------------------------------------------------------------- réglages */
PAGES.reglages = () => {
  const s = state.settings, ops = s.operators || [];
  const slider = (id, label, hint, v) => `<div class="slider"><label for="${id}">${label} <span>${hint}</span></label>
    <input type="range" min="0" max="100" step="1" id="${id}" value="${v}" style="--v:${v}"><output id="${id}V">${v} %</output></div>`;
  const hw = (state.engine || {}).handwriting || {};
  return `<div class="page">
    <h1 class="ptitle">Réglages</h1>
    <div class="settings">
      <div class="set"><div><h2>Seuils de décision</h2><p class="hint">Propres à ${esc(currentOp || "")}. Enregistrés dès qu'on les déplace.</p></div><div>
        ${slider("sPresent", "Présent", "à partir de ce score", s.present_thr)}
        ${slider("sReview", "À vérifier", "entre ce score et le précédent", s.review_thr)}
        ${slider("sQuality", "Lecture minimale", "en dessous, un mot non trouvé reste incertain", s.min_quality)}</div></div>
      <div class="set"><div><h2>Équipe</h2><p class="hint">Chaque personne a ses dossiers, ses mots-clés et son code.</p></div><div class="people">
        ${ops.map(o => `<div class="person"><span class="ini" style="${profStyle(o)}">${esc(initials(o))}</span><div>${esc(o)}<small>${plural((state.owners || {})[o] || 0, "dossier")}</small></div>
          ${ops.length > 1 ? `<button class="icon del" data-del-op="${esc(o)}" aria-label="Retirer ${esc(o)} de l'équipe">${ic("x")}</button>` : ""}</div>`).join("")}
        <form class="addline" id="opForm" autocomplete="off" style="margin-top:8px"><label for="opInput" class="sr">Ajouter une personne</label>
          <input id="opInput" placeholder="Prénom et nom"><button class="btn" type="submit">Ajouter</button></form></div></div>
      <div class="set"><div><h2>Code PIN</h2><p class="hint">Demandé à l'ouverture. Verrouillage automatique après 30 minutes sans activité.</p></div><div class="row-btns" style="display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn" data-action="change-pin">Changer mon code</button><button class="btn" data-action="lock">${ic("lock")}Verrouiller maintenant</button></div></div>
      <div class="set"><div><h2>Écriture manuscrite</h2></div><div>${hw.ready
        ? `<p style="margin:0">Activée (${esc(hw.label || "")}). Les lignes écrites à la main sont repérées puis lues ; leurs mots proches sont toujours à vérifier.</p>`
        : `<p style="margin:0">Non installée. En mode Python, installez-la une fois avec <code>python -m engine.trocr --install fr</code> puis relancez KeyScan.</p>`}</div></div>
      <div class="set"><div><h2>Résultats</h2></div><div><button class="btn" data-action="export">${ic("download")}Exporter en CSV</button></div></div>
    </div></div>`;
};
