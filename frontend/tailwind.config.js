/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: '#1e3a8a',
        secondary: '#f59e0b',
        up: '#ef4444',
        down: '#10b981',
        'crypto-green': '#00C853',
        'crypto-red': '#FF1744',
        'crypto-bg': '#0D1117',
        'crypto-card': '#161B22',
        'crypto-border': '#30363D',
      }
    },
  },
  plugins: [],
}
