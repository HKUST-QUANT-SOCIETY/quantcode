const { spawn } = require("node:child_process")
const { existsSync } = require("node:fs")
const path = require("node:path")

const projectRoot = path.resolve(__dirname, "../..")
const venvPython = path.join(projectRoot, ".venv", "bin", "python")
const python = existsSync(venvPython) ? venvPython : "python3"
const bridge = path.join(projectRoot, "scripts", "run_risk_gate_tool.py")

function runPython(args) {
  return new Promise((resolve, reject) => {
    const child = spawn(python, [bridge, ...args], {
      cwd: projectRoot,
      env: { ...process.env, PYTHONPATH: projectRoot },
      stdio: ["ignore", "pipe", "pipe"],
    })

    let stdout = ""
    let stderr = ""
    child.stdout.setEncoding("utf8")
    child.stderr.setEncoding("utf8")
    child.stdout.on("data", (chunk) => {
      stdout += chunk
    })
    child.stderr.on("data", (chunk) => {
      stderr += chunk
    })
    child.on("error", reject)
    child.on("close", (code) => {
      if (code === 0) resolve({ stdout, stderr })
      else reject(new Error(`risk_gate_demo failed with exit ${code}\n${stderr || stdout}`))
    })
  })
}

module.exports = {
  description:
    "Run QuantCode risk:gate Python flow via local stub data. Use for PR risk review demos; it returns RiskProfile, HumanGate status, acceptance, and artifact paths.",
  args: {
    scenario: {
      type: "string",
      enum: ["normal", "high_risk"],
      description: "normal runs straight through; high_risk triggers HumanGate and then uses the decision.",
    },
    decision: {
      type: "string",
      enum: ["approve", "reject", "pending"],
      description: "HumanGate decision for high_risk. Use pending to stop after interrupt.",
    },
    pr_number: {
      type: "string",
      description: "PR number used in generated artifact filenames.",
    },
    head_sha: {
      type: "string",
      description: "Commit SHA used for PR comment dedupe.",
    },
    pr_url: {
      type: "string",
      description: "Optional PR URL. Defaults to the QuantCode repository PR URL.",
    },
  },
  async execute(args) {
    const cliArgs = [
      "--scenario",
      args.scenario ?? "normal",
      "--decision",
      args.decision ?? "approve",
      "--pr-number",
      args.pr_number ?? "303",
      "--head-sha",
      args.head_sha ?? "opencode1234567890abcdef",
    ]
    if (args.pr_url) cliArgs.push("--pr-url", args.pr_url)

    const { stdout, stderr } = await runPython(cliArgs)
    const parsed = JSON.parse(stdout)
    const title =
      parsed.status === "waiting_for_human"
        ? "risk:gate waiting for HumanGate approval"
        : `risk:gate ${parsed.status}`
    return {
      title,
      output: JSON.stringify(parsed, null, 2),
      metadata: {
        scenario: args.scenario ?? "normal",
        status: parsed.status,
        thread_id: parsed.thread_id,
        artifacts: parsed.artifacts ?? [],
        stderr,
      },
    }
  },
}
