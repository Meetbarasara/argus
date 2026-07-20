/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // control-room palette, light edition: cool paper base, one accent, status hues.
        // The scale keeps its role-by-position (950=page bg, 900=surface, 800=hairline,
        // 500=muted text, 100=strongest text) so component markup never renames.
        ink: {
          950: "#f3f5f9",
          900: "#ffffff",
          850: "#eef1f6",
          800: "#e3e8f0",
          700: "#c9d3e0",
          600: "#8e9cb3",
          500: "#5b6b84",
          400: "#43536e",
          300: "#2e3c53",
          200: "#1e293b",
          100: "#0f172a",
        },
        accent: { DEFAULT: "#2563eb", deep: "#1d4ed8", soft: "#eff4ff" },
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
