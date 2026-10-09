import { describe, expect, it } from "vitest";

import { BRAND } from "@/config/brand";

import { publicDocsHref } from "./externalDocs";

describe("publicDocsHref", () => {
  it("accepts our own docs host", () => {
    const url = `${BRAND.docsUrl}/voice-agent/introduction`;
    expect(publicDocsHref(url)).toBe(url);
  });

  it("accepts genuine third-party docs", () => {
    const url = "https://learn.microsoft.com/azure/ai-services/speech-service/";
    expect(publicDocsHref(url)).toBe(url);
  });

  it.each(["https://docs.dograh.com/integrations/tts", "https://dograh.com/docs"])(
    "suppresses the upstream vendor's docs (%s)",
    (url) => expect(publicDocsHref(url)).toBeUndefined(),
  );

  it.each([undefined, null, "", "not a url", "javascript:alert(1)"])(
    "rejects %s",
    (url) => expect(publicDocsHref(url)).toBeUndefined(),
  );
});
