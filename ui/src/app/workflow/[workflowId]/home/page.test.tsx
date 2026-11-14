import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AgentHomePage from "./page";

const mocks = vi.hoisted(() => ({ query: "", replace: vi.fn() }));

vi.mock("next/navigation", () => ({
    useParams: () => ({ workflowId: "14" }),
    useSearchParams: () => new URLSearchParams(mocks.query),
    useRouter: () => ({ replace: mocks.replace }),
}));

describe("an agent's old dashboard address", () => {
    beforeEach(() => {
        mocks.replace.mockReset();
        mocks.query = "";
    });

    it("lands on Home showing that agent", () => {
        render(<AgentHomePage />);
        expect(mocks.replace).toHaveBeenCalledWith("/overview?agent=14");
    });

    it("keeps the test panel opening on arrival", () => {
        mocks.query = "onboarding=web_call";
        render(<AgentHomePage />);
        expect(mocks.replace).toHaveBeenCalledWith("/overview?agent=14&onboarding=web_call");
    });
});
