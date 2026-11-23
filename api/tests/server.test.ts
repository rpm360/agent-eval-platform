import assert from "node:assert/strict";
import test from "node:test";
import { buildServer } from "../src/server.js";

test("API health, catalog, experiments, and CSV export", async () => {
  const app = await buildServer({ serveStatic: false });

  const health = await app.inject({ method: "GET", url: "/api/health" });
  assert.equal(health.statusCode, 200);
  assert.equal(health.json().status, "ok");

  const catalog = await app.inject({ method: "GET", url: "/api/catalog" });
  assert.equal(catalog.statusCode, 200);
  const catBody = catalog.json();
  assert.ok(catBody.harnesses.includes("hermes"));
  assert.ok(catBody.harnesses.includes("langgraph"));
  assert.ok(catBody.tasks.length >= 24);

  const exps = await app.inject({ method: "GET", url: "/api/experiments" });
  assert.equal(exps.statusCode, 200);
  const expList = exps.json().experiments;
  assert.ok(Array.isArray(expList));
  if (expList.length > 0) {
    assert.ok("expectedTrials" in expList[0]);
  }

  // Test SSE /api/events initial snapshot
  const sse = await app.inject({ method: "GET", url: "/api/events?once=1" });
  assert.equal(sse.statusCode, 200);
  assert.match(sse.headers["content-type"] || "", /text\/event-stream/);
  assert.ok(sse.body.includes("event: experiments"));

  const verify = await app.inject({ method: "GET", url: "/api/experiments/verify_v3" });
  if (verify.statusCode === 200) {
    const vBody = verify.json();
    assert.equal(vBody.experiment_id, "verify_v3");
    assert.ok(vBody.comparison);

    const csv = await app.inject({ method: "GET", url: "/api/experiments/verify_v3/export?format=csv" });
    assert.equal(csv.statusCode, 200);
    assert.ok(csv.body.startsWith("trial_id,config_name,"));
  }

  await app.close();
});
