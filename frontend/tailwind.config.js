/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      opacity: Object.fromEntries(
        Array.from({ length: 100 }, (_, index) => [index, String(index / 100)]),
      ),
      colors: {
        ink: {
          950: '#07080a',
          900: '#0b0d11',
          850: '#0f1218',
          800: '#141821',
          700: '#1c2230',
          600: '#2a3242',
          500: '#525d70',
          400: '#7d8798',
          300: '#a8b1c0',
          200: '#d4d9e2',
          100: '#f2f4f8',
        },
        accent: {
          DEFAULT: '#e8b06a',
          soft: '#f2cf9c',
          deep: '#a9773a',
        },
      },
      fontFamily: {
        sans: [
          'Inter',
          'PingFang SC',
          'Hiragino Sans GB',
          'Microsoft YaHei',
          'Noto Sans SC',
          'system-ui',
          'sans-serif',
        ],
        display: [
          'PingFang SC',
          'Hiragino Sans GB',
          'Microsoft YaHei',
          'Noto Sans SC',
          'system-ui',
          'sans-serif',
        ],
      },
      boxShadow: {
        card: '0 18px 40px -22px rgba(0,0,0,0.9)',
        lift: '0 28px 60px -24px rgba(0,0,0,0.95)',
        glow: '0 0 0 1px rgba(232,176,106,0.35), 0 12px 40px -8px rgba(232,176,106,0.35)',
      },
      transitionTimingFunction: {
        silk: 'cubic-bezier(0.22, 1, 0.36, 1)',
      },
      keyframes: {
        shimmer: {
          '0%': { backgroundPosition: '-500px 0' },
          '100%': { backgroundPosition: '500px 0' },
        },
        kenburns: {
          '0%': { transform: 'scale(1.02)' },
          '100%': { transform: 'scale(1.09)' },
        },
        fadeUp: {
          '0%': { opacity: '0', transform: 'translateY(14px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        pulseSoft: {
          '0%, 100%': { opacity: '0.55' },
          '50%': { opacity: '1' },
        },
      },
      animation: {
        shimmer: 'shimmer 1.6s linear infinite',
        kenburns: 'kenburns 18s ease-out forwards',
        fadeUp: 'fadeUp 0.6s cubic-bezier(0.22,1,0.36,1) both',
        pulseSoft: 'pulseSoft 2.4s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
