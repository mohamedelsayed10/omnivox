/**
 * DEV-ONLY: start the mock backend and the Vite dev server together, with the
 * proxy pointed at the mock. Use `npm run dev` instead to talk to the real API.
 */
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import { startMockServer } from "./mock-server.mjs";

const port = Number(process.env.MOCK_PORT) || 8787;
await startMockServer(port);

// The proxy in vite.config.ts reads VITE_API_BASE_URL (process.env wins over .env files).
process.env.VITE_API_BASE_URL = `http://localhost:${port}`;

const root = fileURLToPath(new URL("..", import.meta.url));
process.chdir(root);
const server = await createServer({ root });
await server.listen();
server.printUrls();
