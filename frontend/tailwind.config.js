/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Align with BitPro / @bitpro/ui tokens
        primary: '#58a6ff',
        secondary: '#d29922',
        up: '#ff1744',
        down: '#00c853',
        'crypto-green': '#00C853',
        'crypto-red': '#FF1744',
        'crypto-bg': '#0D1117',
        'crypto-card': '#161B22',
        'crypto-panel': '#111820',
        'crypto-border': '#30363D',
        'crypto-muted': '#8b949e',
        'crypto-accent': '#58a6ff',
      },
      fontFamily: {
        sans: [
          'Inter',
          'ui-sans-serif',
          'system-ui',
          '"PingFang SC"',
          '"HarmonyOS Sans SC"',
          '"Microsoft YaHei"',
          '"Noto Sans CJK SC"',
          'sans-serif',
        ],
        mono: [
          '"SFMono-Regular"',
          'Consolas',
          '"Liberation Mono"',
          'Menlo',
          'monospace',
        ],
      },
    },
  },
  plugins: [],
}
