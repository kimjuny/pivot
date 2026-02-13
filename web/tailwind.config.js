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
        // shadcn CSS variable based colors
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        sidebar: {
          DEFAULT: "hsl(var(--sidebar-background))",
          foreground: "hsl(var(--sidebar-foreground))",
          primary: "hsl(var(--sidebar-primary))",
          "primary-foreground": "hsl(var(--sidebar-primary-foreground))",
          accent: "hsl(var(--sidebar-accent))",
          "accent-foreground": "hsl(var(--sidebar-accent-foreground))",
          border: "hsl(var(--sidebar-border))",
          ring: "hsl(var(--sidebar-ring))",
        },
        // Legacy custom colors (keep for backward compatibility)
        danger: {
          DEFAULT: 'rgb(239, 68, 68)',
          50: 'rgba(239, 68, 68, 0.05)',
          100: 'rgba(239, 68, 68, 0.1)',
          200: 'rgba(239, 68, 68, 0.2)',
          300: 'rgba(239, 68, 68, 0.3)',
          400: 'rgba(239, 68, 68, 0.4)',
          500: 'rgba(239, 68, 68, 0.5)',
          600: 'rgb(220, 38, 38)',
          700: 'rgb(185, 28, 28)',
          800: 'rgba(239, 68, 68, 0.8)',
          900: 'rgba(239, 68, 68, 0.9)',
        },
        warning: {
          DEFAULT: 'rgb(234, 179, 8)',
          50: 'rgba(234, 179, 8, 0.05)',
          100: 'rgba(234, 179, 8, 0.1)',
          200: 'rgba(234, 179, 8, 0.2)',
          300: 'rgba(234, 179, 8, 0.3)',
          400: 'rgba(234, 179, 8, 0.4)',
          500: 'rgba(234, 179, 8, 0.5)',
          600: 'rgb(202, 138, 4)',
          700: 'rgb(161, 98, 7)',
          800: 'rgba(234, 179, 8, 0.8)',
          900: 'rgba(234, 179, 8, 0.9)',
        },
        success: {
          DEFAULT: 'rgb(34, 197, 94)',
          50: 'rgba(34, 197, 94, 0.05)',
          100: 'rgba(34, 197, 94, 0.1)',
          200: 'rgba(34, 197, 94, 0.2)',
          300: 'rgba(34, 197, 94, 0.3)',
          400: 'rgba(34, 197, 94, 0.4)',
          500: 'rgba(34, 197, 94, 0.5)',
          600: 'rgb(22, 163, 74)',
          700: 'rgb(21, 128, 61)',
          800: 'rgba(34, 197, 94, 0.8)',
          900: 'rgba(34, 197, 94, 0.9)',
        },
        info: {
          DEFAULT: 'rgb(59, 130, 246)',
          50: 'rgba(59, 130, 246, 0.05)',
          100: 'rgba(59, 130, 246, 0.1)',
          200: 'rgba(59, 130, 246, 0.2)',
          300: 'rgba(59, 130, 246, 0.3)',
          400: 'rgba(59, 130, 246, 0.4)',
          500: 'rgba(59, 130, 246, 0.5)',
          600: 'rgb(37, 99, 235)',
          700: 'rgb(29, 78, 216)',
          800: 'rgba(59, 130, 246, 0.8)',
          900: 'rgba(59, 130, 246, 0.9)',
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
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
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
        'thinking-wave': 'thinkingWave 5s ease-in-out infinite',
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
        thinkingWave: {
          '0%': { backgroundPosition: '200% center' },
          '100%': { backgroundPosition: '-200% center' },
        },
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
}