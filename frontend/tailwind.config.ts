 
module.exports = { 
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"], 
  theme: { 
    extend: { 
      colors: { 
        obsidian: "#000607", 
        charcoal: "#012b32", 
        surface: "#013b4f", 
        parchment: "#efe6d8", 
        parchmentdim: "#cfc3a9", 

        burgundy: { 
          DEFAULT: "#00424e", 
          light: "#008080", 
          dark: "#000a0b", 
        }, 

        gold: { 
          DEFAULT: "#c9a05a", 
          bright: "#ded4be", 
          dim: "#c4b299", 
        }, 

        emerald: "#008080", 
      }, 

      fontFamily: { 
        serif: ["Cinzel", "Georgia", "serif"], 
        body: ["Inter", "system-ui", "sans-serif"], 
        mono: ["JetBrains Mono", "monospace"], 
      }, 

      boxShadow: { 
        glow: "0 0 30px rgba(0,88,106,0.25)", 
        goldline: "0 1px 0 rgba(201,160,90,0.35)", 
      }, 

      backgroundImage: { 
        mist: "radial-gradient(ellipse at top, rgba(0,105,124,0.25), transparent 60%)", 
      }, 
    }, 
  }, 
  plugins: [], 
};