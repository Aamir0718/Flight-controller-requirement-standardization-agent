import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./layouts/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        drdo: {
          bg: "#07111F",
          card: "#0F172A",
          surface: "#142036",
          border: "#243244",
          primary: "#1EA7FF",
          "primary-hover": "#008ee6",
          success: "#00C853",
          warning: "#FFB300",
          error: "#FF4D4F",
          text: "#F5F7FA",
          muted: "#8FA3BF",
        },
      },
      fontFamily: {
        sans: ["var(--font-sans)", "Inter", "sans-serif"],
        mono: ["var(--font-mono)", "JetBrains Mono", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
