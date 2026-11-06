'use client';

import { FileText, Pencil, RefreshCw, Search, Trash2, TriangleAlert, Upload } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';

import {
  deleteDocumentApiV1KnowledgeBaseDocumentsDocumentUuidDelete,
  listDocumentsApiV1KnowledgeBaseDocumentsGet,
} from '@/client/sdk.gen';
import type { DocumentResponseSchema } from '@/client/types.gen';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { useAppConfig } from '@/context/AppConfigContext';
import { useOrganizationTimezone } from '@/hooks/useOrganizationTimezone';
import { formatDateTime } from '@/lib/dateTime';
import logger from '@/lib/logger';

import DocumentEditor, { isEditableDocument } from './DocumentEditor';

interface DocumentListProps {
  refreshTrigger: number;
  /** Offered from the empty state when uploads are available. */
  onUploadClick?: () => void;
}

export default function DocumentList({ refreshTrigger, onUploadClick }: DocumentListProps) {
  const organizationTimezone = useOrganizationTimezone();
  const [documents, setDocuments] = useState<DocumentResponseSchema[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [editingDoc, setEditingDoc] = useState<DocumentResponseSchema | null>(null);
  // Saving an edit re-processes the document; when the server can't process
  // documents, editing is off like uploads.
  const { config } = useAppConfig();
  const editingAvailable = Boolean(config?.documentProcessingEnabled);

  const fetchDocuments = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);

      const response = await listDocumentsApiV1KnowledgeBaseDocumentsGet({
        query: {
          limit: 100,
          offset: 0,
        },
      });

      if (response.error || !response.data) {
        throw new Error('Failed to fetch documents');
      }

      setDocuments(response.data.documents);
    } catch (err) {
      // The details go to the log; the owner gets a plain sentence.
      setError("Your documents couldn't be loaded.");
      logger.error('Error fetching documents:', err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Fetch documents on mount and when refreshTrigger changes
  useEffect(() => {
    fetchDocuments();
  }, [fetchDocuments, refreshTrigger]);

  // Poll for documents that are processing
  useEffect(() => {
    const processingDocs = documents.filter(
      (doc) => doc.processing_status === 'processing' || doc.processing_status === 'pending'
    );

    if (processingDocs.length === 0) return;

    const pollInterval = setInterval(() => {
      logger.info(`Polling for ${processingDocs.length} processing documents...`);
      fetchDocuments();
    }, 5000); // Poll every 5 seconds

    return () => clearInterval(pollInterval);
  }, [documents, fetchDocuments]);

  const handleDelete = async (documentUuid: string, filename: string) => {
    if (!confirm(`Are you sure you want to delete "${filename}"?`)) return;

    try {
      const response = await deleteDocumentApiV1KnowledgeBaseDocumentsDocumentUuidDelete({
        path: {
          document_uuid: documentUuid,
        },
      });

      if (response.error) {
        throw new Error('Failed to delete document');
      }

      toast.success(`Deleted "${filename}"`);
      fetchDocuments();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to delete document');
      logger.error('Error deleting document:', err);
    }
  };

  const isBusy = (doc: DocumentResponseSchema) =>
    doc.processing_status === 'processing' || doc.processing_status === 'pending';

  const canEdit = (doc: DocumentResponseSchema) =>
    editingAvailable && isEditableDocument(doc.filename);

  const canOpen = (doc: DocumentResponseSchema) => canEdit(doc) && !isBusy(doc);

  const getStatusBadge = (doc: DocumentResponseSchema) => {
    // A previously indexed document keeps serving agents while it is re-indexed
    // after an edit, and after that re-index fails.
    if (doc.has_live_content && isBusy(doc)) {
      return (
        <Badge variant="secondary" className="animate-pulse">
          Updating
        </Badge>
      );
    }
    if (doc.has_live_content && doc.processing_status === 'failed') {
      return <Badge variant="destructive">Update failed</Badge>;
    }
    switch (doc.processing_status) {
      case 'completed':
        return <Badge variant="success">Completed</Badge>;
      case 'processing':
        return (
          <Badge variant="secondary" className="animate-pulse">
            Processing
          </Badge>
        );
      case 'pending':
        return <Badge variant="outline">Pending</Badge>;
      case 'failed':
        return <Badge variant="destructive">Failed</Badge>;
      default:
        return <Badge variant="outline">{doc.processing_status}</Badge>;
    }
  };

  const formatFileSize = (bytes: number): string => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
  };

  const filteredDocuments = documents.filter((doc) =>
    doc.filename.toLowerCase().includes(searchQuery.toLowerCase())
  );

  if (isLoading && documents.length === 0) {
    return (
      <div className="space-y-4">
        {[1, 2, 3].map((i) => (
          <div key={i} className="flex items-center justify-between p-4 border rounded-lg">
            <div className="space-y-2 flex-1">
              <Skeleton className="h-4 w-48" />
              <Skeleton className="h-3 w-64" />
            </div>
            <Skeleton className="h-8 w-24" />
          </div>
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <EmptyState
        tone="danger"
        icon={TriangleAlert}
        title={error}
        description="Check your connection, then try again."
        action={
          <Button variant="outline" onClick={() => void fetchDocuments()}>
            <RefreshCw aria-hidden />
            Try again
          </Button>
        }
      />
    );
  }

  return (
    <div className="space-y-4">
      {/* Search and Refresh */}
      <div className="flex items-center gap-4">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            aria-label="Search documents"
            placeholder="Search documents…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-10"
          />
        </div>
        <Button
          aria-label="Reload documents"
          variant="outline"
          size="icon"
          onClick={fetchDocuments}
          disabled={isLoading}
        >
          <RefreshCw className={`h-4 w-4 ${isLoading ? 'animate-spin' : ''}`} />
        </Button>
      </div>

      {/* Document List */}
      {filteredDocuments.length === 0 ? (
        searchQuery ? (
          <EmptyState
            icon={Search}
            title="No documents match your search"
            description="Try a different word, or clear the search to see every document."
            action={
              <Button variant="outline" onClick={() => setSearchQuery('')}>
                Clear search
              </Button>
            }
          />
        ) : (
          <EmptyState
            icon={FileText}
            title="No documents yet"
            description="Upload your menu, price list or FAQs and your agents can use them to answer callers."
            action={
              onUploadClick && (
                <Button onClick={onUploadClick}>
                  <Upload aria-hidden />
                  Upload a document
                </Button>
              )
            }
          />
        )
      ) : (
        <div className="space-y-3">
          {filteredDocuments.map((doc) => (
            <div
              key={doc.document_uuid}
              role={canOpen(doc) ? 'button' : undefined}
              tabIndex={canOpen(doc) ? 0 : undefined}
              aria-label={canOpen(doc) ? `Edit ${doc.filename}` : undefined}
              className={`flex items-center justify-between p-4 border rounded-lg hover:bg-muted/50 transition-colors ${
                canOpen(doc)
                  ? 'cursor-pointer focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring'
                  : ''
              }`}
              onClick={canOpen(doc) ? () => setEditingDoc(doc) : undefined}
              onKeyDown={(event) => {
                if (!canOpen(doc) || event.target !== event.currentTarget) return;
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  setEditingDoc(doc);
                }
              }}
            >
              <div className="flex items-center gap-4 flex-1">
                <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center">
                  <FileText className="w-5 h-5 text-primary" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-medium truncate">{doc.filename}</span>
                    {getStatusBadge(doc)}
                    {doc.retrieval_mode === 'full_document' ? (
                      <Badge variant="outline" className="text-xs">Full Document</Badge>
                    ) : (
                      <Badge variant="outline" className="text-xs">Chunked</Badge>
                    )}
                  </div>
                  <div className="flex items-center gap-4 text-sm text-muted-foreground">
                    <span>{formatFileSize(doc.file_size_bytes)}</span>
                    {doc.processing_status === 'completed' && doc.retrieval_mode !== 'full_document' && (
                      <span>{doc.total_chunks} chunks</span>
                    )}
                    <span>{formatDateTime(doc.created_at, organizationTimezone)}</span>
                  </div>
                  {doc.needs_reindex && (
                    <p className="text-xs text-amber mt-1">
                      Re-index needed: this document was indexed with a different
                      embedding model than the one now configured, so agents can&apos;t
                      find it. Delete it and upload it again.
                    </p>
                  )}
                  {doc.has_live_content && isBusy(doc) && (
                    <p className="text-xs text-muted-foreground mt-1">
                      Agents keep using the previous version until the update finishes.
                    </p>
                  )}
                  {doc.processing_error && (
                    <p className="text-xs text-destructive mt-1">
                      Error: {doc.processing_error}
                      {doc.has_live_content && ' Agents are still using the previous version.'}
                    </p>
                  )}
                  {doc.processing_status === 'failed' &&
                   doc.docling_metadata &&
                   typeof doc.docling_metadata === 'object' &&
                   'duplicate_of' in doc.docling_metadata && (
                    <p className="text-xs text-muted-foreground mt-1">
                      Duplicate of another document
                    </p>
                  )}
                </div>
              </div>
              <div
                className="flex items-center gap-1"
                onClick={(event) => event.stopPropagation()}
              >
                {canEdit(doc) && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setEditingDoc(doc)}
                    disabled={isBusy(doc)}
                    title={isBusy(doc) ? 'Available once processing finishes' : 'Edit'}
                  >
                    <Pencil className="w-4 h-4" />
                  </Button>
                )}
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleDelete(doc.document_uuid, doc.filename)}
                  className="text-destructive hover:text-destructive/90"
                >
                  <Trash2 className="w-4 h-4" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      <DocumentEditor
        doc={editingDoc}
        onClose={() => setEditingDoc(null)}
        onSaved={() => {
          setEditingDoc(null);
          fetchDocuments();
        }}
      />
    </div>
  );
}
