"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { AdminError, AdminLoading } from "@/components/platform-admin/AdminStates";
import { formatWhen } from "@/components/platform-admin/format";
import { Pager } from "@/components/platform-admin/Pager";
import { useAdminData } from "@/components/platform-admin/useAdminData";
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
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Panel, PanelDescription, PanelTitle } from "@/components/ui/panel";
import { StatusPill } from "@/components/ui/status-pill";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useAuth } from "@/lib/auth";
import { type AdminUser, platformAdminApi } from "@/lib/platformAdminApi";
import { impersonateAsSuperadmin } from "@/lib/utils";

const LIMIT = 50;

/** Platform admin > Users: who has an account, their workspaces, platform
 *  admin grants, and impersonation (Stack Auth sign-in only). */
export default function PlatformAdminUsersPage() {
    const searchParams = useSearchParams();
    const initialSearch = searchParams.get("search") ?? "";
    const [search, setSearch] = useState(initialSearch);
    const [query, setQuery] = useState(initialSearch);
    const [adminsOnly, setAdminsOnly] = useState(false);
    const [page, setPage] = useState(1);
    const [pending, setPending] = useState<{ user: AdminUser; grant: boolean } | null>(null);
    const [saving, setSaving] = useState(false);
    const [impersonateTarget, setImpersonateTarget] = useState("");
    const { getAccessToken } = useAuth();
    const { data, error, loading, reload } = useAdminData(
        () => platformAdminApi.users({ search: query, platform_admins_only: adminsOnly, page, limit: LIMIT }),
        [query, adminsOnly, page],
    );

    const changeAdmin = async () => {
        if (!pending) return;
        setSaving(true);
        try {
            await platformAdminApi.setPlatformAdmin(pending.user.id, pending.grant);
            toast.success(pending.grant ? "Platform admin granted" : "Platform admin revoked");
            void reload();
        } catch (err) {
            toast.error(err instanceof Error ? err.message : "Could not change platform admin");
        } finally {
            setSaving(false);
            setPending(null);
        }
    };

    const impersonate = async (target: { userId?: number; email?: string; providerUserId?: string }) => {
        try {
            const accessToken = await getAccessToken();
            await impersonateAsSuperadmin({ accessToken, ...target, redirectPath: "/workflow", openInNewTab: true });
        } catch (err) {
            toast.error(err instanceof Error ? err.message : "Could not impersonate");
        }
    };

    const impersonationAvailable = data?.impersonation_available ?? false;

    return (
        <div className="space-y-4">
            <div className="flex flex-wrap items-end gap-4">
                <form
                    className="flex w-full max-w-md gap-2"
                    onSubmit={(event) => {
                        event.preventDefault();
                        setPage(1);
                        setQuery(search.trim());
                    }}
                >
                    <Input
                        aria-label="Search users"
                        placeholder="Email, name or id"
                        value={search}
                        onChange={(event) => setSearch(event.target.value)}
                    />
                </form>
                <label className="flex items-center gap-2 text-sm">
                    <Checkbox
                        checked={adminsOnly}
                        onCheckedChange={(checked) => {
                            setPage(1);
                            setAdminsOnly(checked === true);
                        }}
                    />
                    Platform admins only
                </label>
            </div>

            {data && !impersonationAvailable ? (
                <p className="rounded-lg border border-line bg-panel-2 px-4 py-2.5 text-xs text-ink-2">
                    {data.impersonation_note}
                </p>
            ) : null}
            <p className="text-xs text-ink-3">Last sign-in is not recorded by the app, so it is not shown.</p>

            {error ? <AdminError message={error} /> : null}
            {!data && loading ? <AdminLoading /> : null}
            {data ? (
                <>
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead>User</TableHead>
                                <TableHead>Workspaces</TableHead>
                                <TableHead>Email verified</TableHead>
                                <TableHead>Signed up</TableHead>
                                <TableHead className="text-right">Actions</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {data.users.map((user) => (
                                <TableRow key={user.id}>
                                    <TableCell>
                                        <div className="font-medium">{user.email || "No email"}</div>
                                        <div className="text-xs text-ink-3">
                                            {user.name ? `${user.name} · ` : ""}#{user.id}
                                        </div>
                                        {user.is_platform_admin ? (
                                            <StatusPill tone="warn" className="mt-1">Platform admin</StatusPill>
                                        ) : null}
                                    </TableCell>
                                    <TableCell className="text-xs">
                                        {user.memberships.length === 0
                                            ? "—"
                                            : user.memberships.map((membership) => (
                                                <div key={membership.organization_id}>
                                                    <Link className="hover:underline" href={`/superadmin/organizations/${membership.organization_id}`}>
                                                        {membership.organization_name || `#${membership.organization_id}`}
                                                    </Link>
                                                    <span className="text-ink-3"> · {membership.role}</span>
                                                </div>
                                            ))}
                                    </TableCell>
                                    <TableCell>{user.email_verified ? "Yes" : "No"}</TableCell>
                                    <TableCell className="whitespace-nowrap text-xs">{formatWhen(user.created_at)}</TableCell>
                                    <TableCell className="text-right">
                                        <div className="flex justify-end gap-2">
                                            <Button
                                                variant="outline"
                                                size="sm"
                                                onClick={() => setPending({ user, grant: !user.is_platform_admin })}
                                            >
                                                {user.is_platform_admin ? "Revoke admin" : "Make admin"}
                                            </Button>
                                            <Button
                                                variant="outline"
                                                size="sm"
                                                disabled={!impersonationAvailable}
                                                title={impersonationAvailable ? undefined : data.impersonation_note ?? undefined}
                                                onClick={() => void impersonate({ userId: user.id })}
                                            >
                                                Impersonate
                                            </Button>
                                        </div>
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                    {data.users.length === 0 ? <p className="text-sm text-ink-3">No user matches.</p> : null}
                    <Pager page={page} limit={LIMIT} total={data.total} onPage={setPage} />
                </>
            ) : null}

            {impersonationAvailable ? (
                <Panel className="space-y-3">
                    <div>
                        <PanelTitle as="h2">Impersonate someone not listed</PanelTitle>
                        <PanelDescription>By email, or by Stack Auth user id for someone who has not signed in to the app yet.</PanelDescription>
                    </div>
                    <form
                        className="flex max-w-lg items-end gap-2"
                        onSubmit={(event) => {
                            event.preventDefault();
                            const value = impersonateTarget.trim();
                            if (!value) return;
                            void impersonate(value.includes("@") ? { email: value } : { providerUserId: value });
                        }}
                    >
                        <div className="w-full space-y-1.5">
                            <Label htmlFor="impersonate-target">Email or Stack user id</Label>
                            <Input id="impersonate-target" value={impersonateTarget} onChange={(event) => setImpersonateTarget(event.target.value)} />
                        </div>
                        <Button type="submit" size="sm" variant="outline">
                            Impersonate
                        </Button>
                    </form>
                </Panel>
            ) : null}

            <AlertDialog open={pending !== null} onOpenChange={(open) => !open && setPending(null)}>
                <AlertDialogContent>
                    <AlertDialogHeader>
                        <AlertDialogTitle>
                            {pending?.grant ? "Make" : "Stop"} {pending?.user.email || `user #${pending?.user.id}`}{" "}
                            {pending?.grant ? "a platform admin?" : "being a platform admin?"}
                        </AlertDialogTitle>
                        <AlertDialogDescription>
                            {pending?.grant
                                ? "Platform admins can see every workspace, change billing and feature switches, and grant this access to others."
                                : "They lose access to this area at once. You can't remove your own access, or the last platform admin."}
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <AlertDialogCancel>Cancel</AlertDialogCancel>
                        <AlertDialogAction disabled={saving} onClick={() => void changeAdmin()}>
                            {pending?.grant ? "Make admin" : "Revoke admin"}
                        </AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </div>
    );
}
