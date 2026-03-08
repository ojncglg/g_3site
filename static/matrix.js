// Matrix rain effect used by the branded 404/500 pages.
(function () {
  const canvas = document.getElementById("matrix");
  if (!canvas) return;

  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  // Characters used in the rain stream.
  const glyphs = "G3INDUSTRIES".split("");
  const fontSize = 16;
  const frameIntervalMs = 1000 / 30; // ~30 FPS keeps the effect smooth but cheaper.

  let drops = [];
  let columns = 0;
  let rafId = null;
  let lastFrameTs = 0;

  function resizeCanvas() {
    // Keep the canvas synced with viewport size.
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    ctx.font = `${fontSize}px monospace`;
    columns = Math.max(1, Math.floor(canvas.width / fontSize));

    // Seed each column at a random vertical offset for a less uniform start.
    const maxRows = Math.max(1, Math.floor(canvas.height / fontSize));
    drops = Array.from({ length: columns }, () => Math.floor(Math.random() * maxRows));
  }

  function drawFrame() {
    // Slight alpha leaves trails behind moving characters.
    ctx.fillStyle = "rgba(0, 0, 0, 0.15)";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#22c55e";

    for (let index = 0; index < drops.length; index += 1) {
      const glyph = glyphs[Math.floor(Math.random() * glyphs.length)];
      const x = index * fontSize;
      const y = drops[index] * fontSize;
      ctx.fillText(glyph, x, y);

      // Reset each column occasionally once it goes beyond the viewport.
      if (y > canvas.height && Math.random() > 0.975) {
        drops[index] = 0;
      } else {
        drops[index] += 1;
      }
    }
  }

  function loop(timestamp) {
    if (timestamp - lastFrameTs >= frameIntervalMs) {
      drawFrame();
      lastFrameTs = timestamp;
    }
    rafId = window.requestAnimationFrame(loop);
  }

  function start() {
    if (rafId !== null) return;
    rafId = window.requestAnimationFrame(loop);
  }

  function stop() {
    if (rafId === null) return;
    window.cancelAnimationFrame(rafId);
    rafId = null;
  }

  resizeCanvas();

  // Honor user preference for reduced motion with a single static render.
  const prefersReducedMotion =
    window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (prefersReducedMotion) {
    drawFrame();
  } else {
    start();
  }

  window.addEventListener("resize", resizeCanvas);
  document.addEventListener("visibilitychange", () => {
    if (prefersReducedMotion) return;
    if (document.hidden) stop();
    else start();
  });
})();
