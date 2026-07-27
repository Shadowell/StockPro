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
        'crypto-bg': '#0d1117',
        'crypto-card': '#161b22',
        'crypto-panel': '#111820',
        'crypto-border': '#30363d',
        'crypto-muted': '#8b949e',
      }
    },
  },
  plugins: [],
}
