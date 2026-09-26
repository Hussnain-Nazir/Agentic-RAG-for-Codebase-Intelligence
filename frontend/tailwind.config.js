/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#0a0d12",
        surface: {
          DEFAULT: "#0d1117",
          1: "#0d1117",
          2: "#11161d",
          3: "#161b23",
          hover: "#1b212b",
          active: "#20272f",
        },
        border: {
          DEFAULT: "#20262f",
          subtle: "#181d24",
          strong: "#2c3440",
        },
        ink: {
          primary: "#e6edf3",
          secondary: "#9aa7b5",
          muted: "#6b7684",
          disabled: "#4b535e",
        },
        accent: {
          DEFAULT: "#3b82f6",
          hover: "#5b9dff",
          muted: "#1d3a63",
          subtle: "#132339",
        },
        success: { DEFAULT: "#3fb950", subtle: "#0f2a16" },
        warning: { DEFAULT: "#d29922", subtle: "#2e2410" },
        danger: { DEFAULT: "#f85149", subtle: "#2d1214" },
      },
      fontFamily: {
        sans: ["Inter", "-apple-system", "BlinkMacSystemFont", "Segoe UI", "Helvetica Neue", "Arial", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "Liberation Mono", "monospace"],
      },
      borderRadius: {
        sm: "4px",
        DEFAULT: "6px",
        md: "6px",
        lg: "8px",
        xl: "10px",
      },
      boxShadow: {
        panel: "0 1px 0 rgba(255,255,255,0.02) inset, 0 8px 24px -12px rgba(0,0,0,0.5)",
        overlay: "0 16px 48px -12px rgba(0,0,0,0.6)",
      },
      keyframes: {
        "fade-in": { from: { opacity: 0 }, to: { opacity: 1 } },
        "slide-up": { from: { opacity: 0, transform: "translateY(6px)" }, to: { opacity: 1, transform: "translateY(0)" } },
        "pulse-soft": { "0%, 100%": { opacity: 0.6 }, "50%": { opacity: 1 } },
      },
      animation: {
        "fade-in": "fade-in 160ms ease-out",
        "slide-up": "slide-up 200ms ease-out",
        "pulse-soft": "pulse-soft 1.8s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
