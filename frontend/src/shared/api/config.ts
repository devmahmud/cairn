// Cairn frontend — runtime config (BLUEPRINT.md §4.1, §8 step 8).
//
// The one place `import.meta.env` is read -- everything else in `shared/api`
// imports `API_BASE_URL` from here instead of touching Vite's env directly.

export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
