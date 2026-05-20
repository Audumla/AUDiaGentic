import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { existsSync, readFileSync, unlinkSync } from "node:fs";
import { join } from "node:path";

const RELOAD_COMMAND = "ag-runtime-reload";
const RELOAD_POLL_MS = 1500;

function readReloadToken(markerPath: string): string | null {
    if (!existsSync(markerPath)) {
        return null;
    }
    try {
        const payload = JSON.parse(readFileSync(markerPath, "utf-8")) as { requested_at?: string };
        return payload.requested_at ?? null;
    } catch {
        return null;
    }
}

export default function (pi: ExtensionAPI) {
    pi.registerCommand(RELOAD_COMMAND, {
        description: "Reload AUDiaGentic runtime after component changes",
        handler: async (_args, ctx) => {
            await ctx.reload();
        },
    });

    pi.on("session_start", async (_event, ctx) => {
        const rigType = process.env["AUDIAGENTIC_RIG_TYPE"] ?? "unknown";
        const profile = process.env["AUDIAGENTIC_RIG_PROFILE"] ?? process.env["AUDIAGENTIC_AG_MODEL"] ?? "unknown";
        const label = `[${rigType}] ${profile}`;
        const projectRoot = process.env["AUDIAGENTIC_REPO_ROOT"];
        const markerPath = projectRoot
            ? join(projectRoot, ".audiagentic", "runtime", "harness", "reload-request.json")
            : null;
        let lastToken = markerPath ? readReloadToken(markerPath) : null;
        let reloadQueued = false;

        const maybeQueueReload = () => {
            if (!markerPath) {
                return;
            }
            const token = readReloadToken(markerPath);
            if (!token || token === lastToken || reloadQueued) {
                return;
            }
            lastToken = token;
            reloadQueued = true;
            try {
                unlinkSync(markerPath);
            } catch {}
            if (ctx.hasUI) {
                ctx.ui.notify("AUDiaGentic: reloading runtime for component changes", "info");
            }
            pi.sendUserMessage(`/${RELOAD_COMMAND}`, { deliverAs: "followUp" });
        };

        maybeQueueReload();
        const timer = setInterval(maybeQueueReload, RELOAD_POLL_MS);

        ctx.ui.setFooter((_tui, _theme, _footerData) => ({
            dispose: () => {
                clearInterval(timer);
            },
            invalidate() {},
            render(_width: number): string[] {
                return [label];
            },
        }));

        pi.on("session_shutdown", () => {
            clearInterval(timer);
        });
    });
}
