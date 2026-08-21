/** @type {import('tailwindcss').Config} */
export default {
  content: ["./src/features/trusted-energy/**/*.{ts,tsx}"],
  prefix: "tw-",
  corePlugins: { preflight: false },
  theme: { extend: {} },
};
