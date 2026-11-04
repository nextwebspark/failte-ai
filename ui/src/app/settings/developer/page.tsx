"use client";

import { Activity, Plug, Webhook } from "lucide-react";

import { CallEventsSection } from "@/components/CallEventsSection";
import { MCPSection } from "@/components/MCPSection";
import { SettingBlock, SettingsSection } from "@/components/settings/SettingsLayout";
import { TelemetrySection } from "@/components/TelemetrySection";
import { BRAND } from "@/config/brand";

/** Developer > MCP & telemetry: what used to sit under Workspace settings. */
export default function DeveloperSettingsPage() {
  return (
    <div className="page-body">
      <div className="flex w-full flex-col gap-[18px]">
        <SettingsSection
          id="mcp"
          icon={Plug}
          tone="brand"
          title="MCP server"
          description={`Let AI agents access your ${BRAND.name} workspace and documentation via the Model Context Protocol.`}
        >
          <SettingBlock>
            <MCPSection />
          </SettingBlock>
        </SettingsSection>

        <SettingsSection
          id="telemetry"
          icon={Activity}
          tone="sky"
          title="Telemetry"
          description="Configure Langfuse tracing for your voice agent calls."
        >
          <SettingBlock>
            <TelemetrySection />
          </SettingBlock>
        </SettingsSection>

        <SettingsSection
          id="call-events"
          icon={Webhook}
          title="Call events"
          description="Configure where your organization sends call diagnostics."
        >
          <SettingBlock>
            <CallEventsSection />
          </SettingBlock>
        </SettingsSection>
      </div>
    </div>
  );
}
