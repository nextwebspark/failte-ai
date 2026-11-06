"use client";

import { Plus, RotateCcw, Search, Trash2, Wrench } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import {
    createToolApiV1ToolsPost,
    deleteToolApiV1ToolsToolUuidDelete,
    getWorkflowsSummaryApiV1WorkflowSummaryGet,
    listToolsApiV1ToolsGet,
    unarchiveToolApiV1ToolsToolUuidUnarchivePost,
} from "@/client/sdk.gen";
import type { CreateToolRequest, ToolResponse } from "@/client/types.gen";
import { CredentialSelector } from "@/components/http";
import { PageActions } from "@/components/layout/PageActionsSlot";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageHeader } from "@/components/ui/page-header";
import { PageSkeleton } from "@/components/ui/page-skeleton";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";
import { ROW_LINK } from "@/lib/rowLink";

import {
    createMcpDefinition,
    createToolDefinition,
    createTransferAgentDefinition,
    DEFAULT_TRANSFER_AGENT_MESSAGE,
    getCategoryConfig,
    MCP_URL_PATTERN,
    renderToolIcon,
    TOOL_CATEGORIES,
    type ToolCategory,
    type ToolDefinition,
} from "./config";

export default function ToolsPage() {
    const { user, getAccessToken, redirectToLogin, loading } = useAuth();
    const router = useRouter();

    const [tools, setTools] = useState<ToolResponse[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [searchQuery, setSearchQuery] = useState("");
    const [isCreateDialogOpen, setIsCreateDialogOpen] = useState(false);
    const [newToolName, setNewToolName] = useState("");
    const [newToolDescription, setNewToolDescription] = useState("");
    const [newToolCategory, setNewToolCategory] = useState<ToolCategory>("http_api");
    const [isCreating, setIsCreating] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [createError, setCreateError] = useState<string | null>(null);

    // MCP-specific create dialog state
    // A transfer tool is defined by where it sends the caller, so the
    // destination is collected up front rather than defaulted to nothing.
    const [newTransferAgentWorkflowId, setNewTransferAgentWorkflowId] = useState("");
    const [agentOptions, setAgentOptions] = useState<{ id: number; name: string }[]>([]);

    const [mcpUrl, setMcpUrl] = useState("");
    const [mcpCredentialUuid, setMcpCredentialUuid] = useState("");
    const [mcpToolsFilter, setMcpToolsFilter] = useState("");

    // Redirect if not authenticated
    useEffect(() => {
        if (!loading && !user) {
            redirectToLogin();
        }
    }, [loading, user, redirectToLogin]);

    const fetchTools = useCallback(async () => {
        if (loading || !user) return;

        try {
            setIsLoading(true);
            setError(null);
            const accessToken = await getAccessToken();

            const response = await listToolsApiV1ToolsGet({
                headers: {
                    Authorization: `Bearer ${accessToken}`,
                },
                query: {
                    status: "active,archived",
                },
            });

            if (response.data) {
                setTools(response.data);
            } else {
                setError("Couldn't load your tools. Please try again.");
            }
        } catch (err) {
            setError("Couldn't load your tools. Please try again.");
            console.error("Error fetching tools:", err);
        } finally {
            setIsLoading(false);
        }
    }, [loading, user, getAccessToken]);

    const fetchAgentOptions = useCallback(async () => {
        if (loading || !user) return;
        try {
            const response = await getWorkflowsSummaryApiV1WorkflowSummaryGet({});
            // The generated client resolves rather than throws on a 4xx/5xx.
            if (response.error || !response.data) {
                setAgentOptions([]);
                return;
            }
            setAgentOptions(
                response.data.map((workflow) => ({
                    id: workflow.id,
                    name: workflow.name,
                })),
            );
        } catch {
            setAgentOptions([]);
        }
    }, [loading, user]);

    useEffect(() => {
        fetchTools();
    }, [fetchTools]);

    useEffect(() => {
        // Only the agent-transfer dialog needs the agent list; fetch it when
        // that category is actually picked.
        if (isCreateDialogOpen && newToolCategory === "transfer_agent") {
            fetchAgentOptions();
        }
    }, [isCreateDialogOpen, newToolCategory, fetchAgentOptions]);

    const selectedCategoryHref = getCategoryConfig(newToolCategory)?.href;

    const handleCreateTool = async () => {
        if (selectedCategoryHref) {
            // Created on its own page (e.g. integrations), not as an empty tool here.
            setIsCreateDialogOpen(false);
            router.push(selectedCategoryHref);
            return;
        }

        if (!newToolName.trim()) {
            setCreateError("Please enter a name for the tool");
            return;
        }

        if (newToolCategory === "transfer_agent" && !newTransferAgentWorkflowId) {
            setCreateError("Choose the agent to transfer to");
            return;
        }

        if (newToolCategory === "mcp" && !mcpUrl.trim()) {
            setCreateError("Please enter the MCP server URL");
            return;
        }

        if (newToolCategory === "mcp" && !MCP_URL_PATTERN.test(mcpUrl.trim())) {
            setCreateError("MCP server URL must start with http:// or https://");
            return;
        }

        try {
            setIsCreating(true);
            setCreateError(null);
            const accessToken = await getAccessToken();

            const categoryConfig = getCategoryConfig(newToolCategory);

            let definition: ToolDefinition;
            if (newToolCategory === "mcp") {
                definition = createMcpDefinition(mcpUrl, mcpCredentialUuid, mcpToolsFilter);
            } else if (newToolCategory === "transfer_agent") {
                definition = createTransferAgentDefinition({
                    workflow_id: Number(newTransferAgentWorkflowId),
                    message: DEFAULT_TRANSFER_AGENT_MESSAGE,
                });
            } else {
                definition = createToolDefinition(newToolCategory);
            }

            const requestBody: CreateToolRequest = {
                name: newToolName,
                description: newToolDescription || undefined,
                category: newToolCategory,
                icon: categoryConfig?.iconName || "globe",
                icon_color: categoryConfig?.iconColor || "#3B82F6",
                definition,
            };

            const response = await createToolApiV1ToolsPost({
                body: requestBody,
                headers: {
                    Authorization: `Bearer ${accessToken}`,
                },
            });

            if (response.error) {
                setCreateError(detailFromError(response.error, "Failed to create tool"));
                return;
            }

            if (response.data) {
                setIsCreateDialogOpen(false);
                setNewToolName("");
                setNewToolDescription("");
                setNewToolCategory("http_api");
                setNewTransferAgentWorkflowId("");
                setMcpUrl("");
                setMcpCredentialUuid("");
                setMcpToolsFilter("");
                // Navigate to the new tool's detail page
                router.push(`/tools/${response.data.tool_uuid}`);
            }
        } catch (err: unknown) {
            let errorMessage = "Failed to create tool";
            if (err && typeof err === "object") {
                const errObj = err as Record<string, unknown>;
                // Handle API client error response
                if (errObj.error && typeof errObj.error === "object") {
                    const errorData = errObj.error as Record<string, unknown>;
                    if (typeof errorData.detail === "string") {
                        errorMessage = errorData.detail;
                    }
                }
                // Handle standard Error objects
                else if (errObj.message && typeof errObj.message === "string") {
                    errorMessage = errObj.message;
                }
            }
            setCreateError(errorMessage);
            console.error("Error creating tool:", err);
        } finally {
            setIsCreating(false);
        }
    };

    const handleDeleteTool = async (toolUuid: string, e: React.MouseEvent) => {
        e.stopPropagation();
        if (!confirm("Are you sure you want to archive this tool?")) return;

        try {
            setError(null);
            const accessToken = await getAccessToken();

            const result = await deleteToolApiV1ToolsToolUuidDelete({
                path: {
                    tool_uuid: toolUuid,
                },
                headers: {
                    Authorization: `Bearer ${accessToken}`,
                },
            });
            if (result.error) {
                setError(detailFromError(result.error, "Couldn't archive the tool. Please try again."));
                return;
            }

            fetchTools();
        } catch (err) {
            setError("Couldn't archive the tool. Please try again.");
            console.error("Error archiving tool:", err);
        }
    };

    const handleUnarchiveTool = async (toolUuid: string, e: React.MouseEvent) => {
        e.stopPropagation();

        try {
            setError(null);
            const accessToken = await getAccessToken();

            const result = await unarchiveToolApiV1ToolsToolUuidUnarchivePost({
                path: {
                    tool_uuid: toolUuid,
                },
                headers: {
                    Authorization: `Bearer ${accessToken}`,
                },
            });
            if (result.error) {
                setError(detailFromError(result.error, "Couldn't restore the tool. Please try again."));
                return;
            }

            fetchTools();
        } catch (err) {
            setError("Couldn't restore the tool. Please try again.");
            console.error("Error unarchiving tool:", err);
        }
    };

    const filteredTools = tools.filter(
        (tool) =>
            tool.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
            tool.description?.toLowerCase().includes(searchQuery.toLowerCase())
    );

    const activeTools = filteredTools.filter((tool) => tool.status === "active");
    const archivedTools = filteredTools.filter((tool) => tool.status === "archived");

    const getCategoryBadge = (category: string) => {
        switch (category) {
            case "http_api":
                return <Badge variant="default">HTTP API</Badge>;
            case "end_call":
                return <Badge variant="destructive">End Call</Badge>;
            case "calculator":
                return <Badge variant="secondary">Calculator</Badge>;
            case "native":
                return <Badge variant="secondary">Native</Badge>;
            case "integration":
                return <Badge variant="outline">Integration</Badge>;
            case "mcp":
                return <Badge variant="outline">MCP</Badge>;
            default:
                return <Badge variant="outline">{category}</Badge>;
        }
    };

    const getStatusBadge = (status: string) => {
        switch (status) {
            case "active":
                return <Badge variant="success">Active</Badge>;
            case "draft":
                return <Badge variant="secondary">Draft</Badge>;
            case "archived":
                return <Badge variant="destructive">Archived</Badge>;
            default:
                return <Badge variant="outline">{status}</Badge>;
        }
    };

    if (loading || !user) {
        return <PageSkeleton variant="list" />;
    }

    return (
        <div className="page-body">
            <div className="max-w-6xl">
                <PageHeader
                    title="Tools"
                    description="Things your agents can do during a call, like checking a booking system or passing the caller to a person."
                />
                {/* The primary action sits in the app header — see PageActions. */}
                <PageActions>
                    <Button size="toolbar" onClick={() => setIsCreateDialogOpen(true)}>
                        <Plus className="w-4 h-4" />
                        New tool
                    </Button>
                </PageActions>

                    {error && (
                        <div
                            role="alert"
                            className="mb-4 flex flex-wrap items-center justify-between gap-3 p-4 bg-destructive/10 border border-destructive/20 rounded-lg text-destructive"
                        >
                            <span>{error}</span>
                            <Button size="sm" variant="outline" onClick={() => void fetchTools()}>
                                Try again
                            </Button>
                        </div>
                    )}

                    <Card className="mb-6">
                        <CardContent className="p-4 sm:p-6">
                            {/* Search */}
                            <div className="relative mb-4">
                                <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                                <Input
                                    aria-label="Search tools"
                                    placeholder="Search tools…"
                                    value={searchQuery}
                                    onChange={(e) => setSearchQuery(e.target.value)}
                                    className="pl-10"
                                />
                            </div>

                            {isLoading ? (
                                <div className="space-y-4">
                                    {[1, 2, 3].map((i) => (
                                        <div
                                            key={i}
                                            className="flex items-center justify-between p-4 border rounded-lg"
                                        >
                                            <div className="space-y-2">
                                                <Skeleton className="h-4 w-32" />
                                                <Skeleton className="h-3 w-48" />
                                            </div>
                                            <Skeleton className="h-8 w-20" />
                                        </div>
                                    ))}
                                </div>
                            ) : activeTools.length === 0 && archivedTools.length === 0 ? (
                                // A failed load says so above; don't also claim there are none.
                                error && tools.length === 0 ? null : searchQuery ? (
                                    <EmptyState
                                        icon={Search}
                                        title="No tools match your search"
                                        description="Try a different word, or clear the search to see every tool."
                                        action={
                                            <Button variant="outline" onClick={() => setSearchQuery("")}>
                                                Clear search
                                            </Button>
                                        }
                                    />
                                ) : (
                                    <EmptyState
                                        icon={Wrench}
                                        title="No tools yet"
                                        description="Add a tool so your agent can do more on a call, like transferring the caller or checking your booking system."
                                        action={
                                            <Button onClick={() => setIsCreateDialogOpen(true)}>
                                                <Plus aria-hidden />
                                                Create your first tool
                                            </Button>
                                        }
                                    />
                                )
                            ) : (
                                <>
                                    {/* Active Tools */}
                                    {activeTools.length > 0 ? (
                                        <div className="space-y-4">
                                            {activeTools.map((tool) => (
                                                <div
                                                    key={tool.tool_uuid}
                                                    // The name is a real link stretched over the card.
                                                    className="relative flex items-center justify-between gap-3 p-4 border rounded-lg hover:bg-muted/50 focus-within:bg-muted/50 transition-colors"
                                                >
                                                    <div className="flex min-w-0 items-center gap-4">
                                                        <div className="grid size-10 shrink-0 place-items-center rounded-lg bg-brand-dim text-brand" aria-hidden>
                                                            {renderToolIcon(tool.category, "size-5 text-brand")}
                                                        </div>
                                                        <div className="min-w-0">
                                                            <div className="flex flex-wrap items-center gap-2">
                                                                <Link href={`/tools/${tool.tool_uuid}`} className={`font-medium ${ROW_LINK}`}>
                                                                    {tool.name}
                                                                </Link>
                                                                {getCategoryBadge(tool.category)}
                                                            </div>
                                                            {tool.description && (
                                                                <p className="text-sm text-muted-foreground mt-1">
                                                                    {tool.description}
                                                                </p>
                                                            )}
                                                        </div>
                                                    </div>
                                                    <Button
                                                        variant="ghost"
                                                        size="sm"
                                                        onClick={(e) =>
                                                            handleDeleteTool(tool.tool_uuid, e)
                                                        }
                                                        className="relative z-10 text-destructive hover:text-destructive/90"
                                                        aria-label={`Archive ${tool.name}`}
                                                        title="Archive tool"
                                                    >
                                                        <Trash2 className="w-4 h-4" aria-hidden />
                                                    </Button>
                                                </div>
                                            ))}
                                        </div>
                                    ) : !searchQuery ? (
                                        <EmptyState
                                            icon={Wrench}
                                            title="No tools in use"
                                            description="Every tool here is archived. Restore one below, or create a new one."
                                            action={
                                                <Button onClick={() => setIsCreateDialogOpen(true)}>
                                                    <Plus aria-hidden />
                                                    Create a tool
                                                </Button>
                                            }
                                        />
                                    ) : null}

                                    {/* Archived Tools */}
                                    {archivedTools.length > 0 && (
                                        <div className="mt-8">
                                            <h2 className="mb-3 text-[15px] font-semibold text-ink-2">
                                                Archived tools
                                            </h2>
                                            <div className="space-y-4">
                                                {archivedTools.map((tool) => (
                                                    <div
                                                        key={tool.tool_uuid}
                                                        className="relative flex items-center justify-between gap-3 p-4 border rounded-lg hover:bg-muted/50 focus-within:bg-muted/50 transition-colors opacity-60"
                                                    >
                                                        <div className="flex min-w-0 items-center gap-4">
                                                            <div className="grid size-10 shrink-0 place-items-center rounded-lg bg-brand-dim text-brand" aria-hidden>
                                                            {renderToolIcon(tool.category, "size-5 text-brand")}
                                                        </div>
                                                            <div className="min-w-0">
                                                                <div className="flex flex-wrap items-center gap-2">
                                                                    <Link href={`/tools/${tool.tool_uuid}`} className={`font-medium ${ROW_LINK}`}>
                                                                        {tool.name}
                                                                    </Link>
                                                                    {getCategoryBadge(tool.category)}
                                                                    {getStatusBadge(tool.status)}
                                                                </div>
                                                                {tool.description && (
                                                                    <p className="text-sm text-muted-foreground mt-1">
                                                                        {tool.description}
                                                                    </p>
                                                                )}
                                                            </div>
                                                        </div>
                                                        <Button
                                                            variant="ghost"
                                                            size="sm"
                                                            onClick={(e) =>
                                                                handleUnarchiveTool(tool.tool_uuid, e)
                                                            }
                                                            className="relative z-10 text-primary hover:text-primary/90"
                                                            title="Restore tool"
                                                            aria-label={`Restore ${tool.name}`}
                                                        >
                                                            <RotateCcw className="w-4 h-4" aria-hidden />
                                                        </Button>
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                    )}
                                </>
                            )}
                        </CardContent>
                    </Card>
                </div>

            {/* Create Tool Dialog */}
            <Dialog open={isCreateDialogOpen} onOpenChange={(open) => {
                setIsCreateDialogOpen(open);
                if (open) {
                    setCreateError(null);
                } else {
                    // Reset MCP fields when dialog is closed without creating
                    setMcpUrl("");
                    setMcpCredentialUuid("");
                    setMcpToolsFilter("");
                }
            }}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>Create New Tool</DialogTitle>
                        <DialogDescription>
                            Create a new tool that can be used by your agents.
                        </DialogDescription>
                    </DialogHeader>
                    <div className="grid gap-4 py-4">
                        <div className="grid gap-2">
                            <Label>Tool Type</Label>
                            <Select
                                value={newToolCategory}
                                onValueChange={(v) => {
                                    const category = v as ToolCategory;
                                    setNewToolCategory(category);
                                    setCreateError(null);
                                    const categoryConfig = getCategoryConfig(category);
                                    if (categoryConfig?.autoFill) {
                                        setNewToolName(categoryConfig.autoFill.name);
                                        setNewToolDescription(categoryConfig.autoFill.description);
                                    }
                                }}
                            >
                                <SelectTrigger className="w-full">
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    {TOOL_CATEGORIES.map((category) => (
                                        <SelectItem
                                            key={category.value}
                                            value={category.value}
                                            disabled={category.disabled}
                                        >
                                            {category.label}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                            <p className="text-xs text-muted-foreground">
                                {getCategoryConfig(newToolCategory)?.description}
                            </p>
                        </div>
                        {!selectedCategoryHref && (
                            <>
                                <div className="grid gap-2">
                                    <Label htmlFor="name">Tool Name</Label>
                                    <Label className="text-xs text-muted-foreground">
                                        Use a descriptive name, like &quot;Get Weather using API&quot; for a tool that fetches weather
                                    </Label>
                                    <Input
                                        id="name"
                                        value={newToolName}
                                        onChange={(e) => setNewToolName(e.target.value)}
                                        placeholder="e.g., Book Appointment, Check Inventory"
                                    />
                                </div>
                                <div className="grid gap-2">
                                    <Label htmlFor="description">Description (Optional)</Label>
                                    <Label className="text-xs text-muted-foreground">
                                        Provide a description which makes it easy for LLM to understand what this tool does
                                    </Label>
                                    <Input
                                        id="description"
                                        value={newToolDescription}
                                        onChange={(e) => setNewToolDescription(e.target.value)}
                                        placeholder="What does this tool do?"
                                    />
                                </div>
                            </>
                        )}

                        {newToolCategory === "transfer_agent" && (
                            <div className="grid gap-2">
                                <Label htmlFor="transfer-agent-workflow">
                                    Transfer to agent
                                </Label>
                                <Label className="text-xs text-muted-foreground">
                                    The agent this tool hands the caller to. For more
                                    than one destination, create a tool per agent.
                                </Label>
                                <Select
                                    value={newTransferAgentWorkflowId}
                                    onValueChange={setNewTransferAgentWorkflowId}
                                >
                                    <SelectTrigger id="transfer-agent-workflow">
                                        <SelectValue placeholder="Select an agent" />
                                    </SelectTrigger>
                                    <SelectContent>
                                        {agentOptions.map((agent) => (
                                            <SelectItem
                                                key={agent.id}
                                                value={String(agent.id)}
                                            >
                                                {agent.name}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>
                        )}

                        {newToolCategory === "mcp" && (
                            <>
                                <div className="grid gap-2">
                                    <Label htmlFor="mcp-url">MCP Server URL</Label>
                                    <Input
                                        id="mcp-url"
                                        value={mcpUrl}
                                        onChange={(e) => setMcpUrl(e.target.value)}
                                        placeholder="https://your-mcp-server.example.com/mcp"
                                    />
                                </div>
                                <div className="grid gap-2">
                                    <Label>Transport</Label>
                                    <Input
                                        value="Streamable HTTP"
                                        disabled
                                        readOnly
                                    />
                                </div>
                                <CredentialSelector
                                    value={mcpCredentialUuid}
                                    onChange={setMcpCredentialUuid}
                                    label="Credential (Optional)"
                                    description="Select a credential for authenticating with the MCP server, or leave empty for no auth."
                                />
                                <div className="grid gap-2">
                                    <Label htmlFor="mcp-tools-filter">Tools Filter (Optional)</Label>
                                    <Input
                                        id="mcp-tools-filter"
                                        value={mcpToolsFilter}
                                        onChange={(e) => setMcpToolsFilter(e.target.value)}
                                        placeholder="e.g., tool_one, tool_two"
                                    />
                                    <p className="text-xs text-muted-foreground">
                                        Comma-separated list of tool names to allow. Leave empty to expose all tools from the server.
                                    </p>
                                </div>
                            </>
                        )}
                    </div>
                    {createError && (
                        <div className="p-3 bg-destructive/10 border border-destructive/20 rounded-lg text-destructive text-sm">
                            {createError}
                        </div>
                    )}
                    <DialogFooter>
                        <Button
                            variant="outline"
                            onClick={() => setIsCreateDialogOpen(false)}
                        >
                            Cancel
                        </Button>
                        <Button onClick={handleCreateTool} disabled={isCreating}>
                            {selectedCategoryHref
                                ? "Open Integrations"
                                : isCreating ? "Creating..." : "Create Tool"}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}
