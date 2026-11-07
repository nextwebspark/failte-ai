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
import { SettingRow } from "@/components/settings/SettingsLayout";
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
import { Skeleton } from "@/components/ui/skeleton";
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

/**
 * The organization's preferences as setting rows, for a SettingsSection card.
 * `show` picks the rows: General settings shows the defaults, Privacy &
 * compliance the retention period. Each save sends only what was loaded plus
 * the edits, and the period only when it changed, so either screen leaves the
 * other's values alone.
 */
export function OrganizationPreferencesSection({
  show = "all",
}: {
  show?: "all" | "general" | "retention";
} = {}) {
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
    // Rows shaped like the settings below, so nothing jumps when they load.
    return (
      <div aria-busy="true" aria-label="Loading settings" className="divide-y divide-line-soft">
        {Array.from({ length: show === "retention" ? 1 : 2 }, (_, i) => (
          <div key={i} className="flex items-center justify-between gap-4 px-[18px] py-4">
            <div className="space-y-2">
              <Skeleton className="h-3.5 w-36" />
              <Skeleton className="h-3 w-56 max-w-full" />
            </div>
            <Skeleton className="h-9 w-40 max-w-[40%]" />
          </div>
        ))}
      </div>
    );
  }

  const mappingCount = Object.keys(preferences.disposition_mapping ?? {}).length;
  const showGeneral = show !== "retention";
  const showRetention = show !== "general";

  return (
    <form onSubmit={handleSave} className="divide-y divide-line-soft">
      {loadFailed && (
        <p role="alert" className="px-[18px] py-3.5 text-sm text-destructive">
          Preferences could not be loaded. Reload the page before changing
          them.
        </p>
      )}
      {showGeneral && (
        <>
          <SettingRow
            label="Test phone number"
            htmlFor="settings-test-phone-number"
            hint="The number test calls ring when you don't enter one."
          >
            <Input
              id="settings-test-phone-number"
              value={preferences.test_phone_number || ""}
              onChange={(event) =>
                setPreferences({
                  ...preferences,
                  test_phone_number: event.target.value,
                })
              }
              placeholder="+353851234567"
            />
          </SettingRow>
          <SettingRow
            label="Timezone"
            hint="Used for schedules and the times in reports."
          >
            <TimezoneSelect
              instanceId={timezoneSelectId}
              value={timezone}
              onChange={setTimezone}
              styles={timezoneSelectStyles}
            />
          </SettingRow>
        </>
      )}
      {showRetention && (
        <SettingRow
          label="Call data retention (days)"
          htmlFor="settings-call-data-retention"
          hint={
            <span id="settings-call-data-retention-help">
              Recordings, transcripts and call details are permanently deleted
              after this many days ({MIN_RETENTION_DAYS}–{MAX_RETENTION_DAYS}).
              Billing details (duration, cost, status) are kept.
            </span>
          }
        >
          <Input
            id="settings-call-data-retention"
            type="number"
            inputMode="numeric"
            min={MIN_RETENTION_DAYS}
            max={MAX_RETENTION_DAYS}
            step={1}
            value={retentionDays}
            onChange={(event) => setRetentionDays(event.target.value)}
            aria-describedby="settings-call-data-retention-help"
          />
        </SettingRow>
      )}
      {showGeneral && (
        <>
          {/* Most businesses never need these two: they are for workspaces
              that run their own phone system or reporting codes. */}
          <div className="bg-panel-2/60 px-[18px] pb-2 pt-3">
            <h3 className="text-meta font-semibold uppercase tracking-[0.08em] text-ink-3">
              Advanced
            </h3>
            <p className="mt-0.5 text-xs text-ink-3">
              Most businesses can leave these off.
            </p>
          </div>
          <SettingRow
            label="Your own phone system (PBX)"
            htmlFor="settings-external-pbx-integrations"
            hint="Turn on only if your business already runs its own phone system, such as Asterisk, and wants calls passed to it. Your set-up is kept if you turn this off."
            compact
          >
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
          </SettingRow>
          <SettingRow
            label="Your own call outcome codes"
            htmlFor="settings-disposition-mapping"
            hint={`Show call outcomes (like "booked" or "call back") using the codes your business already uses, instead of ${BRAND.name}'s, in reports and the data sent to other systems. Your codes are kept if you turn this off.`}
            compact
          >
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
          </SettingRow>
          {preferences.disposition_mapping_enabled && (
            <div className="flex items-center gap-3 px-[18px] py-3.5">
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
          <DispositionMappingDialog
            open={mappingDialogOpen}
            onOpenChange={setMappingDialogOpen}
            mapping={preferences.disposition_mapping ?? {}}
            onSave={handleDispositionMappingSave}
          />
        </>
      )}
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
      <div className="flex justify-end bg-panel-2/60 px-[18px] py-3">
        <Button type="submit" disabled={saving || loadFailed}>
          <Save className="mr-2 h-4 w-4" />
          {saving ? "Saving..." : "Save"}
        </Button>
      </div>
    </form>
  );
}
