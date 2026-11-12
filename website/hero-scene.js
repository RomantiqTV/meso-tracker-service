// Three.js hero backdrop: drifting gold mesos coins + a few original pixel-art loot sprites, matching the site's
// sky-to-parchment palette. Pure procedural geometry/canvas textures - no external model or image assets (and
// deliberately no MapleStory sprites - see the note by pixelIconTexture below), so this costs nothing to host.
//
// Respects prefers-reduced-motion (never mounts) and pauses whenever the tab is hidden or the canvas has scrolled out
// of view, so it never burns battery for no visual benefit.
import * as THREE from "three";

const canvas = document.getElementById("hero-canvas");
if (canvas && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0x69c3fb, 0.012);

  const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 100);
  camera.position.set(0, 0, 14);

  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  // Everything in this scene is an unlit canvas-drawn sprite (coins, points, pixel-art loot icons), so no lights
  // are needed - their color comes straight from the texture, which keeps the flat, crisp pixel-art look intact.

  // A round, soft-edged gold coin sprite, drawn once to a canvas - this is the "texture" for every particle.
  function coinTexture() {
    const s = 128, c = document.createElement("canvas");
    c.width = c.height = s;
    const ctx = c.getContext("2d");
    const g = ctx.createRadialGradient(s / 2, s / 2, 2, s / 2, s / 2, s / 2);
    g.addColorStop(0, "#fff6da");
    g.addColorStop(0.35, "#ffd873");
    g.addColorStop(0.7, "#e8801c");
    g.addColorStop(1, "rgba(232,128,28,0)");
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(s / 2, s / 2, s / 2, 0, Math.PI * 2);
    ctx.fill();
    const tex = new THREE.CanvasTexture(c);
    tex.colorSpace = THREE.SRGBColorSpace;
    return tex;
  }

  const area = window.innerWidth * window.innerHeight;
  const count = Math.round(Math.min(260, Math.max(90, area / 6500)));
  const positions = new Float32Array(count * 3);
  const sizes = new Float32Array(count);
  const speeds = new Float32Array(count);
  for (let i = 0; i < count; i++) {
    positions[i * 3] = (Math.random() - 0.5) * 26;
    positions[i * 3 + 1] = (Math.random() - 0.5) * 16;
    positions[i * 3 + 2] = (Math.random() - 0.5) * 16 - 2;
    sizes[i] = Math.random() * 1.6 + 0.4;
    speeds[i] = Math.random() * 0.4 + 0.15;
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geo.setAttribute("size", new THREE.BufferAttribute(sizes, 1));
  const mat = new THREE.PointsMaterial({
    map: coinTexture(), size: 0.9, sizeAttenuation: true, transparent: true,
    opacity: 0.9, blending: THREE.AdditiveBlending, depthWrite: false, vertexColors: false,
  });
  const points = new THREE.Points(geo, mat);
  scene.add(points);

  // A handful of larger drifting "loot" sprites for depth - entirely original pixel-art icons drawn on a canvas at
  // runtime (a coin, a potion, a scroll, a gem, a tiny sword). Deliberately generic RPG iconography, not a copy of
  // any MapleStory asset - the game's actual sprites are Nexon's copyrighted art and have no place on this site.
  function pixelIconTexture(draw) {
    const s = 64, c = document.createElement("canvas");
    c.width = c.height = s;
    const ctx = c.getContext("2d");
    ctx.imageSmoothingEnabled = false;
    draw(ctx, s);
    const tex = new THREE.CanvasTexture(c);
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.magFilter = THREE.NearestFilter;
    return tex;
  }
  function px(ctx, scale, color, cells) {
    ctx.fillStyle = color;
    cells.forEach(([x, y, w = 1, h = 1]) => ctx.fillRect(x * scale, y * scale, w * scale, h * scale));
  }
  const iconTextures = [
    // coin: round gold piece with a bright rim highlight
    pixelIconTexture((ctx, s) => {
      const u = s / 8;
      px(ctx, u, "#7a3b0c", [[2, 1, 4, 1], [1, 2, 1, 4], [6, 2, 1, 4], [2, 6, 4, 1]]);
      px(ctx, u, "#e8801c", [[2, 2, 4, 4]]);
      px(ctx, u, "#ffc65c", [[3, 2, 2, 1], [2, 3, 1, 2]]);
      px(ctx, u, "#fff6da", [[3, 3, 1, 1]]);
    }),
    // potion: round-bottomed flask with a glowing red fill
    pixelIconTexture((ctx, s) => {
      const u = s / 8;
      px(ctx, u, "#fff6da", [[3, 1, 2, 1]]);
      px(ctx, u, "#7a3b0c", [[2, 2, 4, 1], [1, 3, 6, 3], [2, 6, 4, 1]]);
      px(ctx, u, "#c23a2a", [[2, 4, 4, 2]]);
      px(ctx, u, "#ff8f7a", [[3, 4, 1, 1]]);
    }),
    // scroll: parchment roll with ribbon
    pixelIconTexture((ctx, s) => {
      const u = s / 8;
      px(ctx, u, "#7a3b0c", [[1, 1, 6, 1], [1, 6, 6, 1]]);
      px(ctx, u, "#fff6da", [[1, 2, 6, 4]]);
      px(ctx, u, "#e8801c", [[2, 3, 4, 1], [2, 5, 3, 1]]);
    }),
    // gem: faceted blue shard
    pixelIconTexture((ctx, s) => {
      const u = s / 8;
      px(ctx, u, "#2b78b8", [[3, 1, 2, 1], [2, 2, 4, 1], [1, 3, 6, 2], [2, 5, 4, 1], [3, 6, 2, 1]]);
      px(ctx, u, "#7fd4ff", [[3, 2, 1, 1], [2, 3, 2, 1]]);
      px(ctx, u, "#fff6da", [[3, 3, 1, 1]]);
    }),
  ];

  const gems = [];
  for (let i = 0; i < 7; i++) {
    const mat = new THREE.SpriteMaterial({
      map: iconTextures[i % iconTextures.length], transparent: true, depthWrite: false,
    });
    const sprite = new THREE.Sprite(mat);
    const scale = Math.random() * 0.8 + 1.1;
    sprite.scale.set(scale, scale, 1);
    sprite.position.set((Math.random() - 0.5) * 18, (Math.random() - 0.5) * 10, (Math.random() - 0.5) * 6 - 3);
    sprite.userData.spin = (Math.random() - 0.5) * 0.6;
    sprite.userData.bob = Math.random() * Math.PI * 2;
    sprite.userData.baseRot = Math.random() * Math.PI * 2;
    scene.add(sprite);
    gems.push(sprite);
  }

  let w = 0, h = 0;
  function resize() {
    const rect = canvas.parentElement.getBoundingClientRect();
    w = rect.width; h = rect.height;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  resize();
  window.addEventListener("resize", resize);

  // Gentle parallax toward the pointer, lerped so it never feels twitchy.
  const target = { x: 0, y: 0 };
  const current = { x: 0, y: 0 };
  window.addEventListener("pointermove", (e) => {
    target.x = (e.clientX / window.innerWidth - 0.5) * 1.6;
    target.y = (e.clientY / window.innerHeight - 0.5) * -1.0;
  });

  let inViewport = true;
  new IntersectionObserver(([entry]) => { inViewport = entry.isIntersecting; }, { threshold: 0.01 }).observe(canvas);

  const clock = new THREE.Clock();
  function tick() {
    requestAnimationFrame(tick);
    if (document.hidden || !inViewport) return;
    const t = clock.getElapsedTime();
    current.x += (target.x - current.x) * 0.04;
    current.y += (target.y - current.y) * 0.04;
    camera.position.x = current.x;
    camera.position.y = current.y;
    camera.lookAt(0, 0, 0);

    const pos = geo.attributes.position;
    for (let i = 0; i < count; i++) {
      pos.array[i * 3 + 1] += Math.sin(t * speeds[i] + i) * 0.0015;
      pos.array[i * 3] += Math.cos(t * speeds[i] * 0.6 + i) * 0.0012;
    }
    pos.needsUpdate = true;
    points.rotation.y = t * 0.02;

    gems.forEach((g) => {
      g.material.rotation = g.userData.baseRot + t * g.userData.spin * 0.3;
      g.position.y += Math.sin(t * 0.6 + g.userData.bob) * 0.0025;
      g.position.x += Math.cos(t * 0.4 + g.userData.bob) * 0.0018;
    });

    renderer.render(scene, camera);
  }
  tick();
}
