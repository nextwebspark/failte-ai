import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const widgetSource = readFileSync(
    resolve(process.cwd(), 'public/embed/lightmove-widget.js'),
    'utf8',
);
const fallchaShimSource = readFileSync(
    resolve(process.cwd(), 'public/embed/fallcha-widget.js'),
    'utf8',
);

type WidgetWindow = Window & {
    LightMoveWidget?: {
        init: () => Promise<void>;
        start: () => Promise<void>;
        startChat: () => Promise<void>;
        endChat: () => Promise<unknown[] | null>;
        getState: () => { chat: { status: string }; disclosureText: string | null };
        getDisclosureText: () => string | null;
        getContext: () => Record<string, unknown>;
    };
    FallchaWidget?: unknown;
    FailteWidget?: unknown;
    DograhWidget?: unknown;
};

// The embed config endpoint resolves every visitor-facing label server-side, so
// the widget never carries defaults of its own. Mirror that here.
const WIDGET_TEXTS = {
    endChatText: 'End chat',
    endChatConfirmText: 'End this chat?',
    endChatCancelText: 'Cancel',
    endingChatText: 'Ending…',
    conversationEndedText: 'Conversation ended.',
    startNewChatText: 'Start new chat',
    chatRetryText: 'Retry',
    chatInputPlaceholder: 'Type a message…',
    sendMessageLabel: 'Send message',
    closeChatLabel: 'Close chat',
};

async function flushMicrotasks() {
    for (let i = 0; i < 5; i += 1) {
        await Promise.resolve();
    }
}

function createFetchMock(autoStart: boolean) {
    return vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes('/api/v1/public/embed/config/')) {
            return {
                ok: true,
                status: 200,
                json: async () => ({
                    workflow_id: 7,
                    settings: {
                        widgetType: 'chat',
                        embedMode: 'inline',
                        containerId: 'lightmove-inline-container',
                    },
                    texts: WIDGET_TEXTS,
                    auto_start: autoStart,
                }),
            } as Response;
        }

        if (url.includes('/api/v1/public/embed/chat/') && url.endsWith('/end')) {
            return {
                ok: true,
                status: 200,
                json: async () => ({
                    revision: 3,
                    state: 'completed',
                    is_completed: true,
                    turns: [],
                }),
            } as Response;
        }

        return {
            ok: true,
            status: 200,
            json: async () => ({
                session_token: 'emb_session_TEST',
                workflow_run_id: 101,
                chat_session: {
                    revision: 2,
                    state: 'running',
                    is_completed: false,
                    turns: [],
                },
            }),
        } as Response;
    });
}

function countInitCalls(fetchMock: ReturnType<typeof createFetchMock>) {
    return fetchMock.mock.calls.filter(([url]) =>
        String(url).endsWith('/api/v1/public/embed/init'),
    ).length;
}

async function loadWidget(fetchMock: ReturnType<typeof createFetchMock>) {
    vi.stubGlobal('fetch', fetchMock);
    window.eval(widgetSource);
    await flushMicrotasks();

    const widget = (window as WidgetWindow).LightMoveWidget;
    expect(widget).toBeDefined();
    if (fetchMock.mock.calls.length === 0) {
        await widget?.init();
    }
    await flushMicrotasks();
    return widget as NonNullable<WidgetWindow['LightMoveWidget']>;
}

describe('public embed widget chat lifecycle', () => {
    beforeEach(() => {
        vi.useFakeTimers();
        document.head.innerHTML = '';
        document.body.innerHTML = `
            <script src="http://widget.test/embed/lightmove-widget.js?token=emb_TEST"></script>
            <div id="lightmove-inline-container"></div>
        `;
    });

    afterEach(() => {
        delete (window as WidgetWindow).LightMoveWidget;
        delete (window as WidgetWindow).FallchaWidget;
        delete (window as WidgetWindow).FailteWidget;
        delete (window as WidgetWindow).DograhWidget;
        vi.useRealTimers();
        vi.unstubAllGlobals();
        vi.restoreAllMocks();
        document.head.innerHTML = '';
        document.body.innerHTML = '';
    });

    it('auto-start replaces the inline CTA with the started conversation', async () => {
        const fetchMock = createFetchMock(true);
        await loadWidget(fetchMock);
        await vi.advanceTimersByTimeAsync(1000);
        await flushMicrotasks();

        expect(countInitCalls(fetchMock)).toBe(1);
        expect(document.querySelector('.lightmove-chat-inline-cta')).toBeNull();
        expect(document.querySelector('.lightmove-chat-panel--inline')).not.toBeNull();
    });

    it('public startChat opens the inline panel and reuses its session', async () => {
        const fetchMock = createFetchMock(false);
        const widget = await loadWidget(fetchMock);

        expect(document.querySelector('.lightmove-chat-inline-cta')).not.toBeNull();
        expect(countInitCalls(fetchMock)).toBe(0);

        await widget.startChat();
        await flushMicrotasks();

        expect(countInitCalls(fetchMock)).toBe(1);
        expect(document.querySelector('.lightmove-chat-inline-cta')).toBeNull();
        expect(document.querySelector('.lightmove-chat-panel--inline')).not.toBeNull();

        await widget.startChat();
        await flushMicrotasks();
        expect(countInitCalls(fetchMock)).toBe(1);
    });

    it('shows an end-chat action that completes the server session', async () => {
        const fetchMock = createFetchMock(false);
        const widget = await loadWidget(fetchMock);

        await widget.startChat();
        await flushMicrotasks();

        const endButton = document.querySelector<HTMLButtonElement>('.lightmove-chat-end');
        expect(endButton).not.toBeNull();
        expect(endButton?.disabled).toBe(false);

        endButton?.click();
        await flushMicrotasks();

        expect(fetchMock.mock.calls.some(([url]) =>
            String(url).endsWith('/api/v1/public/embed/chat/emb_session_TEST/end'),
        )).toBe(false);

        expect(document.querySelector('.lightmove-chat-end-confirmation')?.textContent)
            .toContain(WIDGET_TEXTS.endChatConfirmText);
        expect(document.querySelector('.lightmove-chat-end-confirm-cancel')?.textContent)
            .toBe(WIDGET_TEXTS.endChatCancelText);

        const confirmEndButton = document.querySelector<HTMLButtonElement>(
            '.lightmove-chat-end-confirm-submit',
        );
        expect(confirmEndButton).not.toBeNull();
        confirmEndButton?.click();
        await flushMicrotasks();

        const endCalls = fetchMock.mock.calls.filter(([url]) =>
            String(url).endsWith('/api/v1/public/embed/chat/emb_session_TEST/end'),
        );
        expect(endCalls).toHaveLength(1);
        expect(widget.getState().chat.status).toBe('ended');
        expect(document.querySelector('.lightmove-chat-banner')?.textContent).toContain('Conversation ended.');
        expect(document.querySelector<HTMLButtonElement>('.lightmove-chat-send')?.disabled).toBe(true);
    });

    it('generic start waits for chat configuration before choosing a flow', async () => {
        let resolveConfig: (response: Response) => void = () => undefined;
        const configResponse = new Promise<Response>((resolve) => {
            resolveConfig = resolve;
        });
        const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
            const url = String(input);
            if (url.includes('/api/v1/public/embed/config/')) {
                return configResponse;
            }
            if (url.endsWith('/api/v1/public/embed/init')) {
                return {
                    ok: true,
                    status: 200,
                    json: async () => ({
                        session_token: 'emb_session_TEST',
                        workflow_run_id: 101,
                        config: { workflow_id: 7 },
                        chat_session: {
                            revision: 2,
                            state: 'running',
                            is_completed: false,
                            turns: [],
                        },
                    }),
                } as Response;
            }
            if (url.includes('/turn-credentials/')) {
                return { ok: false, status: 503 } as Response;
            }
            throw new Error(`Unexpected request: ${url}`);
        });
        const getUserMedia = vi.fn().mockRejectedValue(
            Object.assign(new Error('permission denied'), { name: 'NotAllowedError' }),
        );
        vi.stubGlobal('fetch', fetchMock);
        vi.stubGlobal('navigator', { mediaDevices: { getUserMedia } });

        window.eval(widgetSource);
        await flushMicrotasks();
        const widget = (window as WidgetWindow).LightMoveWidget;
        expect(widget).toBeDefined();

        const startPromise = widget?.start();
        await flushMicrotasks();

        expect(countInitCalls(fetchMock)).toBe(0);
        expect(getUserMedia).not.toHaveBeenCalled();

        resolveConfig({
            ok: true,
            status: 200,
            json: async () => ({
                workflow_id: 7,
                settings: {
                    widgetType: 'chat',
                    embedMode: 'inline',
                    containerId: 'lightmove-inline-container',
                },
                auto_start: false,
            }),
        } as Response);
        await startPromise;
        await flushMicrotasks();

        const configCalls = fetchMock.mock.calls.filter(([url]) =>
            String(url).includes('/api/v1/public/embed/config/'),
        );
        expect(configCalls).toHaveLength(1);
        expect(countInitCalls(fetchMock)).toBe(1);
        expect(getUserMedia).not.toHaveBeenCalled();
        expect(document.querySelector('.lightmove-chat-panel--inline')).not.toBeNull();
    });
});

// EU AI Act Art. 50 and call-recording notice: every voice widget tells the
// visitor before the microphone opens, without a blocking dialog.
describe('public embed widget voice disclosure', () => {
    const DISCLOSURE = "You'll talk to an AI assistant. The call is recorded and uses your microphone.";
    const VOICE_TEXTS = {
        voiceConnectingText: 'Connecting…',
        voiceEndCallText: 'End Call',
        voiceRetryText: 'Retry',
        voiceReadyTitle: 'Ready to Connect',
        voiceConnectingSubtext: 'Please wait',
        voiceConnectedTitle: 'Connected',
        voiceConnectedSubtext: 'Your voice call is now active',
        voiceConnectionFailedTitle: 'Connection failed',
        voiceConnectionFailedSubtext: 'Please check your microphone and try again',
        voiceDisclosureText: DISCLOSURE,
    };

    beforeEach(() => {
        vi.useFakeTimers();
        document.head.innerHTML = '';
        document.body.innerHTML = `
            <script src="http://widget.test/embed/lightmove-widget.js?token=emb_TEST"></script>
            <div id="lightmove-inline-container"></div>
        `;
    });

    afterEach(() => {
        delete (window as WidgetWindow).LightMoveWidget;
        delete (window as WidgetWindow).FallchaWidget;
        delete (window as WidgetWindow).FailteWidget;
        delete (window as WidgetWindow).DograhWidget;
        vi.useRealTimers();
        vi.unstubAllGlobals();
        vi.restoreAllMocks();
        document.head.innerHTML = '';
        document.body.innerHTML = '';
    });

    function voiceFetch(embedMode: string, autoStart = false) {
        return vi.fn(async (input: RequestInfo | URL) => {
            const url = String(input);
            if (url.includes('/api/v1/public/embed/config/')) {
                return {
                    ok: true,
                    status: 200,
                    json: async () => ({
                        workflow_id: 7,
                        settings: {
                            widgetType: 'voice',
                            embedMode,
                            containerId: 'lightmove-inline-container',
                        },
                        texts: VOICE_TEXTS,
                        auto_start: autoStart,
                    }),
                } as Response;
            }
            // Session start never resolves: the test inspects the page
            // while the call is still connecting.
            return new Promise<Response>(() => {});
        });
    }

    it('inline mode shows the notice under the start button', async () => {
        await loadWidget(voiceFetch('inline'));

        const notice = document.getElementById('lightmove-inline-disclosure');
        expect(notice?.textContent).toBe(DISCLOSURE);
        expect(
            document.getElementById('lightmove-inline-start-btn')?.getAttribute('aria-describedby'),
        ).toBe('lightmove-inline-disclosure');
    });

    it('inline auto-start renders the notice before and while it connects', async () => {
        const fetchMock = voiceFetch('inline', true);
        await loadWidget(fetchMock);

        expect(document.getElementById('lightmove-inline-disclosure')?.textContent).toBe(DISCLOSURE);
        expect(countInitCalls(fetchMock)).toBe(0);

        await vi.advanceTimersByTimeAsync(1000);
        await flushMicrotasks();

        expect(countInitCalls(fetchMock)).toBe(1);
        expect(document.getElementById('lightmove-inline-disclosure')?.textContent).toBe(DISCLOSURE);
    });

    it('floating mode captions the call button before the first call', async () => {
        await loadWidget(voiceFetch('floating'));

        const caption = document.getElementById('lightmove-widget-disclosure');
        expect(caption?.textContent).toBe(DISCLOSURE);
        expect(
            document.getElementById('lightmove-widget-cta')?.getAttribute('aria-describedby'),
        ).toBe('lightmove-widget-disclosure');
        // Informs, never blocks: there is no consent dialog to get past.
        expect(document.querySelector('[role="dialog"]')).toBeNull();
    });

    it('headless mode hands the notice to the host page', async () => {
        const widget = await loadWidget(voiceFetch('headless'));

        expect(widget.getDisclosureText()).toBe(DISCLOSURE);
        expect(widget.getState().disclosureText).toBe(DISCLOSURE);
        expect(document.getElementById('lightmove-widget-disclosure')).toBeNull();
    });
});

// Snippets and host pages written before the Fallcha.ai, Failte AI and Dograh
// renames must keep working against the canonical widget.
describe('public embed widget legacy names', () => {
    beforeEach(() => {
        document.head.innerHTML = '';
    });

    afterEach(() => {
        delete (window as WidgetWindow).LightMoveWidget;
        delete (window as WidgetWindow).FallchaWidget;
        delete (window as WidgetWindow).FailteWidget;
        delete (window as WidgetWindow).DograhWidget;
        vi.unstubAllGlobals();
        vi.restoreAllMocks();
        document.head.innerHTML = '';
        document.body.innerHTML = '';
    });

    function configOnlyFetch(settings: Record<string, unknown>) {
        return vi.fn(async (input: RequestInfo | URL) => {
            const url = String(input);
            if (url.includes('/api/v1/public/embed/config/')) {
                return {
                    ok: true,
                    status: 200,
                    json: async () => ({
                        workflow_id: 7,
                        settings,
                        texts: WIDGET_TEXTS,
                        auto_start: false,
                    }),
                } as Response;
            }
            throw new Error(`Unexpected request: ${url}`);
        });
    }

    it('aliases the legacy globals to the canonical widget', async () => {
        document.body.innerHTML = `
            <script src="http://widget.test/embed/lightmove-widget.js?token=emb_TEST"></script>
            <div id="lightmove-inline-container"></div>
        `;
        const widget = await loadWidget(
            configOnlyFetch({ widgetType: 'chat', embedMode: 'inline' }),
        );

        expect((window as WidgetWindow).FallchaWidget).toBe(widget);
        expect((window as WidgetWindow).FailteWidget).toBe(widget);
        expect((window as WidgetWindow).DograhWidget).toBe(widget);
    });

    it.each(['data-fallcha-context', 'data-failte-context', 'data-dograh-context'])(
        'reads visitor context from the legacy %s attribute',
        async (attribute) => {
            document.body.innerHTML = `
                <script src="http://widget.test/embed/lightmove-widget.js?token=emb_TEST"
                    ${attribute}='{"plan":"pro"}'></script>
                <div id="lightmove-inline-container"></div>
            `;
            const widget = await loadWidget(
                configOnlyFetch({ widgetType: 'chat', embedMode: 'inline' }),
            );

            expect(widget.getContext()).toEqual({ plan: 'pro' });
        },
    );

    it.each(['fallcha-inline-container', 'failte-inline-container', 'dograh-inline-container'])(
        'renders into a legacy #%s when the config names no container',
        async (containerId) => {
            document.body.innerHTML = `
                <script src="http://widget.test/embed/lightmove-widget.js?token=emb_TEST"></script>
                <div id="${containerId}"></div>
            `;
            await loadWidget(configOnlyFetch({ widgetType: 'chat', embedMode: 'inline' }));

            expect(
                document.querySelector(`#${containerId} .lightmove-chat-inline-cta`),
            ).not.toBeNull();
        },
    );

    it.each([
        // Saved before the LightMove rename, host page on the current name.
        ['fallcha-inline-container', 'lightmove-inline-container'],
        // Saved after the rename, host page still on an older name.
        ['lightmove-inline-container', 'fallcha-inline-container'],
        ['lightmove-inline-container', 'failte-inline-container'],
    ])(
        'uses #%s as the default container and finds the page\'s #%s',
        async (savedId, pageId) => {
            document.body.innerHTML = `
                <script src="http://widget.test/embed/lightmove-widget.js?token=emb_TEST"></script>
                <div id="${pageId}"></div>
            `;
            await loadWidget(configOnlyFetch({
                widgetType: 'chat',
                embedMode: 'inline',
                containerId: savedId,
            }));

            expect(
                document.querySelector(`#${pageId} .lightmove-chat-inline-cta`),
            ).not.toBeNull();
        },
    );

    it('finds its own tag when loaded under the legacy fallcha-widget.js name', async () => {
        document.body.innerHTML = `
            <script src="http://widget.test/embed/fallcha-widget.js?token=emb_TEST"></script>
            <div id="fallcha-inline-container"></div>
        `;
        await loadWidget(configOnlyFetch({ widgetType: 'chat', embedMode: 'inline' }));

        expect(
            document.querySelector('#fallcha-inline-container .lightmove-chat-inline-cta'),
        ).not.toBeNull();
    });
});

// fallcha-widget.js is now a shim: it must re-inject the canonical widget with
// the original query string and data-* attributes.
describe('fallcha-widget.js shim', () => {
    afterEach(() => {
        delete (window as WidgetWindow).LightMoveWidget;
        document.head.innerHTML = '';
        document.body.innerHTML = '';
    });

    it('injects lightmove-widget.js with the same query and data attributes', () => {
        document.body.innerHTML = `
            <script id="fallcha-widget"
                src="http://widget.test/embed/fallcha-widget.js?token=emb_TEST&environment=prod"
                data-fallcha-context='{"plan":"pro"}'></script>
        `;
        window.eval(fallchaShimSource);

        const injected = document.querySelector<HTMLScriptElement>(
            'script[src*="lightmove-widget.js"]',
        );
        expect(injected?.src).toBe(
            'http://widget.test/embed/lightmove-widget.js?token=emb_TEST&environment=prod',
        );
        expect(injected?.getAttribute('data-fallcha-context')).toBe('{"plan":"pro"}');
    });

    it('does nothing when the canonical widget is already on the page', () => {
        document.body.innerHTML = `
            <script src="http://widget.test/embed/lightmove-widget.js?token=emb_TEST"></script>
            <script src="http://widget.test/embed/fallcha-widget.js?token=emb_TEST"></script>
        `;
        window.eval(fallchaShimSource);

        expect(document.querySelectorAll('script[src*="lightmove-widget.js"]')).toHaveLength(1);
    });
});
