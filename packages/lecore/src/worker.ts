import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process"
import { fileURLToPath } from "node:url"
import { resolve } from "node:path"
import type { Socket } from "node:net"
import { existsSync } from "node:fs"

export type WorkerConfig = {
  python?: string
  workerPath?: string
  timeoutMs?: number
  cacheDirectory?: string
}

export type Item = {
  id: string
  text: string
  source: string
  kind: string
  file_path?: string
}

export type Recall = {
  id: string
  ok: true
  entries: Item[]
  evidence: Item[]
  metrics: Record<string, unknown>
  engine?: { name?: string; revision?: string }
}

type Pending = {
  resolve: (response: Record<string, unknown>) => void
  reject: (error: Error) => void
  finish: () => void
}

const workers = new Map<string, Worker>()
const defaultPath = fileURLToPath(new URL("../python/worker.py", import.meta.url))
const defaultPython = fileURLToPath(
  new URL(process.platform === "win32" ? "../.venv/Scripts/python.exe" : "../.venv/bin/python", import.meta.url),
)

function python(config: WorkerConfig) {
  return config.python ?? process.env.LECORE_PYTHON ?? (existsSync(defaultPython) ? defaultPython : "python3")
}

export class LecoreError extends Error {
  constructor(message: string) {
    super(`lecore: ${message}. Set OPENCODE_LECORE=0 only for an explicit baseline run.`)
    this.name = "LecoreError"
  }
}

class Worker {
  readonly child: ChildProcessWithoutNullStreams
  readonly pipes: Socket[]
  readonly pending = new Map<string, Pending>()
  buffer = ""
  stderr = ""
  idle?: ReturnType<typeof setTimeout>
  closed = false

  constructor(
    readonly key: string,
    config: WorkerConfig,
  ) {
    this.child = spawn(python(config), [config.workerPath ?? defaultPath], {
      env: {
        ...process.env,
        PYTHONHASHSEED: "0",
        PYTHONUNBUFFERED: "1",
        ...(config.cacheDirectory ? { LECORE_STORAGE_DIR: config.cacheDirectory } : {}),
      },
      stdio: "pipe",
    })
    this.pipes = [this.child.stdin, this.child.stdout, this.child.stderr].map((pipe) => pipe as Socket)
    this.child.stdout.setEncoding("utf8")
    this.child.stderr.setEncoding("utf8")
    this.child.stdout.on("data", (chunk: string) => this.receive(chunk))
    this.child.stderr.on("data", (chunk: string) => {
      this.stderr = (this.stderr + chunk).slice(-4000)
    })
    this.child.on("error", (error) => this.close(new LecoreError(`worker could not start: ${error.message}`)))
    this.child.on("exit", (code, signal) =>
      this.close(new LecoreError(`worker exited (${signal ?? code}): ${this.stderr.trim()}`)),
    )
    this.child.unref()
    this.pipes.forEach((pipe) => pipe.unref?.())
  }

  receive(chunk: string) {
    this.buffer += chunk
    if (this.buffer.length > 4_000_000) return this.close(new LecoreError("worker response exceeded 4 MB"))
    while (this.buffer.includes("\n")) {
      const split = this.buffer.indexOf("\n")
      const line = this.buffer.slice(0, split)
      this.buffer = this.buffer.slice(split + 1)
      if (!line.trim()) continue
      const response = parse(line)
      if (!response || typeof response.id !== "string") {
        this.close(new LecoreError("worker returned an invalid JSONL response"))
        return
      }
      const pending = this.pending.get(response.id)
      if (!pending) continue
      this.pending.delete(response.id)
      pending.finish()
      if (response.ok !== true) pending.reject(new LecoreError(String(response.error ?? "worker request failed")))
      if (response.ok === true) pending.resolve(response)
      this.release()
    }
  }

  request(input: Record<string, unknown>, timeoutMs: number, signal?: AbortSignal) {
    if (this.closed) return Promise.reject(new LecoreError("worker is closed"))
    if (signal?.aborted) return Promise.reject(signal.reason ?? new Error("lecore request aborted"))
    if (this.idle) clearTimeout(this.idle)
    this.child.ref()
    this.pipes.forEach((pipe) => pipe.ref?.())
    const id = crypto.randomUUID()
    return new Promise<Record<string, unknown>>((resolve, reject) => {
      const abort = () => {
        const current = this.pending.get(id)
        if (!current) return
        this.pending.delete(id)
        current.finish()
        current.reject(signal?.reason ?? new Error("lecore request aborted"))
        this.release()
      }
      const timer = setTimeout(() => this.close(new LecoreError(`worker timed out after ${timeoutMs} ms`)), timeoutMs)
      this.pending.set(id, {
        resolve,
        reject,
        finish: () => {
          clearTimeout(timer)
          signal?.removeEventListener("abort", abort)
        },
      })
      signal?.addEventListener("abort", abort, { once: true })
      this.child.stdin.write(JSON.stringify({ ...input, id }) + "\n", (error) => {
        if (error) this.close(new LecoreError(`worker input failed: ${error.message}`))
      })
    })
  }

  release() {
    if (this.pending.size || this.closed) return
    this.child.unref()
    this.pipes.forEach((pipe) => pipe.unref?.())
    this.idle = setTimeout(() => this.close(), 60_000)
    this.idle.unref()
  }

  close(error = new LecoreError("worker was closed")) {
    if (this.closed) return
    this.closed = true
    if (this.idle) clearTimeout(this.idle)
    workers.delete(this.key)
    this.pending.forEach((pending) => {
      pending.finish()
      pending.reject(error)
    })
    this.pending.clear()
    this.child.stdin.destroy()
    this.child.stdout.destroy()
    this.child.stderr.destroy()
    this.child.kill()
  }
}

function parse(line: string): Record<string, unknown> | undefined {
  try {
    const value: unknown = JSON.parse(line)
    if (typeof value === "object" && value !== null && !Array.isArray(value)) return value as Record<string, unknown>
  } catch {
    return
  }
}

export async function requestWorker(input: Record<string, unknown>, config: WorkerConfig, signal?: AbortSignal) {
  if (signal?.aborted) throw signal.reason ?? new Error("lecore request aborted")
  const key = JSON.stringify([python(config), config.workerPath ?? defaultPath, config.cacheDirectory])
  const worker = workers.get(key) ?? new Worker(key, config)
  workers.set(key, worker)
  return worker.request(input, config.timeoutMs ?? 30_000, signal)
}

export function closeWorkers() {
  workers.forEach((worker) => worker.close())
}

export function workspacePath(workspace: string) {
  return resolve(workspace)
}

process.once("exit", closeWorkers)
