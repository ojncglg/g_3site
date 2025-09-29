// Matrix rain effect for error pages

// Grab the canvas
const canvas = document.getElementById("matrix");
const ctx = canvas.getContext("2d");

// Set canvas full size
canvas.width = window.innerWidth;
canvas.height = window.innerHeight;

// Letters to use
let letters = "G3INDUSTRIES";
letters = letters.split("");

// Font size and columns
const fontSize = 16;
const columns = Math.floor(canvas.width / fontSize);

// Drops - one per column
const drops = new Array(columns).fill(1);

// Draw function
function draw() {
  // Black background with slight opacity for trail effect
  ctx.fillStyle = "rgba(0, 0, 0, 0.1)";
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  // Draw characters
  for (let i = 0; i < drops.length; i++) {
    const text = letters[Math.floor(Math.random() * letters.length)];
    ctx.fillStyle = "#0f0"; // green
    ctx.fillText(text, i * fontSize, drops[i] * fontSize);

    // Move drop down
    drops[i]++;

    // Reset drop randomly after passing screen bottom
    if (drops[i] * fontSize > canvas.height && Math.random() > 0.95) {
      drops[i] = 0;
    }
  }
}

// Loop
setInterval(draw, 33);

// Handle resize
window.addEventListener("resize", () => {
  canvas.width = window.innerWidth;
  canvas.height = window.innerHeight;
});