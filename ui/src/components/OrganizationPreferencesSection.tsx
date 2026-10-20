"use client";

import { Save, SlidersHorizontal } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import TimezoneSelect, { type ITimezoneOption } from "react-timezone-select";
import { toast } from "sonner";

import {
  getPreferencesApiV1OrganizationsPreferencesGet,
  savePreferencesApiV1OrganizationsPreferencesPut,
} from "@/client/sdk.gen";
import type { OrganizationPreferences } from "@/client/types.gen";
import { DispositionMappingDialog } from "@/components/DispositionMappingDialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { BRAND } from "@/config/brand";
import { useUserConfig } from "@/context/UserConfigContext";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";

// Mirrors api/schemas/organization_preferences.py.
const DEFAULT_RETENTION_DAYS = 90;
const MIN_RETENTION_DAYS = 1;
const MAX_RETENTION_DAYS = 365;

function parseRetentionDays(value: string): number | null {
  const days = Number(value);
  return Number.isInteger(days) &&
    days >= MIN_RETENTION_DAYS &&
    days <= MAX_RETENTION_DAYS
    ? days
    : null;
}

const emptyPreferences: OrganizationPreferences = {
  test_phone_number: "",
  timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
  external_pbx_integrations_enabled: false,
  call_data_retention_days: DEFAULT_RETENTION_DAYS,
  disposition_mapping_enabled: false,
  disposition_mapping: {},
};

/** Normalize a server response into the shape this form edits. */
function toFormPreferences(
  preferences: OrganizationPreferences,
): OrganizationPreferences {
  return {
    test_phone_number: preferences.test_phone_number || "",
    timezone: preferences.timezone || emptyPreferences.timezone,
    external_pbx_integrations_enabled:
      preferences.external_pbx_integrations_enabled ?? false,
    call_data_retention_days:
      preferences.call_data_retention_days ?? DEFAULT_RETENTION_DAYS,
    disposition_mapping_enabled: preferences.disposition_mapping_enabled ?? false,
    disposition_mapping: preferences.disposition_mapping ?? {},
  };
}

const timezoneSelectStyles = {
  control: (base: Record<string, unknown>, state: { isFocused: boolean }) => ({
    ...base,
    minHeight: "36px",
    fontSize: "14px",
    backgroundColor: "var(--background)",
    borderColor: state.isFocused ? "var(--ring)" : "var(--border)",
    boxShadow: state.isFocused
      ? "0 0 0 2px color-mix(in srgb, var(--ring) 20%, transparent)"
      : "none",
    "&:hover": { borderColor: "var(--border)" },
  }),
  menu: (base: Record<string, unknown>) => ({
    ...base,
    zIndex: 9999,
    backgroundColor: "var(--popover)",
    border: "1px solid var(--border)",
    boxShadow:
      "0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)",
  }),
  menuList: (base: Record<string, unknown>) => ({
    ...base,
    backgroundColor: "var(--popover)",
    padding: 0,
  }),
  option: (
    base: Record<string, unknown>,
    state: { isFocused: boolean; isSelected: boolean },
  ) => ({
    ...base,
    backgroundColor: state.isSelected
      ? "var(--accent)"
      : state.isFocused
        ? "var(--accent)"
        : "var(--popover)",
    color: "var(--foreground)",
    cursor: "pointer",
    "&:active": { backgroundColor: "var(--accent)" },
  }),
  singleValue: (base: Record<string, unknown>) => ({
    ...base,
    color: "var(--foreground)",
  }),
  input: (base: Record<string, unknown>) => ({
    ...base,
    color: "var(--foreground)",
  }),
  placeholder: (base: Record<string, unknown>) => ({
    ...base,
    color: "var(--muted-foreground)",
  }),
  indicatorSeparator: (base: Record<string, unknown>) => ({
    ...base,
    backgroundColor: "var(--border)",
  }),
  dropdownIndicator: (base: Record<string, unknown>) => ({
    ...base,
    color: "var(--muted-foreground)",
    "&:hover": { color: "var(--foreground)" },
  }),
};

function getTimezoneValue(tz: ITimezoneOption | string): string {
  return typeof tz === "string" ? tz : tz.value;
}

export function OrganizationPreferencesSection() {
  const { user, loading: authLoading } = useAuth();
  const { refreshConfig } = useUserConfig();
  const timezoneSelectId = useId();
  const hasFetched = useRef(false);

  const [preferences, setPreferences] =
    useState<OrganizationPreferences>(emptyPreferences);
  const [timezone, setTimezone] = useState<ITimezoneOption | string>(
    emptyPreferences.timezone || "UTC",
  );
  const [retentionDays, setRetentionDays] = useState(
    String(DEFAULT_RETENTION_DAYS),
  );
  // The period stored on the server; null until it has been loaded.
  const [savedRetentionDays, setSavedRetentionDays] = useState<number | null>(
    null,
  );
  // Days awaiting confirmation that shortening the period deletes call data.
  const [pendingShorterRetention, setPendingShorterRetention] = useState<
    number | null
  >(null);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [mappingDialogOpen, setMappingDialogOpen] = useState(false);

  useEffect(() => {
    if (authLoading || !user || hasFetched.current) {
      return;
    }
    hasFetched.current = true;
    void fetchPreferences();
  }, [authLoading, user]);

  async function fetchPreferences() {
    setLoading(true);
    try {
      const result =
        await getPreferencesApiV1OrganizationsPreferencesGet();

      if (result.error || !result.data) {
        setLoadFailed(true);
        toast.error(
          detailFromError(
            result.error,
            "Failed to load organization preferences",
          ),
        );
        return;
      }

      const formPreferences = toFormPreferences(result.data);
      setPreferences(formPreferences);
      setRetentionDays(String(formPreferences.call_data_retention_days));
      setSavedRetentionDays(formPreferences.call_data_retention_days ?? null);
      setTimezone(result.data.timezone || emptyPreferences.timezone || "UTC");
    } catch {
      setLoadFailed(true);
      toast.error("Failed to load organization preferences");
    } finally {
      setLoading(false);
    }
  }

  /**
   * Save the preferences. The retention period is only sent when given (the
   * main form changed it), so another save never persists an unsaved edit.
   */
  async function persistPreferences(
    nextPreferences: OrganizationPreferences,
    successMessage: string,
    callDataRetentionDays?: number,
  ): Promise<boolean> {
    if (loadFailed) {
      // Saving now would overwrite the stored values with the form defaults.
      toast.error("Preferences could not be loaded, so they cannot be saved");
      return false;
    }
    setSaving(true);
    try {
      const result =
        await savePreferencesApiV1OrganizationsPreferencesPut(
          {
            body: {
              test_phone_number: nextPreferences.test_phone_number || null,
              timezone: getTimezoneValue(timezone),
              external_pbx_integrations_enabled:
                nextPreferences.external_pbx_integrations_enabled ?? false,
              ...(callDataRetentionDays !== undefined && {
                call_data_retention_days: callDataRetentionDays,
              }),
              disposition_mapping_enabled:
                nextPreferences.disposition_mapping_enabled ?? false,
              // Sent even when the toggle is off: turning the mapping off
              // should stop it being applied, not discard the entries someone
              // spent time configuring.
              disposition_mapping: nextPreferences.disposition_mapping ?? {},
            },
          },
        );

      if (result.error) {
        toast.error(detailFromError(result.error, "Failed to save preferences"));
        return false;
      }
      if (!result.data) {
        toast.error("Failed to save preferences");
        return false;
      }

      const savedPreferences = toFormPreferences(result.data);
      setPreferences(savedPreferences);
      setSavedRetentionDays(savedPreferences.call_data_retention_days ?? null);
      if (callDataRetentionDays !== undefined) {
        setRetentionDays(String(savedPreferences.call_data_retention_days));
      }
      setTimezone(result.data.timezone || emptyPreferences.timezone || "UTC");
      await refreshConfig();
      toast.success(successMessage);
      return true;
    } catch {
      toast.error("Failed to save preferences");
      return false;
    } finally {
      setSaving(false);
    }
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    const days = parseRetentionDays(retentionDays);
    if (days === null) {
      toast.error(
        `Call data retention must be a whole number of days from ${MIN_RETENTION_DAYS} to ${MAX_RETENTION_DAYS}`,
      );
      return;
    }
    if (savedRetentionDays !== null && days < savedRetentionDays) {
      setPendingShorterRetention(days);
      return;
    }
    await persistPreferences(
      preferences,
      "Preferences saved",
      days !== savedRetentionDays ? days : undefined,
    );
  }

  async function handleConfirmShorterRetention() {
    const days = pendingShorterRetention;
    setPendingShorterRetention(null);
    if (days !== null) {
      await persistPreferences(preferences, "Preferences saved", days);
    }
  }

  async function handleDispositionMappingSave(
    dispositionMapping: Record<string, string>,
  ): Promise<boolean> {
    return persistPreferences(
      { ...preferences, disposition_mapping: dispositionMapping },
      "Disposition mapping saved",
    );
  }

  if (loading) {
    return <p className="text-sm text-muted-foreground">Loading...</p>;
  }

  const mappingCount = Object.keys(preferences.disposition_mapping ?? {}).length;

  return (
    <form onSubmit={handleSave} className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Set organization-wide defaults used by testing and scheduling flows.
      </p>
      {loadFailed && (
        <p role="alert" className="text-sm text-destructive">
          Preferences could not be loaded. Reload the page before changing
          them.
        </p>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="settings-test-phone-number">Test Phone Number</Label>
          <Input
            id="settings-test-phone-number"
            value={preferences.test_phone_number || ""}
            onChange={(event) =>
              setPreferences({
                ...preferences,
                test_phone_number: event.target.value,
              })
            }
            placeholder="+15551234567"
          />
        </div>
        <div className="space-y-2">
          <Label>Timezone</Label>
          <TimezoneSelect
            instanceId={timezoneSelectId}
            value={timezone}
            onChange={setTimezone}
            styles={timezoneSelectStyles}
          />
        </div>
      </div>
      <div className="space-y-2">
        <Label htmlFor="settings-call-data-retention">
          Call data retention (days)
        </Label>
        <Input
          id="settings-call-data-retention"
          type="number"
          inputMode="numeric"
          min={MIN_RETENTION_DAYS}
          max={MAX_RETENTION_DAYS}
          step={1}
          className="sm:max-w-[12rem]"
          value={retentionDays}
          onChange={(event) => setRetentionDays(event.target.value)}
          aria-describedby="settings-call-data-retention-help"
        />
        <p
          id="settings-call-data-retention-help"
          className="text-xs text-muted-foreground"
        >
          Recordings, transcripts and call details are permanently deleted
          after this many days ({MIN_RETENTION_DAYS}–{MAX_RETENTION_DAYS}).
        </p>
      </div>
      <div className="flex items-start justify-between gap-4 rounded-lg border p-4">
        <div className="space-y-1">
          <Label htmlFor="settings-external-pbx-integrations">
            External PBX integrations
          </Label>
          <p className="text-xs text-muted-foreground">
            Show and enable advanced external-PBX configuration for Asterisk,
            transfer tools, and workflows. Existing configuration is preserved
            when this is disabled.
          </p>
        </div>
        <Switch
          id="settings-external-pbx-integrations"
          checked={preferences.external_pbx_integrations_enabled ?? false}
          onCheckedChange={(checked) =>
            setPreferences({
              ...preferences,
              external_pbx_integrations_enabled: checked,
            })
          }
        />
      </div>
      <div className="space-y-3 rounded-lg border p-4">
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-1">
            <Label htmlFor="settings-disposition-mapping">
              Disposition mapping
            </Label>
            <p className="text-xs text-muted-foreground">
              Report call outcomes using your own disposition codes instead of{" "}
              {BRAND.name}&apos;s. Applies to webhooks, run filters, reports, and
              external PBX write-backs. Configuration is preserved when this is
              disabled.
            </p>
          </div>
          <Switch
            id="settings-disposition-mapping"
            checked={preferences.disposition_mapping_enabled ?? false}
            onCheckedChange={(checked) =>
              setPreferences({
                ...preferences,
                disposition_mapping_enabled: checked,
              })
            }
          />
        </div>
        {preferences.disposition_mapping_enabled && (
          <div className="flex items-center gap-3">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={loadFailed}
              onClick={() => setMappingDialogOpen(true)}
            >
              <SlidersHorizontal className="mr-2 h-3.5 w-3.5" />
              Configure mapping
            </Button>
            <span className="text-xs text-muted-foreground">
              {mappingCount === 0
                ? "No overrides yet"
                : `${mappingCount} disposition${mappingCount === 1 ? "" : "s"} mapped`}
            </span>
          </div>
        )}
      </div>
      <DispositionMappingDialog
        open={mappingDialogOpen}
        onOpenChange={setMappingDialogOpen}
        mapping={preferences.disposition_mapping ?? {}}
        onSave={handleDispositionMappingSave}
      />
      <AlertDialog
        open={pendingShorterRetention !== null}
        onOpenChange={(open) => {
          if (!open) setPendingShorterRetention(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Shorten call data retention?</AlertDialogTitle>
            <AlertDialogDescription>
              Recordings, transcripts and call details older than{" "}
              {pendingShorterRetention} days will be permanently deleted at the
              next daily cleanup run. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={() => void handleConfirmShorterRetention()}>
              Shorten and save
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <Button type="submit" disabled={saving || loadFailed}>
        <Save className="mr-2 h-4 w-4" />
        {saving ? "Saving..." : "Save"}
      </Button>
    </form>
  );
}
