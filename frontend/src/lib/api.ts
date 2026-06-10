/** API base — empty for same-origin (HF Space / local dev with proxy);
 *  set VITE_API_BASE for split deployments (e.g. Vercel frontend → Space API). */
export const API_BASE: string = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ?? "";

export const api = (path: string) => `${API_BASE}${path}`;
