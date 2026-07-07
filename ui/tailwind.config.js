/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // control-room palette: calm slate base, one accent, status hues
        ink: {
          950: "#0a0e17",
          900: "#0f1420",
          850: "#151b2b",
          800: "#1b2333",
          700: "#273248",
          600: "#3a4a68",
          500: "#64748b",
          400: "#94a3b8",
          300: "#cbd5e1",
        },
        accent: { DEFAULT: "#5b9bff", dim: "#2a4a80" },
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
