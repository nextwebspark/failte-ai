import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApiKeyErrorDialog } from "./ApiKeyErrorDialog";

const appConfig = vi.hoisted(() => ({ platformModelsEnabled: true }));
vi.mock("@/context/AppConfigContext", () => ({ useAppConfig: () => ({ config: appConfig }) }));

function renderDialog(errorCode: string | null) {
    render(
        <ApiKeyErrorDialog
            open
            onOpenChange={vi.fn()}
            error="Invalid API key for provider"
            errorCode={errorCode}
            onNavigateToBilling={vi.fn()}
            onNavigateToDevelopers={vi.fn()}
            onNavigateToModelConfig={vi.fn()}
        />,
    );
}

describe("ApiKeyErrorDialog", () => {
    it("shows a generic service message on platform models", () => {
        appConfig.platformModelsEnabled = true;
        renderDialog(null);

        expect(screen.getByText(/couldn't start the voice service/)).toBeTruthy();
        expect(screen.queryByText(/Invalid API key/)).toBeNull();
        expect(screen.queryByRole("button", { name: "Go to Model Configurations" })).toBeNull();
    });

    it("still sends credit problems to billing", () => {
        appConfig.platformModelsEnabled = true;
        renderDialog("insufficient_credits");

        expect(screen.getByRole("button", { name: "Go to Billing" })).toBeTruthy();
    });

    it("keeps the key message when platform models are off", () => {
        appConfig.platformModelsEnabled = false;
        renderDialog(null);

        expect(screen.getByText("Invalid API key for provider")).toBeTruthy();
        expect(screen.getByRole("button", { name: "Go to Model Configurations" })).toBeTruthy();
    });
});
