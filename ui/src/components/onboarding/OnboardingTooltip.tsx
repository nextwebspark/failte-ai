'use client';

import { arrow, autoUpdate, flip, offset, shift, useFloating } from '@floating-ui/react-dom';
import { X } from 'lucide-react';
import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

import { Button } from '@/components/ui/button';
import { type TooltipKey, useOnboarding } from '@/context/OnboardingContext';
import { cn } from '@/lib/utils';

interface OnboardingTooltipProps {
    /** Onboarding flag this tooltip is keyed to. Visibility ("not seen yet")
     * and dismissal (mark seen, including when the target itself is clicked)
     * are derived from it, so call sites don't wire up the onboarding
     * context themselves. */
    tooltipKey: TooltipKey;
    targetRef: React.RefObject<HTMLElement | HTMLButtonElement | null>;
    title?: string;
    message: string;
    /** Extra gating beyond "not seen yet" (e.g. panel open, data loaded). */
    enabled?: boolean;
    onNext?: () => void;
    showNext?: boolean;
}

export const OnboardingTooltip = ({
    tooltipKey,
    targetRef,
    title = 'One more thing...',
    message,
    enabled = true,
    onNext,
    showNext = true,
}: OnboardingTooltipProps) => {
    const { hasSeenTooltip, markTooltipSeen } = useOnboarding();
    const arrowRef = useRef<HTMLDivElement>(null);
    const messageId = useId();
    const [mounted, setMounted] = useState(false);

    const isVisible = enabled && !hasSeenTooltip(tooltipKey);
    const dismiss = useCallback(() => markTooltipSeen(tooltipKey), [markTooltipSeen, tooltipKey]);

    const { refs, floatingStyles, middlewareData, placement, isPositioned, elements } = useFloating({
        placement: 'bottom',
        strategy: 'fixed',
        open: isVisible,
        // Tracks the target through scrolling (including nested overflow
        // containers), resizes, and layout shifts.
        whileElementsMounted: autoUpdate,
        middleware: [
            offset(8),
            flip({ padding: 16 }),
            shift({ padding: 16 }),
            arrow({ element: arrowRef }),
        ],
    });

    useEffect(() => {
        setMounted(true);
        return () => setMounted(false);
    }, []);

    // Adopt the target as the floating reference on every render: a ref prop
    // can't trigger effects when its element mounts late or remounts, and
    // setReference bails out when the element is unchanged.
    useEffect(() => {
        refs.setReference(targetRef.current);
    });

    // While pointing at the target: pulsate it, link it to the message for
    // screen readers, and treat a click on it as "seen".
    useEffect(() => {
        const target = elements.reference;
        if (!isVisible || !(target instanceof HTMLElement)) return;

        target.classList.add('onboarding-pulse');
        target.setAttribute('aria-describedby', messageId);
        target.addEventListener('click', dismiss);
        return () => {
            target.classList.remove('onboarding-pulse');
            target.removeAttribute('aria-describedby');
            target.removeEventListener('click', dismiss);
        };
    }, [isVisible, elements.reference, dismiss, messageId]);

    useEffect(() => {
        if (!isVisible) return;

        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') dismiss();
        };
        window.addEventListener('keydown', onKeyDown);
        return () => window.removeEventListener('keydown', onKeyDown);
    }, [isVisible, dismiss]);

    if (!mounted || !isVisible) return null;

    // Actual side after flip(): 'bottom' (below target) or 'top' (above).
    const side = placement.split('-')[0] === 'top' ? 'top' : 'bottom';

    // z-50 is the dialogs' layer: the tooltip shows over the test-rail Sheet it
    // points into (mounted before it), while a dialog opened later is appended
    // after it and covers it.
    const tooltipContent = (
        <div
            ref={refs.setFloating}
            className={`z-50 animate-in fade-in duration-300 ${side === 'bottom' ? 'slide-in-from-top-2' : 'slide-in-from-bottom-2'}`}
            style={{
                ...floatingStyles,
                // Avoid a flash at (0,0) before the first position resolves.
                visibility: isPositioned ? 'visible' : 'hidden',
            }}
        >
            {/* Arrow pointing at the target; floating-ui keeps it aligned even
                when the tooltip body is shifted to stay on-screen. */}
            <div
                ref={arrowRef}
                aria-hidden
                className={cn(
                    "absolute h-3 w-3 rotate-45 border-line bg-panel",
                    side === 'bottom' ? "border-l border-t" : "border-r border-b",
                )}
                style={{
                    left: middlewareData.arrow?.x != null ? `${middlewareData.arrow.x}px` : undefined,
                    ...(side === 'bottom' ? { top: '-6px' } : { bottom: '-6px' }),
                }}
            />

            {/* A floating panel like the app's other popovers, brand only on the action. */}
            <div className="relative max-w-sm rounded-xl border border-line bg-panel p-5 text-foreground shadow-[var(--panel-shadow)]">
                <button
                    onClick={dismiss}
                    className="absolute top-2.5 right-2.5 rounded-md p-1 text-ink-3 transition-colors hover:bg-panel-2 hover:text-foreground"
                    aria-label="Close tooltip"
                >
                    <X className="h-4 w-4" />
                </button>

                <h3 className="mb-1.5 pr-6 text-[15px] font-semibold">{title}</h3>

                <p id={messageId} className="mb-4 pr-4 text-[13.5px] leading-relaxed text-ink-2">
                    {message}
                </p>

                <div className="flex items-center justify-end gap-2">
                    <Button size="sm" variant={showNext ? "outline" : "default"} onClick={dismiss}>
                        Close
                    </Button>

                    {showNext && (
                        <Button
                            size="sm"
                            onClick={() => {
                                onNext?.();
                                dismiss();
                            }}
                        >
                            Next
                        </Button>
                    )}
                </div>
            </div>
        </div>
    );

    // Use portal to render tooltip at document root
    return createPortal(tooltipContent, document.body);
};
