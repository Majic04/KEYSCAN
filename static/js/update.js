/* ================================================================ mise à jour de l'application
   Dans l'application installée (Mac, Windows), une nouvelle version se télécharge toute seule en arrière-plan
   (voir updater.py). Quand elle est prête, un bouton apparaît en haut : « Redémarrer » l'installe tout de suite ;
   sinon, elle s'installe à la fermeture de KeyScan. Dans un navigateur, ce fichier ne fait rien. */
let update = null;     // dernier état reçu : {current, latest, step, progress, message}

async function refreshUpdate(){
  if(!desktop() || !window.pywebview.api.update_status) return;
  try{ update = await window.pywebview.api.update_status(); }catch{ return; }
  const pill = $("#updatePill"), ready = update.step === "ready";
  pill.hidden = !ready;
  if(ready) pill.innerHTML = `${ic("refresh")}Version ${esc(update.latest)} prête<span>Redémarrer</span>`;
  const box = $("#updateInfo"); if(box) box.innerHTML = updateText();
}

/* le texte de la section « Application » des réglages */
function updateText(){
  const u = update || {step:"check"}, version = `<p style="margin:0">KeyScan ${esc(u.current || "")}</p>`;
  const again = `<button class="btn mt" data-action="check-update">${ic("refresh")}Rechercher maintenant</button>`;
  switch(u.step){
    case "check": return version + `<p class="hint">Recherche d'une nouvelle version…</p>`;
    case "uptodate": return version + `<p class="hint">C'est la dernière version.</p>` + again;
    case "download": return version + `<p class="hint">Téléchargement de la version ${esc(u.latest)} : ${Math.round((u.progress || 0) * 100)} %</p>
      <span class="pbar" style="max-width:260px"><i style="--p:${(u.progress || 0).toFixed(3)}"></i></span>`;
    case "ready": return version + `<p class="hint">La version ${esc(u.latest)} est prête. Elle s'installe à la fermeture de KeyScan, ou tout de suite.
      Ensuite, chaque profil choisit un nouveau code.</p><button class="btn pen mt" data-action="install-update">${ic("refresh")}Redémarrer et mettre à jour</button>`;
    case "error": return version + `<p class="hint">${esc(u.message)}</p>` + again;
    default: return version;
  }
}

async function installUpdate(){
  if(await window.pywebview.api.install_update()) toast("Installation de la nouvelle version : KeyScan va se rouvrir");
}
async function checkUpdate(){
  await window.pywebview.api.check_update();
  update = {...(update || {}), step:"check"}; refreshUpdate();
  setTimeout(refreshUpdate, 2500);
}

window.addEventListener("pywebviewready", refreshUpdate);
setInterval(refreshUpdate, 15000);
