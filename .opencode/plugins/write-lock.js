/**
 * Product write_lock enforcement for the branded OpenCode workspace.
 *
 * This file lives in-repo as part of prd-ai-battle. It is NOT an npm plugin
 * to install into upstream OpenCode. `prd-ai-battle` launches OpenCode with
 * this workspace; Python `write-check` is the source of truth.
 *
 * Both `permission.ask` and `tool.execute.before` call
 * `python3 -m prd_ai_battle write-check --actor --tool --path`.
 * Spawn errors, non-zero exits, missing/non-JSON payloads, and ok:false
 * all deny write/edit/apply_patch/shell/bash (fail closed).
 */

import { spawnSync } from "node:child_process"

export const WRITE_TOOLS = new Set([
  "write",
  "edit",
  "apply_patch",
  "applypatch",
  "write_file",
  "patch",
  "strreplace",
  "str_replace",
])
export const SHELL_TOOLS = new Set(["bash", "shell"])

function pythonBin() {
  return process.env.PRD_AI_PYTHON || process.env.PYTHON || "python3"
}

function repoRoot(directory) {
  return process.env.PRD_AI_ROOT || directory
}

export function parseJson(text) {
  const trimmed = (text || "").trim()
  if (!trimmed) return null
  try {
    return JSON.parse(trimmed)
  } catch {
    const start = trimmed.indexOf("{")
    const end = trimmed.lastIndexOf("}")
    if (start >= 0 && end > start) {
      try {
        return JSON.parse(trimmed.slice(start, end + 1))
      } catch {
        return null
      }
    }
    return null
  }
}

export function isMutatingTool(tool) {
  const name = String(tool || "").toLowerCase()
  return WRITE_TOOLS.has(name) || SHELL_TOOLS.has(name)
}

export function runCli(directory, args) {
  const result = spawnSync(pythonBin(), ["-m", "prd_ai_battle", ...args], {
    cwd: repoRoot(directory),
    encoding: "utf8",
    env: process.env,
  })
  const stdout = result.stdout || ""
  const stderr = result.stderr || ""
  return {
    status: result.status,
    payload: parseJson(stdout) || parseJson(stderr),
    stdout,
    stderr,
    error: result.error,
  }
}

export function writeCheckArgs(actor, tool, filePath) {
  return [
    "write-check",
    "--actor",
    String(actor || "unknown"),
    "--tool",
    String(tool || ""),
    "--path",
    String(filePath || ""),
  ]
}

export function runWriteCheck(directory, actor, tool, filePath, spawn = runCli) {
  return spawn(directory, writeCheckArgs(actor, tool, filePath))
}

/**
 * Fail-closed decision from a write-check spawn result.
 * Write/edit/patch/shell: deny unless payload.ok === true and status === 0.
 * Read-only tools: deny only when write-check explicitly returns ok:false.
 */
export function evaluateWriteCheck(result, tool) {
  const name = String(tool || "").toLowerCase()
  const mutating = isMutatingTool(name)
  const failedSpawn = Boolean(result && result.error)
  const payload = result && result.payload
  const status = result && typeof result.status === "number" ? result.status : 1
  const hasDecision = Boolean(payload) && typeof payload.ok === "boolean"

  if (failedSpawn) {
    if (mutating) {
      const msg = result.error && result.error.message ? result.error.message : "spawn error"
      return {
        deny: true,
        reason: `write_lock: python write-check failed (${msg}). Denying ${name || "write"}.`,
      }
    }
    return { deny: false, reason: "" }
  }

  if (!hasDecision) {
    if (mutating) {
      return {
        deny: true,
        reason: `write_lock: write-check returned no usable decision. Denying ${name || "write"}.`,
      }
    }
    return { deny: false, reason: "" }
  }

  if (payload.ok === false) {
    return { deny: true, reason: payload.reason || "write_lock denied" }
  }

  if (mutating && status !== 0) {
    return {
      deny: true,
      reason:
        (result && (result.stderr || result.stdout)) ||
        `write_lock denied ${name} for ${(payload && payload.actor) || "unknown"}`,
    }
  }

  return { deny: false, reason: "", payload }
}

export function pathFromArgs(args) {
  if (!args || typeof args !== "object") return ""
  if (typeof args.pattern === "string" && args.pattern) return args.pattern
  if (Array.isArray(args.patterns) && args.patterns[0]) return String(args.patterns[0])
  return args.filePath || args.filepath || args.path || args.file || args.target || ""
}

export function actorFrom(sessionAgents, sessionID) {
  return sessionAgents.get(sessionID) || "unknown"
}

function permissionPath(permission, output) {
  return (
    pathFromArgs(permission) ||
    pathFromArgs(permission && permission.metadata) ||
    pathFromArgs(permission && permission.extra) ||
    pathFromArgs(output && output.args) ||
    ""
  )
}

export function createWriteLockHook({ runCliImpl } = {}) {
  const spawn = runCliImpl || runCli

  return async ({ directory, client } = {}) => {
    const sessionAgents = new Map()

    const remember = (sessionID, agent) => {
      if (sessionID && agent) sessionAgents.set(sessionID, agent)
    }

    const decide = (actor, tool, filePath) => {
      const result = runWriteCheck(directory, actor, tool, filePath, spawn)
      return { result, decision: evaluateWriteCheck(result, tool), actor, tool, filePath }
    }

    return {
      "chat.message": async (input) => {
        remember(input?.sessionID, input?.agent)
      },
      "chat.params": async (input) => {
        remember(input?.sessionID, input?.agent)
      },
      "experimental.chat.system.transform": async (input, output) => {
        const result = spawn(directory, ["phase", "status"])
        const payload = result.payload
        if (payload) {
          output.system.push(
            [
              "prd-ai-battle contract:",
              `phase=${payload.phase}`,
              `primary=${payload.primary}`,
              `advisors=${(payload.advisors || []).join(",")}`,
              `write_lock=${payload.write_lock}`,
              `artifact_version=${payload.artifact_version || "(none)"}`,
              `matrix_locked=${payload.matrix_locked}`,
              "Advisors always have tools=[]. Review input is brief+matrix+chapter_diff only.",
            ].join(" "),
          )
        }
      },
      "permission.ask": async (input, output) => {
        const permission = input || {}
        const sessionID = permission.sessionID || permission.session_id
        const actor = actorFrom(sessionAgents, sessionID)
        const tool = String(
          permission.permission || permission.type || permission.tool || "",
        ).toLowerCase()
        const filePath = permissionPath(permission, output)
        const { decision } = decide(actor, tool, filePath)
        if (decision.deny) {
          output.status = "deny"
        }
      },
      "tool.execute.before": async (input, output) => {
        const tool = String((input && input.tool) || "").toLowerCase()
        const actor = actorFrom(sessionAgents, input && input.sessionID)
        const filePath = pathFromArgs(output && output.args) || pathFromArgs(input)
        const { decision } = decide(actor, tool, filePath)
        if (decision.deny) {
          throw new Error(decision.reason || `write_lock denied ${tool} for ${actor}`)
        }
      },
      "tool.execute.after": async (input, output) => {
        const tool = String((input && input.tool) || "").toLowerCase()
        if (!WRITE_TOOLS.has(tool)) return
        const actor = actorFrom(sessionAgents, input && input.sessionID)
        const status = spawn(directory, ["phase", "status"])
        const primary = (status.payload && status.payload.primary) || ""
        if (!primary || actor !== primary || actor === "unknown") return
        const filePath = pathFromArgs(output && output.args) || pathFromArgs(input)
        if (!filePath) return
        spawn(directory, ["record-draft", "--actor", actor, "--path", filePath])
      },
    }
  }
}

export const WriteLockHook = createWriteLockHook()
export default WriteLockHook
