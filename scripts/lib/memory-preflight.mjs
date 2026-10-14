// Compares the memory limits of the selected services with the memory the Docker engine has, so a
// too small WSL2 VM is explained before the model is killed by the kernel (ADR-001 section 8).
const UNITS = { b: 1, k: 1024, m: 1024 ** 2, g: 1024 ** 3 };

/** Bytes from a Compose mem_limit value (a number, "268435456", "6g", "64m", "512MB"). */
export function parseMemory(value) {
  if (typeof value === "number") return value;
  const match = String(value ?? "")
    .trim()
    .toLowerCase()
    .match(/^(\d+(?:\.\d+)?)\s*([bkmg])?b?$/);
  if (!match) return 0;
  return Math.round(Number(match[1]) * UNITS[match[2] ?? "b"]);
}

export function totalMemoryLimit(services) {
  return Object.values(services).reduce((sum, service) => sum + parseMemory(service.mem_limit), 0);
}

const gigabytes = (bytes) => (bytes / 1024 ** 3).toFixed(1);

/** Warning text, or null when the limits fit (or the engine memory is unknown). */
export function memoryWarning(services, engineBytes) {
  const needed = totalMemoryLimit(services);
  if (!engineBytes || needed <= engineBytes) return null;
  return [
    `Warning: the selected services may use up to ${gigabytes(needed)} GB (sum of the memory limits) but Docker has ${gigabytes(engineBytes)} GB.`,
    "The model server normally needs 3-5 GB in practice, so this can still work, but the kernel may kill a container when memory runs out.",
    "Docker Desktop with WSL2: create %UserProfile%\\.wslconfig with [wsl2] memory=10GB, then run `wsl --shutdown` and restart Docker Desktop.",
    "Or start without the model: npm run up -- --no-model",
  ].join("\n");
}
