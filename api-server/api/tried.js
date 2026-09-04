const { MongoClient } = require("mongodb");

let cachedClient = null;

async function getCollection() {
  if (!cachedClient) {
    cachedClient = new MongoClient(process.env.MONGODB_URI);
    await cachedClient.connect();
  }
  return cachedClient.db("sd_rankings").collection("tried");
}

module.exports = async (req, res) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, x-app-secret");

  if (req.method === "OPTIONS") {
    res.status(204).end();
    return;
  }

  let col;
  try {
    col = await getCollection();
  } catch (err) {
    res.status(500).json({ error: "db connection failed" });
    return;
  }

  if (req.method === "GET") {
    const docs = await col.find({}).toArray();
    const result = {};
    for (const d of docs) {
      if (!result[d.category]) result[d.category] = [];
      result[d.category].push(d.id);
    }
    res.status(200).json(result);
    return;
  }

  // writes require the shared secret. Note: this is a deterrent, not real
  // security -- the secret ships in the public frontend JS bundle, so
  // anyone who inspects the page can extract it. Fine for a low-stakes
  // personal "tried" list; don't put anything sensitive behind this.
  if (req.headers["x-app-secret"] !== process.env.APP_SHARED_SECRET) {
    res.status(401).json({ error: "unauthorized" });
    return;
  }

  const { category, id } = req.body || {};
  if (!category || !id) {
    res.status(400).json({ error: "category and id required" });
    return;
  }

  if (req.method === "POST") {
    await col.updateOne(
      { category, id },
      { $set: { category, id, triedAt: new Date() } },
      { upsert: true }
    );
    res.status(200).json({ ok: true });
    return;
  }

  if (req.method === "DELETE") {
    await col.deleteOne({ category, id });
    res.status(200).json({ ok: true });
    return;
  }

  res.status(405).json({ error: "method not allowed" });
};
