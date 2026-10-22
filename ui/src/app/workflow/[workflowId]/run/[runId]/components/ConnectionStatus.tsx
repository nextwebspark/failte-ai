import { Loader2 } from 'lucide-react';

interface ConnectionStatusProps {
    connectionStatus: 'idle' | 'connecting' | 'connected' | 'failed';
}

export const ConnectionStatus = ({ connectionStatus }: ConnectionStatusProps) => {
    if (connectionStatus === 'idle') return null;

    if (connectionStatus === 'connecting') {
        return (
            <div className="flex items-center justify-center space-x-2 text-sky">
                <Loader2 className="h-5 w-5 animate-spin" />
                <span className="text-sm font-medium">Establishing Connection...</span>
            </div>
        );
    }

    if (connectionStatus === 'connected') {
        return (
            <div className="flex items-center justify-center space-x-2 text-live-text">
                <div className="h-2 w-2 bg-live rounded-full animate-pulse" />
                <span className="text-sm font-medium">Connected</span>
            </div>
        );
    }

    if (connectionStatus === 'failed') {
        return (
            <div className="flex items-center justify-center space-x-2 text-danger">
                <div className="h-2 w-2 bg-danger rounded-full" />
                <span className="text-sm font-medium">Connection Failed</span>
            </div>
        );
    }

    return null;
};
