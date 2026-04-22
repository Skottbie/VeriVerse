/**
 * server.js — VeriVerse Express API Server
 * Serves: /api/agent-token/* routes + static dashboard
 */
import express from "express";
import dotenv from "dotenv";
import { fileURLToPath } from "url";
import path from "path";
import agentTokenRouter from "./routes/agentToken.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: path.resolve(__dirname, ".env") });

const app = express();
const PORT = process.env.PORT || 3001;

// ── Middleware ────────────────────────────────────────────────────────
app.use(express.json());

// ── API Routes ───────────────────────────────────────────────────────
app.use("/api/agent-token", agentTokenRouter);

// ── PCEG Proxy (FastAPI on port 8002) ────────────────────────────────
const PCEG_UPSTREAM = process.env.PCEG_API_URL || "http://127.0.0.1:8002";
const PCEG_ALLOWED = new Set(["graph", "rankings", "worker", "edge"]);
app.get("/api/pceg/:endpoint", async (req, res) => {
  const ep = req.params.endpoint;
  if (!PCEG_ALLOWED.has(ep)) return res.status(400).json({ error: "invalid endpoint" });
  try {
    const url = `${PCEG_UPSTREAM}/pceg/${ep}?${new URLSearchParams(req.query)}`;
    const upstream = await fetch(url, { signal: AbortSignal.timeout(10000) });
    const data = await upstream.json();
    res.status(upstream.status).json(data);
  } catch (err) {
    res.status(502).json({ error: "PCEG API unreachable", detail: err.message });
  }
});

// ── Health Check ─────────────────────────────────────────────────────
app.get("/api/health", (_req, res) => {
  res.json({
    status: "ok",
    tokenMode: process.env.TOKEN_MODE || "mock",
    network: process.env.TARGET_NETWORK || "bsc_testnet",
  });
});

// ── Verification Page ────────────────────────────────────────────────
app.get("/verify/agent/:agentId", (_req, res) => {
  res.sendFile(path.resolve(__dirname, "dashboard", "verify.html"));
});

// ── Static Dashboard ─────────────────────────────────────────────────
app.use(express.static(path.resolve(__dirname, "dashboard")));

// ── Fallback: serve dashboard for SPA ────────────────────────────────
app.get("/{*path}", (_req, res) => {
  res.sendFile(path.resolve(__dirname, "dashboard", "index.html"));
});

// ── Start ────────────────────────────────────────────────────────────
app.listen(PORT, "127.0.0.1", () => {
  console.log(`[VeriVerse] Server running on http://127.0.0.1:${PORT}`);
  console.log(`[VeriVerse] TOKEN_MODE: ${process.env.TOKEN_MODE || "mock"}`);
  console.log(`[VeriVerse] Network: ${process.env.TARGET_NETWORK || "bsc_testnet"}`);
});
