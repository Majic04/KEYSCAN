/* ================================================================ curseur : un cercle à l'encre bleue
   Il suit la souris avec une légère inertie, épouse la forme des boutons, devient une barre d'insertion
   sur les champs de texte. Piloté par les événements souris ; la boucle s'arrête dès qu'il est immobile. */
(function cursor(){
  if(!matchMedia("(pointer:fine)").matches || calm.matches) return;
  const root = document.documentElement, ring = $("#cur-ring");
  const MORPH = ".btn,.icon,.key,.pick,.who,.upd,.nav a,.tabs button,.choice button,.menu button,.textlink";
  const TEXT = "input:not([type=range]),textarea,[contenteditable]";
  const POINT = "a,button,[data-drop],label,input[type=range],select";
  const BASE = 28;
  let mx = -100, my = -100, x = -100, y = -100, w = BASE, h = BASE, rad = BASE / 2, sc = 1;
  let target = null, mode = "", rect = null, radius = 0, down = false, running = false, last = 0, seen = false;
  root.classList.add("cc");
  function measure(){ if(!target) return; rect = target.getBoundingClientRect(); radius = Math.min(parseFloat(getComputedStyle(target).borderRadius) || 6, rect.height / 2); }
  function setTarget(el){
    const m = el && el.closest(MORPH), t = !m && el && el.closest(TEXT), pt = !m && !t && el && el.closest(POINT);
    const next = m || t || pt || null, nmode = m ? "morph" : t ? "text" : pt ? "point" : "";
    if(next === target && nmode === mode) return;
    target = next; mode = nmode; rect = null;
    if(mode === "morph"){ measure(); if(rect.width > 320) mode = "point"; }
    ring.className = mode;
  }
  function kick(){ if(!running){ running = true; last = performance.now(); requestAnimationFrame(frame); } }
  addEventListener("pointermove", e => { if(e.pointerType !== "mouse") return; mx = e.clientX; my = e.clientY;
    if(!seen){ x = mx; y = my; seen = true; } root.classList.remove("cur-out"); kick(); }, {passive:true});
  document.addEventListener("pointerover", e => { if(e.pointerType === "mouse"){ setTarget(e.target); kick(); } }, {passive:true});
  document.addEventListener("mouseleave", () => root.classList.add("cur-out"));
  addEventListener("scroll", () => { if(mode === "morph") measure(); kick(); }, {passive:true, capture:true});
  addEventListener("pointerdown", () => { down = true; kick(); });
  addEventListener("pointerup", () => { down = false; kick(); });
  new MutationObserver(() => { if(target && !target.isConnected){ target = null; mode = ""; ring.className = ""; kick(); } })
    .observe(document.body, {childList:true, subtree:true});
  function frame(now){
    const dt = Math.min(64, now - last) / 16.67; last = now;
    const f = a => 1 - Math.pow(1 - a, dt);
    let tx = mx, ty = my, tw = BASE, th = BASE, tr = BASE / 2, k = .45;
    if(mode === "morph" && rect){ tx = rect.left + rect.width / 2; ty = rect.top + rect.height / 2; tw = rect.width + 8; th = rect.height + 8; tr = radius + 4; k = .4; }
    else if(mode === "text"){ tw = 2; th = 20; tr = 1; k = .75; }
    else if(mode === "point"){ tw = th = 34; tr = 17; }
    const ts = down ? .9 : 1;
    x += (tx - x) * f(k); y += (ty - y) * f(k);
    w += (tw - w) * f(.35); h += (th - h) * f(.35); rad += (tr - rad) * f(.35); sc += (ts - sc) * f(.4);
    const still = Math.abs(tx - x) < .05 && Math.abs(ty - y) < .05 && Math.abs(tw - w) < .05 && Math.abs(th - h) < .05 && Math.abs(ts - sc) < .005;
    if(still){ x = tx; y = ty; w = tw; h = th; rad = tr; sc = ts; }
    ring.style.width = w.toFixed(2) + "px"; ring.style.height = h.toFixed(2) + "px"; ring.style.borderRadius = rad.toFixed(2) + "px";
    ring.style.transform = `translate3d(${(x - w / 2).toFixed(2)}px,${(y - h / 2).toFixed(2)}px,0) scale(${sc.toFixed(3)})`;
    if(still){ running = false; return; }
    requestAnimationFrame(frame);
  }
})();
