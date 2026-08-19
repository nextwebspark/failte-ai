import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { VoiceSelectorModal } from "./VoiceSelectorModal";

const mocks = vi.hoisted(() => ({
  getVoices: vi.fn(),
  getAccessToken: vi.fn(),
}));

vi.stubGlobal(
  "ResizeObserver",
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
);

vi.mock("@/client/sdk.gen", () => ({
  getVoicesApiV1UserConfigurationsVoicesProviderGet: mocks.getVoices,
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ getAccessToken: mocks.getAccessToken }),
}));

vi.mock("@/lib/apiClient", () => ({
  resolveBrowserBackendUrl: () => "http://backend:8001",
}));

const AOEDE = {
  voice_id: "en-GB-Chirp3-HD-Aoede",
  name: "Aoede",
  description: "British female · Chirp3-HD",
  accent: "gb",
  gender: "female",
  language: "en",
  // Google publishes no sample URLs of its own, so ours is a relative path on
  // our API that needs an origin and a bearer token.
  preview_url:
    "/api/v1/user/configurations/voices/google/preview?voice_id=en-GB-Chirp3-HD-Aoede",
};

const MPS_VOICE = {
  voice_id: "mps-voice",
  name: "Nova",
  accent: "us",
  gender: "female",
  language: "en",
  preview_url: "https://cdn.example.com/nova.mp3",
};

/** Capture what `new Audio(src)` was handed, and let the test end playback. */
function stubAudio() {
  const created: { src: string; instance: Record<string, unknown> }[] = [];
  vi.stubGlobal(
    "Audio",
    class {
      onended: (() => void) | null = null;
      onerror: (() => void) | null = null;
      constructor(public src: string) {
        created.push({ src, instance: this as unknown as Record<string, unknown> });
      }
      play() {
        return Promise.resolve();
      }
      pause() {}
    },
  );
  return created;
}

function renderModal(props: Partial<React.ComponentProps<typeof VoiceSelectorModal>> = {}) {
  return render(
    <VoiceSelectorModal provider="google" value="" onChange={vi.fn()} {...props} />,
  );
}

async function openModal() {
  fireEvent.click(screen.getByRole("button", { name: /select a voice/i }));
  await waitFor(() => expect(screen.queryByText("Aoede")).toBeTruthy());
}

describe("VoiceSelectorModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getVoices.mockResolvedValue({
      data: {
        provider: "google",
        voices: [AOEDE, MPS_VOICE],
        facets: { genders: ["female", "male"], accents: ["gb", "us"], languages: ["en"] },
      },
    });
    mocks.getAccessToken.mockResolvedValue("test-token");
  });

  it("opens on the caller's default filters, not the component's", async () => {
    // Google's catalogue is mostly American; an Irish deployment wants British
    // voices first. The managed pipeline keeps the "us" default.
    renderModal({ defaultAccent: "gb" });
    await openModal();

    const query = mocks.getVoices.mock.calls.at(-1)?.[0].query;
    expect(query).toMatchObject({ gender: "female", accent: "gb", language: "en" });
  });

  it("falls back to American English when no defaults are given", async () => {
    renderModal();
    await openModal();

    expect(mocks.getVoices.mock.calls.at(-1)?.[0].query).toMatchObject({
      accent: "us",
      language: "en",
    });
  });

  it("passes the provider and model through to the catalogue query", async () => {
    renderModal({ model: "chirp_3_hd" });
    await openModal();

    const call = mocks.getVoices.mock.calls.at(-1)?.[0];
    expect(call.path).toEqual({ provider: "google" });
    expect(call.query).toMatchObject({ model: "chirp_3_hd" });
  });

  it("fetches our own preview URLs with a bearer token and plays them as a blob", async () => {
    // An <audio> element can send neither a backend origin nor an Authorization
    // header, so the bytes have to be fetched by hand.
    const created = stubAudio();
    const blob = new Blob(["mp3"], { type: "audio/mpeg" });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, blob: async () => blob });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: vi.fn(() => "blob:preview"),
      revokeObjectURL: vi.fn(),
    });

    renderModal();
    await openModal();
    fireEvent.click(screen.getAllByRole("button", { name: /preview/i })[0]);

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`http://backend:8001${AOEDE.preview_url}`);
    expect(init.headers).toEqual({ Authorization: "Bearer test-token" });

    await waitFor(() => expect(created).toHaveLength(1));
    expect(created[0].src).toBe("blob:preview");
  });

  it("revokes the blob when playback ends", async () => {
    const created = stubAudio();
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, blob: async () => new Blob() }));
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: vi.fn(() => "blob:preview"),
      revokeObjectURL,
    });

    renderModal();
    await openModal();
    fireEvent.click(screen.getAllByRole("button", { name: /preview/i })[0]);
    await waitFor(() => expect(created).toHaveLength(1));

    (created[0].instance.onended as () => void)();

    expect(revokeObjectURL).toHaveBeenCalledWith("blob:preview");
  });

  it("plays an absolute MPS sample URL directly, with no fetch", async () => {
    const created = stubAudio();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    renderModal();
    await openModal();
    fireEvent.click(screen.getAllByRole("button", { name: /preview/i })[1]);

    await waitFor(() => expect(created).toHaveLength(1));
    expect(created[0].src).toBe(MPS_VOICE.preview_url);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
