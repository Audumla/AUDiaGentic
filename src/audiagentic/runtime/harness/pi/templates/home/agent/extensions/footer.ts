import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { existsSync, readFileSync, unlinkSync } from "node:fs";
import { join } from "node:path";

const RELOAD_POLL_MS = 1500;

type RuntimeAction = "refresh_required" | "reload_required" | "restart_required";

type ReloadMarker = {
    requested_at?: string;
    action?: RuntimeAction;
    reason?: string;
    component_id?: string;
};

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

function readReloadMarker(markerPath: string): ReloadMarker | null {
    if (!existsSync(markerPath)) {
        return null;
    }
    try {
        return JSON.parse(readFileSync(markerPath, "utf-8")) as ReloadMarker;
    } catch {
        return null;
    }
}

function buildRuntimeNotice(marker: ReloadMarker): string {
    const component = marker.component_id ? ` for component '${marker.component_id}'` : "";
    switch (marker.action) {
        case "refresh_required":
            return `AUDiaGentic runtime files refreshed${component}.`;
        case "reload_required":
            return `AUDiaGentic runtime changed${component}. Reload Pi session to apply updates.`;
        case "restart_required":
        default:
            return `AUDiaGentic runtime changed${component}. Restart Pi session to load updated component config.`;
    }
}

export default function (pi: ExtensionAPI) {
    pi.registerCommand("ag-runtime-reload", {
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

        const maybeQueueReload = async () => {
            if (!markerPath) {
                return;
            }
            const token = readReloadToken(markerPath);
            const marker = readReloadMarker(markerPath);
            if (!token || token === lastToken || reloadQueued) {
                return;
            }
            lastToken = token;
            reloadQueued = true;
            try {
                unlinkSync(markerPath);
            } catch {}
            if (ctx.hasUI) {
                const message = buildRuntimeNotice(marker ?? {});
                ctx.ui.notify(message, "info");
                ctx.ui.setStatus("audiagentic-runtime-action", message);
            }
        };

        void maybeQueueReload();
        const timer = setInterval(() => {
            void maybeQueueReload();
        }, RELOAD_POLL_MS);

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
