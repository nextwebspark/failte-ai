import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { recordingSrc, SharedRecording } from "./SharedRecording";

const mocks = vi.hoisted(() => ({ info: vi.fn() }));

vi.mock("@/client/sdk.gen", () => ({ sharedRecordingInfoApiV1PublicRecordingTokenInfoGet: mocks.info }));
vi.mock("@/client/client.gen", () => ({ client: { getConfig: () => ({ baseUrl: "https://api.example/" }) } }));
vi.mock("@/components/BrandLogo", () => ({ BrandLogo: () => <span>LightMove</span> }));

const TOKEN = "42.abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQ";

describe("the public listening page", () => {
    beforeEach(() => vi.clearAllMocks());

    it("plays the recording with the business, the date and the expiry, and nothing about the caller", async () => {
        mocks.info.mockResolvedValue({
            data: {
                status: "active",
                business_name: "Bia Bistro",
                called_at: "2026-11-06T16:44:58Z",
                timezone: "Europe/Dublin",
                duration_seconds: 132,
                expires_at: "2026-11-13T16:44:58Z",
            },
        });
        const { container } = render(<SharedRecording token={TOKEN} />);
        expect(await screen.findByRole("heading", { level: 1, name: "A call to Bia Bistro" })).toBeTruthy();
        expect(screen.getByText(/Fri 6 Nov 2026, 16:44 · 2 min 12 s/)).toBeTruthy();
        expect(screen.getByText(/This link expires on Fri 13 Nov 2026, 16:44/)).toBeTruthy();
        const audio = container.querySelector("audio")!;
        expect(audio.getAttribute("src")).toBe(`https://api.example/api/v1/public/recording/${TOKEN}`);
        expect(container.textContent).not.toMatch(/\+353|caller/i);
        expect(container.querySelectorAll("h1")).toHaveLength(1);
    });

    it.each([
        ["expired", "This link has expired"],
        ["revoked", "This link was turned off"],
        ["unavailable", "This recording is no longer available"],
    ])("says plainly when the link is %s, with no player", async (status, title) => {
        mocks.info.mockResolvedValue({ data: { status } });
        const { container } = render(<SharedRecording token={TOKEN} />);
        expect(await screen.findByRole("heading", { level: 1, name: title })).toBeTruthy();
        expect(container.querySelector("audio")).toBeNull();
    });

    it("treats an unknown link kindly", async () => {
        mocks.info.mockResolvedValue({ error: { detail: "This link isn't valid." }, response: { status: 404 } });
        render(<SharedRecording token="nonsense" />);
        expect(await screen.findByRole("heading", { level: 1, name: "This link doesn't work" })).toBeTruthy();
    });

    it("encodes the token into the recording address", () => {
        expect(recordingSrc("https://api.example", "a/b")).toBe("https://api.example/api/v1/public/recording/a%2Fb");
    });
});
