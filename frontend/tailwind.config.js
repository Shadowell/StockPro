/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: '#2563eb',
        secondary: '#f59e0b',
        up: '#ff4d57',
        down: '#10b981',
        'crypto-green': '#10b981',
        'crypto-red': '#ff4d57',
        'crypto-bg': '#0b1220',
        'crypto-card': '#111827',
        'crypto-panel': '#0d1524',
        'crypto-border': '#223047',
        'crypto-muted': '#94a3b8',
      }
    },
  },
  plugins: [],
}
