/* ================================================================ pages
   Chaque page est une fonction qui reçoit la route et rend du HTML :
     PAGES.dossiers       accueil : une carte par dossier
     PAGES.dossier        un dossier : ses mots-clés (par décision), ses documents et l'aperçu d'une page
     PAGES["mots-cles"]   la liste par défaut du prof
     PAGES.reglages       seuils, équipe, code PIN
     PAGES.comparer       (fichier compare.js) tous les dossiers dans un tableau */
const PAGES = {};

PAGES.dossiers = () => {
  const D = state.dossiers;
  if(!D.length) return `<div class="welcome">
      <h1>Premier dossier</h1>
      <p>Créez le dossier d'un candidat, choisissez les mots-clés à y chercher et déposez ses documents : PDF, scans ou photos. KeyScan les lit et surligne ce qu'il trouve.</p>
      <div class="welcome-acts"><button class="btn pen" data-action="new">${ic("plus")}Créer un dossier</button>
      <button class="btn" data-action="import">${ic("folder")}Importer plusieurs candidats</button></div></div>`;
  const pend = D.filter(d => d.pending).length;
  const check = D.reduce((n, d) => n + summary(d).c.a_verifier, 0);
  let line = plural(D.length, "dossier") + (pend ? `, dont ${pend} en cours de lecture` : ", tous lus");
  if(check) line += `. ${check > 1 ? `${check} mots sont` : "Un mot est"} à vérifier`;
  return `<div class="page wide">
    <div class="phead"><div><h1 class="ptitle">Dossiers de ${esc(currentOp || "")}</h1><p class="plead">${line}.</p></div>
      <div class="acts"><button class="btn pen" data-action="new">${ic("plus")}Nouveau dossier</button>
        <button class="btn" data-action="import">${ic("folder")}Importer</button>
        <a class="btn" href="#/comparer">${ic("grid")}Comparer</a>
        <button class="btn plain" data-action="export">${ic("download")}Exporter</button></div></div>
    <div class="cards">${D.map(dossierCard).join("")}</div>
    <button class="drop" data-drop="import">${ic("folder")}Importer des candidats<span>déposez un dossier ou un .zip, un sous-dossier par candidat</span></button></div>`;
};

/* la carte d'un dossier sur l'accueil : le nombre de mots-clés trouvés, en grand, et les mots eux-mêmes surlignés */
function dossierCard(d){
  const {ready, c, total} = summary(d), q = prog(d);
  const found = d.keywords.map(k => ({k, c:d.cells[k.id]}))
    .filter(x => ready && x.c && (x.c.decision === "present" || x.c.decision === "a_verifier"))
    .sort((a, b) => order(b.c.decision) - order(a.c.decision));      // les mots à vérifier d'abord
  const shown = found.slice(0, 8), more = found.length - shown.length;
  let foot;
  if(d.pending) foot = `<span class="pbar"><i data-bar="c${d.id}" style="--p:${q.p.toFixed(3)}"></i></span>
      <small data-pg="c${d.id}">Lecture : ${q.docsDone} sur ${plural(q.docs, "document")}</small>`;
  else foot = `<small>${plural(d.documents.length, "document")}${d.unread.length ? `, <span class="bad">${d.unread.length} illisible${d.unread.length > 1 ? "s" : ""}</span>` : ""}</small>`;
  return `<a class="card" href="#/dossier/${d.id}">
    <span class="card-top"><b>${esc(d.name)}</b>
      <span class="ratio">${ready ? c.present : "–"}<small>/${total}</small></span></span>
    ${c.a_verifier ? `<span class="badge rev">${c.a_verifier} à vérifier</span>` : ""}
    <span class="marks">${shown.map(({k, c}) => `<span class="hl ${HL[c.decision]}">${esc(k.term)}</span>`).join("")}${more > 0 ? `<span class="more">+${more}</span>` : ""}
      ${ready && !found.length ? `<span class="none">Aucun mot-clé trouvé</span>` : ""}</span>
    <span class="card-foot">${foot}</span></a>`;
}

/* un dossier : en haut les compteurs, puis les mots-clés (grands, surlignés) et les documents ; à droite, l'aperçu du document */
PAGES.dossier = r => {
  const d = state.dossiers.find(x => x.id === r.id);
  if(!d) return `<div class="welcome"><h1>Dossier introuvable</h1><p>Il a été supprimé ou confié à une autre personne.</p>
    <a class="btn" href="#/dossiers">Retour aux dossiers</a></div>`;
  const q = prog(d), nDocs = d.documents.length, {ready, c} = summary(d);
  const count = (dec, label, n) => `<div class="count-box ${HL[dec] || "no"}${n ? "" : " zero"}"><b>${n}</b><span>${label}</span></div>`;
  const head = `<div class="dhead">
      <a class="icon back" href="#/dossiers" aria-label="Retour à la liste">${ic("back")}</a>
      <h1>${esc(d.name)}</h1>
      <div class="acts"><button class="btn" data-action="add-docs" data-id="${d.id}">${ic("upload")}Ajouter des documents</button>
      <button class="btn" data-action="edit-kw" data-id="${d.id}">${ic("edit")}Mots-clés</button>
      <button class="icon" data-action="menu" data-id="${d.id}" aria-label="Autres actions">${ic("more")}</button></div></div>
    ${ready && d.keywords.length ? `<div class="counts">${count("present", "présents", c.present)}${count("a_verifier", "à vérifier", c.a_verifier)}
      ${count("absent_douteux", "incertains", c.absent_douteux)}${count("absent", "absents", c.absent)}</div>` : `<p class="verdict">${verdictText(d)}</p>`}
    ${d.pending ? `<div class="running"><span class="spin"></span><span data-pg="h${d.id}">${q.docsDone} sur ${plural(q.docs, "document")} lus, page ${Math.min(q.done + 1, q.total)} sur ${q.total}</span>
      <span class="pbar"><i data-bar="h${d.id}" style="--p:${q.p.toFixed(3)}"></i></span><span data-pg="h${d.id}e">${q.eta != null ? fmtEta(q.eta) : ""}</span></div>` : ""}
    ${d.unread.length ? `<div class="alert" role="alert">${ic("info")}<span><b>${d.unread.length > 1 ? `${d.unread.length} documents n'ont pas pu être lus` : "Un document n'a pas pu être lu"}</b> (${d.unread.map(esc).join(", ")}). Tant qu'il n'est pas remplacé, aucun mot n'est déclaré absent.</span></div>` : ""}`;
  if(!nDocs) return `<div class="page">${head}
    <button class="drop big" data-drop="${d.id}">${ic("upload")}Déposez les documents du candidat<span>PDF, images ou .zip, ou cliquez pour les choisir</span></button>
    <p class="note">Mots-clés recherchés : ${d.keywords.length ? d.keywords.map(k => esc(k.term)).join(", ") : "aucun pour l'instant"}. <button class="textlink" data-action="edit-kw" data-id="${d.id}">Modifier</button></p></div>`;
  return `<div class="page dossier">${head}
    <div class="dgrid">
      <div class="dmain">${kwList(d)}
        <h2 class="sec">Documents<small>${nDocs}</small></h2>${docList(d)}</div>
      <aside class="dside">${previewPanel(d)}</aside></div></div>`;
};

function kwList(d){
  const K = d.keywords;
  if(!K.length) return `<p class="note">Aucun mot-clé n'est recherché dans ce dossier. <button class="textlink" data-action="edit-kw" data-id="${d.id}">Choisir les mots-clés</button></p>`;
  if(!d.documents.some(x => x.status === "ok")) return `<p class="note">${d.pending ? "Les résultats apparaîtront dès que les documents seront lus." : "Aucun document n'a pu être lu."}</p>`;
  const cells = K.map(k => ({k, c:d.cells[k.id]})).filter(x => x.c);
  const where = c => { const f = {}; (c.where || []).forEach(w => (f[w.file] = f[w.file] || []).push(w.page)); return Object.entries(f).map(([n, p]) => `${n}, p. ${p.join(", ")}`).join(" ; "); };
  let n = 0;
  // une tuile par mot-clé trouvé : le mot surligné en grand, son score, où il est
  const tiles = list => `<div class="tiles">${list.sort((a, b) => b.c.score - a.c.score).map(({k, c}) => `
    <button class="kw ${HL[c.decision]}" data-kw="${k.id}" data-dossier="${d.id}">
      <span class="term"><span class="hl ${HL[c.decision]}" style="--n:${n++}">${esc(k.term)}</span></span>
      <span class="score">${Math.round(c.score)}<small> %</small></span>
      <span class="where">${esc(where(c)) || plural(c.count, "occurrence")}</span></button>`).join("")}</div>`;
  const by = dec => cells.filter(x => x.c.decision === dec);
  const title = (dec, label, L, hint) => `<h2 class="sec ${HL[dec] || "no"}">${label}<small>${L.length}${hint ? ` · ${hint}` : ""}</small></h2>`;
  const words = (L, cls) => `<div class="absents">${L.map(({k}) => `<button data-kw="${k.id}" data-dossier="${d.id}"><span class="${cls}">${esc(k.term)}</span></button>`).join("")}</div>`;
  const rev = by("a_verifier"), ok = by("present"), doubt = by("absent_douteux"), absent = by("absent");
  const doubtFound = doubt.filter(x => x.c.count), doubtNone = doubt.filter(x => !x.c.count);
  return (rev.length ? title("a_verifier", "À vérifier", rev, "un mot proche a été lu, regardez la preuve") + tiles(rev) : "")
    + (ok.length ? title("present", "Présents", ok) + tiles(ok) : "")
    + (doubt.length ? title("absent_douteux", "Absence incertaine", doubt, "rien de sûr n'a été lu") + (doubtFound.length ? tiles(doubtFound) : "") + (doubtNone.length ? words(doubtNone, "hl doubt") : "") : "")
    + (absent.length ? title("absent", "Absents", absent) + words(absent, "") : "");
}

function docList(d){
  return `<div class="docs">` + d.documents.map(x => {
    const [lab, cls] = x.duplicate_of ? ["Doublon ignoré", "err"] : STATUS[x.status], pg = x.progress;
    const label = x.status === "en_cours" && pg && pg.total > 1 ? `Page ${Math.min(pg.done + 1, pg.total)} sur ${pg.total}` : lab;
    const info = x.duplicate_of ? `Identique à ${esc(x.duplicate_of)}, compté une seule fois`
      : x.status === "erreur" ? `<span title="${esc(x.error || "")}">Fichier corrompu ou protégé par un mot de passe : KeyScan ne peut pas l'ouvrir. Remplacez-le par une autre copie.</span>`
      : x.status === "ok" ? `${plural(x.pages.length, "page")}, lecture ${Math.round(x.quality)} %`
      : pg && pg.total ? `${plural(pg.total, "page")}${pg.eta != null ? `, ${fmtEta(pg.eta)}` : ""}` : "";
    const showing = x.id === preview.doc;
    return `<div class="doc${showing ? " on" : ""}">
      <div><a class="name" href="/api/documents/${x.id}/file" target="_blank">${esc(x.filename)}</a>
        <small data-pg="x${x.id}i">${info}</small>
        ${pg && pg.total ? `<span class="pbar" style="max-width:260px"><i data-bar="x${x.id}" style="--p:${(pg.done / pg.total).toFixed(3)}"></i></span>` : ""}
        ${x.status === "ok" && !x.duplicate_of && x.hits.length ? docHits(d, x) : ""}</div>
      <span class="state ${cls}" data-pg="x${x.id}t">${label}</span>
      <span class="acts">
        ${x.status === "ok" && !x.duplicate_of ? `<button class="icon" data-pv-doc="${x.id}" aria-label="Afficher ce document dans l'aperçu" title="Afficher dans l'aperçu">${ic("eye")}</button>` : ""}
        <button class="icon" data-re-doc="${x.id}" aria-label="Relire ce document" title="Relire">${ic("refresh")}</button>
        <button class="icon del" data-del-doc="${x.id}" data-name="${esc(x.filename)}" aria-label="Retirer ${esc(x.filename)}" title="Retirer">${ic("x")}</button>
      </span></div>`;
  }).join("") + `</div><button class="drop" data-drop="${d.id}">${ic("upload")}Ajouter des documents<span>PDF, images ou .zip</span></button>`;
}
/* dans un document : tous les mots trouvés, surlignés (les mots à vérifier d'abord, avec leur page) */
function docHits(d, x){
  const hits = [...x.hits].sort((a, b) => b.review - a.review);
  return `<div class="hits">${hits.map(h => `<button data-kw="${h.kid}" data-dossier="${d.id}" data-doc="${x.id}" title="Voir où est « ${esc(h.term)} »"><span class="hl ${h.review ? "rev" : "ok"}">${esc(h.term)}</span><small>p. ${h.pages.join(", ")}</small></button>`).join("")}</div>`;
}

/* ---------------------------------------------------------------- aperçu : une page du document, mots-clés encadrés
   preview = {doc, page} : le document et la page affichés (par défaut, la première page où un mot a été trouvé) */
let preview = {doc:null, page:1};
const firstHitPage = x => { const pages = x.hits.flatMap(h => h.pages); return pages.length ? Math.min(...pages) : 1; };
function previewPanel(d){
  const ok = d.documents.filter(x => x.status === "ok" && !x.duplicate_of);
  if(!ok.length) return `<div class="pv empty">${ic("eye")}<p>L'aperçu du document apparaîtra ici dès qu'il sera lu, avec les mots-clés encadrés.</p></div>`;
  let x = ok.find(y => y.id === preview.doc);
  if(!x){ x = ok.find(y => y.hits.length) || ok[0]; preview = {doc:x.id, page:firstHitPage(x)}; }
  const n = Math.max(1, x.pages.length), p = Math.min(Math.max(1, preview.page), n);
  const here = x.hits.filter(h => h.pages.includes(p)).sort((a, b) => b.review - a.review);
  return `<div class="pv">
    ${ok.length > 1 ? `<div class="pv-docs" role="group" aria-label="Document affiché">${ok.map(y => `<button data-pv-doc="${y.id}" aria-pressed="${y.id === x.id}">${esc(y.filename)}<small>${y.hits.length}</small></button>`).join("")}</div>` : ""}
    <div class="pv-bar"><b>${ok.length > 1 ? "" : esc(x.filename)}</b>
      <span class="pv-nav"><button class="icon" data-pv-page="${p - 1}" ${p <= 1 ? "disabled" : ""} aria-label="Page précédente">${ic("back")}</button>
        <span>Page ${p} sur ${n}</span>
        <button class="icon" data-pv-page="${p + 1}" ${p >= n ? "disabled" : ""} aria-label="Page suivante">${ic("chev")}</button></span></div>
    <div class="hits">${here.length ? here.map(h => `<button data-kw="${h.kid}" data-dossier="${d.id}" data-doc="${x.id}"><span class="hl ${h.review ? "rev" : "ok"}">${esc(h.term)}</span></button>`).join("") : `<span class="none">Aucun mot-clé sur cette page</span>`}</div>
    <figure><img src="/api/documents/${x.id}/page/${p}.png?all=1&trim=1" alt="Page ${p} de ${esc(x.filename)}, mots-clés encadrés"></figure></div>`;
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
  const slider = (id, label, hint, v, off) => `<div class="slider${off ? " off" : ""}"><label for="${id}">${label} <span>${hint}</span></label>
    <input type="range" min="0" max="100" step="1" id="${id}" value="${v}" style="--v:${v}"${off ? " disabled" : ""}><output id="${id}V">${v} %</output></div>`;
  const prudent = s.absence === "prudent";
  const ocrReady = (state.engine || {}).ocr !== false;
  return `<div class="page">
    <h1 class="ptitle">Réglages</h1>
    <div class="settings">
      <div class="set"><div><h2>Seuils de décision</h2><p class="hint">Propres à ${esc(currentOp || "")}. Enregistrés dès qu'on les déplace.</p></div><div>
        ${slider("sPresent", "Présent", "à partir de ce score", s.present_thr)}
        ${slider("sReview", "À vérifier", "entre ce score et le précédent", s.review_thr)}
        ${slider("sQuality", "Lecture minimale", prudent ? "en dessous, un mot non trouvé reste incertain" : "utilisée en mode prudent seulement", s.min_quality, !prudent)}
        <p class="flabel">Mot non trouvé</p>
        <div class="choice" role="group" aria-label="Mot non trouvé">
          <button data-action="absence-absent" aria-pressed="${!prudent}">Absent</button>
          <button data-action="absence-prudent" aria-pressed="${prudent}">Prudent</button></div>
        <p class="hint">${prudent ? "« Absence incertaine » dès qu'un document est difficile à lire : scan de mauvaise qualité, mot très court lu sur une image."
          : "Un mot non trouvé est déclaré absent. Seul un document impossible à ouvrir le laisse « Absence incertaine »."}</p></div></div>
      <div class="set"><div><h2>Équipe</h2><p class="hint">Chaque personne a ses dossiers, ses mots-clés et son code.</p></div><div class="people">
        ${ops.map(o => `<div class="person"><span class="ini" style="${profStyle(o)}">${esc(initials(o))}</span><div>${esc(o)}<small>${plural((state.owners || {})[o] || 0, "dossier")}</small></div>
          ${ops.length > 1 ? `<button class="icon del" data-del-op="${esc(o)}" aria-label="Retirer ${esc(o)} de l'équipe">${ic("x")}</button>` : ""}</div>`).join("")}
        <form class="addline" id="opForm" autocomplete="off" style="margin-top:8px"><label for="opInput" class="sr">Ajouter une personne</label>
          <input id="opInput" placeholder="Prénom et nom"><button class="btn" type="submit">Ajouter</button></form></div></div>
      <div class="set"><div><h2>Code PIN</h2><p class="hint">Demandé à l'ouverture. Verrouillage automatique après 30 minutes sans activité.</p></div><div class="row-btns" style="display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn" data-action="change-pin">Changer mon code</button><button class="btn" data-action="lock">${ic("lock")}Verrouiller maintenant</button></div></div>
      <div class="set"><div><h2>Lecture des images</h2></div><div>${ocrReady
        ? `<p style="margin:0">Modèle OCRia-nano-1 (LlamaIndex), sur le processeur de l'ordinateur. Les écritures à la main ne sont pas lues de façon fiable : vérifiez-les dans l'aperçu.</p>`
        : `<p style="margin:0">Modèle OCR absent : les scans et les images ne peuvent pas être lus. En mode Python, installez-le une fois avec <code>python -m engine.ocr --install</code> puis relancez KeyScan.</p>`}</div></div>
      ${desktop() ? `<div class="set"><div><h2>Application</h2><p class="hint">Mises à jour automatiques. Seul le numéro de la dernière version est demandé à GitHub : aucun document ne quitte l'ordinateur.</p></div>
        <div id="updateInfo">${updateText()}</div></div>` : ""}
      <div class="set"><div><h2>Résultats</h2></div><div><button class="btn" data-action="export">${ic("download")}Exporter en CSV</button></div></div>
    </div></div>`;
};
