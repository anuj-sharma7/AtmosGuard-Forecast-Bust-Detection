/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      // Tailwind's default opacity scale is too coarse for a dark command
      // centre, where tints sit between 8% and 20%. These are the steps the
      // UI actually uses.
      opacity: {
        8: '0.08',
        12: '0.12',
        18: '0.18',
        45: '0.45',
        55: '0.55',
        65: '0.65',
        85: '0.85',
        92: '0.92',
      },
      colors: {
        // Command-centre surfaces: deep navy through charcoal.
        surface: {
          0: '#070c16',
          1: '#0d1524',
          2: '#131e30',
          3: '#1a273c',
        },
        edge: { DEFAULT: '#1e2c44', strong: '#2b3d5c' },
        ink: {
          primary: '#e8eef7',
          secondary: '#9aa9bf',
          muted: '#66768f',
        },
        // Chart series - validated against the #0d1524 panel surface.
        series: { 1: '#3987e5', 2: '#d95926', 3: '#199e70' },
        // Risk status scale. Always rendered alongside its category label;
        // never the sole carrier of meaning.
        risk: {
          low: '#0ca30c',
          moderate: '#fab219',
          high: '#ec835a',
          severe: '#d03b3b',
        },
        accent: { DEFAULT: '#38bdf8', dim: '#0ea5e9' },
      },
      fontFamily: {
        sans: ['"Inter"', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      fontSize: { '2xs': ['0.6875rem', { lineHeight: '1rem' }] },
      animation: {
        'fade-in': 'fadeIn 220ms ease-out',
        'rise': 'rise 260ms cubic-bezier(0.22, 1, 0.36, 1)',
        'pulse-ring': 'pulseRing 2.4s ease-out infinite',
      },
      keyframes: {
        fadeIn: { '0%': { opacity: '0' }, '100%': { opacity: '1' } },
        rise: { '0%': { opacity: '0', transform: 'translateY(6px)' }, '100%': { opacity: '1', transform: 'none' } },
        pulseRing: {
          '0%': { boxShadow: '0 0 0 0 rgba(208, 59, 59, 0.45)' },
          '70%': { boxShadow: '0 0 0 10px rgba(208, 59, 59, 0)' },
          '100%': { boxShadow: '0 0 0 0 rgba(208, 59, 59, 0)' },
        },
      },
    },
  },
  plugins: [],
};
