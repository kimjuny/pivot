/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: 'rgb(24, 91, 233)',
          50: 'rgba(24, 91, 233, 0.05)',
          100: 'rgba(24, 91, 233, 0.1)',
          200: 'rgba(24, 91, 233, 0.2)',
          300: 'rgba(24, 91, 233, 0.3)',
          400: 'rgba(24, 91, 233, 0.4)',
          500: 'rgba(24, 91, 233, 0.5)',
          600: 'rgba(24, 91, 233, 0.6)',
          700: 'rgba(24, 91, 233, 0.7)',
          800: 'rgba(24, 91, 233, 0.8)',
          900: 'rgba(24, 91, 233, 0.9)',
        },
        dark: {
          bg: {
            DEFAULT: 'rgb(30, 30, 30)',
            lighter: 'rgb(40, 40, 40)',
            darker: 'rgb(25, 25, 25)',
          },
          border: {
            DEFAULT: 'rgb(50, 50, 50)',
            light: 'rgb(60, 60, 60)',
            dark: 'rgb(40, 40, 40)',
          },
          text: {
            primary: '#f1f5f9',
            secondary: '#cbd5e1',
            muted: '#94a3b8',
          },
        },
      },
      spacing: {
        '18': '4.5rem',
        '88': '22rem',
        '128': '32rem',
      },
      boxShadow: {
        'glow': '0 0 20px rgba(24, 91, 233, 0.3)',
        'glow-sm': '0 0 10px rgba(24, 91, 233, 0.2)',
        'card': '0 4px 6px -1px rgba(0, 0, 0, 0.3), 0 2px 4px -1px rgba(0, 0, 0, 0.15)',
        'card-lg': '0 10px 15px -3px rgba(0, 0, 0, 0.4), 0 4px 6px -2px rgba(0, 0, 0, 0.2)',
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'fade-in': 'fadeIn 0.3s ease-in-out',
        'slide-up': 'slideUp 0.3s ease-out',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { transform: 'translateY(10px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
      },
    },
  },
  plugins: [],
}