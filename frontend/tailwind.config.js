module.exports = {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      typography: {
        invert: {
          css: {
            '--tw-prose-body': '#e5e7eb',
            '--tw-prose-headings': '#f9fafb',
            '--tw-prose-links': '#a78bfa',
            '--tw-prose-bold': '#f9fafb',
            '--tw-prose-code': '#e879f9',
            '--tw-prose-pre-bg': '#111827',
          },
        },
      },
    },
  },
  plugins: [
    require('@tailwindcss/typography'),
  ],
}
