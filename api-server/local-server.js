// Ad-hoc local runner for api/tried.js so it can be smoke-tested without a
// Vercel account -- NOT part of the deployed project (not in api/, so
// Vercel won't pick it up).
require("dotenv").config();
const http = require("http");
const handler = require("./api/tried.js");

const server = http.createServer((req, res) => {
  const chunks = [];
  req.on("data", (c) => chunks.push(c));
  req.on("end", () => {
    const body = Buffer.concat(chunks).toString("utf8");
    req.body = body ? JSON.parse(body) : {};
    const json = (obj) => {
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify(obj));
    };
    res.status = (code) => {
      res.statusCode = code;
      return { json, end: () => res.end() };
    };
    handler(req, res).catch((err) => {
      res.statusCode = 500;
      res.end(String(err));
    });
  });
});

server.listen(3001, () => console.log("local api on http://localhost:3001"));
