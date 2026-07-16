/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./templates/**/*.html'],
  // Picker tone classes are assembled at runtime in status-picker.js
  // ('status-picker__dot--' + tone), so Tailwind's content scan can't see them
  // and would purge the @layer component rules. Keep them explicitly.
  safelist: [
    {
      pattern: /^status-picker__(dot|badge|trigger)--(zinc|sky|cyan|indigo|violet|emerald|rose|amber)$/,
      variants: ['dark'],
    },
  ],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        sans: ['Plus Jakarta Sans', 'system-ui', 'sans-serif'],
      },
      colors: {
        // SSL Wireless brand palette (from official logo).
        brand: {
          blue: '#284699',
          'blue-dark': '#1e3578',
          'blue-light': '#3d5fbd',
          red: '#e62832',
        },
        // Brand "ink" — a warm near-black scale (replaces the generic indigo).
        primary: {
          50: '#fafaf9',
          100: '#f5f5f4',
          200: '#e7e5e4',
          300: '#d6d3d1',
          400: '#a8a29e',
          500: '#78716c',
          600: '#292524',
          700: '#1c1917',
          800: '#171311',
          900: '#0c0a09',
        },
        dark: {
          50: '#fafafa',
          100: '#f4f4f5',
          200: '#e4e4e7',
          300: '#d4d4d8',
          400: '#a1a1aa',
          500: '#71717a',
          600: '#52525b',
          700: '#3f3f46',
          800: '#27272a',
          900: '#18181b',
          950: '#09090b',
        },
      },
      boxShadow: {
        soft: '0 1px 2px rgba(0,0,0,.04), 0 4px 24px -4px rgba(15,23,42,.08)',
        'soft-dark': '0 1px 2px rgba(0,0,0,.2), 0 8px 32px -8px rgba(0,0,0,.45)',
      },
    },
  },
  plugins: [],
};
