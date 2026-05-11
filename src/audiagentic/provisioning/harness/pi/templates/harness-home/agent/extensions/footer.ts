import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
    pi.on("session_start", async (_event, ctx) => {
        ctx.ui.setFooter((_tui, _theme, _footerData) => ({
            dispose: () => {},
            invalidate() {},
            render(_width: number): string[] {
                return [];
            },
        }));
    });
}
