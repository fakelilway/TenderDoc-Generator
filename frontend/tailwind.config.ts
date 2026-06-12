import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./lib/**/*.{js,ts,jsx,tsx,mdx}"
  ],
  theme: {
    extend: {
      colors: {
        ink: "#111827",
        muted: "#6b7280",
        panel: "#ffffff",
        line: "#e5e7eb",
        field: "#f8fafc",
        brand: "#2563eb",
        ok: "#047857",
        warn: "#a16207",
        danger: "#c2410c"
      },
      boxShadow: {
        panel: "0 18px 45px rgba(15, 23, 42, 0.06), 0 1px 2px rgba(15, 23, 42, 0.04)"
      }
    }
  },
  plugins: []
};

export default config;
