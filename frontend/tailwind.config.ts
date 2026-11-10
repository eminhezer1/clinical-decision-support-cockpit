import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        ink: "#172d3a",
        clinic: "#147d73",
      },
      boxShadow: {
        panel: "0 12px 32px rgba(27, 52, 65, 0.055)",
      },
    },
  },
  plugins: [],
};

export default config;
