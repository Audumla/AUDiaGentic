import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

type FollowUpTarget = {
    handler?: string;
    kwargs?: Record<string, unknown>;
};

type FollowUpAction = {
    id?: string;
    kind?: string;
    title?: string;
    message?: string;
    target?: FollowUpTarget;
};

type RuntimeSync = {
    action?: string;
    component_id?: string;
};

function getFollowUpAction(details: unknown): FollowUpAction | undefined {
    if (!details || typeof details !== "object" || Array.isArray(details)) {
        return undefined;
    }
    const mcpResult = (details as Record<string, unknown>).mcpResult;
    if (!mcpResult || typeof mcpResult !== "object" || Array.isArray(mcpResult)) {
        return undefined;
    }
    const structured = (mcpResult as Record<string, unknown>).structuredContent;
    if (!structured || typeof structured !== "object" || Array.isArray(structured)) {
        return undefined;
    }
    const followUp = (structured as Record<string, unknown>).follow_up;
    if (!followUp || typeof followUp !== "object" || Array.isArray(followUp)) {
        return undefined;
    }
    return followUp as FollowUpAction;
}

function getRuntimeSync(details: unknown): RuntimeSync | undefined {
    if (!details || typeof details !== "object" || Array.isArray(details)) {
        return undefined;
    }
    const sync = (details as Record<string, unknown>).sync;
    if (!sync || typeof sync !== "object" || Array.isArray(sync)) {
        return undefined;
    }
    return sync as RuntimeSync;
}

function summarizeExecResult(stdout: string, stderr: string): string {
    const text = stdout.trim() || stderr.trim();
    if (!text) {
        return "Follow-up action completed.";
    }
    return text.length > 800 ? `${text.slice(0, 800)}...` : text;
}

export default function followUpActions(pi: ExtensionAPI) {
    const seen = new Set<string>();

    pi.on("tool_result", async (event, ctx) => {
        if (!ctx.hasUI) {
            return;
        }

        const followUp = getFollowUpAction(event.details);
        if (!followUp || followUp.kind !== "confirmable_handler_call") {
            return;
        }

        const key = followUp.id
            ?? JSON.stringify({ title: followUp.title, message: followUp.message, target: followUp.target });
        if (seen.has(key)) {
            return;
        }
        seen.add(key);

        const confirmed = await ctx.ui.confirm(
            followUp.title ?? "Confirm follow-up action",
            followUp.message ?? "Proceed?",
        );
        if (!confirmed) {
            ctx.ui.notify("Follow-up action cancelled.", "info");
            return;
        }

        const payload = JSON.stringify(followUp);
        const result = await pi.exec("python", [
            "-m",
            "audiagentic.foundation.invoke.follow_up_executor",
            "--payload",
            payload,
        ]);

        const summary = summarizeExecResult(result.stdout ?? "", result.stderr ?? "");
        if (result.exitCode === 0) {
            ctx.ui.notify("Follow-up action completed.", "info");
            ctx.ui.setStatus("audiagentic-follow-up", summary);
        } else {
            ctx.ui.notify("Follow-up action failed.", "error");
            ctx.ui.setStatus("audiagentic-follow-up", summary);
            return;
        }

        const sync = getRuntimeSync(event.details);
        if (sync?.action === "reload_required") {
            const component = sync.component_id ? ` for component "${sync.component_id}"` : "";
            ctx.ui.notify(`AUDiaGentic runtime changed${component}. Reload Pi session to apply updates.`, "info");
        }
    });
}

