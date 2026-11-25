import { execFile } from "node:child_process";
import { homedir } from "node:os";
import { join } from "node:path";

// A chat switched from Claude to Pi dropped valentin-mode and its board drain loop: Pi runs no
// skill frontmatter hook, so nothing handed it the version line or the re-arm order (VSTA-305).

interface StartContext {
  customType: string;
  content: string;
  display: boolean;
}

interface PiApi {
  on(event: "session_start", handler: () => void): void;
  sendMessage(message: StartContext, options: { deliverAs: "nextTurn" }): void;
}

export default function (pi: PiApi) {
  pi.on("session_start", () => {
    execFile(
      "python3",
      [join(homedir(), ".claude", "hooks", "harness-start.py"),
       "--harness", "pi", "--event", "start"],
      { timeout: 5000, env: process.env },
      (_error: Error | null, stdout: string) => {
        const text = (stdout || "").trim();
        if (!text) return;
        pi.sendMessage(
          { customType: "vstack-valentin-mode", content: text, display: false },
          { deliverAs: "nextTurn" },
        );
      },
    );
  });
}
