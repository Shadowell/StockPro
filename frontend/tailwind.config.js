/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // 自定义颜色
        'crypto-green': '#00C853',
        'crypto-red': '#FF1744',
        'crypto-bg': '#0D1117',
        'crypto-card': '#161B22',
        'crypto-border': '#30363D',
      },
    },
  },
  plugins: [],
}
