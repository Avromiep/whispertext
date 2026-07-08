import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

// Resolve the Tailwind config absolutely so builds work from any cwd.
const here = dirname(fileURLToPath(import.meta.url));

export default {
  plugins: {
    tailwindcss: { config: join(here, "tailwind.config.js") },
    autoprefixer: {},
  },
};
