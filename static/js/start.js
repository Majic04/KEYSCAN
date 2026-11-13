/* ================================================================ démarrage
   Sans adresse, on arrive sur la liste des dossiers ; boot() (lock.js) demande au serveur quel profil est ouvert. */
if(!location.hash) history.replaceState(null, "", "#/dossiers");
boot();
