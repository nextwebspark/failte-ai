"use client";

import { useCallback, useEffect, useState } from "react";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

import { SkillsGate, useCanEditSkills } from "./access";
import { LibraryTab } from "./LibraryTab";
import { MySkillsTab } from "./MySkillsTab";
import { useLibrarySkills, usePlatformAdmin, useWorkspaceSkills } from "./useSkills";

type SkillsTab = "mine" | "library";

function tabFromUrl(): SkillsTab {
    if (typeof window === "undefined") return "mine";
    return new URLSearchParams(window.location.search).get("tab") === "library" ? "library" : "mine";
}

export default function SkillsPage() {
    return (
        <SkillsGate>
            <SkillsScreen />
        </SkillsGate>
    );
}

function SkillsScreen() {
    const canWrite = useCanEditSkills();
    const isPlatformAdmin = usePlatformAdmin();
    const workspace = useWorkspaceSkills(true);
    const library = useLibrarySkills(true);
    const [tab, setTab] = useState<SkillsTab>("mine");

    useEffect(() => setTab(tabFromUrl()), []);

    // Publishing or syncing seeds can flag "Update available" on workspace copies.
    const { refresh: refreshLibrary } = library;
    const { refresh: refreshWorkspace } = workspace;
    const refreshBoth = useCallback(async () => {
        await Promise.all([refreshLibrary(), refreshWorkspace()]);
    }, [refreshLibrary, refreshWorkspace]);

    const changeTab = useCallback((next: string) => {
        const value: SkillsTab = next === "library" ? "library" : "mine";
        setTab(value);
        const url = new URL(window.location.href);
        if (value === "library") url.searchParams.set("tab", "library");
        else url.searchParams.delete("tab");
        window.history.replaceState(window.history.state, "", url.toString());
    }, []);

    return (
        <div className="page-body">
            <div className="w-full max-w-5xl">
                <Tabs value={tab} onValueChange={changeTab} className="gap-6">
                    <TabsList aria-label="Skills">
                        <TabsTrigger value="mine">My skills</TabsTrigger>
                        <TabsTrigger value="library">Library</TabsTrigger>
                    </TabsList>
                    <TabsContent value="mine">
                        <MySkillsTab
                            skills={workspace.items}
                            loading={workspace.loading}
                            error={workspace.error}
                            canWrite={canWrite}
                            onRetry={() => void workspace.refresh()}
                            onChanged={workspace.refresh}
                            onBrowseLibrary={() => changeTab("library")}
                        />
                    </TabsContent>
                    <TabsContent value="library">
                        <LibraryTab
                            library={library.items}
                            loading={library.loading}
                            error={library.error}
                            workspaceSkills={workspace.items}
                            canWrite={canWrite}
                            isPlatformAdmin={isPlatformAdmin === true}
                            onRetry={() => void library.refresh()}
                            onLibraryChanged={refreshBoth}
                            onSkillAdded={workspace.refresh}
                        />
                    </TabsContent>
                </Tabs>
            </div>
        </div>
    );
}
