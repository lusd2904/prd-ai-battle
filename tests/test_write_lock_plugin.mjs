/**
 * Fail-closed write_lock plugin: both hooks defer to write-check.
 * Run via: node --experimental-default-type=module tests/test_write_lock_plugin.mjs
 */
import { strict as assert } from "node:assert"

import {
  createWriteLockHook,
  evaluateWriteCheck,
  isMutatingTool,
  writeCheckArgs,
} from "../.opencode/plugins/write-lock.js"

const MUTATING = ["write", "edit", "apply_patch", "applypatch", "bash", "shell", "patch"]
const READS = ["read", "glob", "grep", "list"]

function crashResult() {
  return {
    status: null,
    payload: null,
    stdout: "",
    stderr: "",
    error: new Error("ENOENT: python3"),
  }
}

function allowResult() {
  return { status: 0, payload: { ok: true, reason: "allowed" }, stdout: '{"ok":true}', stderr: "", error: null }
}

function denyResult(reason = "write_lock denied") {
  return { status: 2, payload: { ok: false, reason }, stdout: `{"ok":false,"reason":"${reason}"}`, stderr: "", error: null }
}

async function hooksWith(runCliImpl) {
  const calls = []
  const hook = createWriteLockHook({
    runCliImpl: (directory, args) => {
      calls.push({ directory, args })
      return runCliImpl(directory, args, calls)
    },
  })
  const handlers = await hook({ directory: "/tmp/prd" })
  return { handlers, calls }
}

async function remember(handlers, sessionID, agent) {
  await handlers["chat.message"]({ sessionID, agent })
}

function assertDenied(decision, message) {
  assert.equal(decision.deny, true, message || "expected deny")
  assert.ok(decision.reason, "deny must include a reason")
}

function assertAllowed(decision, message) {
  assert.equal(decision.deny, false, message || "expected allow")
}

// --- evaluateWriteCheck: fail closed ---------------------------------------

for (const tool of MUTATING) {
  assert.equal(isMutatingTool(tool), true, tool)
  assertDenied(evaluateWriteCheck(crashResult(), tool), `crash must deny ${tool}`)
  assertDenied(evaluateWriteCheck({ status: 0, payload: null, stdout: "not-json", stderr: "", error: null }, tool))
  assertDenied(evaluateWriteCheck({ status: 0, payload: { reason: "missing ok" }, stdout: "{}", stderr: "", error: null }, tool))
  assertDenied(evaluateWriteCheck({ status: 1, payload: { ok: true }, stdout: "", stderr: "nonzero", error: null }, tool))
  assertDenied(evaluateWriteCheck(denyResult("phase discuss"), tool))
  assertAllowed(evaluateWriteCheck(allowResult(), tool), `ok:true status 0 allows ${tool}`)
}

for (const tool of READS) {
  assert.equal(isMutatingTool(tool), false, tool)
  assertAllowed(evaluateWriteCheck(crashResult(), tool), `crash does not block ${tool}`)
  assertAllowed(evaluateWriteCheck({ status: 0, payload: null, stdout: "not-json", stderr: "", error: null }, tool))
  assertAllowed(evaluateWriteCheck({ status: 0, payload: { reason: "missing ok" }, stdout: "{}", stderr: "", error: null }, tool))
  assertDenied(evaluateWriteCheck(denyResult("tender"), tool), `ok:false still denies ${tool}`)
  assertAllowed(evaluateWriteCheck(allowResult(), tool))
}

assert.deepEqual(writeCheckArgs("unknown", "write", "x.md"), [
  "write-check",
  "--actor",
  "unknown",
  "--tool",
  "write",
  "--path",
  "x.md",
])
assert.equal(writeCheckArgs("", "edit", "")[2], "unknown")

// --- hooks: both call write-check; crash / unknown / phase rules -----------

{
  const { handlers, calls } = await hooksWith(() => crashResult())
  const askOut = { status: "ask" }
  await handlers["permission.ask"]({ sessionID: "s1", permission: "edit", path: "draft.md" }, askOut)
  assert.equal(askOut.status, "deny", "permission.ask: python crash denies write")
  await assert.rejects(
    () =>
      handlers["tool.execute.before"](
        { sessionID: "s1", tool: "write" },
        { args: { path: "draft.md" } },
      ),
    /write-check failed/,
  )
  const readOut = { status: "ask" }
  await handlers["permission.ask"]({ sessionID: "s1", permission: "read" }, readOut)
  assert.notEqual(readOut.status, "deny", "permission.ask: crash does not deny read")
  await handlers["tool.execute.before"]({ sessionID: "s1", tool: "read" }, { args: { path: "brief.md" } })
  assert.ok(
    calls.every((c) => c.args[0] === "write-check"),
    "both hooks must invoke write-check, never phase status for the gate",
  )
  assert.ok(calls.some((c) => c.args.includes("--actor") && c.args.includes("unknown")))
}

{
  const { handlers, calls } = await hooksWith(() =>
    denyResult("write_lock denied for unknown actor"),
  )
  const askOut = { status: "ask" }
  await handlers["permission.ask"]({ sessionID: "missing", tool: "write" }, askOut)
  assert.equal(askOut.status, "deny", "unknown actor denies writes via permission.ask")
  await assert.rejects(
    () => handlers["tool.execute.before"]({ sessionID: "missing", tool: "apply_patch" }, { args: {} }),
    /unknown actor/,
  )
  const writeCalls = calls.filter((c) => c.args[0] === "write-check")
  assert.ok(writeCalls.length >= 2)
  assert.ok(writeCalls.every((c) => c.args[2] === "unknown"))
}

{
  const { handlers } = await hooksWith((_d, args) => {
    const actor = args[2]
    const tool = args[4]
    if (actor !== "primary") return denyResult(`advisor ${actor} denied`)
    if (["write", "edit", "apply_patch", "bash"].includes(tool)) {
      return denyResult("Filesystem writes are forbidden in phase discuss (only execute/revise + primary)")
    }
    return allowResult()
  })
  await remember(handlers, "p", "primary")
  await remember(handlers, "a", "advisor-sonnet")
  for (const tool of ["write", "edit", "apply_patch", "bash"]) {
    const out = { status: "ask" }
    await handlers["permission.ask"]({ sessionID: "p", permission: tool }, out)
    assert.equal(out.status, "deny", `primary ${tool} denied in discuss`)
    await assert.rejects(
      () => handlers["tool.execute.before"]({ sessionID: "p", tool }, { args: { path: "x.md" } }),
      /discuss|forbidden|denied/,
    )
    const adv = { status: "ask" }
    await handlers["permission.ask"]({ sessionID: "a", permission: tool }, adv)
    assert.equal(adv.status, "deny", `advisor ${tool} denied`)
    await assert.rejects(
      () => handlers["tool.execute.before"]({ sessionID: "a", tool }, { args: { path: "sneaky.md" } }),
      /denied/,
    )
  }
}

{
  const { handlers } = await hooksWith((_d, args) => {
    const actor = args[2]
    if (actor !== "primary") return denyResult("advisor denied")
    return allowResult()
  })
  await remember(handlers, "p", "primary")
  for (const tool of ["write", "edit", "apply_patch"]) {
    const out = { status: "ask" }
    await handlers["permission.ask"]({ sessionID: "p", permission: tool, path: "drafts/v1/response.md" }, out)
    assert.notEqual(out.status, "deny", `primary ${tool} allowed in execute`)
    await handlers["tool.execute.before"](
      { sessionID: "p", tool },
      { args: { path: "drafts/v1/response.md" } },
    )
  }
  const adv = { status: "ask" }
  await handlers["permission.ask"]({ sessionID: "nope", permission: "write" }, adv)
  assert.equal(adv.status, "deny", "unknown still denied when primary would be allowed")
}

{
  const { handlers } = await hooksWith(() => ({
    status: 0,
    payload: { reason: "looks fine" },
    stdout: "not a decision",
    stderr: "",
    error: null,
  }))
  const out = { status: "ask" }
  await handlers["permission.ask"]({ sessionID: "s", permission: "shell" }, out)
  assert.equal(out.status, "deny", "missing ok denies shell via permission.ask")
  await assert.rejects(
    () => handlers["tool.execute.before"]({ sessionID: "s", tool: "bash" }, { args: {} }),
    /no usable decision/,
  )
}

console.log("test_write_lock_plugin.mjs: ok")
