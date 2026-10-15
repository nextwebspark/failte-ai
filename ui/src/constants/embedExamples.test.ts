import { afterEach, describe, expect, it, vi } from "vitest";

import { HEADLESS_CHAT_EXAMPLE } from "./embedExamples";

type HeadlessWidget = {
    onChatStateChange: (callback: (state: string) => void) => void;
    onMessage: (callback: (text: string, turn: unknown) => void) => void;
    startChat: () => void;
    endChat: () => Promise<unknown[] | null>;
    sendMessage: (text: string) => Promise<unknown[]>;
};

type WidgetWindow = Window & { LightMoveWidget?: HeadlessWidget };

describe("headless chat embed example", () => {
    afterEach(() => {
        delete (window as WidgetWindow).LightMoveWidget;
        vi.unstubAllGlobals();
        vi.restoreAllMocks();
        document.body.innerHTML = "";
    });

    it("waits for the async widget script before registering callbacks", () => {
        document.body.innerHTML = `
            <script id="lightmove-widget"></script>
            <button id="open-chat"></button>
            <input id="chat-input" />
            <button id="send-btn"></button>
            <button id="end-chat"></button>
        `;
        vi.stubGlobal("appendAgentBubble", vi.fn());
        vi.stubGlobal("appendVisitorBubble", vi.fn());

        const onChatStateChange = vi.fn();
        const onMessage = vi.fn();
        const widget: HeadlessWidget = {
            onChatStateChange,
            onMessage,
            startChat: vi.fn(),
            endChat: vi.fn(async () => []),
            sendMessage: vi.fn(async () => []),
        };

        window.eval(HEADLESS_CHAT_EXAMPLE);

        expect(onChatStateChange).not.toHaveBeenCalled();
        expect(onMessage).not.toHaveBeenCalled();

        (window as WidgetWindow).LightMoveWidget = widget;
        document.getElementById("lightmove-widget")?.dispatchEvent(new Event("load"));

        expect(onChatStateChange).toHaveBeenCalledOnce();
        expect(onMessage).toHaveBeenCalledOnce();
    });
});
