/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: '#1e3a8a', // Deep blue
        secondary: '#f59e0b', // Gold
        up: '#ef4444', // Red for Up in China
        down: '#10b981', // Green for Down in China
        // Wait, standard international is Green Up, Red Down.
        // Chinese market is Red Up, Green Down.
        // The user didn't specify, but "akshare" implies Chinese market.
        // "涨跌幅用红绿色显示" -> usually implies standard Red/Green.
        // In China: Red = Up, Green = Down.
        // Let's stick to Chinese convention for A-share app.
      }
    },
  },
  plugins: [],
}
