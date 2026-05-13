import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
    pi.on("session_start", async (_event, ctx) => {
        const rigType = process.env["AUDIAGENTIC_RIG_TYPE"] ?? "unknown";
        const profile = process.env["AUDIAGENTIC_RIG_PROFILE"] ?? process.env["AUDIAGENTIC_PI_MODEL"] ?? "unknown";
        const label = `[${rigType}] ${profile}`;

        ctx.ui.setFooter((_tui, _theme, _footerData) => ({
            dispose: () => {},
            invalidate() {},
            render(_width: number): string[] {
                return [label];
            },
        }));
    });
}
