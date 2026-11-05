import createClient from "openapi-fetch";
import type { paths } from "./schema";

// Demo-grade (README states this plainly): no build-time env setup
// needed for the common case (backend on :8000, frontend dev server
// on a different port) - override with VITE_API_BASE_URL if needed.
export const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export const api = createClient<paths>({ baseUrl: BASE_URL });

export type { components } from "./schema";
