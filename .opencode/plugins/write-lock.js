/**
 * Product write_lock enforcement for the branded OpenCode workspace.
 *
 * This file lives in-repo as part of prd-ai-battle. It is NOT an npm plugin
 * to install into upstream OpenCode. `prd-ai-battle` launches OpenCode with
 * this workspace; Python `write-check` is the source of truth.
 */

import { spawnSync } from "node:child_process"

const WRITE_TOOLS = new Set([
  "write",
  "edit",
  "apply_patch",
  "applypatch",
  "write_file",
  "patch",
  "strreplace",
  "str_replace",
])
const SHELL_TOOLS = new Set(["bash", "shell"])

function pythonBin() {
  return process.env.PRD_AI_PYTHON || process.env.PYTHON || "python3"
}

function repoRoot(directory) {
  return process.env.PRD_AI_ROOT || directory
}

function parseJson(text) {
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

function runCli(directory, args) {
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

function pathFromArgs(args) {
  if (!args || typeof args !== "object") return ""
  return args.filePath || args.filepath || args.path || args.file || args.target || ""
}

function actorFrom(sessionAgents, sessionID) {
  return sessionAgents.get(sessionID) || "unknown"
}

export const WriteLockHook = async ({ directory, client }) => {
  const sessionAgents = new Map()

  const remember = (sessionID, agent) => {
    if (sessionID && agent) sessionAgents.set(sessionID, agent)
  }

  return {
    "chat.message": async (input) => {
      remember(input?.sessionID, input?.agent)
    },
    "chat.params": async (input) => {
      remember(input?.sessionID, input?.agent)
    },
    "experimental.chat.system.transform": async (input, output) => {
      const result = runCli(directory, ["phase", "status"])
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
      const tool = String(permission.permission || permission.type || permission.tool || "").toLowerCase()
      if (
        actor !== "primary" &&
        actor !== "build" &&
        (WRITE_TOOLS.has(tool) || SHELL_TOOLS.has(tool) || tool === "edit" || tool === "bash")
      ) {
        output.status = "deny"
      }
    },
    "tool.execute.before": async (input, output) => {
      const tool = String(input.tool || "").toLowerCase()
      const actor = actorFrom(sessionAgents, input.sessionID)
      const filePath = pathFromArgs(output.args)
      const result = runCli(directory, [
        "write-check",
        "--actor",
        actor,
        "--tool",
        tool,
        "--path",
        filePath,
      ])
      const payload = result.payload
      if (result.error) {
        if (WRITE_TOOLS.has(tool) || SHELL_TOOLS.has(tool)) {
          throw new Error(
            `write_lock: python write-check failed (${result.error.message}). Denying ${tool}.`,
          )
        }
        return
      }
      if (payload && payload.ok === false) {
        throw new Error(payload.reason || "write_lock denied")
      }
      if ((WRITE_TOOLS.has(tool) || SHELL_TOOLS.has(tool)) && result.status !== 0) {
        throw new Error(result.stderr || result.stdout || `write_lock denied ${tool} for ${actor}`)
      }
    },
    "tool.execute.after": async (input, output) => {
      const tool = String(input.tool || "").toLowerCase()
      if (!WRITE_TOOLS.has(tool)) return
      const actor = actorFrom(sessionAgents, input.sessionID)
      if (actor !== "primary" && actor !== "build") return
      const filePath = pathFromArgs(output.args) || pathFromArgs(input)
      if (!filePath) return
      runCli(directory, ["record-draft", "--actor", actor, "--path", filePath])
    },
  }
}

export default WriteLockHook
